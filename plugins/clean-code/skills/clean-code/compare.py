"""Per-row verdicts between two measurements of the same files.

Imported by measure.py for --compare; nothing runs this file. The skill's
rules are about single functions and files — a touched function crosses no
new threshold, a new one is under all of them — and a SUMMARY is a sum that
hides a swap, so every row is judged on its own here.

Function verdicts:
  new-over    new, over a threshold                  blocks
  crossed     over a threshold it was under before   blocks
  grew        over before and after, and a measure that is over went up; the report says why
  fixed       over before, under every threshold after
  still-over  over before and after, not worse       context
  new         new and under every threshold          context

File verdicts use the file-lines cap the same way (new-over, crossed, grew,
fixed), plus suppressions-up: more suppressions than before, each new one
allowed only with its reason on the line.

A function is matched by file, name and its position among the functions of
that name in the file. A renamed function is therefore one removed row and
one new row.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass

from languages import FunctionMeasure
from shape import FileMeasure, Thresholds, exceeded

QUIET = frozenset({"still-over", "new"})
ORDER = ("new-over", "crossed", "grew", "suppressions-up", "fixed", "still-over", "new")
VERDICT_KEYS = (
    ("new_over", "function", "new-over"),
    ("crossed", "function", "crossed"),
    ("grew", "function", "grew"),
    ("fixed", "function", "fixed"),
    ("file_new_over", "file", "new-over"),
    ("file_crossed", "file", "crossed"),
    ("file_grew", "file", "grew"),
    ("suppressions_up", "file", "suppressions-up"),
)

Key = tuple[str, str, int]


@dataclass(frozen=True)
class FunctionChange:
    verdict: str
    before: FunctionMeasure | None
    after: FunctionMeasure
    flags: tuple[str, ...]


@dataclass(frozen=True)
class FileChange:
    verdict: str
    before: FileMeasure | None
    after: FileMeasure


@dataclass(frozen=True)
class Comparison:
    functions: list[FunctionChange]
    files: list[FileChange]

    def verdict(self) -> dict[str, int]:
        counts = Counter([("function", c.verdict) for c in self.functions] + [("file", c.verdict) for c in self.files])
        return {key: counts[(kind, verdict)] for key, kind, verdict in VERDICT_KEYS}


def _keyed(functions: list[FunctionMeasure]) -> dict[Key, FunctionMeasure]:
    seen: Counter[tuple[str, str]] = Counter()
    out: dict[Key, FunctionMeasure] = {}
    for fm in sorted(functions, key=lambda f: (f.file, f.line)):
        out[(fm.file, fm.name, seen[(fm.file, fm.name)])] = fm
        seen[(fm.file, fm.name)] += 1
    return out


def _grew(before: FunctionMeasure, after: FunctionMeasure, over: set[str]) -> bool:
    return any(getattr(after, measure) > getattr(before, measure) for measure in over)


def _function_verdict(before: FunctionMeasure | None, after: FunctionMeasure, t: Thresholds):
    """The verdict and the thresholds it names, or None for a row that stays under every threshold."""
    now = set(exceeded(after, t))
    if before is None:
        return ("new-over" if now else "new"), now
    was = set(exceeded(before, t))
    if now - was:
        return "crossed", now - was
    if not now:
        return ("fixed", was) if was else None
    return ("grew" if _grew(before, after, now) else "still-over"), now


def function_change(before: FunctionMeasure | None, after: FunctionMeasure, t: Thresholds) -> FunctionChange | None:
    judged = _function_verdict(before, after, t)
    if judged is None:
        return None
    verdict, flags = judged
    return FunctionChange(verdict, before, after, tuple(sorted(flags)))


def _cap_verdict(before: FileMeasure | None, after: FileMeasure, cap: int) -> str | None:
    was_over = before is not None and before.lines > cap
    now_over = after.lines > cap
    if now_over and before is None:
        return "new-over"
    if now_over and not was_over:
        return "crossed"
    if now_over and after.lines > before.lines:
        return "grew"
    return "fixed" if was_over and not now_over else None


def file_changes(before: FileMeasure | None, after: FileMeasure, t: Thresholds) -> list[FileChange]:
    verdicts = [_cap_verdict(before, after, t.file_lines)]
    if after.suppressions > (before.suppressions if before else 0):
        verdicts.append("suppressions-up")
    return [FileChange(v, before, after) for v in verdicts if v]


def _rank(verdict: str) -> int:
    return ORDER.index(verdict)


def compare(before, after, t: Thresholds) -> Comparison:
    """Judge every function and file of `after` against `before`; both are measure.py Reports."""
    old = _keyed(before.functions)
    judged = (function_change(old.get(key), fm, t) for key, fm in _keyed(after.functions).items())
    functions = sorted((c for c in judged if c), key=lambda c: (_rank(c.verdict), c.after.file, c.after.line))
    old_files = {fs.file: fs for fs in before.files}
    files = [change for fs in after.files for change in file_changes(old_files.get(fs.file), fs, t)]
    return Comparison(functions, sorted(files, key=lambda c: (_rank(c.verdict), c.after.file)))


# --- Rendering ----------------------------------------------------------------

def _shape(fm: FunctionMeasure | None) -> str:
    return "-" if fm is None else f"{fm.lines}/{fm.cc}/{fm.params}/{fm.depth}"


def _file_shape(fs: FileMeasure | None) -> str:
    return "-" if fs is None else f"{fs.lines}/{fs.suppressions}"


def _function_lines(changes: list[FunctionChange]) -> list[str]:
    out = ["  verdict      before           after            where"]
    for c in changes:
        flags = f"  [{' '.join(c.flags)}]" if c.flags else ""
        where = f"{c.after.file}:{c.after.line} {c.after.name}"
        out.append(f"  {c.verdict:<11}  {_shape(c.before):<15}  {_shape(c.after):<15}  {where}{flags}")
    return out


def _file_lines(changes: list[FileChange]) -> list[str]:
    out = ["  verdict          before     after      file"]
    for c in changes:
        out.append(f"  {c.verdict:<15}  {_file_shape(c.before):<9}  {_file_shape(c.after):<9}  {c.after.file}")
    return out


def render_text(comparison: Comparison, ref: str, show_all: bool) -> list[str]:
    functions = [c for c in comparison.functions if show_all or c.verdict not in QUIET]
    head = f"COMPARE functions against {ref} (lines/cc/params/depth): {len(functions)} rows"
    out = [head, *(_function_lines(functions) if functions else [])]
    out.append(f"COMPARE files against {ref} (lines/suppressions): {len(comparison.files)} rows")
    out.extend(_file_lines(comparison.files) if comparison.files else [])
    return out


def verdict_line(comparison: Comparison) -> str:
    return "VERDICT " + " ".join(f"{key}={value}" for key, value in comparison.verdict().items())


def _function_row(c: FunctionChange) -> dict[str, object]:
    return {
        "verdict": c.verdict,
        "file": c.after.file,
        "name": c.after.name,
        "flags": list(c.flags),
        "before": asdict(c.before) if c.before else None,
        "after": asdict(c.after),
    }


def _file_row(c: FileChange) -> dict[str, object]:
    before = asdict(c.before) if c.before else None
    return {"verdict": c.verdict, "file": c.after.file, "before": before, "after": asdict(c.after)}


def to_json(comparison: Comparison, ref: str) -> dict[str, object]:
    return {
        "ref": ref,
        "functions": [_function_row(c) for c in comparison.functions],
        "files": [_file_row(c) for c in comparison.files],
        "verdict": comparison.verdict(),
    }
