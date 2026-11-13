#!/usr/bin/env python3
"""Check at the end of a captain run (R17) that nothing unfinished stays only in the session.

Usage: python3 check-run-end.py --run-dir=<abs run-state dir> --todo=<abs repo TODO file>

Reads <run-dir>/run.md, <run-dir>/decisions.md (optional) and the TODO file. A TODO ID is two or
three Latin capital letters plus digits ([A-Z]{2,3}\\d+); it "occurs" in the TODO file when it
appears there as a whole word (a heading `## KP7 - ...` or an entry `- **KP7** ...`).

Checks:
  1. rows: every row of the `## Tasks` table in run.md whose State cell does not start with
     `merged` names a TODO ID as `→ <ID>` in its State cell, and that ID occurs in the TODO file.
     Cells split on an unescaped `|` only; an escaped `\\|` stays inside its cell.
  2. decisions: every decisions.md line (with or without a leading `- `) whose class (the second
     `|` field) is `TODO`, e.g. `- ZD1 r3 F2 | TODO owner decision → KP12 | ...`, carries
     `→ <ID>` anywhere in the line, and that ID occurs in the TODO file. A missing decisions.md
     is no problem. A line with a `source: owner` field and a `status:` field that does not
     start with `done ` (an owner decision not done, e.g.
     `- RSH3 | scope: run | source: owner | "..." | status: deferred → KP12`) is checked the same
     way and counted with the TODO decisions. A `source: owner` line without `status:` is a
     standing owner rule, not work: it is not checked.
  3. phase: a non-table, non-empty line inside `## Tasks` that names a phase or wave
     (Wave|Phase, case-insensitive) and names no ZD<n> that is a row of the table.
  4. processes: every row of the first table under `## Processes` (columns
     `PID | Start time | Working dir | Agent`) whose PID is alive and whose live start time
     equals the row's `Start time` is still running: `PROCESS <PID>`, a problem. A dead PID, or
     a live PID with another start time (a reused PID, not ours), gives nothing. A row that
     holds `kept: owner` in any of its cells (the Agent cell or a trailing note cell) is left
     running for the owner on purpose: a live one gives `KEPT <PID>`, not a problem. A row
     whose PID cell holds no number is skipped. No `## Processes` section, or no table under
     it, is no problem.
     The live start time comes from `ps -o lstart= -p <PID>`, read twice: with LC_ALL=C and
     in the caller's own locale, so a row written by a `ps` without LC_ALL=C (localized day
     and month names) still matches; the row matches when either reading does. The row's
     `Start time` is accepted in the R14 `ps -axo pid,lstart,command` format
     (`Fri Oct 30 14:01:56 2026`), without the weekday (`Oct 30 14:01:56 2026`) or as ISO
     (`2026-10-30 14:01:56`, `2026-10-30T14:01:56`), local time, to the second; runs of
     spaces and surrounding backticks do not matter. A start time in none of these formats
     matches only when it equals the `ps` text after the space runs are collapsed.

  5. cowboy (KB4, KB6, KB8): the guard's cowboy records of the repository that holds the TODO
     file (<state dir>/cowboy/, $CAPTAIN_STATE_DIR or ~/.claude/captain/sessions; the TODO
     file's directory names the repository). For every record with untested cowboy commits (no
     green record covers them): a local branch other than the cowboy branch and its own agent
     branches that holds one gives `COWBOY <branch> — ...`, a problem, in every run. In a
     cowboy run (a run.md line `Mode: ... cowboy ...`, e.g. `- Mode: cowboy, tests: night`) the
     TODO file must also name the branch (the KB6 entry): `MISSING cowboy <branch> — ...`
     when it does not, `UNTESTED <branch> — ...` (not a problem) when it does. An unreadable
     record is a problem. No repository, or no record, is no problem.

Output: first one line `KEPT <PID>` per live `kept: owner` row and one `UNTESTED <branch>` per
  untested cowboy branch with its TODO entry, then one line per problem,
  MISSING <rows|decisions|phase|cowboy> <ID, line or branch> — <what is missing>
  PROCESS <PID>
  COWBOY <branch> — <where its untested commits are>
and a last line `PASS: ...` or `FAIL: <n> problem(s)`.
Exit codes: 0 clean; 1 problems; 2 bad input (no run.md, no `## Tasks` table, no TODO file).
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

TODO_ID = r"[A-Z]{2,3}\d+"
ARROW_ID = re.compile(r"→\s*(" + TODO_ID + r")(?!\w)")
PHASE_WORD = re.compile(r"\b(?:Wave|Phase)", re.IGNORECASE)
TASK_ID = re.compile(r"(?<!\w)(ZD\d+)(?!\w)")
SEPARATOR = re.compile(r"^\|[\s:|-]+\|?$")
DECISION_CLASS_TODO = re.compile(r"^TODO(?![\w.])")
OWNER_SOURCE = "source: owner"
STATUS_PREFIX = "status:"
UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
# `## Processes` ends at a level 1 or 2 heading; `###` stays inside (as in cleanup-run.py).
SECTION_END = re.compile(r"#{1,2}(?:\s|$)")
KEPT_MARK = "kept: owner"
PID_NUMBER = re.compile(r"\d+")
START_FORMATS = ("%a %b %d %H:%M:%S %Y", "%b %d %H:%M:%S %Y",
                 "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


class BadInput(Exception):
    pass


def cells(line: str) -> list[str]:
    """The cells of a markdown table line, without the outer pipes."""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip() for cell in UNESCAPED_PIPE.split(body)]


def section_lines(run_md: str, heading: str, level_1_ends: bool = False) -> list[str] | None:
    """The lines under `heading` up to the next `## ` heading, or None without the heading.
    With `level_1_ends` (only `## Processes`, as in cleanup-run.py) the section ends at the next
    `#` or `##` heading; a `###` subheading stays inside either way."""
    lines = run_md.splitlines()
    for start, line in enumerate(lines):
        if line.strip() == heading:
            section = []
            for following in lines[start + 1:]:
                if (SECTION_END.match(following.strip()) if level_1_ends
                        else following.startswith("## ")):
                    break
                section.append(following)
            return section
    return None


def tasks_section(run_md: str) -> list[str]:
    section = section_lines(run_md, "## Tasks")
    if section is None:
        raise BadInput("run.md has no `## Tasks` heading")
    return section


def parse_table(section: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    """The first table of the section as rows, and the section's non-table lines."""
    rows: list[dict[str, str]] = []
    prose: list[str] = []
    header: list[str] | None = None
    table_done = False
    in_table = False
    for line in section:
        if line.lstrip().startswith("|"):
            if table_done:
                continue
            if header is None:
                header = cells(line)
                in_table = True
            elif not SEPARATOR.match(line.strip()):
                rows.append(dict(zip(header, cells(line))))
            continue
        if in_table:
            in_table, table_done = False, True
        prose.append(line)
    if header is None:
        raise BadInput("`## Tasks` has no table")
    for column in ("ID", "State"):
        if column not in header:
            raise BadInput(f"`## Tasks` table has no `{column}` column")
    return rows, prose


def occurs(todo_id: str, todo_text: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(todo_id) + r"(?!\w)", todo_text) is not None


def check_rows(rows: list[dict[str, str]], todo_text: str) -> list[str]:
    problems = []
    for row in rows:
        state = row.get("State", "")
        if state.startswith("merged"):
            continue
        task = row.get("ID", "") or "?"
        found = ARROW_ID.search(state)
        if not found:
            problems.append(f"MISSING rows {task} — no `→ <TODO ID>` in State `{state}`")
        elif not occurs(found.group(1), todo_text):
            problems.append(f"MISSING rows {task} — {found.group(1)} is not in the TODO file")
    return problems


def is_open_owner_decision(fields: list[str]) -> bool:
    """A `source: owner` line with a `status:` field that is not `done <sha>`. A standing
    owner rule carries no `status:` and is never work to sweep."""
    if OWNER_SOURCE not in fields:
        return False
    status = next((field for field in fields if field.startswith(STATUS_PREFIX)), None)
    return status is not None and not status[len(STATUS_PREFIX):].strip().startswith("done ")


def check_decisions(decisions_md: str, todo_text: str) -> tuple[list[str], int]:
    problems, count = [], 0
    for line in decisions_md.splitlines():
        text = line.strip()
        if text.startswith("- "):
            text = text[2:]
        fields = [field.strip() for field in text.split("|")]
        todo_class = len(fields) >= 2 and DECISION_CLASS_TODO.match(fields[1])
        if not todo_class and not is_open_owner_decision(fields):
            continue
        count += 1
        name = fields[0] or line.strip()
        found = ARROW_ID.search(text)
        if not found:
            what = "line" if todo_class else "line, an owner decision not done"
            problems.append(f"MISSING decisions {name} — no `→ <TODO ID>` in the {what}")
        elif not occurs(found.group(1), todo_text):
            problems.append(f"MISSING decisions {name} — {found.group(1)} is not in the TODO file")
    return problems, count


def check_phases(prose: list[str], row_ids: set[str]) -> list[str]:
    problems = []
    for line in prose:
        text = line.strip()
        if not text or not PHASE_WORD.search(text):
            continue
        if row_ids.intersection(TASK_ID.findall(text)):
            continue
        problems.append(f"MISSING phase {text} — a phase or wave with no ZD row in the table")
    return problems


def process_rows(run_md: str) -> list[list[str]]:
    """The cells of each body row of the first table under `## Processes`."""
    rows: list[list[str]] = []
    seen_header = False
    for line in section_lines(run_md, "## Processes", level_1_ends=True) or []:
        if not line.lstrip().startswith("|"):
            if seen_header:
                break
            continue
        if not seen_header:
            seen_header = True
        elif not SEPARATOR.match(line.strip()):
            rows.append(cells(line))
    return rows


def ps_lstart(pid: int, env: dict[str, str]) -> str | None:
    """The `ps` lstart text of a live PID in the locale of `env`, or None when it does not run."""
    result = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)],
                            capture_output=True, text=True, env=env)
    text = result.stdout.strip()
    return text if result.returncode == 0 and text else None


def live_starts(pid: int) -> list[str]:
    """The lstart texts of a live PID in the C locale and the caller's locale; empty when dead."""
    readings = (ps_lstart(pid, dict(os.environ, LC_ALL="C")), ps_lstart(pid, dict(os.environ)))
    return [text for text in readings if text is not None]


def start_key(text: str) -> datetime | str:
    """A comparable start time: a datetime for a known format, else the collapsed text."""
    collapsed = " ".join(text.strip().strip("`").split())
    for fmt in START_FORMATS:
        try:
            return datetime.strptime(collapsed, fmt)
        except ValueError:
            continue
    return collapsed


def check_processes(run_md: str) -> tuple[list[str], list[str]]:
    """PROCESS problems for live rows of this run, KEPT lines for live `kept: owner` rows."""
    problems, kept = [], []
    for row in process_rows(run_md):
        found = PID_NUMBER.search(row[0]) if row else None
        if not found or len(row) < 2:
            continue
        pid = int(found.group())
        recorded = start_key(row[1])
        if not any(start_key(started) == recorded for started in live_starts(pid)):
            continue
        if any(KEPT_MARK in cell for cell in row):
            kept.append(f"KEPT {pid}")
        else:
            problems.append(f"PROCESS {pid}")
    return problems, kept


GUARD = Path(__file__).resolve().parents[3] / "hooks" / "guard.py"
COWBOY_MODE = re.compile(r"^\s*(?:-\s*)?Mode:.*\bcowboy\b", re.IGNORECASE | re.MULTILINE)


def load_guard():
    spec = importlib.util.spec_from_file_location("captain_guard", GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_cowboy(run_md: str, todo: Path, todo_text: str) -> tuple[list[str], list[str]]:
    """Check 5: (problems, UNTESTED lines) over the guard's cowboy records of the TODO file's
    repository. The guard owns the record format and the untested-commit rule."""
    guard = load_guard()
    directory = str(todo.resolve().parent)
    identity = guard.repo_identity(directory)
    if identity is None:
        return [], []
    try:
        records = guard.read_cowboy(identity[1])
    except guard.CowboyUnreadable as error:
        return [f"COWBOY ? — the cowboy record is unreadable ({error})"], []
    cowboy_run = COWBOY_MODE.search(run_md) is not None
    problems, untested_lines = [], []
    for branch, record in sorted(records.items()):
        untested = guard.untested_commits(directory, branch, record)
        if untested is None:
            problems.append(f"COWBOY {branch} — git cannot list its untested commits")
            continue
        if not untested:
            continue
        holders = set()
        for commit in untested:
            out = guard.git_out(directory, "for-each-ref", "--format=%(refname:short)",
                                "--contains", commit, "refs/heads")
            holders.update((out or "").split())
        for holder in sorted(holders):
            if not guard.own_branch(holder, branch):
                problems.append(f"COWBOY {branch} — `{holder}` holds untested cowboy commits "
                                "(merged without a green record)")
        if not cowboy_run:
            continue
        if occurs(branch, todo_text):
            untested_lines.append(f"UNTESTED {branch} — {len(untested)} cowboy commit(s) not "
                                  "tested; the TODO entry names the branch")
        else:
            problems.append(f"MISSING cowboy {branch} — {len(untested)} untested cowboy "
                            "commit(s) and no TODO entry names the branch (KB6)")
    return problems, untested_lines


def read(path: Path, what: str) -> str:
    if not path.is_file():
        raise BadInput(f"no {what} at {path}")
    return path.read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--todo", required=True)
    args = parser.parse_args(argv)
    run_dir = Path(args.run_dir)
    try:
        run_md = read(run_dir / "run.md", "run.md")
        rows, prose = parse_table(tasks_section(run_md))
        todo_text = read(Path(args.todo), "TODO file")
    except BadInput as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    decisions_path = run_dir / "decisions.md"
    decisions_md = decisions_path.read_text(encoding="utf-8") if decisions_path.is_file() else ""

    problems = check_rows(rows, todo_text)
    decision_problems, todo_decisions = check_decisions(decisions_md, todo_text)
    problems += decision_problems
    problems += check_phases(prose, {row.get("ID", "") for row in rows})
    process_problems, kept = check_processes(run_md)
    problems += process_problems
    cowboy_problems, untested = check_cowboy(run_md, Path(args.todo), todo_text)
    problems += cowboy_problems
    for line in kept + untested + problems:
        print(line)
    if problems:
        print(f"FAIL: {len(problems)} problem(s)")
        return 1
    open_rows = sum(1 for row in rows if not row.get("State", "").startswith("merged"))
    print(f"PASS: {len(rows)} rows ({open_rows} not merged), {todo_decisions} TODO decision(s), "
          "every open item has a TODO ID in the TODO file")
    return 0


if __name__ == "__main__":
    sys.exit(main())
