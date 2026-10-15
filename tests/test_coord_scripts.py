#!/usr/bin/env python3
"""Tests for plugins/coord/skills/coord/scripts/*.

Every fixture is a real, throwaway git repository (and, for the hooks, a temp $HOME), because the
bugs pinned down here only show up against real git topologies and real ~/.claude layouts. No
network, no real ~/.claude is touched - HOME is always redirected to a tempdir first.

Run:  python3 tests/test_coord_scripts.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "plugins" / "coord" / "skills" / "coord" / "scripts"
DERIVE_STATE = SCRIPTS / "derive-state.sh"
INSTALL_HOOKS = SCRIPTS / "install-hooks.sh"
KICKOFF_HOOK = SCRIPTS / "hooks" / "kickoff-on-clear.py"
HANDOFF_HOOK = SCRIPTS / "hooks" / "handoff-at-boundary.py"
MEASURE_CONTEXT = SCRIPTS / "measure-context.py"
COST_REPORT = SCRIPTS / "cost-report.py"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Tester", "GIT_AUTHOR_EMAIL": "t@t.t",
    "GIT_COMMITTER_NAME": "Tester", "GIT_COMMITTER_EMAIL": "t@t.t",
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(cwd, *args, env=None, check=True):
    e = dict(os.environ)
    e.update(GIT_ENV)
    if env:
        e.update(env)
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=e, timeout=30)
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} -> rc={p.returncode} stderr={p.stderr}")
    return p


def init_repo(path: Path, branch: str = "main") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    run(path, "git", "init", "-q", "-b", branch, str(path))
    run(path, "git", "commit", "-q", "--allow-empty", "-m", "init")
    return path


@contextlib.contextmanager
def temp_home():
    """A temp $HOME, so hooks that read ~/.claude/* never touch the real one."""
    with tempfile.TemporaryDirectory() as td:
        old = os.environ.get("HOME")
        os.environ["HOME"] = td
        try:
            yield Path(td)
        finally:
            if old is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old


def derive_state(repo, *extra, cwd=None, env=None):
    p = run(cwd or "/tmp", "bash", str(DERIVE_STATE), str(repo), *extra, env=env, check=False)
    return p.stdout + p.stderr


class DeriveStateSyntaxTest(unittest.TestCase):
    def test_bash_syntax(self):
        p = subprocess.run(["bash", "-n", str(DERIVE_STATE)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)


class F4MergeDetectionTest(unittest.TestCase):
    """derive-state.sh line ~63: a staged merge must be detected from outside the repo."""

    def test_merge_head_detected_when_run_from_outside_repo(self):
        with tempfile.TemporaryDirectory() as td:
            repo = init_repo(Path(td) / "repo")
            run(repo, "git", "checkout", "-q", "-b", "feat")
            (repo / "f.txt").write_text("x\n")
            run(repo, "git", "add", "f.txt")
            run(repo, "git", "commit", "-q", "-m", "feat")
            run(repo, "git", "checkout", "-q", "main")
            (repo / "f.txt").write_text("y\n")
            run(repo, "git", "add", "f.txt")
            run(repo, "git", "commit", "-q", "-m", "mainchange")
            run(repo, "git", "merge", "--no-commit", "feat", check=False)
            self.assertTrue((repo / ".git" / "MERGE_HEAD").exists(), "setup: expected a staged merge")
            # cwd is OUTSIDE the repo entirely - this is exactly the bug scenario.
            out = derive_state(repo, cwd="/tmp")
            self.assertIn("MERGE IN PROGRESS", out, out)


class F5WorktreeMatchingTest(unittest.TestCase):
    """derive-state.sh: REPO must be absolute, and worktree/process matching must be exact,
    not a string prefix (a "<project>-wt" sibling must not match "<project>")."""

    def _spawn_fake(self, cwd: Path, name: str):
        script = cwd / f"fake_{name}.sh"
        script.write_text(f"#!/bin/bash\nexec -a {name} sleep 30\n")
        script.chmod(0o755)
        proc = subprocess.Popen([str(script)], cwd=str(cwd))
        time.sleep(0.4)  # give lsof/pgrep time to see the new process's cwd
        return proc

    def test_sibling_wt_directory_is_not_flagged_and_own_process_is(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(os.path.realpath(td))
            proj = init_repo(td / "proj")
            lane = td / "proj-wt" / "lane1"
            lane.mkdir(parents=True)
            proc = self._spawn_fake(lane, "pytest")
            try:
                out = derive_state(proj)
                if "process scan unavailable" in out:
                    self.skipTest("this environment denies the process list (pgrep), so the "
                                  "checkout process check cannot run here")
                self.assertNotIn("RUNNING in checkout", out,
                                  "a process in the sibling '-wt' dir must not match REPO by prefix")
                # Running derive-state.sh against the lane itself (with a RELATIVE "." REPO
                # argument) must still find its own process - proves REPO was made absolute.
                out2 = derive_state(".", cwd=lane)
                self.assertIn("RUNNING in checkout", out2)
                self.assertIn(str(proc.pid), out2)
            finally:
                proc.kill()
                proc.wait(timeout=5)

    def test_repo_argument_is_resolved_to_absolute_path(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(os.path.realpath(td))
            repo = init_repo(td / "proj")
            out = derive_state(".", cwd=repo)
            self.assertIn("== worktrees ==", out)
            self.assertIn(str(repo), out)


class ProcessScanFailureTest(unittest.TestCase):
    """derive-state.sh: a pgrep that cannot list processes (exit >= 2, e.g. in a sandbox) must
    be reported, not read as "no test runner in the checkout"."""

    def _derive_with_pgrep(self, rc: int, stderr: str) -> str:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            repo = init_repo(td / "repo")
            stubs = td / "bin"
            stubs.mkdir()
            pgrep = stubs / "pgrep"
            pgrep.write_text(f"#!/bin/bash\necho '{stderr}' >&2\nexit {rc}\n")
            pgrep.chmod(0o755)
            return derive_state(repo, env={"PATH": f"{stubs}:{os.environ['PATH']}"})

    def test_pgrep_that_cannot_list_processes_is_reported(self):
        out = self._derive_with_pgrep(3, "pgrep: Cannot get process list")
        self.assertIn("!! process scan unavailable (pgrep exit 3)", out)

    def test_pgrep_with_no_match_is_not_reported(self):
        out = self._derive_with_pgrep(1, "")
        self.assertNotIn("process scan unavailable", out)


class F14ConfigCommentTest(unittest.TestCase):
    """The config key() reader must strip a trailing ` # comment`, not treat it as part of the value."""

    def test_inline_comment_does_not_leak_into_integration_branch(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            origin = td / "origin.git"
            run(td, "git", "init", "-q", "--bare", str(origin))
            repo = init_repo(td / "repo")
            run(repo, "git", "remote", "add", "origin", str(origin))
            run(repo, "git", "push", "-q", "-u", "origin", "main")
            run(repo, "git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
            (repo / ".coord").mkdir()
            (repo / ".coord" / "project.md").write_text(
                "remote: origin\nintegration_branch: main  # not yet ratified (unverified)\n")
            out = derive_state(repo)
            self.assertNotIn("no ref", out, out)
            self.assertIn("first-parent log of origin/main", out, out)


class F27FlagGuardTest(unittest.TestCase):
    """--log/--config with no value must not crash under `set -u`; worktree paths with spaces
    must not be mis-split by `read`."""

    def test_log_flag_without_value_does_not_crash(self):
        with tempfile.TemporaryDirectory() as td:
            repo = init_repo(Path(td) / "repo")
            p = run("/tmp", "bash", str(DERIVE_STATE), str(repo), "--log", check=False)
            self.assertNotIn("unbound variable", p.stderr)
            self.assertEqual(p.returncode, 2)  # usage error, not a crash

    def test_worktree_path_with_space_is_not_split(self):
        with tempfile.TemporaryDirectory() as td:
            repo = init_repo(Path(td) / "has space" / "proj")
            out = derive_state(repo)
            self.assertIn(str(repo), out)


class InstallHooksTest(unittest.TestCase):
    def setUp(self):
        self._home_cm = temp_home()
        self.home = self._home_cm.__enter__()

    def tearDown(self):
        self._home_cm.__exit__(None, None, None)

    def _settings(self):
        return json.loads((self.home / ".claude" / "settings.json").read_text())

    def test_f15_null_hooks_key_does_not_crash(self):
        (self.home / ".claude").mkdir(parents=True)
        (self.home / ".claude" / "settings.json").write_text('{"hooks": null}\n')
        p = run(None, "bash", str(INSTALL_HOOKS), check=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("SessionStart", self._settings()["hooks"])

    def test_f6_matcher_is_checked_not_just_basename(self):
        (self.home / ".claude").mkdir(parents=True)
        stale = str(self.home / "somewhere-else" / "kickoff-on-clear.py")
        (self.home / ".claude" / "settings.json").write_text(json.dumps({
            "hooks": {"SessionStart": [{"matcher": "startup",
                                         "hooks": [{"type": "command", "command": stale}]}]}}))
        run(None, "bash", str(INSTALL_HOOKS))
        matchers = {g["matcher"] for g in self._settings()["hooks"]["SessionStart"]}
        self.assertEqual(matchers, {"startup", "clear"})

    def test_f7_symlinked_settings_keeps_symlink_and_mode(self):
        real_dir = self.home / "dotfiles"
        real_dir.mkdir(parents=True)
        real = real_dir / "claude-settings.json"
        real.write_text('{"hooks": {}}\n')
        os.chmod(real, 0o600)
        (self.home / ".claude").mkdir(parents=True)
        (self.home / ".claude" / "settings.json").symlink_to(real)
        run(None, "bash", str(INSTALL_HOOKS))
        link = self.home / ".claude" / "settings.json"
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), str(real))
        self.assertEqual(oct(os.stat(real).st_mode)[-3:], "600")
        self.assertIn("kickoff-on-clear.py", real.read_text())

    def test_rerun_is_idempotent(self):
        run(None, "bash", str(INSTALL_HOOKS))
        before = self._settings()
        p = run(None, "bash", str(INSTALL_HOOKS))
        self.assertIn("settings.json unchanged", p.stdout)
        self.assertEqual(self._settings(), before)


class KickoffOnClearTest(unittest.TestCase):
    def setUp(self):
        self.mod = load_module("kickoff_on_clear", KICKOFF_HOOK)

    def _write_transcript(self, path: Path, records):
        with open(path, "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

    def test_f3_last_name_wins_even_past_the_first_50_lines(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "t.jsonl"
            records = [{"type": "assistant", "customTitle": "alpha"}]
            records += [{"type": "assistant", "text": "filler"} for _ in range(60)]
            records.append({"type": "assistant", "customTitle": "alpha-old"})  # the rename
            self._write_transcript(path, records)
            self.assertEqual(self.mod.session_name(str(path)), "alpha-old")

    def test_f3_agrees_with_measure_context_last_wins(self):
        measure = load_module("measure_context_for_agreement", MEASURE_CONTEXT)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "t.jsonl"
            self._write_transcript(path, [
                {"type": "assistant", "customTitle": "first"},
                {"type": "assistant", "customTitle": "second"},
            ])
            self.assertEqual(self.mod.session_name(str(path)), measure.session_name(str(path)))

    def test_f27_archives_do_not_collide_on_rapid_successive_clears(self):
        with temp_home() as home:
            (home / ".claude" / "kickoffs").mkdir(parents=True)
            used_names = set()
            for i in range(2):
                kfile = home / ".claude" / "kickoffs" / "sess.md"
                kfile.write_text(f"kickoff number {i}\n")
                transcript = home / f"t{i}.jsonl"
                self._write_transcript(transcript, [{"type": "assistant", "customTitle": "sess"}])
                out = subprocess.run(
                    [sys.executable, str(KICKOFF_HOOK)],
                    input=json.dumps({"source": "clear", "cwd": str(home),
                                       "transcript_path": str(transcript)}),
                    capture_output=True, text=True, env=dict(os.environ, HOME=str(home)))
                self.assertEqual(out.returncode, 0, out.stderr)
            archived = list((home / ".claude" / "kickoffs" / "kickoff-used").glob("*.md"))
            self.assertEqual(len(archived), 2, archived)
            for f in archived:
                self.assertNotIn(f.name, used_names)
                used_names.add(f.name)


class HandoffAtBoundaryTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("HANDOFF_CONTEXT_THRESHOLD", None)
        self.mod = load_module("handoff_at_boundary", HANDOFF_HOOK)

    def test_f13_task_start_table(self):
        should_match = [
            "Implement Task 3: build the login form",
            "Implement PL2-B: wire up the API client",
            "PR2 T1 fix the header",
            "implement the thing",
            "Имплементирай задача 2",
        ]
        should_not = [
            "Review Task 3",
            "Fix review findings",
            "Re-review T1",
            "Explore the codebase for auth patterns",
            "T1: address review comments",       # a fix wave for T1, not T1 starting
            "T1 fix review comment",
            "T3 add tests",                        # bare task code, no PR prefix -> not a start
            "Fix review findings for T1",
            "Re-review PR2 T1",
        ]
        for d in should_match:
            with self.subTest(desc=d):
                self.assertTrue(self.mod.TASK_START.search(d), d)
        for d in should_not:
            with self.subTest(desc=d):
                self.assertFalse(self.mod.TASK_START.search(d), d)

    def test_f10_env_overrides_config_overrides_default(self):
        with tempfile.TemporaryDirectory() as td:
            repo = init_repo(Path(td) / "repo")
            (repo / ".coord").mkdir()
            self.assertEqual(self.mod.config_threshold(str(repo)), 250000)  # no config -> default
            (repo / ".coord" / "project.md").write_text("context_threshold: 5k  # small model\n")
            self.assertEqual(self.mod.config_threshold(str(repo)), 5000)  # config, comment stripped
            os.environ["HANDOFF_CONTEXT_THRESHOLD"] = "999"
            try:
                self.assertEqual(self.mod.config_threshold(str(repo)), 999)  # env wins
            finally:
                del os.environ["HANDOFF_CONTEXT_THRESHOLD"]

    def test_f11_manual_line_names_all_three_first_messages(self):
        # The role is not guessed from cwd (sessions often run from the primary checkout),
        # so the manual line lists /coord, /coord lane and „давай“ for the session to pick.
        with tempfile.TemporaryDirectory() as td:
            repo = init_repo(Path(td) / "repo")
            (repo / ".coord").mkdir()
            (repo / ".coord" / "project.md").write_text("automation: manual\n")
            line = self.mod.handover_line(300, str(repo))
            for first in ("`/coord`", "`/coord lane`", "„давай“"):
                self.assertIn(first, line)
            self.assertNotIn("tell coord one line", line)
            (repo / ".coord" / "project.md").write_text("automation: cmux\n")
            self.assertIn("tell coord one line", self.mod.handover_line(300, str(repo)))


class MeasureContextTest(unittest.TestCase):
    def setUp(self):
        self.mod = load_module("measure_context", MEASURE_CONTEXT)

    def _write_transcript(self, path, records):
        with open(path, "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

    def test_f16_unnamed_sessions_grouped_by_session_id_not_collapsed(self):
        with temp_home():
            # self.mod.PROJECTS was bound at module-exec time (setUp, before HOME was redirected
            # here) - repoint it now so the module looks under the temp HOME, not the real one.
            self.mod.PROJECTS = os.path.expanduser("~/.claude/projects")
            with tempfile.TemporaryDirectory() as td:
                repo = init_repo(Path(td) / "repo")
                wt = self.mod.worktree_paths(str(repo))[0]
                proj_dir = Path(self.mod.PROJECTS) / self.mod.project_dir_name(wt)
                proj_dir.mkdir(parents=True)
                for i in range(2):
                    p = proj_dir / f"session{i}.jsonl"
                    self._write_transcript(p, [{"type": "user", "text": "hi"}])  # no name -> "(unnamed)"
                    os.utime(p, (time.time() - i, time.time() - i))
                buf = []
                self.mod.print = lambda *a, **k: buf.append(" ".join(str(x) for x in a))
                try:
                    self.mod.main([str(repo)])
                finally:
                    del self.mod.print  # falls back to the builtin again
                data_lines = [l for l in buf[1:] if l.strip()]
                self.assertEqual(len(data_lines), 2, buf)

    def test_f27_threshold_flag_without_value_errors_cleanly(self):
        p = subprocess.run([sys.executable, str(MEASURE_CONTEXT), "/tmp", "--threshold"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)
        self.assertIn("--threshold requires a value", p.stderr)

    def test_f10_default_threshold_comes_from_project_config(self):
        with tempfile.TemporaryDirectory() as td:
            repo = init_repo(Path(td) / "repo")
            (repo / ".coord").mkdir()
            (repo / ".coord" / "project.md").write_text("context_threshold: 7000\n")
            self.assertEqual(self.mod.config_threshold(str(repo)), 7000)


class CostReportTest(unittest.TestCase):
    OPUS, SONNET = "claude-opus-5-5", "claude-sonnet-5-5"

    @staticmethod
    def _asst(mid, ts, model, usage, content=None, sidechain=False):
        rec = {"type": "assistant", "timestamp": ts, "isSidechain": sidechain,
               "message": {"id": mid, "model": model, "usage": usage, "content": content or [{"type": "text", "text": "hi"}]}}
        return rec

    @staticmethod
    def _write(path, records):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")

    def _run(self, *extra):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "proj"
            tool_use = [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "TOPSECRETWORD"}}]
            a = self._asst
            self._write(proj / "aaaaaaaa-1.jsonl", [
                {"customTitle": "alpha-session"},
                a("m0", "2026-01-01T10:00:00.000Z", self.OPUS, {"output_tokens": 1000000}),  # before --since
                a("m1", "2026-09-01T10:00:00.000Z", self.OPUS, {"input_tokens": 1000, "output_tokens": 1,
                                                                "cache_creation_input_tokens": 30000}),
                a("m1", "2026-09-01T10:00:01.000Z", self.OPUS, {"input_tokens": 1000, "output_tokens": 1000,
                                                                "cache_creation_input_tokens": 30000},
                  [{"type": "text", "text": "TOPSECRETWORD"}]),  # duplicate id: the last record wins
                a("m2", "2026-09-01T12:50:00.000Z", self.OPUS,  # 2h50m after m1
                  {"output_tokens": 500, "cache_creation_input_tokens": 100000,
                   "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 100000}}, tool_use),
                {"type": "user", "message": {"content": [{"type": "tool_result", "content": "TOPSECRETWORD ok"}]}},
            ])
            self._write(proj / "bbbbbbbb-2.jsonl", [
                a("m3", "2026-09-02T10:00:00.000Z", self.OPUS,
                  {"cache_read_input_tokens": 200000, "output_tokens": 1000})])
            self._write(proj / "aaaaaaaa-1" / "subagents" / "agent-x.jsonl", [
                a("m4", "2026-09-02T11:00:00.000Z", self.SONNET,
                  {"input_tokens": 1000000, "output_tokens": 100000}, sidechain=True), ])
            with open(proj / "bbbbbbbb-2.jsonl", "a") as fh:
                fh.write("not json at all\n")
            p = subprocess.run([sys.executable, str(COST_REPORT), str(proj), "--since", "2026-09-01", *extra],
                               capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def test_totals_dedupe_since_and_subagents(self):
        out = self._run()
        # main: m1 0.264 + m2 0.81 + m3 0.06 = 1.134; subagent: 2.00 + 1.00 = 3.00
        self.assertIn("main: 3 calls, $1.13", out)
        self.assertIn("subagents: 1 calls, $3.00", out)
        self.assertIn("total: $4.13", out)
        self.assertIn("alpha-session", out)

    def test_rewrite_after_gap_in_1_3h_bucket(self):
        out = self._run()
        self.assertRegex(out, r"gap 1-3h\s+1 rewrites  \$0\.81")
        self.assertRegex(out, r"gap <60 min\s+0 rewrites")

    def test_output_has_no_message_content(self):
        self.assertNotIn("TOPSECRETWORD", self._run())


class PyCompileTest(unittest.TestCase):
    def test_hooks_and_measure_context_compile(self):
        for path in (KICKOFF_HOOK, HANDOFF_HOOK, MEASURE_CONTEXT):
            with self.subTest(path=str(path)):
                p = subprocess.run([sys.executable, "-m", "py_compile", str(path)],
                                   capture_output=True, text=True)
                self.assertEqual(p.returncode, 0, p.stderr)


VOTE = SCRIPTS / "vote.py"


def stub(path, body):
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)
    return path


class VoteTest(unittest.TestCase):
    def run_vote(self, env, voters="codex", extra=(), prompt="Q?\nA) x\nB) y\n"):
        td = Path(tempfile.mkdtemp())
        (td / "p.md").write_text(prompt)
        out = td / "out"
        full_env = dict(os.environ, **env)
        r = subprocess.run([sys.executable, str(VOTE), voters, str(td / "p.md"), str(out), *extra],
                           capture_output=True, text=True, env=full_env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return [json.loads(l) for l in r.stdout.splitlines() if l.strip()], td

    def test_codex_vote_parsed_from_output_file(self):
        td = Path(tempfile.mkdtemp())
        # codex writes the final answer to the -o file; find it after "-o"
        args_file = td / "args"
        codex = stub(td / "codex", f'echo "$@" > {args_file}; while [ "$1" != "-o" ]; do shift; done; echo "Vote: B — safer" > "$2"')
        [res], _ = self.run_vote({"COORD_CODEX_BIN": str(codex)})
        self.assertEqual((res["status"], res["answer"], res["reason"]), ("voted", "B", "safer"))
        self.assertIn("-m gpt-6-astra", args_file.read_text())
        self.assertIn("--skip-git-repo-check", args_file.read_text())  # votes may run outside a repo

    def test_bold_vote_line_accepted_prose_rejected(self):
        td = Path(tempfile.mkdtemp())
        ok = stub(td / "ok", 'while [ "$1" != "-o" ]; do shift; done; printf "**Vote: A - simple**\\n" > "$2"')
        [res], _ = self.run_vote({"COORD_CODEX_BIN": str(ok)})
        self.assertEqual(res["answer"], "A")
        bad = stub(td / "bad", 'while [ "$1" != "-o" ]; do shift; done; echo "I think B is better" > "$2"')
        [res], _ = self.run_vote({"COORD_CODEX_BIN": str(bad)})
        self.assertEqual((res["status"], res["why"]), ("missing", "invalid"))

    def test_timeout_kills_process_group(self):
        td = Path(tempfile.mkdtemp())
        slow = stub(td / "slow", "sleep 30 & sleep 30")
        [res], _ = self.run_vote({"COORD_CODEX_BIN": str(slow)}, extra=["--timeout", "1"])
        self.assertEqual((res["status"], res["why"]), ("missing", "timeout"))

    def test_missing_binary_and_usage_limit_and_empty(self):
        [res], _ = self.run_vote({"COORD_CODEX_BIN": "/nonexistent/codex"})
        self.assertEqual(res["why"], "missing-binary")
        td = Path(tempfile.mkdtemp())
        lim = stub(td / "lim", "echo \"You've hit your usage limit\" >&2; exit 1")
        [res], _ = self.run_vote({"COORD_CODEX_BIN": str(lim)})
        self.assertEqual(res["why"], "usage-limit")
        empty = stub(td / "empty", "exit 0")
        [res], _ = self.run_vote({"COORD_CODEX_BIN": str(empty)})
        self.assertEqual(res["why"], "empty")

    def test_grok_and_unknown_voters_are_rejected(self):
        for voters in ("grok", "codex,grok", "opus", "codex,codex"):
            with self.subTest(voters=voters):
                p = subprocess.run([sys.executable, str(VOTE), voters, "/dev/null", tempfile.mkdtemp()],
                                   capture_output=True, text=True, timeout=30)
                self.assertNotEqual(p.returncode, 0)
                self.assertIn("voters: codex", p.stderr)
                self.assertEqual(p.stdout, "")

    def test_vote_without_reason_counts(self):
        td = Path(tempfile.mkdtemp())
        codex = stub(td / "codex", 'while [ "$1" != "-o" ]; do shift; done; echo "Vote: B" > "$2"')
        [res], _ = self.run_vote({"COORD_CODEX_BIN": str(codex)})
        self.assertEqual((res["status"], res["answer"], res["reason"]), ("voted", "B", ""))

    def test_login_only_on_auth_phrases(self):
        td = Path(tempfile.mkdtemp())
        crash = stub(td / "crash", "echo 'reviewing the login form handler'; exit 2")
        [res], _ = self.run_vote({"COORD_CODEX_BIN": str(crash)})
        self.assertEqual(res["why"], "exit 2")
        auth = stub(td / "auth", "echo 'Error: Not logged in. Run codex login' >&2; exit 1")
        [res], _ = self.run_vote({"COORD_CODEX_BIN": str(auth)})
        self.assertEqual(res["why"], "login")

    def test_timeout_survives_group_already_gone(self):
        vote = load_module("vote_mod", VOTE)
        td = Path(tempfile.mkdtemp())
        (td / "p.md").write_text("Q?")
        slow = stub(td / "slow", "sleep 30")
        old_env, old_kill = os.environ.get("COORD_CODEX_BIN"), vote.os.killpg

        def gone(*args):  # the group exits between the timeout and the kill
            old_kill(*args)
            raise ProcessLookupError
        os.environ["COORD_CODEX_BIN"] = str(slow)
        vote.os.killpg = gone
        try:
            res = vote.run_one("codex", str(td / "p.md"), str(td), 1, str(td), "high", "vote")
        finally:
            vote.os.killpg = old_kill
            if old_env is None:
                os.environ.pop("COORD_CODEX_BIN")
            else:
                os.environ["COORD_CODEX_BIN"] = old_env
        self.assertEqual(res["why"], "timeout")

    def test_review_contract(self):
        td = Path(tempfile.mkdtemp())
        codex = stub(td / "codex", 'while [ "$1" != "-o" ]; do shift; done; printf "Verdict: changes\\nFindings:\\n1. x\\n" > "$2"')
        [res], _ = self.run_vote({"COORD_CODEX_BIN": str(codex)}, extra=["--contract", "review"])
        self.assertEqual((res["status"], res["answer"]), ("voted", "changes"))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + sys.argv[1:])
