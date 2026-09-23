#!/usr/bin/env python3
"""Measure the import boundaries of a Python package: direction, cycles, framework leaks.

Usage:
    boundaries.py <path>... [--changed] [--base origin/main] [--json] [--all]
                  [--at <ref>] [--compare [<ref>]]
                  [--layers api,services,models,schemas,domain,parsers]
                  [--core core,shared] [--domain domain,shared,parsers]

Every file gets a place (module, layer) from its path under the top-level
package: app/billing/api/users.py is module `billing`, layer `api`;
app/api/users.py (flat layout) is module `app`, layer `api`; a directory that
is not a layer name gives layer `root`. Every import is then an edge between
two places. Nothing is dropped: a file that fits no layer is reported as root.

Measures, each a count; the rule is 0 unless said otherwise:
  upward               services / models / domain importing api
  cycles               pairs of modules that import each other; the direction
                       with fewer imports is printed as the closing edges
  cyclic_modules       modules inside any cycle, pairs or longer (strongly
                       connected components of the module graph)
  core_outward         a --core module importing a feature module; main.py is
                       the composition root and is exempt
  framework_in_domain  fastapi / sqlalchemy / starlette imported under a
                       --domain module or layer
  sql_in_api           files under api/ whose statements contain select(,
                       .execute(, .where( or func. (text match); sites per file
  http_in_services     fastapi / starlette imported under services/
  ports                Protocol / ABC classes under services/ or domain/
                       (informational, no rule)

Core modules and the package root are not part of the cycle graph: their
outward edges are core_outward. Point the script at the package root, one
package per run: a subtree sees only its own edges, so its cycles are
incomplete. The package and every directory under it need an __init__.py;
without the top one the files are placed under a lower root and no import
names it, which the script reports on stderr. --changed
narrows the rows to files that differ from --base (row_files in the SUMMARY);
cycles and cyclic_modules always cover the whole tree, because a cycle is not
a property of one file.

--at <ref> reads the package as committed at ref, so an uncommitted edit
stays out. --compare reads it a second time at <ref> (default: the
merge-base with --base), prints that SUMMARY as the BEFORE line, and a
VERDICT line with every rule count that went up. With --changed both sides
keep rows from the same files.

Python only, through the stdlib ast. A TypeScript file is a broken run; use
dependency-cruiser there. The import graph lives in imports.py, the rules in
boundary_rules.py and file collection in languages.py, all next to this script.

Exit codes: 0 measured (the numbers are the verdict), 2 broken run or bad arguments.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
# imports.py and languages.py sit next to this script; the path makes them
# importable when boundaries.py is run by its full path from any directory.
sys.path.insert(0, str(SCRIPT_DIR))

from boundary_rules import COMPOSITION_ROOT, DOMAIN_FRAMEWORKS, HTTP_FRAMEWORKS, Cycle, Report, build_report
from imports import SQL_SITE, Edge, External, Layout, Package, Place, SqlFile, parse_sources
from languages import MeasureError, collect_files
from revisions import Revision, add_revision_flags, before_ref, relative_to_repo, repository_of, snapshot, verify_ref

# --- Rendering ----------------------------------------------------------------

def _edge_lines(edges: list[Edge]) -> list[str]:
    return [f"  {e.file}:{e.line} -> {e.target}" for e in edges]


def _external_lines(externals: list[External]) -> list[str]:
    return [f"  {e.file}:{e.line} imports {e.framework}" for e in externals]


def _cycle_lines(cycle: Cycle) -> list[str]:
    a, b = cycle.forward
    head = f"  {a} -> {b} {cycle.forward_count}, {b} -> {a} {cycle.backward_count}; closing edges:"
    return [head] + [f"    {e.file}:{e.line} -> {e.target}" for e in cycle.closing]


def _sql_lines(files: list[SqlFile]) -> list[str]:
    return ["  sites  file"] + [f"  {f.sites:5d}  {f.file}" for f in files] if files else []


def _sorted_places(modules: Counter[Place]) -> list[tuple[Place, int]]:
    return sorted(modules.items(), key=lambda item: str(item[0]))


def _modules_lines(report: Report) -> list[str]:
    out = ["MODULES (files per module and layer)", "  files  module.layer"]
    out += [f"  {count:5d}  {place}" for place, count in _sorted_places(report.modules)]
    out.append("MODULE EDGES (imports between modules)")
    out += [f"  {count:5d}  {a} -> {b}" for (a, b), count in sorted(report.module_edges.items())]
    return out


def _sections(report: Report) -> list[tuple[str, int, list[str]]]:
    """(title, count, rows) per measure, in the order the text report prints them."""
    layout = report.layout
    s = report.summary
    return [
        ("UPWARD (services/models/domain -> api)", s["upward"], _edge_lines(report.upward)),
        ("CYCLES (module pairs that import each other)", s["cycles"], [line for c in report.cycles for line in _cycle_lines(c)]),
        ("CYCLIC MODULES (inside any cycle)", s["cyclic_modules"], [f"  {m}" for m in report.cyclic_modules]),
        (f"CORE OUTWARD ({','.join(sorted(layout.core))} -> feature, {COMPOSITION_ROOT} exempt)", s["core_outward"], _edge_lines(report.core_outward)),
        (f"FRAMEWORK IN DOMAIN ({'/'.join(sorted(DOMAIN_FRAMEWORKS))} under {','.join(sorted(layout.domain))})", s["framework_in_domain"], _external_lines(report.framework_in_domain)),
        (f"SQL IN API (statements with {SQL_SITE.pattern} under api/)", s["sql_in_api"], _sql_lines(report.sql_in_api)),
        (f"HTTP IN SERVICES ({'/'.join(sorted(HTTP_FRAMEWORKS))} under services/)", s["http_in_services"], _external_lines(report.http_in_services)),
        ("PORTS (Protocol/ABC under services/ or domain/)", s["ports"], [f"  {p.file}:{p.line} {p.name}" for p in report.ports]),
    ]


def render_text(report: Report, show_all: bool) -> str:
    lines: list[str] = []
    if not report.sources:
        lines.append("no Python files to measure")
    for title, count, rows in _sections(report):
        lines.append(f"{title}: {count}")
        lines.extend(rows)
    if show_all:
        lines.extend(_modules_lines(report))
    lines.append("SUMMARY " + " ".join(f"{key}={value}" for key, value in report.summary.items()))
    return "\n".join(lines) + "\n"


ROW_LISTS = ("upward", "cycles", "core_outward", "framework_in_domain", "sql_in_api", "http_in_services", "ports")


def _payload(report: Report) -> dict[str, object]:
    return {
        "layout": {key: sorted(value) for key, value in asdict(report.layout).items()},
        "modules": [{"module": p.module, "layer": p.layer, "files": n} for p, n in _sorted_places(report.modules)],
        "module_edges": [{"from": a, "to": b, "imports": n} for (a, b), n in sorted(report.module_edges.items())],
        **{name: [row.row() for row in getattr(report, name)] for name in ROW_LISTS},
        "cyclic_modules": report.cyclic_modules,
        "summary": report.summary,
    }


def render_json_payload(payload: dict[str, object]) -> str:
    return json.dumps(payload, indent=2) + "\n"


def render_json(report: Report) -> str:
    return render_json_payload(_payload(report))


# --- CLI ----------------------------------------------------------------------

def names(value: str) -> frozenset[str]:
    parsed = frozenset(name.strip() for name in value.split(",") if name.strip())
    if not parsed:
        raise argparse.ArgumentTypeError(f"expected a comma-separated list of names, got {value!r}")
    return parsed


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", type=Path, help="files or directories to measure")
    parser.add_argument("--changed", action="store_true", help="rows only from files that differ from --base, plus untracked")
    parser.add_argument("--base", default="origin/main", help="git ref for --changed (default: origin/main)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of the text report")
    parser.add_argument("--all", action="store_true", help="also list every module, layer and module edge")
    add_revision_flags(parser, "the package")
    defaults = Layout()
    parser.add_argument("--layers", type=names, default=defaults.layers, help="layer directory names")
    parser.add_argument("--core", type=names, default=defaults.core, help="modules that must not import a feature")
    parser.add_argument("--domain", type=names, default=defaults.domain, help="modules or layers that must not import the framework")
    return parser.parse_args(argv)


def _changed_set(args: argparse.Namespace) -> set[Path] | None:
    if not args.changed:
        return None
    return {path.resolve() for path in collect_files(list(args.paths), changed=True, base=args.base)}


def _no_edges_note(package: Package) -> str:
    return (
        f"boundaries.py: no file imports the package {package.name!r} ({package.root}). "
        "Every count is 0 by absence, not by cleanliness: check that the package root and each "
        "directory under it have an __init__.py."
    )


RULE_COUNTS = (
    "upward",
    "cycles",
    "cyclic_modules",
    "core_outward",
    "framework_in_domain",
    "sql_in_api",
    "sql_sites",
    "http_in_services",
)


@dataclass(frozen=True)
class Outcome:
    """One side of a run, rendered while its files still exist."""

    payload: dict[str, object]
    text: str
    note: str | None

    @property
    def summary(self) -> dict[str, int]:
        return self.payload["summary"]


def _outcome(report: Report, show_all: bool) -> Outcome:
    note = _no_edges_note(report.package) if report.sources and not report.edges else None
    return Outcome(_payload(report), render_text(report, show_all=show_all), note)


def _measure(paths: list[Path], layout: Layout, changed: set[Path] | None) -> Report:
    files = collect_files(paths, changed=False, base="")
    return build_report(parse_sources(files, layout), layout, changed)


@dataclass(frozen=True)
class Measurement:
    """What every side of a run shares: the arguments, the layout and the repository."""

    args: argparse.Namespace
    layout: Layout
    repo: Path

    def working_tree(self) -> Outcome:
        return _outcome(_measure(list(self.args.paths), self.layout, _changed_set(self.args)), self.args.all)

    def at(self, ref: str, changed: list[str] | None) -> Outcome:
        """The package as committed at ref; with `changed`, rows come from those repository paths only."""
        revision = Revision(self.repo, ref)
        with snapshot(revision, revision.files(relative_to_repo(self.repo, list(self.args.paths)))) as taken:
            roots = [root for root in map(taken.mirror, self.args.paths) if root.exists()]
            kept = None if changed is None else {(taken.root / relative).resolve() for relative in changed}
            with taken.entered():
                return _outcome(_measure(roots, self.layout, kept), self.args.all)

    def after(self) -> tuple[Outcome, list[str] | None]:
        if self.args.at is None:
            changed = _changed_set(self.args)
            relatives = None if changed is None else relative_to_repo(self.repo, sorted(changed))
            return self.working_tree(), relatives
        verify_ref(self.repo, self.args.at, "--at")
        relatives = self._changed_at_ref()
        return self.at(self.args.at, relatives), relatives

    def _changed_at_ref(self) -> list[str] | None:
        if not self.args.changed:
            return None
        wanted = relative_to_repo(self.repo, list(self.args.paths))
        return Revision(self.repo, self.args.at).changed_since(self.args.base, wanted)


def _went_up(before: dict[str, int], after: dict[str, int]) -> dict[str, dict[str, int]]:
    return {key: {"before": before[key], "after": after[key]} for key in RULE_COUNTS if after[key] > before[key]}


def verdict_line(went_up: dict[str, dict[str, int]]) -> str:
    counts = ",".join(f"{key}:{pair['before']}->{pair['after']}" for key, pair in went_up.items())
    return "VERDICT up=" + (counts or "none")


def _compared_json(after: Outcome, before: Outcome, label: str) -> str:
    compare = {"ref": label, "up": _went_up(before.summary, after.summary)}
    return render_json_payload({**after.payload, "before": {"ref": label, "summary": before.summary}, "compare": compare})


def _compared_text(after: Outcome, before: Outcome, label: str) -> str:
    before_line = f"BEFORE {label} " + " ".join(f"{key}={value}" for key, value in before.summary.items())
    return after.text + before_line + "\n" + verdict_line(_went_up(before.summary, after.summary)) + "\n"


def _run_revisions(args: argparse.Namespace, layout: Layout) -> tuple[str, str | None]:
    run = Measurement(args, layout, repository_of(args.paths[0]))
    after, relatives = run.after()
    if args.compare is None:
        return (render_json_payload(after.payload) if args.json else after.text), after.note
    commit, label = before_ref(run.repo, args)
    compared = _compared_json if args.json else _compared_text
    return compared(after, run.at(commit, relatives), label), after.note


def _run(args: argparse.Namespace, layout: Layout) -> tuple[str, str | None]:
    if args.at is not None or args.compare is not None:
        return _run_revisions(args, layout)
    files = collect_files(list(args.paths), changed=False, base=args.base)
    outcome = _outcome(build_report(parse_sources(files, layout), layout, _changed_set(args)), args.all)
    return (render_json_payload(outcome.payload) if args.json else outcome.text), outcome.note


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    layout = Layout(layers=args.layers, core=args.core, domain=args.domain)
    try:
        output, note = _run(args, layout)
    except MeasureError as exc:
        print(f"boundaries.py: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(output)
    if note:
        print(note, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
