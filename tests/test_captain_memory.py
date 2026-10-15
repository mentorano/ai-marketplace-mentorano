#!/usr/bin/env python3
"""Tests for captain's project-memory helper, scripts/memory-apply.py (TS1-TS3).

Every test builds temporary git repos and passes the repo's own
plugins/project-memory/scripts/memory.py through --memory-py, and a fixture
installed_plugins.json through --installed-json, so nothing reads the real ~/.claude.

Run:  python3 tests/test_captain_memory.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins" / "captain" / "skills" / "captain" / "scripts" / "memory-apply.py"
PLUGIN = ROOT / "plugins" / "project-memory"
MEMORY_PY = PLUGIN / "scripts" / "memory.py"
GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", *GIT_ID, "-C", str(repo), *args], capture_output=True,
                         text=True, timeout=60)
    if out.returncode:
        raise AssertionError(f"git {args}: {out.stderr}")
    return out.stdout.strip()


def topic(name: str, description: str = "Read when touching the widget code.",
          body: str = "Run the widget tests with WIDGET_DB=1.") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          timeout=120, env={**os.environ, "GIT_AUTHOR_NAME": "t",
                                            "GIT_AUTHOR_EMAIL": "t@example.com",
                                            "GIT_COMMITTER_NAME": "t",
                                            "GIT_COMMITTER_EMAIL": "t@example.com"})


class MemoryRepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(os.path.realpath(self.tmp.name))
        self.repo = self.base / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "app.py").write_text("print(1)\n")
        git(self.repo, "add", "app.py")
        git(self.repo, "commit", "-q", "-m", "init")
        self.installed = self.base / "installed_plugins.json"
        self.register()

    def tearDown(self):
        self.tmp.cleanup()

    def register(self, entries=None):
        if entries is None:
            entries = {"project-memory@m": [{"installPath": str(PLUGIN), "version": "0.1.0"}]}
        self.installed.write_text(json.dumps({"version": 2, "plugins": entries}))

    def init_memory(self, files: dict[str, str] | None = None):
        subprocess.run([sys.executable, str(MEMORY_PY), "init", "--cwd", str(self.repo)],
                       check=True, capture_output=True, timeout=60)
        for name, text in (files or {}).items():
            (self.repo / ".agent-memory" / name).write_text(text)
        git(self.repo, "add", ".agent-memory", ".claude/rules/project-memory")
        git(self.repo, "commit", "-q", "-m", "memory")

    def detect(self, checkout=None) -> str:
        out = run("detect", f"--checkout={checkout or self.repo}",
                  f"--installed-json={self.installed}")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stderr, "")
        lines = out.stdout.splitlines()
        self.assertEqual(len(lines), 1, out.stdout)
        return lines[0]


class DetectTest(MemoryRepoCase):
    """TS1."""

    def test_no_agent_memory_is_off_without_reading_the_registry(self):
        self.installed.write_text("{not json")
        self.assertEqual(self.detect(), "off: no .agent-memory/")

    def test_layout_ok_and_plugin_registered_is_on(self):
        self.init_memory()
        self.assertEqual(self.detect(), f"on {MEMORY_PY}")

    def test_broken_layouts(self):
        self.init_memory()
        link = self.repo / ".claude" / "rules" / "project-memory"
        link.unlink()
        self.assertTrue(self.detect().startswith("off: layout broken: "), self.detect())
        link.symlink_to("../../elsewhere")
        self.assertTrue(self.detect().startswith("off: layout broken: "))

    def test_agent_memory_as_a_symlink_is_broken(self):
        (self.base / "real").mkdir()
        (self.repo / ".agent-memory").symlink_to(self.base / "real")
        self.assertTrue(self.detect().startswith("off: layout broken: "), self.detect())

    def test_registry_shapes_that_mean_not_installed(self):
        self.init_memory()
        off = "off: project-memory plugin not installed"
        stale = self.base / "cache" / "project-memory" / "0.1.0"
        (stale / "scripts").mkdir(parents=True)
        (stale / "scripts" / "memory.py").write_text(MEMORY_PY.read_text())
        for payload in ({"version": 2, "plugins": {"captain@m": [{"installPath": str(stale)}]}},
                        {"version": 2, "plugins": []},
                        {"version": 2},
                        [],
                        {"plugins": {"project-memory@m": {"installPath": str(PLUGIN)}}},
                        {"plugins": {"project-memory@m": ["x"]}},
                        {"plugins": {"project-memory@m": [{"installPath": str(self.base)}]}},
                        {"plugins": {"project-memory@m": [{"version": "1"}]}}):
            with self.subTest(payload=payload):
                self.installed.write_text(json.dumps(payload))
                self.assertEqual(self.detect(), off)
        for raw in ("{not json", "\xff"):
            with self.subTest(raw=raw):
                self.installed.write_bytes(raw.encode("latin-1"))
                self.assertEqual(self.detect(), off)
        self.installed.unlink()
        self.assertEqual(self.detect(), off)
        self.installed.mkdir()  # unreadable as a file
        self.assertEqual(self.detect(), off)

    def test_two_entries_pick_the_higher_version(self):
        self.init_memory()
        old = self.base / "old"
        old.mkdir()  # no scripts/memory.py: chosen only if the version order were wrong
        self.register({"project-memory@a": [{"installPath": str(old), "version": "0.9.0"},
                                            {"installPath": str(PLUGIN), "version": "0.10.0"}]})
        self.assertEqual(self.detect(), f"on {MEMORY_PY}")
        self.register({"project-memory@a": [{"installPath": str(PLUGIN), "version": "0.9.0"},
                                            {"installPath": str(old), "version": "0.10.0"}]})
        self.assertEqual(self.detect(), "off: project-memory plugin not installed")

    def test_not_a_git_repo_is_off(self):
        plain = self.base / "plain"
        (plain / ".agent-memory").mkdir(parents=True)
        self.assertEqual(self.detect(plain), "off: no .agent-memory/")
        self.assertEqual(self.detect(self.base / "missing"), "off: no .agent-memory/")


class CommitTest(MemoryRepoCase):
    """TS2."""

    def setUp(self):
        super().setUp()
        self.init_memory({"old.md": topic("old")})
        git(self.repo, "switch", "-q", "-c", "captain/x")

    def commit(self, files: str, branch: str = "captain/x") -> subprocess.CompletedProcess:
        return run("commit", f"--checkout={self.repo}", f"--branch={branch}",
                   f"--memory-py={MEMORY_PY}", f"--files={files}",
                   "--message=docs(memory): add new.md (MK1)")

    def head(self) -> str:
        return git(self.repo, "rev-parse", "HEAD")

    def test_one_new_and_one_edited_file_commit_alone(self):
        mem = self.repo / ".agent-memory"
        (mem / "new.md").write_text(topic("new"))
        (mem / "old.md").write_text(topic("old", body="Edited rule."))
        (self.repo / "app.py").write_text("print(2)\n")
        before = self.head()
        out = self.commit("new.md,old.md")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertNotEqual(self.head(), before)
        files = git(self.repo, "show", "--name-only", "--format=", "HEAD").splitlines()
        self.assertEqual(sorted(files), [".agent-memory/new.md", ".agent-memory/old.md"])
        self.assertIn("new .agent-memory/new.md", out.stdout)
        self.assertIn("edit .agent-memory/old.md", out.stdout)
        self.assertIn(f"commit {self.head()}", out.stdout)
        self.assertIn("app.py", git(self.repo, "status", "--porcelain"))

    def assert_refused(self, out: subprocess.CompletedProcess, before: str):
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        self.assertEqual(self.head(), before)

    def test_refusals(self):
        mem = self.repo / ".agent-memory"
        for name in ("a.md", "b.md", "c.md"):
            (mem / name).write_text(topic(name[:-3]))
        before = self.head()
        for files in ("README.md", "readme.md", "sub/x.md", "x.py", "..md", "a.md.md"):
            with self.subTest(files=files):
                self.assert_refused(self.commit(files), before)
        (mem / "c.md").unlink()
        self.assert_refused(self.commit("a.md,b.md", branch="main"), before)
        # a stray write by a subagent (FR7): b.md changed but not listed
        out = self.commit("a.md")
        self.assert_refused(out, before)
        self.assertIn("b.md", out.stdout)

    def test_no_file_budget(self):
        # TS2: a captain run has no 1-2 file budget; five files commit together
        mem = self.repo / ".agent-memory"
        names = [f"t{i}.md" for i in range(5)]
        for name in names:
            (mem / name).write_text(topic(name[:-3]))
        out = self.commit(",".join(names))
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertEqual(len(git(self.repo, "show", "--name-only", "--format=", "HEAD").split()), 5)

    def test_empty_file_list_is_refused(self):
        # r1 F2: nothing left to commit is refused, never an empty commit
        before = self.head()
        self.assert_refused(self.commit(""), before)

    def test_violation_in_a_listed_file_fails(self):
        (self.repo / ".agent-memory" / "bad.md").write_text(topic("bad", description="x" * 200))
        before = self.head()
        out = self.commit("bad.md")
        self.assert_refused(out, before)
        self.assertIn("FM4", out.stdout)
        self.assertTrue((self.repo / ".agent-memory" / "bad.md").exists())

    def test_violation_in_an_untouched_file_is_printed_only(self):
        git(self.repo, "switch", "-q", "main")
        (self.repo / ".agent-memory" / "old.md").write_text(topic("old", description=""))
        git(self.repo, "commit", "-q", "-am", "broken old")
        git(self.repo, "switch", "-q", "captain/x")
        git(self.repo, "merge", "-q", "main")
        (self.repo / ".agent-memory" / "new.md").write_text(topic("new"))
        out = self.commit("new.md")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("untouched old.md: FM4", out.stdout)



class RestoreTest(MemoryRepoCase):
    """TS3."""

    def test_restore(self):
        self.init_memory({"old.md": topic("old")})
        mem = self.repo / ".agent-memory"
        (mem / "old.md").write_text(topic("old", body="Changed."))
        (mem / "new.md").write_text(topic("new"))
        (mem / "staged.md").write_text(topic("staged"))
        git(self.repo, "add", ".agent-memory/staged.md")
        out = run("restore", f"--checkout={self.repo}", "--files=old.md,new.md,staged.md")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual((mem / "old.md").read_text(), topic("old"))
        self.assertFalse((mem / "new.md").exists())
        self.assertFalse((mem / "staged.md").exists())
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        for files in ("README.md", "sub/x.md"):
            self.assertEqual(run("restore", f"--checkout={self.repo}",
                                 f"--files={files}").returncode, 1)

    def test_restore_never_deletes_an_ignored_file(self):
        # r1 F1: an owner's git-ignored memory file is not a new file of this run
        self.init_memory()
        (self.repo / ".git" / "info" / "exclude").write_text(".agent-memory/local.md\n")
        local = self.repo / ".agent-memory" / "local.md"
        local.write_text(topic("local"))
        out = run("restore", f"--checkout={self.repo}", "--files=local.md")
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertTrue(local.exists())

    def test_symlinked_memory_dir_is_refused(self):
        # r1 F3: restore and commit never act through a symlinked .agent-memory
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "topic.md").write_text(topic("topic"))
        (self.repo / ".agent-memory").symlink_to(outside)
        out = run("restore", f"--checkout={self.repo}", "--files=topic.md")
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertTrue((outside / "topic.md").exists())
        out = run("commit", f"--checkout={self.repo}", "--branch=main",
                  f"--memory-py={MEMORY_PY}", "--files=topic.md", "--message=x")
        self.assertEqual(out.returncode, 1, out.stdout)


if __name__ == "__main__":
    unittest.main()
