#!/usr/bin/env python3
"""Tests for the typescript package measure.py parses with when the project has none.

Every run gets an empty cache directory and a stub npm (or none), so no test
downloads anything and none depends on what the machine has cached.

Run:  python3 tests/test_typescript_cache.py
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins" / "clean-code" / "skills" / "clean-code" / "measure.py"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ts_package import CACHE_ENV, SKIP_REASON, TS_PACKAGE, TS_READY, cache_env  # noqa: E402  (the tests directory goes on sys.path first)


def load_measure():
    spec = importlib.util.spec_from_file_location("measure", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["measure"] = module
    spec.loader.exec_module(module)
    return module


measure = load_measure()
import typescript  # noqa: E402  (measure.py put the skill directory on sys.path)

VERSION = typescript.TYPESCRIPT_VERSION
HOME = f"typescript-{VERSION}"

if not TS_READY:
    print(f"test_typescript_cache: install tests skipped — {SKIP_REASON}", file=sys.stderr)


def run_cli(*args, env):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env)


def write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def npm_calls(tmp: Path) -> list[str]:
    log = tmp / "npm.log"
    return log.read_text().splitlines() if log.exists() else []


class CacheRootTest(unittest.TestCase):
    def test_the_variable_names_the_cache_directory(self):
        with mock.patch.dict(os.environ, {CACHE_ENV: "/somewhere/cc"}):
            self.assertEqual(typescript.cache_root(), Path("/somewhere/cc"))

    def test_the_cache_directory_is_always_absolute(self):
        with mock.patch.dict(os.environ, {CACHE_ENV: "cc"}):
            self.assertEqual(typescript.cache_root(), typescript.START_DIR / "cc")

    def test_the_default_is_the_users_cache_directory(self):
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": "/xdg"}):
            os.environ.pop(CACHE_ENV, None)
            self.assertEqual(typescript.cache_root(), Path("/xdg/clean-code"))
            os.environ.pop("XDG_CACHE_HOME")
            self.assertEqual(typescript.cache_root(), Path.home() / ".cache" / "clean-code")


@unittest.skipUnless(TS_READY, SKIP_REASON)
class FirstUseInstallTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.env = cache_env(self.tmp, "npm-links-typescript")
        self.site = self.tmp / "site"
        self.script = write(self.site / "app.js", "function f(a) {\n  return a;\n}\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_repository_without_typescript_installs_once_into_the_cache(self):
        first = run_cli(str(self.script), env=self.env)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("SUMMARY functions=1 ", first.stdout)
        self.assertIn(f"installing typescript@{VERSION} once into {self.tmp / 'cache' / HOME}", first.stderr)
        self.assertIn("typescript package not found above", first.stderr)
        [call] = npm_calls(self.tmp)
        self.assertIn(f"--prefix {self.tmp / 'cache' / HOME}.", call)
        self.assertIn("--ignore-scripts", call)
        self.assertTrue(call.endswith(f"typescript@{VERSION}"), call)

        second = run_cli(str(self.script), env=self.env)
        self.assertEqual((second.returncode, second.stderr), (0, ""))
        self.assertEqual(second.stdout, first.stdout)
        self.assertEqual(len(npm_calls(self.tmp)), 1)

    def test_nothing_is_written_into_the_measured_repository_and_no_staging_is_left(self):
        run_cli(str(self.site), env=self.env)
        self.assertEqual([p.name for p in self.site.iterdir()], ["app.js"])
        self.assertEqual([p.name for p in (self.tmp / "cache").iterdir()], [HOME])

    def test_a_relative_cache_directory_is_taken_from_where_the_command_started(self):
        # npm runs in the staging directory and node next to measure-ts.mjs: each would read a relative path its own way.
        self.env[CACHE_ENV] = "relative-cache"
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "site/app.js"], capture_output=True, text=True, env=self.env, cwd=self.tmp
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("SUMMARY functions=1 ", proc.stdout)
        self.assertTrue((self.tmp / "relative-cache" / HOME / "node_modules" / "typescript").exists())
        self.assertIn(f"--prefix {self.tmp / 'relative-cache' / HOME}.", npm_calls(self.tmp)[0])

    def test_typescript_and_html_files_use_the_cache_too(self):
        write(self.site / "lonely.ts", "export const g = (a: number): number => a;\n")
        write(self.site / "page.html", "<script>\nfunction h() {}\n</script>\n")
        proc = run_cli(str(self.site), "--all", env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("SUMMARY functions=3 ", proc.stdout)
        self.assertRegex(proc.stdout, r"page\.html:2 h\n")
        self.assertEqual(len(npm_calls(self.tmp)), 1)

    def test_a_parse_error_under_the_cached_package_says_which_parser_read_the_file(self):
        # The project's own compiler may read syntax the cached one does not.
        write(self.site / "broken.ts", "export function broken( {\n")
        proc = run_cli(str(self.site / "broken.ts"), env=self.env)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("broken.ts:", proc.stderr)
        self.assertIn(f"Parsed with the cached typescript {VERSION}", proc.stderr)
        self.assertIn("npm ci", proc.stderr)

    def test_a_parse_error_under_the_projects_own_package_has_no_cache_hint(self):
        (self.site / "node_modules").mkdir()
        os.symlink(TS_PACKAGE, self.site / "node_modules" / "typescript")
        write(self.site / "broken.ts", "export function broken( {\n")
        proc = run_cli(str(self.site / "broken.ts"), env=self.env)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("cached typescript", proc.stderr)

    def test_the_projects_own_package_is_used_when_it_has_one(self):
        (self.site / "node_modules").mkdir()
        os.symlink(TS_PACKAGE, self.site / "node_modules" / "typescript")
        proc = run_cli(str(self.script), env=self.env)
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        self.assertEqual(npm_calls(self.tmp), [])
        self.assertFalse((self.tmp / "cache").exists())

    def test_a_typescript_7_project_is_parsed_with_the_cached_package(self):
        # TypeScript 7 is the native compiler: its package has no `main`, so nothing can be required from it.
        write(self.site / "node_modules" / "typescript" / "package.json", '{"name": "typescript", "version": "7.0.2"}')
        proc = run_cli(str(self.script), env=self.env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("SUMMARY functions=1 ", proc.stdout)
        self.assertIn("typescript 7.0.2", proc.stderr)
        self.assertIn("no JavaScript compiler API", proc.stderr)


class InstallFailureTest(unittest.TestCase):
    """The message of a failed first use says what was missing and what to run by hand."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.lonely = write(self.tmp / "site" / "lonely.ts", "export const x = 1;\n")
        self.home = self.tmp / "cache" / HOME

    def tearDown(self):
        self._tmp.cleanup()

    def test_without_npm_the_message_names_the_install_to_run_by_hand(self):
        proc = run_cli(str(self.lonely), env=cache_env(self.tmp))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("typescript package not found above", proc.stderr)
        self.assertIn("npm is not on PATH", proc.stderr)
        self.assertIn(f"npm install --prefix {self.home} --no-save typescript@{VERSION}", proc.stderr)
        self.assertIn("npm ci", proc.stderr)
        self.assertIn(CACHE_ENV, proc.stderr)

    def test_a_failed_install_shows_npms_error_and_leaves_no_half_install(self):
        proc = run_cli(str(self.lonely), env=cache_env(self.tmp, "npm-fails"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("ENOTFOUND", proc.stderr)
        self.assertIn(f"npm install --prefix {self.home}", proc.stderr)
        self.assertEqual(list((self.tmp / "cache").iterdir()), [])

    def test_a_cache_directory_that_cannot_be_written_is_a_broken_run_not_a_traceback(self):
        env = cache_env(self.tmp, "npm-links-typescript")
        (self.tmp / "file").write_text("not a directory\n")
        env[CACHE_ENV] = str(self.tmp / "file" / "cache")
        proc = run_cli(str(self.lonely), env=env)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("cannot write the cache directory", proc.stderr)
        self.assertIn("npm install --prefix", proc.stderr)

    def test_an_install_that_hangs_is_given_up(self):
        hung = subprocess.TimeoutExpired(cmd="npm", timeout=typescript.INSTALL_TIMEOUT_SECONDS)
        with mock.patch.object(typescript.subprocess, "run", side_effect=hung):
            failure = typescript._npm_install("npm", self.tmp)
        self.assertEqual(failure, f"npm did not finish in {typescript.INSTALL_TIMEOUT_SECONDS} seconds")

    def test_a_typescript_package_without_the_compiler_api_names_the_version(self):
        package = self.tmp / "site" / "node_modules" / "typescript"
        write(package / "package.json", '{"name": "typescript", "version": "7.0.2"}')
        proc = run_cli(str(self.lonely), env=cache_env(self.tmp))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("typescript 7.0.2", proc.stderr)
        self.assertIn("typescript@5", proc.stderr)


class PublishTest(unittest.TestCase):
    """Two runs may install at the same time; the second one to finish keeps the first one's package."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / HOME
        self.staging = self.tmp / f"{HOME}.staging"
        write(self.staging / "node_modules" / "typescript" / "package.json", '{"version": "mine"}')

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_finished_install_moves_into_place(self):
        typescript._publish(self.staging, self.home)
        self.assertIn("mine", (self.home / "node_modules" / "typescript" / "package.json").read_text())

    def test_a_package_another_run_installed_first_is_kept(self):
        theirs = write(self.home / "node_modules" / "typescript" / "package.json", '{"version": "theirs"}')
        typescript._publish(self.staging, self.home)
        self.assertIn("theirs", theirs.read_text())

    def test_a_directory_in_the_way_without_a_package_is_a_broken_run(self):
        write(self.home / "stray.txt", "x")
        with self.assertRaises(measure.MeasureError) as ctx:
            typescript._publish(self.staging, self.home)
        self.assertIn(str(self.home), str(ctx.exception))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + sys.argv[1:])
