#!/usr/bin/env python3
"""Tests for the manual archive of stale captain session markers (archive-sessions.py)."""
from __future__ import annotations

import errno
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "plugins" / "captain" / "skills" / "captain" / "scripts" / "archive-sessions.py"
DAY = 86400
SPEC = importlib.util.spec_from_file_location("archive_sessions", ARCHIVE)
archive_sessions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(archive_sessions)


class ArchiveSessionsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(os.path.realpath(self.tmp.name))
        self.state = base / "captain" / "sessions"
        self.projects = base / "projects"
        self.state.mkdir(parents=True)
        (self.projects / "-some-repo").mkdir(parents=True)
        self.archive = base / "captain" / "sessions-archive" / time.strftime("%Y%m%d")
        self.env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_SESSION_ID"}
        self.env.update(CAPTAIN_STATE_DIR=str(self.state), CAPTAIN_PROJECTS_DIR=str(self.projects))

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path: Path, data: dict, days_old: float) -> Path:
        path.write_text(json.dumps(data) + "\n", encoding="utf-8")
        stamp = time.time() - days_old * DAY
        os.utime(path, (stamp, stamp))
        return path

    def session(self, sid: str, days_old: float, sidecars: bool = True,
                since_days: float | None = None) -> list[str]:
        since = int(time.time() - (days_old if since_days is None else since_days) * DAY)
        self.write(self.state / sid, {"since": since, "cwd": "/x", "run": "r"}, days_old)
        names = [sid]
        if sidecars:
            for suffix in (".merge", ".base"):
                self.write(self.state / f"{sid}{suffix}",
                           {"branch": "captain/x", "run": "r", "since": since}, days_old)
                names.append(f"{sid}{suffix}")
        return names

    def run_script(self, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(ARCHIVE), *args], capture_output=True,
                              text=True, env=env or self.env)

    def lines(self, result: subprocess.CompletedProcess) -> list[str]:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.splitlines()

    def line_for(self, lines: list[str], sid: str) -> str:
        found = [line for line in lines if line.split()[1:2] == [sid]]
        self.assertEqual(len(found), 1, lines)
        return found[0]

    def test_stale_session_is_archived_with_sidecars(self):
        names = self.session("old", 6)
        lines = self.lines(self.run_script("--older-than-days=5"))
        self.assertEqual(self.line_for(lines, "old"), "ARCHIVE old old old.merge old.base")
        for name in names:
            self.assertFalse((self.state / name).exists(), name)
            self.assertTrue((self.archive / name).is_file(), name)

    def test_recent_transcript_keeps_session(self):
        self.session("talking", 6)
        (self.projects / "-some-repo" / "talking.jsonl").write_text("{}\n", encoding="utf-8")
        lines = self.lines(self.run_script("--older-than-days=5"))
        self.assertTrue(self.line_for(lines, "talking").startswith("KEEP talking active "), lines)
        self.assertIn("talking.jsonl", self.line_for(lines, "talking"))
        self.assertTrue((self.state / "talking").is_file())

    def test_old_transcript_does_not_keep_session(self):
        self.session("quiet", 6)
        self.write(self.projects / "-some-repo" / "quiet.jsonl", {}, 7)
        lines = self.lines(self.run_script("--older-than-days=5"))
        self.assertTrue(self.line_for(lines, "quiet").startswith("ARCHIVE quiet "), lines)

    def test_calling_session_is_kept_from_env_and_option(self):
        self.session("me", 6)
        self.session("pinned", 6)
        env = dict(self.env, CLAUDE_CODE_SESSION_ID="me")
        lines = self.lines(self.run_script("--older-than-days=5", "--keep-session=pinned", env=env))
        self.assertEqual(self.line_for(lines, "me"), "KEEP me calling session")
        self.assertEqual(self.line_for(lines, "pinned"), "KEEP pinned calling session")
        self.assertTrue((self.state / "me").is_file())
        self.assertTrue((self.state / "pinned.merge").is_file())
        self.assertEqual(lines, ["KEEP me calling session", "KEEP pinned calling session"])

    def test_merge_since_under_12_hours_is_kept(self):
        # mtimes are 6 days back (e.g. a restored copy), the grant itself is 1 hour old
        self.session("granted", 6, since_days=1 / 24)
        lines = self.lines(self.run_script("--older-than-days=5"))
        self.assertEqual(self.line_for(lines, "granted"),
                         "KEEP granted granted.merge since is under 12 hours old")
        self.assertTrue((self.state / "granted.merge").is_file())

    def test_orphan_sidecars_older_than_age_are_archived(self):
        self.write(self.state / "gone.merge", {"since": int(time.time() - 8 * DAY)}, 8)
        self.write(self.state / "young.base", {"since": int(time.time() - 2 * DAY)}, 2)
        lines = self.lines(self.run_script("--older-than-days=5"))
        self.assertEqual(self.line_for(lines, "gone"), "ARCHIVE gone gone.merge")
        self.assertTrue(self.line_for(lines, "young").startswith("KEEP young active "))
        self.assertTrue((self.archive / "gone.merge").is_file())
        self.assertTrue((self.state / "young.base").is_file())

    def test_other_files_are_ignored(self):
        self.write(self.state / "notes.txt", {}, 30)
        self.write(self.state / "bad.name.merge", {}, 30)
        lines = self.lines(self.run_script("--older-than-days=5"))
        self.assertEqual(lines, [])
        self.assertTrue((self.state / "notes.txt").is_file())

    def test_dry_run_moves_nothing_and_prints_the_same_lines(self):
        names = self.session("old", 6)
        self.session("fresh", 1)
        dry = self.lines(self.run_script("--older-than-days=5", "--dry-run"))
        for name in names:
            self.assertTrue((self.state / name).is_file(), name)
        self.assertFalse(self.archive.exists())
        real = self.lines(self.run_script("--older-than-days=5"))
        self.assertEqual(dry, real)

    def test_restore_command_puts_files_back(self):
        names = self.session("old", 6) + self.session("older", 9, sidecars=False)
        lines = self.lines(self.run_script("--older-than-days=5"))
        self.assertTrue(lines[-1].startswith("NOTE "), lines)
        self.assertIn("/captain resume", lines[-1])
        restore = lines[-2]
        self.assertTrue(restore.startswith("mv -n "), restore)
        for name in names:
            self.assertFalse((self.state / name).exists(), name)
        result = subprocess.run(["sh", "-c", restore], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in names:
            self.assertTrue((self.state / name).is_file(), name)
            self.assertFalse((self.archive / name).exists(), name)

    def test_nothing_to_move_prints_no_restore(self):
        self.session("fresh", 1)
        lines = self.lines(self.run_script("--older-than-days=5"))
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("KEEP fresh "))

    def test_file_already_in_archive_is_never_overwritten(self):
        self.session("old", 6)
        self.archive.mkdir(parents=True)
        (self.archive / "old.base").write_text("earlier\n", encoding="utf-8")
        lines = self.lines(self.run_script("--older-than-days=5"))
        self.assertEqual(self.line_for(lines, "old"),
                         f"KEEP old already in archive: {self.archive / 'old.base'}")
        self.assertEqual((self.archive / "old.base").read_text(encoding="utf-8"), "earlier\n")
        self.assertTrue((self.state / "old.base").is_file())

    def test_dangling_symlink_in_archive_is_never_replaced(self):
        self.session("old", 6)
        self.archive.mkdir(parents=True)
        link = self.archive / "old.merge"
        link.symlink_to(self.archive / "missing-target")
        lines = self.lines(self.run_script("--older-than-days=5"))
        self.assertEqual(self.line_for(lines, "old"), f"KEEP old already in archive: {link}")
        self.assertTrue(link.is_symlink())
        self.assertTrue((self.state / "old.merge").is_file())

    def test_move_refuses_a_destination_that_appeared_after_the_check(self):
        source, target = self.state / "s.merge", self.state / "t.merge"
        source.write_text("new\n", encoding="utf-8")
        target.write_text("earlier\n", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            archive_sessions.move_no_replace(source, target)
        self.assertEqual(target.read_text(encoding="utf-8"), "earlier\n")
        self.assertTrue(source.is_file())

    def test_move_without_hard_links_copies_and_still_never_replaces(self):
        source, target = self.state / "s.base", self.state / "t.base"
        source.write_text("data\n", encoding="utf-8")
        cross = OSError(errno.EXDEV, "Invalid cross-device link")
        with mock.patch.object(archive_sessions.os, "link", side_effect=cross):
            archive_sessions.move_no_replace(source, target)
            self.assertFalse(source.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), "data\n")
            source.write_text("second\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                archive_sessions.move_no_replace(source, target)
        self.assertEqual(target.read_text(encoding="utf-8"), "data\n")
        self.assertTrue(source.is_file())

    def test_bad_arguments_exit_2(self):
        for args in ([], ["--older-than-days=0"], ["--older-than-days=x"],
                     ["--older-than-days=5", "--keep-session=../x"]):
            result = self.run_script(*args)
            self.assertEqual(result.returncode, 2, (args, result.stdout, result.stderr))

    def test_missing_state_dir_is_not_an_error(self):
        env = dict(self.env, CAPTAIN_STATE_DIR=str(self.state / "absent"))
        result = self.run_script("--older-than-days=5", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
