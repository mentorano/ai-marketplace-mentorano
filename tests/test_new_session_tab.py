#!/usr/bin/env python3
"""Tests for plugins/utils/skills/new-session-tab/scripts/new-session-tab.py.

The script runs as a subprocess against stub `supacode`, `cmux` and `claude` binaries on PATH,
with HOME redirected to a tempdir: no real terminal tab is opened and no Claude session starts.

Run:  python3 tests/test_new_session_tab.py
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UTILS = ROOT / "plugins" / "utils"
SKILL_DIR = UTILS / "skills" / "new-session-tab"
NEW_TAB = SKILL_DIR / "scripts" / "new-session-tab.py"
# The test host may itself run in Supacode, cmux or another Claude session; none of that may leak in.
HOST_ENV = {"TERM_PROGRAM", "SUPACODE_WORKTREE_ID", "CLAUDE_CODE_SESSION_ID",
            "CMUX_SOCKET_PATH", "CMUX_WORKSPACE_ID", "CMUX_SURFACE_ID", "CMUX_BUNDLED_CLI_PATH",
            "XDG_CONFIG_HOME"}


# SUPA_RUN / CMUX_RUN: `1` runs the tab command at once, `late` one second later, empty never (a tab
# with no terminal, 2026-10-07). A closed tab leaves the listing unless SUPA_CLOSE_KEEPS is set.
SUPACODE_STUB = """#!/usr/bin/env python3
import json, os, subprocess, sys
args = sys.argv[1:]
log = os.environ["SUPA_LOG"]
with open(log, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\\n")
tab = os.environ["SUPA_TAB"]
if args[:2] == ["worktree", "list"]:
    print("\\n".join(os.environ["SUPA_ROWS"].split()))
elif args[:2] == ["tab", "new"]:
    command = args[args.index("-i") + 1]
    if os.environ.get("SUPA_RUN") == "1":
        subprocess.run(["sh", "-c", command])
    elif os.environ.get("SUPA_RUN") == "late":
        subprocess.Popen(["sh", "-c", "sleep 1; " + command], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # `tab new` returns at once
    print(tab)
elif args[:2] == ["tab", "list"] and os.environ.get("SUPA_BOOT"):  # a fresh worktree: bootstrap + new
    if args[args.index("-w") + 1] == os.environ["SUPA_TAB_IN"]:
        closed = open(log + ".closed").read().split() if os.path.exists(log + ".closed") else []
        made = any(json.loads(line)[:2] == ["tab", "new"] for line in open(log, encoding="utf-8"))
        for row in os.environ["SUPA_BOOT"].split() + ([tab] if made else []):
            if row not in closed:
                print(row)
elif args[:2] == ["worktree", "script"]:
    print(os.environ.get("SUPA_SCRIPTS", ""), end="")
elif args[:2] == ["tab", "close"] and os.environ.get("SUPA_BOOT"):
    if os.environ.get("SUPA_CLOSE_KEEPS"):
        sys.exit(0)
    with open(log + ".closed", "a", encoding="utf-8") as fh:
        fh.write(args[args.index("-t") + 1] + "\\n")
elif args[:2] == ["tab", "list"]:
    if os.path.exists(log + ".closed") and os.environ.get("SUPA_LIST_FAILS_AFTER_CLOSE"):
        sys.exit(1)
    closed = os.path.exists(log + ".closed") and not os.environ.get("SUPA_CLOSE_KEEPS")
    if args[args.index("-w") + 1] == os.environ["SUPA_TAB_IN"] and not closed:
        print(tab.lower())
elif args[:2] == ["tab", "close"]:
    rc = int(os.environ.get("SUPA_CLOSE_RC", "0"))
    if rc == 0:
        open(log + ".closed", "w").close()
    sys.exit(rc)
"""


CMUX_STUB = """#!/usr/bin/env python3
import json, os, subprocess, sys
args = sys.argv[1:]
with open(os.environ["CMUX_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\\n")
if args[0] == "new-surface":
    print(os.environ["CMUX_NEW_OUT"])
elif args[0] == "read-screen":
    sys.exit(int(os.environ.get("CMUX_READ_RC", "0")))
elif args[0] == "send":
    sys.exit(int(os.environ.get("CMUX_SEND_RC", "0")))
elif args[0] == "send-key":
    rc = int(os.environ.get("CMUX_KEY_RC", "0"))
    if rc == 0 and os.environ.get("CMUX_RUN") == "1":
        with open(os.environ["CMUX_LOG"], encoding="utf-8") as fh:
            sent = [json.loads(line) for line in fh if line.startswith('["send",')]
        subprocess.run(["sh", "-c", sent[-1][-1]])
    sys.exit(rc)
elif args[0] == "close-surface":
    sys.exit(int(os.environ.get("CMUX_CLOSE_RC", "0")))
"""


def worktree_row(path: Path) -> str:
    return urllib.parse.quote(str(path).rstrip("/") + "/", safe="")


class NewSessionTabTest(unittest.TestCase):
    """new-session-tab.py against stub `supacode` and `claude` binaries on PATH."""
    TAB = "0D1E2F30-AAAA-BBBB-CCCC-000000000001"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home = root / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.bin = root / "bin"
        self.bin.mkdir()
        for name, body in (("supacode", SUPACODE_STUB), ("claude", "#!/bin/sh\nexit 0\n")):
            (self.bin / name).write_text(body, encoding="utf-8")
            (self.bin / name).chmod(0o755)
        self.repo = root / "repo"
        self.other = root / "other"
        self.dir = self.repo / ".claude" / "worktrees" / "wt"
        for path in (self.dir, self.other):
            path.mkdir(parents=True)
        self.prompt = self.repo / "tmp" / "handover-next-20261002.md"
        self.prompt.parent.mkdir(parents=True)
        self.prompt.write_text("Continue with the next task (café).\n", encoding="utf-8")
        self.log = root / "supacode.log"
        self.rows = [worktree_row(root), worktree_row(self.repo), worktree_row(self.other)]

    def tearDown(self):
        self.tmp.cleanup()

    def run_tab(self, terminal: str | None = None, env: dict | None = None, directory: Path | None = None,
                name: str = "proj-c5-r2", wait: int = 1, extra: tuple = ()) -> subprocess.CompletedProcess:
        flags = [f"--terminal={terminal}"] if terminal else []
        base = {k: v for k, v in os.environ.items() if k not in HOST_ENV}
        full = {**base, "HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin",
                "SUPA_LOG": str(self.log), "SUPA_ROWS": " ".join(self.rows), "SUPA_TAB": self.TAB,
                "SUPA_TAB_IN": worktree_row(self.repo), "SUPA_RUN": "1", "CMUX_RUN": "1", **(env or {})}
        return subprocess.run([sys.executable, str(NEW_TAB), f"--dir={directory or self.dir}",
                               f"--prompt-file={self.prompt}", f"--name={name}",
                               f"--wait={wait}", *flags, *extra],
                              capture_output=True, text=True, timeout=30, env=full)

    def calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def tab_command(self) -> str:
        new = [c for c in self.calls() if c[:2] == ["tab", "new"]]
        self.assertEqual(len(new), 1, self.calls())
        return new[0][new[0].index("-i") + 1]

    def test_auto_outside_supacode_and_cmux_is_tab_none(self):
        result = self.run_tab(terminal="auto")
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertTrue(result.stdout.startswith("TAB-NONE "), result.stdout)
        self.assertEqual(self.calls(), [])

    def test_opens_the_tab_with_w_of_the_innermost_worktree_and_the_prompt_in_a_file(self):
        result = self.run_tab(terminal="supacode")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        prompt = self.prompt
        self.assertEqual(result.stdout.strip(), f"TAB-OK {self.TAB} {worktree_row(self.repo)} proj-c5-r2 "
                                                f"mode=default prompt={prompt}")
        new = [c for c in self.calls() if c[:2] == ["tab", "new"]][0]
        self.assertEqual(new[new.index("-w") + 1], worktree_row(self.repo), "the innermost, not the parent")
        command = self.tab_command()
        self.assertTrue(command.isascii(), command)
        marker = self.prompt.parent / "proj-c5-r2.alive"
        self.assertEqual(command, f'cd {self.dir} && : > {marker} && {self.bin / "claude"} -n proj-c5-r2 '
                                  f'"$(cat {prompt})"', "the marker is written before claude starts")
        self.assertNotIn("close", [c[1] for c in self.calls() if len(c) > 1], "a live tab is never closed")
        self.assertEqual(prompt.read_text(encoding="utf-8"), "Continue with the next task (café).\n", "the prompt is left as is")

    def test_without_the_key_a_supacode_session_is_detected(self):
        result = self.run_tab(terminal="auto", env={"TERM_PROGRAM": "supacode",
                                              "SUPACODE_WORKTREE_ID": worktree_row(self.repo)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.startswith("TAB-OK "), result.stdout)

    CMUX_ENV = {"CMUX_SOCKET_PATH": "/tmp/cmux.sock", "CMUX_WORKSPACE_ID": "WS-1"}

    def add_cmux(self):
        (self.bin / "cmux").write_text(CMUX_STUB, encoding="utf-8")
        (self.bin / "cmux").chmod(0o755)
        self.cmux_log = Path(self.tmp.name) / "cmux.log"
        return {"CMUX_LOG": str(self.cmux_log), "CMUX_NEW_OUT": "OK surface:103 pane:7 workspace:2"}

    def cmux_calls(self) -> list[list[str]]:
        if not self.cmux_log.exists():
            return []
        return [json.loads(line) for line in self.cmux_log.read_text(encoding="utf-8").splitlines()]

    def run_cmux(self, terminal=None, env=None, **kwargs) -> subprocess.CompletedProcess:
        return self.run_tab(terminal="cmux" if terminal is None else terminal,
                            env={**self.add_cmux(), **self.CMUX_ENV, **(env or {})}, **kwargs)

    def test_cmux_asked_opens_a_surface_types_the_command_and_presses_enter(self):
        result = self.run_cmux()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        prompt = self.prompt
        self.assertEqual(result.stdout.strip(), f"TAB-OK surface:103 WS-1 proj-c5-r2 mode=default prompt={prompt}")
        marker = self.prompt.parent / "proj-c5-r2.alive"
        command = f'cd {self.dir} && : > {marker} && {self.bin / "claude"} -n proj-c5-r2 "$(cat {prompt})"'
        self.assertEqual(self.cmux_calls(), [
            ["new-surface", "--type", "terminal", "--focus", "false", "--workspace", "WS-1"],
            ["send", "--surface", "surface:103", command],
            ["send-key", "--surface", "surface:103", "enter"]])
        self.assertEqual(self.calls(), [], "supacode is untouched")

    def test_without_workspace_id_the_workspace_flag_is_left_out_and_shown_as_a_dash(self):
        result = self.run_cmux(env={"CMUX_WORKSPACE_ID": ""})
        self.assertTrue(result.stdout.startswith("TAB-OK surface:103 - proj-c5-r2 "), result.stdout)
        self.assertEqual(self.cmux_calls()[0], ["new-surface", "--type", "terminal", "--focus", "false"])

    def test_without_the_key_a_cmux_session_is_detected(self):
        result = self.run_cmux(terminal="auto")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.startswith("TAB-OK surface:103 "), result.stdout)

    def test_without_the_key_cmux_needs_the_socket(self):
        env = self.add_cmux()
        result = self.run_tab(terminal="auto", env=env)
        self.assertEqual(result.returncode, 3, result.stdout)
        self.assertEqual(self.cmux_calls(), [])

    def test_supacode_wins_when_both_are_detected(self):
        result = self.run_cmux(terminal="auto", env={"TERM_PROGRAM": "supacode",
                                               "SUPACODE_WORKTREE_ID": worktree_row(self.repo)})
        self.assertTrue(result.stdout.startswith(f"TAB-OK {self.TAB} "), result.stdout)
        self.assertEqual(self.cmux_calls(), [])

    def test_terminal_none_beats_a_cmux_session(self):
        result = self.run_cmux(terminal="none")
        self.assertEqual(result.returncode, 3, result.stdout)
        self.assertEqual(self.cmux_calls(), [])

    def test_the_bundled_cli_is_used_when_cmux_is_not_on_path(self):
        env = self.add_cmux()
        bundled = self.bin.parent / "bundled-cmux"
        (self.bin / "cmux").rename(bundled)
        result = self.run_tab(terminal="cmux",
                              env={**env, **self.CMUX_ENV, "CMUX_BUNDLED_CLI_PATH": str(bundled)})
        self.assertTrue(result.stdout.startswith("TAB-OK surface:103 "), result.stdout)

    def test_a_missing_cmux_cli_is_no_cmux(self):
        result = self.run_tab(terminal="cmux", env=self.CMUX_ENV)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stdout.startswith("FAILED NO-CMUX"), result.stdout)

    def test_unrecognised_new_surface_output_is_tab_new_failed_and_nothing_is_typed(self):
        result = self.run_cmux(env={"CMUX_NEW_OUT": "ERROR: no workspace"})
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stdout.startswith("FAILED TAB-NEW-FAILED"), result.stdout)
        self.assertEqual([c[0] for c in self.cmux_calls()], ["new-surface"])

    def test_read_screen_is_never_called_on_the_new_surface(self):
        # 2026-10-06, cmux 0.64.25: an unfocused new surface has no PTY yet, so read-screen fails
        result = self.run_cmux(env={"CMUX_READ_RC": "1"})
        self.assertTrue(result.stdout.startswith("TAB-OK surface:103 "), result.stdout)
        self.assertNotIn("read-screen", [c[0] for c in self.cmux_calls()])

    def test_a_failing_send_reports_the_surface_ref_and_presses_no_key(self):
        result = self.run_cmux(env={"CMUX_SEND_RC": "1"})
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stdout.startswith("FAILED CMUX-ERROR surface=surface:103 cmux send"), result.stdout)
        self.assertEqual([c[0] for c in self.cmux_calls()], ["new-surface", "send"])

    def test_a_failing_send_key_reports_the_surface_ref(self):
        result = self.run_cmux(env={"CMUX_KEY_RC": "1"})
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stdout.startswith("FAILED CMUX-ERROR surface=surface:103 cmux send-key"), result.stdout)

    def test_a_failing_cmux_command_is_cmux_error(self):
        result = self.run_cmux(env={"CMUX_NEW_OUT": "x"})
        self.assertTrue(result.stdout.startswith("FAILED TAB-NEW-FAILED"), result.stdout)
        (self.bin / "cmux").write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
        result = self.run_tab(terminal="cmux", env=self.CMUX_ENV)
        self.assertTrue(result.stdout.startswith("FAILED CMUX-ERROR cmux new-surface rc=2"), result.stdout)

    def test_cmux_refuses_a_non_ascii_directory_and_a_backslash(self):
        for name in ("café-tést", "back\\slash"):
            with self.subTest(name=name):
                directory = self.repo / name
                directory.mkdir()
                result = self.run_cmux(directory=directory)
                self.assertEqual(result.returncode, 1)
                self.assertTrue(result.stdout.startswith("FAILED "), result.stdout)
                self.assertEqual(self.cmux_calls(), [])

    def test_the_permission_mode_is_mirrored_only_when_safe(self):
        session = "9081b697-f16a-4b97-88d6-f3e6d5198fdb"
        transcript = self.home / ".claude" / "projects" / "-repo" / f"{session}.jsonl"
        transcript.parent.mkdir(parents=True)
        for last, flag, shown in (("auto", "--permission-mode auto", "mode=auto"),
                                  ("bypassPermissions", None, "mode=default"), ("plan", None, "mode=default")):
            with self.subTest(last=last):
                records = [{"type": "permission-mode", "permissionMode": "default"},
                           {"type": "permission-mode", "permissionMode": last}]
                transcript.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
                self.log.unlink(missing_ok=True)
                result = self.run_tab(terminal="supacode",
                                      env={"CLAUDE_CODE_SESSION_ID": session})
                self.assertIn(shown, result.stdout)
                command = self.tab_command()
                if flag:
                    self.assertIn(f"-n proj-c5-r2 {flag} ", command)
                else:
                    self.assertNotIn("--permission-mode", command)

    def test_a_non_ascii_directory_is_refused_before_any_tab(self):
        directory = self.repo / "café-tést"
        directory.mkdir()
        result = self.run_tab(terminal="supacode", directory=directory)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stdout.startswith("FAILED NON-ASCII"), result.stdout)
        self.assertFalse([c for c in self.calls() if c[:2] == ["tab", "new"]])

    def test_a_quote_in_the_directory_is_shell_quoted(self):
        directory = self.repo / "it's"
        directory.mkdir()
        result = self.run_tab(terminal="supacode", directory=directory)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(shlex.split(self.tab_command())[1], str(directory))

    def test_a_tab_in_another_worktree_is_reported_with_where_it_is(self):
        result = self.run_tab(terminal="supacode",
                              env={"SUPA_TAB_IN": worktree_row(self.other)})
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), f"FAILED TAB-ELSEWHERE {self.TAB} in={worktree_row(self.other)}")
        self.assertFalse([c for c in self.calls() if c[:2] == ["tab", "close"]], "only a dead tab is closed")

    def marker(self) -> Path:
        return self.prompt.parent / "proj-c5-r2.alive"

    def test_a_tab_whose_command_never_runs_is_tab_dead_and_the_script_closes_it(self):
        # 2026-10-07: display off → Supacode kept a nil surface; `tab new` and `tab list` both passed
        result = self.run_tab(terminal="supacode", env={"SUPA_RUN": ""})
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        wt = worktree_row(self.repo)
        self.assertEqual(result.stdout.strip(), f"FAILED TAB-DEAD {self.TAB} in={wt} after=1s closed=yes")
        self.assertEqual([c for c in self.calls() if c[:2] == ["tab", "close"]],
                         [["tab", "close", "-w", wt, "-t", self.TAB]], "always with -w: never the focused one")

    def test_a_dead_tab_the_close_fails_on_says_closed_no(self):
        result = self.run_tab(terminal="supacode", env={"SUPA_RUN": "", "SUPA_CLOSE_RC": "1"})
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stdout.strip().endswith(" after=1s closed=no"), result.stdout)

    def test_a_dead_tab_still_listed_after_the_close_says_closed_no(self):
        result = self.run_tab(terminal="supacode",
                              env={"SUPA_RUN": "", "SUPA_CLOSE_KEEPS": "1"})
        self.assertTrue(result.stdout.strip().endswith(" closed=no"), result.stdout)

    def test_a_close_that_cannot_be_checked_says_closed_no(self):
        result = self.run_tab(terminal="supacode",
                              env={"SUPA_RUN": "", "SUPA_LIST_FAILS_AFTER_CLOSE": "1"})
        self.assertTrue(result.stdout.strip().endswith(" closed=no"), result.stdout)

    def test_a_stale_marker_does_not_make_a_dead_tab_pass(self):
        self.marker().write_text("", encoding="utf-8")
        result = self.run_tab(terminal="supacode", env={"SUPA_RUN": ""})
        self.assertTrue(result.stdout.startswith(f"FAILED TAB-DEAD {self.TAB} "), result.stdout)

    def test_a_marker_that_cannot_be_removed_is_one_failed_line(self):
        self.marker().mkdir()
        result = self.run_tab(terminal="supacode")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(result.stdout.startswith("FAILED MARKER "), result.stdout + result.stderr)
        self.assertFalse([c for c in self.calls() if c[:2] == ["tab", "new"]])

    def test_a_marker_that_appears_within_the_wait_is_tab_ok(self):
        result = self.run_tab(terminal="supacode", env={"SUPA_RUN": "late"}, wait=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.startswith(f"TAB-OK {self.TAB} "), result.stdout)
        self.assertTrue(self.marker().exists())
        new = self.calls().index(next(c for c in self.calls() if c[:2] == ["tab", "new"]))
        self.assertFalse([c for c in self.calls()[new:] if c[:2] == ["tab", "close"]])

    def test_a_cmux_surface_whose_command_never_runs_is_tab_dead_and_closed(self):
        result = self.run_cmux(env={"CMUX_RUN": ""})
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "FAILED TAB-DEAD surface:103 in=WS-1 after=1s closed=yes")
        self.assertEqual(self.cmux_calls()[-1], ["close-surface", "--surface", "surface:103"])

    def test_a_cmux_surface_the_close_fails_on_says_closed_no(self):
        result = self.run_cmux(env={"CMUX_RUN": "", "CMUX_CLOSE_RC": "1"})
        self.assertEqual(result.stdout.strip(), "FAILED TAB-DEAD surface:103 in=WS-1 after=1s closed=no")

    def test_a_directory_outside_every_supacode_worktree_is_refused(self):
        self.rows = [worktree_row(self.other)]
        result = self.run_tab(terminal="supacode")
        self.assertTrue(result.stdout.startswith("FAILED NOT-IN-A-SUPACODE-WORKTREE"), result.stdout)
        self.assertFalse([c for c in self.calls() if c[:2] == ["tab", "new"]])
        self.assertFalse(self.marker().exists())

    def test_a_prompt_path_with_a_space_is_shell_quoted(self):
        self.prompt = self.repo / "tmp" / "my run" / "handover-x-20261002.md"
        self.prompt.parent.mkdir(parents=True)
        self.prompt.write_text("go\n", encoding="utf-8")
        result = self.run_tab(terminal="supacode")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(shlex.split(self.tab_command())[5], str(self.prompt.parent / "proj-c5-r2.alive"))
        self.assertTrue(self.tab_command().endswith(f'"$(cat {shlex.quote(str(self.prompt))})"'))

    def test_a_missing_or_relative_prompt_file_is_refused(self):
        for prompt in (self.repo / "tmp" / "missing.md", Path("tmp/handover.md")):
            with self.subTest(prompt=prompt):
                self.prompt = prompt
                result = self.run_tab(terminal="supacode")
                self.assertTrue(result.stdout.startswith("FAILED BAD-PROMPT-FILE"), result.stdout)
        self.assertEqual(self.calls(), [])

    def test_a_prompt_file_that_is_its_own_marker_is_refused_and_kept(self):
        self.prompt = self.repo / "tmp" / "task.alive"
        self.prompt.write_text("go\n", encoding="utf-8")
        result = self.run_tab(terminal="supacode", name="task")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(result.stdout.startswith("FAILED BAD-PROMPT-FILE"), result.stdout)
        self.assertEqual(self.prompt.read_text(encoding="utf-8"), "go\n")
        self.assertEqual(self.calls(), [])

    def test_skill_starts_no_second_session_while_a_tab_may_run(self):
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        for needle in ("from before any tab opened", "never two\n   sessions on one handover",
                       "cmux close-surface --surface <ref>"):
            self.assertIn(needle, text)

    def test_bad_names_are_refused(self):
        for name in ("my session", "-dash", "x" * 65):
            with self.subTest(name=name):
                result = self.run_tab(terminal="supacode", name=name)
                self.assertTrue(result.stdout.startswith("FAILED BAD-NAME"), result.stdout)
        self.assertEqual(self.calls(), [])

    def test_an_explicit_permission_mode_is_passed_through_and_beats_the_mirrored_one(self):
        result = self.run_tab(terminal="supacode", extra=("--permission-mode=plan",))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(" mode=plan ", result.stdout)
        self.assertIn("-n proj-c5-r2 --permission-mode plan ", self.tab_command())

    def test_an_unknown_permission_mode_is_refused(self):
        result = self.run_tab(terminal="supacode", extra=("--permission-mode=x; rm",))
        self.assertTrue(result.stdout.startswith("FAILED BAD-MODE"), result.stdout)
        self.assertEqual(self.calls(), [])

    def test_auto_is_the_default_terminal(self):
        result = self.run_tab(env={"TERM_PROGRAM": "supacode", "SUPACODE_WORKTREE_ID": worktree_row(self.repo)})
        self.assertTrue(result.stdout.startswith(f"TAB-OK {self.TAB} "), result.stdout)
        result = self.run_tab()
        self.assertEqual(result.returncode, 3, result.stdout)
        self.assertTrue(result.stdout.startswith("TAB-NONE "), result.stdout)


class FreshWorktreeTest(NewSessionTabTest):
    """--fresh-worktree: the bootstrap tab of a just-made worktree is closed after TAB-OK."""
    BOOT = "AAAA0000-1111-2222-3333-444444444444"

    def setUp(self):
        super().setUp()  # a fake git names the main checkout: GIT_FAIL makes it fail
        (self.bin / "git").write_text('#!/bin/sh\n[ -n "$GIT_FAIL" ] && exit 128\n'
                                      f'echo {shlex.quote(str(self.repo / ".git"))}\n', encoding="utf-8")
        (self.bin / "git").chmod(0o755)

    def fresh(self, env: dict | None = None, extra: tuple = ()) -> subprocess.CompletedProcess:
        return self.run_tab(terminal="supacode", env={"SUPA_BOOT": self.BOOT, **(env or {})},
                            extra=("--fresh-worktree", *extra))

    def closes(self) -> list[list[str]]:
        return [c for c in self.calls() if c[:2] == ["tab", "close"]]

    def test_the_bootstrap_tab_is_closed_in_the_background_and_tab_ok_stays_last(self):
        result = self.fresh()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = result.stdout.strip().splitlines()
        self.assertEqual(lines[0], f"BOOTSTRAP-CLOSED {self.BOOT}")
        self.assertTrue(lines[-1].startswith(f"TAB-OK {self.TAB} "), lines)
        wt = worktree_row(self.repo)
        self.assertEqual(self.closes(), [["tab", "close", "-w", wt, "-t", self.BOOT, "--background"]])
        first_list = next(i for i, c in enumerate(self.calls()) if c[:2] == ["tab", "list"])
        new = next(i for i, c in enumerate(self.calls()) if c[:2] == ["tab", "new"])
        self.assertLess(first_list, new, "the tab ids are recorded before `tab new`")

    def test_a_setup_script_keeps_the_bootstrap_tab(self):
        (self.repo / "supacode.json").write_text(json.dumps({"setupScript": "make setup"}), encoding="utf-8")
        result = self.fresh()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines()[0], "BOOTSTRAP-KEPT setup-script")
        self.assertEqual(self.closes(), [])

    def test_a_setup_script_in_repos_json_or_the_script_list_keeps_it_too(self):
        config = self.home / ".config" / "supacode"
        config.mkdir(parents=True)
        (config / "repos.json").write_text(json.dumps({str(self.repo) + "/": {"setupScript": "x"}}),
                                           encoding="utf-8")
        result = self.fresh()
        self.assertEqual(result.stdout.splitlines()[0], "BOOTSTRAP-KEPT setup-script")
        (config / "repos.json").unlink()
        self.log.unlink()  # a second, separate run
        result = self.fresh(env={"SUPA_SCRIPTS": "B90F7467-8638-4FB6-9CFC-450207596267\tsetup\tSetup\n"})
        self.assertEqual(result.stdout.splitlines()[0], "BOOTSTRAP-KEPT setup-script")
        self.assertEqual(self.closes(), [])

    def test_unreadable_settings_keep_the_tab(self):
        (self.repo / "supacode.json").write_text("{not json", encoding="utf-8")
        result = self.fresh()
        self.assertEqual(result.stdout.splitlines()[0], "BOOTSTRAP-KEPT setup-script-unknown")
        self.assertEqual(self.closes(), [])

    def test_a_repo_root_git_cannot_name_keeps_the_tab(self):
        result = self.fresh(env={"GIT_FAIL": "1"})
        self.assertEqual(result.stdout.splitlines()[0], "BOOTSTRAP-KEPT setup-script-unknown")
        self.assertEqual(self.closes(), [])

    def test_a_repos_json_that_is_not_an_object_keeps_the_tab(self):
        config = self.home / ".config" / "supacode"
        config.mkdir(parents=True)
        (config / "repos.json").write_text("[]", encoding="utf-8")
        result = self.fresh()
        self.assertEqual(result.stdout.splitlines()[0], "BOOTSTRAP-KEPT setup-script-unknown")
        self.assertEqual(self.closes(), [])

    def test_an_empty_setup_script_and_other_scripts_do_not_keep_it(self):
        (self.repo / "supacode.json").write_text(json.dumps({"setupScript": "  "}), encoding="utf-8")
        result = self.fresh(env={"SUPA_SCRIPTS": "B90F7467-8638-4FB6-9CFC-450207596267\trun\tRun\n"})
        self.assertEqual(result.stdout.splitlines()[0], f"BOOTSTRAP-CLOSED {self.BOOT}")

    def test_nothing_to_close_when_the_worktree_had_no_tab(self):
        result = self.fresh(env={"SUPA_BOOT": " "})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines()[0], "BOOTSTRAP-NONE no-tab")
        self.assertEqual(self.closes(), [])

    def test_a_worktree_with_two_tabs_is_not_fresh_and_nothing_is_closed(self):
        result = self.fresh(env={"SUPA_BOOT": f"{self.BOOT} BBBB0000-1111-2222-3333-444444444444"})
        self.assertEqual(result.stdout.splitlines()[0], "BOOTSTRAP-NONE tabs=2")
        self.assertEqual(self.closes(), [])

    def test_a_dead_new_tab_closes_no_bootstrap(self):
        result = self.fresh(env={"SUPA_RUN": ""})
        self.assertTrue(result.stdout.startswith(f"FAILED TAB-DEAD {self.TAB} "), result.stdout)
        self.assertNotIn(self.BOOT, json.dumps(self.closes()))

    def test_a_close_that_leaves_the_tab_is_close_failed(self):
        result = self.fresh(env={"SUPA_CLOSE_KEEPS": "1"})
        self.assertEqual(result.stdout.splitlines()[0], f"BOOTSTRAP-KEPT close-failed {self.BOOT}")

    def test_without_the_flag_a_single_tab_worktree_keeps_its_tab(self):
        result = self.run_tab(terminal="supacode", env={"SUPA_BOOT": self.BOOT})
        self.assertEqual(result.stdout.strip().splitlines(), [result.stdout.strip()], "one line")
        self.assertEqual(self.closes(), [])

    def test_the_flag_needs_supacode(self):
        result = self.run_cmux(extra=("--fresh-worktree",))
        self.assertTrue(result.stdout.startswith("FAILED BAD-FRESH-WORKTREE"), result.stdout)
        self.assertEqual(self.cmux_calls(), [])


for _name in [n for n in vars(NewSessionTabTest) if n.startswith("test_")]:
    setattr(FreshWorktreeTest, _name, None)  # reuse the fixtures, not the parent's tests


class VersionAndSkillTest(unittest.TestCase):
    def test_version_prints_the_plugin_version(self):
        manifest = json.loads((UTILS / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        result = subprocess.run([sys.executable, str(NEW_TAB), "--version"], capture_output=True, text=True,
                                timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), manifest["version"])
        self.assertGreaterEqual(tuple(int(p) for p in manifest["version"].split(".")), (0, 3, 0))

    def test_the_script_knows_nothing_about_captain(self):
        text = NEW_TAB.read_text(encoding="utf-8")
        for word in ("captain", "successor", "/captain resume"):
            self.assertNotIn(word, text.lower())

    def test_skill_names_the_script_the_lines_and_the_handover_flow(self):
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        for needle in ("scripts/new-session-tab.py", "--prompt-file=", "--terminal=", "--permission-mode=",
                       "TAB-OK", "TAB-DEAD", "TAB-NONE", "./tmp/handover-<topic>-<date>.md", "CLAUDE_PLUGIN_ROOT",
                       "a shell ran"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
