#!/usr/bin/env python3
"""Print per-agent numbers from the captain writer-duel records.

Usage: python3 experiment-summary.py [<experiments.jsonl>]

Reads ~/.claude/captain/experiments.jsonl (or the file given), one JSON object per duel:
`contestants` maps a letter to {agent, finished, rounds, minutes, tokens,
out_of_scope_files, escalate, ...} and `winner` is a letter or "none". Prints one row per
contestant agent (a `captain:*` agent type), sorted by name:

  agent  duels  wins  win-rate  rounds  minutes  tokens  out-of-scope  not-finished  escalations

- win-rate is `<percent>%(<wins>/<duels>)`: the count stands next to every rate, since a run
  holds only a few duels.
- rounds, minutes and tokens are means over the duels where the number is a valid count;
  when some duels lack it, the mean is followed by `(<measured>/<duels>)`, and `-` means
  none had it.
- out-of-scope is the total number of files touched outside the owned list; not-finished
  and escalations count duels.

It computes only and draws no conclusion: routing changes are the owner's decision.
Lines that are not a duel record (bad JSON, no `contestants` object, a contestant without
an `agent`) are skipped and counted; blank lines are ignored.

Exit codes: 0 printed; 2 bad arguments or the file is missing or unreadable.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

DEFAULT = Path.home() / ".claude" / "captain" / "experiments.jsonl"
NO_WINNER = "none"
MEANS = ("rounds", "minutes", "tokens")
HEADER = ("agent", "duels", "wins", "win-rate", "rounds", "minutes", "tokens",
          "out-of-scope", "not-finished", "escalations")


def is_number(value: object) -> bool:
    # a bool is not a count, and neither is a negative, NaN or Infinity (json accepts both)
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def contestants(record: object) -> list[dict] | None:
    """The record's contestants with their letters; None when it is not a duel record."""
    if not isinstance(record, dict) or not isinstance(record.get("contestants"), dict):
        return None
    found = []
    for letter, entry in record["contestants"].items():
        if not isinstance(entry, dict) or not isinstance(entry.get("agent"), str) \
                or not entry["agent"]:
            return None
        found.append({**entry, "letter": letter})
    return found or None


def out_of_scope(entry: dict) -> int:
    files = entry.get("out_of_scope_files")
    if isinstance(files, list):
        return len(files)
    return files if type(files) is int and files >= 0 else 0


class Tally:
    def __init__(self) -> None:
        self.duels = self.wins = self.outside = self.not_finished = self.escalations = 0
        self.sums = {key: 0.0 for key in MEANS}
        self.measured = {key: 0 for key in MEANS}

    def add(self, entry: dict, won: bool) -> None:
        self.duels += 1
        self.wins += won
        self.outside += out_of_scope(entry)
        self.not_finished += entry.get("finished") is False
        self.escalations += entry.get("escalate") is True
        for key in MEANS:
            if is_number(entry.get(key)):
                self.sums[key] += entry[key]
                self.measured[key] += 1

    def mean(self, key: str) -> str:
        measured = self.measured[key]
        if not measured:
            return "-"
        value = self.sums[key] / measured
        text = f"{round(value)}" if key == "tokens" else f"{value:.1f}"
        return text if measured == self.duels else f"{text}({measured}/{self.duels})"

    def row(self, agent: str) -> list[str]:
        rate = f"{self.wins * 100 // self.duels}%({self.wins}/{self.duels})"
        return [agent, str(self.duels), str(self.wins), rate,
                *(self.mean(key) for key in MEANS),
                str(self.outside), str(self.not_finished), str(self.escalations)]


def summarize(lines: list[str]) -> tuple[dict[str, Tally], int, int, int]:
    """Per-agent tallies, the number of duels, of duels with no winner, of skipped lines."""
    tallies: dict[str, Tally] = {}
    duels = no_winner = skipped = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        entries = contestants(record)
        if entries is None:
            skipped += 1
            continue
        duels += 1
        winner = record.get("winner")
        if not any(entry["letter"] == winner for entry in entries):
            no_winner += 1
        for entry in entries:
            tallies.setdefault(entry["agent"], Tally()).add(entry, entry["letter"] == winner)
    return tallies, duels, no_winner, skipped


def table(rows: list[list[str]]) -> str:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip()
                     for row in rows)


def main(argv: list[str]) -> int:
    if len(argv) > 1 or (argv and argv[0].startswith("-")):
        print("usage: experiment-summary.py [<experiments.jsonl>]", file=sys.stderr)
        return 2
    path = Path(argv[0]) if argv else DEFAULT
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        print(f"experiment-summary: cannot read {path}: {error.strerror or error}",
              file=sys.stderr)
        return 2
    tallies, duels, no_winner, skipped = summarize(lines)
    print(f"duels: {duels}  no winner: {no_winner}  skipped malformed lines: {skipped}")
    if tallies:
        print(table([list(HEADER), *(tallies[agent].row(agent) for agent in sorted(tallies))]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
