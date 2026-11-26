#!/usr/bin/env python3
"""Tests for the 3amigos config layer: plugins/3amigos/skills/3amigos/scripts/amigos_config.py
and the config flags of panel.py (--panel, --show-config, --voters).

Spec decisions: GV1, GV2 (the --voters rule), GV4 and the config cases of GV8. amigos_config is imported from the scripts dir; panel.py is run for real
with cwd= a temp dir and HOME redirected to a temp dir. PATH is the stub dir + /usr/bin + /bin: stub
`codex`, `agy` and `gcloud` binaries only count their calls and exit 1, the Gemini fallback is `none`
and the REST base points at a closed local port, so no case reaches a real voter or the network.
The --voters default cases start a stub voter and assert which stubs were called, not the result.

Run:  python3 tests/test_3amigos_config.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "plugins" / "3amigos" / "skills" / "3amigos" / "scripts"
PANEL = SCRIPTS / "panel.py"

DEFAULT_PANEL = ["codex", "gemini", "fable"]
DEFAULT_GEMINI = {
    "agy": True,
    "model": "gemini-4-carbon",
    "model_fallback": "gemini-4-argon",
    "effort": "high",
    "fallback": "none",
    "vertex": {"project": None, "location": "global"},
    "key_env": "GEMINI_API_KEY",
    "key_dotenv": None,
}

DEFAULT_SOURCE_KEYS = {
    "panel", "gemini.agy", "gemini.model", "gemini.model_fallback", "gemini.effort", "gemini.fallback",
    "gemini.vertex.project", "gemini.vertex.location", "gemini.key_env", "gemini.key_dotenv",
}

FAKE_ENV_KEY = "FAKE-KEY-123"
FAKE_DOTENV_KEY = "FAKE-DOTENV-KEY-456"
FAKE_OTHER = "FAKE-OTHER-789"

# Counts every call in $STUB_DIR/<name>.calls and fails; a voter that starts by mistake shows up.
STUB = '#!/bin/sh\nprintf x >> "$STUB_DIR/$(basename "$0").calls"\nexit 1\n'

GIT = ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",
       "-c", "core.hooksPath=/dev/null", "-c", "init.defaultBranch=main"]


def amigos_config():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import amigos_config as module
    return module


def write_json(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")
    return path


def git(cwd: Path, *args):
    subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=30)


class ConfigTestBase(unittest.TestCase):
    def setUp(self):
        # realpath: git reports /private/var/... on macOS, the paths must compare equal
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.plain = self.tmp / "plain"  # not a git repo
        self.plain.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for name in ("codex", "agy", "gcloud"):
            stub = self.bin / name
            stub.write_text(STUB)
            stub.chmod(0o755)

    # -- paths -------------------------------------------------------------------------------
    def user_config(self, obj) -> Path:
        return write_json(self.home / ".claude" / "3amigos" / "config.json", obj)

    def make_repo(self, name="repo") -> Path:
        repo = self.tmp / name
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "commit", "-q", "--allow-empty", "-m", "init")
        return repo

    @staticmethod
    def project_config(main: Path, obj) -> Path:
        return write_json(main / ".claude" / "3amigos.local.json", obj)

    # -- runs --------------------------------------------------------------------------------
    def load(self, cwd: Path):
        return amigos_config().load(cwd=str(cwd), home=str(self.home))

    def calls(self, name):
        path = self.tmp / f"{name}.calls"
        return len(path.read_text()) if path.exists() else 0

    def assert_no_voter_ran(self):
        for name in ("codex", "agy", "gcloud"):
            self.assertEqual(self.calls(name), 0, name)

    def run_panel(self, *args, cwd: Path, extra_env=None):
        env = {k: v for k, v in os.environ.items()
               if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "AMIGOS_GEMINI_API_BASE")}
        env.update(PATH=os.pathsep.join((str(self.bin), "/usr/bin", "/bin")), HOME=str(self.home),
                   STUB_DIR=str(self.tmp), AMIGOS_GEMINI_API_BASE="http://127.0.0.1:9")
        env.update(extra_env or {})
        return subprocess.run([sys.executable, str(PANEL), *args], cwd=cwd, env=env,
                              capture_output=True, text=True, timeout=60)

    def show_config(self, *args, cwd: Path, extra_env=None) -> dict:
        p = self.run_panel("--show-config", *args, cwd=cwd, extra_env=extra_env)
        self.assertEqual(p.returncode, 0, p.stderr)
        lines = p.stdout.splitlines()
        self.assertEqual(len(lines), 1, p.stdout)
        return json.loads(lines[0])

    def run_args(self):
        (self.tmp / "task.md").write_text("Propose ideas.")
        (self.tmp / "data.md").write_text("data")
        return ["--task", str(self.tmp / "task.md"), "--input", str(self.tmp / "data.md"),
                "--out", str(self.tmp / "out")]


class LoadTest(ConfigTestBase):
    """amigos_config.load(): defaults, paths, precedence, project root (GV1, GV4)."""

    def test_no_config_gives_the_defaults_from_default_sources(self):
        cfg = self.load(self.plain)
        self.assertEqual(cfg["panel"], DEFAULT_PANEL)
        self.assertEqual(cfg["external"], ["codex", "gemini"])
        self.assertEqual(cfg["gemini"], DEFAULT_GEMINI)
        self.assertEqual(cfg["errors"], [])
        self.assertEqual(cfg["sources"], {key: "default" for key in DEFAULT_SOURCE_KEYS})

    def test_user_config_is_read_from_home_claude_3amigos_config_json(self):
        self.user_config({"version": 1, "gemini": {"model": "gemini-user-model"}})
        cfg = self.load(self.plain)
        self.assertEqual(cfg["gemini"]["model"], "gemini-user-model")
        self.assertEqual(cfg["sources"]["gemini.model"], "user")

    def test_project_config_is_read_from_main_checkout_claude_3amigos_local_json(self):
        repo = self.make_repo()
        self.project_config(repo, {"version": 1, "gemini": {"effort": "low"}})
        cfg = self.load(repo)
        self.assertEqual(cfg["project_root"], str(repo))
        self.assertEqual(cfg["gemini"]["effort"], "low")
        self.assertEqual(cfg["sources"]["gemini.effort"], "project")

    def test_linked_worktree_reads_the_main_checkout_project_config(self):
        repo = self.make_repo()
        worktree = self.tmp / "linked"
        git(repo, "worktree", "add", "-q", "-b", "side", str(worktree))
        self.project_config(repo, {"version": 1, "gemini": {"fallback": "key"}})
        cfg = self.load(worktree)
        self.assertEqual(cfg["project_root"], str(repo))
        self.assertEqual(cfg["gemini"]["fallback"], "key")
        self.assertEqual(cfg["sources"]["gemini.fallback"], "project")

    def test_dir_outside_git_has_no_project_config_and_no_error(self):
        self.user_config({"version": 1, "gemini": {"effort": "medium"}})
        cfg = self.load(self.plain)
        self.assertIsNone(cfg["project_root"])
        self.assertEqual(cfg["errors"], [])
        self.assertEqual(cfg["gemini"]["effort"], "medium")
        self.assertNotIn("project", cfg["sources"].values())

    def test_git_dir_not_named_dot_git_has_no_main_checkout(self):
        sep = self.tmp / "sep"
        git(self.tmp, "init", "-q", "--separate-git-dir", str(self.tmp / "store.git"), str(sep))
        git(sep, "commit", "-q", "--allow-empty", "-m", "init")
        self.project_config(self.tmp, {"version": 1, "gemini": {"effort": "low"}})  # beside store.git
        self.project_config(sep, {"version": 1, "gemini": {"effort": "low"}})
        cfg = self.load(sep)
        self.assertIsNone(cfg["project_root"])
        self.assertEqual(cfg["files"]["project"], "none (no main checkout)")
        self.assertEqual(cfg["gemini"]["effort"], "high")
        self.assertNotIn("project", cfg["sources"].values())

    def test_user_and_project_keys_merge_key_by_key(self):
        repo = self.make_repo()
        self.user_config({"version": 1, "gemini": {"model": "gemini-user-model"}})
        self.project_config(repo, {"version": 1, "gemini": {"effort": "low"}})
        cfg = self.load(repo)
        self.assertEqual((cfg["gemini"]["model"], cfg["sources"]["gemini.model"]), ("gemini-user-model", "user"))
        self.assertEqual((cfg["gemini"]["effort"], cfg["sources"]["gemini.effort"]), ("low", "project"))
        self.assertEqual((cfg["gemini"]["model_fallback"], cfg["sources"]["gemini.model_fallback"]),
                         ("gemini-4-argon", "default"))

    def test_project_wins_over_user_on_the_same_key(self):
        repo = self.make_repo()
        self.user_config({"version": 1, "panel": ["codex", "opus", "fable"], "gemini": {"effort": "low"}})
        self.project_config(repo, {"version": 1, "panel": ["gemini", "opus", "fable"], "gemini": {"effort": "medium"}})
        cfg = self.load(repo)
        self.assertEqual((cfg["panel"], cfg["sources"]["panel"]), (["gemini", "opus", "fable"], "project"))
        self.assertEqual((cfg["gemini"]["effort"], cfg["sources"]["gemini.effort"]), ("medium", "project"))

    def test_vertex_keys_merge_nested(self):
        repo = self.make_repo()
        self.user_config({"version": 1, "gemini": {"vertex": {"project": "example-project"}}})
        self.project_config(repo, {"version": 1, "gemini": {"vertex": {"location": "eu"}}})
        cfg = self.load(repo)
        self.assertEqual(cfg["gemini"]["vertex"], {"project": "example-project", "location": "eu"})
        self.assertEqual(cfg["sources"]["gemini.vertex.project"], "user")
        self.assertEqual(cfg["sources"]["gemini.vertex.location"], "project")

    def test_run_panel_argument_wins_over_project_and_user(self):
        repo = self.make_repo()
        self.user_config({"version": 1, "panel": ["codex", "opus", "fable"]})
        self.project_config(repo, {"version": 1, "panel": ["gemini", "opus", "fable"]})
        cfg = amigos_config().load(cwd=str(repo), home=str(self.home), panel=["fable", "codex", "opus"])
        self.assertEqual((cfg["panel"], cfg["sources"]["panel"]), (["fable", "codex", "opus"], "run"))
        self.assertEqual(cfg["external"], ["codex"])

    def test_files_names_the_user_and_main_checkout_project_config(self):
        repo = self.make_repo()
        user = self.user_config({"version": 1})
        files = self.load(repo)["files"]
        self.assertEqual(files["user"], str(user))
        self.assertEqual(files["project"], str(repo / ".claude" / "3amigos.local.json"))

    def test_files_project_from_a_linked_worktree_is_the_main_checkout_path(self):
        repo = self.make_repo()
        worktree = self.tmp / "linked"
        git(repo, "worktree", "add", "-q", "-b", "side", str(worktree))
        self.assertEqual(self.load(worktree)["files"]["project"], str(repo / ".claude" / "3amigos.local.json"))

    def test_files_project_outside_git_is_none_no_main_checkout(self):
        self.assertEqual(self.load(self.plain)["files"]["project"], "none (no main checkout)")

    def test_external_is_panel_codex_gemini_in_panel_order(self):
        repo = self.make_repo()
        self.project_config(repo, {"version": 1, "panel": ["gemini", "opus", "codex"]})
        self.assertEqual(self.load(repo)["external"], ["gemini", "codex"])
        self.project_config(repo, {"version": 1, "panel": ["opus", "fable", "gemini"]})
        self.assertEqual(self.load(repo)["external"], ["gemini"])
        self.project_config(repo, {"version": 1, "panel": ["opus", "fable", "codex"]})
        self.assertEqual(self.load(repo)["external"], ["codex"])


class BrokenConfigTest(ConfigTestBase):
    """A broken config never raises; load() names the file in errors (GV4, AR5 F12)."""

    def assert_error_names(self, cfg, path: Path):
        self.assertTrue(any(str(path) in e for e in cfg["errors"]), cfg["errors"])

    def test_user_config_that_is_not_json_is_an_error_not_a_raise(self):
        path = self.user_config("{not json")
        cfg = self.load(self.plain)
        self.assert_error_names(cfg, path)
        self.assertEqual(cfg["panel"], DEFAULT_PANEL)
        self.assertEqual(cfg["gemini"], DEFAULT_GEMINI)

    def test_project_config_that_is_not_json_is_an_error_not_a_raise(self):
        repo = self.make_repo()
        path = self.project_config(repo, "{not json")
        cfg = self.load(repo)
        self.assert_error_names(cfg, path)
        self.assertEqual(cfg["panel"], DEFAULT_PANEL)

    def test_unknown_voter_in_config_panel_is_an_error_and_the_default_stays(self):
        path = self.user_config({"version": 1, "panel": ["codex", "grok", "fable"]})
        cfg = self.load(self.plain)
        self.assert_error_names(cfg, path)
        self.assertEqual(cfg["panel"], DEFAULT_PANEL)

    def test_out_of_enum_value_is_an_error_and_the_default_stays(self):
        repo = self.make_repo()
        path = self.project_config(repo, {"version": 1, "gemini": {"effort": "extreme", "fallback": "cloud"}})
        cfg = self.load(repo)
        self.assert_error_names(cfg, path)
        self.assertEqual(cfg["gemini"]["effort"], "high")
        self.assertEqual(cfg["gemini"]["fallback"], "none")

    def test_unknown_top_level_key_is_an_error(self):
        path = self.user_config({"version": 1, "voters": ["codex"]})
        self.assert_error_names(self.load(self.plain), path)

    def test_unknown_key_under_gemini_is_an_error(self):
        path = self.user_config({"version": 1, "gemini": {"modle": "gemini-user-model"}})
        self.assert_error_names(self.load(self.plain), path)

    def test_version_other_than_1_is_an_error(self):
        path = self.user_config({"version": 2})
        self.assert_error_names(self.load(self.plain), path)

    def test_gemini_section_that_is_not_an_object_is_an_error_and_the_default_stays(self):
        path = self.user_config({"version": 1, "gemini": 5})
        cfg = self.load(self.plain)
        self.assert_error_names(cfg, path)
        self.assertEqual(cfg["gemini"], DEFAULT_GEMINI)

    def unreadable_user_config(self) -> Path:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root reads a file with mode 000")
        path = self.user_config({"version": 1})
        path.chmod(0)  # rmtree in cleanup still removes it: the dir stays writable
        return path

    def broken_symlink_user_config(self) -> Path:
        path = self.home / ".claude" / "3amigos" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(self.tmp / "no-such-target.json")
        return path

    def deep_user_config(self) -> Path:
        return self.user_config("[" * 100000 + "]" * 100000)

    def test_unreadable_config_is_an_error(self):
        path = self.unreadable_user_config()
        self.assert_error_names(self.load(self.plain), path)

    def test_broken_symlink_config_is_an_error_not_a_missing_file(self):
        path = self.broken_symlink_user_config()
        self.assert_error_names(self.load(self.plain), path)

    def test_boolean_version_is_an_error(self):
        path = self.user_config({"version": True})
        self.assert_error_names(self.load(self.plain), path)

    def test_very_deep_json_is_an_error_naming_the_file(self):
        path = self.deep_user_config()
        cfg = self.load(self.plain)
        self.assert_error_names(cfg, path)
        self.assertEqual(cfg["panel"], DEFAULT_PANEL)

    def assert_cli_exit_2_naming(self, path: Path):
        for args in (self.run_args(), ["--show-config"]):
            with self.subTest(args=args[0]):
                p = self.run_panel(*args, cwd=self.plain)
                self.assertEqual(p.returncode, 2, (p.stdout, p.stderr))
                self.assertIn(str(path), p.stderr)
        self.assert_no_voter_ran()

    def test_unreadable_config_exits_2(self):
        self.assert_cli_exit_2_naming(self.unreadable_user_config())

    def test_symlink_deep_and_bool_version_exit_2(self):
        makers = (self.broken_symlink_user_config, self.deep_user_config,
                  lambda: self.user_config({"version": True}))
        for make in makers:
            path = self.home / ".claude" / "3amigos" / "config.json"
            if path.is_symlink() or path.exists():
                path.unlink()
            path = make()
            for args in (self.run_args(), ["--show-config"]):
                with self.subTest(config=make, args=args[0]):
                    p = self.run_panel(*args, cwd=self.plain)
                    self.assertEqual(p.returncode, 2, (p.stdout, p.stderr))
                    self.assertIn(str(path), p.stderr)
        self.assert_no_voter_ran()

    def test_known_top_level_keys_give_no_error(self):
        self.user_config({"version": 1, "panel": DEFAULT_PANEL, "gemini": {"effort": "high"}, "updated": "2026-11-18"})
        self.assertEqual(self.load(self.plain)["errors"], [])

    def test_strict_config_errors_exit_2_for_a_run_and_show_config(self):
        cases = ({"version": 1, "voters": ["codex"]}, {"version": 1, "gemini": {"modle": "x"}},
                 {"version": 2}, {"version": 1, "gemini": 5})
        for body in cases:
            path = self.user_config(body)
            for args in (self.run_args(), ["--show-config"]):
                with self.subTest(config=body, args=args[0]):
                    p = self.run_panel(*args, cwd=self.plain)
                    self.assertEqual(p.returncode, 2, (p.stdout, p.stderr))
                    self.assertIn(str(path), p.stderr)
        self.assert_no_voter_ran()

    def test_panel_run_exits_2_and_names_the_broken_project_config(self):
        repo = self.make_repo()
        path = self.project_config(repo, "{not json")
        p = self.run_panel(*self.run_args(), cwd=repo)
        self.assertEqual(p.returncode, 2, (p.stdout, p.stderr))
        self.assertIn(str(path), p.stderr)
        self.assert_no_voter_ran()

    def test_panel_run_exits_2_and_names_the_broken_user_config(self):
        path = self.user_config({"version": 1, "panel": ["codex", "grok", "fable"]})
        p = self.run_panel(*self.run_args(), cwd=self.plain)
        self.assertEqual(p.returncode, 2, (p.stdout, p.stderr))
        self.assertIn(str(path), p.stderr)
        self.assert_no_voter_ran()

    def test_show_config_exits_2_and_names_the_broken_config(self):
        repo = self.make_repo()
        path = self.project_config(repo, {"version": 1, "gemini": {"effort": "extreme"}})
        p = self.run_panel("--show-config", cwd=repo)
        self.assertEqual(p.returncode, 2, (p.stdout, p.stderr))
        self.assertIn(str(path), p.stderr)
        self.assert_no_voter_ran()

    def test_check_reads_no_config_and_still_prints_ok(self):
        repo = self.make_repo()
        self.user_config("{not json")
        self.project_config(repo, "{not json")
        answer = write_json(self.tmp / "opus.json", {"ideas": ["a", "b", "c"]})
        p = self.run_panel("--check", str(answer), "--require", "ideas=3", cwd=repo)
        self.assertEqual(p.returncode, 0, p.stderr)
        line = json.loads(p.stdout)
        self.assertEqual((line["voter"], line["status"]), ("opus", "ok"))
        self.assert_no_voter_ran()


class ValidatePanelTest(unittest.TestCase):
    """validate_panel(): exactly three different names from codex, gemini, opus, fable (GV1)."""

    def setUp(self):
        self.validate = amigos_config().validate_panel

    def test_three_different_names_from_the_pool_pass(self):
        for names in (["codex", "gemini", "fable"], ["opus", "codex", "gemini"], ["fable", "opus", "gemini"]):
            with self.subTest(names=names):
                self.assertEqual(self.validate(names), "")

    def test_two_names_fail_with_a_reason(self):
        self.assertTrue(self.validate(["codex", "gemini"]))

    def test_four_names_fail_with_a_reason(self):
        self.assertTrue(self.validate(["codex", "gemini", "opus", "fable"]))

    def test_a_repeated_name_fails_with_a_reason(self):
        self.assertTrue(self.validate(["codex", "codex", "fable"]))

    def test_an_unknown_name_fails_with_a_reason(self):
        self.assertTrue(self.validate(["codex", "grok", "fable"]))


class PanelCliTest(ConfigTestBase):
    """panel.py --show-config, --panel and --voters (GV1, GV2, GV4)."""

    def test_show_config_prints_one_json_line_needs_no_task_runs_no_voter(self):
        cfg = self.show_config(cwd=self.plain)
        self.assertEqual(cfg["panel"], DEFAULT_PANEL)
        self.assertEqual(cfg["external"], ["codex", "gemini"])
        self.assertEqual(cfg["gemini"], DEFAULT_GEMINI)
        self.assertEqual(set(cfg["sources"].values()), {"default"})
        self.assert_no_voter_ran()

    def test_show_config_files_names_the_project_config_or_none(self):
        repo = self.make_repo()
        worktree = self.tmp / "linked"
        git(repo, "worktree", "add", "-q", "-b", "side", str(worktree))
        expected = str(repo / ".claude" / "3amigos.local.json")
        self.assertEqual(self.show_config(cwd=repo)["files"]["project"], expected)
        self.assertEqual(self.show_config(cwd=worktree)["files"]["project"], expected)
        self.assertEqual(self.show_config(cwd=self.plain)["files"]["project"], "none (no main checkout)")

    def test_show_config_holds_no_key_value(self):
        dotenv = self.tmp / "example.env"
        dotenv.write_text(f"EXAMPLE_GEMINI_KEY={FAKE_DOTENV_KEY}\nOTHER_SECRET={FAKE_OTHER}\n")
        self.user_config({"version": 1, "gemini": {"fallback": "key", "key_env": "EXAMPLE_GEMINI_KEY",
                                                    "key_dotenv": str(dotenv)}})
        env = {"EXAMPLE_GEMINI_KEY": FAKE_ENV_KEY, "GEMINI_API_KEY": FAKE_ENV_KEY}
        p = self.run_panel("--show-config", cwd=self.plain, extra_env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["gemini"]["key_env"], "EXAMPLE_GEMINI_KEY")
        for secret in (FAKE_ENV_KEY, FAKE_DOTENV_KEY, FAKE_OTHER):
            self.assertNotIn(secret, p.stdout)
            self.assertNotIn(secret, p.stderr)
        self.assert_no_voter_ran()

    def test_show_config_in_a_linked_worktree_reads_the_main_checkout(self):
        repo = self.make_repo()
        worktree = self.tmp / "linked"
        git(repo, "worktree", "add", "-q", "-b", "side", str(worktree))
        self.project_config(repo, {"version": 1, "panel": ["opus", "codex", "gemini"]})
        cfg = self.show_config(cwd=worktree)
        self.assertEqual(cfg["project_root"], str(repo))
        self.assertEqual((cfg["panel"], cfg["sources"]["panel"]), (["opus", "codex", "gemini"], "project"))

    def test_run_panel_flag_wins_over_project_and_user(self):
        repo = self.make_repo()
        self.user_config({"version": 1, "panel": ["codex", "opus", "fable"]})
        self.project_config(repo, {"version": 1, "panel": ["gemini", "opus", "fable"]})
        cfg = self.show_config("--panel", "fable,codex,opus", cwd=repo)
        self.assertEqual((cfg["panel"], cfg["sources"]["panel"]), (["fable", "codex", "opus"], "run"))
        self.assertEqual(cfg["external"], ["codex"])

    def test_bad_panel_flag_exits_2(self):
        for bad in ("codex,gemini", "codex,gemini,opus,fable", "codex,codex,fable", "codex,grok,fable"):
            with self.subTest(panel=bad):
                p = self.run_panel(*self.run_args(), "--panel", bad, cwd=self.plain)
                self.assertEqual(p.returncode, 2, (p.stdout, p.stderr))
        self.assert_no_voter_ran()

    def started(self):
        return {name for name in ("codex", "agy") if self.calls(name)}

    def test_no_voters_flag_runs_the_external_voters_of_the_run_panel(self):
        p = self.run_panel(*self.run_args(), "--deadline", "30", "--panel", "codex,opus,fable", cwd=self.plain)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.started(), {"codex"})

    def test_no_voters_flag_runs_the_external_voters_of_the_config_panel(self):
        repo = self.make_repo()
        self.project_config(repo, {"version": 1, "panel": ["gemini", "opus", "fable"]})
        p = self.run_panel(*self.run_args(), "--deadline", "30", cwd=repo)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.started(), {"agy"})

    def test_no_voters_flag_runs_both_external_voters_of_the_default_panel(self):
        p = self.run_panel(*self.run_args(), "--deadline", "30", cwd=self.plain)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.started(), {"codex", "agy"})

    def test_valid_voters_subset_runs_only_that_voter(self):
        p = self.run_panel(*self.run_args(), "--deadline", "30", "--voters", "codex", cwd=self.plain)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.started(), {"codex"})

    def test_voters_outside_the_run_panel_external_voters_exits_2(self):
        p = self.run_panel(*self.run_args(), "--panel", "codex,opus,fable", "--voters", "gemini", cwd=self.plain)
        self.assertEqual(p.returncode, 2, (p.stdout, p.stderr))
        self.assert_no_voter_ran()

    def test_voters_outside_the_config_panel_external_voters_exits_2(self):
        repo = self.make_repo()
        self.project_config(repo, {"version": 1, "panel": ["gemini", "opus", "fable"]})
        p = self.run_panel(*self.run_args(), "--voters", "codex", cwd=repo)
        self.assertEqual(p.returncode, 2, (p.stdout, p.stderr))
        self.assert_no_voter_ran()


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + sys.argv[1:])
