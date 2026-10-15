#!/usr/bin/env python3
"""Tests for the project-memory plugin scripts (memory.py, session_start.py).

Run:  python3 tests/test_project_memory.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "plugins" / "project-memory" / "scripts"
MEMORY = SCRIPTS / "memory.py"
HOOK = SCRIPTS / "session_start.py"
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]


def load_memory():
    spec = importlib.util.spec_from_file_location("pm_memory", MEMORY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mem = load_memory()


def topic(name: str, *, paths: list[str] | None = None, size: int | None = None,
          description: str = "Read before touching the billing code.", body: str = "- a rule\n") -> str:
    head = f"---\nname: {name}\ndescription: {description}\n"
    if paths:
        head += "paths:\n" + "".join(f"  - {p}\n" for p in paths)
    text = head + "---\n\n" + body
    if size is not None:
        pad = size - len(text.encode("utf-8"))
        assert pad >= 0, (name, size)
        text = text + "x" * pad
        assert len(text.encode("utf-8")) == size
    return text


@unittest.skipUnless(shutil.which("git"), "no git")
class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(os.path.realpath(self.tmp.name))
        home = self.base / "home"
        home.mkdir()
        self.env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
                        GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        self.repo = self.base / "repo"
        self.git(self.base, "init", "-q", "-b", "main", str(self.repo))
        (self.repo / "a.txt").write_text("base\n", encoding="utf-8")
        self.git(self.repo, "add", "a.txt")
        self.git(self.repo, "commit", "-q", "-m", "base")
        self.mem = self.repo / ".agent-memory"
        self.link = self.repo / ".claude" / "rules" / "project-memory"

    def tearDown(self):
        for p in self.base.rglob("*"):
            try:
                if not p.is_symlink():
                    p.chmod(0o755)
            except OSError:
                pass
        self.tmp.cleanup()

    def git(self, cwd, *args):
        p = subprocess.run(GIT + list(args), cwd=cwd, capture_output=True, text=True, env=self.env)
        if p.returncode != 0:
            raise RuntimeError(f"git {args} -> {p.stderr}")
        return p.stdout

    def run_memory(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(MEMORY), *args, "--cwd", str(cwd or self.repo)],
                              capture_output=True, text=True, env=self.env)

    def status(self, cwd=None) -> dict:
        p = self.run_memory("status", "--json", cwd=cwd)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def init(self):
        p = self.run_memory("init")
        self.assertEqual(p.returncode, 0, p.stderr)
        return p

    def write(self, name: str, text: str | bytes):
        path = self.mem / name
        if isinstance(text, bytes):
            path.write_bytes(text)
        else:
            path.write_text(text, encoding="utf-8")
        return path


class HealthTest(Case):
    def setUp(self):
        super().setUp()
        self.init()

    def level(self):
        rep = self.status()
        self.assertEqual(rep["layout"], "ok", rep["layout_reason"])
        return rep["level"], rep["reasons"]

    def test_fresh_and_ok(self):
        self.assertEqual(self.level(), ("fresh", []))
        self.write("billing.md", topic("billing"))
        self.assertEqual(self.level(), ("ok", []))

    def test_file_count_edge(self):
        for i in range(29):
            self.write(f"t{i:02}.md", topic(f"t{i:02}"))
        self.assertEqual(self.level()[0], "ok")
        self.write("t29.md", topic("t29"))
        level, reasons = self.level()
        self.assertEqual(level, "due")
        self.assertIn("30 files in project memory (due at 30)", reasons)

    def test_soft_cap_edge(self):
        self.write("big.md", topic("big", paths=["src/**"], size=8192))
        self.assertEqual(self.level()[0], "ok")
        self.write("big.md", topic("big", paths=["src/**"], size=8193))
        level, reasons = self.level()
        self.assertEqual(level, "due")
        self.assertEqual(reasons, ["1 file over the 8192-byte soft cap: big.md"])

    def test_hard_cap_edge(self):
        self.write("huge.md", topic("huge", paths=["src/**"], size=32768))
        self.assertEqual(self.level()[0], "due")
        self.write("huge.md", topic("huge", paths=["src/**"], size=32769))
        level, reasons = self.level()
        self.assertEqual(level, "overdue")
        self.assertIn("1 file over the 32768-byte hard cap: huge.md", reasons)

    def test_always_on_due_edge(self):
        self.write("a.md", topic("a", size=8192))
        self.write("b.md", topic("b", size=8191))
        self.assertEqual(self.level()[0], "ok")
        self.write("b.md", topic("b", size=8192))
        level, reasons = self.level()
        self.assertEqual(level, "due")
        self.assertEqual(reasons, ["16384 bytes of memory load into the context of every session "
                                   "(2 files without paths; due at 16384)"])

    def test_path_scoped_files_are_not_always_on(self):
        self.write("a.md", topic("a", size=8192, paths=["a/**"]))
        self.write("b.md", topic("b", size=8192, paths=["b/**"]))
        rep = self.status()
        self.assertEqual(rep["level"], "ok")
        self.assertEqual(rep["totals"]["always_on_bytes"], 0)

    def test_always_on_overdue_edge(self):
        for n in "abc":
            self.write(f"{n}.md", topic(n, size=8192))
        self.write("d.md", topic("d", size=8191))
        self.assertEqual(self.level()[0], "due")
        self.write("d.md", topic("d", size=8192))
        self.assertEqual(self.level()[0], "overdue")

    def test_violation_makes_due(self):
        self.write("x.md", topic("y"))
        level, reasons = self.level()
        self.assertEqual(level, "due")
        self.assertEqual(reasons, ["1 file with format violations: x.md"])

    def test_readme_excluded(self):
        (self.mem / "README.md").write_text("no frontmatter\n" + "x" * 40000, encoding="utf-8")
        rep = self.status()
        self.assertEqual(rep["level"], "fresh")
        self.assertEqual(rep["files"], [])

    def test_dotfiles_ignored_other_non_md_flagged(self):
        self.write(".DS_Store", b"\x00\x01")
        self.write(".gitkeep", "")
        self.assertEqual(self.level(), ("fresh", []))
        self.write("notes.txt", "x")
        rep = self.status()
        self.assertEqual(rep["level"], "due")
        self.assertEqual(rep["totals"]["files"], 0)
        [rec] = rep["files"]
        self.assertEqual((rec["file"], rec["kind"]), ("notes.txt", "other"))
        self.assertTrue(rec["violations"][0].startswith("FM7"))

    def test_readme_not_a_regular_file_is_fm7(self):
        (self.mem / "README.md").unlink()
        (self.mem / "README.md").mkdir()
        (self.mem / "README.md" / "nested.md").write_text(topic("nested"), encoding="utf-8")
        rep = self.status()
        self.assertEqual(rep["level"], "due")
        self.assertTrue(rep["files"][0]["violations"][0].startswith("FM7"))
        p = self.run_memory("init")
        self.assertEqual(p.returncode, 1)
        self.assertIn("not a regular file", p.stderr)
        (self.mem / "README.md" / "nested.md").unlink()
        (self.mem / "README.md").rmdir()
        (self.mem / "real.txt").write_text("x", encoding="utf-8")
        os.symlink("real.txt", self.mem / "README.md")
        self.assertTrue(any(r["file"] == "README.md" and r["kind"] == "symlink"
                            for r in self.status()["files"]))

    def test_brief(self):
        self.write("a.md", topic("a", size=8193))
        p = self.run_memory("brief")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(p.stdout.startswith("## Memory health\n\nLevel: due."), p.stdout)
        self.assertIn("- 1 file over the 8192-byte soft cap: a.md", p.stdout)
        self.assertIn("now 8193 in 1 file; fewer than 30 files, now 1;", p.stdout)
        self.assertNotIn("counter", p.stdout)
        (self.mem / "a.md").unlink()
        self.assertIn("Level: fresh. No threshold is crossed", self.run_memory("brief").stdout)


class FormatTest(Case):
    def setUp(self):
        super().setUp()
        self.init()

    def violations(self, file: str) -> list[str]:
        rep = self.status()
        for rec in rep["files"]:
            if rec["file"] == file:
                return rec["violations"]
        self.fail(f"{file} not listed: {rep['files']}")

    def assert_rule(self, file: str, code: str):
        found = self.violations(file)
        self.assertTrue(any(v.startswith(code) for v in found), (file, code, found))

    def test_valid_file_has_none(self):
        self.write("ok.md", topic("ok", paths=["src/**"]))
        self.assertEqual(self.violations("ok.md"), [])

    def test_fm1_name_not_stem(self):
        self.write("alpha.md", topic("beta"))
        self.assert_rule("alpha.md", "FM1")

    def test_fm1_no_frontmatter(self):
        self.write("plain.md", "just text\n")
        self.assert_rule("plain.md", "FM1")

    def test_fm2_bad_name(self):
        self.write("bad name.md", topic("bad name"))
        self.assert_rule("bad name.md", "FM2")
        self.write(".hidden.md", topic(".hidden"))
        self.assert_rule(".hidden.md", "FM2")

    def test_fm3_case_twins(self):
        self.write("Deploy.md", topic("Deploy"))
        self.write("deploy.md", topic("deploy"))
        names = {r["file"] for r in self.status()["files"]}
        if len(names) == 2:
            self.assert_rule("Deploy.md", "FM3")
            self.assert_rule("deploy.md", "FM3")
        # A case-insensitive file system cannot hold both files: check the rule itself.
        recs = [{"file": f, "kind": "file", "violations": []} for f in ("Deploy.md", "deploy.md", "x.md")]
        mem.mark_case_twins(recs)
        readme_twin = [{"file": "readme.md", "kind": "file", "violations": []}]
        mem.mark_case_twins(readme_twin)
        self.assertTrue(readme_twin[0]["violations"][0].startswith("FM3"), readme_twin)
        self.assertTrue(recs[0]["violations"][0].startswith("FM3"))
        self.assertTrue(recs[1]["violations"][0].startswith("FM3"))
        self.assertEqual(recs[2]["violations"], [])

    def test_fm4_description(self):
        self.write("long.md", topic("long", description="w" * 161))
        self.assert_rule("long.md", "FM4")
        self.write("edge.md", topic("edge", description="w" * 160))
        self.assertEqual(self.violations("edge.md"), [])
        self.write("multi.md", "---\nname: multi\ndescription: >\n  one\n  two\n---\nbody\n")
        self.assert_rule("multi.md", "FM4")
        self.write("quoted.md", topic("quoted", description="'Read ''billing'' " + "x" * 160 + "'"))
        self.assert_rule("quoted.md", "FM4")
        self.write("nodesc.md", "---\nname: nodesc\n---\nbody\n")
        self.assert_rule("nodesc.md", "FM4")

    def test_fm5_empty_paths(self):
        self.write("p.md", "---\nname: p\ndescription: Read first.\npaths:\n---\nbody\n")
        self.assert_rule("p.md", "FM5")

    def test_fm6_source_updated(self):
        self.write("s.md", "---\nname: s\ndescription: Read first.\nsource: run-1\n"
                           "updated: 2026-01-01\nowner: kept\n---\nbody\n")
        found = self.violations("s.md")
        self.assertEqual(sum(v.startswith("FM6") for v in found), 2, found)

    def test_fm7_subdirectory_and_symlink(self):
        (self.mem / "nested").mkdir()
        (self.mem / "nested" / "x.md").write_text(topic("x"), encoding="utf-8")
        self.write("real.md", topic("real"))
        os.symlink("real.md", self.mem / "alias.md")
        self.assert_rule("nested", "FM7")
        self.assert_rule("alias.md", "FM7")
        rep = self.status()
        self.assertEqual(rep["totals"]["files"], 1)
        self.assertEqual(rep["level"], "due")

    def test_fm7_alone_is_due_not_fresh(self):
        (self.mem / "nested").mkdir()
        self.assertEqual(self.status()["level"], "due")

    def test_fm8_empty_and_frontmatter_only(self):
        self.write("empty.md", "  \n")
        self.write("fmonly.md", "---\nname: fmonly\ndescription: Read first.\n---\n\n")
        self.assert_rule("empty.md", "FM8")
        self.assert_rule("fmonly.md", "FM8")

    def test_broken_files_are_violations_not_crashes(self):
        self.write("binary.md", b"---\nname: binary\n\xff\xfe\n---\n")
        self.write("locked.md", topic("locked"))
        os.chmod(self.mem / "locked.md", 0)
        self.write("garbage.md", "---\nname: garbage\n: : :\n[[[\ndescription: x\n---\nbody\n")
        p = self.run_memory("status")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(any(v.startswith("read error") for v in self.violations("binary.md")))
        if not os.access(self.mem / "locked.md", os.R_OK):
            self.assertTrue(any(v.startswith("read error") for v in self.violations("locked.md")))
        self.assertTrue(any("not `key: value`" in v for v in self.violations("garbage.md")))
        self.assertEqual(self.status()["level"], "due")


class PathsParsingTest(unittest.TestCase):
    def parse(self, text):
        fields, _, problems = mem.parse_frontmatter(text)
        self.assertEqual(problems, [])
        return mem.paths_of(fields)

    def test_yaml_list(self):
        self.assertEqual(self.parse("---\nname: a\npaths:\n  - src/a.ts\n  - 'lib/**'\n---\nb\n"),
                         ["src/a.ts", "lib/**"])

    def test_yaml_list_without_indent(self):
        self.assertEqual(self.parse("---\npaths:\n- src/a.ts\n- \"lib/**\"\n---\nb\n"),
                         ["src/a.ts", "lib/**"])

    def test_comma_separated(self):
        self.assertEqual(self.parse("---\npaths: docs/x.md, cfg/*.json\n---\nb\n"),
                         ["docs/x.md", "cfg/*.json"])

    def test_flow_list(self):
        self.assertEqual(self.parse("---\npaths: [a/*.py, \"b/**\"]\n---\nb\n"), ["a/*.py", "b/**"])

    def test_missing(self):
        self.assertEqual(self.parse("---\nname: a\n---\nb\n"), [])
        self.assertEqual(mem.paths_of(None), [])

    def test_inline_comment_and_quotes(self):
        fields, _, problems = mem.parse_frontmatter(
            "---\nname: a # topic\ndescription: \"Read # this\"  # why\npaths:\n  - src/** # all\n---\nb\n")
        self.assertEqual(problems, [])
        self.assertEqual((fields["name"], fields["description"]), ("a", "Read # this"))
        self.assertEqual(mem.paths_of(fields), ["src/**"])

    def test_escaped_quotes_keep_the_whole_value(self):
        long = "x" * 160
        fields, _, problems = mem.parse_frontmatter(
            f"---\nname: 'it''s'\ndescription: 'Read ''billing'' {long}'\n"
            f"paths: \"a \\\"b\\\" c\"\n---\nb\n")
        self.assertEqual(problems, [])
        self.assertEqual(fields["name"], "it's")
        self.assertEqual(fields["description"], f"Read 'billing' {long}")
        self.assertEqual(fields["paths"], 'a "b" c')

    def test_text_after_closing_quote_is_a_problem(self):
        _, _, problems = mem.parse_frontmatter("---\nname: 'a' b\n---\nb\n")
        self.assertEqual(len(problems), 1)
        self.assertIn("after the closing quote", problems[0])

    def test_unterminated_quote_and_unclosed_list_are_problems(self):
        _, _, problems = mem.parse_frontmatter(
            "---\nname: a\ndescription: \"unterminated\npaths: [\n---\nb\n")
        self.assertEqual(len(problems), 2, problems)
        self.assertIn("unterminated quote", problems[0])
        self.assertIn("unclosed", problems[1])

    def test_crlf_and_bom(self):
        self.assertEqual(self.parse("﻿---\r\npaths:\r\n  - x/**\r\n---\r\nb\r\n"), ["x/**"])


class LayoutTest(Case):
    def test_ok(self):
        self.init()
        rep = self.status()
        self.assertEqual((rep["layout"], rep["layout_reason"]), ("ok", None))

    def test_absent(self):
        rep = self.status()
        self.assertEqual(rep["layout"], "absent")
        self.assertIsNone(rep["level"])

    def test_not_a_git_repo(self):
        plain = self.base / "plain"
        plain.mkdir()
        rep = self.status(cwd=plain)
        self.assertEqual((rep["layout"], rep["layout_reason"]), ("absent", "not a git repository"))
        rep = self.status(cwd=self.base / "missing-dir")
        self.assertEqual(rep["layout"], "absent")

    def test_missing_link(self):
        self.init()
        self.link.unlink()
        rep = self.status()
        self.assertEqual(rep["layout"], "broken")
        self.assertIn("missing", rep["layout_reason"])

    def test_dangling_link(self):
        self.init()
        self.link.unlink()
        os.symlink("../../.agent-memory-old", self.link)
        rep = self.status()
        self.assertEqual(rep["layout"], "broken")
        self.assertIn("dangling", rep["layout_reason"])

    def test_wrong_target(self):
        self.init()
        (self.repo / "docs").mkdir()
        self.link.unlink()
        os.symlink("../../docs", self.link)
        rep = self.status()
        self.assertEqual(rep["layout"], "broken")
        self.assertIn("points to ../../docs", rep["layout_reason"])

    def test_link_is_a_directory(self):
        self.mem.mkdir()
        self.link.mkdir(parents=True)
        rep = self.status()
        self.assertEqual(rep["layout"], "broken")
        self.assertIn("not a symlink", rep["layout_reason"])

    def test_subdirectory_cwd_is_broken(self):
        self.init()
        sub = self.repo / "src" / "deep"
        sub.mkdir(parents=True)
        rep = self.status(cwd=sub)
        self.assertEqual(rep["layout"], "broken")
        self.assertIn("path-scoped memory rules do not load", rep["layout_reason"])
        self.assertEqual(rep["repo_root"], str(self.repo))
        self.assertEqual(rep["level"], "fresh")

    def test_worktree_root_is_ok(self):
        self.init()
        (self.mem / "rule.md").write_text(topic("rule"), encoding="utf-8")
        self.git(self.repo, "add", ".agent-memory", ".claude/rules/project-memory")
        self.git(self.repo, "commit", "-q", "-m", "memory")
        wt = self.repo / ".claude" / "worktrees" / "w1"
        self.git(self.repo, "worktree", "add", "-q", "-b", "w1", str(wt))
        rep = self.status(cwd=wt)
        self.assertEqual((rep["layout"], rep["layout_reason"]), ("ok", None))
        self.assertEqual(rep["memory_dir"], str(wt / ".agent-memory"))
        self.assertEqual(rep["totals"]["files"], 1)


class InitTest(Case):
    def head(self):
        return self.git(self.repo, "rev-parse", "HEAD").strip()

    def test_fresh_repo(self):
        before = self.head()
        out = self.init().stdout
        self.assertTrue((self.mem / "README.md").is_file())
        self.assertEqual(os.readlink(self.link), "../../.agent-memory")
        self.assertIn("created .agent-memory/README.md", out)
        self.assertIn(f"git -C {self.repo} add .agent-memory/README.md .claude/rules/project-memory",
                      out)
        self.assertNotIn("ignores", out)
        self.assertEqual(self.head(), before)
        self.assertEqual(self.status()["layout"], "ok")

    def test_rerun_is_idempotent(self):
        self.init()
        (self.mem / "README.md").write_text("edited by the team\n", encoding="utf-8")
        out = self.init().stdout
        self.assertNotIn("created", out)
        self.assertIn("kept .claude/rules/project-memory", out)
        self.assertEqual((self.mem / "README.md").read_text(encoding="utf-8"), "edited by the team\n")

    def test_partial_install_repaired(self):
        self.init()
        (self.mem / "README.md").unlink()
        self.link.unlink()
        out = self.init().stdout
        self.assertIn("kept .agent-memory/", out)
        self.assertIn("created .agent-memory/README.md", out)
        self.assertIn("created .claude/rules/project-memory", out)
        self.assertEqual(self.status()["layout"], "ok")

    def test_foreign_file_refused(self):
        self.link.parent.mkdir(parents=True)
        self.link.write_text("mine\n", encoding="utf-8")
        p = self.run_memory("init")
        self.assertEqual(p.returncode, 1)
        self.assertIn("refusing", p.stderr)
        self.assertEqual(self.link.read_text(encoding="utf-8"), "mine\n")
        self.assertFalse(self.mem.exists())

    def test_foreign_symlink_and_directory_refused(self):
        self.link.parent.mkdir(parents=True)
        os.symlink("../../elsewhere", self.link)
        self.assertEqual(self.run_memory("init").returncode, 1)
        self.link.unlink()
        self.link.mkdir()
        self.assertEqual(self.run_memory("init").returncode, 1)

    def test_ignored_claude_reported_with_negation(self):
        (self.repo / ".gitignore").write_text(".claude/rules/project-memory\n", encoding="utf-8")
        out = self.init().stdout
        self.assertIn("add this line to .gitignore: !.claude/rules/project-memory", out)

    def test_ignored_whole_claude_dir_reported_with_negation(self):
        (self.repo / ".gitignore").write_text(".claude/\n", encoding="utf-8")
        out = self.init().stdout
        self.assertIn("add this line to .gitignore: !.claude/rules/project-memory", out)
        self.assertIn("parent directory is excluded", out)

    def test_old_readme_with_budget_kept_and_not_broken(self):
        # A repo initialised before BYU1 keeps its README; init and status do not flag it.
        self.mem.mkdir()
        old = ("# Project memory\n\n**Budget and format.** At most 1-2 files per session; "
               "prefer editing an existing file.\n")
        (self.mem / "README.md").write_text(old, encoding="utf-8")
        for _ in range(2):
            out = self.init().stdout
            self.assertIn("kept .agent-memory/README.md", out)
            self.assertEqual((self.mem / "README.md").read_text(encoding="utf-8"), old)
        rep = self.status()
        self.assertEqual(rep["layout"], "ok", rep["layout_reason"])
        self.assertEqual(rep["level"], "fresh")
        self.assertEqual(rep["reasons"], [])

    def test_from_subdirectory_targets_root(self):
        sub = self.repo / "src"
        sub.mkdir()
        p = self.run_memory("init", cwd=sub)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((self.mem / "README.md").is_file())
        self.assertFalse((sub / ".agent-memory").exists())

    def test_not_a_repo(self):
        plain = self.base / "plain"
        plain.mkdir()
        self.assertEqual(self.run_memory("init", cwd=plain).returncode, 1)


class ReadmeTextTest(unittest.TestCase):
    def test_under_budget(self):
        self.assertLess(len(mem.README_TEXT.encode("utf-8")), 1500)

    def test_every_rule_is_present(self):
        text = mem.README_TEXT
        for phrase in ("Only the main session writes here", "A subagent never writes",
                       "except the defragment subagent of `/project-memory:memory-defrag`",
                       "Memory candidate: <one line>",
                       ".claude/rules/project-memory/", "never write there", "(a) cost you a cycle",
                       "(b) contradicted", "next month", "a trap", "verification recipe",
                       "invariant", "settled user decision", "defect class", "session summaries",
                       "restatements of code", "one-off task facts", "CLAUDE.md / CONTRIBUTING / README",
                       "secrets", "facts about the user (auto memory)", "unverified guesses",
                       "**Format.** Prefer editing", "`name` (= filename stem)",
                       "`description` (one line, max 160", "*when*", "`paths` (YAML list",
                       "~8 KB", "delete it", "Tell the user", "never overrides the user or CLAUDE.md"):
            self.assertIn(phrase, text)

    def test_no_per_session_file_budget(self):
        # Owner decision BYU1: no count limit on memory files per session.
        text = mem.README_TEXT
        for phrase in ("1-2", "1–2", "per session", "Budget", "At most"):
            self.assertNotIn(phrase, text)


class PruneTest(Case):
    def setUp(self):
        super().setUp()
        self.init()
        self.write("a.md", topic("a"))
        self.write("b.md", "")
        self.write("c.md", topic("c"))
        self.write("keep.md", topic("keep"))
        self.before = self.status()
        self.before_file = self.base / "before.json"
        self.before_file.write_text(json.dumps(self.before), encoding="utf-8")

    def test_deletes_only_before_listed_files_now_empty(self):
        self.write("a.md", "\n  \n")
        self.write("c.md", "---\nname: c\ndescription: Read first.\n---\n")
        self.write("new.md", "")
        (self.mem / "README.md").write_text("", encoding="utf-8")
        p = self.run_memory("prune", "--before", str(self.before_file))
        self.assertEqual(p.returncode, 0, p.stderr)
        left = sorted(x.name for x in self.mem.iterdir())
        self.assertEqual(left, ["README.md", "b.md", "c.md", "keep.md", "new.md"])
        self.assertIn("deleted .agent-memory/a.md", p.stdout)
        self.assertIn("left for the user: .agent-memory/c.md", p.stdout)

    def test_inline_json_and_nothing_to_prune(self):
        p = self.run_memory("prune", "--before", json.dumps(self.before))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("nothing to prune", p.stdout)

    def test_unsafe_names_in_before_are_ignored(self):
        outside = self.repo / "victim.md"
        outside.write_text("", encoding="utf-8")
        forged = {"memory_dir": str(self.mem),
                  "files": [{"file": "../victim.md", "kind": "file", "has_content": True},
                            {"file": "README.md", "kind": "file", "has_content": True},
                            {"file": "readme.md", "kind": "file", "has_content": True}]}
        (self.mem / "README.md").write_text(" ", encoding="utf-8")
        p = self.run_memory("prune", "--before", json.dumps(forged))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(outside.exists())
        self.assertTrue((self.mem / "README.md").exists())

    def test_listing_from_another_repo_refused(self):
        other = self.base / "other"
        self.git(self.base, "init", "-q", "-b", "main", str(other))
        self.assertEqual(self.run_memory("init", cwd=other).returncode, 0)
        (other / ".agent-memory" / "a.md").write_text("", encoding="utf-8")
        p = self.run_memory("prune", "--before", str(self.before_file), cwd=other)
        self.assertEqual(p.returncode, 1)
        self.assertIn("not", p.stderr)
        self.assertTrue((other / ".agent-memory" / "a.md").exists())
        no_dir = {"files": self.before["files"]}
        self.assertEqual(self.run_memory("prune", "--before", json.dumps(no_dir)).returncode, 1)

    def test_unicode_whitespace_counts_as_empty(self):
        self.write("a.md", "\u00a0\n")
        p = self.run_memory("prune", "--before", str(self.before_file))
        self.assertIn("deleted .agent-memory/a.md", p.stdout)
        self.assertFalse((self.mem / "a.md").exists())

    def test_undecodable_file_kept(self):
        self.write("a.md", b"\xff\xfe")
        self.run_memory("prune", "--before", str(self.before_file))
        self.assertTrue((self.mem / "a.md").exists())

    def test_symlink_never_deleted(self):
        self.write("a.md", "")
        (self.mem / "a.md").unlink()
        (self.mem / "empty-target").write_text("", encoding="utf-8")
        os.symlink("empty-target", self.mem / "a.md")
        self.run_memory("prune", "--before", str(self.before_file))
        self.assertTrue((self.mem / "a.md").is_symlink())

    def test_bad_before(self):
        p = self.run_memory("prune", "--before", str(self.base / "nope.json"))
        self.assertEqual(p.returncode, 1)
        p = self.run_memory("prune", "--before", "{not json")
        self.assertEqual(p.returncode, 1)


class SessionStartTest(Case):
    def hook(self, payload, raw: str | None = None):
        stdin = raw if raw is not None else json.dumps(payload)
        return subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True,
                              text=True, env=self.env)

    def context(self, p) -> str:
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(set(out), {"hookSpecificOutput"})
        self.assertEqual(set(out["hookSpecificOutput"]), {"hookEventName", "additionalContext"})
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        text = out["hookSpecificOutput"]["additionalContext"]
        self.assertLessEqual(len(text), 1000)
        self.assertNotIn("\n", text)
        return text

    def payload(self, cwd=None):
        return {"session_id": "s", "hook_event_name": "SessionStart", "source": "startup",
                "cwd": str(cwd or self.repo)}

    def test_silent_when_absent(self):
        p = self.hook(self.payload())
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    def test_silent_when_ok_and_fresh(self):
        self.init()
        self.assertEqual(self.hook(self.payload()).stdout, "")
        self.write("a.md", topic("a"))
        self.assertEqual(self.hook(self.payload()).stdout, "")

    def test_broken_line(self):
        self.init()
        sub = self.repo / "src"
        sub.mkdir()
        text = self.context(self.hook(self.payload(sub)))
        self.assertTrue(text.startswith("project memory is not fully loading in this session: "))
        self.assertIn("path-scoped memory rules do not load", text)
        self.assertTrue(text.endswith("; start the session at the repo root, or run "
                                      "`/project-memory:memory-init` to repair"))

    def test_due_line(self):
        self.init()
        self.write("a.md", topic("a", size=9000))
        text = self.context(self.hook(self.payload()))
        self.assertEqual(text, "project memory health is due: 1 file over the 8192-byte soft cap: "
                               "a.md. Suggest `/project-memory:memory-defrag` to the user once; "
                               "do not run it yourself.")

    def test_overdue_line_and_cap_with_long_names(self):
        self.init()
        for c in "abcd":
            name = c * 200
            self.write(f"{name}.md", topic(name, size=33000))
        text = self.context(self.hook(self.payload()))
        self.assertTrue(text.startswith("project memory health is overdue: "))
        self.assertTrue(text.endswith("do not run it yourself."))
        self.assertEqual(len(text), 1000)

    def test_cap_with_long_cwd_path(self):
        self.init()
        sub = self.repo
        for i in range(8):
            sub = sub / (f"d{i}" + "x" * 90)
        sub.mkdir(parents=True)
        p = self.hook(self.payload(sub))
        self.context(p)
        long_wrong = self.repo / ".claude" / "rules"
        self.link.unlink()
        os.symlink("../../" + "/".join(["y" * 200] * 4), self.link)
        text = self.context(self.hook(self.payload()))
        self.assertTrue(text.endswith("to repair"))
        self.assertTrue(long_wrong.exists())

    def test_control_characters_never_break_the_line(self):
        rep = {"layout": "ok", "level": "due", "reasons": ["1 file with format violations: bad\nname.md\u2028x"]}
        sys.path.insert(0, str(SCRIPTS))
        try:
            import session_start
        finally:
            sys.path.remove(str(SCRIPTS))
        text = session_start.message(rep)
        self.assertNotIn("\n", text)
        self.assertNotIn("\u2028", text)
        self.assertIn("bad name.md x", text)
        bad = "bad\nname"
        self.init()
        self.write(f"{bad}.md", topic("x"))
        self.context(self.hook(self.payload()))

    def test_malformed_input_is_silent(self):
        self.init()
        self.write("a.md", topic("a", size=9000))
        for raw in ("", "not json", "[1, 2]", "{}", '{"cwd": 5}', '{"cwd": ""}'):
            p = self.hook(None, raw=raw)
            self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""), raw)
        p = self.hook({"cwd": str(self.base / "gone")})
        self.assertEqual((p.returncode, p.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
