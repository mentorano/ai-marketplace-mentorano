#!/usr/bin/env python3
"""Tests for plugins/utils/skills/bg-claude-rc/start.sh.

`claude` is a stub on PATH that answers `agents --json`, `--bg` and `logs` from files the
test writes, and records the arguments it got. HOME is a tempdir, so no real session or
transcript is read and nothing is started.

Run:  python3 tests/test_bg_claude_rc.py
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
START = ROOT / "plugins" / "utils" / "skills" / "bg-claude-rc" / "start.sh"
HOST = "claude.ai"  # a made-up session link for the stub log
URL = f"https://{HOST}/code/session_01AbCdEfGhIjKlMnOpQrStUvWx"

STUB = """#!/usr/bin/env bash
echo "$*" >> "$STUB_DIR/calls"
case "$1" in
  agents) [ -f "$STUB_DIR/agents-fail" ] && exit 1; cat "$STUB_DIR/agents.json" ;;
  --bg) printf 'session \\033[36mbackgrounded · 79e56fd5\\033[39m\\n' ;;
  logs) cat "$STUB_DIR/logs" 2>/dev/null ;;
esac
"""


class StartScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        stub = self.bin / "claude"
        stub.write_text(STUB)
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        self.home = self.tmp / "home"
        (self.home / ".claude" / "projects" / "p").mkdir(parents=True)
        self.repo = self.tmp / "my-web-app"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.live([])
        self.today = time.strftime("%Y%m%d")

    def live(self, names):
        (self.tmp / "agents.json").write_text(json.dumps([{"name": n} for n in names]))

    def run_start(self, *args, cwd=None, env=None):
        env = dict(os.environ, HOME=str(self.home), STUB_DIR=str(self.tmp), TMPDIR=str(self.tmp),
                   PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}", **(env or {}))
        return subprocess.run([str(START), *args], cwd=cwd or self.repo, env=env,
                              capture_output=True, text=True, timeout=60)

    def fields(self, out):
        return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)

    def test_slug_is_the_initials_of_the_repository_name(self):
        result = self.run_start("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.fields(result.stdout)["name"], f"mwa-{self.today}-rc1")

    def test_runs_from_a_subdirectory_with_the_git_root_name(self):
        sub = self.repo / "src" / "deep"
        sub.mkdir(parents=True)
        result = self.run_start("--dry-run", cwd=sub)
        self.assertEqual(self.fields(result.stdout)["name"], f"mwa-{self.today}-rc1")

    def test_a_live_session_name_is_skipped(self):
        self.live([f"mwa-{self.today}-rc1", f"mwa-{self.today}-rc2", f"other-{self.today}-rc3"])
        result = self.run_start("--dry-run")
        self.assertEqual(self.fields(result.stdout)["name"], f"mwa-{self.today}-rc3")

    def test_a_stopped_session_name_from_a_transcript_is_skipped(self):
        transcript = self.home / ".claude" / "projects" / "p" / "s.jsonl"
        transcript.write_text(json.dumps({"customTitle": f"web-{self.today}-rc1"}, separators=(",", ":")) + "\n")
        result = self.run_start("--dry-run", "web")
        self.assertEqual(self.fields(result.stdout)["name"], f"web-{self.today}-rc2")

    def test_defaults_and_overrides_for_model_and_effort(self):
        default = self.fields(self.run_start("--dry-run").stdout)
        self.assertEqual((default["model"], default["effort"]), ("opus", "high"))
        custom = self.fields(self.run_start("--model=sonnet", "--effort", "low", "--dry-run").stdout)
        self.assertEqual((custom["model"], custom["effort"]), ("sonnet", "low"))

    def test_bad_input_stops_before_anything_starts(self):
        for args in (["--effort", "huge"], ["--nope"], ["Bad-Slug"], ["a", "b"], ["--model"]):
            with self.subTest(args=args):
                result = self.run_start(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("start.sh:", result.stderr)
        calls = self.tmp / "calls"
        self.assertFalse(calls.exists() and "--bg" in calls.read_text())

    def test_a_failing_agents_listing_stops_the_script(self):
        (self.tmp / "agents-fail").write_text("")
        result = self.run_start()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("--bg", (self.tmp / "calls").read_text())

    def test_a_held_lock_stops_the_script_and_stays_in_place(self):
        lock = self.tmp / "bg-claude-rc.lock"
        lock.mkdir()
        result = self.run_start(env={"BG_CLAUDE_RC_LOCK_WAIT": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"rmdir {lock}", result.stderr)
        self.assertTrue(lock.is_dir(), "the other start's lock was removed")
        self.assertFalse((self.tmp / "calls").exists() and "--bg" in (self.tmp / "calls").read_text())

    def test_a_missing_url_leaves_url_empty_and_says_where_to_look(self):
        result = self.run_start(env={"BG_CLAUDE_RC_URL_WAIT": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        out = self.fields(result.stdout)
        self.assertEqual(out["url"], "")
        self.assertIn("claude logs 79e56fd5", out["note"])

    def test_start_passes_the_name_twice_and_prints_the_longest_url(self):
        (self.tmp / "logs").write_text(f"{URL[:-6]}\n\x1b[2m{URL}\x1b[0m\n")
        result = self.run_start("--model", "haiku")
        self.assertEqual(result.returncode, 0, result.stderr)
        out = self.fields(result.stdout)
        name = f"mwa-{self.today}-rc1"
        self.assertEqual((out["name"], out["id"], out["url"]), (name, "79e56fd5", URL))
        self.assertIn(f"--bg --remote-control {name} -n {name} --model haiku --effort high",
                      (self.tmp / "calls").read_text())
        self.assertFalse((self.tmp / "bg-claude-rc.lock").exists())


if __name__ == "__main__":
    if shutil.which("jq") is None:
        print("SKIP test_bg_claude_rc: needs jq on PATH")
        sys.exit(0)
    unittest.main(argv=[sys.argv[0]] + sys.argv[1:])
