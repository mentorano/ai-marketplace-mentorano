#!/usr/bin/env python3
"""Measure function and file shape for Python, TypeScript, JavaScript and HTML sources.

Usage:
    measure.py <path>... [--changed] [--base origin/main] [--json] [--all]
               [--at <ref>] [--compare [<ref>]]
               [--max-lines 20] [--max-cc 10] [--max-params 3]
               [--max-file-lines 500] [--max-depth 2]

Per function: lines, cyclomatic complexity, parameters, nesting depth.
Per file: lines and suppressed findings (# noqa, # type: ignore,
eslint-disable, @ts-ignore, @ts-expect-error, and `as any` in TypeScript).
Python suppressions are counted in comments only; the others by text match.

Measured files: .py, .ts, .tsx, .js, .mjs, .cjs, .jsx and .html. A minified
.min.js is build output and is not measured. Of an .html file only the
inline <script> blocks the browser runs as JavaScript are code: their
functions print with the line in the .html file, and the file row counts
their lines and suppressions only. Markup, a `src` script and a data block
(application/json, a template) count for nothing, so a long page or a large
data block is not a long file.

A .ts or .js file that does not parse is a broken run, exit 2. An inline
script of an .html file that does not parse does not break the run: a page
template is not JavaScript until it is rendered. It is listed under
UNPARSED and counted as unparsed_scripts in SUMMARY and VERDICT, because
its functions are in no row. Legacy octal forms (0755, an octal escape in a string) are read as the
engines read them.

Python files go through the stdlib ast. The others go through measure-ts.mjs
next to this script, using the typescript package found in the nearest
node_modules above each file, or the one typescript.py installs once into
the plugin's cache directory (~/.cache/clean-code, moved with
CLEAN_CODE_CACHE_DIR) when the project has none. File collection and the
language of a file live in languages.py next to this script, shared with
boundaries.py.

--at <ref> measures the files as committed at ref instead of the working
tree, so uncommitted edits and untracked files stay out; with --changed the
files are the ones committed between the merge-base with --base and ref.
--compare measures the same files a second time at <ref> (default: the
merge-base with --base) and gives every function and file a verdict, so the
before needs no copy on disk; compare.py lists the verdicts. Both print
every path from the repository root, so the two sides pair up wherever the
command runs from.

Exit codes: 0 measured (the numbers are the verdict), 2 broken run or bad arguments.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tokenize
from dataclasses import asdict, dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
# languages.py sits next to this script; the path makes it importable when
# measure.py is run by its full path from any working directory.
sys.path.insert(0, str(SCRIPT_DIR))

from html_scripts import script_blocks, script_lines, script_text
from languages import (
    FunctionMeasure,
    MeasureError,
    _display,
    collect_files,
    language_of,
    measure_python_file,
    read_script_text,
    read_text,
)
from typescript import UnparsedScript, find_typescript_package, parse_files
from shape import FileMeasure, Thresholds, exceeded
import compare as comparing
from revisions import Revision, add_revision_flags, before_ref, relative_to_repo, repository_of, snapshot, verify_ref

_JS_SUPPRESSIONS = [re.compile(r"eslint-disable"), re.compile(r"@ts-ignore"), re.compile(r"@ts-expect-error")]
SUPPRESSION_PATTERNS = {
    "py": [re.compile(r"#\s*noqa"), re.compile(r"#\s*type:\s*ignore")],
    # `as any` is TypeScript syntax; in JavaScript the words only occur in prose.
    "ts": [*_JS_SUPPRESSIONS, re.compile(r"\bas any\b")],
    "js": _JS_SUPPRESSIONS,
    "html": _JS_SUPPRESSIONS,
}
MEASURED = "Python, TypeScript, JavaScript or HTML"
NO_FILES = f"no {MEASURED} files to measure"


# --- Files --------------------------------------------------------------------

def _py_suppressions(path: Path, text: str) -> int:
    """Count Python suppressions in comments only, never in strings or docstrings."""
    patterns = SUPPRESSION_PATTERNS["py"]
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError) as exc:
        raise MeasureError(f"{path}: cannot tokenize: {exc}") from exc
    comments = [token.string for token in tokens if token.type == tokenize.COMMENT]
    return sum(len(pattern.findall(comment)) for comment in comments for pattern in patterns)


def _suppressions(path: Path, text: str, language: str) -> int:
    if language == "py":
        return _py_suppressions(path, text)
    return sum(len(pattern.findall(text)) for pattern in SUPPRESSION_PATTERNS[language])


def _code(text: str, language: str) -> tuple[int, str]:
    """The line count of a file and the text its suppressions are counted in."""
    if language != "html":
        return text.count("\n") + (0 if text.endswith("\n") or not text else 1), text
    # Of an HTML file only the inline scripts are code. Markup and data blocks
    # are content: counted, a long page would read as a long source file.
    blocks = script_blocks(text)
    return script_lines(text, blocks), script_text(text, blocks)


def measure_file_shape(path: Path) -> FileMeasure:
    language = language_of(path)
    if language is None:
        raise MeasureError(f"{path}: not a {MEASURED} file")
    text = read_script_text(path) if language in ("js", "html") else read_text(path)
    lines, code = _code(text, language)
    return FileMeasure(
        file=_display(path),
        language=language,
        lines=lines,
        suppressions=_suppressions(path, code, language),
    )


# --- Report -------------------------------------------------------------------

@dataclass
class Report:
    thresholds: Thresholds
    functions: list[FunctionMeasure]
    files: list[FileMeasure]
    unparsed: list[UnparsedScript]
    summary: dict[str, int]


def _severity(fm: FunctionMeasure, t: Thresholds) -> float:
    return max(fm.lines / t.lines, fm.cc / t.cc, fm.params / t.params, fm.depth / t.depth)


def _summarize(
    functions: list[FunctionMeasure], shapes: list[FileMeasure], t: Thresholds
) -> dict[str, int]:
    return {
        "functions": len(functions),
        "over_lines": sum(fm.lines > t.lines for fm in functions),
        "over_cc": sum(fm.cc > t.cc for fm in functions),
        "over_params": sum(fm.params > t.params for fm in functions),
        "over_depth": sum(fm.depth > t.depth for fm in functions),
        "files": len(shapes),
        "over_file_lines": sum(fs.lines > t.file_lines for fs in shapes),
        "suppressions": sum(fs.suppressions for fs in shapes),
    }


def build_report(files: list[Path], thresholds: Thresholds) -> Report:
    functions: list[FunctionMeasure] = []
    shapes: list[FileMeasure] = []
    ts_files: list[Path] = []
    for path in files:
        shapes.append(measure_file_shape(path))
        if language_of(path) == "py":
            functions.extend(measure_python_file(path))
        else:
            ts_files.append(path)
    parsed = parse_files(ts_files)
    functions.extend(parsed.functions)
    functions.sort(key=lambda fm: (-_severity(fm, thresholds), fm.file, fm.line))
    shapes.sort(key=lambda fs: (-fs.lines, fs.file))
    unparsed = sorted(parsed.unparsed, key=lambda script: (script.file, script.line))
    # A script the parser could not read is in no function row; the count keeps it in the verdict.
    summary = {**_summarize(functions, shapes, thresholds), "unparsed_scripts": len(unparsed)}
    return Report(thresholds=thresholds, functions=functions, files=shapes, unparsed=unparsed, summary=summary)


# --- Rendering ----------------------------------------------------------------

@dataclass(frozen=True)
class Counted:
    """How many rows were measured and how many of them are over a threshold."""

    over: int
    total: int


def _functions_header(counted: Counted, t: Thresholds, show_all: bool) -> str:
    thresholds_text = f"lines>{t.lines} cc>{t.cc} params>{t.params} depth>{t.depth}"
    if show_all:
        return f"FUNCTIONS ({counted.over} of {counted.total} over threshold: {thresholds_text})"
    return f"FUNCTIONS over threshold ({thresholds_text}): {counted.over} of {counted.total}"


def _files_header(counted: Counted, t: Thresholds, show_all: bool) -> str:
    suffix = f"over {t.file_lines} lines or with suppressions"
    if show_all:
        return f"FILES ({counted.over} of {counted.total} {suffix})"
    return f"FILES {suffix}: {counted.over} of {counted.total}"


def _render_functions(report: Report, show_all: bool) -> list[str]:
    t = report.thresholds
    offenders = [fm for fm in report.functions if exceeded(fm, t)]
    shown = report.functions if show_all else offenders
    out = [_functions_header(Counted(len(offenders), len(report.functions)), t, show_all)]
    if not shown:
        return out
    out.append("  lines    cc  params  depth  where")
    for fm in shown:
        flags = " ".join(exceeded(fm, t))
        marker = f"  [{flags}]" if flags else ""
        out.append(f"  {fm.lines:5d} {fm.cc:5d}  {fm.params:6d}  {fm.depth:5d}  {fm.file}:{fm.line} {fm.name} {marker}".rstrip())
    return out


def _render_files(report: Report, show_all: bool) -> list[str]:
    t = report.thresholds
    file_offenders = [fs for fs in report.files if fs.lines > t.file_lines or fs.suppressions]
    shown_files = report.files if show_all else file_offenders
    out = [_files_header(Counted(len(file_offenders), len(report.files)), t, show_all)]
    if not shown_files:
        return out
    out.append("  lines  suppr  file")
    for fs in shown_files:
        out.append(f"  {fs.lines:5d}  {fs.suppressions:5d}  {fs.file}")
    return out


def _render_unparsed(report: Report) -> list[str]:
    """The JavaScript no function row covers; nothing when every script parsed."""
    if not report.unparsed:
        return []
    out = [f"UNPARSED scripts, their functions are not measured: {len(report.unparsed)}"]
    out.extend(f"  {script.file}:{script.line}  {script.message}" for script in report.unparsed)
    return out


def _summary_text(summary: dict[str, int]) -> str:
    return " ".join(f"{key}={value}" for key, value in summary.items())


def render_text(report: Report, show_all: bool) -> str:
    lines: list[str] = []
    if not report.files:
        lines.append(NO_FILES)
    lines.extend(_render_functions(report, show_all))
    lines.extend(_render_files(report, show_all))
    lines.extend(_render_unparsed(report))
    lines.append("SUMMARY " + _summary_text(report.summary))
    return "\n".join(lines) + "\n"


def _payload(report: Report) -> dict[str, object]:
    return {
        "thresholds": asdict(report.thresholds),
        "functions": [asdict(fm) for fm in report.functions],
        "files": [asdict(fs) for fs in report.files],
        "unparsed": [asdict(script) for script in report.unparsed],
        "summary": report.summary,
    }


def render_json(report: Report) -> str:
    return json.dumps(_payload(report), indent=2) + "\n"


@dataclass(frozen=True)
class Compared:
    """The two reports of one --compare run and the ref the before side was read at."""

    before: Report
    after: Report
    ref: str


def render_compare_text(compared: Compared, show_all: bool) -> str:
    comparison = comparing.compare(compared.before, compared.after, compared.after.thresholds)
    lines = [] if compared.after.files else [NO_FILES]
    lines += comparing.render_text(comparison, compared.ref, show_all)
    lines += _render_unparsed(compared.after)
    lines.append("SUMMARY " + _summary_text(compared.after.summary))
    lines.append(f"BEFORE {compared.ref} " + _summary_text(compared.before.summary))
    lines.append(comparing.verdict_line(comparison))
    return "\n".join(lines) + "\n"


def render_compare_json(compared: Compared) -> str:
    comparison = comparing.compare(compared.before, compared.after, compared.after.thresholds)
    payload = _payload(compared.after)
    payload["before"] = {"ref": compared.ref, "summary": compared.before.summary}
    payload["compare"] = comparing.to_json(comparison, compared.ref)
    return json.dumps(payload, indent=2) + "\n"


# --- CLI ----------------------------------------------------------------------

def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value!r}")
    return parsed


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", type=Path, help="files or directories to measure")
    parser.add_argument("--changed", action="store_true", help="only files that differ from --base, plus untracked")
    parser.add_argument("--base", default="origin/main", help="git ref for --changed (default: origin/main)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of the text table")
    parser.add_argument("--all", action="store_true", help="show every function and file, not only offenders")
    add_revision_flags(parser, "the same files")
    defaults = Thresholds()
    parser.add_argument("--max-lines", type=positive_int, default=defaults.lines)
    parser.add_argument("--max-cc", type=positive_int, default=defaults.cc)
    parser.add_argument("--max-params", type=positive_int, default=defaults.params)
    parser.add_argument("--max-file-lines", type=positive_int, default=defaults.file_lines)
    parser.add_argument("--max-depth", type=positive_int, default=defaults.depth)
    return parser.parse_args(argv)


def _require_files(revision: Revision, pathspecs: list[str]) -> list[str]:
    """Every given path has files at the revision; a typo would otherwise measure nothing."""
    for pathspec in pathspecs:
        if not revision.files([pathspec]):
            raise MeasureError(f"{pathspec}: no files at {revision.ref}")
    return revision.files(pathspecs)


def _selected_at(args: argparse.Namespace, revision: Revision) -> list[str]:
    pathspecs = relative_to_repo(revision.repo, list(args.paths))
    found = revision.changed_since(args.base, pathspecs) if args.changed else _require_files(revision, pathspecs)
    return [relative for relative in found if language_of(Path(relative))]


def _from_root(report: Report, root: Path) -> Report:
    """Print every path from the repository root, so a mirror and the working tree name a file alike."""
    for row in [*report.functions, *report.files, *report.unparsed]:
        row.file = (Path.cwd() / row.file).resolve().relative_to(root).as_posix()
    return report


def measure_at(revision: Revision, relatives: list[str], thresholds: Thresholds) -> Report:
    """Measure the files as they are at the revision; one that does not exist there is left out."""
    with snapshot(revision, relatives) as taken, taken.entered():
        present = [taken.root / relative for relative in relatives if (taken.root / relative).is_file()]
        return _from_root(build_report(present, thresholds), taken.root)


def _after(args: argparse.Namespace, repo: Path, thresholds: Thresholds) -> tuple[Report, list[str]]:
    if args.at is None:
        files = collect_files(list(args.paths), changed=args.changed, base=args.base)
        relatives = relative_to_repo(repo, files)
        return _from_root(build_report(files, thresholds), repo), relatives
    verify_ref(repo, args.at, "--at")
    revision = Revision(repo, args.at)
    relatives = _selected_at(args, revision)
    return measure_at(revision, relatives, thresholds), relatives


def _run_revisions(args: argparse.Namespace, thresholds: Thresholds) -> str:
    repo = repository_of(args.paths[0])
    after, relatives = _after(args, repo, thresholds)
    if args.compare is None:
        return render_json(after) if args.json else render_text(after, show_all=args.all)
    commit, label = before_ref(repo, args)
    compared = Compared(before=measure_at(Revision(repo, commit), relatives, thresholds), after=after, ref=label)
    return render_compare_json(compared) if args.json else render_compare_text(compared, show_all=args.all)


def _run(args: argparse.Namespace, thresholds: Thresholds) -> str:
    if args.at is not None or args.compare is not None:
        return _run_revisions(args, thresholds)
    report = build_report(collect_files(list(args.paths), changed=args.changed, base=args.base), thresholds)
    return render_json(report) if args.json else render_text(report, show_all=args.all)


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    thresholds = Thresholds(
        lines=args.max_lines,
        cc=args.max_cc,
        params=args.max_params,
        file_lines=args.max_file_lines,
        depth=args.max_depth,
    )
    try:
        output = _run(args, thresholds)
    except MeasureError as exc:
        print(f"measure.py: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
