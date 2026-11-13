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
                "the re-review bound stays 3, or 5 only after the review-bound panel",
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
                "It does not reset the loop's re-review count (at most 3, or 5 after the "
                "review-bound panel)",
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
                      "out of the task's scope | review bound (3 re-reviews) | review bound (5 re-reviews) "
                      "| does not fit: "
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


class PhaseRowsTest(unittest.TestCase):
    """KP8: every plan phase is a `## Tasks` row from the start, never a prose line."""

    def test_skill_start_step_and_r18_name_the_phase_rule(self):
        text = flat(SKILL_DIR / "SKILL.md")
        for needle in ("every phase of the plan or handover a row, never prose",
                       "No box: nothing goes to TODO for time. A planned phase is done in "
                       "the run, deferred only by the owner or R6/TP6.",
                       "28.10: a handover's wave 2 stayed prose: not done, not in TODO."):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_queue_template_state_cell_is_exact(self):
        self.assertIn("| todo / queued / running / review k/3 (k/5 after a review-bound "
                      "panel) / merged / cut → <TODO ID> |", flat(QUEUE_MD))

    def test_queue_tasks_paragraph_has_the_mechanics(self):
        text = flat(QUEUE_MD)
        for needle in ("Every phase or wave of the plan or handover is rows here from the "
                       "start, never a prose line.",
                       "gets one placeholder row now (state `todo`, `After` = the earlier "
                       "rows) and is split into its own rows when it starts.",
                       "only the owner defers it by choice → state `cut → <TODO ID>`, "
                       "reason `owner decision` (R18).",
                       "The R6 review bound and trap and the other TP6 reasons still send "
                       "open work to TODO."):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_parallel_plan_points_to_the_placeholder_row(self):
        self.assertIn("a phase whose split waits is one placeholder row until it starts",
                      flat(REFERENCE / "parallel.md"))


class ReviewBoundPanelTest(unittest.TestCase):
    """KP10: the bound stays 3 re-reviews; 4-5 only after a 3amigos panel; the trap first."""

    SKILL_MD = SKILL_DIR / "SKILL.md"
    CONSENSUS_MD = REFERENCE / "consensus.md"
    PROMPTS_MD = REFERENCE / "prompts.md"
    PARALLEL_MD = REFERENCE / "parallel.md"

    def test_skill_r6_names_the_panel_and_the_owner_words(self):
        text = flat(self.SKILL_MD)
        r6 = text.split("### R6 — The review loop", 1)[1].split("### R7", 1)[0]
        body, why = r6.split("**Why:**", 1)
        for needle in ("at most 3 re-reviews",
                       "FIX NOW of a critical impact left after the 3rd, outside the trap → "
                       "a 3amigos panel: 2 more or TODO."):
            with self.subTest(needle=needle):
                self.assertIn(needle, body)
        for needle in ("29.10.2026", "up to 5 reviews", "only after a 3amigos assessment"):
            with self.subTest(needle=needle):
                self.assertIn(needle, why)

    def test_triage_has_the_panel_mechanics(self):
        body = flat(TRIAGE_MD).split("## When the loop stops", 1)[1].split("## The register", 1)[0]
        for needle in (
                "The bound of 3 re-reviews stays.",
                "**The review-bound panel.** After the 3rd re-review, when triage still leaves "
                "FIX NOW findings with impact `data loss`, `security`, `build/test broken` or "
                "`wrong result`, main runs one 3amigos panel",
                '"2 more rounds or TODO"',
                "The trap keeps its priority",
                "never to the panel",
                "the open FIX NOW findings with their triage lines, the new real defects per "
                "round",
                "the fix-of-fix count",
                "Majority yes → re-reviews 4–5",
                "→ TODO, reason `review bound (3 re-reviews)`",
                "One panel per loop. After the 5th re-review the open findings go to TODO, "
                "reason `review bound (5 re-reviews)`; no second panel.",
                "Present mode: one line to the owner, no question",
                "the owner, 2026-10-29"):
            with self.subTest(needle=needle):
                self.assertIn(needle, body)

    def test_trap_comes_before_the_panel_in_the_priority(self):
        text = flat(TRIAGE_MD)
        self.assertIn("At the review bound the trap also comes before the review-bound panel",
                      text)
        self.assertIn("(at most 3, or 5 after the review-bound panel)", text)
        self.assertIn("its own re-review bound (3, or 5 after the review-bound panel)", text)
        self.assertNotIn("its own 3 re-reviews", text)

    def test_queue_has_both_reasons_and_the_panel_line(self):
        text = flat(QUEUE_MD)
        self.assertIn("review bound (3 re-reviews) | review bound (5 re-reviews)", text)
        self.assertNotIn("review bound (3 re-reviews) | does not fit", text)
        self.assertIn("| tier: full | scope: run | source: agent | review bound | ZD1 after r4 (3rd re-review):", text)
        self.assertIn("result: A re-reviews 4–5 (majority)", text)
        self.assertIn("FIX NOW open | options: A re-reviews 4–5 / B TODO |", text)
        self.assertIn("| panel: tmp/captain/<run>/amigos-<ID>/", text)

    def test_consensus_tiers_carry_the_panel(self):
        text = flat(self.CONSENSUS_MD)
        for needle in ("| Review bound (R6) | after the 3rd re-review",
                       'full consensus (3amigos panel) main runs: "2 more rounds or TODO"',
                       "present: one line, no question",
                       "**Review-bound panel** (R6",
                       "A trapped mechanism goes to the trap, never to this panel.",
                       "the complex tiers, the review-bound panel and away-mode product "
                       "questions only"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_prompts_and_parallel_use_the_variable_bound(self):
        prompts = flat(self.PROMPTS_MD)
        self.assertNotIn("round <k>/3", prompts)
        self.assertIn("In `round <k>/<n>`, `<n>` is the re-review bound: 3, or 5 after the "
                      "review-bound panel", prompts)
        for needle in ("round <k>/<n>) are in", "Fix now, round <k>/<n>:",
                       "count does not reset (round <k>/<n>)."):
            with self.subTest(needle=needle):
                self.assertIn(needle, prompts)
        self.assertIn("R6 bounds re-reviews only by their count (3, or 5 after the review-bound "
                      "panel).", flat(self.PARALLEL_MD))


if __name__ == "__main__":
    unittest.main()
