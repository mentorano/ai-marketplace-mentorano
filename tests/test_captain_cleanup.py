#!/usr/bin/env python3
"""Tests for the captain run manifest (record-created.py) and cleanup (cleanup-run.py)."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "plugins" / "captain" / "skills" / "captain" / "scripts"
RECORD = SCRIPTS / "record-created.py"
CLEANUP = SCRIPTS / "cleanup-run.py"
QUEUE_MD = ROOT / "plugins" / "captain" / "skills" / "captain" / "reference" / "queue.md"
RUN_ID = "20261013-150000"
FEATURE = "captain/20261013-demo"
SUPACODE_LOCK = '{"owner":"supacode"}'

RUN_MD = """# captain run {run_id}
- Repo: {repo}   Start branch: main   Default branch: main
- Feature branch: {feature}, based on origin/main
- Run checkout: {checkout}   Writers: per-writer worktrees
- Base branch (R10): none: feature branch only

## Tasks
| ID | Task | Agent | State |
|---|---|---|---|
| ZD1 | demo | w-running | running |

## Agents
| Name | agentId | Task id (TaskStop) | Task | Checkout (abs) | Model | Limit | Period start | Minutes | output_file | notified | Context |
|---|---|---|---|---|---|---|---|---|---|---|---|
{rows}| w-running | a2 | t2 | demo | {running} | opus | 15m | 14:05 | 0 | /y | no | 0% keep |
"""
ROW = "| w-{name} | a | t | demo | {path} | opus | 15m | 14:05 | 12 | /x | yes | 9% keep |\n"


@unittest.skipUnless(shutil.which("git"), "no git")
class CleanupCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(self.tmp.name))
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com",
                        CAPTAIN_STATE_DIR=str(base / "sessions"))
        self.repo, self.origin = base / "repo", base / "origin.git"
        self.trees = self.repo / ".claude" / "worktrees"
        self.run_dir = base / "tmp" / "captain" / RUN_ID
        self.run_dir.mkdir(parents=True)
        (base / "sessions").mkdir()
        self.git(base, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(base, "init", "-q", "-b", "main", str(self.repo))
        self.commit(self.repo, "README", "base\n")
        self.git(self.repo, "remote", "add", "origin", str(self.origin))
        self.git(self.repo, "push", "-q", "origin", "main")
        self.git(self.repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.git(self.repo, "branch", "--no-track", FEATURE, "origin/main")
        self.checkout = self.add("captain-run", FEATURE, new=False)
        self.wt = {name: self.add(name, f"captain/w-{name}")
                   for name in ("clean", "dirty", "unmerged", "running", "cwd", "supacode", "other-lock",
                                "nested-lock", "no-row")}
        # clean: a commit merged into the feature branch
        self.commit(self.wt["clean"], "clean.txt", "x\n")
        self.git(self.checkout, "merge", "-q", "--ff-only", "captain/w-clean")
        self.commit(self.wt["unmerged"], "unmerged.txt", "x\n")
        (self.wt["dirty"] / "scratch.txt").write_text("untracked\n", encoding="utf-8")
        self.git(self.repo, "worktree", "lock", "--reason", SUPACODE_LOCK, str(self.wt["supacode"]))
        self.git(self.repo, "worktree", "lock", "--reason", "in use by an editor",
                 str(self.wt["other-lock"]))
        self.git(self.repo, "worktree", "lock", "--reason",
                 '{"owner":"editor","previous":{"owner":"supacode"}}', str(self.wt["nested-lock"]))
        (base / "sessions" / "session-1").write_text(
            json.dumps({"since": 1, "cwd": str(self.wt["cwd"] / "sub")}) + "\n", encoding="utf-8")
        (self.run_dir / "run.md").write_text(RUN_MD.format(
            run_id=RUN_ID, repo=self.repo, feature=FEATURE, checkout=self.checkout,
            running=self.wt["running"],
            rows="".join(ROW.format(name=name, path=path) for name, path in self.wt.items()
                         if name not in ("running", "no-row"))), encoding="utf-8")
        for path in (self.checkout, *self.wt.values()):
            self.script(RECORD, f"--run-dir={self.run_dir}", f"--worktree={path}", check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, cwd: Path, *args: str) -> str:
        result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                                env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def commit(self, cwd: Path, name: str, text: str) -> None:
        (cwd / name).write_text(text, encoding="utf-8")
        self.git(cwd, "add", name)
        self.git(cwd, "commit", "-q", "-m", name)

    def add(self, name: str, branch: str, new: bool = True) -> Path:
        path = self.trees / name
        self.git(self.repo, "worktree", "add", "-q", *(["-b", branch] if new else []), str(path),
                 FEATURE if new else branch)
        return path

    def script(self, path: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
        result = subprocess.run([sys.executable, str(path), *args], capture_output=True,
                                text=True, env=self.env, cwd=str(ROOT))
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def snapshot(self) -> tuple[str, str]:
        return (self.git(self.repo, "worktree", "list", "--porcelain"),
                self.git(self.repo, "branch", "--list"))

    def lines(self, *extra: str) -> dict[str, str]:
        result = self.script(CLEANUP, f"--run-dir={self.run_dir}", *extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        found = {}
        for line in result.stdout.splitlines():
            path = line.split()[1]
            found[Path(path).name] = line
        return found


class RecordCreatedTest(CleanupCase):
    def test_one_json_line_per_worktree_with_the_fields_from_git(self):
        entries = [json.loads(line) for line in
                   (self.run_dir / "created.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(entries), 1 + len(self.wt))
        first = entries[0]
        self.assertEqual(set(first), {"run_id", "common_dir", "worktree", "branch", "sha", "created"})
        self.assertEqual(first["run_id"], RUN_ID)
        self.assertEqual(first["common_dir"], os.path.realpath(self.repo / ".git"))
        self.assertEqual(first["worktree"], str(self.checkout))
        self.assertEqual(first["branch"], FEATURE)
        self.assertEqual(first["sha"], self.git(self.checkout, "rev-parse", "HEAD").strip())

    def test_refuses_the_main_worktree_and_a_detached_head(self):
        before = (self.run_dir / "created.jsonl").read_text(encoding="utf-8")
        result = self.script(RECORD, f"--run-dir={self.run_dir}", f"--worktree={self.repo}")
        self.assertEqual(result.returncode, 2)
        self.assertIn("main worktree", result.stderr)
        self.git(self.wt["clean"], "checkout", "-q", "--detach")
        result = self.script(RECORD, f"--run-dir={self.run_dir}", f"--worktree={self.wt['clean']}")
        self.assertEqual(result.returncode, 2)
        self.assertIn("detached HEAD", result.stderr)
        self.assertEqual((self.run_dir / "created.jsonl").read_text(encoding="utf-8"), before)


class CleanupRunTest(CleanupCase):
    def index_bytes(self) -> dict[str, bytes]:
        return {str(path): path.read_bytes() for path in (self.repo / ".git").rglob("index")}

    def test_dry_run_changes_nothing(self):
        for path in self.wt.values():  # make every index stat cache stale
            os.utime(path / "README", (1, 1))
        before, index = self.snapshot(), self.index_bytes()
        found = self.lines("--dry-run")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.index_bytes(), index)
        self.assertTrue(found["clean"].startswith("WOULD-REMOVE "), found["clean"])
        self.assertTrue(found["supacode"].startswith("WOULD-REMOVE "), found["supacode"])

    def test_removes_only_safe_items_and_says_why_it_skips_the_others(self):
        found = self.lines()
        self.assertEqual(set(found), {"captain-run", *self.wt})
        expected_skip = {
            "dirty": "tracked or untracked changes",
            "unmerged": "not merged",
            "running": "writer still running",
            "cwd": "working directory of a main session",
            "other-lock": "locked by another tool",
            "nested-lock": "locked by another tool",
            "no-row": "no agent row",
            "captain-run": "run checkout while captain mode is on",
        }
        for name, reason in expected_skip.items():
            self.assertTrue(found[name].startswith("SKIPPED "), found[name])
            self.assertIn(reason, found[name])
            self.assertTrue((self.trees / name).is_dir(), name)
        for name in ("clean", "supacode"):
            self.assertTrue(found[name].startswith("REMOVED "), found[name])
            self.assertFalse((self.trees / name).exists(), name)
        branches = self.git(self.repo, "branch", "--list")
        self.assertNotIn("captain/w-clean", branches)
        self.assertNotIn("captain/w-supacode", branches)
        self.assertIn("captain/w-unmerged", branches)
        self.assertIn(FEATURE, branches)
        self.assertIn("locked in use by an editor", self.git(self.repo, "worktree", "list", "--porcelain"))

    def test_run_checkout_goes_last_once_captain_mode_is_off(self):
        for marker in Path(self.env["CAPTAIN_STATE_DIR"]).iterdir():
            marker.unlink()
        (self.run_dir / "run.md").write_text(
            (self.run_dir / "run.md").read_text(encoding="utf-8").replace("| no |", "| yes |"),
            encoding="utf-8")
        self.git(self.repo, "merge", "-q", "--ff-only", FEATURE)
        self.git(self.repo, "push", "-q", "origin", "main")
        found = self.lines()
        self.assertTrue(found["captain-run"].startswith("REMOVED "), found["captain-run"])
        self.assertTrue(found["running"].startswith("REMOVED "), found["running"])
        self.assertTrue(found["cwd"].startswith("REMOVED "), found["cwd"])
        self.assertNotIn(FEATURE, self.git(self.repo, "branch", "--list"))

    def test_branch_merged_into_the_default_branch_only_is_deleted_from_the_main_worktree(self):
        # merged into main and origin/main, not into the feature branch the run checkout holds
        self.git(self.repo, "merge", "-q", "--ff-only", "captain/w-unmerged")
        self.git(self.repo, "push", "-q", "origin", "main")
        found = self.lines()
        self.assertTrue(found["unmerged"].startswith("REMOVED "), found["unmerged"])
        self.assertFalse((self.trees / "unmerged").exists())
        self.assertNotIn("captain/w-unmerged", self.git(self.repo, "branch", "--list"))

    def test_merged_branch_stays_when_no_checkout_has_it_in_head(self):
        self.git(self.repo, "push", "-q", "origin", "captain/w-unmerged:main")
        self.git(self.repo, "fetch", "-q", "origin")
        found = self.lines()
        self.assertTrue(found["unmerged"].startswith("SKIPPED "), found["unmerged"])
        self.assertIn("merged into origin/main but no checkout", found["unmerged"])
        self.assertIn("captain/w-unmerged", self.git(self.repo, "branch", "--list"))

    def test_second_run_reports_already_removed(self):
        self.lines()
        found = self.lines()
        self.assertIn("already removed", found["clean"])

    def test_no_agents_table_skips_everything(self):
        text = (self.run_dir / "run.md").read_text(encoding="utf-8")
        (self.run_dir / "run.md").write_text(text.split("## Agents")[0], encoding="utf-8")
        found = self.lines()
        self.assertTrue(all(line.startswith("SKIPPED ") for line in found.values()), found)
        self.assertIn("no readable ## Agents table", found["clean"])
        self.assertIn("no readable ## Agents table", found["supacode"])
        self.assertTrue((self.trees / "clean").is_dir())

    def test_missing_run_md_is_bad_input(self):
        (self.run_dir / "run.md").unlink()
        result = self.script(CLEANUP, f"--run-dir={self.run_dir}")
        self.assertEqual(result.returncode, 2)


def load_cleanup():
    spec = importlib.util.spec_from_file_location("cleanup_run", CLEANUP)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


class RunMdTemplateTest(unittest.TestCase):
    """cleanup-run.py parses run.md as reference/queue.md tells the captain to write it."""

    def template(self) -> str:
        text = QUEUE_MD.read_text(encoding="utf-8")
        match = re.search(r"## run\.md\n\n```markdown\n(.*?)\n```", text, re.S)
        self.assertTrue(match, "queue.md has no run.md template")
        return match.group(1)

    def test_parser_reads_the_fields_and_the_agents_table_of_the_template(self):
        cleanup = load_cleanup()
        text = self.template()
        for label in ("Feature branch", "Run checkout", "Default branch", "Base branch (R10)"):
            self.assertIsNotNone(cleanup.field_value(text, label), label)
        rows = cleanup.table(text, "Agents")
        self.assertTrue(rows, "no ## Agents table rows")
        self.assertIn("Checkout (abs)", rows[0])
        self.assertIn("notified", rows[0])
        filled = (text.replace("<abs>", "/abs/w-auth")
                  .replace("captain/<YYYYMMDD>-<slug>, based", "captain/20261013-x, based"))
        run = cleanup.read_run(filled)
        self.assertEqual(run.feature, "captain/20261013-x")
        self.assertIn(os.path.realpath("/abs/w-auth"), run.running)


if __name__ == "__main__":
    unittest.main()
