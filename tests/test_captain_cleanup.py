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
import time
import unittest
from pathlib import Path
from unittest import mock

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
- Base SHA (bootstrap): {base_sha}   Last pushed SHA (feature branch): none

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
            base_sha=self.git(self.repo, "rev-parse", "origin/main").strip(),
            running=self.wt["running"],
            rows="".join(ROW.format(name=name, path=path) for name, path in self.wt.items()
                         if name not in ("running", "no-row"))), encoding="utf-8")
        for path in (self.checkout, *self.wt.values()):
            self.script(RECORD, f"--run-dir={self.run_dir}", f"--worktree={path}",
                        f"--agent={path.name}", check=True)

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
        """Item lines keyed by worktree name; every line of the output stays in self.out."""
        result = self.script(CLEANUP, f"--run-dir={self.run_dir}", *extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.out = result.stdout.splitlines()
        found = {}
        for line in self.out:
            if line.split()[0] in ("REMOVED", "WOULD-REMOVE", "SKIPPED"):
                found[Path(line.split()[1]).name] = line
        return found

    def set_agent(self, path: Path, agent: str) -> None:
        """Put `agent` into the manifest line of a worktree, as record-created.py --agent does."""
        manifest = self.run_dir / "created.jsonl"
        entries = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
        for entry in entries:
            if entry["worktree"] == str(path):
                entry["agent"] = agent
        manifest.write_text("".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8")

    def edit_run_md(self, old: str, new: str) -> None:
        run_md = self.run_dir / "run.md"
        text = run_md.read_text(encoding="utf-8")
        self.assertIn(old, text)
        run_md.write_text(text.replace(old, new), encoding="utf-8")

    def stub(self, name: str, body: str) -> None:
        """A fake command first on PATH for the cleanup script."""
        directory = Path(self.tmp.name) / "bin"
        directory.mkdir(exist_ok=True)
        path = directory / name
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        path.chmod(0o755)
        self.env["PATH"] = f"{directory}{os.pathsep}{os.environ.get('PATH', '')}"

    def sleeper(self, cwd: Path) -> subprocess.Popen:
        process = subprocess.Popen(["sleep", "60"], cwd=str(cwd))
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        return process


class RecordCreatedTest(CleanupCase):
    def test_one_json_line_per_worktree_with_the_fields_from_git(self):
        entries = [json.loads(line) for line in
                   (self.run_dir / "created.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(entries), 1 + len(self.wt))
        first = entries[0]
        self.assertEqual(set(first), {"run_id", "common_dir", "worktree", "branch", "sha", "created",
                                      "agent", "git_ino", "git_dev"})
        self.assertEqual(first["run_id"], RUN_ID)
        self.assertEqual(first["common_dir"], os.path.realpath(self.repo / ".git"))
        self.assertEqual(first["worktree"], str(self.checkout))
        self.assertEqual(first["branch"], FEATURE)
        self.assertEqual(first["sha"], self.git(self.checkout, "rev-parse", "HEAD").strip())

    def test_line_carries_the_agent_and_the_inode_and_device_of_the_git_file(self):
        entries = [json.loads(line) for line in
                   (self.run_dir / "created.jsonl").read_text(encoding="utf-8").splitlines()]
        for entry in entries:
            link = os.stat(Path(entry["worktree"]) / ".git")
            self.assertEqual(entry["agent"], Path(entry["worktree"]).name)
            self.assertEqual(entry["git_ino"], link.st_ino)
            self.assertEqual(entry["git_dev"], link.st_dev)
            self.assertIsInstance(entry["git_ino"], int)
            self.assertIsInstance(entry["git_dev"], int)

    def test_recorded_output_line_is_unchanged(self):
        result = self.script(RECORD, f"--run-dir={self.run_dir}", f"--worktree={self.wt['clean']}",
                             "--agent=clean", check=True)
        sha = self.git(self.wt["clean"], "rev-parse", "HEAD").strip()
        self.assertEqual(result.stdout,
                         f"RECORDED {self.wt['clean']} branch=captain/w-clean sha={sha}\n")

    def test_missing_or_empty_agent_is_refused_and_nothing_is_written(self):
        before = (self.run_dir / "created.jsonl").read_text(encoding="utf-8")
        missing = self.script(RECORD, f"--run-dir={self.run_dir}", f"--worktree={self.wt['clean']}")
        self.assertEqual(missing.returncode, 2)
        self.assertIn("--agent", missing.stderr)
        for value in ("", "  "):
            empty = self.script(RECORD, f"--run-dir={self.run_dir}",
                                f"--worktree={self.wt['clean']}", f"--agent={value}")
            self.assertEqual(empty.returncode, 2)
            self.assertIn("non-empty", empty.stderr)
        self.assertEqual((self.run_dir / "created.jsonl").read_text(encoding="utf-8"), before)

    def test_refuses_the_main_worktree_and_a_detached_head(self):
        before = (self.run_dir / "created.jsonl").read_text(encoding="utf-8")
        result = self.script(RECORD, f"--run-dir={self.run_dir}", f"--worktree={self.repo}",
                             "--agent=main")
        self.assertEqual(result.returncode, 2)
        self.assertIn("main worktree", result.stderr)
        self.git(self.wt["clean"], "checkout", "-q", "--detach")
        result = self.script(RECORD, f"--run-dir={self.run_dir}", f"--worktree={self.wt['clean']}",
                             "--agent=clean")
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
            "captain-run": "run checkout kept; pass --include-run-checkout on the owner's request",
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

    def test_run_checkout_goes_last_with_the_flag(self):
        for marker in Path(self.env["CAPTAIN_STATE_DIR"]).iterdir():
            marker.unlink()
        (self.run_dir / "run.md").write_text(
            (self.run_dir / "run.md").read_text(encoding="utf-8").replace("| no |", "| yes |"),
            encoding="utf-8")
        self.git(self.repo, "merge", "-q", "--ff-only", FEATURE)
        self.git(self.repo, "push", "-q", "origin", "main")
        found = self.lines("--include-run-checkout")
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

    def test_second_run_reports_already_removed_in_one_line(self):
        self.lines()
        found = self.lines()
        self.assertNotIn("clean", found)
        self.assertNotIn("supacode", found)
        self.assertEqual(self.out[-1], "ALREADY-REMOVED 2")

    def test_second_run_after_a_full_cleanup_prints_only_read_and_already_removed(self):
        manifest = self.run_dir / "created.jsonl"
        kept = [line for line in manifest.read_text(encoding="utf-8").splitlines()
                if json.loads(line)["worktree"] in (str(self.wt["clean"]), str(self.wt["supacode"]))]
        manifest.write_text("\n".join(kept) + "\n", encoding="utf-8")
        found = self.lines()
        self.assertTrue(found["clean"].startswith("REMOVED "), found["clean"])
        self.assertTrue(found["supacode"].startswith("REMOVED "), found["supacode"])
        self.lines()
        self.assertEqual(len(self.out), 2, self.out)
        self.assertTrue(self.out[0].startswith("READ "), self.out)
        self.assertEqual(self.out[1], "ALREADY-REMOVED 2")

    def test_no_agents_table_skips_everything(self):
        text = (self.run_dir / "run.md").read_text(encoding="utf-8")
        (self.run_dir / "run.md").write_text(text.split("## Agents")[0], encoding="utf-8")
        found = self.lines()
        self.assertTrue(all(line.startswith("SKIPPED ") for line in found.values()), found)
        self.assertIn("no readable ## Agents table", found["clean"])
        self.assertIn("no readable ## Agents table", found["supacode"])
        self.assertTrue((self.trees / "clean").is_dir())

    def test_agents_table_without_data_rows_or_notified_skips_everything(self):
        text = (self.run_dir / "run.md").read_text(encoding="utf-8")
        header, _, rest = text.partition("## Agents\n")
        empty = header + "## Agents\n" + "\n".join(rest.splitlines()[:2]) + "\n"
        no_notified = text.replace("| notified |", "| notice |")
        for variant in (empty, no_notified):
            (self.run_dir / "run.md").write_text(variant, encoding="utf-8")
            found = self.lines()
            self.assertTrue(all(line.startswith("SKIPPED ") for line in found.values()), found)
            self.assertIn("no readable ## Agents table", found["clean"])
        self.assertTrue((self.trees / "clean").is_dir())

    def test_row_found_by_name_when_no_checkout_matches(self):
        self.set_agent(self.wt["no-row"], "w-late")
        self.edit_run_md("| w-running | a2 |",
                         "| w-late | a3 | t3 | demo | - | opus | 15m | 14:05 | 3 | /z | yes | 1% keep |\n"
                         "| w-running | a2 |")
        found = self.lines()
        self.assertTrue(found["no-row"].startswith("REMOVED "), found["no-row"])
        self.assertFalse((self.trees / "no-row").exists())

    def test_row_found_by_name_not_notified_is_still_running(self):
        self.set_agent(self.wt["no-row"], "w-late")
        self.edit_run_md("| w-running | a2 |",
                         "| w-late | a3 | t3 | demo | - | opus | 15m | 14:05 | 3 | /z | no | 1% keep |\n"
                         "| w-running | a2 |")
        found = self.lines()
        self.assertTrue(found["no-row"].startswith("SKIPPED "), found["no-row"])
        self.assertIn("writer still running in run.md", found["no-row"])

    def test_no_row_for_the_agent_names_it(self):
        self.set_agent(self.wt["no-row"], "w-late")
        found = self.lines()
        self.assertTrue(found["no-row"].startswith("SKIPPED "), found["no-row"])
        self.assertIn(f"no agent row for w-late ({self.wt['no-row']})", found["no-row"])

    def test_a_process_inside_the_worktree_keeps_it(self):
        process = self.sleeper(self.wt["clean"])
        found = self.lines()
        self.assertTrue(found["clean"].startswith("SKIPPED "), found["clean"])
        self.assertIn(f"a process works in it (pid {process.pid}, sleep)", found["clean"])
        self.assertTrue((self.trees / "clean").is_dir())
        self.assertTrue(found["supacode"].startswith("REMOVED "), found["supacode"])

    def test_ps_failure_makes_the_process_check_incomplete(self):
        self.stub("ps", "exit 1\n")
        found = self.lines()
        self.assertTrue(found["clean"].startswith("SKIPPED "), found["clean"])
        self.assertIn("process check incomplete: ps failed: exit 1", found["clean"])
        self.assertTrue((self.trees / "clean").is_dir())

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("lsof"), "macOS lsof path")
    def test_lsof_dropping_a_live_pid_makes_the_process_check_incomplete(self):
        process = self.sleeper(Path(self.tmp.name))  # a live pid outside every worktree
        self.env.update(REAL_LSOF=shutil.which("lsof"), DROP_PID=str(process.pid))
        self.stub("lsof", '"$REAL_LSOF" "$@" | awk -v drop="p$DROP_PID" '
                          "'/^p/ { skip = ($0 == drop) } !skip'\n")
        found = self.lines()
        self.assertTrue(found["clean"].startswith("SKIPPED "), found["clean"])
        self.assertIn(f"process check incomplete: lsof gave no cwd for pid {process.pid}",
                      found["clean"])

    def test_an_ended_pid_and_another_users_pid_are_ignored(self):
        ended = next(pid for pid in range(4_000_000, 4_001_000) if not pid_exists(pid))
        self.stub("ps", f"echo '{ended} {os.getuid()} S sleep'\necho '1 0 Ss init'\n")
        found = self.lines()
        self.assertTrue(found["clean"].startswith("REMOVED "), found["clean"])

    def test_ignored_logs_are_copied_and_other_ignored_files_keep_the_worktree(self):
        (self.repo / ".git" / "info").mkdir(exist_ok=True)
        (self.repo / ".git" / "info" / "exclude").write_text("tmp/\nnode_modules/\n*.local\n",
                                                             encoding="utf-8")
        logs = self.wt["clean"] / "tmp" / "claude-logs"
        logs.mkdir(parents=True)
        (logs / "x.log").write_text("log\n", encoding="utf-8")
        (self.wt["clean"] / "node_modules" / "pkg").mkdir(parents=True)
        (self.wt["clean"] / "node_modules" / "pkg" / "index.js").write_text("x\n", encoding="utf-8")
        (self.wt["supacode"] / "notes.local").write_text("mine\n", encoding="utf-8")
        found = self.lines()
        copy = self.run_dir / "worktree-logs" / "clean"
        self.assertTrue(found["clean"].startswith("REMOVED "), found["clean"])
        self.assertIn(f"logs={copy}", found["clean"])
        self.assertEqual((copy / "x.log").read_text(encoding="utf-8"), "log\n")
        self.assertFalse((self.trees / "clean").exists())
        self.assertTrue(found["supacode"].startswith("SKIPPED "), found["supacode"])
        self.assertIn("ignored files that are not disposable: notes.local", found["supacode"])
        self.assertTrue((self.trees / "supacode" / "notes.local").is_file())

    def write_log(self, worktree: Path) -> Path:
        """An ignored tmp/claude-logs/x.log in a worktree; returns the logs directory."""
        (self.repo / ".git" / "info").mkdir(exist_ok=True)
        (self.repo / ".git" / "info" / "exclude").write_text("tmp/\n", encoding="utf-8")
        logs = worktree / "tmp" / "claude-logs"
        logs.mkdir(parents=True)
        (logs / "x.log").write_text("log\n", encoding="utf-8")
        return logs

    def test_a_second_row_not_notified_for_the_same_checkout_keeps_it(self):
        self.edit_run_md("| w-running | a2 |",
                         f"| w-again | a4 | t4 | demo | {self.wt['clean']} | opus | 15m | 14:05 | 1 "
                         f"| /w | no | 1% keep |\n| w-running | a2 |")
        found = self.lines()
        self.assertTrue(found["clean"].startswith("SKIPPED "), found["clean"])
        self.assertIn("writer still running in run.md", found["clean"])
        self.assertTrue((self.trees / "clean").is_dir())

    def test_a_symlink_in_the_logs_keeps_the_worktree(self):
        logs = self.write_log(self.wt["clean"])
        (logs / "link.log").symlink_to("../../README")
        found = self.lines()
        self.assertTrue(found["clean"].startswith("SKIPPED "), found["clean"])
        self.assertIn("tmp/claude-logs/ holds a symlink: tmp/claude-logs/link.log", found["clean"])
        self.assertTrue((self.trees / "clean").is_dir())

    def test_a_failed_log_copy_keeps_the_worktree(self):
        self.write_log(self.wt["clean"])
        (self.run_dir / "worktree-logs").write_text("not a directory\n", encoding="utf-8")
        found = self.lines()
        self.assertTrue(found["clean"].startswith("SKIPPED "), found["clean"])
        self.assertIn("copy of tmp/claude-logs/ failed", found["clean"])
        self.assertTrue((self.trees / "clean" / "tmp" / "claude-logs" / "x.log").is_file())

    def test_a_failed_branch_step_after_removal_names_the_log_copy(self):
        self.write_log(self.wt["unmerged"])
        self.git(self.repo, "push", "-q", "origin", "captain/w-unmerged:main")
        self.git(self.repo, "fetch", "-q", "origin")
        found = self.lines()
        copy = self.run_dir / "worktree-logs" / "unmerged"
        self.assertTrue(found["unmerged"].startswith("SKIPPED "), found["unmerged"])
        self.assertIn(f"logs={copy} reason=worktree removed; merged into origin/main",
                      found["unmerged"])
        self.assertFalse((self.trees / "unmerged").exists())
        self.assertEqual((copy / "x.log").read_text(encoding="utf-8"), "log\n")

    def test_an_unreadable_repository_is_skipped_not_already_removed(self):
        broken = Path(self.tmp.name) / "not-a-repo"
        broken.mkdir()
        manifest = self.run_dir / "created.jsonl"
        entries = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
        for entry in entries:
            if entry["worktree"] == str(self.wt["clean"]):
                entry["common_dir"] = str(broken)
        manifest.write_text("".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8")
        found = self.lines()
        self.assertTrue(found["clean"].startswith("SKIPPED "), found["clean"])
        self.assertIn("git cannot read the repository", found["clean"])
        self.assertNotIn("ALREADY-REMOVED 1", self.out)
        self.assertTrue((self.trees / "clean").is_dir())

    def test_first_line_says_what_was_read_from_run_md(self):
        self.lines()
        sha = self.git(self.repo, "rev-parse", "origin/main").strip()
        self.assertEqual(self.out[0], f"READ feature={FEATURE} base=none default=main "
                                      f"checkout={self.checkout} base_sha={sha} agents=8")
        self.assertFalse([line for line in self.out if line.startswith("WARN ")], self.out)

    def test_an_other_base_label_is_missing_and_warned(self):
        self.edit_run_md("- Base branch (R10): none: feature branch only",
                         "- Base branch for merges: main")
        self.lines()
        self.assertIn(" base=- ", self.out[0])
        self.assertIn("WARN run.md has no Base branch (R10): line; the base branch is not a merge "
                      "target", self.out)

    def test_missing_run_md_is_bad_input(self):
        (self.run_dir / "run.md").unlink()
        result = self.script(CLEANUP, f"--run-dir={self.run_dir}")
        self.assertEqual(result.returncode, 2)


SIX_DAYS = 6 * 24 * 3600


class IdentityAndMarkerTest(CleanupCase):
    """D3: the worktree is the one the run created; D5: stale and foreign markers."""

    def setUp(self):
        super().setUp()
        self.projects = Path(self.env["CAPTAIN_STATE_DIR"]).parent / "projects"
        (self.projects / "-some-project").mkdir(parents=True)
        self.env["CAPTAIN_PROJECTS_DIR"] = str(self.projects)
        self.sessions = Path(self.env["CAPTAIN_STATE_DIR"])

    def manifest(self) -> list[dict]:
        return [json.loads(line) for line in
                (self.run_dir / "created.jsonl").read_text(encoding="utf-8").splitlines()]

    def write_manifest(self, entries: list[dict]) -> None:
        (self.run_dir / "created.jsonl").write_text(
            "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8")

    def record_identity(self) -> None:
        """The fields record-created.py writes since D3, taken from each worktree's .git."""
        entries = self.manifest()
        for entry in entries:
            found = os.stat(Path(entry["worktree"]) / ".git")
            entry.update(git_ino=found.st_ino, git_dev=found.st_dev)
        self.write_manifest(entries)

    def recreate(self, name: str) -> None:
        path = self.trees / name
        # a hard link keeps the old .git inode in use, so the new .git cannot reuse its number
        os.link(path / ".git", self.run_dir / f"{name}.old-git")
        self.git(self.repo, "worktree", "remove", str(path))
        self.git(self.repo, "worktree", "add", "-q", str(path), f"captain/w-{name}")

    def marker(self, session: str, cwd: Path, age: float = 0) -> Path:
        path = self.sessions / session
        path.write_text(json.dumps({"since": 1, "cwd": str(cwd)}) + "\n", encoding="utf-8")
        if age:
            stamp = time.time() - age
            os.utime(path, (stamp, stamp))
        return path

    def session_cwds(self, run_common: str) -> tuple[bool, set[str]]:
        cleanup = load_cleanup()
        with mock.patch.dict(os.environ, {"CAPTAIN_STATE_DIR": str(self.sessions),
                                          "CAPTAIN_PROJECTS_DIR": str(self.projects)}):
            return cleanup.session_cwds(run_common)

    def common(self) -> str:
        return os.path.realpath(self.repo / ".git")

    def test_recreated_worktree_at_the_same_path_and_branch_is_skipped(self):
        self.record_identity()
        self.recreate("clean")
        found = self.lines()
        self.assertTrue(found["clean"].startswith("SKIPPED "), found["clean"])
        self.assertIn("worktree at this path is not the one the run created", found["clean"])
        self.assertTrue((self.trees / "clean").is_dir())
        self.assertIn("captain/w-clean", self.git(self.repo, "branch", "--list"))
        self.assertTrue(found["supacode"].startswith("REMOVED "), found["supacode"])

    def test_missing_git_file_is_not_the_one_the_run_created(self):
        self.record_identity()
        os.unlink(self.trees / "clean" / ".git")
        found = self.lines("--dry-run")
        self.assertIn("worktree at this path is not the one the run created", found["clean"])

    def test_old_manifest_line_without_inode_keeps_todays_behaviour(self):
        entries = self.manifest()
        for entry in entries:
            if entry["worktree"] == str(self.wt["clean"]):
                del entry["git_ino"], entry["git_dev"]
        self.write_manifest(entries)
        self.recreate("clean")
        line = next(entry for entry in self.manifest() if entry["worktree"] == str(self.wt["clean"]))
        self.assertNotIn("git_ino", line)
        self.assertNotIn("git_dev", line)
        found = self.lines()
        self.assertTrue(found["clean"].startswith("REMOVED "), found["clean"])
        self.assertFalse((self.trees / "clean").exists())

    def test_branch_left_by_an_earlier_run_is_deleted_once_merged_into_a_head(self):
        self.record_identity()
        self.git(self.repo, "push", "-q", "origin", "captain/w-unmerged:main")
        self.git(self.repo, "fetch", "-q", "origin")
        found = self.lines()
        self.assertIn("merged into origin/main but no checkout", found["unmerged"])
        self.assertFalse((self.trees / "unmerged").exists())
        self.git(self.repo, "merge", "-q", "--ff-only", "captain/w-unmerged")
        found = self.lines()
        self.assertTrue(found["unmerged"].startswith("REMOVED "), found["unmerged"])
        self.assertNotIn("captain/w-unmerged", self.git(self.repo, "branch", "--list"))

    def test_only_a_stale_marker_leaves_captain_mode_off(self):
        marker = self.sessions / "session-1"
        for path in (marker, *(marker.with_name(f"session-1{suffix}")
                               for suffix in (".merge", ".base"))):
            if not path.exists():
                path.write_text("{}\n", encoding="utf-8")
            stamp = time.time() - SIX_DAYS
            os.utime(path, (stamp, stamp))
        self.assertEqual(self.session_cwds(self.common()), (False, set()))
        found = self.lines()
        self.assertTrue(found["cwd"].startswith("REMOVED "), found["cwd"])
        self.assertTrue(marker.is_file(), "a stale marker is never moved or deleted")

    def test_stale_marker_whose_transcript_changed_today_counts(self):
        marker = self.sessions / "session-1"
        stamp = time.time() - SIX_DAYS
        os.utime(marker, (stamp, stamp))
        (self.projects / "-some-project" / "session-1.jsonl").write_text("{}\n", encoding="utf-8")
        on, cwds = self.session_cwds(self.common())
        self.assertTrue(on)
        self.assertEqual(cwds, {str(self.wt["cwd"] / "sub")})
        found = self.lines()
        self.assertIn("working directory of a main session", found["cwd"])

    def test_fresh_marker_in_another_repository_leaves_mode_off_for_this_run(self):
        (self.sessions / "session-1").unlink()
        other = self.repo.parent / "other"
        self.git(self.repo.parent, "init", "-q", "-b", "main", str(other))
        self.marker("session-2", other)
        on, cwds = self.session_cwds(self.common())
        self.assertFalse(on)
        self.assertEqual(cwds, {str(other)})
        self.assertTrue(self.session_cwds(os.path.realpath(other / ".git"))[0])

    def test_fresh_marker_inside_a_worktree_protects_that_worktree(self):
        self.marker("session-3", self.wt["clean"])
        found = self.lines()
        self.assertTrue(found["clean"].startswith("SKIPPED "), found["clean"])
        self.assertIn("working directory of a main session", found["clean"])
        self.assertTrue((self.trees / "clean").is_dir())
        self.assertTrue(self.session_cwds(self.common())[0])


KEPT = "run checkout kept; pass --include-run-checkout on the owner's request"


class RunCheckoutTest(CleanupCase):
    """D6: the run checkout goes only with --include-run-checkout, and only when used and pushed.

    setUp: the feature branch holds the w-clean commit beyond Base SHA (= origin/main), and
    session-1 is a live marker of this repository, so captain mode is on.
    """

    def setUp(self):
        super().setUp()
        projects = Path(self.env["CAPTAIN_STATE_DIR"]).parent / "projects"
        projects.mkdir()  # no transcripts: a marker's age is its own mtime
        self.env["CAPTAIN_PROJECTS_DIR"] = str(projects)

    def merge_feature_locally(self) -> None:
        self.git(self.repo, "merge", "-q", "--ff-only", FEATURE)

    def push_main(self) -> None:
        self.git(self.repo, "push", "-q", "origin", "main")

    def assert_kept(self, found: dict[str, str], reason: str) -> None:
        self.assertTrue(found["captain-run"].startswith("SKIPPED "), found["captain-run"])
        self.assertIn(reason, found["captain-run"])
        self.assertTrue(self.checkout.is_dir())
        self.assertIn(FEATURE, self.git(self.repo, "branch", "--list"))

    def test_without_the_flag_kept_with_a_live_marker_even_merged_and_pushed(self):
        self.merge_feature_locally()
        self.push_main()
        self.assert_kept(self.lines(), KEPT)

    def test_without_the_flag_kept_with_only_stale_markers_even_merged_and_pushed(self):
        stamp = time.time() - SIX_DAYS
        for marker in Path(self.env["CAPTAIN_STATE_DIR"]).iterdir():
            os.utime(marker, (stamp, stamp))
        self.merge_feature_locally()
        self.push_main()
        found = self.lines()
        self.assertTrue(found["cwd"].startswith("REMOVED "), "the stale marker no longer counts")
        self.assert_kept(found, KEPT)

    def test_with_the_flag_a_fresh_run_checkout_is_kept(self):
        self.git(self.checkout, "reset", "-q", "--hard", "origin/main")
        self.assert_kept(self.lines("--include-run-checkout"), "no commits beyond Base SHA")

    def test_with_the_flag_merged_only_locally_is_kept(self):
        self.merge_feature_locally()
        self.assert_kept(self.lines("--include-run-checkout"),
                         "the feature branch is not in origin/main")

    def test_with_the_flag_a_missing_base_sha_keeps_it(self):
        self.merge_feature_locally()
        self.push_main()
        self.edit_run_md("- Base SHA (bootstrap): ", "- Bootstrap SHA: ")
        self.assert_kept(self.lines("--include-run-checkout"), "run.md has no Base SHA")

    def test_with_the_flag_merged_pushed_and_clean_is_removed_with_captain_mode_on(self):
        self.merge_feature_locally()
        self.push_main()
        found = self.lines("--include-run-checkout")
        self.assertTrue(found["captain-run"].startswith("REMOVED "), found["captain-run"])
        self.assertFalse(self.checkout.exists())
        self.assertNotIn(FEATURE, self.git(self.repo, "branch", "--list"))
        self.assertTrue(found["cwd"].startswith("SKIPPED "), "the live marker still protects")

    def test_with_the_flag_a_dirty_run_checkout_is_kept(self):
        self.merge_feature_locally()
        self.push_main()
        (self.checkout / "scratch.txt").write_text("untracked\n", encoding="utf-8")
        self.assert_kept(self.lines("--include-run-checkout"), "tracked or untracked changes")

    def test_with_the_flag_merged_in_another_clone_removes_the_worktree_and_keeps_the_branch(self):
        self.git(self.repo, "push", "-q", "origin", f"{FEATURE}:main")
        self.git(self.repo, "fetch", "-q", "origin")
        feature_head = self.git(self.repo, "rev-parse", FEATURE).strip()
        found = self.lines("--include-run-checkout")
        self.assertTrue(found["captain-run"].startswith("SKIPPED "), found["captain-run"])
        self.assertIn("reason=worktree removed; merged into origin/main but no checkout",
                      found["captain-run"])
        self.assertFalse(self.checkout.exists())
        self.assertIn(FEATURE, self.git(self.repo, "branch", "--list"))
        self.assertNotEqual(self.git(self.repo, "rev-parse", "main").strip(), feature_head)


def pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


class TreeHelpersTest(unittest.TestCase):
    def test_disposable_names_count_only_as_directories(self):
        cleanup = load_cleanup()
        for path in ("node_modules/a.js", "src/__pycache__/m.cpython-312.pyc", ".pytest_cache/v",
                     "tmp/claude-logs/x.log", "m.pyc"):
            self.assertTrue(cleanup.disposable(path), path)
        for path in ("node_modules", "__pycache__", "tmp/claude-logs", "tmp/claude-logs-old/x",
                     "notes.local"):
            self.assertFalse(cleanup.disposable(path), path)

    def test_same_named_worktrees_get_their_own_log_copy(self):
        cleanup = load_cleanup()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for repo in ("one", "two"):
                logs = base / repo / "w" / "tmp" / "claude-logs"
                logs.mkdir(parents=True)
                (logs / "x.log").write_text(repo, encoding="utf-8")
            first = cleanup.copy_logs(str(base / "one" / "w"), str(base / "run"))
            second = cleanup.copy_logs(str(base / "two" / "w"), str(base / "run"))
            self.assertEqual(first, (str(base / "run" / "worktree-logs" / "w"), None))
            self.assertEqual(second, (str(base / "run" / "worktree-logs" / "w-2"), None))
            self.assertEqual((base / "run" / "worktree-logs" / "w" / "x.log").read_text(), "one")
            self.assertEqual((base / "run" / "worktree-logs" / "w-2" / "x.log").read_text(), "two")


class ProcCwdTest(unittest.TestCase):
    """Linux cwd lookup, with os.readlink faked so it runs on every platform."""

    def test_a_failed_lookup_of_a_live_pid_is_an_error(self):
        cleanup = load_cleanup()
        with mock.patch.object(cleanup.os, "readlink", side_effect=PermissionError("denied")):
            cwds, error = cleanup.cwds_from_proc([os.getpid()])
        self.assertEqual(cwds, {})
        self.assertIn(f"cwd of pid {os.getpid()}", error)

    def test_a_pid_that_ended_is_ignored(self):
        cleanup = load_cleanup()
        ended = next(pid for pid in range(4_000_000, 4_001_000) if not pid_exists(pid))
        with mock.patch.object(cleanup.os, "readlink", side_effect=FileNotFoundError("gone")):
            self.assertEqual(cleanup.cwds_from_proc([ended]), ({}, None))


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


if __name__ == "__main__":
    unittest.main()
