#!/usr/bin/env python3
"""Tests for the captain cowboy merge gate (KB8) in hooks/guard.py and its R17 check (check 5
of scripts/check-run-end.py).

The model's Skill calls `captain cowboy on`, `captain cowboy off` and `captain cowboy green
<sha>` keep a record per repository (git common dir) and branch in <state dir>/cowboy/. A merge
whose source brings a cowboy commit no green record covers is denied into every branch other
than the cowboy branch and its own agent branches, also with a `/captain merge` grant. The
green record needs HEAD at the SHA, a cowboy branch tip at the SHA and a passing
tmp/captain/<run>/tests/<sha>.json (OP5). Every case runs on a temporary repository with one
state directory per test, so the records persist across calls, `/captain off` and sessions.

Run:  python3 tests/test_captain_cowboy.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "plugins" / "captain" / "hooks" / "guard.py"
CHECK = ROOT / "plugins" / "captain" / "skills" / "captain" / "scripts" / "check-run-end.py"
AUDIT = ROOT / "plugins" / "captain" / "skills" / "captain" / "scripts" / "audit-main.py"
SESSION = "c0b0y000-7d1f-4c39-9a2e-0f6b7f3d1a10"
NIGHT = "c0b0y111-7d1f-4c39-9a2e-0f6b7f3d1a11"
GATE = "Captain cowboy gate (KB8)"


class CowboyBase(unittest.TestCase):
    """A repository with main (the origin default), the base `dev`, the cowboy branch
    `captain/cow` off dev and a plain branch `topic` off dev; one state directory."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.tmp.name))
        self.repo = self.root / "repo"
        self.state = self.root / "state"
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        (self.repo / ".git" / "info" / "exclude").write_text("tmp/\n")
        self.commit("base")
        self.git("update-ref", "refs/remotes/origin/main", "main")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.git("branch", "dev")
        self.git("checkout", "-q", "-b", "topic", "dev")
        self.commit("topic")
        self.git("checkout", "-q", "-b", "captain/cow", "dev")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@t", "-c",
                               "user.name=t", *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    def commit(self, name: str) -> str:
        (self.repo / f"{name.replace('/', '_')}.txt").write_text(f"{name}\n")
        self.git("add", "-A", ".")
        self.git("commit", "-q", "-m", name)
        return self.git("rev-parse", "HEAD")

    def hook(self, event: dict, session: str = SESSION) -> subprocess.CompletedProcess:
        event = {"session_id": session, "cwd": str(self.repo), **event}
        result = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event),
                                capture_output=True, text=True, timeout=60,
                                env={**os.environ, "CAPTAIN_STATE_DIR": str(self.state)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return result

    def prompt(self, text: str, session: str = SESSION) -> None:
        self.hook({"hook_event_name": "UserPromptSubmit", "prompt": text}, session)

    def cowboy(self, args: str, session: str = SESSION) -> str:
        """The guard's note on the Skill call `captain cowboy ...`."""
        result = self.hook({"hook_event_name": "PostToolUse", "tool_name": "Skill",
                            "tool_input": {"skill": "captain:captain", "args": f"cowboy {args}"}},
                           session)
        return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]

    def merge(self, branch: str, session: str = SESSION) -> str | None:
        """The deny reason for `git merge --no-ff --no-edit <branch>` at HEAD, else None."""
        return self.bash(f"git merge --no-ff --no-edit {branch}", session)

    def bash(self, command: str, session: str = SESSION) -> str | None:
        result = self.hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                            "tool_input": {"command": command}}, session)
        if not result.stdout.strip():
            return None
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        return output["permissionDecisionReason"]

    def gated(self, reason: str | None) -> bool:
        return reason is not None and reason.startswith(GATE)

    def result_file(self, sha: str, commands=None, named: str | None = None,
                    raw: str | None = None) -> Path:
        path = self.repo / "tmp" / "captain" / "r1" / "tests" / f"{sha}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {"sha": named or sha,
                "commands": [{"cmd": "./run-tests.sh", "exit": 0}] if commands is None
                else commands}
        path.write_text(raw if raw is not None else json.dumps(body))
        return path

    def start_cowboy(self) -> str:
        """A captain run with base dev, cowboy on for captain/cow and one cowboy commit; its SHA."""
        self.prompt("/captain 1h")
        self.prompt("/captain base dev")
        self.assertIn("cowboy on for `captain/cow`", self.cowboy("on"))
        return self.commit("cow one")

    def green(self, sha: str) -> str:
        self.result_file(sha)
        return self.cowboy(f"green {sha}")


class MergeGateTest(CowboyBase):

    def test_merge_denied_before_green_allowed_after_denied_after_a_new_commit(self):
        one = self.start_cowboy()
        self.git("checkout", "-q", "dev")
        self.assertTrue(self.gated(self.merge("captain/cow")))
        self.git("checkout", "-q", "captain/cow")
        self.assertIn("cowboy green", self.green(one))
        self.git("checkout", "-q", "dev")
        self.assertIsNone(self.merge("captain/cow"))
        self.git("checkout", "-q", "captain/cow")
        self.commit("cow two")  # a later commit: a sync, a conflict fix, a TODO commit
        self.git("checkout", "-q", "dev")
        self.assertTrue(self.gated(self.merge("captain/cow")))

    def test_any_source_holding_an_untested_commit_is_denied(self):
        self.start_cowboy()
        self.git("checkout", "-q", "-b", "renamed")  # the same commits under another name
        self.git("checkout", "-q", "dev")
        self.assertTrue(self.gated(self.merge("renamed")))

    def test_the_conclusion_of_a_started_merge_is_gated_too(self):
        self.start_cowboy()
        self.git("checkout", "-q", "dev")
        self.git("merge", "--no-ff", "--no-commit", "captain/cow")  # MERGE_HEAD is set
        self.assertTrue(self.gated(self.bash("git commit --no-edit")))

    def test_the_record_survives_off_and_a_new_session(self):
        one = self.start_cowboy()
        self.prompt("/captain off")
        self.assertTrue(any((self.state / "cowboy").iterdir()))
        self.prompt("/captain 1h", NIGHT)  # the night-shift session, a normal run
        self.prompt("/captain base dev", NIGHT)
        self.git("checkout", "-q", "dev")
        self.assertTrue(self.gated(self.merge("captain/cow", NIGHT)))
        self.git("checkout", "-q", "captain/cow")
        self.result_file(one)
        self.assertIn("cowboy green", self.cowboy(f"green {one}", NIGHT))
        self.git("checkout", "-q", "dev")
        self.assertIsNone(self.merge("captain/cow", NIGHT))

    def test_cowboy_off_keeps_the_commits_made_so_far_gated(self):
        self.start_cowboy()
        self.prompt("/captain off")
        self.assertIn("cowboy off for `captain/cow`", self.cowboy("off"))
        self.assertFalse((self.state / SESSION).exists())  # the call does not turn the mode on
        self.prompt("/captain 1h")
        self.prompt("/captain base dev")
        self.git("checkout", "-q", "dev")
        self.assertTrue(self.gated(self.merge("captain/cow")))

    def test_a_grant_does_not_lift_the_gate(self):
        one = self.start_cowboy()
        self.prompt("/captain merge main")
        self.git("checkout", "-q", "main")
        self.assertTrue(self.gated(self.merge("captain/cow")))
        self.git("checkout", "-q", "captain/cow")
        self.green(one)
        self.git("checkout", "-q", "main")
        self.assertIsNone(self.merge("captain/cow"))

    def test_a_green_branch_deleted_after_its_merge_still_lets_the_base_go_on(self):
        one = self.start_cowboy()
        self.green(one)
        self.git("checkout", "-q", "dev")
        self.git("merge", "-q", "--no-ff", "-m", "tested", "captain/cow")
        self.git("branch", "-D", "captain/cow")  # run cleanup
        self.prompt("/captain merge main")
        self.git("checkout", "-q", "main")
        self.assertIsNone(self.merge("dev"))

    def test_an_untested_branch_deleted_denies_fail_closed(self):
        self.start_cowboy()
        self.git("checkout", "-q", "dev")
        self.git("branch", "-D", "captain/cow")
        self.assertTrue(self.gated(self.merge("topic")))

    def test_a_sync_of_the_cowboy_branch_does_not_gate_the_synced_commits(self):
        self.start_cowboy()
        self.git("checkout", "-q", "main")
        self.commit("upstream")
        self.git("update-ref", "refs/remotes/origin/main", "main")
        self.git("checkout", "-q", "dev")
        self.commit("dev own")
        self.git("checkout", "-q", "captain/cow")
        self.git("merge", "-q", "--no-ff", "-m", "sync", "origin/main")
        self.git("merge", "-q", "--no-ff", "-m", "sync base", "dev")
        self.git("checkout", "-q", "dev")
        self.assertIsNone(self.bash("git merge --ff-only origin/main"))
        self.assertTrue(self.gated(self.merge("captain/cow")))  # its own commit still waits
        self.prompt("/captain merge main")
        self.git("checkout", "-q", "main")
        self.assertIsNone(self.merge("dev"))  # dev's own commit came into cow by the sync

    def test_the_gate_holds_with_no_session_marker(self):
        # r1 F1: after `/captain off` the record stays and so does the gate, alone
        self.start_cowboy()
        self.prompt("/captain off")
        self.git("checkout", "-q", "dev")
        self.assertTrue(self.gated(self.merge("captain/cow")))
        self.assertIsNone(self.merge("topic"))  # nothing else of captain mode applies
        self.assertIsNone(self.bash("git status"))

    def test_a_chain_outside_captain_mode_is_split_and_checked(self):
        # r2 F1, OP9: the HEAD a switch earlier in the chain sets is the merge target
        self.start_cowboy()
        self.prompt("/captain off")
        chain = "git switch dev && git merge --no-ff --no-edit captain/cow"
        self.assertTrue(self.gated(self.bash(chain)))  # HEAD is captain/cow when it is asked
        self.assertTrue(self.gated(self.bash("git checkout -q dev && git merge captain/cow -m x")))
        reason = self.bash("git checkout - && git merge --no-ff --no-edit captain/cow")
        self.assertTrue(self.gated(reason))
        self.assertIn("cannot tell", reason)
        self.git("checkout", "-q", "dev")
        self.assertIsNone(self.bash("git fetch -q . && git merge --no-ff --no-edit topic"))
        self.assertIsNone(self.bash("git status | head -n 3 && git log -n 1 --oneline"))
        self.assertIsNone(self.bash("git switch captain/cow && git merge --no-ff --no-edit dev"))

    def test_a_cd_into_a_subdirectory_keeps_the_switched_head(self):
        # r3 F1: HEAD is tracked per checkout, not per directory
        self.start_cowboy()
        self.prompt("/captain off")
        (self.repo / "sub").mkdir()
        chain = "git switch dev && cd sub && git merge --no-ff --no-edit captain/cow"
        self.assertTrue(self.gated(self.bash(chain)))
        reason = self.bash("cd missing-dir && git merge --no-ff --no-edit topic")
        self.assertTrue(self.gated(reason))
        self.assertIn("cannot resolve", reason)

    def test_a_move_not_joined_by_and_denies_the_merge(self):
        # r3 F2: after `||`, `;` or `|` the switch may have failed
        self.start_cowboy()
        self.prompt("/captain off")
        self.git("checkout", "-q", "dev")
        for chain in ("git switch captain/cow || git merge --no-ff --no-edit captain/cow",
                      "git switch captain/cow; git merge --no-ff --no-edit captain/cow",
                      "git switch captain/cow && git status; git merge --no-ff --no-edit topic"):
            with self.subTest(chain=chain):
                reason = self.bash(chain)
                self.assertTrue(self.gated(reason))
                self.assertIn("other than `&&`", reason)

    def test_a_merge_with_no_source_resolves_the_upstream(self):
        # r3 F3: `git merge` alone merges the upstream of HEAD
        self.start_cowboy()
        self.prompt("/captain off")
        self.git("branch", "--set-upstream-to=captain/cow", "dev")
        self.assertTrue(self.gated(self.bash("git switch dev && git merge")))
        self.git("branch", "--set-upstream-to=topic", "dev")
        self.assertIsNone(self.bash("git switch dev && git merge"))
        self.git("branch", "--unset-upstream", "dev")
        reason = self.bash("git switch dev && git merge")
        self.assertTrue(self.gated(reason))
        self.assertIn("upstream", reason)

    def test_option_values_are_no_merge_source(self):
        # r4 F1: `-m <msg>` with no source still merges the upstream
        self.start_cowboy()
        self.prompt("/captain off")
        self.git("branch", "--set-upstream-to=captain/cow", "dev")
        self.git("checkout", "-q", "dev")
        for command in ('git merge -m "Merge upstream"', "git merge --no-ff -s ort -X ours",
                        "git merge --message=x", "git merge --into-name dev -F msg.txt"):
            with self.subTest(command=command):
                self.assertTrue(self.gated(self.bash(command)))
        self.assertTrue(self.gated(self.bash("git merge -m captain/cow-is-a-message captain/cow")))
        self.git("branch", "--set-upstream-to=topic", "dev")
        self.assertIsNone(self.bash('git merge -m "Merge upstream"'))

    def test_a_concluding_commit_after_an_uncertain_move_is_denied(self):
        # r4 F2: `git switch x || git commit --no-edit` concludes the merge where HEAD is
        self.start_cowboy()
        self.prompt("/captain off")
        self.git("checkout", "-q", "dev")
        self.git("merge", "--no-ff", "--no-commit", "topic")  # MERGE_HEAD: a plain branch
        for chain in ("git switch captain/cow || git commit --no-edit",
                      "git switch captain/cow; git merge --continue"):
            with self.subTest(chain=chain):
                reason = self.bash(chain)
                self.assertTrue(self.gated(reason))
                self.assertIn("other than `&&`", reason)
        self.assertIsNone(self.bash("git commit --no-edit"))  # topic brings no cowboy commit

    def test_an_unresolvable_move_in_a_repo_without_a_record_passes(self):
        # r4 F3: no denial at all outside a repository with a cowboy record
        self.assertIsNone(self.bash("cd - && git merge --no-ff --no-edit topic"))
        self.assertIsNone(self.bash("cd missing-dir && git merge --no-ff --no-edit topic"))
        self.assertIsNone(self.bash("git switch dev; git merge --no-ff --no-edit topic"))

    def test_no_marker_and_no_record_changes_nothing(self):
        self.git("checkout", "-q", "dev")
        self.assertIsNone(self.merge("captain/cow"))
        self.assertIsNone(self.bash("git merge"))
        self.assertIsNone(self.bash("git switch main && git merge --no-ff --no-edit captain/cow"))

    def test_a_commit_after_cowboy_off_and_green_is_gated(self):
        # r1 F2: `cowboy off` freezes nothing; a later commit makes the green record stale
        one = self.start_cowboy()
        self.cowboy("off")
        self.green(one)
        self.git("checkout", "-q", "dev")
        self.assertIsNone(self.merge("captain/cow"))
        self.git("checkout", "-q", "captain/cow")
        self.commit("after off")
        self.git("checkout", "-q", "dev")
        self.assertTrue(self.gated(self.merge("captain/cow")))

    def test_an_agent_branch_merged_straight_into_the_base_is_gated(self):
        # r1 F4: the commits of the cowboy branch's own agent branches are cowboy commits
        self.start_cowboy()
        self.git("checkout", "-q", "-b", "captain/cow-a")
        self.commit("agent work")
        self.git("checkout", "-q", "dev")
        self.assertTrue(self.gated(self.merge("captain/cow-a")))

    def test_a_cowboy_start_ends_the_previous_grant(self):
        # r1 F5: `cowboy` and `tests=` are start words
        self.prompt("/captain 1h")
        self.prompt("/captain merge main")
        grant = self.state / f"{SESSION}.merge"
        self.assertTrue(grant.is_file())
        self.prompt("/captain cowboy tests=night")
        self.assertFalse(grant.is_file())

    def test_the_fallback_start_branch_is_gated_with_its_grant(self):
        # KB9 fallback: the start branch `work` is no base; its merge back needs /captain merge
        self.git("branch", "work", "dev")
        self.start_cowboy()
        self.prompt("/captain merge work")
        self.git("checkout", "-q", "work")
        self.assertIsNone(self.merge("topic"))  # the grant alone lets a plain branch in
        self.assertTrue(self.gated(self.merge("captain/cow")))

    def test_own_agent_branches_are_free_other_branches_are_gated(self):
        self.start_cowboy()
        self.git("checkout", "-q", "-b", "captain/cow-a")
        self.commit("agent")
        self.assertIsNone(self.merge("captain/cow"))  # a sync of the agent branch
        self.git("checkout", "-q", "captain/cow")
        self.assertIsNone(self.merge("captain/cow-a"))  # the loop: agent work lands
        self.git("checkout", "-q", "-b", "captain/other", "dev")
        self.assertTrue(self.gated(self.merge("captain/cow")))
        self.assertTrue(self.gated(self.merge("captain/cow-a")))  # the agent branch holds them too

    def test_non_cowboy_merges_are_unchanged(self):
        self.prompt("/captain 1h")
        self.prompt("/captain base dev")
        self.git("checkout", "-q", "dev")
        self.assertIsNone(self.merge("topic"))  # no record at all
        self.git("checkout", "-q", "captain/cow")
        self.cowboy("on")
        self.commit("cow one")
        self.git("checkout", "-q", "dev")
        self.assertIsNone(self.merge("topic"))  # a record of another branch
        self.git("checkout", "-q", "main")
        reason = self.merge("topic")  # main still waits for the grant, not for the gate
        self.assertFalse(self.gated(reason))
        self.assertIn("/captain merge <branch>", reason)

    def test_an_unreadable_record_denies(self):
        self.start_cowboy()
        for path in (self.state / "cowboy").iterdir():
            path.write_text("{not json")
        self.git("checkout", "-q", "dev")
        reason = self.merge("topic")
        self.assertTrue(self.gated(reason))
        self.assertIn("unreadable", reason)

    def test_the_state_directory_is_denied_to_write_and_bash(self):
        self.start_cowboy()
        target = next((self.state / "cowboy").iterdir())
        result = self.hook({"hook_event_name": "PreToolUse", "tool_name": "Write",
                            "tool_input": {"file_path": str(target), "content": "{}"}})
        self.assertIn("written only by the guard", result.stdout)
        self.assertIsNotNone(self.bash(f"rm '{target}'"))


class GreenRecordTest(CowboyBase):

    def setUp(self):
        super().setUp()
        self.one = self.start_cowboy()

    def refused(self, note: str, needle: str) -> None:
        self.assertIn("cowboy NOT green", note)
        self.assertIn(needle, note)
        self.git("checkout", "-q", "dev")
        self.assertTrue(self.gated(self.merge("captain/cow")))
        self.git("checkout", "-q", "captain/cow")

    def test_accepted_with_a_passing_result_file(self):
        self.result_file(self.one, [{"cmd": "./run-tests.sh", "exit": 0},
                                    {"cmd": "npm run build", "exit": 0}])
        self.assertIn(f"cowboy green {self.one[:12]}", self.cowboy(f"green {self.one}"))

    def test_accepted_with_the_file_in_another_worktree(self):
        # r1 F7: the runner may write the result in its temporary worktree
        other = self.root / "pass-wt"
        self.git("worktree", "add", "-q", "--detach", str(other), self.one)
        path = other / "tmp" / "captain" / "r1" / "tests" / f"{self.one}.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"sha": self.one,
                                    "commands": [{"cmd": "./run-tests.sh", "exit": 0}]}))
        self.assertIn(f"cowboy green {self.one[:12]}", self.cowboy(f"green {self.one}"))

    def test_missing_file(self):
        self.refused(self.cowboy(f"green {self.one}"), "no test result file")

    def test_unreadable_file(self):
        self.result_file(self.one, raw="{broken")
        self.refused(self.cowboy(f"green {self.one}"), "unreadable")

    def test_file_for_another_sha(self):
        self.result_file(self.one, named="0" * 40)
        self.refused(self.cowboy(f"green {self.one}"), "names another SHA")

    def test_no_commands(self):
        self.result_file(self.one, commands=[])
        self.refused(self.cowboy(f"green {self.one}"), "lists no commands")

    def test_a_failed_command(self):
        self.result_file(self.one, [{"cmd": "./run-tests.sh", "exit": 0},
                                    {"cmd": "npm run build", "exit": 1}])
        self.refused(self.cowboy(f"green {self.one}"), "npm run build")

    def test_head_not_at_the_sha(self):
        self.commit("cow two")
        self.result_file(self.one)
        self.refused(self.cowboy(f"green {self.one}"), "HEAD")

    def test_not_a_cowboy_tip(self):
        self.git("checkout", "-q", "dev")
        dev = self.git("rev-parse", "HEAD")
        self.result_file(dev)
        note = self.cowboy(f"green {dev}")
        self.git("checkout", "-q", "captain/cow")
        self.refused(note, "no cowboy branch has its tip")

    def test_bad_forms_change_nothing(self):
        for args in ("green", "on ..bad", "off x"):
            with self.subTest(args=args):
                self.assertIn("cowboy NOT changed", self.cowboy(args))

    def test_cowboy_on_names_a_branch_from_another_checkout(self):
        self.git("branch", "captain/cow2", "dev")
        self.git("checkout", "-q", "dev")  # main's checkout on the base; the branch elsewhere
        self.assertIn("cowboy on for `captain/cow2`", self.cowboy("on captain/cow2"))
        self.assertIn("cowboy NOT on", self.cowboy("on missing-branch"))
        self.assertIn("cowboy NOT on", self.cowboy("on dev"))

    def test_cowboy_on_refuses_the_base_and_main(self):
        for branch in ("dev", "main"):
            with self.subTest(branch=branch):
                self.git("checkout", "-q", branch)
                self.assertIn("cowboy NOT on", self.cowboy("on"))


class RunEndCowboyTest(CowboyBase):
    """check-run-end.py check 5 on the TODO file of the same repository."""

    RUN_MD = """# captain run 20261030-155634
- Mode: {mode}   Box: none

## Tasks
| ID | Task | Group | Touches | After | Agent | State |
|---|---|---|---|---|---|---|
| ZD1 | first | g1 | `a.py` | - | w-a | merged |
"""

    def check(self, mode: str = "cowboy, tests: night", todo: str = "# TODO\n"):
        run_dir = self.root / "run"
        run_dir.mkdir(exist_ok=True)
        (run_dir / "run.md").write_text(self.RUN_MD.format(mode=mode), encoding="utf-8")
        todo_path = self.repo / "docs" / "plans" / "TODO.md"
        todo_path.parent.mkdir(parents=True, exist_ok=True)
        todo_path.write_text(todo, encoding="utf-8")
        return subprocess.run([sys.executable, str(CHECK), f"--run-dir={run_dir}",
                               f"--todo={todo_path}"], capture_output=True, text=True,
                              env={**os.environ, "CAPTAIN_STATE_DIR": str(self.state)})

    def test_untested_cowboy_run_needs_its_todo_entry(self):
        self.start_cowboy()
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("MISSING cowboy captain/cow", result.stdout)
        # the KB6 entry's reason `skipped test pass` is outside the TP6 list; the check takes it
        result = self.check(todo="# TODO\n\n- **KP30** captain/cow at abc123: run the tests "
                                 "before the merge into dev — deferred: skipped test pass "
                                 "(2026-10-30).\n")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("UNTESTED captain/cow", result.stdout)

    def test_a_merge_without_green_is_a_problem_in_every_run(self):
        self.start_cowboy()
        self.git("checkout", "-q", "dev")
        self.git("merge", "-q", "--no-ff", "-m", "wrong", "captain/cow")
        result = self.check(mode="present", todo="# TODO\n")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("COWBOY captain/cow — `dev` holds untested cowboy commits", result.stdout)

    def test_a_sync_from_the_base_is_no_leak(self):
        self.start_cowboy()
        self.git("checkout", "-q", "dev")
        self.commit("dev own")
        self.git("checkout", "-q", "captain/cow")
        self.git("merge", "-q", "--no-ff", "-m", "sync base", "dev")
        result = self.check(mode="present")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("COWBOY", result.stdout)

    def test_a_green_cowboy_run_passes_without_an_entry(self):
        one = self.start_cowboy()
        self.green(one)
        self.git("checkout", "-q", "dev")
        self.git("merge", "-q", "--no-ff", "-m", "tested", "captain/cow")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("UNTESTED", result.stdout)
        self.assertNotIn("COWBOY", result.stdout)

    def test_no_record_is_no_problem(self):
        result = self.check(mode="present")
        self.assertEqual(result.returncode, 0, result.stdout)


class StartWordTest(unittest.TestCase):
    """r1 F5: a kickoff with the cowboy words is a new run (audit-main.py starts_run)."""

    def test_cowboy_words_start_a_run(self):
        spec = importlib.util.spec_from_file_location("audit_main", AUDIT)
        audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audit)
        for args in ("cowboy", "1h cowboy tests=night", "каубойски", "каубой tests=merge"):
            with self.subTest(args=args):
                self.assertTrue(audit.starts_run(args))
        self.assertFalse(audit.starts_run("tests=later"))
        self.assertFalse(audit.starts_run("cowboy on"))


if __name__ == "__main__":
    unittest.main()
