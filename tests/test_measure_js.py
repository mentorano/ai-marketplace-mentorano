#!/usr/bin/env python3
"""Tests for JavaScript files and inline HTML scripts in measure.py.

Run:  python3 tests/test_measure_js.py
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
SKILL = ROOT / "plugins" / "clean-code" / "skills" / "clean-code"
SCRIPT = SKILL / "measure.py"
FIXTURES = ROOT / "tests" / "fixtures" / "clean-code"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ts_package import SKIP_REASON, TS_PACKAGE, TS_READY, cache_env  # noqa: E402  (the tests directory goes on sys.path first)


def load_measure():
    spec = importlib.util.spec_from_file_location("measure", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["measure"] = module
    spec.loader.exec_module(module)
    return module


measure = load_measure()
import html_scripts  # noqa: E402  (measure.py put the skill directory on sys.path)

if not TS_READY:
    print(f"test_measure_js: parser tests skipped — {SKIP_REASON}", file=sys.stderr)


def by_name(functions):
    return {f.name: f for f in functions}


def shape(f):
    return (f.line, f.lines, f.cc, f.params, f.depth)


def make_project(tmp: Path, *fixtures: str) -> Path:
    """A scratch project: the named fixtures next to a node_modules/typescript symlink."""
    project = tmp / "project"
    (project / "node_modules").mkdir(parents=True)
    os.symlink(TS_PACKAGE, project / "node_modules" / "typescript")
    for name in fixtures:
        shutil.copy(FIXTURES / name, project / name)
    return project


def run_cli(*args, env=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env)


class LanguageTest(unittest.TestCase):
    def test_javascript_and_html_files_are_measured(self):
        for name in ("a.js", "a.mjs", "a.cjs", "a.jsx", "A.JS"):
            self.assertEqual(measure.language_of(Path(name)), "js", name)
        self.assertEqual(measure.language_of(Path("page.html")), "html")

    def test_a_minified_file_is_build_output_and_is_not_measured(self):
        for name in ("vendor.min.js", "vendor.min.mjs", "Vendor.MIN.JS"):
            self.assertIsNone(measure.language_of(Path(name)), name)

    def test_collect_takes_javascript_and_html_and_leaves_minified_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("app.js", "worker.mjs", "legacy.cjs", "index.html", "vendor.min.js", "style.css"):
                (root / name).write_text("\n")
            found = sorted(p.name for p in measure.collect_files([root], changed=False, base="main"))
        self.assertEqual(found, ["app.js", "index.html", "legacy.cjs", "worker.mjs"])

    def test_collect_skips_generated_pages_and_their_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for directory in ("htmlcov", "_build", "_site", "src"):
                (root / directory).mkdir()
                (root / directory / "index.html").write_text("<script>function f() {}</script>\n")
                (root / directory / "app.js").write_text("function g() {}\n")
            found = sorted(str(p.relative_to(root)) for p in measure.collect_files([root], changed=False, base="main"))
        self.assertEqual(found, ["src/app.js", "src/index.html"])


@unittest.skipUnless(TS_READY, SKIP_REASON)
class JavaScriptMeasurementTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = make_project(Path(self._tmp.name), "sample.js")
        self.js = by_name(measure.parse_files([self.project / "sample.js"]).functions)

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_rows_follow_the_typescript_rules(self):
        self.assertEqual(
            {name: shape(f) for name, f in self.js.items()},
            {
                "clean": (4, 3, 1, 2, 0),
                "tooManyParams": (8, 1, 1, 4, 0),
                "complexBranches": (10, 11, 9, 1, 2),
                "Widget.constructor": (23, 3, 1, 1, 0),
                "Widget.label": (27, 3, 2, 1, 0),
                "anonymous": (32, 8, 1, 0, 0),
                "inner": (35, 3, 1, 0, 0),
            },
        )

    def test_every_javascript_extension_gives_the_same_rows(self):
        expected = {name: shape(f) for name, f in self.js.items()}
        for suffix in (".mjs", ".cjs", ".jsx"):
            copy = self.project / f"copy{suffix}"
            shutil.copy(FIXTURES / "sample.js", copy)
            rows = measure.parse_files([copy]).functions
            self.assertEqual({f.name: shape(f) for f in rows}, expected, suffix)
            self.assertTrue(all(f.file.endswith(f"copy{suffix}") for f in rows), suffix)

    def test_jsx_parses_in_a_javascript_file(self):
        (self.project / "box.jsx").write_text("export const Box = ({ a }) => <div>{a ? 1 : 2}</div>;\n")
        [row] = measure.parse_files([self.project / "box.jsx"]).functions
        self.assertEqual((row.name, row.cc), ("Box", 2))

    def test_file_shape_counts_lines_and_javascript_suppressions(self):
        # "as any" in the fixture is prose inside a string: only TypeScript has the cast.
        found = measure.measure_file_shape(self.project / "sample.js")
        self.assertEqual((found.language, found.lines, found.suppressions), ("js", 41, 1))

    def test_unparsable_javascript_is_a_broken_run(self):
        # A script that checks only the exit code must see a real syntax error.
        broken = self.project / "broken.js"
        broken.write_text("function broken( {\n")
        with self.assertRaises(measure.MeasureError) as ctx:
            measure.parse_files([broken, self.project / "sample.js"])
        self.assertRegex(str(ctx.exception), r"broken\.js:\d+: ")

    def test_typescript_syntax_in_javascript_is_a_broken_run(self):
        # The parser accepts `x: number` in a .js file; only the grammar check rejects it.
        (self.project / "typed.js").write_text("function f(x: number) {\n  return x;\n}\n")
        with self.assertRaises(measure.MeasureError) as ctx:
            measure.parse_files([self.project / "typed.js"])
        self.assertIn("typed.js:1: Type annotations can only be used in TypeScript files", str(ctx.exception))

    def test_typescript_syntax_in_an_inline_script_is_listed(self):
        page = self.project / "typed.html"
        page.write_text("<script>\nclass A { private y = 1 }\n</script>\n<script>function ok() {}</script>\n")
        parsed = measure.parse_files([page])
        self.assertEqual([f.name for f in parsed.functions], ["ok"])
        self.assertEqual([(s.line, "private" in s.message) for s in parsed.unparsed], [(2, True)])

    def test_the_cli_exits_two_on_unparsable_javascript(self):
        (self.project / "broken.mjs").write_text("export const = 1;\n")
        proc = run_cli(str(self.project / "broken.mjs"), env=cache_env(Path(self._tmp.name)))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("broken.mjs:1", proc.stderr)
        self.assertEqual(proc.stdout, "")

    def test_sloppy_mode_octal_forms_are_measured_not_refused(self):
        # Node runs these, and "\033[0m" is how a script colours its output.
        source = 'var mode = 0755;\nvar reset = "\\033[0m";\nvar day = 08;\nfunction paint() { return reset; }\n'
        (self.project / "colours.cjs").write_text(source)
        parsed = measure.parse_files([self.project / "colours.cjs"])
        self.assertEqual(([f.name for f in parsed.functions], parsed.unparsed), (["paint"], []))

    def test_a_typescript_file_with_an_octal_literal_is_still_a_broken_run(self):
        (self.project / "strict.ts").write_text("export const mode = 0755;\n")
        with self.assertRaises(measure.MeasureError) as ctx:
            measure.parse_files([self.project / "strict.ts"])
        self.assertIn("strict.ts:1", str(ctx.exception))

    def test_a_file_that_is_not_utf8_is_measured(self):
        # An old page or script is often cp1251; its letters move no line and no brace.
        script = self.project / "old.js"
        script.write_bytes("// Здравей\nfunction greet() {\n  return 1;\n}\n".encode("cp1251"))
        report = measure.build_report([script], measure.Thresholds())
        self.assertEqual([(f.name, f.line, f.lines) for f in report.functions], [("greet", 2, 3)])
        self.assertEqual(report.files[0].lines, 4)

    def test_an_identifier_in_a_single_byte_encoding_still_parses(self):
        # Read one character per byte, a cp1251 letter is a latin-1 letter; replaced, it would be no letter at all.
        script = self.project / "names.js"
        script.write_bytes("function поздрав() {\n  return 1;\n}\n".encode("cp1251"))
        report = measure.build_report([script], measure.Thresholds())
        self.assertEqual([(f.line, f.lines) for f in report.functions], [(1, 3)])
        self.assertEqual(report.unparsed, [])

    def test_a_report_mixes_javascript_with_the_other_languages(self):
        report = measure.build_report([FIXTURES / "sample.py", self.project / "sample.js"], measure.Thresholds())
        self.assertEqual(report.summary["functions"], 8 + 7)
        self.assertEqual(sorted(f.language for f in report.files), ["js", "py"])
        over = {f.name for f in report.functions if "params" in measure.exceeded(f, report.thresholds)}
        self.assertIn("tooManyParams", over)


class HtmlScriptBlocksTest(unittest.TestCase):
    """Which parts of an HTML file are JavaScript; no parser is needed to tell."""

    def setUp(self):
        self.text = (FIXTURES / "page.html").read_text()
        self.blocks = html_scripts.script_blocks(self.text)
        self.contents = [self.text[b.start : b.end] for b in self.blocks]

    def test_only_inline_javascript_is_a_block(self):
        self.assertEqual(len(self.blocks), 2)
        self.assertIn("function first", self.contents[0])
        self.assertIn("function third", self.contents[1])
        for skipped in ("inData", "behindSrc", "inTemplate", "commentedOut"):
            self.assertNotIn(skipped, "".join(self.contents))

    def test_a_block_starts_after_a_tag_that_spans_lines(self):
        self.assertTrue(self.contents[1].startswith("\nimport { helper }"), self.contents[1][:30])

    def test_a_block_keeps_its_line_and_column_when_taken_alone(self):
        for block in self.blocks:
            alone = html_scripts.in_place(self.text, block).split("\n")
            whole = self.text[: block.end].split("\n")
            first = self.text.count("\n", 0, block.start)
            self.assertEqual(len(alone), len(whole))
            self.assertEqual(len(alone[first]), len(whole[first]))
            self.assertEqual(alone[first + 1 :], whole[first + 1 :])
            self.assertEqual("".join(alone[:first]), "")

    def test_lines_count_the_code_and_not_the_blank_edges(self):
        self.assertEqual(html_scripts.script_lines(self.text, self.blocks), 4 + 12)

    def test_a_script_type_is_matched_by_its_mime_essence(self):
        text = (
            '<SCRIPT TYPE="Text/JavaScript; charset=utf-8">a()</SCRIPT>'
            '<script type="application/ld+json">{"b": 1}</script>'
            '<script type="importmap">{"imports": {}}</script>'
            "<script type=module>c()</script>"
        )
        self.assertEqual([text[b.start : b.end] for b in html_scripts.script_blocks(text)], ["a()", "c()"])

    def test_an_unclosed_script_runs_to_the_end_of_the_file(self):
        text = "<p>x</p>\n<script>\nopen();\n"
        [block] = html_scripts.script_blocks(text)
        self.assertEqual(text[block.start : block.end], "\nopen();\n")

    def test_a_page_without_scripts_has_no_block_and_no_lines(self):
        self.assertEqual(html_scripts.script_blocks("<p>function no() {}</p>\n"), [])

    def test_two_blocks_on_one_line_count_that_line_once(self):
        text = "<p>x</p>\n<script>f()</script><script>g()\nh()</script>\n"
        self.assertEqual(html_scripts.script_lines(text, html_scripts.script_blocks(text)), 2)

    def test_an_empty_or_blank_script_is_no_block(self):
        self.assertEqual(html_scripts.script_blocks("<script></script><script>  \n </script>\n"), [])

    def test_a_self_closing_script_tag_is_no_block(self):
        text = '<p>x</p><script/>\n<p>y</p>\n<script src="a.js"/>\n<script>real()</script>\n'
        self.assertEqual([text[b.start : b.end] for b in html_scripts.script_blocks(text)], ["real()"])


@unittest.skipUnless(TS_READY, SKIP_REASON)
class HtmlMeasurementTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.project = make_project(self.tmp, "page.html")
        self.page = self.project / "page.html"
        self.rows = measure.parse_files([self.page]).functions

    def tearDown(self):
        self._tmp.cleanup()

    def test_rows_carry_the_html_file_and_its_line(self):
        self.assertEqual(
            {f.name: shape(f) for f in self.rows},
            {"first": (10, 4, 2, 2, 1), "second": (25, 1, 1, 4, 0), "third": (27, 7, 4, 1, 3)},
        )
        lines = self.page.read_text().split("\n")
        for row in self.rows:
            self.assertTrue(row.file.endswith("page.html"), row.file)
            self.assertIn(row.name, lines[row.line - 1])

    def test_the_file_row_counts_script_lines_and_script_suppressions_only(self):
        # The page is 36 lines; the prose and the JSON block mention suppressions too.
        found = measure.measure_file_shape(self.page)
        self.assertEqual((found.language, found.lines, found.suppressions), ("html", 16, 1))

    def test_a_long_data_block_does_not_make_a_long_file(self):
        rows = ",\n".join('{"n": %d}' % n for n in range(600))
        self.page.write_text(f'<script type="application/json">[\n{rows}\n]</script>\n<script>const f = () => 1;</script>\n')
        report = measure.build_report([self.page], measure.Thresholds())
        self.assertEqual(report.files[0].lines, 1)
        self.assertEqual((report.summary["functions"], report.summary["over_file_lines"]), (1, 0))

    def test_a_page_that_is_not_utf8_is_measured_at_its_lines(self):
        page = "<p>Здравей</p>\n<script>\nfunction greet() {\n  return 1;\n}\n</script>\n"
        self.page.write_bytes(page.encode("cp1251"))
        report = measure.build_report([self.page], measure.Thresholds())
        self.assertEqual([(f.name, f.line) for f in report.functions], [("greet", 3)])
        self.assertEqual(report.files[0].lines, 3)

    def test_an_inline_identifier_in_a_single_byte_encoding_still_parses(self):
        self.page.write_bytes("<p>x</p>\n<script>\nfunction поздрав() {}\n</script>\n".encode("cp1251"))
        report = measure.build_report([self.page], measure.Thresholds())
        self.assertEqual([f.line for f in report.functions], [3])
        self.assertEqual(report.unparsed, [])

    def test_two_blocks_do_not_run_into_each_other(self):
        # Joined, `a` and the next block's parenthesis would parse as one call.
        self.page.write_text("<script>const a = b</script>\n<script>(function () { return 1; })()</script>\n")
        [row] = measure.parse_files([self.page]).functions
        self.assertEqual((row.name, row.line), ("anonymous", 2))

    def test_the_cli_prints_html_rows_with_all(self):
        proc = run_cli(str(self.page), "--all", env=cache_env(self.tmp))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertRegex(proc.stdout, r"page\.html:27 third\s+\[depth\]")
        self.assertRegex(proc.stdout, r"\n\s+16\s+1\s+\S*page\.html\n")
        self.assertIn("SUMMARY functions=3 ", proc.stdout)

    def test_an_inline_script_that_does_not_parse_is_listed_and_the_rest_is_measured(self):
        # A page template is not JavaScript until it is rendered; the run goes on and says what it left out.
        self.page.write_text("<script>\nconst rows = {{ rows|tojson }};\n</script>\n<script>function ok() {}</script>\n")
        proc = run_cli(str(self.page), env=cache_env(self.tmp))
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        self.assertRegex(
            proc.stdout, r"\nUNPARSED scripts, their functions are not measured: 1\n  \S*page\.html:2  \S.*\nSUMMARY "
        )
        self.assertRegex(proc.stdout, r"\nSUMMARY functions=1 .* unparsed_scripts=1\n$")

    def test_the_json_names_each_unparsed_script(self):
        self.page.write_text("<script>function ok() {}</script>\n<script>\n\nlet = {% if a %}1{% endif %};\n</script>\n")
        proc = run_cli(str(self.page), "--json", env=cache_env(self.tmp))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual([f["name"] for f in data["functions"]], ["ok"])
        [script] = data["unparsed"]
        self.assertTrue(script["file"].endswith("page.html"), script["file"])
        self.assertEqual(script["line"], 4)
        self.assertTrue(script["message"])
        self.assertEqual(data["summary"]["unparsed_scripts"], 1)

    def test_a_page_whose_scripts_all_parse_has_no_unparsed_section(self):
        proc = run_cli(str(self.page), env=cache_env(self.tmp))
        self.assertNotIn("UNPARSED", proc.stdout)
        self.assertIn(" unparsed_scripts=0\n", proc.stdout)


class HtmlWithoutParserTest(unittest.TestCase):
    def test_a_page_without_inline_javascript_needs_no_node_and_no_typescript(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "plain.html"
            page.write_text(
                '<p>text</p>\n<script src="app.js"></script>\n<script type="application/json">{}</script>\n<script>\n</script>\n'
            )
            env = cache_env(Path(tmp))
            env["PATH"] = str(Path(tmp) / "empty")
            proc = run_cli(str(page), "--all", env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("SUMMARY functions=0 over_lines=0 over_cc=0 over_params=0 over_depth=0 files=1", proc.stdout)
            self.assertFalse((Path(tmp) / "cache").exists())


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + sys.argv[1:])
