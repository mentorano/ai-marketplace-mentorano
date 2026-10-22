#!/usr/bin/env python3
"""Tests for the captain parallel plan (PL1), the informative time box (VR1) and the test
groups (TS1): reference/parallel.md and the lines in health.md, queue.md, prompts.md,
triage.md and agents/light-coder.md that carry them.

Run:  python3 tests/test_captain_parallel.py
"""
from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "plugins" / "captain" / "skills" / "captain"
REFERENCE = SKILL_DIR / "reference"
PARALLEL_MD = REFERENCE / "parallel.md"
HEALTH_MD = REFERENCE / "health.md"
QUEUE_MD = REFERENCE / "queue.md"
PROMPTS_MD = REFERENCE / "prompts.md"
TRIAGE_MD = REFERENCE / "triage.md"
LIGHT_CODER_MD = ROOT / "plugins" / "captain" / "agents" / "light-coder.md"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def flat(path: Path) -> str:
    return " ".join(read_text(path).split())


def anchor(heading: str) -> str:
    """GitHub-style anchor of a markdown heading."""
    text = heading.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


class ParallelReferenceTest(unittest.TestCase):

    def test_title_and_contents_anchors_match_the_headings(self):
        text = read_text(PARALLEL_MD)
        self.assertTrue(text.startswith(
            "# parallel - the parallel plan, test groups, the time box\n"))
        headings = re.findall(r"^## (.+)$", text, re.M)
        self.assertEqual(headings[0], "Contents")
        links = re.findall(r"^- \[(.+?)\]\(#(.+?)\)$", text, re.M)
        self.assertEqual([title for title, _ in links], headings[1:])
        for title, link in links:
            with self.subTest(section=title):
                self.assertEqual(link, anchor(title))

    def test_every_section_ends_with_a_why_line(self):
        text = read_text(PARALLEL_MD)
        sections = re.split(r"^## ", text, flags=re.M)[2:]
        self.assertGreaterEqual(len(sections), 10)
        for section in sections:
            with self.subTest(section=section.splitlines()[0]):
                # the last paragraph holds the **Why:** line (it may wrap, no new paragraph)
                last = section.strip().split("\n\n")[-1]
                lines = [line.strip() for line in last.splitlines()]
                why = [i for i, line in enumerate(lines) if line.startswith("**Why:**")]
                self.assertTrue(why, "the last paragraph has no **Why:** line")
                self.assertFalse(any(line.startswith("**") for line in lines[why[-1] + 1:]),
                                 "text follows the **Why:** line")

    def test_parallel_plan_has_the_columns_the_pair_table_and_what_stays_serial(self):
        text = flat(PARALLEL_MD)
        for needle in ("`Group`", "`After`", "`After: ZDn — <what it needs>`",
                       "Launch every task whose `After` is met at once",
                       "Serial work needs a reason in `After`",
                       "There is no fixed cap on parallel writers",
                       "| Disjoint files | `shared-multi` (declared, disjoint) or `worktree` | parallel |",
                       "`worktree` + the integration agent at merge",
                       "`After: ZDn — both rewrite <function / lines>` or `— same <lockfile / migration>`",
                       "Test runs that share a resource: a test DB, a port, a container, a build directory",
                       "the locked `.git/config` retry in the R3 frame stays",
                       "waits on an owner answer"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_time_box_has_box_end_hard_end_and_the_extensions(self):
        text = flat(PARALLEL_MD)
        for needle in ("`Box end` = start + box.", "`Hard end` = start + 1.3 × box",
                       "park = hard end − 10% of the box, at least 5 min before it",
                       "The one-shot `box-end` timer prints one status line",
                       "`42 of 120 minutes gone (+36 tolerance); 7 of 12 tasks done (58%); ZD3 running (12/35 min).`",
                       "Hard end moves by +30% of the box. At most 3 extensions per run.",
                       "Ceiling without outages: start + 2.2 × box",
                       "The done share counts the `## Tasks` rows of `run.md`: done = `merged`",
                       "A total of 0 (no plan yet, or every row cut) leaves the part out.",
                       "`VRn | extension k/3 | open: ZD3, ZD5`",
                       "No open work → no extension: R17.",
                       "It starts no new scope.",
                       "`does not fit: needs ~40 min, 25 min to hard end`",
                       "\"To be safe\" is not a reason.",
                       "With a box, the last hard end (after the extensions and outages) is a hard stop in both modes"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_outage_is_measured_and_strict_mode_keeps_an_exact_end(self):
        text = flat(PARALLEL_MD)
        for needle in ("Main measures it, never estimates it.",
                       "`Last check: <HH:MM>`", "more than 20 min between two checks",
                       "`ECONNRESET`", "`<from>–<to>, <N> min, evidence: <...>`",
                       "`outage_min`", "in every time mode",
                       "`time: strict — <reason>`", "`time: normal — <reason>`",
                       "Hard end = box end: no +30% and no work extensions. Only the outage extension applies.",
                       "The argument word `strict` sets it directly."):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_worked_example_from_ten_oclock(self):
        text = read_text(PARALLEL_MD)
        self.assertIn("## Worked example - /captain 2h from 10:00", text)
        for needle in ("| Box end (`box-end` timer) | 12:00 | 12:00 |",
                       "12:36, park 12:24", "13:12, park 13:00", "13:48, park 13:36",
                       "14:24, park 14:12", "12:00, park 11:48"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_test_groups_flow_and_full_build(self):
        text = flat(PARALLEL_MD)
        for needle in ("**Writers run nothing**, in every mode: no tests, no build, no compile check.",
                       "When every task of the group is `merged` or `cut` (and every contract producer the group row names, PL2, is merged), one `captain:runner`",
                       "logged to a timestamped file under `tmp/claude-logs/`",
                       "A failure is an observed fact, like a verifier failure: FIX NOW in every round",
                       "by the files in the group's merge range",
                       "The fix gets one delta review of the fix commit only",
                       "Two failed reruns of the same test → the R6 trap rules,",
                       "waits for a green group run",
                       "runs once on the feature branch before the first push",
                       "Two group runs run in parallel only when they share no resource",
                       "A `cut` task closes its place in the group",
                       "a clean temporary worktree at that SHA",
                       "then the same full-build command. The push waits for a green full build.",
                       "the R6 trap rules, which then win over FIX NOW",
                       "**One time boundary.**",
                       "a group in `## Groups` with merged tasks whose test run"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_no_person_or_repo_names(self):
        text = read_text(PARALLEL_MD)
        for name in ("Ivan", "Иван", "mentorano", "ai-marketplace"):
            with self.subTest(name=name):
                self.assertNotIn(name, text)


class TimerAndRunStateTest(unittest.TestCase):

    def test_health_timers_follow_the_hard_end(self):
        text = flat(HEALTH_MD)
        for needle in ("| box-end | with a box only: box end (start + box), once; strict mode: none, the deadline covers it |",
                       "| park | with a box only: the current `Hard end` − 10% of the box, at least 5 min before it, in both time modes |",
                       "| deadline | with a box only: the current `Hard end` (first normal: start + 1.3 × box; strict: box end; outages and extensions move it) |",
                       "fallback: `TaskStop` the old `sleep` task ids",
                       "A signal of an earlier, moved time is stale: ignore it.",
                       "`date`. First the outage:",
                       "box end 14:32, hard end 14:41", "park 14:36", "Strict: park 14:27, deadline 14:32.",
                       "With a box, re-arm park and deadline on each work extension and each recorded outage",
                       "**On box end:** print one status line",
                       "a work extension instead (`reference/parallel.md`): no park signal",
                       "Then write `Last check: <HH:MM>` to `run.md`.",
                       "a gap of more than 20 min since the previous `Last check:` while an agent runs is an outage candidate",
                       "Compare work left with the time to the current `Hard end`. Before a cut, count the work extensions left",
                       "`42 of 120 minutes gone (+36 tolerance); 7 of 12 tasks done (58%); ZD3 running (12/35 min).`",
                       "the group's runner runs the tests after the group's last merge"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        self.assertNotIn("a runner runs the tests on the merged head", text)

    def test_health_keeps_the_existing_needles(self):
        text = flat(HEALTH_MD)
        for needle in ("## The 15-minute check - one status line (R13)",
                       "A blank health id stays blank", "explicit exception to R12",
                       "One `stat` per Bash call", "only the owner's `!` commands wait"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_run_md_template_has_the_time_fields_groups_and_outages(self):
        text = read_text(QUEUE_MD)
        template = re.search(r"## run\.md\n\n```markdown\n(.*?)\n```", text, re.S).group(1)
        for needle in ("Box: <N> min (given) | none   time: normal | strict — <reason> (a box only)",
                       "- Start: <HH:MM>   Box end: <HH:MM>   Hard end: <HH:MM>",
                       "Park: <HH:MM>   Deadline: <HH:MM>",
                       "- Last check: <HH:MM>",
                       "| box-end | cron / sleep | <id> |",
                       "| ID | Task | Group | Touches | After | Agent | State |",
                       "## Groups", "| Group | Test command | Shared resource | Tasks | State |",
                       "## Outages", "- <from>–<to>, <N> min, evidence: <"):
            with self.subTest(needle=needle):
                self.assertIn(needle, template)

    def test_queue_decisions_todo_and_report_carry_the_numbers(self):
        text = flat(QUEUE_MD)
        for needle in ("- VR3 | extension 1/3 | open: ZD3, ZD5",
                       "does not fit: needs ~<N> min, <M> min to hard end",
                       "with a box, work extensions used (`<k>/3`); outage minutes",
                       '"extensions": 1, "outage_min": 0',
                       "`extensions` is the count of work extensions (0-3; 0 with no box)",
                       "The group's runner runs the group's tests after the group's last merge"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        self.assertNotIn("A runner runs the tests on the merged head first", text)


class WritersRunNoTestsTest(unittest.TestCase):

    def test_r3_frame_names_the_group_runner_and_the_hard_end(self):
        text = flat(PROMPTS_MD)
        for needle in ('e.g. "commit on <branch>; the group runner runs the tests"',
                       "Writers, every mode (TS1): run no tests, no build, no compile check; "
                       "the group's runner runs them after the group's last merge.",
                       "Hard time limit: finish within <N> minutes.",
                       "Park time (absolute): <HH:MM>. Hard end (absolute): <HH:MM>.",
                       "Run no tests: the group's runner runs them (TS1).",
                       "Main may send you a later park time and hard end; the latest message wins."):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        self.assertNotIn("the designated test agent runs them", text)
        self.assertNotIn('"tests in <file> pass, logged; commit on <branch>"', text)

    def test_group_test_prompt_template(self):
        text = read_text(PROMPTS_MD)
        self.assertIn("## Group test prompt (TS1) - to a `captain:runner`", text)
        self.assertIn("(#group-test-prompt-ts1---to-a-captainrunner)", text)
        body = " ".join(text.split("## Group test prompt (TS1)", 1)[1].split("\n## ", 1)[0].split())
        for needle in ("Run the tests of group <group> on the merged head <sha>",
                       "./tmp/claude-logs/group-<group>-$(date +%Y%m%d-%H%M%S).log",
                       "pass or fail", "each failing test, with its error line",
                       "mapped to the group's merge range", "<ZDn: files> per task"):
            with self.subTest(needle=needle):
                self.assertIn(needle, body)

    def test_triage_treats_a_group_failure_like_a_verifier_failure(self):
        text = flat(TRIAGE_MD)
        self.assertIn("A group test failure (TS1, `reference/parallel.md`) is treated like a "
                      "verifier failure: an observed fact, FIX NOW in every round", text)
        self.assertIn("the group's runner runs the tests after the group's last merge", text)
        self.assertNotIn("then a runner runs the tests on the merged head", text)
        self.assertIn("With a box, time does not cover it → TODO with the reason \"does not fit: "
                      "needs ~<N> min, <M> min to hard end\", in both modes.", text)
        self.assertIn("after two failed reruns of the same test, the trap wins over FIX NOW", text)
        self.assertNotIn("does not fit the box", text)

    def test_light_coder_done_line_points_to_the_group_runner(self):
        text = flat(LIGHT_CODER_MD)
        self.assertIn("Done means the commit is on your branch; the group runner runs the "
                      "task's check command (TS1).", text)
        self.assertNotIn("Done means the task's check command passes", text)


class SplitAndTouchesTest(unittest.TestCase):
    """A ready plan runs in parallel (PL2), and a shared file is judged by what each task
    touches, not by its name (PL1, 22.10.2026)."""

    def test_skill_r2_splits_the_plan_and_judges_by_touches(self):
        text = flat(SKILL_DIR / "SKILL.md")
        for needle in ("splits it into the smallest tasks that each pass a review alone",
                       '"One coupled piece", "few files" or "new files" is no reason for one writer',
                       "A shared file is no reason for serial work either",
                       "`shared` (one writer; only when the plan has one coding task)",
                       "`Group`, `Touches`, `After`",
                       "split it and fill `Touches` now (R2, PL2), before the checkout mode.",
                       "Choose the R2 checkout mode from that split (no plan yet → `worktree`)"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_parallel_md_has_the_split_touches_and_the_contract_rows(self):
        text = flat(PARALLEL_MD)
        for needle in ("## Split the plan into tasks (PL2)",
                       "the spec is the contract between them.",
                       "A part the spec leaves open is a decision: main takes it by R9",
                       "Tasks joined by a contract share one `Group` (TS1)",
                       "names every producer task it builds on, directly or through another producer",
                       "Docs and tests the plan asks for are their own tasks",
                       "**Not a reason for one writer or for serial work:**",
                       "## What each task touches (PL1)",
                       "\"Same file\" alone is never an `After` reason.",
                       "| One task needs the other's output, but the spec or the prompts fix the "
                       "contract (signature, name, schema, flag) | `worktree` | parallel, each "
                       "writes against the contract |"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_writer_prompt_names_the_shared_file_and_the_contract(self):
        text = flat(PROMPTS_MD)
        self.assertIn("You share <file> with <task ID>; change only <its Touches entry>", text)
        self.assertIn("keep them exactly. Need a change to one → stop and report.", text)


class NoBoxByDefaultTest(unittest.TestCase):
    """A box only when the owner names a time (R11, 22.10.2026); without one, no box timers,
    no hard end and no cut for time."""

    def test_skill_r11_has_a_box_only_when_the_owner_names_one(self):
        text = flat(SKILL_DIR / "SKILL.md")
        for needle in ("### R11 — A time box only when the owner names one",
                       "Main never picks one.",
                       "No box: no box end, hard end, park or deadline, no timer but the R13 "
                       "health check, no cut for time; R17 starts when no open work is left.",
                       "`strict` with no time: present → ask once for the time; away → ignore "
                       "the word, log it in `decisions.md`.",
                       "No box: `42 minutes gone; 7 of 12 tasks done (58%); ZD3 running (12/35 min).`",
                       "No box: nothing goes to TODO for time.",
                       "Never pick a box the owner did not name."):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        for gone in ("else 60 min (complex) or 30 (smaller)", "minimum 15",
                     "pick the box if none was given", "time-boxed solo coding run"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, text)

    def test_parallel_md_defines_the_no_box_run(self):
        text = flat(PARALLEL_MD)
        for needle in ("## No box - the default (VR1)",
                       "`run.md` says `Box: none` and holds no `Box end`, `Hard end`, `Park` or "
                       "`Deadline`; `## Timers` holds only the health job.",
                       "R6 bounds re-reviews only by their count (3).",
                       "Nothing goes to TODO because of time;",
                       "The run ends when no open work is left (finished, below): R17.",
                       "it moves nothing.",
                       "With a box only. The box is informative.",
                       "**Cut.** With a box only (no box: no cut for time)."):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_timers_prompts_and_runs_line_cover_no_box(self):
        health, queue, prompts = flat(HEALTH_MD), flat(QUEUE_MD), flat(PROMPTS_MD)
        self.assertIn("No box (R11): only the health timer;", health)
        self.assertIn("4. With a box only (no box: skip; nothing is cut for time).", health)
        self.assertIn("No box: only the health row.", queue)
        self.assertIn("`box_min` is the owner's box in minutes, `null` with no box;", queue)
        self.assertIn("<no box:> The run has no park time or hard end; only your own time limit "
                      "above applies.", prompts)
        self.assertIn("--deadline <min(300, park - 5 min) in s; 300 with no box>", prompts)


class StrictStartsARunTest(unittest.TestCase):
    """A start with `strict` (VR1) is a new run, so it ends the previous merge grant."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("audit_main", SKILL_DIR / "scripts" / "audit-main.py")
        cls.audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.audit)

    def test_strict_and_its_bulgarian_word_start_a_run(self):
        for args in ("30m strict", "1h away точно", "strict", "2h experiment"):
            with self.subTest(args=args):
                self.assertTrue(self.audit.starts_run(args))
        self.assertFalse(self.audit.starts_run("what is left?"))

    def test_a_strict_start_ends_the_merge_grant(self):
        grant = ("main", "/repo", 1792486800.0)
        self.assertIsNone(self.audit.next_grant(grant, "30m strict", "/repo", "2026-10-20T10:00:00Z"))


if __name__ == "__main__":
    unittest.main()
