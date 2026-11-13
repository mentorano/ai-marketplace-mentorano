# cowboy - the fast visual loop, one review, tests once before the merge (R22)

## Contents

- [Turning it on (KB1)](#turning-it-on-kb1)
- [The test policy (KB5)](#the-test-policy-kb5)
- [The loop (KB2)](#the-loop-kb2)
- [One review round (KB3)](#one-review-round-kb3)
- [Tests written, not run (KB4)](#tests-written-not-run-kb4)
- [The test pass (KB5)](#the-test-pass-kb5)
- [The guard gate (KB8)](#the-guard-gate-kb8)
- [The TODO entry and the end (KB6)](#the-todo-entry-and-the-end-kb6)

Cowboy mode trades safety during the loop for speed and pays it back once, before the merge
into the base branch. Nothing untested reaches the base branch or `main`.
**Why:** the owner, 2026-10-30: some runs are a fast visual loop ("see a change, react, see the
next one"); every change paid up to 3 re-reviews, a green `Group` run and the full build.

## Turning it on (KB1)

- The argument word `cowboy`, also in the kickoff, order-free like
  `away` and `strict`. A kickoff `tests=merge` or `tests=night` overrides the policy for this
  run only; the override is not written to the config.
- `run.md`: `- Mode: cowboy, tests: merge | night` (`reference/queue.md`, run.md). Cowboy mode
  is present mode: the loop needs the owner's eyes.
- `cowboy` with `away`: main asks once at kickoff which word to drop (recommendation: drop
  `away`).
- A cowboy run always works on its own new `captain/*` feature branch, never on an auto base
  (R2): agent branches must not land untested on the base branch. The gate below covers every
  merge of that branch into any branch but itself and its own agent branches: the base branch,
  `main` and the KB9 fallback's start branch included. It also covers a merge of any other
  branch that carries an untested cowboy commit.
- Right after the feature branch exists, main makes the skill call `cowboy on <branch>` with
  the feature branch named, because main's cwd is not the run checkout: the guard records the
  branch as a cowboy branch (KB8). At `/captain off` main makes the skill call `cowboy off`:
  it ends cowboy mode for the session and never removes or closes the branch's record (only a
  green record does).

## The test policy (KB5)

`~/.claude/captain/config.json` key `"cowboy":{"tests":"merge"}`, values `merge` or `night`.
Missing → main asks once (recommendation: `merge`) and writes the answer to the config;
`captain-setup` asks the same question.

At kickoff main says the active policy in one line, explicitly:
`Cowboy mode: 1 review, the tests do not run; tests: at the merge.` (or `tests: night
shift.` for `night`).

- `merge`: the test pass runs once, in this run, when the owner says they are satisfied.
- `night`: no test pass in this session. The TODO entry below; the owner starts a separate
  night-shift session by hand, a normal captain run (not a cowboy one), with the TODO IDs. No
  scheduler, cron or routine.

## The loop (KB2)

- Main splits the owner's feedback into small tasks and sends them to writers as usual (R2,
  R4). The shared checkout mode is preferred while the loop has one writer at a time.
- A change is shown once its FIX NOW fixes are committed and merged into the run checkout:
  what changed and where to look (URL, screen, command), one line each.
- A `captain:runner` keeps one dev server or watch build running on the run checkout for the
  whole loop; that start is the only build step in the loop. The external-write classifier
  (UP2, `reference/ui-check.md`) and the safe-start rules still apply: the classifier runs on
  the loop's diff once, before the server starts, without the green-tests precondition.
- The owner's look replaces the automated UI check during the loop; the UI check runs in the
  test pass or the night session.
- The owner's next feedback starts the next iteration. The loop ends when the owner says they
  are satisfied (→ the test pass, `merge`; the TODO entry, `night`) or at `/captain off`.
- Status lines stay R12-style; no extra reports between iterations.

## One review round (KB3)

Every change, code and tests together, gets exactly one review (R7); a spec the run writes too.
Triage runs once under the round-1 table; every confirmed defect is FIX NOW; the writer fixes
and commits; no re-review of the fix. The data-loss exception and the push gate:
`reference/triage.md` (cowboy mode) and R5. Findings not fixed go to `decisions.md` or TODO as
in a normal run.

## Tests written, not run (KB4)

Writers write or update tests for every change, as in a normal run; they are part of the
reviewed diff. Nothing runs them in the loop: no `Group` run (R20), no full build. A compile or
type check that the change needs to be visible at all may run in the dev server or watch build.
R5 in cowboy mode: a commit with a passed single review may be pushed to the feature branch
without a green `Group` run; it is never merged into the base branch or `main` before the test
pass is green.

## The test pass (KB5)

Policy `merge`, when the owner is satisfied, before R17 and before any merge into the base
branch:

1. A `captain:runner` runs every skipped `Group` test run and the full build (TS1,
   `reference/parallel.md`) in a clean temporary worktree at the feature branch tip, and the UI
   check of every UI group (`reference/ui-check.md`).
2. Failures are fixed under the normal R6 loop (`reference/triage.md`): the single-round rule
   ends with the loop. Each fix commit makes a new tip; the pass reruns on it.
3. Green at one exact SHA → the runner writes the result file
   `<abs repo>/tmp/captain/<run>/tests/<sha>.json`, an absolute path in the run dir (full
   40-character SHA):
   `{"sha": "<sha>", "commands": [{"cmd": "<command>", "exit": <code>}, ...]}`, one entry per
   skipped `Group` run and the full build, and reports the SHA and the file path. Main then
   makes the skill call `cowboy green <sha>`, with the run checkout's HEAD at `<sha>`.
4. Only then does the merge flow go on (`reference/queue.md`): the feature branch into the base
   branch; `main` still needs `/captain merge` (R10).

The night-shift session runs the same pass branch by branch from the TODO entries, merges a
green branch into its base branch and queues a `main` merge for `/captain merge`. No review of
the whole branch diff before the merge, unless the owner asks for one (one Codex review, R7).

## The guard gate (KB8)

The cowboy state the guard records (KB8) is keyed by the repository and the branch, not by the
session. `/captain off`, R17, a handoff and a new session do not remove it; only a green record
closes it. `hooks/guard.py` refuses a merge whose source contains an untested cowboy commit,
whatever the source is called, into any branch other than the cowboy branch itself and its own
agent branches (the base branch, `main` and the KB9 fallback's start branch included); a
`/captain merge` grant does not lift it. It also refuses `cowboy green <sha>` when
HEAD is not `<sha>` or the result file is missing, names another SHA, has no commands or has a
non-zero exit code. The green record names one commit: any later commit (a sync with
`origin/<default>`, a conflict fix, a TODO commit) makes it stale and the pass runs again. A
denial here is final for the run (R16): the pass runs, never a workaround. `check-run-end.py`
checks the same at R17.

## The TODO entry and the end (KB6)

A cowboy run whose tests did not pass in the run (`night`, a `merge` pass that cannot finish,
or `/captain off` before the pass) ends with one TODO entry per feature branch (format:
`reference/queue.md`, TODO entry for a cowboy run). A green `merge` pass → no entry. The
entry's commit never lands on the tested branch after its green record.

`/captain off` ends the loop without the test pass: the cowboy record stays, and main writes the
TODO entry in its reply to `off` (an agent commits it, R1); if it cannot, the next captain start
in that repository finds the open record and writes it.

The R17 end report names the cowboy run with tests not run and its TODO ID
(`reference/queue.md`, end report); `check-run-end.py` accepts such a run only with that entry.
