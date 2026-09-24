"""Regression tests for the branch-board collector.

Each test pins one way the collector was previously wrong. The comment above a
test says what it used to answer, because a test that only asserts the right
answer does not explain why the assertion is worth keeping.

Run: python3 tests/test_collect.py
"""
import os
import shutil
import tempfile
import unittest

from fixtures import branch, collect, commit, new_repo, run, write


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bb-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)


class TestBaseResolution(Base):
    """Regression: an unresolvable base dropped every branch and exited 0."""

    def test_missing_remote_is_fatal_not_empty(self):
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "work")
        write(repo, "w.txt", "x\n")
        commit(repo, "work 1")
        run(repo, "git", "checkout", "-q", "main")
        run(repo, "git", "remote", "remove", "origin")

        err = collect(repo, expect_rc=1)
        self.assertIn("does not resolve", err)

    def test_explicit_base_still_works_without_a_remote(self):
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "work")
        write(repo, "w.txt", "x\n")
        commit(repo, "work 1")
        run(repo, "git", "checkout", "-q", "main")
        run(repo, "git", "remote", "remove", "origin")

        data = collect(repo, "--base", "main", "--no-fetch")
        self.assertEqual(branch(data, "work")["ahead"], 1)


class TestPrune(Base):
    """Regression: --no-fetch skipped the mandatory prune without saying so."""

    def test_no_fetch_is_declared_as_unpruned(self):
        repo, _ = new_repo(self.tmp)
        data = collect(repo, "--no-fetch")
        self.assertIs(data["meta"]["pruned"], False)
        self.assertTrue(data["meta"]["warnings"])
        self.assertIn("prune", data["meta"]["warnings"][0])

    def test_successful_fetch_reports_pruned(self):
        repo, _ = new_repo(self.tmp)
        data = collect(repo)
        self.assertIs(data["meta"]["pruned"], True)
        self.assertEqual(data["meta"]["warnings"], [])

    def test_a_failed_gh_listing_is_recorded_and_warned_about(self):
        # the same defect as the fetch one: listing a command that never
        # succeeded makes the page claim a derivation it does not have
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "work")
        write(repo, "w.txt", "x\n")
        commit(repo, "work 1")
        run(repo, "git", "checkout", "-q", "main")

        data = collect(repo, "--no-fetch", gh_stub="gh-broken")
        gh_lines = [c for c in data["meta"]["commands"] if c.startswith("gh pr list --state open")]
        self.assertEqual(len(gh_lines), 1)
        self.assertIn("FAILED", gh_lines[0])
        self.assertTrue(any("gh could not list" in w for w in data["meta"]["warnings"]))

    def test_a_working_gh_listing_is_recorded_without_a_warning(self):
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "work")
        write(repo, "w.txt", "x\n")
        commit(repo, "work 1")
        run(repo, "git", "checkout", "-q", "main")

        data = collect(repo, "--no-fetch")
        gh_lines = [c for c in data["meta"]["commands"] if c.startswith("gh pr list --state open")]
        # the recorded line must be the command that RAN. It used to omit the
        # --limit that was in fact passed, which is the same defect this file
        # pins down elsewhere: a page listing a command nobody ran.
        self.assertEqual(
            gh_lines,
            ["gh pr list --state open --limit 200 --json headRefName,updatedAt"])
        # --no-fetch raises its own prune warning; only the gh one must be absent
        self.assertFalse(any("gh could not list" in w for w in data["meta"]["warnings"]))

    def test_failed_fetch_is_recorded_in_commands(self):
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "remote", "set-url", "origin",
            os.path.join(self.tmp, "gone.git"))
        data = collect(repo)
        self.assertIs(data["meta"]["fetched"], False)
        self.assertIn("FAILED", data["meta"]["commands"][0])


class TestLanded(Base):
    """Regression: a squash-merged branch reported merged=False."""

    def squashed_repo(self):
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "feature/squashed")
        write(repo, "s.txt", "one\n")
        commit(repo, "squash work 1")
        write(repo, "s.txt", "one\ntwo\n")
        commit(repo, "squash work 2")
        run(repo, "git", "push", "-q", "-u", "origin", "feature/squashed")
        run(repo, "git", "checkout", "-q", "main")
        run(repo, "git", "merge", "-q", "--squash", "feature/squashed")
        commit(repo, "squash: feature/squashed (#42)")
        run(repo, "git", "push", "-q", "origin", "main")
        return repo

    def test_squash_merge_without_a_pr_is_not_called_landed(self):
        # honest: git alone cannot know, and the diff must never be the evidence
        data = collect(self.squashed_repo(), "--no-fetch")
        b = branch(data, "feature/squashed")
        self.assertIs(b["merged"], False)
        self.assertIsNone(b["landed_by"])

    def test_merged_pr_lands_a_squashed_branch(self):
        data = collect(self.squashed_repo(), "--no-fetch", gh_stub="gh-merged",
                       env_extra={"BB_TEST_MERGED_HEAD": "feature/squashed"})
        b = branch(data, "feature/squashed")
        self.assertIs(b["merged"], True)
        self.assertEqual(b["landed_by"], "pr")

    def test_real_merge_lands_by_ancestor(self):
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "feature/real")
        write(repo, "r.txt", "x\n")
        commit(repo, "real work")
        run(repo, "git", "checkout", "-q", "main")
        run(repo, "git", "merge", "-q", "--no-ff", "-m", "merge", "feature/real")
        run(repo, "git", "push", "-q", "origin", "main")

        b = branch(collect(repo, "--no-fetch"), "feature/real")
        self.assertEqual(b["landed_by"], "ancestor")


class TestWindowAndRefs(Base):
    """Regression: the window filter ran before local and remote were merged."""

    def test_pushed_branch_with_an_old_remote_tip_is_not_local_only(self):
        repo, origin = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "pushed-long-ago")
        write(repo, "old.txt", "old\n")
        commit(repo, "old push", when="2020-01-01T10:00:00+00:00")
        run(repo, "git", "push", "-q", "-u", "origin", "pushed-long-ago")
        write(repo, "new.txt", "new\n")
        commit(repo, "fresh local commit")
        run(repo, "git", "checkout", "-q", "main")

        b = branch(collect(repo, "--no-fetch"), "pushed-long-ago")
        self.assertIs(b["local_only"], False,
                      "the branch exists on origin; calling it unpushed is a lie")

    def test_a_stale_tip_with_a_live_open_pr_stays_on_the_page(self):
        # Regression: the window read committerdate only, so a branch sitting in
        # review for longer than N days fell off exactly when it mattered most.
        from datetime import datetime, timedelta, timezone
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "in-review")
        write(repo, "r.txt", "x\n")
        commit(repo, "old work", when="2020-01-01T10:00:00+00:00")
        run(repo, "git", "push", "-q", "-u", "origin", "in-review")
        run(repo, "git", "checkout", "-q", "main")

        recent = (datetime.now(timezone.utc) - timedelta(days=1)
                  ).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = collect(repo, "--no-fetch", gh_stub="gh-openpr",
                       env_extra={"BB_TEST_OPEN_HEAD": "in-review",
                                  "BB_TEST_OPEN_UPDATED": recent})
        b = branch(data, "in-review")
        self.assertEqual(b["in_window_by"], "pr")
        self.assertEqual(b["pr"]["state"], "OPEN")

    def test_a_stale_tip_with_a_stale_pr_is_dropped(self):
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "in-review")
        write(repo, "r.txt", "x\n")
        commit(repo, "old work", when="2020-01-01T10:00:00+00:00")
        run(repo, "git", "push", "-q", "-u", "origin", "in-review")
        run(repo, "git", "checkout", "-q", "main")

        data = collect(repo, "--no-fetch", gh_stub="gh-openpr",
                       env_extra={"BB_TEST_OPEN_HEAD": "in-review",
                                  "BB_TEST_OPEN_UPDATED": "2020-01-02T10:00:00Z"})
        self.assertNotIn("in-review", [b["name"] for b in data["branches"]])

    def test_a_branch_older_than_the_window_is_still_dropped(self):
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "ancient")
        write(repo, "o.txt", "o\n")
        commit(repo, "ancient", when="2020-01-01T10:00:00+00:00")
        run(repo, "git", "checkout", "-q", "main")

        names = [b["name"] for b in collect(repo, "--no-fetch")["branches"]]
        self.assertNotIn("ancient", names)


class TestPlanSelection(Base):
    """Regression: a top-level plans/ ranked no higher than an incidental doc,
    and a deleted path silently consumed one of the three plan slots."""

    def test_top_level_plans_outranks_docs(self):
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "work")
        write(repo, "docs/notes.md", "# Notes\n\n## Overview\n\nIncidental.\n")
        write(repo, "plans/real.md", "# Real\n\n## Цел\n\nThe actual goal.\n")
        commit(repo, "plan plus a passing doc")
        run(repo, "git", "checkout", "-q", "main")

        plans = branch(collect(repo, "--no-fetch"), "work")["plans"]
        self.assertEqual([p["path"] for p in plans],
                         ["plans/real.md", "docs/notes.md"])
        self.assertEqual([p["kind"] for p in plans], ["plan", "incidental"])

    def test_deleted_docs_do_not_hide_the_real_plan(self):
        repo, _ = new_repo(self.tmp)
        for n in "abc":
            write(repo, f"docs/{n}.md", f"# Doc {n}\n\n## Overview\n\nOld {n}.\n")
        commit(repo, "three docs on the base")
        run(repo, "git", "push", "-q", "origin", "main")

        run(repo, "git", "checkout", "-q", "-b", "work")
        run(repo, "git", "rm", "-q", "docs/a.md", "docs/b.md", "docs/c.md")
        write(repo, "plans/mine.md", "# Mine\n\n## Цел\n\nThe branch's own plan.\n")
        commit(repo, "drop old docs, add a plan")
        run(repo, "git", "checkout", "-q", "main")

        plans = branch(collect(repo, "--no-fetch"), "work")["plans"]
        self.assertEqual([p["path"] for p in plans], ["plans/mine.md"])

    def test_a_branch_with_only_incidental_docs_says_so(self):
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "work")
        write(repo, "docs/setup.md", "# Setup\n\n## Overview\n\nUnrelated.\n")
        commit(repo, "touch a doc in passing")
        run(repo, "git", "checkout", "-q", "main")

        plans = branch(collect(repo, "--no-fetch"), "work")["plans"]
        self.assertEqual([p["kind"] for p in plans], ["incidental"])


class TestPlanParsing(Base):
    """Regression: fenced blocks leaked into flags and checkbox
    counts, and a "what is NOT built" section was read as the goal."""

    def plan_branch(self, body):
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "work")
        write(repo, "plans/p.md", body)
        commit(repo, "add plan")
        run(repo, "git", "checkout", "-q", "main")
        return branch(collect(repo, "--no-fetch"), "work")["plans"][0]

    def test_checkboxes_inside_a_fenced_block_are_not_counted(self):
        p = self.plan_branch(
            "# Plan\n\n## Цел\n\nShow the syntax.\n\n"
            "```markdown\n- [x] example one\n\n- [ ] example two\n```\n\n"
            "- [x] actually done\n")
        self.assertEqual(p["checkboxes"], {"done": 1, "todo": 0})

    def test_plus_is_a_valid_checkbox_marker(self):
        p = self.plan_branch("# Plan\n\n## Цел\n\nGoal.\n\n+ [x] done\n+ [ ] todo\n")
        self.assertEqual(p["checkboxes"], {"done": 1, "todo": 1})

    def test_a_flag_word_inside_a_fenced_block_is_not_a_flag(self):
        p = self.plan_branch(
            "# Plan\n\n## Цел\n\nGoal.\n\n"
            "```bash\nset -e\n\necho \"deployment is blocked until migration\"\n```\n")
        self.assertEqual(p["flags"], [])

    def test_a_real_flagged_paragraph_is_still_found(self):
        p = self.plan_branch(
            "# Plan\n\n## Цел\n\nGoal.\n\n"
            "Стъпка три е ⏸ паркирана, докато миграцията не мине.\n")
        self.assertEqual(len(p["flags"]), 1)
        self.assertIn("паркирана", p["flags"][0])

    def test_a_table_cell_is_not_a_flag(self):
        p = self.plan_branch(
            "# Plan\n\n## Цел\n\nGoal.\n\n"
            "| Стъпка | Състояние |\n|---|---|\n| миграция | ✅ готова |\n")
        self.assertEqual(p["flags"], [])

    def test_a_negative_scope_section_is_not_the_goal(self):
        p = self.plan_branch(
            "# Spec\n\n## Какво НЕ се строи\n\n"
            "Не пипаме billing и не мигрираме базата.\n\n"
            "## Цел\n\nДобавяме един endpoint за търсене.\n")
        self.assertEqual(p["goal"], "Добавяме един endpoint за търсене.")

    def test_an_explicit_goal_heading_beats_an_earlier_overview(self):
        p = self.plan_branch(
            "# Spec\n\n## Overview\n\nBackground prose.\n\n"
            "## Цел\n\nThe real goal.\n")
        self.assertEqual(p["goal"], "The real goal.")

    def test_a_goal_written_as_a_numbered_list_survives(self):
        p = self.plan_branch(
            "# Plan\n\n## Цел\n\n1. First thing.\n2. Second thing.\n")
        self.assertIn("First thing.", p["goal"])
        self.assertIn("Second thing.", p["goal"])


class TestRole(Base):
    """Regression: a release pointer looked exactly like work in flight."""

    def test_a_branch_at_the_base_is_a_pointer_not_work(self):
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "branch", "prod", "main")
        run(repo, "git", "push", "-q", "origin", "prod")

        b = branch(collect(repo, "--no-fetch"), "prod")
        self.assertEqual(b["role"], "pointer")
        self.assertEqual(b["ahead"], 0)

    def test_a_branch_with_commits_is_work(self):
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "work")
        write(repo, "w.txt", "x\n")
        commit(repo, "work 1")
        run(repo, "git", "checkout", "-q", "main")

        self.assertEqual(branch(collect(repo, "--no-fetch"), "work")["role"], "work")

    def test_a_branch_nobody_started_is_kept_and_marked_pointer(self):
        # branched off a base that has since moved on, with nothing of its own.
        # SKILL.md calls dropping these a mistake: someone made it and stopped.
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "branch", "started-nothing", "main")
        write(repo, "b.txt", "b\n")
        commit(repo, "base moves on")
        run(repo, "git", "push", "-q", "origin", "main")

        b = branch(collect(repo, "--no-fetch"), "started-nothing")
        self.assertEqual(b["role"], "pointer")
        self.assertEqual(b["ahead"], 0)
        self.assertEqual(b["behind"], 1)



class TestBrokenGhIsDeclared(Base):
    """Regression: `gh` installed but failing was reported as "no PR".

    The repo-wide `gh pr list --state open` call already marks itself FAILED and
    raises a warning. The per-branch `gh pr list --head ... --state all` call —
    the ONE thing that catches a squash merge — did neither. `meta.commands`
    listed it as if it had run, `meta.gh` said "yes", and the board printed
    "няма PR" as a fact about a branch whose PR was never read.
    """

    def squashed_repo(self):
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "feature/squashed")
        write(repo, "s.txt", "one\n")
        commit(repo, "squash work 1")
        run(repo, "git", "push", "-q", "-u", "origin", "feature/squashed")
        run(repo, "git", "checkout", "-q", "main")
        run(repo, "git", "merge", "-q", "--squash", "feature/squashed")
        commit(repo, "squash: feature/squashed (#42)")
        run(repo, "git", "push", "-q", "origin", "main")
        return repo

    def test_a_failed_per_branch_pr_lookup_is_marked_failed(self):
        data = collect(self.squashed_repo(), "--no-fetch", gh_stub="gh-broken")
        head_lines = [c for c in data["meta"]["commands"]
                      if c.startswith("gh pr list --head")]
        self.assertEqual(len(head_lines), 1)
        self.assertIn("FAILED", head_lines[0],
                      "the page lists a command that never succeeded")

    def test_a_failed_per_branch_pr_lookup_raises_a_warning(self):
        data = collect(self.squashed_repo(), "--no-fetch", gh_stub="gh-broken")
        self.assertTrue(
            any("PR" in w and ("squash" in w or "не може" in w or "could not read" in w)
                for w in data["meta"]["warnings"]),
            f"a squash merge is invisible and nothing says so: {data['meta']['warnings']}")

    def test_a_working_per_branch_lookup_is_not_marked_failed(self):
        # positive control: the assertion above must be able to pass
        data = collect(self.squashed_repo(), "--no-fetch", gh_stub="gh-none")
        head_lines = [c for c in data["meta"]["commands"]
                      if c.startswith("gh pr list --head")]
        self.assertEqual(head_lines, ["gh pr list --head <branch> --state all"])


class TestPrHistory(Base):
    """Regression: `gh pr list --head ... --state all --limit 1` returns the
    NEWEST pr. A branch merged by PR #1 and then given an abandoned follow-up
    PR #2 reports landed_by=None — the exact squash case the design exists for.
    """

    def test_a_merged_pr_is_found_behind_a_newer_closed_one(self):
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "feature/squashed")
        write(repo, "s.txt", "one\n")
        commit(repo, "squash work 1")
        run(repo, "git", "push", "-q", "-u", "origin", "feature/squashed")
        run(repo, "git", "checkout", "-q", "main")
        run(repo, "git", "merge", "-q", "--squash", "feature/squashed")
        commit(repo, "squash: feature/squashed (#1)")
        run(repo, "git", "push", "-q", "origin", "main")

        data = collect(repo, "--no-fetch", gh_stub="gh-merged-then-closed",
                       env_extra={"BB_TEST_MERGED_HEAD": "feature/squashed"})
        b = branch(data, "feature/squashed")
        self.assertEqual(b["landed_by"], "pr")
        self.assertIs(b["merged"], True)


class TestFenceClosing(Base):
    """Regression: strip_fences required the closing fence to be the exact
    same string as the opening one. CommonMark allows a LONGER closing fence, so
    ``` ... ```` left the fence "unclosed" and blanked the rest of the document:
    every checkbox and every flag after it silently disappeared.
    """

    def plan_branch(self, body):
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "work")
        write(repo, "plans/p.md", body)
        commit(repo, "add plan")
        run(repo, "git", "checkout", "-q", "main")
        return branch(collect(repo, "--no-fetch"), "work")["plans"][0]

    BODY = ("# Plan\n\n## Цел\n\nGoal.\n\n"
            "```\nprint('sample')\n````\n\n"      # legal CommonMark: closing fence may be longer
            "- [x] стъпка едно\n- [ ] стъпка две\n\n"
            "Стъпка три е ⏸ паркирана, докато миграцията не мине.\n")

    def test_a_longer_closing_fence_still_closes_the_block(self):
        p = self.plan_branch(self.BODY)
        self.assertEqual(p["checkboxes"], {"done": 1, "todo": 1},
                         "content after the fence was blanked out")

    def test_a_flag_after_a_longer_closing_fence_survives(self):
        p = self.plan_branch(self.BODY)
        self.assertEqual(len(p["flags"]), 1, "the flagged paragraph was blanked out")

    def test_a_task_heading_inside_a_fence_is_not_a_task(self):
        # tasks were read from the RAW lines while checkboxes and flags were
        # read from the stripped text, so a plan documenting its own heading
        # syntax counted the example headings as real tasks
        p = self.plan_branch(
            "# Plan\n\n## Цел\n\nGoal.\n\n"
            "```markdown\n## Задача 1 — примерна ✅ готова\n## Задача 2 — примерна\n```\n\n"
            "## Задача 1 — истинската задача\n")
        self.assertEqual([t["n"] for t in p["tasks"]], [1])
        self.assertEqual(p["tasks_done"], 0)


class TestTopDirs(Base):
    """Regression: top_dirs joined the first two path segments, so a file at
    the repo root, and any file one directory deep, was labelled a directory.
    The real board showed `dirs: STATUS.md (1)` and `dirs: CLAUDE.md (1)`.
    """

    def test_a_root_file_is_not_reported_as_a_directory(self):
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "work")
        write(repo, "STATUS.md", "x\n")
        write(repo, "docs/deep/note.md", "x\n")
        commit(repo, "touch a root file and a nested one")
        run(repo, "git", "checkout", "-q", "main")

        dirs = [d["path"] for d in branch(collect(repo, "--no-fetch"), "work")["top_dirs"]]
        self.assertNotIn("STATUS.md", dirs, "a file is presented as a directory")

    def test_a_file_one_level_deep_is_not_reported_as_a_directory(self):
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "work")
        write(repo, "docs/note.md", "x\n")
        commit(repo, "touch one file inside docs/")
        run(repo, "git", "checkout", "-q", "main")

        dirs = [d["path"] for d in branch(collect(repo, "--no-fetch"), "work")["top_dirs"]]
        self.assertNotIn("docs/note.md", dirs, "a file is presented as a directory")


class TestOrdering(Base):
    """Regression: last_date is `iso[:10]` — the date in the COMMITTER's
    timezone — and branches are sorted by that string. SKILL.md says the page is
    ordered by last activity because "recency is the one ranking that needs no
    judgement". Across timezones the string ranking reverses real recency.
    """

    def test_branches_are_ordered_by_absolute_time_not_by_local_date(self):
        repo, _ = new_repo(self.tmp)
        # 2026-08-26T20:00-11:00 == 2026-08-27T07:00Z — the NEWER of the two
        run(repo, "git", "checkout", "-q", "-b", "newer")
        write(repo, "n.txt", "n\n")
        commit(repo, "newer", when="2026-08-26T20:00:00-11:00")
        run(repo, "git", "checkout", "-q", "main")
        # 2026-08-27T14:00+13:00 == 2026-08-27T01:00Z — six hours OLDER
        run(repo, "git", "checkout", "-q", "-b", "older")
        write(repo, "o.txt", "o\n")
        commit(repo, "older", when="2026-08-27T14:00:00+13:00")
        run(repo, "git", "checkout", "-q", "main")

        names = [b["name"] for b in
                 collect(repo, "--no-fetch", "--days", "36500")["branches"]]
        self.assertLess(names.index("newer"), names.index("older"),
                        "the newer branch is ranked below the older one")



class TestNegativeHeadingInTheOtherDirection(Base):
    """Regression: NEGATIVE_HEAD_RE rejects a heading containing any of
    "не", "няма", "not", "no". It was written for "## Какво НЕ се строи", but it
    also silences real goal headings. GOAL_HEADS deliberately ranks
    "проблем"/"problem" as the second-best goal source — and a problem is almost
    always stated in the negative, so that whole group is unusable in Bulgarian.
    "No" is also an ordinary abbreviation for a number in both languages.
    """

    def plan_branch(self, body):
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "work")
        write(repo, "plans/p.md", body)
        commit(repo, "add plan")
        run(repo, "git", "checkout", "-q", "main")
        return branch(collect(repo, "--no-fetch"), "work")["plans"][0]

    def test_a_problem_statement_stated_in_the_negative_is_still_the_goal(self):
        p = self.plan_branch(
            "# Spec\n\n## Проблем: не се вижда кой какво прави\n\n"
            "Никой не чете списъка с branches.\n")
        self.assertIn("Никой", p["goal"])

    def test_no_as_a_number_abbreviation_does_not_reject_a_goal_heading(self):
        p = self.plan_branch("# Spec\n\n## Цел No 2\n\nДобавяме search endpoint.\n")
        self.assertEqual(p["goal"], "Добавяме search endpoint.")

    def test_a_genuine_negative_scope_heading_is_still_rejected(self):
        # positive control: the guard this regex exists for must keep working
        p = self.plan_branch(
            "# Spec\n\n## Какво НЕ се строи\n\nНе пипаме billing.\n\n"
            "## Цел\n\nДобавяме един endpoint.\n")
        self.assertEqual(p["goal"], "Добавяме един endpoint.")



class TestOpenPrListingCap(Base):
    """Regression: `gh pr list --state open --limit 200` is a silent cap.
    A repository with more open PRs than the limit loses the tail, and a branch
    whose tip is older than the window but whose PR is live falls off the page
    with nothing said. SKILL.md builds its whole warning mechanism around
    exactly this: a run that could not measure something must declare it.
    """

    def test_a_full_open_pr_page_is_declared_as_possibly_truncated(self):
        repo, _ = new_repo(self.tmp)
        data = collect(repo, "--no-fetch", gh_stub="gh-full-page")
        self.assertTrue(
            any("open PR" in w and ("truncat" in w or "cap" in w or "limit" in w)
                for w in data["meta"]["warnings"]),
            f"the listing may be cut off and nothing says so: {data['meta']['warnings']}")

    def test_a_short_open_pr_page_raises_no_cap_warning(self):
        # positive control: the warning must not fire on every run
        repo, _ = new_repo(self.tmp)
        data = collect(repo, "--no-fetch", gh_stub="gh-openpr",
                       env_extra={"BB_TEST_OPEN_HEAD": "nothing",
                                  "BB_TEST_OPEN_UPDATED": "2026-08-27T10:00:00Z"})
        self.assertFalse(any("truncat" in w for w in data["meta"]["warnings"]))



class TestShortstatLocale(Base):
    """Regression: the diff size is parsed by looking for the English words
    "insertion" and "deletion" in `git diff --shortstat`. git translates that
    line, so a translated build reports every branch as +0 −0 — a measurement
    replaced by a plausible number, with nothing said.
    """

    def test_diff_size_survives_a_translated_git(self):
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "work")
        write(repo, "w.txt", "one\ntwo\nthree\n")
        commit(repo, "work 1")
        run(repo, "git", "checkout", "-q", "main")

        b = branch(collect(repo, "--no-fetch", gh_stub="git-localized"), "work")
        self.assertEqual((b["insertions"], b["deletions"]), (3, 0))

    def test_diff_size_is_right_with_an_untranslated_git(self):
        # positive control: the fixture itself must not be what makes it pass
        repo, _ = new_repo(self.tmp)
        run(repo, "git", "checkout", "-q", "-b", "work")
        write(repo, "w.txt", "one\ntwo\nthree\n")
        commit(repo, "work 1")
        run(repo, "git", "checkout", "-q", "main")

        b = branch(collect(repo, "--no-fetch"), "work")
        self.assertEqual((b["insertions"], b["deletions"]), (3, 0))


class TestCommandProvenance(Base):
    """Regression: meta.commands listed commands that never ran."""

    def test_explicit_base_does_not_claim_a_symbolic_ref_lookup(self):
        repo, _ = new_repo(self.tmp)
        data = collect(repo, "--no-fetch", "--base", "main")
        joined = "\n".join(data["meta"]["commands"])
        self.assertNotIn("symbolic-ref", joined)
        self.assertIn("--base main", joined)

    def test_derived_base_does_record_the_lookup(self):
        repo, _ = new_repo(self.tmp)
        data = collect(repo, "--no-fetch")
        self.assertIn("git symbolic-ref --short refs/remotes/origin/HEAD",
                      data["meta"]["commands"])

    def test_per_branch_commands_are_absent_when_there_are_no_branches(self):
        repo, _ = new_repo(self.tmp)
        data = collect(repo, "--no-fetch")
        self.assertEqual(data["branches"], [])
        self.assertNotIn("git merge-base <base> <branch>", data["meta"]["commands"])


class TestLockSafety(Base):
    """Regression: one git call bypassed the wrapper and its
    --no-optional-locks. Asserted on the source, so a new call site fails."""

    def test_every_git_subprocess_carries_no_optional_locks(self):
        import ast

        from fixtures import COLLECT
        with open(COLLECT, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        offenders = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "run" and node.args):
                continue
            arg = node.args[0]
            if not (isinstance(arg, ast.List) and arg.elts
                    and isinstance(arg.elts[0], ast.Constant)):
                continue  # the wrapper builds its list in a variable
            if arg.elts[0].value != "git":
                continue
            if not any(isinstance(e, ast.Constant) and e.value == "--no-optional-locks"
                       for e in arg.elts):
                offenders.append(node.lineno)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
