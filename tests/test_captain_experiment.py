#!/usr/bin/env python3
"""Tests for the captain writer-duel records: scripts/experiment-summary.py and
`agent-context.py --total`.

Both scripts run as subprocesses on temp files: synthetic experiments.jsonl lines in the
record shape of reference/experiment.md, and
subagent transcripts shaped like ~/.claude/projects/*/*/subagents/agent-<id>.jsonl, where
Claude Code writes one line per content block and repeats the message's usage on each.
The real ~/.claude/captain/experiments.jsonl is never read.

Run:  python3 tests/test_captain_experiment.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "plugins" / "captain" / "skills" / "captain" / "scripts"
SUMMARY = SCRIPTS / "experiment-summary.py"
CONTEXT = SCRIPTS / "agent-context.py"
LIGHT, SOL, WORKER = "captain:light-coder", "captain:light-coder-sol", "captain:worker"


def contestant(agent: str, *, finished: bool = True, rounds: int = 1, minutes: float = 10,
               tokens: int = 1000, out_of_scope: list[str] | None = None,
               escalate: bool = False) -> dict:
    return {"agent": agent, "model": "m", "effort": "medium", "finished": finished,
            "rounds": rounds, "findings_per_round": [0] * rounds, "fix_now": 0,
            "out_of_scope_files": out_of_scope or [], "escalate": escalate,
            "minutes": minutes, "tokens": tokens}


def duel(winner: str, a: dict, b: dict, c: dict) -> dict:
    return {"date": "2026-09-30", "repo": "r", "run": "20260930", "task": "ZD1 x",
            "light_test": ["KL1"], "duel_reason": "test",
            "contestants": {"A": a, "B": b, "C": c},
            "winner": winner, "judge_reason": "because", "reviewer": "codex"}


class ExperimentSummaryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "experiments.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, *lines: object) -> None:
        self.path.write_text("".join(
            (line if isinstance(line, str) else json.dumps(line)) + "\n" for line in lines))

    def run_summary(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SUMMARY), *args],
                              capture_output=True, text=True, timeout=30)

    def rows(self, stdout: str) -> dict[str, list[str]]:
        """The per-agent table rows, keyed by agent: the words after the agent name."""
        found = {}
        for line in stdout.splitlines():
            words = line.split()
            if words and words[0].startswith("captain:"):
                found[words[0]] = words[1:]
        return found

    def test_aggregates_per_agent_with_counts_next_to_rates(self):
        self.write(
            duel("A", contestant(LIGHT, rounds=1, minutes=10, tokens=100),
                 contestant(SOL, rounds=3, minutes=20, tokens=300, out_of_scope=["x.py"]),
                 contestant(WORKER, rounds=2, minutes=30, tokens=500)),
            duel("C", contestant(SOL, rounds=1, minutes=40, tokens=500,
                                 out_of_scope=["a", "b"]),
                 contestant(LIGHT, finished=False, rounds=3, minutes=20, tokens=300,
                            escalate=True),
                 contestant(WORKER, rounds=2, minutes=10, tokens=700)))
        result = self.run_summary(str(self.path))
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = self.rows(result.stdout)
        # duels wins win-rate(wins/duels) rounds minutes tokens out-of-scope not-finished escalations
        self.assertEqual(rows[LIGHT], ["2", "1", "50%(1/2)", "2.0", "15.0", "200", "0", "1", "1"])
        self.assertEqual(rows[SOL], ["2", "0", "0%(0/2)", "2.0", "30.0", "400", "3", "0", "0"])
        self.assertEqual(rows[WORKER], ["2", "1", "50%(1/2)", "2.0", "20.0", "600", "0", "0", "0"])
        self.assertIn("duels: 2", result.stdout)

    def test_no_winner_is_counted_and_gives_nobody_a_win(self):
        self.write(duel("none", contestant(LIGHT), contestant(SOL), contestant(WORKER)),
                   duel("B", contestant(LIGHT), contestant(SOL), contestant(WORKER)))
        result = self.run_summary(str(self.path))
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = self.rows(result.stdout)
        self.assertEqual(rows[LIGHT][:3], ["2", "0", "0%(0/2)"])
        self.assertEqual(rows[SOL][:3], ["2", "1", "50%(1/2)"])
        self.assertIn("no winner: 1", result.stdout)

    def test_ties_in_the_table_keep_a_stable_order(self):
        # equal records for all three: same numbers, rows sorted by agent name
        self.write(duel("none", contestant(WORKER), contestant(SOL), contestant(LIGHT)))
        result = self.run_summary(str(self.path))
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = self.rows(result.stdout)
        self.assertEqual(list(rows), sorted([LIGHT, SOL, WORKER]))
        self.assertEqual(len({tuple(row) for row in rows.values()}), 1)

    def test_malformed_lines_are_skipped_and_counted(self):
        good = duel("A", contestant(LIGHT), contestant(SOL), contestant(WORKER))
        self.write("not json", good, "[1, 2]", {"winner": "A"},
                   {**good, "contestants": {"A": "text"}}, "")
        result = self.run_summary(str(self.path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("duels: 1", result.stdout)
        self.assertIn("skipped malformed lines: 4", result.stdout)
        self.assertEqual(self.rows(result.stdout)[LIGHT][:2], ["1", "1"])

    def test_a_bad_number_marks_that_mean_unknown_not_zero(self):
        self.write(duel("A", contestant(LIGHT, tokens=100), contestant(SOL), contestant(WORKER)),
                   duel("A", {**contestant(LIGHT), "tokens": "n/a"}, contestant(SOL),
                        contestant(WORKER)))
        result = self.run_summary(str(self.path))
        self.assertEqual(result.returncode, 0, result.stderr)
        # the mean covers the one measured duel, and says how many it covers
        self.assertEqual(self.rows(result.stdout)[LIGHT][5], "100(1/2)")

    def test_infinity_and_nan_are_not_numbers(self):
        # Codex consensus note: json accepts Infinity and NaN; they must not crash the mean
        self.write(duel("A", contestant(LIGHT, tokens=100), contestant(SOL), contestant(WORKER)))
        with open(self.path, "a") as handle:
            handle.write(json.dumps(duel("A", contestant(LIGHT), contestant(SOL),
                                         contestant(WORKER))).replace('"tokens": 1000',
                                                                      '"tokens": Infinity', 1)
                         .replace('"minutes": 10', '"minutes": NaN', 1) + "\n")
        result = self.run_summary(str(self.path))
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.rows(result.stdout)[LIGHT]
        self.assertEqual((row[4], row[5]), ("10.0(1/2)", "100(1/2)"))

    def test_empty_file_prints_zero_duels(self):
        self.write()
        result = self.run_summary(str(self.path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("duels: 0", result.stdout)

    def test_missing_file_is_exit_2_with_one_line(self):
        result = self.run_summary(str(self.path))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(len(result.stderr.strip().splitlines()), 1)
        self.assertIn(str(self.path), result.stderr)

    def test_directory_is_unreadable_exit_2(self):
        result = self.run_summary(self.tmp.name)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(len(result.stderr.strip().splitlines()), 1)

    def test_too_many_arguments_is_exit_2(self):
        self.assertEqual(self.run_summary("a", "b").returncode, 2)


class AgentContextTotalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.projects = Path(self.tmp.name) / "projects"
        self.subagents = self.projects / "-repo" / "sess" / "subagents"
        self.subagents.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def transcript(self, agent: str, calls: list[tuple[str | None, dict]], blocks: int = 1) -> None:
        """One model call per (message id, usage); `blocks` lines per call, as Claude Code writes."""
        lines = [json.dumps({"type": "user", "isSidechain": True, "message": {"content": "go"}})]
        for message_id, usage in calls:
            message = {"model": "claude-opus-5-5", "usage": usage,
                       "content": [{"type": "text", "text": "x"}]}
            if message_id is not None:
                message["id"] = message_id
            lines += [json.dumps({"type": "assistant", "isSidechain": True, "message": message})
                      ] * blocks
        (self.subagents / f"agent-{agent}.jsonl").write_text("\n".join(lines) + "\nnot json\n")

    def run_context(self, *args: str) -> subprocess.CompletedProcess:
        env = {**os.environ, "CAPTAIN_PROJECTS_DIR": str(self.projects)}
        return subprocess.run([sys.executable, str(CONTEXT), *args], env=env,
                              capture_output=True, text=True, timeout=30)

    def test_total_sums_every_call_default_keeps_the_last(self):
        self.transcript("aduel", [("msg_1", {"input_tokens": 100, "output_tokens": 10}),
                                  ("msg_2", {"input_tokens": 200, "output_tokens": 10})])
        default = self.run_context("aduel")
        self.assertEqual((default.returncode, default.stdout), (0, "aduel 210 tokens 0% keep\n"))
        total = self.run_context("--total", "aduel")
        self.assertEqual(total.returncode, 0, total.stderr)
        self.assertEqual(total.stdout, "aduel 320 tokens total\n")

    def test_total_counts_a_call_once_across_its_content_block_lines(self):
        self.transcript("ablocks", [("msg_1", {"input_tokens": 100, "output_tokens": 10}),
                                    ("msg_2", {"input_tokens": 200, "output_tokens": 10})],
                        blocks=3)
        self.assertEqual(self.run_context("--total", "ablocks").stdout, "ablocks 320 tokens total\n")

    def test_total_counts_calls_without_an_id_each(self):
        self.transcript("anoid", [(None, {"input_tokens": 5}), (None, {"input_tokens": 5})])
        self.assertEqual(self.run_context("--total", "anoid").stdout, "anoid 10 tokens total\n")

    def test_total_skips_bad_records(self):
        self.transcript("abad", [("m1", {"input_tokens": 50}), ("m2", {"input_tokens": False}),
                                 ("m3", {"input_tokens": -1}), ("m4", {})])
        self.assertEqual(self.run_context("--total", "abad").stdout, "abad 50 tokens total\n")

    def test_total_unknown_and_not_found(self):
        self.transcript("anone", [])
        result = self.run_context("--total", "anone", "amissing")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.splitlines(), ["anone unknown", "amissing not found"])

    def test_total_needs_an_agent_id(self):
        self.assertEqual(self.run_context("--total").returncode, 2)
        self.assertEqual(self.run_context("--total", "../x").returncode, 2)
        self.assertEqual(self.run_context("--bogus", "a1").returncode, 2)


if __name__ == "__main__":
    unittest.main()
