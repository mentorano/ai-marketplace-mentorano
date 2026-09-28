#!/usr/bin/env python3
"""Tests for --at and --compare in measure.py and boundaries.py.

Every test builds a scratch git repository, because the two flags read files
from git refs: a working tree alone cannot show what they are for.

Run:  python3 tests/test_revisions.py
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
SKILL = ROOT / "plugins" / "clean-code" / "skills" / "clean-code"
MEASURE = SKILL / "measure.py"
BOUNDARIES = SKILL / "boundaries.py"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ts_package import SKIP_REASON, TS_PACKAGE, TS_READY  # noqa: E402


def git(repo: Path, *args: str) -> str:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.t"})
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, env=env, check=True)
    return proc.stdout.strip()


def write(repo: Path, files: dict[str, str]) -> None:
    for relative, body in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)


def commit(repo: Path, files: dict[str, str], message: str) -> None:
    write(repo, files)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def new_repo(tmp: Path, files: dict[str, str]) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, files, "base")
    return repo


def function(name: str, lines: int, params: str = "") -> str:
    """A Python function `lines` lines long, signature included."""
    body = "".join("    x = 1\n" for _ in range(lines - 2))
    return f"def {name}({params}):\n{body}    return 0\n"


def filler(lines: int) -> str:
    return "".join(f"V{i} = {i}\n" for i in range(lines))


def run(script: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script), *args], cwd=cwd, capture_output=True, text=True)


def run_json(script: Path, *args: str, cwd: Path) -> dict:
    proc = run(script, *args, "--json", cwd=cwd)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return json.loads(proc.stdout)


class AtRefTest(unittest.TestCase):
    """--at reads the committed files, so another session's uncommitted work does not leak in."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = new_repo(Path(self._tmp.name), {"pkg/a.py": function("long_one", 25)})

    def tearDown(self):
        self._tmp.cleanup()

    def test_at_head_ignores_uncommitted_edits_and_untracked_files(self):
        write(self.repo, {"pkg/a.py": function("long_one", 3), "pkg/b.py": function("stray", 30)})
        data = run_json(MEASURE, "pkg", "--at", "HEAD", cwd=self.repo)
        rows = {(f["file"], f["name"]): f["lines"] for f in data["functions"]}
        self.assertEqual(rows, {("pkg/a.py", "long_one"): 25})

    def test_at_an_older_ref_measures_that_version(self):
        git(self.repo, "checkout", "-q", "-b", "work")
        commit(self.repo, {"pkg/a.py": function("long_one", 3)}, "shorter")
        data = run_json(MEASURE, "pkg", "--at", "main", cwd=self.repo)
        self.assertEqual([f["lines"] for f in data["functions"]], [25])

    def test_changed_at_head_lists_committed_changes_only(self):
        git(self.repo, "checkout", "-q", "-b", "work")
        commit(self.repo, {"pkg/c.py": function("committed", 3)}, "c")
        write(self.repo, {"pkg/a.py": function("long_one", 4), "pkg/d.py": function("untracked", 3)})
        data = run_json(MEASURE, "pkg", "--changed", "--base", "main", "--at", "HEAD", cwd=self.repo)
        self.assertEqual(sorted(f["file"] for f in data["files"]), ["pkg/c.py"])

    def test_a_path_with_no_files_at_the_ref_is_a_broken_run(self):
        proc = run(MEASURE, "nowhere", "--at", "HEAD", cwd=self.repo)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("nowhere: no files at HEAD", proc.stderr)

    def test_a_compare_with_no_files_says_so(self):
        git(self.repo, "checkout", "-q", "-b", "work")
        proc = run(MEASURE, "pkg", "--changed", "--base", "main", "--compare", cwd=self.repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("no Python or TypeScript files to measure", proc.stdout)

    def test_an_unknown_ref_is_a_broken_run_that_names_the_flag(self):
        proc = run(MEASURE, "pkg", "--at", "nowhere", cwd=self.repo)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--at", proc.stderr)

    def test_a_run_from_outside_the_repository_prints_paths_from_its_root(self):
        data = run_json(MEASURE, str(self.repo / "pkg"), "--at", "HEAD", cwd=Path(self._tmp.name))
        self.assertEqual([f["file"] for f in data["files"]], ["pkg/a.py"])


BEFORE = {
    "pkg/a.py": "\n".join(
        [
            function("stays_clean", 2, "a"),
            function("will_cross", 2, "a, b, c"),
            function("grows", 25),
            function("will_fix", 25),
            function("untouched_long", 25),
        ]
    ),
    "pkg/big.py": filler(510),
    "pkg/small.py": filler(495),
}

AFTER = {
    "pkg/a.py": "\n".join(
        [
            function("stays_clean", 2, "a"),
            function("will_cross", 2, "a, b, c, d"),
            function("grows", 27),
            function("will_fix", 3),
            function("untouched_long", 25),
            function("new_long", 25),
            function("new_clean", 3),
        ]
    )
    + "Z = 1  # noqa: E501\n",
    "pkg/big.py": filler(520),
    "pkg/small.py": filler(505),
}


class CompareTest(unittest.TestCase):
    """--compare measures the same files at the merge-base and gives each function a verdict."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.repo = new_repo(Path(cls._tmp.name), BEFORE)
        git(cls.repo, "checkout", "-q", "-b", "work")
        commit(cls.repo, AFTER, "work")
        cls.data = run_json(MEASURE, "pkg", "--changed", "--base", "main", "--compare", cwd=cls.repo)
        cls.text = run(MEASURE, "pkg", "--changed", "--base", "main", "--compare", cwd=cls.repo).stdout

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def verdicts(self):
        return {row["name"]: row["verdict"] for row in self.data["compare"]["functions"]}

    def test_every_function_gets_the_verdict_its_numbers_earn(self):
        self.assertEqual(
            self.verdicts(),
            {
                "will_cross": "crossed",
                "grows": "grew",
                "will_fix": "fixed",
                "untouched_long": "still-over",
                "new_long": "new-over",
                "new_clean": "new",
            },
        )

    def test_a_crossed_row_names_the_new_threshold(self):
        row = next(r for r in self.data["compare"]["functions"] if r["name"] == "will_cross")
        self.assertEqual(row["flags"], ["params"])
        self.assertEqual((row["before"]["params"], row["after"]["params"]), (3, 4))

    def test_files_get_verdicts_for_the_500_line_cap_and_suppressions(self):
        rows = {(r["file"], r["verdict"]) for r in self.data["compare"]["files"]}
        self.assertEqual(
            rows,
            {("pkg/big.py", "grew"), ("pkg/small.py", "crossed"), ("pkg/a.py", "suppressions-up")},
        )

    def test_the_verdict_line_counts_every_kind(self):
        self.assertIn(
            "VERDICT new_over=1 crossed=1 grew=1 fixed=1 file_new_over=0 file_crossed=1 file_grew=1 suppressions_up=1",
            self.text,
        )

    def test_the_text_keeps_both_summary_lines(self):
        before = next(line for line in self.text.splitlines() if line.startswith("BEFORE "))
        self.assertIn("functions=5", before)
        self.assertIn("SUMMARY functions=7", self.text)

    def test_quiet_rows_show_only_with_all(self):
        self.assertNotIn("untouched_long", self.text)
        self.assertNotIn("new_clean", self.text)
        full = run(MEASURE, "pkg", "--changed", "--base", "main", "--compare", "--all", cwd=self.repo).stdout
        self.assertIn("untouched_long", full)
        self.assertIn("new_clean", full)

    def test_an_explicit_ref_is_used_as_the_before(self):
        data = run_json(MEASURE, "pkg", "--compare", "HEAD", cwd=self.repo)
        self.assertEqual({r["verdict"] for r in data["compare"]["functions"]}, {"still-over"})
        self.assertEqual(data["compare"]["verdict"]["crossed"], 0)


class CompareAgainstWorkingTreeTest(unittest.TestCase):
    def test_without_at_the_after_side_is_the_working_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = new_repo(Path(tmp), {"pkg/a.py": function("f", 3)})
            write(repo, {"pkg/a.py": function("f", 30)})
            data = run_json(MEASURE, "pkg", "--compare", "HEAD", cwd=repo)
        self.assertEqual([(r["name"], r["verdict"]) for r in data["compare"]["functions"]], [("f", "crossed")])


class ComparePathsTest(unittest.TestCase):
    """The two sides are read from different directories; their rows must still pair up."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = new_repo(Path(self._tmp.name), {"pkg/a.py": function("f", 3), "other/b.py": function("g", 3)})
        write(self.repo, {"other/b.py": function("g", 30)})

    def tearDown(self):
        self._tmp.cleanup()

    def pairs(self, *args: str, cwd: Path) -> list[tuple[str, str]]:
        data = run_json(MEASURE, *args, "--compare", "HEAD", cwd=cwd)
        return [(r["file"], r["verdict"]) for r in data["compare"]["functions"]]

    def test_a_path_above_the_working_directory_pairs_up(self):
        [(file, verdict)] = self.pairs("../other", cwd=self.repo / "pkg")
        self.assertEqual(verdict, "crossed")
        self.assertTrue(file.endswith("other/b.py"), file)
        self.assertNotIn("clean-code-", file)

    def test_a_path_outside_the_repository_is_a_broken_run(self):
        with tempfile.TemporaryDirectory() as elsewhere:
            write(Path(elsewhere), {"x.py": function("h", 3)})
            proc = run(MEASURE, "pkg", elsewhere, "--compare", "HEAD", cwd=self.repo)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("inside the repository", proc.stderr)

    def test_an_absolute_path_pairs_up(self):
        [(file, verdict)] = self.pairs(str(self.repo / "other"), cwd=self.repo)
        self.assertEqual((file, verdict), ("other/b.py", "crossed"))


@unittest.skipUnless(TS_READY, SKIP_REASON)
class CompareTypeScriptTest(unittest.TestCase):
    def test_the_snapshot_finds_the_projects_typescript_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = new_repo(Path(tmp), {".gitignore": "node_modules\n", "web/src/a.ts": "export const f = () => 1;\n"})
            (repo / "web" / "node_modules").mkdir()
            os.symlink(TS_PACKAGE, repo / "web" / "node_modules" / "typescript")
            long_body = "".join(f"  const v{i} = {i};\n" for i in range(25))
            write(repo, {"web/src/a.ts": f"export const f = () => {{\n{long_body}  return 1;\n}};\n"})
            data = run_json(MEASURE, "web/src", "--compare", "HEAD", cwd=repo)
            self.assertTrue((repo / "web" / "node_modules" / "typescript" / "package.json").is_file())
        self.assertEqual([(r["name"], r["verdict"]) for r in data["compare"]["functions"]], [("f", "crossed")])
        self.assertTrue((TS_PACKAGE / "package.json").is_file())


PACKAGE = {
    "app/__init__.py": "",
    "app/orders/__init__.py": "",
    "app/orders/services/__init__.py": "",
    "app/orders/services/orders.py": "X = 1\n",
    "app/orders/api/__init__.py": "",
    "app/orders/api/orders.py": "from app.orders.services import orders\n",
}


class BoundariesRevisionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = new_repo(Path(self._tmp.name), PACKAGE)
        git(self.repo, "checkout", "-q", "-b", "work")
        commit(self.repo, {"app/orders/services/orders.py": "from app.orders.api import orders\n"}, "upward")

    def tearDown(self):
        self._tmp.cleanup()

    def test_at_measures_the_package_as_committed_at_the_ref(self):
        self.assertEqual(run_json(BOUNDARIES, "app", "--at", "main", cwd=self.repo)["summary"]["upward"], 0)
        self.assertEqual(run_json(BOUNDARIES, "app", "--at", "HEAD", cwd=self.repo)["summary"]["upward"], 1)

    def test_at_head_ignores_an_uncommitted_edit(self):
        write(self.repo, {"app/orders/services/orders.py": "X = 1\n"})
        self.assertEqual(run_json(BOUNDARIES, "app", "--at", "HEAD", cwd=self.repo)["summary"]["upward"], 1)

    def test_compare_prints_the_before_line_and_the_counts_that_went_up(self):
        proc = run(BOUNDARIES, "app", "--base", "main", "--compare", cwd=self.repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("BEFORE ", proc.stdout)
        self.assertIn("VERDICT up=upward:0->1", proc.stdout)

    def test_compare_with_nothing_worse_says_so(self):
        proc = run(BOUNDARIES, "app", "--compare", "HEAD", cwd=self.repo)
        self.assertIn("VERDICT up=none", proc.stdout)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + sys.argv[1:])
