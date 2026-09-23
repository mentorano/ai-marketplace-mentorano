"""The thresholds and the file row, shared by measure.py and compare.py.

Imported only; nothing runs this file. They live apart from measure.py so the
comparison can judge a row without importing the entry point that prints it.
"""
from __future__ import annotations

from dataclasses import dataclass

from languages import FunctionMeasure


@dataclass
class FileMeasure:
    file: str
    language: str
    lines: int
    suppressions: int


@dataclass(frozen=True)
class Thresholds:
    lines: int = 20
    cc: int = 10
    params: int = 3
    file_lines: int = 500
    depth: int = 2


def exceeded(fm: FunctionMeasure, t: Thresholds) -> list[str]:
    out = []
    if fm.lines > t.lines:
        out.append("lines")
    if fm.cc > t.cc:
        out.append("cc")
    if fm.params > t.params:
        out.append("params")
    if fm.depth > t.depth:
        out.append("depth")
    return out
