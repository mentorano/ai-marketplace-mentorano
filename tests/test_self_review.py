#!/usr/bin/env python3
"""Tests for the self-review rule (SV1): whoever writes an output self-reviews it once, in the
same context, before anyone acts on it, with the skill `utils:self-review`.

The skill lives in the utils plugin. The rule that calls it lives in captain (the agent frame,
the handoff, the run state; the boundary hook's text is in tests/test_captain_handoff.py and the
allowed Skill name in tests/test_captain_skill.py), in the utils handover prompt and in the
project-memory defragmenter. A self-review is never a review: every place
says so.

Run:  python3 tests/test_self_review.py
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "plugins"
CAPTAIN = PLUGINS / "captain"
SKILL_DIR = CAPTAIN / "skills" / "captain"
REFERENCE = SKILL_DIR / "reference"
RUN_END = SKILL_DIR / "scripts" / "check-run-end.py"
SELF_REVIEW = PLUGINS / "utils" / "skills" / "self-review" / "SKILL.md"
RESULT_LINE = "`self-review: <n> findings, <m> fixed, <k> rejected, <d> decisions`"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def flat(path: Path) -> str:
    return " ".join(read_text(path).split())


def fenced_block_after(text: str, heading: str) -> str:
    """The first fenced block after `heading`."""
    rest = text[text.index(heading):].splitlines()
    start = next(i for i, line in enumerate(rest) if line.startswith("```"))
    end = next(i for i in range(start + 1, len(rest)) if rest[i].startswith("```"))
    return "\n".join(rest[start + 1:end])


def numbered_steps(text: str) -> list[str]:
    return re.findall(r"(?m)^(\d+)\. ", text)


class SkillTest(unittest.TestCase):
    """utils:self-review: the steps, the checks per kind of output, the limits."""

    def setUp(self):
        self.text = read_text(SELF_REVIEW)
        self.flat = " ".join(self.text.split())

    def test_the_description_says_when_and_names_the_triggers(self):
        description = re.search(r"(?m)^description: (.*)$", self.text).group(1)
        self.assertTrue(description.startswith("Use when"))
        self.assertLess(len(description), 1024)
        for needle in ("before you commit it, hand it over or report it done", "a handoff or handover prompt",
                       "SV1", "\"self review\"", "\"check that nothing was missed\""):
            self.assertIn(needle, description)

    def test_the_six_steps_revalidate_before_any_fix(self):
        steps = self.text.split("## Steps", 1)[1].split("## What to check", 1)[0]
        self.assertEqual(numbered_steps(steps), ["1", "2", "3", "4", "5", "6"])
        body = " ".join(steps.split())
        for needle in ("**Name the output and its sources.**", "**Read the whole output back**",
                       "not your memory of it", "**Collect findings**", "Change nothing yet",
                       "**Revalidate each finding against the source, one at a time.**",
                       "`VALID`", "`INVALID`", "`DECISION`", "**Read back what you changed**",
                       RESULT_LINE, "No findings: `self-review: 0 findings, 0 fixed, 0 rejected, 0 decisions`"):
            with self.subTest(needle=needle):
                self.assertIn(needle, body)
        self.assertLess(body.index("Collect findings"), body.index("Revalidate each finding"))

    def test_every_kind_of_output_has_its_checks(self):
        table = self.text.split("## What to check", 1)[1].split("## Limits", 1)[0]
        rows = [line.split("|")[1].strip() for line in table.splitlines()
                if line.startswith("|") and not line.startswith("|---")][1:]
        self.assertEqual(rows, ["Code (a diff)", "A fix of review findings", "A spec or a plan",
                                "A handoff, a handover prompt, a prompt file for another agent",
                                "A doc or a report"])
        self.assertIn("Whatever lives only in this conversation is written down", " ".join(table.split()))

    def test_the_limits_keep_it_one_pass_in_one_context(self):
        limits = " ".join(self.text.split("## Limits", 1)[1].split("## Why", 1)[0].split())
        for needle in ("Launch no subagent and invoke no other review skill or command",
                       "Run no test and no build for this pass", "Do not commit or push",
                       "Fix only `VALID` findings", "Do not loop until nothing is found"):
            with self.subTest(needle=needle):
                self.assertIn(needle, limits)
        self.assertIn("A self-review never counts as a passed review", self.flat)
        self.assertIn("## Why", self.text)

    def test_the_skill_names_no_project_and_no_person(self):
        self.assertNotRegex(self.text, r"(?i)\b(ivan|i?dachev|mentorano)\b")

    def test_the_readme_lists_the_skill(self):
        readme = flat(ROOT / "README.md")
        self.assertIn("`self-review` (since 0.8.0)", readme)
        self.assertIn("plugins/utils/skills/self-review/SKILL.md", readme)


class CaptainFrameTest(unittest.TestCase):
    """Every agent gets the rule in its prompt frame and a slot for the result in its report."""

    def setUp(self):
        self.prompts = read_text(REFERENCE / "prompts.md")
        self.block = fenced_block_after(self.prompts, "## Agent frame (R3)")
        self.frame = " ".join(self.block.split())

    def test_the_frame_tells_every_author_to_run_the_skill(self):
        for needle in ("Self-review (SV1) before every commit (no commit → before you report) and before you "
                       "run any script on your code, once per finished piece of work, in this context: invoke "
                       "the skill `utils:self-review` (Skill tool)",
                       "the full diff of your change",
                       "a spec, a plan, a doc, a TODO entry, a report file, a memory draft",
                       "Its sources are the task text, \"Done means\" and the spec",
                       "The Skill list does not show `utils:self-review` → do its steps by hand",
                       "check each one against the source, and fix the confirmed ones",
                       "No subagent, no other review skill, no test or build run (TS1)",
                       "It is not the review and replaces none (R5)",
                       "reports `self-review: no files`"):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.frame)

    def test_a_light_coder_may_still_run_it(self):
        self.assertIn("Do not launch subagents or invoke review skills; the `utils:self-review` of your own "
                      "output (SV1, House rules) is no review skill and stays required.", self.frame)
        self.assertIn("`utils:self-review` of your own output (SV1) is no review skill and stays required",
                      flat(CAPTAIN / "agents" / "light-coder.md"))

    def test_the_report_has_a_slot_for_the_result_inside_its_eight_lines(self):
        self.assertIn("at most 8 lines", self.frame)
        self.assertIn(f"then the SV1 result on the same line: {RESULT_LINE} (or `no files`)", self.frame)
        report = self.block[self.block.index("1. blocked on the coordinator"):]
        self.assertEqual(re.findall(r"(?:^|\s)(\d)\. ", report.split("<only with")[0]),
                         ["1", "2", "3", "4", "5", "6", "7", "8"])

    def test_a_fix_round_self_reviews_the_fix_diff_before_the_commit(self):
        fix = " ".join(fenced_block_after(self.prompts, "## Fix list message (R6)").split())
        self.assertIn("Before the commit, self-review the fix diff (SV1, `utils:self-review`): each F in the list "
                      "is closed, and no unchanged line around a fix stopped working", fix)
        self.assertIn(f"{RESULT_LINE} line", fix)

    def test_triage_and_review_outputs_are_read_back_by_hand(self):
        # their own output contracts stay; Codex cannot call a Claude skill
        triage = " ".join(fenced_block_after(self.prompts, "## Revalidation message (R6)").split())
        self.assertIn("self-review the triage file (`utils:self-review`; by hand only when the Skill list does not "
                      "show it): one block for every finding in the review file", triage)
        review = " ".join(fenced_block_after(self.prompts, "## Review prompt (R6, R7)").split())
        self.assertIn("Before you answer, go through your own result once", review)
        self.assertIn("each finding's file:line was opened again in the source", review)
        self.assertNotIn("utils:self-review", review)
        self.assertLess(review.index("go through your own result once"), review.index("Output exactly:"))

    def test_a_panel_task_file_is_self_reviewed_as_a_voter_would_read_it(self):
        self.assertIn("main self-reviews both files as a voter would, who sees nothing else (SV1",
                      " ".join(self.prompts.split()))

    def test_every_agent_definition_carries_the_rule(self):
        files = sorted((CAPTAIN / "agents").glob("*.md"))
        self.assertEqual(len(files), 4)
        for path in files:
            with self.subTest(agent=path.name):
                body = flat(path)
                self.assertIn("self-review your whole output once, in this context (SV1 in the frame): the skill "
                              "`utils:self-review`", body)
                self.assertIn("or its steps by hand when the Skill list does not show it", body)
                self.assertIn("`self-review:` result in the report", body)
                self.assertIn("It is not the review and replaces none", body)


class CaptainHandoffTest(unittest.TestCase):
    """The handoff is self-reviewed against the run files before the successor gets it."""

    def setUp(self):
        self.text = read_text(REFERENCE / "handoff.md")
        self.flat = " ".join(self.text.split())

    def test_step_2_names_the_skill_its_sources_and_its_three_checks(self):
        for needle in ("Then the self-review (SV1), at once and in this session, before step 3 or the successor "
                       "terminal: the Skill call `utils:self-review` on the written handoff (not in the Skill "
                       "list → the same checks by hand)",
                       "`Read` the written handoff, `decisions.md`, `run.md` and `queue.md`; never check from "
                       "memory",
                       "files → handoff: every `decisions.md` line that still stands is in §1 or §3",
                       "window → files: whatever lives only in this window",
                       "a piece of work the owner asked for that is no `## Tasks` row",
                       "form: no status outside §2, gates only as quoted owner words",
                       "The kickoff text gets its own `utils:self-review` before the runner writes it",
                       "It is not a review and replaces none (R5)"):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.flat)

    def test_the_self_review_sits_inside_step_2_so_no_step_is_renumbered(self):
        how = self.text.split("## How", 1)[1].split("## Successor terminal", 1)[0]
        self.assertEqual(numbered_steps(how), ["1", "2", "3", "4", "5"])
        step2 = how.split("\n2. [ ]", 1)[1].split("\n3. [ ]", 1)[0]
        self.assertIn("self-review (SV1)", step2)
        self.assertLess(step2.index("self-review (SV1)"), step2.index("Steps 3-5 below are the `/clear` path"))

    def test_the_template_has_the_line_the_successor_looks_for(self):
        template = fenced_block_after(self.text, "## Handoff template")
        self.assertIn("Self-review (SV1): decisions <n> of <n> carried; owner decisions <n> of <n> in §2; "
                      "added from this window: <items, or none>.", template)
        resume = self.text.split("## `/captain resume`", 1)[1].split("## The hooks", 1)[0]
        self.assertIn("A handoff with no `Self-review (SV1):` line was not self-reviewed by its writer",
                      " ".join(resume.split()))

    def test_the_skill_rules_and_the_allow_list_name_the_skill(self):
        skill = flat(SKILL_DIR / "SKILL.md")
        self.assertIn("Every author, main too, runs `utils:self-review` on its output first (SV1): "
                      "no review (R5).", skill)
        self.assertIn("main writes and self-reviews (SV1) the handoff (template; status only in §2)", skill)
        self.assertIn("`Skill` for `utils:self-review` (SV1: main's self-review of an output it wrote",
                      flat(REFERENCE / "tools.md"))


class CaptainRunStateTest(unittest.TestCase):
    """Main's own outputs: the section in queue.md, the plan split line, the UI list, memory."""

    def setUp(self):
        self.queue = read_text(REFERENCE / "queue.md")
        self.flat = " ".join(self.queue.split())

    def test_the_section_says_who_when_how_and_that_it_is_no_review(self):
        section = self.queue.split("## Self-review of every written output (SV1)", 1)[1].split("\n## ", 1)[0]
        text = " ".join(section.split())
        for needle in ("Whoever writes an output self-reviews it once, in the same context, before anyone acts on "
                       "it: the Skill call `utils:self-review` (utils plugin, 0.8.0 or later)",
                       "Main does it in the turn of the `Write` or `Edit`, with `Read` of the written file and of "
                       "its sources, never from memory",
                       "The Skill list does not show `utils:self-review` → the same steps by hand",
                       "No subagent, no other review skill, no test run",
                       "Only the exact name `utils:self-review`",
                       "a self-review never counts as a passed review at the push gate",
                       "the `## Tasks` split (start step 6) and every re-split",
                       "the handoff, the kickoff text, the `ACK`",
                       "the `ui-check.md` use-case list",
                       "a panel's `task.md` and `data.md`",
                       "a `.agent-memory/` file (MSH2)",
                       "Bookkeeping lines of `run.md`",
                       "goes back to that agent once, by `SendMessage`",
                       "Reviews, triage reports and votes have their own contract",
                       "**Why:**"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        self.assertIn("(#self-review-of-every-written-output-sv1)", self.queue)

    def test_the_plan_split_line_is_in_the_run_md_header_not_inside_tasks(self):
        template = fenced_block_after(self.queue, "## run.md")
        line = next(line for line in template.splitlines() if "Plan split self-review (SV1)" in line)
        self.assertTrue(line.startswith("- Plan split self-review (SV1): <n> of <n> plan items are `## Tasks` rows"))
        self.assertLess(template.index("Plan split self-review (SV1)"), template.index("## Timers"),
                        "check-run-end.py reads every non-table line inside `## Tasks`")
        tasks = template.split("\n## Tasks\n", 1)[1].split("\n## Groups\n", 1)[0]
        self.assertNotIn("Self-review", tasks)

    def test_the_run_end_gate_accepts_a_run_md_with_the_header_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "tmp" / "captain" / "20261118-100000"
            run_dir.mkdir(parents=True)
            (run_dir / "run.md").write_text(
                "# captain run 20261118-100000\n"
                "- mode: normal — one feature\n"
                "- Plan split self-review (SV1): 2 of 2 plan items are `## Tasks` rows; added: none\n\n"
                "## Tasks\n"
                "| ID | Task | Group | Touches | After | Agent | State |\n"
                "|---|---|---|---|---|---|---|\n"
                "| ZD1 | the list | web | `a.py` | - | w-a | merged a1b2c3d |\n"
                "| ZD2 | the form | web | `b.py` | ZD1 — the list | w-b | merged e4f5a6b |\n",
                encoding="utf-8")
            todo = root / "TODO.md"
            todo.write_text("# TODO\n", encoding="utf-8")
            result = subprocess.run([sys.executable, str(RUN_END), f"--run-dir={run_dir}", f"--todo={todo}"],
                                    capture_output=True, text=True, timeout=30, cwd=root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_ui_list_and_the_memory_step_point_at_the_rule(self):
        ui = flat(REFERENCE / "ui-check.md")
        self.assertIn("Self-review (SV1, `utils:self-review`) before the list is shown or used", ui)
        self.assertIn("`Self-review (SV1): <n> of <n> criteria and <m> of <m> frontend tasks have a use case or a "
                      "`not checked` reason` (the ~12 limit above stands)", ui)
        self.assertIn("Then main self-reviews each written file against its drafts (SV1): no rule lost or "
                      "changed in a merge.", self.flat)


class OtherPluginsTest(unittest.TestCase):
    """The same pass where another plugin hands work to a reader that cannot ask back."""

    def test_the_handover_prompt_is_self_reviewed_before_the_tab_opens(self):
        text = flat(PLUGINS / "utils" / "skills" / "new-session-tab" / "SKILL.md")
        for needle in ("Then self-review it at once, in this session, before the tab opens: invoke this plugin's "
                       "skill `utils:self-review` on the file",
                       "Read the file as the new session will",
                       "tell the user the `self-review:` result line and what the pass added",
                       "The self-review is not a review and replaces none"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_the_defragmenter_traces_every_removed_line_before_its_report(self):
        folder = PLUGINS / "project-memory" / "skills" / "memory-defrag"
        text = read_text(folder / "defragmenter.md")
        self.assertEqual(numbered_steps(text), ["1", "2", "3", "4", "5"])
        prompt = " ".join(text.split())
        self.assertIn("4. Self-review before the report, in this context: invoke the skill `utils:self-review` "
                      "(not in your Skill list → the same steps by hand) with these checks. Run the read-only "
                      "`git diff -- <memory directory>` and read every removed line", prompt)
        self.assertIn("`self-review: <n> removed rules traced, <m> put back`", prompt)
        self.assertLess(prompt.index("4. Self-review before the report"), prompt.index("5. Return the report"))
        self.assertIn("`self-review:` line; a report without that line", flat(folder / "SKILL.md"))


class OutputSkillsTest(unittest.TestCase):
    """The skills that write an output for someone else run the pass before they hand it over."""

    CASES = {
        "3amigos/skills/3amigos": ("Then self-review both files with the skill `utils:self-review`",
                                   "before that report, self-review the written proposals with `utils:self-review`"),
        "branch-board/skills/branch-board": ("Then self-review the prose with the skill `utils:self-review`",),
        "clean-code/skills/architecture-fundamentals": ("Before an ADR or a review is handed over, self-review it "
                                                        "with the skill `utils:self-review`",),
    }

    def test_each_skill_names_the_pass_and_its_fallback(self):
        for folder, needles in self.CASES.items():
            text = flat(PLUGINS / folder / "SKILL.md")
            for needle in (*needles, "the same steps by hand"):
                with self.subTest(skill=folder, needle=needle):
                    self.assertIn(needle, text)

    def test_the_utils_skill_takes_over_the_old_triggers(self):
        description = re.search(r"(?m)^description: (.*)$", read_text(SELF_REVIEW)).group(1)
        self.assertIn("\"check that nothing was missed\"", description)
        self.assertIn("about to hand a branch over and wants it checked first", description)


if __name__ == "__main__":
    unittest.main()
