#!/usr/bin/env python3
"""Tests for the captain automatic base branch (БР1) in hooks/guard.py.

A model-made Skill call `captain base <branch>` records the run's base only while АБ1–АБ6
hold at that moment: a named branch that is not the default, a working `git fetch origin
<default>`, HEAD on the fetched tip, no other origin/<branch>, not checked out elsewhere, a
clean tree. The owner's typed `/captain base <branch>` skips АБ2–АБ6. Every case runs on a
temporary repository with a local bare origin; nothing reaches the network.

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
    """The table over АБ1–АБ6, for the Skill path and the typed path."""

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
        # sessions often run in a linked worktree; АБ5 must not count the session's own one
        linked = self.root / "linked"
        self.git(self.repo, "worktree", "add", "-q", "-b", "feat2", str(linked), "origin/main")
        return linked, "feat2"

    def case_with_a_commit(self):
        (self.repo / "a.txt").write_text("mine\n")
        self.git(self.repo, "commit", "-q", "-am", "mine")
        return self.repo, "feat"

    def case_behind(self):
        # local origin/main still equals HEAD; only the fetch shows that origin moved on
        self.seed_commit("main")
        return self.repo, "feat"

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

    def case_checked_out_elsewhere(self):
        other = self.root / "other"
        self.git(self.repo, "worktree", "add", "-q", "-f", str(other), "feat")
        return self.repo, "feat"

    def case_dirty_tree(self):
        (self.repo / "a.txt").write_text("edited\n")
        return self.repo, "feat"

    def case_untracked_file(self):
        (self.repo / "new.txt").write_text("new\n")
        return self.repo, "feat"

    def case_run_state_only(self):
        # main wrote its run state before start step 5, in a repo that does not ignore tmp/
        run = self.repo / "tmp" / "captain" / "20261013-150626"
        run.mkdir(parents=True)
        (run / "run.md").write_text("# captain run\n")
        return self.repo, "feat"

    def case_local_settings_only(self):
        # start step 3 wrote the permissions, in a repo that does not ignore the file
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "settings.local.json").write_text("{}\n")
        return self.repo, "feat"

    def case_tracked_local_settings(self):
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "settings.local.json").write_text("{}\n")
        self.git(self.repo, "add", ".claude/settings.local.json")
        return self.repo, "feat"

    def case_tracked_change_under_run_state(self):
        run = self.repo / "tmp" / "captain"
        run.mkdir(parents=True)
        (run / "kept.md").write_text("one\n")
        self.git(self.repo, "add", "tmp/captain/kept.md")
        self.git(self.repo, "commit", "-q", "-m", "kept")
        self.git(self.repo, "reset", "-q", "--soft", "HEAD~1")  # back on the tip, file staged
        return self.repo, "feat"

    def case_other_branch_named(self):
        self.git(self.repo, "branch", "other")
        return self.repo, "other"

    def case_no_origin_head(self):
        self.git(self.repo, "symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
        self.git(self.repo, "switch", "-q", "-c", "captain/x")
        return self.repo, "captain/x"

    # case, Skill path records?, АБ named in a refusal, typed path records?
    TABLE = [
        ("on_tip", True, None, True),
        ("linked_worktree_on_tip", True, None, True),
        ("with_a_commit", False, "АБ3", True),
        ("behind", False, "АБ3", True),
        ("default_branch", False, "АБ1", False),
        ("detached_head", False, "АБ1", True),
        ("fetch_failure", False, "АБ2", True),
        ("remote_branch_ahead", False, "АБ4", True),
        ("remote_branch_on_the_same_sha", True, None, True),
        ("checked_out_elsewhere", False, "АБ5", True),
        ("dirty_tree", False, "АБ6", True),
        ("untracked_file", False, "АБ6", True),
        ("run_state_only", True, None, True),
        ("tracked_change_under_run_state", False, "АБ6", True),
        ("local_settings_only", True, None, True),
        ("tracked_local_settings", False, "АБ6", True),
        ("other_branch_named", False, "АБ1", True),
        ("no_origin_head", False, "АБ1", True),
    ]

    def test_the_table(self):
        for name, records, rule, typed_records in self.TABLE:
            for form in ("base {}", "base={}"):
                with self.subTest(case=name, form=form):
                    self.tmp.cleanup()
                    self.setUp()
                    directory, branch = getattr(self, f"case_{name}")()
                    base, stdout = self.skill(form.format(branch), directory)
                    note = self.note(stdout)
                    if records:
                        self.assertEqual(base["branch"], branch, note)
                        self.assertTrue(base["auto"])
                        self.assertIn("recorded (АБ1–АБ6 hold)", note)
                    else:
                        self.assertIsNone(base, note)
                        self.assertIn(f"NOT recorded ({rule}", note)
                    typed = self.typed(f"/captain {form.format(branch)}", directory)
                    if typed_records:
                        self.assertEqual(typed["branch"], branch)
                        self.assertFalse(typed["auto"])
                    else:
                        self.assertIsNone(typed)

    def test_a_model_call_never_records_a_protected_branch(self):
        for branch in ("main", "master"):
            with self.subTest(branch=branch):
                self.git(self.repo, "switch", "-q", "-C", branch, "origin/main")
                base, stdout = self.skill(f"base {branch}")
                self.assertIsNone(base)
                self.assertIn("NOT recorded (АБ1", self.note(stdout))
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

    # ---- review round 1 regressions

    def load_guard(self):
        spec = importlib.util.spec_from_file_location("captain_guard", GUARD)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_a_head_that_moves_during_the_network_calls_is_refused(self):  # r1 F1
        guard = self.load_guard()
        real = guard.fetched_tip
        for move in (["switch", "-q", "main"], ["switch", "-q", "-c", "other"],
                     ["switch", "-q", "--detach"]):
            with self.subTest(move=move):
                self.git(self.repo, "switch", "-q", "feat")

                def fetched(directory, default, move=move):
                    tip = real(directory, default)
                    self.git(self.repo, *move)
                    return tip

                guard.fetched_tip = fetched
                self.assertIn("АБ1", guard.auto_base_problem(str(self.repo), "feat") or "")
        guard.fetched_tip = real
        self.git(self.repo, "switch", "-q", "feat")
        self.assertIsNone(guard.auto_base_problem(str(self.repo), "feat"))

    def test_the_live_origin_default_is_never_a_base(self):  # r1 F2
        # origin switched its default to trunk after the clone; the local origin/HEAD says main
        self.git(self.seed, "push", "-q", "origin", "main:trunk")
        self.git(self.origin, "symbolic-ref", "HEAD", "refs/heads/trunk")
        self.git(self.repo, "switch", "-q", "-c", "trunk")
        base, stdout = self.skill("base trunk")
        self.assertIsNone(base)
        self.assertIn("NOT recorded (АБ1", self.note(stdout))

    def test_another_fetch_cannot_change_the_compared_sha(self):  # r1 F3
        (self.repo / "a.txt").write_text("mine\n")
        self.git(self.repo, "commit", "-q", "-am", "mine")
        head = self.git(self.repo, "rev-parse", "HEAD")
        guard = self.load_guard()
        real = guard.subprocess.run

        def run(argv, *args, **kwargs):
            result = real(argv, *args, **kwargs)
            if "fetch" in argv:  # a parallel fetch rewrites FETCH_HEAD with the branch's SHA
                fetch_head = self.git(self.repo, "rev-parse", "--git-path", "FETCH_HEAD")
                (self.repo / fetch_head).write_text(f"{head}\t\tbranch 'feat'\n")
            return result

        guard.subprocess.run = run
        try:
            self.assertIn("АБ3", guard.auto_base_problem(str(self.repo), "feat") or "")
        finally:
            guard.subprocess.run = real
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
