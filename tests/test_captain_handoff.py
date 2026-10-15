#!/usr/bin/env python3
"""Tests for the captain handoff process (R21): hooks/handoff_at_boundary.py, hooks/kickoff_on_clear.py,
the measure-context copy, and the text that names them.

Every hook runs as a subprocess with HOME redirected to a tempdir, so no real ~/.claude is touched.

Run:  python3 tests/test_captain_handoff.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_new_session_tab import SUPACODE_STUB, worktree_row  # noqa: E402  (shared tab stubs)

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "captain"
SKILL_DIR = PLUGIN / "skills" / "captain"
BOUNDARY = PLUGIN / "hooks" / "handoff_at_boundary.py"
KICKOFF = PLUGIN / "hooks" / "kickoff_on_clear.py"
MEASURE = SKILL_DIR / "scripts" / "measure-context.py"
HOOKS_JSON = PLUGIN / "hooks" / "hooks.json"
SESSION = "c969799f-4996-462a-86bd-e085e620405a"
SUCCESSOR_TAB = SKILL_DIR / "scripts" / "successor-tab.py"
UTILS_PLUGIN = ROOT / "plugins" / "utils"
# The test host may itself run in Supacode or another Claude session; none of that may leak in.
HOST_ENV = {"HANDOFF_CONTEXT_THRESHOLD", "TERM_PROGRAM", "SUPACODE_WORKTREE_ID", "CLAUDE_CODE_SESSION_ID",
            "CMUX_SOCKET_PATH", "CMUX_WORKSPACE_ID", "CMUX_SURFACE_ID", "CMUX_BUNDLED_CLI_PATH"}


def usage_line(tokens: int, sidechain: bool = False) -> dict:
    return {"type": "assistant", "isSidechain": sidechain,
            "message": {"usage": {"input_tokens": 10, "cache_read_input_tokens": tokens - 10,
                                  "cache_creation_input_tokens": 0}}}


CLAUDE_STUB = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["CLAUDE_STUB_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
window = os.environ.get("CLAUDE_STUB_WINDOW")
if not window:
    sys.exit(1)
model = sys.argv[sys.argv.index("--model") + 1]
usage = {model: {"contextWindow": int(window), "costUSD": 0.01}}
if os.environ.get("CLAUDE_STUB_OTHER"):  # Claude Code may also report a side model, e.g. for a title
    usage = {os.environ["CLAUDE_STUB_OTHER"]: {"contextWindow": 9_000_000}, **usage}
if os.environ.get("CLAUDE_STUB_ONLY_OTHER"):
    usage = {os.environ["CLAUDE_STUB_ONLY_OTHER"]: {"contextWindow": 9_000_000}}
print(json.dumps({"type": "result", "modelUsage": usage}))
"""


class HookCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.state = Path(self.tmp.name) / "sessions"

    def tearDown(self):
        self.tmp.cleanup()

    def transcript(self, tokens: int = 0, name: str | None = None) -> Path:
        path = Path(self.tmp.name) / "session.jsonl"
        records = []
        if name:
            records.append({"type": "custom-title", "customTitle": name})
        if tokens:
            records.append(usage_line(tokens))
        path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        return path

    def run_hook(self, script: Path, event: dict, env: dict | None = None) -> subprocess.CompletedProcess:
        base = {k: v for k, v in os.environ.items() if k not in HOST_ENV}
        full = {**base, "HOME": str(self.home), "CAPTAIN_STATE_DIR": str(self.state), **(env or {})}
        return subprocess.run([sys.executable, str(script)], input=json.dumps(event),
                              capture_output=True, text=True, timeout=30, env=full)

    def claude_stub(self, window: int | None) -> dict:
        """Env with a stub `claude` on PATH that reports `window` as the model's contextWindow
        (None: the probe fails), logging each call to self.claude_log."""
        bin_dir = Path(self.tmp.name) / "claude-bin"
        bin_dir.mkdir(exist_ok=True)
        (bin_dir / "claude").write_text(CLAUDE_STUB, encoding="utf-8")
        (bin_dir / "claude").chmod(0o755)
        self.claude_log = Path(self.tmp.name) / "claude.log"
        env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "CLAUDE_STUB_LOG": str(self.claude_log)}
        if window:
            env["CLAUDE_STUB_WINDOW"] = str(window)
        return env

    def probes(self) -> int:
        log = getattr(self, "claude_log", None)
        return len(log.read_text(encoding="utf-8").splitlines()) if log and log.exists() else 0

    def model_transcript(self, tokens: int, model: str = "claude-opus-5-5", name: str = "proj-captain") -> Path:
        path = self.transcript(0, name=name)
        records = [{"type": "assistant", "isSidechain": True, "message": {"model": "claude-haiku-4-5", "usage": {}}},
                   {"type": "assistant", "isSidechain": False, "message": {
                       "model": model, "usage": {"input_tokens": 10, "cache_read_input_tokens": tokens - 10}}},
                   {"type": "assistant", "isSidechain": True, "message": {"model": "claude-haiku-4-5", "usage": {}}}]
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("".join(json.dumps(r) + "\n" for r in records))
        return path

    def captain_mode(self, on: bool = True):
        self.state.mkdir(parents=True, exist_ok=True)
        if on:
            (self.state / SESSION).write_text("{}\n", encoding="utf-8")

    def settings(self, command: str):
        data = {"hooks": {"PreToolUse": [{"matcher": "Agent|Task", "hooks": [{"type": "command", "command": command}]}]}}
        (self.home / ".claude" / "settings.json").write_text(json.dumps(data), encoding="utf-8")

    def config(self, **values):
        directory = self.home / ".claude" / "captain"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "config.json").write_text(json.dumps({"version": 1, **values}), encoding="utf-8")


class BoundaryHookTest(HookCase):
    def dispatch(self, transcript: Path, description="Implement ЗД3: the export page",
                 kind="captain:worker", env=None, **extra) -> subprocess.CompletedProcess:
        event = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "session_id": SESSION,
                 "transcript_path": str(transcript), "cwd": str(self.home),
                 "tool_input": {"description": description, "subagent_type": kind, "prompt": "x"}, **extra}
        return self.run_hook(BOUNDARY, event, env)

    def denial(self, result: subprocess.CompletedProcess):
        self.assertEqual(result.returncode, 0, result.stderr)
        if not result.stdout.strip():
            return None
        out = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual((out["hookEventName"], out["permissionDecision"]), ("PreToolUse", "deny"))
        return out["permissionDecisionReason"]

    def test_at_the_threshold_the_new_writer_is_held_once(self):
        self.captain_mode()
        tr = self.transcript(300_000, name="proj-captain")
        reason = self.denial(self.dispatch(tr))
        self.assertIn("~300k", reason)
        self.assertIn("threshold 250k", reason)
        self.assertIn("`~/.claude/kickoffs/proj-captain.md`", reason)
        self.assertIn("Контекстът е 300k", reason)
        self.assertIn("/captain resume", reason)
        self.assertIsNone(self.denial(self.dispatch(tr)), "the same dispatch goes through on retry")
        self.assertIsNotNone(self.denial(self.dispatch(tr, description="Implement ЗД4: the import page")),
                             "another task is held again")

    SUPACODE_ENV = {"TERM_PROGRAM": "supacode", "SUPACODE_WORKTREE_ID": "%2Frepo%2F"}

    def supacode_on_path(self) -> dict:
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir(exist_ok=True)
        stub = bin_dir / "supacode"
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
        return {"PATH": f"{bin_dir}:{os.environ['PATH']}"}

    def held_reason(self, env=None) -> str:
        for path in (self.home / ".claude" / "captain" / "hook-state").glob("*"):
            path.unlink()
        return self.denial(self.dispatch(self.transcript(300_000, name="proj-captain"), env=env))

    def assert_supacode_steps(self, reason: str):
        for needle in ("Successor terminal", "write no kickoff yet", "`ListAgents`", "scripts/successor-tab.py",
                       "STARTED", "reply ACK", "TaskStop for fallback sleeps", "наследникът <name> потвърди",
                       "TAB-DEAD", "closed=no", "not reachable"):
            self.assertIn(needle, reason)
        self.assertNotIn("напиши /clear", reason)
        self.assertIn("STAND-DOWN to it first) the /clear steps with the kickoff at "
                      "`~/.claude/kickoffs/proj-captain.md`", reason, "the fallback keeps the kickoff")

    def test_with_supacode_in_the_config_the_denial_opens_a_tab(self):
        self.captain_mode()
        self.config(successor_terminal="supacode")
        self.assert_supacode_steps(self.held_reason())

    def test_without_the_key_a_session_in_supacode_gets_a_tab(self):
        self.captain_mode()
        self.config()
        self.assert_supacode_steps(self.held_reason({**self.SUPACODE_ENV, **self.supacode_on_path()}))

    CMUX_ENV = {"CMUX_SOCKET_PATH": "/tmp/cmux.sock"}

    def cmux_on_path(self) -> dict:
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir(exist_ok=True)
        stub = bin_dir / "cmux"
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
        return {"PATH": f"{bin_dir}:{os.environ['PATH']}"}

    def test_with_cmux_in_the_config_the_denial_opens_a_tab(self):
        self.captain_mode()
        self.config(successor_terminal="cmux")
        self.assert_supacode_steps(self.held_reason())

    def test_without_the_key_a_session_in_cmux_gets_a_tab(self):
        self.captain_mode()
        self.config()
        self.assert_supacode_steps(self.held_reason({**self.CMUX_ENV, **self.cmux_on_path()}))

    def test_without_the_key_cmux_needs_the_socket_and_the_cli(self):
        self.captain_mode()
        self.config()
        for env in (self.cmux_on_path(), {**self.CMUX_ENV, "PATH": "/usr/bin:/bin"}):
            with self.subTest(env=sorted(env)):
                self.assertIn("напиши /clear, после `/captain resume`", self.held_reason(env))

    def test_none_beats_a_cmux_session(self):
        self.captain_mode()
        self.config(successor_terminal="none")
        self.assertIn("напиши /clear, после `/captain resume`",
                      self.held_reason({**self.CMUX_ENV, **self.cmux_on_path()}))

    def test_without_the_key_and_outside_supacode_it_is_clear(self):
        self.captain_mode()
        self.config()
        for env in ({}, {"TERM_PROGRAM": "supacode", **self.supacode_on_path()},
                    {**self.SUPACODE_ENV, "PATH": "/usr/bin:/bin"}):
            with self.subTest(env=sorted(env)):
                reason = self.held_reason(env)
                self.assertIn("`~/.claude/kickoffs/proj-captain.md`", reason)
                self.assertIn("напиши /clear, после `/captain resume`", reason)
                self.assertNotIn("Supacode", reason)

    def test_none_or_an_unknown_value_means_clear_even_in_supacode(self):
        for value in ("none", "tmux", "", 1, None):
            with self.subTest(value=value):
                self.captain_mode()
                self.config(successor_terminal=value)
                reason = self.held_reason({**self.SUPACODE_ENV, **self.supacode_on_path()})
                self.assertIn("напиши /clear, после `/captain resume`", reason)
                self.assertNotIn("Supacode", reason)

    def test_below_the_threshold_nothing_happens(self):
        self.captain_mode()
        self.assertIsNone(self.denial(self.dispatch(self.transcript(249_000))))

    def test_threshold_from_the_captain_config_and_from_the_env(self):
        self.captain_mode()
        tr = self.transcript(150_000)
        self.assertIsNone(self.denial(self.dispatch(tr)))  # default 250k
        self.config(context_threshold=100_000)
        self.assertIn("threshold 100k", self.denial(self.dispatch(tr, description="Implement ЗД5: a")))
        self.assertIn("threshold 120k", self.denial(self.dispatch(
            tr, description="Implement ЗД6: b", env={"HANDOFF_CONTEXT_THRESHOLD": "120k"})))

    def test_a_percentage_threshold_follows_the_model_window(self):
        self.captain_mode()
        self.config(context_threshold="45%")
        tr = self.model_transcript(300_000)
        reason = self.denial(self.dispatch(tr, env=self.claude_stub(500_000)))
        self.assertIn("threshold 225k", reason)
        self.assertEqual(self.probes(), 1)
        self.assertIsNone(self.denial(self.dispatch(self.model_transcript(200_000), description="Implement ЗД7: c",
                                                    env=self.claude_stub(500_000))), "200k < 225k")
        self.assertEqual(self.probes(), 1, "the window is cached")

    def test_a_session_without_a_name_is_told_to_rename(self):
        self.captain_mode()
        self.assertIn("/rename", self.denial(self.dispatch(self.transcript(300_000))))

    def test_only_a_captain_session_is_held(self):
        self.captain_mode(on=False)
        self.assertIsNone(self.denial(self.dispatch(self.transcript(300_000))))

    def test_work_inside_a_task_is_not_a_boundary(self):
        self.captain_mode()
        tr = self.transcript(300_000)
        for description in ("Review ЗД3 round 2", "Verify ЗД3 on the real data", "Fix ЗД3 findings",
                            "Интегрирай ЗД3 и ЗД4", "Ревю на ЗД3"):
            self.assertIsNone(self.denial(self.dispatch(tr, description=description)), description)
        for kind in ("captain:runner", "captain:deep", "general-purpose", ""):
            self.assertIsNone(self.denial(self.dispatch(tr, kind=kind)), kind)

    def test_a_conflict_resolver_is_never_held(self):
        self.captain_mode()
        tr = self.transcript(300_000)
        for description in ("Resolve the conflict in ЗД3", "Conflict on a.txt", "Разреши конфликта в ЗД3",
                            "Конфликт при сливане", "resolver for ЗД4"):
            self.assertIsNone(self.denial(self.dispatch(tr, description=description)), description)

    def test_a_merge_in_progress_in_the_checkout_is_not_a_boundary(self):
        self.captain_mode()
        tr = self.transcript(300_000)
        repo = Path(self.tmp.name) / "repo"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        self.assertIsNotNone(self.denial(self.dispatch(tr, cwd=str(repo))), "no merge: still a boundary")
        for path in (self.home / ".claude" / "captain" / "hook-state").glob("*"):
            path.unlink()
        (repo / ".git" / "MERGE_HEAD").write_text("0" * 40 + "\n", encoding="utf-8")
        self.assertIsNone(self.denial(self.dispatch(tr, cwd=str(repo))))

    def test_a_merge_in_the_run_worktree_is_seen_from_the_main_checkout(self):
        # Codex r1 F2: main merges in the run worktree, while the session runs in the main checkout
        self.captain_mode()
        tr = self.transcript(300_000)
        repo, tree = Path(self.tmp.name) / "repo", Path(self.tmp.name) / "run-tree"
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                        "--allow-empty", "-m", "x"], check=True)
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", "captain/run", str(tree)],
                       check=True)
        merge_head = subprocess.run(["git", "-C", str(tree), "rev-parse", "--path-format=absolute",
                                     "--git-path", "MERGE_HEAD"], capture_output=True, text=True).stdout.strip()
        Path(merge_head).write_text("0" * 40 + "\n", encoding="utf-8")
        self.assertIsNone(self.denial(self.dispatch(tr, description="Finish ЗД3", cwd=str(repo))))

    def test_subagents_and_other_tools_pass(self):
        self.captain_mode()
        tr = self.transcript(300_000)
        self.assertIsNone(self.denial(self.dispatch(tr, agent_id="a1")))
        self.assertIsNone(self.denial(self.dispatch(tr, tool_name="Bash")))

    def test_the_global_coord_hook_does_not_silence_it(self):
        # 2026-10-05: coord's global hook only knows `Implement ...`, so deferring to it left captain ungated
        self.captain_mode()
        tr = self.transcript(300_000)
        self.settings("/Users/x/.claude/hooks/handoff-at-boundary.py")
        self.assertIsNotNone(self.denial(self.dispatch(tr, description="Size cap in the upload step")))

    def test_bad_input_never_blocks(self):
        for raw in ("", "not json", "[]", '{"tool_name": "Agent"}'):
            result = subprocess.run([sys.executable, str(BOUNDARY)], input=raw, capture_output=True, text=True,
                                    env={**os.environ, "HOME": str(self.home)})
            self.assertEqual((result.returncode, result.stdout), (0, ""), raw)


class KickoffHookTest(HookCase):
    def clear(self, transcript: Path, source="clear") -> subprocess.CompletedProcess:
        event = {"hook_event_name": "SessionStart", "source": source, "session_id": SESSION,
                 "transcript_path": str(transcript), "cwd": str(self.home)}
        return self.run_hook(KICKOFF, event)

    def kickoff(self, name="proj-captain", text="You ARE the proj captain, the successor.") -> Path:
        directory = self.home / ".claude" / "kickoffs"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.md"
        path.write_text(text + "\n", encoding="utf-8")
        return path

    def test_clear_injects_the_named_kickoff_and_moves_it_to_kickoff_used(self):
        path = self.kickoff()
        result = self.clear(self.transcript(name="proj-captain"))
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        self.assertIn("You ARE the proj captain, the successor.", out["additionalContext"])
        self.assertIn("/captain resume", out["additionalContext"])
        self.assertFalse(path.exists())
        used = list((path.parent / "kickoff-used").glob("*.md"))
        self.assertEqual(len(used), 1)
        self.assertIn("successor", used[0].read_text())
        self.assertEqual(self.clear(self.transcript(name="proj-captain")).stdout, "", "a later /clear never replays it")

    def test_the_last_rename_wins(self):
        self.kickoff("proj-captain")
        tr = self.transcript(name="proj-captain-old")
        with open(tr, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "custom-title", "customTitle": "proj-captain"}) + "\n")
        self.assertIn("successor", self.clear(tr).stdout)

    def test_only_clear_with_a_name_and_a_file_injects(self):
        path = self.kickoff()
        self.assertEqual(self.clear(self.transcript(name="proj-captain"), source="startup").stdout, "")
        self.assertEqual(self.clear(self.transcript()).stdout, "", "no name, no kickoff: there is no repo fallback")
        self.assertEqual(self.clear(self.transcript(name="someone-else")).stdout, "")
        self.assertTrue(path.exists())

    def test_silent_when_the_global_coord_hook_is_installed(self):
        path = self.kickoff()
        self.settings("/Users/x/.claude/hooks/kickoff-on-clear.py")
        self.assertEqual(self.clear(self.transcript(name="proj-captain")).stdout, "")
        self.assertTrue(path.exists(), "the file stays for coord's hook")


class MeasureAndWiringTest(HookCase):
    def load_measure(self):
        spec = importlib.util.spec_from_file_location("measure_context_copy", MEASURE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_threshold_rule_of_the_copy(self):
        env = {k: v for k, v in os.environ.items() if k != "HANDOFF_CONTEXT_THRESHOLD"}
        old_home, old_env = os.environ.get("HOME"), dict(os.environ)
        try:
            os.environ.clear(); os.environ.update(env); os.environ["HOME"] = str(self.home)
            measure = self.load_measure()
            self.assertEqual(measure.config_threshold(), 250_000)
            self.config(context_threshold=180_000)
            self.assertEqual(measure.config_threshold(), 180_000)
            self.config(context_threshold="200k")
            self.assertEqual(measure.config_threshold(), 200_000)
            self.config(context_threshold="soon")
            self.assertEqual(measure.config_threshold(), 250_000)
            os.environ["HANDOFF_CONTEXT_THRESHOLD"] = "90k"
            self.assertEqual(measure.config_threshold(), 90_000)
        finally:
            os.environ.clear(); os.environ.update(old_env)
            if old_home:
                os.environ["HOME"] = old_home

    def test_percentage_rule_of_the_copy(self):
        old_env = dict(os.environ)
        try:
            os.environ.clear()
            os.environ.update({k: v for k, v in old_env.items() if k not in HOST_ENV})
            os.environ["HOME"] = str(self.home)
            os.environ.update(self.claude_stub(1_000_000))
            measure = self.load_measure()
            tr = str(self.model_transcript(10_000))
            self.config(context_threshold="45%")
            self.assertEqual(measure.session_model(tr), "claude-opus-5-5", "main chain only")
            self.assertEqual(measure.config_threshold(), 250_000, "no transcript, no model")
            self.assertEqual(measure.config_threshold(tr), 450_000)
            call = json.loads(self.claude_log.read_text(encoding="utf-8").splitlines()[0])
            for flag in ("-p", "--no-session-persistence", "--strict-mcp-config", "--setting-sources"):
                self.assertIn(flag, call)
            self.assertEqual(call[call.index("--model") + 1], "claude-opus-5-5")
            os.environ["CLAUDE_STUB_WINDOW"] = "500000"
            self.assertEqual(measure.config_threshold(tr), 450_000, "fresh cache, no new probe")
            self.assertEqual(self.probes(), 1)
            cache_path = self.home / ".claude" / "captain" / "context-windows.json"
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            cache["claude-opus-5-5"]["at"] -= 25 * 3600
            cache_path.write_text(json.dumps(cache), encoding="utf-8")
            self.assertEqual(measure.config_threshold(tr), 225_000, "stale cache → probe again")
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            cache["claude-opus-5-5"]["at"] -= 25 * 3600
            cache_path.write_text(json.dumps(cache), encoding="utf-8")
            del os.environ["CLAUDE_STUB_WINDOW"]
            self.assertEqual(measure.config_threshold(tr), 225_000, "a failed probe keeps the stale window")
            self.assertEqual(measure.config_threshold(tr), 225_000)
            self.assertEqual(self.probes(), 3, "a failed probe is not repeated within the hour")
            cache_path.unlink()
            self.assertEqual(measure.config_threshold(tr), 250_000, "no window at all → the default")
            self.assertEqual(measure.config_threshold(tr), 250_000)
            self.assertEqual(self.probes(), 4, "no retry within the hour without a window either")
            cache_path.unlink()
            os.environ["CLAUDE_STUB_WINDOW"] = "1000000"
            for raw in ("0%", "100%", "45 %", "4.5%"):
                self.config(context_threshold=raw)
                expected = {"0%": 250_000, "100%": 250_000, "45 %": 450_000, "4.5%": 45_000}[raw]
                self.assertEqual(measure.config_threshold(tr), expected, raw)
        finally:
            os.environ.clear(); os.environ.update(old_env)

    def test_the_probe_reads_only_the_window_of_the_asked_model(self):
        old_env = dict(os.environ)
        try:
            os.environ.clear()
            os.environ.update({k: v for k, v in old_env.items() if k not in HOST_ENV})
            os.environ["HOME"] = str(self.home)
            os.environ.update(self.claude_stub(200_000))
            measure = self.load_measure()
            os.environ["CLAUDE_STUB_OTHER"] = "claude-opus-5-5"
            self.assertEqual(measure.probe_window("claude-haiku-4-5"), 200_000)
            del os.environ["CLAUDE_STUB_OTHER"]
            os.environ["CLAUDE_STUB_ONLY_OTHER"] = "claude-opus-5-5"
            self.assertIsNone(measure.probe_window("claude-haiku-4-5"), "no entry for the model → failed")
        finally:
            os.environ.clear(); os.environ.update(old_env)

    def test_a_stale_window_is_refreshed_in_the_background_for_the_hook(self):
        old_env = dict(os.environ)
        try:
            os.environ.clear()
            os.environ.update({k: v for k, v in old_env.items() if k not in HOST_ENV})
            os.environ["HOME"] = str(self.home)
            os.environ.update(self.claude_stub(500_000))
            measure = self.load_measure()
            cache_path = self.home / ".claude" / "captain" / "context-windows.json"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            stale = {"claude-opus-5-5": {"window": 1_000_000, "at": int(time.time()) - 25 * 3600}}
            cache_path.write_text(json.dumps(stale), encoding="utf-8")
            started = time.time()
            self.assertEqual(measure.context_window("claude-opus-5-5", background=True), 1_000_000)
            self.assertLess(time.time() - started, 1.0, "the hook does not wait for the probe")
            self.assertIn(measure.context_window("claude-opus-5-5", background=True), (1_000_000, 500_000),
                          "the stale value, or the new one if the refresh already finished")
            deadline = time.time() + 15
            while time.time() < deadline:
                entry = json.loads(cache_path.read_text(encoding="utf-8"))["claude-opus-5-5"]
                if entry.get("window") == 500_000:
                    break
                time.sleep(0.2)
            self.assertEqual(entry.get("window"), 500_000, "the detached refresh wrote the new window")
            self.assertEqual(self.probes(), 1, "one refresh, not one per call")
        finally:
            os.environ.clear(); os.environ.update(old_env)

    def test_the_cli_threshold_takes_the_same_forms(self):
        old_env = dict(os.environ)
        try:
            os.environ.clear()
            os.environ.update({k: v for k, v in old_env.items() if k not in HOST_ENV})
            os.environ["HOME"] = str(self.home)
            os.environ.update(self.claude_stub(1_000_000))
            measure = self.load_measure()
            tr = self.model_transcript(300_000)
            self.assertEqual(measure.resolve_threshold("25%", str(tr)), 250_000)
            self.assertEqual(measure.resolve_threshold("200k", str(tr)), 200_000)
            for bad in (["--threshold"], ["--threshold", "soon"]):
                with self.subTest(bad=bad):
                    self.assertEqual(measure.main([str(self.home), *bad]), 2)
        finally:
            os.environ.clear(); os.environ.update(old_env)

    def test_context_is_the_last_main_chain_usage(self):
        tr = self.transcript(120_000)
        with open(tr, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(usage_line(900_000, sidechain=True)) + "\n")
        self.assertEqual(self.load_measure().context_tokens(str(tr)), 120_000)

    def test_hooks_json_registers_both_hooks(self):
        hooks = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]
        pre = [g for g in hooks["PreToolUse"] if g.get("matcher") == "Agent|Task"]
        self.assertEqual(len(pre), 1)
        self.assertGreater(pre[0]["hooks"][0]["timeout"], 15, "room for one context-window probe")
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/handoff_at_boundary.py", pre[0]["hooks"][0]["command"])
        start = hooks["SessionStart"]
        self.assertEqual(start[0]["matcher"], "clear")
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/kickoff_on_clear.py", start[0]["hooks"][0]["command"])


class HandoffTextTest(unittest.TestCase):
    def test_skill_names_the_rule_the_argument_and_the_reference(self):
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        for needle in ("### R21 — Handoff at a boundary", "`context_threshold`", "/captain resume",
                       "reference/handoff.md", "hooks/handoff_at_boundary.py", "the successor is the same"):
            self.assertIn(needle, text)

    def test_reference_carries_both_templates_and_the_name_rule(self):
        text = (SKILL_DIR / "reference" / "handoff.md").read_text(encoding="utf-8")
        for needle in ("You ARE the <project> captain, the successor", "~/.claude/kickoffs/<session",
                       "customTitle", "Never mid-operation", "Контекстът е Nk", "kickoff-used",
                       "## Handoff template", "## Kickoff template"):
            self.assertIn(needle, text)

    def test_reference_opens_the_supacode_successor_through_the_script_and_a_handshake(self):
        text = (SKILL_DIR / "reference" / "handoff.md").read_text(encoding="utf-8")
        for needle in ("## Successor terminal", "`successor_terminal`", "NO key → a Supacode tab when",
                       "`TERM_PROGRAM=supacode`", "`CMUX_SOCKET_PATH`", "verified live on 0.64.25", "OWN tab", "scripts/successor-tab.py' --dir=", "ALWAYS with `-w`",
                       "TAB-OK", "TERMINAL-NONE", "FAILED TAB-ELSEWHERE", "STARTED <NEW> pwd=",
                       "sleep 180", "sends that STAND-DOWN FIRST", "STAND-DOWN <NEW>: no STARTED in 3", "ACK <NEW>", "every owner instruction given since",
                       "`TaskStop` per fallback", "supacode tab close -w <worktree id> -t <tab id>",
                       "pure ASCII", "Two sessions must never coordinate one run", "2026-10-01", "2026-10-02",
                       "handoff=<path> from=<FROM> name=<NEW>", "arm no timer until `ACK <NEW>` arrives",
                       "FAILED TAB-DEAD <tab id> in=<worktree id> after=<N>s closed=yes|no", "the marker `<NEW>.alive`", "utils:new-session-tab", "FAILED NO-UTILS",
                       "closed=no", "*not reachable*", "2026-10-07", "a177ba90a",
                       "наследникът не тръгна: tab-ът се отвори без терминал"):
            self.assertIn(needle, text)
        self.assertNotIn("(it waits in the successor's queue if it is still starting)", text)
        self.assertNotIn("supacode tab new", text.split("**Why:**")[0], "the tab is opened by the script only")

    def test_skill_and_setup_name_the_successor_terminal(self):
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        for needle in ("`successor_terminal`, or detected", "scripts/successor-tab.py", "TAB-OK: a shell ran",
                       "/captain resume [handoff=<path> from=<name> name=<name>]",
                       "No pull request, opened or proposed, unless the owner asks for one."):
            self.assertIn(needle, skill)
        setup = (PLUGIN / "skills" / "captain-setup" / "SKILL.md").read_text(encoding="utf-8")
        for needle in ('"successor_terminal":"supacode|cmux|none"', "command -v supacode", "a177ba90a", "command -v cmux", "„В нов cmux tab в същия workspace“",
                       "question 5 skipped → leave the key out", "a Supacode tab when the session runs in Supacode"):
            self.assertIn(needle, setup)
        queue = (SKILL_DIR / "reference" / "queue.md").read_text(encoding="utf-8")
        self.assertIn("Never a pull request: not opened, not queued, not proposed", queue)

    def test_setup_asks_for_the_threshold(self):
        text = (PLUGIN / "skills" / "captain-setup" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn('"context_threshold":250000', text)
        self.assertIn('„45% от контекста на модела“ (препоръчвам) → `"45%"`', text)
        self.assertIn("handoff_at_boundary.py", text)


class SuccessorTabWrapperTest(unittest.TestCase):
    """scripts/successor-tab.py: the thin wrapper that finds the utils new-session-tab script.
    The tab behaviour itself is tested in tests/test_new_session_tab.py."""
    TAB = "0D1E2F30-AAAA-BBBB-CCCC-000000000001"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home = root / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.cache = root / "cache"
        self.bin = root / "bin"
        self.bin.mkdir()
        for name, body in (("supacode", SUPACODE_STUB), ("claude", "#!/bin/sh\nexit 0\n")):
            (self.bin / name).write_text(body, encoding="utf-8")
            (self.bin / name).chmod(0o755)
        self.repo = root / "repo"
        self.dir = self.repo / ".claude" / "worktrees" / "wt"
        self.dir.mkdir(parents=True)
        self.handoff = self.repo / "tmp" / "captain" / "r1" / "handoff-20261002-0700.md"
        self.handoff.parent.mkdir(parents=True)
        self.handoff.write_text("# handoff\n", encoding="utf-8")
        self.log = root / "supacode.log"

    def tearDown(self):
        self.tmp.cleanup()

    def install_utils(self, version: str, answers: str | None = None, marketplace: str = "mkt") -> Path:
        """utils <version> in the fake cache: the real plugin, or a stub script answering `answers`."""
        target = self.cache / marketplace / "utils" / version
        target.parent.mkdir(parents=True, exist_ok=True)
        if answers is None:
            target.symlink_to(UTILS_PLUGIN)
            return target
        script = target / "skills" / "new-session-tab" / "scripts" / "new-session-tab.py"
        script.parent.mkdir(parents=True)
        script.write_text(f"print({answers!r})\n", encoding="utf-8")
        return target

    def run_wrapper(self, config: dict | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
        path = self.home / ".claude" / "captain" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 1, **(config or {"successor_terminal": "supacode"})}),
                        encoding="utf-8")
        base = {k: v for k, v in os.environ.items() if k not in HOST_ENV}
        full = {**base, "HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin",
                "CAPTAIN_PLUGIN_CACHE": str(self.cache), "SUPA_LOG": str(self.log),
                "SUPA_ROWS": worktree_row(self.repo), "SUPA_TAB": self.TAB,
                "SUPA_TAB_IN": worktree_row(self.repo), "SUPA_RUN": "1", **(env or {})}
        return subprocess.run([sys.executable, str(SUCCESSOR_TAB), f"--dir={self.dir}", f"--handoff={self.handoff}",
                               "--from=proj-c5", "--name=proj-c5-r2", "--wait=1"],
                              capture_output=True, text=True, timeout=60, env=full)

    def calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def test_found_utils_opens_the_tab_with_the_resume_prompt(self):
        self.install_utils("0.2.0", answers="0.2.0")
        self.install_utils("0.3.0")
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        prompt = self.handoff.parent / "successor-prompt-proj-c5-r2.md"
        self.assertEqual(result.stdout.strip(), f"TAB-OK {self.TAB} {worktree_row(self.repo)} proj-c5-r2 "
                                                f"mode=default prompt={prompt}")
        self.assertEqual(prompt.read_text(encoding="utf-8"),
                         f"/captain resume handoff={self.handoff} from=proj-c5 name=proj-c5-r2\n")
        new = [c for c in self.calls() if c[:2] == ["tab", "new"]]
        self.assertEqual(len(new), 1, self.calls())
        marker = self.handoff.parent / "proj-c5-r2.alive"
        self.assertEqual(new[0][new[0].index("-i") + 1],
                         f'cd {self.dir} && : > {marker} && {self.bin / "claude"} -n proj-c5-r2 "$(cat {prompt})"')
        self.assertTrue(marker.exists())

    def test_the_highest_version_is_picked_numerically(self):
        self.install_utils("0.3.0")
        self.install_utils("0.10.0", answers="FAILED STUB from 0.10.0")
        self.install_utils("0.9.0", answers="0.9.0")
        result = self.run_wrapper()
        self.assertTrue(result.stdout.startswith("FAILED NO-UTILS utils 0.10.0 answers --version with no answer"),
                        result.stdout)

    def test_missing_utils_prints_the_install_command_and_opens_nothing(self):
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(result.stdout.startswith("FAILED NO-UTILS no utils plugin"), result.stdout)
        self.assertEqual(len(result.stdout.strip().splitlines()), 1)
        self.assertIn("owner: claude plugin install utils@", result.stdout)
        self.assertEqual(self.calls(), [])
        self.assertFalse(list(self.handoff.parent.glob("successor-prompt-*")))

    def test_too_old_utils_prints_the_update_command(self):
        self.install_utils("0.2.9", answers="0.2.9")
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "FAILED NO-UTILS utils 0.2.9 answers --version with 0.2.9, "
                                                "needs 0.3.0; owner: claude plugin update utils@mkt")
        self.assertEqual(self.calls(), [])

    def test_terminal_none_needs_no_utils(self):
        result = self.run_wrapper(config={"successor_terminal": "none"})
        self.assertEqual(result.returncode, 3, result.stdout)
        self.assertTrue(result.stdout.startswith("TERMINAL-NONE "), result.stdout)

    def test_a_failed_line_of_the_utils_script_is_passed_on(self):
        self.install_utils("0.3.0")
        result = self.run_wrapper(env={"SUPA_RUN": ""})
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(result.stdout.strip(),
                         f"FAILED TAB-DEAD {self.TAB} in={worktree_row(self.repo)} after=1s closed=yes")

    def test_captain_arguments_are_still_checked(self):
        self.install_utils("0.3.0")
        self.handoff.unlink()
        result = self.run_wrapper()
        self.assertTrue(result.stdout.startswith("FAILED BAD-HANDOFF"), result.stdout)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
