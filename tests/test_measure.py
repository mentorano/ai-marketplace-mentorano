#!/usr/bin/env python3
"""Tests for plugins/clean-code/skills/clean-code/measure.py.

Run:  python3 tests/test_measure.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "plugins" / "clean-code" / "skills" / "clean-code" / "measure.py"
FIXTURES = ROOT / "tests" / "fixtures" / "clean-code"


def load_measure():
    spec = importlib.util.spec_from_file_location("measure", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["measure"] = module
    spec.loader.exec_module(module)
    return module


measure = load_measure()


def by_name(functions):
    return {f.name: f for f in functions}


class PythonMeasurementTest(unittest.TestCase):
    def setUp(self):
        self.functions = by_name(measure.measure_python_file(FIXTURES / "sample.py"))

    def test_finds_every_function_including_methods_and_nested(self):
        self.assertEqual(
            set(self.functions),
            {
                "clean",
                "complex_branches",
                "too_many_params",
                "deeply_nested",
                "long_function",
                "Widget.method",
                "Widget.outer",
                "Widget.outer.inner",
            },
        )

    def test_clean_function_is_baseline(self):
        f = self.functions["clean"]
        self.assertEqual((f.line, f.lines, f.cc, f.params, f.depth), (4, 2, 1, 2, 0))

    def test_complexity_counts_every_branch_kind_once(self):
        self.assertEqual(self.functions["complex_branches"].cc, 12)

    def test_complexity_of_nested_function_is_excluded_from_parent(self):
        self.assertEqual(self.functions["Widget.outer"].cc, 1)
        self.assertEqual(self.functions["Widget.outer.inner"].cc, 2)

    def test_parameters_exclude_self(self):
        self.assertEqual(self.functions["too_many_params"].params, 5)
        self.assertEqual(self.functions["Widget.method"].params, 2)
        self.assertEqual(self.functions["Widget.outer"].params, 0)

    def test_depth_counts_control_blocks_not_elif(self):
        self.assertEqual(self.functions["deeply_nested"].depth, 4)
        self.assertEqual(self.functions["complex_branches"].depth, 2)

    def test_lines_span_signature_to_last_statement(self):
        self.assertEqual(self.functions["long_function"].lines, 41)
        self.assertEqual(self.functions["Widget.outer"].lines, 7)

    def test_file_shape_counts_lines_and_suppressions(self):
        shape = measure.measure_file_shape(FIXTURES / "sample.py")
        self.assertEqual(shape.language, "py")
        self.assertEqual(shape.lines, 98)
        self.assertEqual(shape.suppressions, 2)

    def test_suppressions_ignore_strings_and_count_comments(self):
        source = '''MESSAGE = "write # noqa on the line"\nvalue = 1  # noqa: E501\n'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "suppressed.py"
            path.write_text(source)
            shape = measure.measure_file_shape(path)
        self.assertEqual(shape.suppressions, 1)

    def test_language_of(self):
        self.assertEqual(measure.language_of(Path("a.py")), "py")
        self.assertEqual(measure.language_of(Path("a.ts")), "ts")
        self.assertEqual(measure.language_of(Path("a.tsx")), "ts")
        self.assertIsNone(measure.language_of(Path("a.md")))


DEFAULT_TS_PACKAGE = Path(__file__).resolve().parent.parent / "node_modules" / "typescript"
TS_PACKAGE = Path(os.environ.get("CLEAN_CODE_TS_PACKAGE", str(DEFAULT_TS_PACKAGE)))
TS_READY = TS_PACKAGE.is_dir() and bool(shutil.which("node"))

if not TS_READY:
    print(
        "test_measure: TypeScript tests skipped \u2014 set CLEAN_CODE_TS_PACKAGE to a "
        f"node_modules/typescript directory (default: {DEFAULT_TS_PACKAGE})",
        file=sys.stderr,
    )


def make_ts_project(tmp: Path) -> Path:
    """A scratch project: copies the TS fixtures next to a node_modules/typescript symlink."""
    project = tmp / "project"
    (project / "node_modules").mkdir(parents=True)
    os.symlink(TS_PACKAGE, project / "node_modules" / "typescript")
    for name in ("sample.ts", "Sample.tsx"):
        shutil.copy(FIXTURES / name, project / name)
    return project


@unittest.skipUnless(
    TS_READY,
    f"needs node on PATH and {TS_PACKAGE} (set CLEAN_CODE_TS_PACKAGE, or run `npm install --no-save typescript@5` in the repo root)",
)
class TypeScriptMeasurementTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = make_ts_project(Path(self._tmp.name))
        functions = measure.measure_ts_files([self.project / "sample.ts", self.project / "Sample.tsx"])
        self.ts = by_name([f for f in functions if f.file.endswith("sample.ts")])
        self.tsx = by_name([f for f in functions if f.file.endswith("Sample.tsx")])

    def tearDown(self):
        self._tmp.cleanup()

    def test_finds_declarations_methods_and_assigned_arrows_only(self):
        self.assertEqual(
            set(self.ts),
            {"clean", "complexBranches", "tooManyParams", "deeplyNested", "longFunction", "Widget.method", "Widget.outer", "inner"},
        )
        self.assertEqual(set(self.tsx), {"ItemList", "Page", "CardInner", "Box", "Loader.load"})

    def test_clean_function_is_baseline(self):
        f = self.ts["clean"]
        self.assertEqual((f.line, f.lines, f.cc, f.params, f.depth), (3, 3, 1, 2, 0))

    def test_complexity_counts_every_branch_kind_once(self):
        self.assertEqual(self.ts["complexBranches"].cc, 12)

    def test_anonymous_callbacks_belong_to_the_parent(self):
        self.assertEqual(self.ts["Widget.outer"].cc, 2)
        self.assertEqual(self.ts["inner"].cc, 2)
        self.assertEqual(self.tsx["ItemList"].cc, 1)

    def test_parameters(self):
        self.assertEqual(self.ts["tooManyParams"].params, 5)
        self.assertEqual(self.tsx["ItemList"].params, 1)
        self.assertEqual(self.tsx["Box"].params, 2)
        self.assertEqual(self.tsx["CardInner"].params, 1)

    def test_depth_counts_control_blocks_not_else_if(self):
        self.assertEqual(self.ts["deeplyNested"].depth, 4)
        self.assertEqual(self.ts["complexBranches"].depth, 2)

    def test_lines(self):
        self.assertEqual(self.ts["longFunction"].lines, 42)
        self.assertEqual(self.tsx["ItemList"].lines, 10)
        self.assertEqual(self.tsx["Page"].line, 18)

    def test_file_shape_counts_ts_suppressions(self):
        shape = measure.measure_file_shape(self.project / "sample.ts")
        self.assertEqual((shape.language, shape.lines, shape.suppressions), ("ts", 115, 2))

    def test_unparsable_typescript_is_a_broken_run(self):
        broken = self.project / "broken.ts"
        broken.write_text("export function broken( {\n")
        with self.assertRaises(measure.MeasureError) as ctx:
            measure.measure_ts_files([broken])
        self.assertIn("broken.ts", str(ctx.exception))

    def test_find_typescript_package_walks_up(self):
        found = measure.find_typescript_package(self.project / "sample.ts")
        self.assertEqual(found, self.project.resolve() / "node_modules" / "typescript")


@unittest.skipUnless(TS_READY, f"needs node on PATH and {TS_PACKAGE} (set CLEAN_CODE_TS_PACKAGE)")
class TypeScriptTestFileTest(unittest.TestCase):
    """describe is a container; each test and hook is measured on its own, named after its call."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = make_ts_project(Path(self._tmp.name))
        shutil.copy(FIXTURES / "sample.test.ts", self.project / "sample.test.ts")
        self.by = by_name(measure.measure_ts_files([self.project / "sample.test.ts"]))

    def tearDown(self):
        self._tmp.cleanup()

    def test_tests_and_hooks_are_measured_and_describe_blocks_are_not(self):
        self.assertEqual(
            set(self.by),
            {
                'vi.mock("./api")',
                "load",
                "doubled",
                "beforeEach()",
                'it("adds numbers")',
                'it.each("row %s is positive")',
                'it("stands alone")',
            },
        )

    def test_a_test_owns_its_own_branches(self):
        f = self.by['it("adds numbers")']
        self.assertEqual((f.line, f.lines, f.cc, f.depth), (16, 5, 2, 1))

    def test_a_table_test_counts_its_row_parameter(self):
        self.assertEqual(self.by['it.each("row %s is positive")'].params, 1)

    def test_a_playwright_describe_is_a_container_too(self):
        (self.project / "e2e.spec.ts").write_text(
            'test.describe("login", () => {\n  test("works", async () => {\n    await go();\n  });\n});\n'
        )
        names = [row.name for row in measure.measure_ts_files([self.project / "e2e.spec.ts"])]
        self.assertEqual(names, ['test("works")'])

    def test_a_long_title_is_cut_so_the_row_stays_readable(self):
        (self.project / "long.test.ts").write_text(f'it("{"x" * 100}", () => {{}});\n')
        [row] = measure.measure_ts_files([self.project / "long.test.ts"])
        self.assertEqual(row.name, f'it("{"x" * 60}…")')


class TypeScriptWithoutToolingTest(unittest.TestCase):
    def test_missing_typescript_package_names_the_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            lonely = Path(tmp) / "lonely.ts"
            lonely.write_text("export const x = 1;\n")
            with self.assertRaises(measure.MeasureError) as ctx:
                measure.measure_ts_files([lonely])
        self.assertIn("typescript package not found", str(ctx.exception))
        self.assertIn("npm ci", str(ctx.exception))

    def test_a_typescript_package_without_the_compiler_api_names_the_version(self):
        # TypeScript 7 is the native compiler: its package has no `main`, so
        # measure-ts.mjs used to fail with a bare "Cannot find module".
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "node_modules" / "typescript"
            package.mkdir(parents=True)
            (package / "package.json").write_text('{"name": "typescript", "version": "7.0.2"}')
            source = Path(tmp) / "a.ts"
            source.write_text("export const x = 1;\n")
            with self.assertRaises(measure.MeasureError) as ctx:
                measure.measure_ts_files([source])
        self.assertIn("7.0.2", str(ctx.exception))
        self.assertIn("typescript@5", str(ctx.exception))


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class CollectionTest(unittest.TestCase):
    def test_collect_walks_roots_and_skips_tooling_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("x = 1\n")
            (root / "sub").mkdir()
            (root / "sub" / "b.tsx").write_text("export const b = 1;\n")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "c.ts").write_text("export const c = 1;\n")
            (root / "README.md").write_text("# no\n")
            found = sorted(p.name for p in measure.collect_files([root], changed=False, base="main"))
        self.assertEqual(found, ["a.py", "b.tsx"])

    def test_changed_returns_modified_and_untracked_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git("init", "-q", "-b", "main", cwd=repo)
            git("config", "user.email", "t@example.com", cwd=repo)
            git("config", "user.name", "t", cwd=repo)
            (repo / "a.py").write_text("a = 1\n")
            (repo / "c.py").write_text("c = 1\n")
            git("add", ".", cwd=repo)
            git("commit", "-q", "-m", "base", cwd=repo)
            git("checkout", "-q", "-b", "work", cwd=repo)
            (repo / "a.py").write_text("a = 2\n")
            (repo / "b.py").write_text("b = 1\n")
            found = sorted(p.name for p in measure.collect_files([repo], changed=True, base="main"))
        self.assertEqual(found, ["a.py", "b.py"])

    def test_changed_with_unknown_base_names_the_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git("init", "-q", "-b", "main", cwd=repo)
            git("config", "user.email", "t@example.com", cwd=repo)
            git("config", "user.name", "t", cwd=repo)
            (repo / "a.py").write_text("a = 1\n")
            git("add", ".", cwd=repo)
            git("commit", "-q", "-m", "base", cwd=repo)
            with self.assertRaises(measure.MeasureError) as ctx:
                measure.collect_files([repo], changed=True, base="origin/nowhere")
        self.assertIn("--base", str(ctx.exception))


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.report = measure.build_report([FIXTURES / "sample.py"], measure.Thresholds())

    def test_exceeded_lists_each_crossed_threshold(self):
        t = measure.Thresholds()
        by = by_name(self.report.functions)
        self.assertEqual(measure.exceeded(by["clean"], t), [])
        self.assertEqual(measure.exceeded(by["long_function"], t), ["lines"])
        self.assertEqual(measure.exceeded(by["complex_branches"], t), ["cc"])
        self.assertEqual(measure.exceeded(by["too_many_params"], t), ["params"])
        self.assertEqual(measure.exceeded(by["deeply_nested"], t), ["depth"])

    def test_summary_counts(self):
        self.assertEqual(
            self.report.summary,
            {
                "functions": 8,
                "over_lines": 1,
                "over_cc": 1,
                "over_params": 1,
                "over_depth": 1,
                "files": 1,
                "over_file_lines": 0,
                "suppressions": 2,
            },
        )

    def test_text_shows_only_offenders_by_default_worst_first(self):
        text = measure.render_text(self.report, show_all=False)
        self.assertIn("long_function", text)
        self.assertIn("deeply_nested", text)
        self.assertNotIn("sample.py:4 clean", text)
        self.assertLess(text.index("long_function"), text.index("deeply_nested"))
        self.assertIn("SUMMARY functions=8", text)
        self.assertIn("FILES over 500 lines or with suppressions:", text)

    def test_text_with_all_shows_clean_functions_too(self):
        text = measure.render_text(self.report, show_all=True)
        self.assertIn("sample.py:4 clean", text)
        self.assertTrue(text.startswith("FUNCTIONS (4 of 8 over threshold"), text)
        self.assertIn("FILES (1 of 1 over 500 lines or with suppressions)", text)

    def test_json_round_trips_with_thresholds(self):
        data = json.loads(measure.render_json(self.report))
        self.assertEqual(data["thresholds"], {"lines": 20, "cc": 10, "params": 3, "file_lines": 500, "depth": 2})
        self.assertEqual(len(data["functions"]), 8)
        self.assertEqual(data["files"][0]["suppressions"], 2)
        self.assertEqual(data["summary"]["over_cc"], 1)

    def test_custom_threshold_changes_summary(self):
        report = measure.build_report([FIXTURES / "sample.py"], measure.Thresholds(lines=3))
        self.assertEqual(report.summary["over_lines"], 5)


class OutOfTreeDisplayTest(unittest.TestCase):
    def test_file_outside_the_cwd_is_printed_as_given_not_relativized(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "sample.py"
            shutil.copy(FIXTURES / "sample.py", fixture)
            report = measure.build_report([fixture], measure.Thresholds())
        rows = [fs.file for fs in report.files] + [fm.file for fm in report.functions]
        self.assertTrue(rows)
        for file in rows:
            self.assertFalse(file.startswith(".."), file)
            self.assertTrue(file.endswith("sample.py"), file)


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)

    def test_measures_a_path_and_exits_zero_even_when_red(self):
        proc = self.run_cli(str(FIXTURES / "sample.py"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("SUMMARY functions=8", proc.stdout)

    def test_json_flag(self):
        proc = self.run_cli(str(FIXTURES / "sample.py"), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["summary"]["functions"], 8)

    def test_broken_run_exits_two_with_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            lonely = Path(tmp) / "lonely.ts"
            lonely.write_text("export const x = 1;\n")
            proc = self.run_cli(str(lonely))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("typescript package not found", proc.stderr)

    def test_unreadable_file_exits_two_with_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "binary.py"
            binary.write_bytes(b"\xff\xfe\x00")
            proc = self.run_cli(str(binary))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot read", proc.stderr)

    def test_no_files_is_reported_not_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli(tmp)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("no Python or TypeScript files", proc.stdout)

    def test_zero_threshold_is_a_usage_error(self):
        proc = self.run_cli(str(FIXTURES / "sample.py"), "--max-cc", "0")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("positive integer", proc.stderr)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + sys.argv[1:])
