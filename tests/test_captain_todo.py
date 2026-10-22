#!/usr/bin/env python3
"""Tests for the captain rule "TODO only with evidence" (TD1, TP1-TP8): the section in
reference/triage.md, the changed round-threshold rows and trap, and the TODO entry reasons in
reference/queue.md.

Run:  python3 tests/test_captain_todo.py
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "plugins" / "captain" / "skills" / "captain"
REFERENCE = SKILL_DIR / "reference"
QUEUE_MD = REFERENCE / "queue.md"
TRIAGE_MD = REFERENCE / "triage.md"

SECTION = "TODO only with evidence (TD1)"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def flat(path: Path) -> str:
    return " ".join(read_text(path).split())


def anchor(heading: str) -> str:
    """GitHub-style anchor of a markdown heading."""
    text = heading.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def section(path: Path, heading: str) -> str:
    text = read_text(path)
    body = text.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]
    return " ".join(body.split())


class TodoSectionTest(unittest.TestCase):

    def test_contents_links_the_section(self):
        text = read_text(TRIAGE_MD)
        self.assertIn(f"\n## {SECTION}\n", text)
        self.assertIn(f"- [{SECTION}](#{anchor(SECTION)})", text)
        self.assertEqual(anchor(SECTION), "todo-only-with-evidence-td1")

    def test_section_carries_every_rule_tp1_to_tp8(self):
        body = section(TRIAGE_MD, SECTION)
        for rule in ("TP1", "TP2", "TP3", "TP4", "TP5", "TP6", "TP7", "TP8"):
            with self.subTest(rule=rule):
                self.assertIn(f"**{rule} ", body)
        self.assertNotIn("TP9", body)

    def test_section_keys_on_evidence(self):
        body = section(TRIAGE_MD, SECTION)
        for needle in (
                "a concrete input, a failing test, an observed failure or a reachable code path",
                "`ACCEPT not confirmed`",
                "only when callers, the schema or enforced validation exclude the input",
                "\"Not seen in today's data\" is not that evidence",
                "`ACCEPT artificial timing or input`",
                "a stale or second tab is not artificial by default",
                "Data loss in normal use, security, and verifier or group test failures keep "
                "their priority",
                "A feature the owner asked for or explicitly deferred stays",
                "never by words such as \"minor\", \"accepted\" or \"polish\"",
                "(implementation, review, merge, group test) fits the last possible hard end "
                "(VR1; no box: it always fits) and R6 permits it",
                "a separate reviewed task in the same run when the owner's scope allows a "
                "behaviour change (PL1, TS1)",
                "one fresh writer with a new hypothesis in every mode",
                "the re-review bound stays 3",
                "owner decision, production or an external system, out of the task's scope, "
                "the review bound, or a time cut with its numbers",
                "make one real attempt at the next operation",
                "No start-up quota probe (R15), no probe loops",
                "never hold a reviewed merge; the R17 agent consolidates them at the end"):
            with self.subTest(needle=needle):
                self.assertIn(needle, body)

    def test_section_ends_with_the_owner_decision_why(self):
        body = section(TRIAGE_MD, SECTION)
        why = body.split("**Why:**", 1)[1]
        for needle in ("the owner's decision, 2026-10-20", "42 captain sessions",
                       "127 TODO entries", "29% were needed", "50% were doable in the box",
                       "16% were unneeded edge cases", "independent Codex check"):
            with self.subTest(needle=needle):
                self.assertIn(needle, why)


class RoundTableAndTrapTest(unittest.TestCase):

    def test_round_rows_do_it_when_the_path_fits(self):
        text = flat(TRIAGE_MD)
        self.assertNotIn("New behaviour or `pre-existing` → TODO.", text)
        self.assertNotIn("`pre-existing` → TODO.", text)
        self.assertNotIn("Tests → one TODO for the loop.", text)
        for needle in (
                "`pre-existing` in scope with evidence → its own task (own round 1) when its "
                "whole path fits the last possible hard end, else TODO with the numbers",
                "out of scope → TODO \"out of the task's scope\" (TP4)",
                "Tests → added in the loop when the whole path fits the last possible hard "
                "end, else one TODO for the loop with the numbers (TP4)",
                "a feature nobody asked for → ACCEPT valid design (TP2)",
                "tests in round 2+ that do not fit (TP4)"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_trap_gets_one_fresh_writer_in_every_mode(self):
        text = flat(TRIAGE_MD)
        self.assertNotIn("A `fix-all` run: first the one extra writer", text)
        self.assertNotIn("In `fix-all`, a mechanism in the trap gets one more", text)
        for needle in (
                "Every run mode, normal and `fix-all`, first: the one extra writer below (NP1)",
                "**One more writer for a trapped mechanism (NP1).** In every run mode",
                "limit plus one re-review timeout",
                "It does not reset the loop's re-review count (at most 3)",
                "in `fix-all` a short time ends in TODO, not in an owner question"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_priority_order_is_kept(self):
        text = flat(TRIAGE_MD)
        self.assertIn("Apply the first that matches: (1) data loss in normal use → FIX NOW; "
                      "(2) a verifier failure → FIX NOW; (3) the trap; (4) the round table.",
                      text)
        self.assertIn("A group test failure (TS1, `reference/parallel.md`) is treated like a "
                      "verifier failure", text)
        self.assertNotIn("Time does not cover it → the owner question", text)


class QueueTodoReasonsTest(unittest.TestCase):

    def test_r18_entry_has_the_closed_reason_list(self):
        body = section(QUEUE_MD, "TODO entry (R18)")
        self.assertIn("<reason: owner decision | production or external system: <name> | "
                      "out of the task's scope | review bound (3 re-reviews) | does not fit: "
                      "needs ~<N> min, <M> min to hard end>", body)
        self.assertIn("Exactly one reason from this closed list (TP6", body)
        self.assertIn("No reason from the list → no TODO entry.", body)
        self.assertNotIn("| ...>", body)

    def test_deferred_finding_entry_has_reason_and_evidence(self):
        body = section(QUEUE_MD, "TODO entry for a deferred finding (R6, R18)")
        for needle in ("reason: <one from the R18 list>",
                       "`kind` is not the reason: both fields are required",
                       "Evidence: <input | failing test | observed failure | code path "
                       "file:line>; review log: <path>",
                       "(only when they do not fit, TP4)",
                       "ACCEPT never goes to TODO"):
            with self.subTest(needle=needle):
                self.assertIn(needle, body)

    def test_end_report_lists_new_entries_with_their_reason(self):
        text = flat(QUEUE_MD)
        self.assertIn("with each new entry and its one-line reason from the TP6 list under it "
                      "(`reference/triage.md`, TODO only with evidence)", text)
        self.assertIn("when added > 0 it is the report's first line", text)


if __name__ == "__main__":
    unittest.main()
