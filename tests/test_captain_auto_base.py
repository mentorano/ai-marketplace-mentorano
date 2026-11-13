#!/usr/bin/env python3
"""Tests for the captain start branch as the base branch (KB9) in hooks/guard.py.

At start step 5 main judges the start branch (a work branch, or an integration branch it asks
about) and makes the Skill call `captain base <branch>`. The guard records it only while the
hard checks hold at that moment: HEAD is that branch, not main, master, the origin default or
detached; origin is readable; origin has no <branch>, or origin/<branch> is an ancestor of
HEAD; it is not checked out in another worktree. Then a start branch behind origin/<default>
with no commits of its own is fast-forwarded. A protected branch → ask the owner; any other
failed check → the fallback with no question and no base. The owner's typed `/captain base
<branch>` is the override. Every case runs on a temporary repository with a local bare
origin; nothing reaches the network.

Run:  python3 tests/test_captain_auto_base.py
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
HOOKS_JSON = ROOT / "plugins" / "captain" / "hooks" / "hooks.json"
SESSION = "5b0c2a4e-7d1f-4c39-9a2e-0f6b7f3d1a10"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}


class AutoBaseTest(unittest.TestCase):
    """The table over the KB9 start-branch checks, for the Skill path and the typed path."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.origin = self.root / "origin.git"
        self.seed = self.root / "seed"
        self.repo = self.root / "repo"
        self.git(self.root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(self.root, "init", "-q", "-b", "main", str(self.seed))
        (self.seed / "a.txt").write_text("one\n")
        self.git(self.seed, "add", "a.txt")
        self.git(self.seed, "commit", "-q", "-m", "one")
        self.git(self.seed, "remote", "add", "origin", str(self.origin))
        self.git(self.seed, "push", "-q", "origin", "main")
        self.git(self.root, "clone", "-q", str(self.origin), str(self.repo))  # sets origin/HEAD
        # the host's global ignore rules must not hide the untracked files the table creates
        self.git(self.repo, "config", "core.excludesFile", os.devnull)
        self.git(self.repo, "switch", "-q", "-c", "feat")
        self.runs = 0

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, directory: Path, *args: str) -> str:
        return subprocess.run(["git", "-C", str(directory), *args], check=True, text=True,
                              capture_output=True, env={**os.environ, **GIT_ENV}).stdout.strip()

    def seed_commit(self, ref: str = "main") -> None:
        """A new commit on origin's `ref`, made in the seed clone; the repo does not fetch it."""
        self.git(self.seed, "switch", "-q", "-C", ref, "main")
        (self.seed / "a.txt").write_text(f"{ref} two\n")
        self.git(self.seed, "commit", "-q", "-am", "two")
        self.git(self.seed, "push", "-q", "-f", "origin", ref)
        self.git(self.seed, "switch", "-q", "main")

    def hook(self, event: dict, cwd: Path) -> tuple[dict | None, str]:
        """Run the guard with a fresh state directory; (the .base record, stdout)."""
        self.runs += 1
        state = self.root / f"state-{self.runs}"
        event = {"session_id": SESSION, "cwd": str(cwd), **event}
        result = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event),
                                capture_output=True, text=True, timeout=60,
                                env={**os.environ, "CAPTAIN_STATE_DIR": str(state)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        path = state / f"{SESSION}.base"
        return (json.loads(path.read_text()) if path.is_file() else None), result.stdout

    def skill(self, args: str, cwd: Path | None = None) -> tuple[dict | None, str]:
        return self.hook({"hook_event_name": "PostToolUse", "tool_name": "Skill",
                          "tool_input": {"skill": "captain:captain", "args": args}},
                         cwd or self.repo)

    def typed(self, text: str, cwd: Path | None = None) -> dict | None:
        return self.hook({"hook_event_name": "UserPromptSubmit", "prompt": text},
                         cwd or self.repo)[0]

    def note(self, stdout: str) -> str:
        output = json.loads(stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PostToolUse")
        return output["additionalContext"]

    # ---- the cases; each returns (directory, branch named in the args)

    def case_on_tip(self):
        return self.repo, "feat"

    def case_linked_worktree_on_tip(self):
        # sessions often run in a linked worktree; AB5 must not count the session's own one
        linked = self.root / "linked"
        self.git(self.repo, "worktree", "add", "-q", "-b", "feat2", str(linked), "origin/main")
        return linked, "feat2"

    def case_with_a_commit(self):
        # a real base branch may have commits of its own (AB3 dropped)
        (self.repo / "a.txt").write_text("mine\n")
        self.git(self.repo, "commit", "-q", "-am", "mine")
        return self.repo, "feat"

    def case_behind(self):
        # local origin/main still equals HEAD; only the fetch shows that origin moved on
        self.seed_commit("main")
        return self.repo, "feat"

    def case_behind_with_a_conflicting_edit(self):
        self.seed_commit("main")
        (self.repo / "a.txt").write_text("edited\n")  # the fast-forward would overwrite it
        return self.repo, "feat"

    def case_diverged_from_the_default(self):
        self.seed_commit("main")
        return self.case_with_a_commit()

    def case_default_branch(self):
        self.git(self.repo, "switch", "-q", "main")
        return self.repo, "main"

    def case_detached_head(self):
        self.git(self.repo, "switch", "-q", "--detach")
        return self.repo, "feat"

    def case_fetch_failure(self):
        self.git(self.repo, "remote", "set-url", "origin", str(self.root / "missing.git"))
        return self.repo, "feat"

    def case_remote_branch_ahead(self):
        self.seed_commit("feat")  # never fetched into the repo: the guard asks origin itself
        return self.repo, "feat"

    def case_remote_branch_on_the_same_sha(self):
        self.git(self.seed, "push", "-q", "origin", "main:feat")
        return self.repo, "feat"

    def case_remote_branch_behind_the_local_tip(self):
        self.git(self.seed, "push", "-q", "origin", "main:feat")
        return self.case_with_a_commit()

    def case_checked_out_elsewhere(self):
        other = self.root / "other"
        self.git(self.repo, "worktree", "add", "-q", "-f", str(other), "feat")
        return self.repo, "feat"

    def case_dirty_tree(self):
        # AB6 dropped: uncommitted files are a question at start, not a guard check
        (self.repo / "a.txt").write_text("edited\n")
        return self.repo, "feat"

    def case_untracked_file(self):
        (self.repo / "new.txt").write_text("new\n")
        return self.repo, "feat"

    def case_other_branch_named(self):
        self.git(self.repo, "branch", "other")
        return self.repo, "other"

    def case_no_origin_head(self):
        self.git(self.repo, "symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
        self.git(self.repo, "switch", "-q", "-c", "captain/x")
        return self.repo, "captain/x"

    # case, Skill path outcome (recorded | protected | fallback), the text in the note, typed
    # path records?
    TABLE = [
        ("on_tip", "recorded", "(KB9 checks hold).", True),
        ("linked_worktree_on_tip", "recorded", "(KB9 checks hold).", True),
        ("with_a_commit", "recorded", "(KB9 checks hold).", True),
        ("behind", "recorded", "fast-forwarded to origin/main", True),
        ("behind_with_a_conflicting_edit", "recorded", "fast-forward to origin/main", True),
        ("diverged_from_the_default", "recorded", "(KB9 checks hold).", True),
        ("default_branch", "protected", "AB1", False),
        ("detached_head", "fallback", "AB1", True),
        ("fetch_failure", "fallback", "origin:", True),
        ("remote_branch_ahead", "fallback", "not an ancestor of HEAD", True),
        ("remote_branch_on_the_same_sha", "recorded", "(KB9 checks hold).", True),
        ("remote_branch_behind_the_local_tip", "recorded", "(KB9 checks hold).", True),
        ("checked_out_elsewhere", "fallback", "AB5", True),
        ("dirty_tree", "recorded", "(KB9 checks hold).", True),
        ("untracked_file", "recorded", "(KB9 checks hold).", True),
        ("other_branch_named", "fallback", "AB1", True),
        ("no_origin_head", "protected", "AB1", True),
    ]

    def test_the_table(self):
        for name, outcome, text, typed_records in self.TABLE:
            for form in ("base {}", "base={}"):
                with self.subTest(case=name, form=form):
                    self.tmp.cleanup()
                    self.setUp()
                    directory, branch = getattr(self, f"case_{name}")()
                    base, stdout = self.skill(form.format(branch), directory)
                    note = self.note(stdout)
                    self.assertIn(text, note)
                    if outcome == "recorded":
                        self.assertEqual(base["branch"], branch, note)
                        self.assertTrue(base["auto"])
                        self.assertIn(f"base `{branch}` recorded (KB9 checks hold)", note)
                    else:
                        self.assertIsNone(base, note)
                        self.assertIn(f"base `{branch}` NOT recorded (", note)
                        self.assertIn("Protected start branch" if outcome == "protected"
                                      else "Fallback, no question", note)
                    if outcome == "fallback":
                        self.assertIn(f"the HEAD of `{branch}`", note)
                        self.assertIn(f"`/captain merge {branch}`", note)
                    if outcome == "protected":
                        self.assertNotIn("Fallback", note)
                    typed = self.typed(f"/captain {form.format(branch)}", directory)
                    if typed_records:
                        self.assertEqual(typed["branch"], branch)
                        self.assertFalse(typed["auto"])
                    else:
                        self.assertIsNone(typed)

    def test_a_start_branch_behind_the_default_is_fast_forwarded(self):
        self.seed_commit("main")
        tip = self.git(self.seed, "rev-parse", "main")
        base, stdout = self.skill("base feat")
        self.assertEqual(base["branch"], "feat")
        self.assertIn(f"fast-forwarded to origin/main ({tip[:12]})", self.note(stdout))
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD"), tip)
        self.assertEqual(self.git(self.repo, "symbolic-ref", "--short", "HEAD"), "feat")

    def test_a_branch_with_commits_of_its_own_is_never_moved(self):
        self.case_diverged_from_the_default()
        head = self.git(self.repo, "rev-parse", "HEAD")
        base, stdout = self.skill("base feat")
        self.assertEqual(base["branch"], "feat")
        self.assertNotIn("fast-forward", self.note(stdout))
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD"), head)

    def test_a_failed_fast_forward_keeps_the_base_and_says_stop(self):
        self.case_behind_with_a_conflicting_edit()
        head = self.git(self.repo, "rev-parse", "HEAD")
        base, stdout = self.skill("base feat")
        note = self.note(stdout)
        self.assertEqual(base["branch"], "feat")
        self.assertIn("fast-forward to origin/main", note)
        self.assertIn("FAILED", note)
        self.assertIn("Stop and tell the owner", note)
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD"), head)
        self.assertEqual((self.repo / "a.txt").read_text(), "edited\n")

    def test_a_start_alone_records_no_base(self):
        # the integration-branch judgment (develop, staging, release/*) is main's at start
        # step 5: no Skill call `captain base <branch>`, no base; the owner's typed yes records
        for name in ("develop", "release/2026.10"):
            with self.subTest(branch=name):
                self.git(self.repo, "switch", "-q", "-C", name, "origin/main")
                self.assertIsNone(self.typed("/captain 1h"))
                self.assertIsNone(self.skill("1h")[0])
                self.assertEqual(self.typed(f"/captain base {name}")["branch"], name)

    def test_a_model_call_never_records_a_protected_branch(self):
        for branch in ("main", "master"):
            with self.subTest(branch=branch):
                self.git(self.repo, "switch", "-q", "-C", branch, "origin/main")
                base, stdout = self.skill(f"base {branch}")
                self.assertIsNone(base)
                self.assertIn("NOT recorded (AB1", self.note(stdout))
                self.assertIn("Protected start branch", self.note(stdout))
        # the origin default under another name
        self.git(self.seed, "push", "-q", "origin", "main:trunk")
        self.git(self.repo, "fetch", "-q", "origin")
        self.git(self.repo, "remote", "set-head", "origin", "trunk")
        self.git(self.repo, "switch", "-q", "-c", "trunk", "origin/trunk")
        base, _ = self.skill("base trunk")
        self.assertIsNone(base)

    def test_a_merge_into_the_auto_base_passes(self):
        state = self.root / "state-merge"
        env = {**os.environ, "CAPTAIN_STATE_DIR": str(state)}

        def run(event: dict) -> str:
            event = {"session_id": SESSION, "cwd": str(self.repo), **event}
            return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event),
                                  capture_output=True, text=True, timeout=60, env=env).stdout

        self.git(self.repo, "branch", "topic")
        run({"hook_event_name": "UserPromptSubmit", "prompt": "/captain 1h"})
        merge = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                 "tool_input": {"command": "git merge --no-ff --no-edit topic"}}
        self.assertIn('"deny"', run(merge))
        run({"hook_event_name": "PostToolUse", "tool_name": "Skill",
             "tool_input": {"skill": "captain", "args": "base feat"}})
        self.assertEqual(run(merge).strip(), "")

    def shared_state(self):
        """A guard runner over one state directory for the whole test: (run, the .base path)."""
        state = self.root / "state-shared"
        env = {**os.environ, "CAPTAIN_STATE_DIR": str(state)}

        def run(event: dict) -> str:
            event = {"session_id": SESSION, "cwd": str(self.repo), **event}
            result = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event),
                                    capture_output=True, text=True, timeout=60, env=env)
            self.assertEqual(result.stderr, "")
            return result.stdout

        return run, state / f"{SESSION}.base"

    def test_a_base_of_an_earlier_run_does_not_count(self):  # KB9 review r1 F1
        run, _ = self.shared_state()
        self.git(self.repo, "branch", "topic")
        merge = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                 "tool_input": {"command": "git merge --no-ff --no-edit topic"}}
        base = {"hook_event_name": "PostToolUse", "tool_name": "Skill",
                "tool_input": {"skill": "captain", "args": "base feat"}}
        run({"hook_event_name": "UserPromptSubmit", "prompt": "/captain 1h"})
        self.assertIn("recorded (KB9 checks hold)", self.note(run(base)))
        self.assertEqual(run(merge).strip(), "")
        # a new start in the same session; this time the check fails → the fallback, no base
        run({"hook_event_name": "UserPromptSubmit", "prompt": "/captain 1h"})
        self.git(self.repo, "remote", "set-url", "origin", str(self.root / "missing.git"))
        self.assertIn("Fallback, no question", self.note(run(base)))
        self.assertIn('"deny"', run(merge))

    def test_a_typed_base_of_this_run_stays(self):  # KB9 review r1 F2
        run, path = self.shared_state()
        self.git(self.repo, "branch", "other")
        base = {"hook_event_name": "PostToolUse", "tool_name": "Skill",
                "tool_input": {"skill": "captain", "args": "base feat"}}
        run({"hook_event_name": "UserPromptSubmit", "prompt": "/captain 1h base=other"})
        note = self.note(run(base))
        self.assertIn("typed base `other` of this run stays", note)
        record = json.loads(path.read_text())
        self.assertEqual((record["branch"], record["auto"]), ("other", False))
        # a new start: the typed base of the earlier run is no override any more
        run({"hook_event_name": "UserPromptSubmit", "prompt": "/captain 1h"})
        self.assertIn("recorded (KB9 checks hold)", self.note(run(base)))
        self.assertEqual(json.loads(path.read_text())["branch"], "feat")

    # ---- review round 1 regressions

    def load_guard(self):
        spec = importlib.util.spec_from_file_location("captain_guard", GUARD)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_a_head_that_moves_during_the_network_calls_is_refused(self):  # r1 F1
        guard = self.load_guard()
        real = guard.fetched_tips
        for move in (["switch", "-q", "main"], ["switch", "-q", "-c", "other"],
                     ["switch", "-q", "--detach"]):
            with self.subTest(move=move):
                self.git(self.repo, "switch", "-q", "feat")

                def fetched(directory, branches, move=move):
                    tips = real(directory, branches)
                    self.git(self.repo, *move)
                    return tips

                guard.fetched_tips = fetched
                self.assertIn("AB1", guard.start_base_check(str(self.repo), "feat").problem or "")
        guard.fetched_tips = real
        self.git(self.repo, "switch", "-q", "feat")
        self.assertIsNone(guard.start_base_check(str(self.repo), "feat").problem)

    def test_the_live_origin_default_is_never_a_base(self):  # r1 F2
        # origin switched its default to trunk after the clone; the local origin/HEAD says main
        self.git(self.seed, "push", "-q", "origin", "main:trunk")
        self.git(self.origin, "symbolic-ref", "HEAD", "refs/heads/trunk")
        self.git(self.repo, "switch", "-q", "-c", "trunk")
        base, stdout = self.skill("base trunk")
        self.assertIsNone(base)
        self.assertIn("NOT recorded (AB1", self.note(stdout))

    def test_another_fetch_cannot_change_the_compared_sha(self):  # r1 F3
        # a parallel fetch rewrites FETCH_HEAD with the old SHA; the check and the
        # fast-forward use the guard's own refs, so HEAD still reaches the real origin tip
        self.seed_commit("main")
        tip = self.git(self.seed, "rev-parse", "main")
        head = self.git(self.repo, "rev-parse", "HEAD")
        guard = self.load_guard()
        real = guard.subprocess.run

        def run(argv, *args, **kwargs):
            result = real(argv, *args, **kwargs)
            if "fetch" in argv:
                fetch_head = self.git(self.repo, "rev-parse", "--git-path", "FETCH_HEAD")
                (self.repo / fetch_head).write_text(f"{head}\t\tbranch 'main'\n")
            return result

        guard.subprocess.run = run
        try:
            check = guard.start_base_check(str(self.repo), "feat")
        finally:
            guard.subprocess.run = real
        self.assertIsNone(check.problem)
        self.assertEqual(check.tip, tip)
        self.assertEqual(self.git(self.repo, "for-each-ref", "refs/captain-guard"), "")

    def test_a_checkout_path_with_a_newline_is_its_own_worktree(self):  # r1 F5
        # without -z, `git worktree list --porcelain` splits this path over two lines
        quoted = self.root / 'a"b\nc'
        self.git(self.root, "clone", "-q", str(self.origin), str(quoted))
        self.git(quoted, "config", "core.excludesFile", os.devnull)
        self.git(quoted, "switch", "-q", "-c", "feat")
        base, stdout = self.skill("base feat", quoted)
        self.assertEqual(base["branch"], "feat", self.note(stdout))

    def test_the_skill_hook_has_an_explicit_timeout(self):
        hooks = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]
        entry = hooks["PostToolUse"][0]
        self.assertEqual(entry["matcher"], "Skill")
        self.assertEqual(entry["hooks"][0]["timeout"], 30)


if __name__ == "__main__":
    unittest.main()
