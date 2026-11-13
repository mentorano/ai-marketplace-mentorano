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
SUCCESSOR_TAB = SCRIPTS / "successor-tab.py"
UTILS_PLUGIN = ROOT / "plugins" / "utils"

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
            "IMPLEMENT task 2",
            "Имплементирай задача 2",  # deliberately Bulgarian: the hook matches it too
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
        # so the manual line lists /coord, /coord lane and "go" for the session to pick.
        with tempfile.TemporaryDirectory() as td:
            repo = init_repo(Path(td) / "repo")
            (repo / ".coord").mkdir()
            (repo / ".coord" / "project.md").write_text("automation: manual\n")
            line = self.mod.handover_line(300, str(repo))
            for first in ("`/coord`", "`/coord lane`", '"go"'):
                self.assertIn(first, line)
            self.assertNotIn("tell coord one line", line)
            (repo / ".coord" / "project.md").write_text("automation: cmux\n")
            self.assertIn("tell coord one line", self.mod.handover_line(300, str(repo)))


STUB_UTILS = """import json, os, sys
if "--version" in sys.argv:
    print(os.environ.get("STUB_VERSION", "0.7.0"))
    sys.exit(0)
with open(os.environ["STUB_LOG"], "a") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
print(os.environ.get("STUB_OUT", "TAB-OK T1 W1 x mode=default prompt=p"))
sys.exit(int(os.environ.get("STUB_RC", "0")))
"""


class SuccessorTabTest(unittest.TestCase):
    """scripts/successor-tab.py: coord's thin wrapper around utils' new-session-tab.py. The tab itself
    (-w, ASCII command, alive marker, TAB-DEAD close, handshake copy) is tested in test_new_session_tab.py."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home = root / "home"
        (self.home / ".claude" / "kickoffs" / "successor").mkdir(parents=True)
        self.kickoff = self.home / ".claude" / "kickoffs" / "successor" / "proj-coord.md"
        self.kickoff.write_text("You ARE proj-coord-r2, the successor of proj-coord.\n", encoding="utf-8")
        self.cache = root / "cache"
        self.dir = root / "repo"
        self.dir.mkdir()
        self.log = root / "utils.log"

    def tearDown(self):
        self.tmp.cleanup()

    def install_utils(self, version: str, marketplace: str = "mkt") -> None:
        script = self.cache / marketplace / "utils" / version / "skills" / "new-session-tab" / "scripts" / "new-session-tab.py"
        script.parent.mkdir(parents=True)
        script.write_text(STUB_UTILS, encoding="utf-8")

    def run_tab(self, config=None, env=None, kickoff=None, name="proj-coord-r2"):
        if config is not None:
            path = self.home / ".claude" / "captain" / "config.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(config), encoding="utf-8")
        base = {k: v for k, v in os.environ.items()
                if k not in ("TERM_PROGRAM", "SUPACODE_WORKTREE_ID", "CMUX_SOCKET_PATH", "CMUX_BUNDLED_CLI_PATH")}
        full = {**base, "HOME": str(self.home), "COORD_PLUGIN_CACHE": str(self.cache),
                "STUB_LOG": str(self.log), **(env or {})}
        return subprocess.run([sys.executable, str(SUCCESSOR_TAB), f"--dir={self.dir}",
                               f"--kickoff={kickoff or self.kickoff}", "--from=proj-coord", f"--name={name}",
                               "--wait=1"], capture_output=True, text=True, timeout=60, env=full)

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def test_tab_ok_runs_utils_with_the_kickoff_and_the_reply_to(self):
        self.install_utils("0.5.0")
        self.install_utils("0.7.0")
        out = "HANDSHAKE proj-coord-r2 reply-to=proj-coord\nTAB-OK T1 W1 proj-coord-r2 mode=auto prompt=p"
        result = self.run_tab(config={"successor_terminal": "supacode"}, env={"STUB_OUT": out})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip().splitlines(), out.splitlines())
        calls = self.calls()
        self.assertEqual(len(calls), 1, calls)
        self.assertEqual(calls[0], [f"--dir={self.dir}", f"--prompt-file={self.kickoff}", "--name=proj-coord-r2",
                                    "--reply-to=proj-coord", "--terminal=supacode", "--wait=1"])

    def test_the_session_prefix_goes_in_front_once(self):
        self.install_utils("0.7.0")
        self.run_tab(config={"successor_terminal": "cmux", "session_prefix": "dev1-"})
        self.run_tab(config={"successor_terminal": "cmux", "session_prefix": "proj-"})
        names = [next(a for a in c if a.startswith("--name=")) for c in self.calls()]
        self.assertEqual(names, ["--name=dev1-proj-coord-r2", "--name=proj-coord-r2"])
        self.assertIn("--terminal=cmux", self.calls()[0])

    def test_a_kickoff_where_clear_looks_is_refused(self):
        # kickoff-on-clear.py reads ~/.claude/kickoffs/<name>.md: a successor's kickoff there would be
        # injected again into the old session by a later /clear.
        self.install_utils("0.7.0")
        flat = self.home / ".claude" / "kickoffs" / "proj-coord.md"
        flat.write_text("kickoff\n", encoding="utf-8")
        result = self.run_tab(config={"successor_terminal": "supacode"}, kickoff=flat)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertTrue(result.stdout.startswith("FAILED BAD-KICKOFF"), result.stdout)
        self.assertEqual(self.calls(), [])

    def test_missing_or_old_utils_names_the_owner_command(self):
        result = self.run_tab(config={"successor_terminal": "supacode"})
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertTrue(result.stdout.startswith("FAILED NO-UTILS no utils plugin"), result.stdout)
        self.assertIn("owner: claude plugin install utils@", result.stdout)
        self.install_utils("0.4.0")
        result = self.run_tab(config={"successor_terminal": "supacode"}, env={"STUB_VERSION": "0.4.0"})
        self.assertEqual(result.stdout.strip(), "FAILED NO-UTILS utils 0.4.0 answers --version with 0.4.0, "
                                                "needs 0.5.0; owner: claude plugin update utils@mkt")
        self.assertEqual(self.calls(), [])

    def test_no_terminal_means_the_clear_path(self):
        result = self.run_tab(config={"successor_terminal": "none"})
        self.assertEqual(result.returncode, 3, result.stdout)
        self.assertTrue(result.stdout.startswith("TERMINAL-NONE config successor_terminal='none'"), result.stdout)
        (self.home / ".claude" / "captain" / "config.json").unlink()
        result = self.run_tab()  # no config, not in Supacode or cmux
        self.assertIn("not running in Supacode or cmux", result.stdout)
        self.assertEqual(result.returncode, 3, result.stdout)
        self.assertEqual(self.calls(), [])

    def test_tab_none_and_failed_lines_are_passed_on(self):
        self.install_utils("0.7.0")
        result = self.run_tab(config={"successor_terminal": "supacode"},
                              env={"STUB_OUT": "HANDSHAKE x reply-to=y\nTAB-NONE why prompt=p", "STUB_RC": "3"})
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout.strip().splitlines(), ["HANDSHAKE x reply-to=y", "TERMINAL-NONE why prompt=p"])
        result = self.run_tab(config={"successor_terminal": "supacode"},
                              env={"STUB_OUT": "FAILED TAB-DEAD T1 in=W1 after=1s closed=yes", "STUB_RC": "1"})
        self.assertEqual((result.returncode, result.stdout.strip()), (1, "FAILED TAB-DEAD T1 in=W1 after=1s closed=yes"))

    def test_names_are_checked_before_utils_runs(self):
        self.install_utils("0.7.0")
        result = self.run_tab(config={"successor_terminal": "supacode"}, name="proj-coord")
        self.assertTrue(result.stdout.startswith("FAILED BAD-NAME --name must differ"), result.stdout)
        self.assertEqual(self.calls(), [])

    def test_detection_without_config(self):
        mod = load_module("coord_successor_tab", SUCCESSOR_TAB)
        found = lambda name: f"/bin/{name}"
        none = lambda name: None
        self.assertEqual(mod.choose_terminal(None, {"TERM_PROGRAM": "supacode", "SUPACODE_WORKTREE_ID": "w"}, found)[0],
                         "supacode")
        self.assertEqual(mod.choose_terminal(None, {"TERM_PROGRAM": "supacode", "SUPACODE_WORKTREE_ID": "w"}, none)[0],
                         "none")
        self.assertEqual(mod.choose_terminal(None, {"CMUX_SOCKET_PATH": "/s"}, found)[0], "cmux")
        self.assertEqual(mod.choose_terminal({"successor_terminal": "tmux"}, {"CMUX_SOCKET_PATH": "/s"}, found)[0],
                         "none")

    def test_the_repo_utils_is_new_enough(self):
        mod = load_module("coord_successor_tab_v", SUCCESSOR_TAB)
        script = UTILS_PLUGIN / mod.UTILS_SCRIPT
        self.assertGreaterEqual(mod.answered_version(script), mod.MIN_UTILS)


    def test_real_utils_opens_a_supacode_tab_with_the_handshake_and_the_prefixed_name(self):
        # Integration: the real utils new-session-tab.py with the stub `supacode` and `claude` of its own tests.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_new_session_tab import HOST_ENV, SUPACODE_STUB, worktree_row
        target = self.cache / "mkt" / "utils" / "0.7.0"
        target.parent.mkdir(parents=True)
        target.symlink_to(UTILS_PLUGIN)
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        for name, body in (("supacode", SUPACODE_STUB), ("claude", "#!/bin/sh\nexit 0\n")):
            (bin_dir / name).write_text(body, encoding="utf-8")
            (bin_dir / name).chmod(0o755)
        config = self.home / ".claude" / "captain" / "config.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"successor_terminal": "supacode", "session_prefix": "dev1-"}), encoding="utf-8")
        row, tab, supa_log = worktree_row(self.dir), "0D1E2F30-AAAA-BBBB-CCCC-000000000001", Path(self.tmp.name) / "supa.log"
        env = {k: v for k, v in os.environ.items() if k not in HOST_ENV}
        env.update({"HOME": str(self.home), "PATH": f"{bin_dir}:/usr/bin:/bin", "COORD_PLUGIN_CACHE": str(self.cache),
                    "SUPA_LOG": str(supa_log), "SUPA_ROWS": row, "SUPA_TAB": tab, "SUPA_TAB_IN": row, "SUPA_RUN": "1"})
        result = subprocess.run([sys.executable, str(SUCCESSOR_TAB), f"--dir={self.dir}", f"--kickoff={self.kickoff}",
                                 "--from=proj-coord", "--name=proj-coord-r2", "--wait=2"],
                                capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = result.stdout.strip().splitlines()
        self.assertEqual(lines[0], "HANDSHAKE dev1-proj-coord-r2 reply-to=proj-coord")
        self.assertTrue(lines[-1].startswith(f"TAB-OK {tab} {row} dev1-proj-coord-r2 "), lines)
        folder = self.kickoff.parent
        self.assertTrue((folder / "dev1-proj-coord-r2.alive").exists())
        wrapped = (folder / "dev1-proj-coord-r2.handshake.md").read_text(encoding="utf-8")
        self.assertIn("STARTED dev1-proj-coord-r2 pwd=", wrapped)
        self.assertTrue(wrapped.endswith(self.kickoff.read_text(encoding="utf-8")), wrapped)
        new = [json.loads(line) for line in supa_log.read_text(encoding="utf-8").splitlines()
               if json.loads(line)[:2] == ["tab", "new"]]
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0][new[0].index("-w") + 1], row)
        self.assertTrue(new[0][new[0].index("-i") + 1].isascii())

class HandoffHookSuccessorTerminalTest(unittest.TestCase):
    def setUp(self):
        self.mod = load_module("handoff_at_boundary_st", HANDOFF_HOOK)

    def test_terminal_rule_matches_the_script(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            self.assertIsNone(self.mod.successor_terminal({}, str(home)))
            (home / ".claude" / "captain").mkdir(parents=True)
            cfg = home / ".claude" / "captain" / "config.json"
            cfg.write_text(json.dumps({"successor_terminal": "cmux"}))
            self.assertEqual(self.mod.successor_terminal({}, str(home)), "cmux")
            cfg.write_text(json.dumps({"successor_terminal": "none"}))
            self.assertIsNone(self.mod.successor_terminal({"CMUX_SOCKET_PATH": "/s"}, str(home)))

    def test_kickoff_line_branches_by_terminal(self):
        with tempfile.TemporaryDirectory() as td:
            repo = init_repo(Path(td) / "repo")
            (repo / ".coord").mkdir()
            (repo / ".coord" / "project.md").write_text("automation: manual\n")
            plain = self.mod.kickoff_line(str(repo), None)
            self.assertIn("`~/.claude/kickoffs/<your session name>.md`", plain)
            self.assertNotIn("successor-tab.py", plain)
            tab = self.mod.kickoff_line(str(repo), "supacode")
            for part in ("§Successor terminal", "kickoffs/successor/", "successor-tab.py", "fall back to /clear",
                         "rewrite that kickoff", "WITHOUT the successor-tab paragraph"):
                self.assertIn(part, tab)
            self.assertNotIn("restarted in place", tab)
            (repo / ".coord" / "project.md").write_text("automation: cmux\n")
            cmux_line = self.mod.kickoff_line(str(repo), "cmux")
            self.assertIn("restarted in place by coord", cmux_line)
            self.assertIn("design/prototype session", cmux_line)


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
        for path in (KICKOFF_HOOK, HANDOFF_HOOK, MEASURE_CONTEXT, SUCCESSOR_TAB):
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
