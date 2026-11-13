#!/usr/bin/env python3
"""Tests for the captain end-of-run check (scripts/check-run-end.py) and the R17 sweep wording."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "plugins" / "captain" / "skills" / "captain"
CHECK = SKILL_DIR / "scripts" / "check-run-end.py"
SKILL_MD = SKILL_DIR / "SKILL.md"
QUEUE_MD = SKILL_DIR / "reference" / "queue.md"

RUN_MD = """# captain run 20261029-043621
- Repo: /x   Start branch: main   Default branch: main

## Tasks
| ID | Task | Group | Touches | After | Agent | State |
|---|---|---|---|---|---|---|
| ZD1 | first | g1 | `a.py` | - | w-a | merged |
| ZD2 | second | g1 | `b.py` | ZD1 | w-b | merged (abc123) |
| ZD3 | third | g2 | `c.py` | - | w-c | cut → KP9 |
{extra_rows}{prose}
## Groups
| Group | Test command | Shared resource | Tasks | State |
|---|---|---|---|---|
| g1 | ./run-tests.sh | - | ZD1, ZD2 | green |
"""

TODO_MD = """# TODO

## KP7 - captain tests: a heading entry

- **KP9** third task — deferred: owner decision (2026-10-29).
- **TV3** docs wave 2 — deferred: owner decision (2026-10-28).
"""

DECISIONS_MD = """- KN1 | tier: full | away: product | <question> | options: A / B
  | votes: Codex A, Fable A, Opus A | result: A (majority) | reason: x
- VR2 | scope cut | subtask → TODO.md | reason: does not fit: needs ~40 min, 25 min to hard end
- ZD1 r2 F6 | ACCEPT artificial timing | a.py:3 — problem
- ZD1 r3 F2 | TODO owner decision → KP7 | a.py:9 — problem
"""

WAVE_PROSE = ("Wave 2 (after wave 1 and an explanation to the owner): K1–K6 code … "
              "Its plan is written after wave 1.\n")


class RunEndBase(unittest.TestCase):
    """A temporary run dir and TODO file, and the helpers to write them and run the check."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.run_dir = self.base / "run"
        self.run_dir.mkdir()
        self.todo = self.base / "TODO.md"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, extra_rows="", prose="", decisions=DECISIONS_MD, todo=TODO_MD, run_md=None):
        (self.run_dir / "run.md").write_text(
            run_md if run_md is not None else RUN_MD.format(extra_rows=extra_rows, prose=prose),
            encoding="utf-8")
        if decisions is not None:
            (self.run_dir / "decisions.md").write_text(decisions, encoding="utf-8")
        if todo is not None:
            self.todo.write_text(todo, encoding="utf-8")

    def run_check(self):
        result = subprocess.run(
            [sys.executable, str(CHECK), f"--run-dir={self.run_dir}", f"--todo={self.todo}"],
            capture_output=True, text=True, encoding="utf-8")
        return result.returncode, result.stdout.splitlines(), result.stderr

    def assert_one_problem(self, kind, needle):
        code, lines, _ = self.run_check()
        self.assertEqual(code, 1, lines)
        self.assertEqual(lines[-1], "FAIL: 1 problem(s)")
        self.assertEqual(len(lines), 2, lines)
        self.assertTrue(lines[0].startswith(f"MISSING {kind} "), lines)
        self.assertIn(needle, lines[0])
        self.assertIn(" — ", lines[0])


class RunEndCheckCase(RunEndBase):
    def test_clean_run_passes(self):
        self.write()
        code, lines, _ = self.run_check()
        self.assertEqual(code, 0, lines)
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith("PASS: "), lines)

    def test_open_row_without_todo_id_fails(self):
        self.write(extra_rows="| ZD4 | fourth | g2 | `d.py` | - | w-d | review 2/3 |\n")
        self.assert_one_problem("rows", "ZD4")

    def test_cut_row_without_arrow_fails(self):
        self.write(extra_rows="| ZD4 | fourth | g2 | `d.py` | - | w-d | cut |\n")
        self.assert_one_problem("rows", "ZD4")

    def test_row_id_not_in_todo_file_fails(self):
        self.write(extra_rows="| ZD4 | fourth | g2 | `d.py` | - | w-d | cut → KP1 |\n")
        self.assert_one_problem("rows", "KP1")

    def test_id_must_occur_as_a_whole_word(self):
        # KP9 is in the TODO file, KP97 is not: a prefix does not count
        self.write(extra_rows="| ZD4 | fourth | g2 | `d.py` | - | w-d | cut → KP97 |\n")
        self.assert_one_problem("rows", "KP97")

    def test_decision_todo_without_id_fails(self):
        self.write(decisions=DECISIONS_MD + "- ZD3 r3 F1 | TODO review bound | c.py:1 — x\n")
        self.assert_one_problem("decisions", "ZD3 r3 F1")

    def test_decision_todo_id_not_in_todo_file_fails(self):
        self.write(decisions=DECISIONS_MD + "- ZD3 r3 F1 | TODO review bound → ZZ5 | c.py:1 — x\n")
        self.assert_one_problem("decisions", "ZZ5")

    def test_scope_cut_to_todo_md_is_not_a_todo_class(self):
        self.write(decisions="- VR2 | scope cut | subtask → TODO.md | reason: x\n")
        code, lines, _ = self.run_check()
        self.assertEqual(code, 0, lines)

    def test_prose_wave_line_without_row_fails(self):
        # the 2026-10-28 shape: wave 2 only as a sentence in `## Tasks`, no ZD row
        self.write(prose="\n" + WAVE_PROSE)
        self.assert_one_problem("phase", "Wave 2")

    def test_prose_wave_line_naming_an_unknown_task_fails(self):
        self.write(prose="\nWave 2: ZD9 after ZD8.\n")
        self.assert_one_problem("phase", "ZD9")

    def test_prose_wave_line_naming_a_row_passes(self):
        self.write(prose="\nPhase 2 (ZD3) waits for wave 1.\nwave 3 is ZD3's split.\n")
        code, lines, _ = self.run_check()
        self.assertEqual(code, 0, lines)

    def test_no_run_md_is_bad_input(self):
        self.todo.write_text(TODO_MD, encoding="utf-8")
        code, _, err = self.run_check()
        self.assertEqual(code, 2)
        self.assertIn("run.md", err)

    def test_no_tasks_table_is_bad_input(self):
        self.write(run_md="# captain run\n\n## Tasks\nWave 1: everything.\n\n## Groups\n")
        code, _, _ = self.run_check()
        self.assertEqual(code, 2)

    def test_no_todo_file_is_bad_input(self):
        self.write(todo=None)
        code, _, err = self.run_check()
        self.assertEqual(code, 2)
        self.assertIn("TODO file", err)

    def test_missing_decisions_md_is_fine(self):
        self.write(decisions=None)
        code, lines, _ = self.run_check()
        self.assertEqual(code, 0, lines)

    def test_decision_todo_line_without_bullet_is_checked(self):
        # F1: the review-register shape `<task ID> r<k> F<n> | <class> ...` has no `- `
        self.write(decisions="ZD1 r3 F2 | TODO owner decision | a.py:9 — problem\n")
        self.assert_one_problem("decisions", "ZD1 r3 F2")

    def test_decision_todo_id_anywhere_in_the_line_passes(self):
        # F3: the spec asks for `→ <ID>` in the line, not only in the class field
        self.write(decisions="- ZD1 r3 F2 | TODO owner decision | a.py:9 — problem → KP7\n")
        code, lines, _ = self.run_check()
        self.assertEqual(code, 0, lines)

    def test_open_owner_decision_without_id_fails(self):
        # an owner decision that never became a task must reach TODO at run end
        self.write(decisions="- RSH3 | scope: permanent | source: owner | \"do it\" | status: open\n")
        self.assert_one_problem("decisions", "RSH3")

    def test_standing_owner_rule_without_status_passes(self):
        # a standing owner rule never becomes `done`; it is not work to sweep
        self.write(decisions="- RSH4 | scope: permanent | source: owner | \"the tests one after another\"\n")
        code, lines, _ = self.run_check()
        self.assertEqual(code, 0, lines)
        self.assertIn("0 TODO decision(s)", lines[-1])

    def test_deferred_owner_decision_id_not_in_todo_file_fails(self):
        self.write(decisions="- RSH3 | scope: run | source: owner | \"x\" | status: deferred → ZZ5\n")
        self.assert_one_problem("decisions", "ZZ5")

    def test_three_letter_todo_id_passes(self):
        # a Latin ID transliterated letter by letter may have three letters (STS1, RSH3)
        self.write(decisions="- ZD1 r3 F2 | TODO owner decision → STS1 | a.py:9 — problem\n",
                   todo=TODO_MD + "- **STS1** a three-letter entry\n")
        code, lines, _ = self.run_check()
        self.assertEqual(code, 0, lines)

    def test_deferred_owner_decision_with_todo_id_passes(self):
        self.write(decisions="- RSH3 | scope: run | source: owner | \"x\" | status: deferred → KP7\n")
        code, lines, _ = self.run_check()
        self.assertEqual(code, 0, lines)
        self.assertIn("1 TODO decision(s)", lines[-1])

    def test_done_owner_decision_and_agent_lines_pass(self):
        self.write(decisions="- RSH3 | scope: run | source: owner | \"x\" | status: done 1a2b3c4\n"
                             "- AR1 | tier: mini | scope: run | source: agent | JSONL | reason: y\n"
                             "- NS2 | scope: run | source: denial | git push origin main | to the owner\n")
        code, lines, _ = self.run_check()
        self.assertEqual(code, 0, lines)

    def test_escaped_pipe_stays_inside_its_cell(self):
        # F2: `\\|` is valid inside a GFM cell and must not shift the State column
        self.write(extra_rows="| ZD4 | support A \\| B | g2 | `d.py` | - | w-d | merged |\n")
        code, lines, _ = self.run_check()
        self.assertEqual(code, 0, lines)

    def test_problems_are_all_listed(self):
        self.write(extra_rows="| ZD4 | fourth | g2 | `d.py` | - | w-d | running |\n",
                   prose="\n" + WAVE_PROSE,
                   decisions=DECISIONS_MD + "- ZD3 r3 F1 | TODO review bound | c.py:1 — x\n")
        code, lines, _ = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(lines[-1], "FAIL: 3 problem(s)")
        self.assertEqual(sorted(line.split()[1] for line in lines[:-1]),
                         ["decisions", "phase", "rows"])


PROCESSES = """
## Processes
| PID | Start time | Working dir | Agent |
|---|---|---|---|
{rows}"""

OTHER_START = "Mon Jan  1 00:00:00 2001"


def lstart(pid: int) -> str:
    """The R14 `ps` start time of a PID, as the run writes it into `## Processes`."""
    return subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True,
                          text=True, check=True, env=dict(os.environ, LC_ALL="C")).stdout.strip()


class RunEndProcessesCase(RunEndBase):
    def setUp(self):
        super().setUp()
        self.child = subprocess.Popen(["sleep", "30"])
        try:
            self.start = lstart(self.child.pid)
        except Exception:
            self.stop_child()
            raise

    def tearDown(self):
        self.stop_child()
        super().tearDown()

    def stop_child(self):
        if self.child.poll() is None:
            self.child.kill()
        self.child.wait()

    def write_processes(self, start=None, agent="w-ui-server"):
        start = self.start if start is None else start
        row = f"| {self.child.pid} | {start} | /tmp/w-ui | {agent} |\n"
        self.write(run_md=RUN_MD.format(extra_rows="", prose="") + PROCESSES.format(rows=row))

    def test_live_process_of_this_run_fails(self):
        # UP15: the child is alive with the recorded start time
        self.write_processes()
        code, lines, _ = self.run_check()
        self.assertEqual(code, 1, lines)
        self.assertEqual(lines, [f"PROCESS {self.child.pid}", "FAIL: 1 problem(s)"])

    def test_exited_process_passes(self):
        # UP15: the same row after the child exits
        self.write_processes()
        self.child.kill()
        self.child.wait()
        code, lines, _ = self.run_check()
        self.assertEqual(code, 0, lines)
        self.assertTrue(lines[-1].startswith("PASS: "), lines)

    def test_reused_pid_with_another_start_time_passes(self):
        # UP15: a live PID with another start time is not ours
        self.write_processes(start=OTHER_START)
        code, lines, _ = self.run_check()
        self.assertEqual(code, 0, lines)
        self.assertNotIn(f"PROCESS {self.child.pid}", lines)

    def test_start_time_in_iso_or_extra_spaces_matches(self):
        parsed = datetime.strptime(" ".join(self.start.split()), "%a %b %d %H:%M:%S %Y")
        for start in (self.start.replace(" ", "  "), f"`{self.start}`",
                      parsed.isoformat(), parsed.strftime("%Y-%m-%d %H:%M:%S"),
                      parsed.strftime("%b %d %H:%M:%S %Y")):
            with self.subTest(start=start):
                self.write_processes(start=start)
                code, lines, _ = self.run_check()
                self.assertEqual(code, 1, lines)
                self.assertIn(f"PROCESS {self.child.pid}", lines)

    def test_kept_owner_row_passes_with_kept_line(self):
        # UP24: a live row marked `kept: owner`
        self.write_processes(agent="w-ui-server kept: owner")
        code, lines, _ = self.run_check()
        self.assertEqual(code, 0, lines)
        self.assertEqual(lines[0], f"KEPT {self.child.pid}")
        self.assertTrue(lines[-1].startswith("PASS: "), lines)

    def test_kept_owner_mark_in_a_trailing_cell_counts(self):
        self.write(run_md=RUN_MD.format(extra_rows="", prose="") + PROCESSES.format(
            rows=f"| {self.child.pid} | {self.start} | /tmp/w-ui | w-ui-server | kept: owner |\n"))
        code, lines, _ = self.run_check()
        self.assertEqual(code, 0, lines)
        self.assertIn(f"KEPT {self.child.pid}", lines)

    def test_same_row_without_the_mark_fails(self):
        # UP24: the same row without `kept: owner`
        self.write_processes(agent="w-ui-server")
        code, lines, _ = self.run_check()
        self.assertEqual(code, 1, lines)
        self.assertNotIn(f"KEPT {self.child.pid}", lines)
        self.assertIn(f"PROCESS {self.child.pid}", lines)

    def test_a_processes_table_after_a_level_3_subheading_is_still_read(self):
        row = f"| {self.child.pid} | {self.start} | /tmp/w-ui | w-ui-server |\n"
        self.write(run_md=RUN_MD.format(extra_rows="", prose="") + PROCESSES.format(rows=row)
                   .replace("## Processes\n", "## Processes\n\n### Servers\n\n"))
        code, lines, _ = self.run_check()
        self.assertEqual(code, 1, lines)
        self.assertIn(f"PROCESS {self.child.pid}", lines)

    def test_empty_processes_table_passes(self):
        self.write(run_md=RUN_MD.format(extra_rows="", prose="") + PROCESSES.format(rows=""))
        code, lines, _ = self.run_check()
        self.assertEqual(code, 0, lines)


def flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


class RunEndWordingTest(unittest.TestCase):
    def test_script_is_executable(self):
        self.assertTrue(CHECK.stat().st_mode & 0o111)

    def test_skill_r17_gates_the_end_report(self):
        skill = flat(SKILL_MD)
        r17 = skill[skill.index("### R17"):skill.index("### R18")]
        for needle in ("`scripts/check-run-end.py`", "exit 0",
                       'no "not done" without a TODO ID', "**Why:**",
                       "28.10.2026", "K1–K6"):
            with self.subTest(needle=needle):
                self.assertIn(needle, r17)
        self.assertLess(r17.index("check-run-end.py"), r17.index("**Why:**"))
        self.assertIn("- `scripts/check-run-end.py` - R17 gate, exit 0.",
                      skill)

    def test_queue_md_has_the_sweep_and_the_report_rule(self):
        queue = flat(QUEUE_MD)
        for needle in ("## End-of-run sweep (R17)",
                       "every `## Tasks` row whose State does not start with `merged`",
                       "every `decisions.md` line of class `TODO`",
                       "every finding still open at the review bound",
                       "its row or line gets `→ <ID>`",
                       "python3 '<skill root>/scripts/check-run-end.py' "
                       "--run-dir='<abs run dir>' --todo='<abs TODO file>'",
                       "Only exit 0 lets the end report go out",
                       "not done, each item with its TODO ID",
                       "the `check-run-end.py` exit code and its lines"):
            with self.subTest(needle=needle):
                self.assertIn(needle, queue)


if __name__ == "__main__":
    unittest.main()
