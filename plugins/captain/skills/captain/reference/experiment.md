# experiment - the light test and the writer duel (R4, R20)

## Contents

- [Light test (R4)](#light-test-r4)
- [Routing outside a duel (R4)](#routing-outside-a-duel-r4)
- [Switch (R20)](#switch-r20)
- [Which tasks get a duel](#which-tasks-get-a-duel)
- [Writing](#writing)
- [Review](#review)
- [Check before the judge](#check-before-the-judge)
- [Judge](#judge)
- [After the judge](#after-the-judge)
- [experiments.jsonl](#experimentsjsonl)

## Light test (R4)

MR1. For every coding task main fills the light test in `run.md` `## Tasks`, each answered yes/no:

- KL1 A command decides "done": a named test, a lint, or a failing test to make pass.
- KL2 The owned files are known up front: about 5 at most, in one module or layer.
- KL3 The change follows a pattern that already exists in the repo, named in the prompt.
- KL4 No decision is left: the spec or plan step fixes names, behaviour and data shape.
- KL5 No risky mechanism: no concurrency, locks, timeouts, retries, hardware, auth or
  security, migrations or data deletion.
- KL6 Not a bug fix, or the bug's root cause is known.

Row shape and the `## Duels` table: `reference/queue.md` (run.md).

## Routing outside a duel (R4)

- MR2 Six yes → `captain:light-coder`; its prompt carries the frame's `ESCALATE` line
  (`reference/prompts.md`). Any no → `captain:worker`, as before.
- MR3 `ESCALATE` → a fresh `captain:worker` with the hand-off prompt and its ESCALATE addition.
- MR4 Trap escalation: a mechanism with findings in two rounds under a light coder → the next
  fix goes to a fresh `captain:worker` (hand-off), instead of the usual trap handling (R6).
- MR5 Sonnet never runs above effort `high`.
- MR6 `captain:light-coder-sol` runs only inside a duel.
- MR3 and MR4 apply outside a duel only (see [Review](#review)).
- Without the plugin agent types: a light task goes to `Agent` with `model: sonnet` at default
  effort, and no duel runs (the light writers' effort `high` cannot be set); `run.md` records
  the reason.

## Switch (R20)

`/captain [<box>] [away] experiment` (a localized alias is also accepted). `run.md` records
`Experiment: on`. Without the word no duel runs.

## Which tasks get a duel

For every task with six yes on KL, main writes `duel: yes|no — <reason>` in `## Tasks`:

- DU1 yes: a real check and medium size (2–5 files, or new tests), and three loops fit
  before park.
- DU2 no: trivial (one line, docs only, a TODO edit); it gives no signal.
- DU3 no: needs network or a dependency install (Sol's `workspace-write` sandbox has no
  network).
- DU4 no: on the critical path when time is short.
- DU5 no: the config has `tools.codex: false`, or a Codex usage limit is active (reset time in
  `run.md`); the reason is recorded and the task goes to `captain:light-coder` by the normal
  route.

Present mode: the plan confirmation shows these lines; the owner may flip any. Away mode: main
decides and logs the reason.

## Writing

- Three contestants: `captain:light-coder`, `captain:light-coder-sol`, `captain:worker`.
- Each gets its own worktree and branch `duel-<run-id>-<task>-<letter>`
  (`<abs repo>/.claude/worktrees/duel-<run-id>-<task>-<letter>`), off the feature branch at
  the same base SHA, whatever the run's R2 mode. The letter mapping (A/B/C → contestant) is
  random per duel and recorded only in `run.md`, never in a prompt.
  In the frame's `worktree add` step the start point is `'<base sha>'`, not the feature branch,
  so a commit landing on the feature branch meanwhile does not split the base.
- Identical task text, owned files, check command and time limit. The two Claude contestants
  get the R3 frame; the Sol wrapper gets the Sol frame variant (`reference/prompts.md`) and
  creates the worktree and commits itself.
- Sol's command, resume and the writer contract: `reference/tools.md` ("Sol writer").

## Review

- Every branch gets its own full R6 loop with Codex `gpt-6-astra`: same review prompt, same
  round threshold, its own register lines keyed `<task ID>/<letter> r<k> F<n>`
  (`reference/queue.md`). The review prompt names the letter's branch only,
  never the writer's model or agent type.
- If Codex fails for any contestant, every later review in that duel goes to the Opus
  fallback, for all three, and the record says so (`reviewer: opus-fallback`).
- At most 3 re-reviews each (R6). The bound, `ESCALATE`, the trap, or park → that contestant
  is "not finished"; its branch stays for the record. Inside a duel MR3/MR4 do not apply: no
  writer of another type takes over a contestant (the 20% replacement below is the only swap).
- The three loops run in parallel. Triage is per contestant, as today; findings go back to
  that contestant's own writer (for Sol, the wrapper relays them through `resume`).
- 20% context (R6, `reference/health.md`): the replacement is a fresh agent of the
  contestant's own type. A fresh Sol wrapper resumes the same Codex session id; Codex compacts
  its own context.

## Check before the judge

When all three loops ended, one `captain:runner` runs the task's check command for each
letter on the exact head SHA in a clean checkout (a temporary detached worktree at that SHA,
removed afterwards), logged. That log is the SD1 evidence. Uncommitted or dirty files in the
contestant's worktree do not count for SD1; they are counted under SD2.

## Judge

A blind `captain:deep` gets, per letter: the diff (`git diff <base>..<head>`), the
`--shortstat` line, the clean-checkout check log, the list of changed and uncommitted paths
against the owned list, and the review register (findings per round and class). Prompt and
output contract: `reference/prompts.md` ("Judge prompt"). It scores:

- SD1 the clean-checkout check passes and the last review left no FIX NOW;
- SD2 files touched outside the owned list, committed or not;
- SD3 review rounds until clean;
- SD4 FIX NOW findings in total;
- SD5 code quality and fit with repo patterns, 1–5;
- SD6 test quality, 1–5.

Winner: SD1 met; ties broken by fewer rounds (SD3), then the smaller diff (added + removed
lines from `git diff --shortstat <base>..<head>`), then the higher SD5 + SD6; still tied → the
judge picks and gives the reason. No contestant meets SD1 → no winner; the task goes back to
the normal flow: a fresh `captain:worker` with the R3 frame, off the feature branch; the
duel branches stay for reference.
An invalid output → one retry, then no winner.

## After the judge

- Main merges the winner's branch into the feature branch (`reference/queue.md`, the merge
  flow). It passed its own review, so R5 holds.
- Cleanup by outcome (the run created these, so R10 allows it):
  - winner merged → remove all three duel worktrees and delete the branch of each loser that
    finished normally; the branch of a contestant that did not finish (`ESCALATE`, the trap,
    the bound, a Sol failure) stays for the record and the end report lists it;
  - no winner, an invalid judge, or park → remove only clean worktrees; the branches, logs and
    Codex session ids stay and the end report lists them.
- The integration agent writes the `experiments.jsonl` record (below); the end report gets one
  "Duels" line per duel (`reference/queue.md`).

## experiments.jsonl

One JSON line per duel in `~/.claude/captain/experiments.jsonl`, next to `runs.jsonl`, so data
collects across repos. The integration agent writes the record to
`./tmp/captain/<run>/experiment-<task>.json` and appends it with the `runs.jsonl` snippet
(`reference/queue.md`), the target file changed to `experiments.jsonl`.

```json
{"date": "2026-09-30", "repo": "<name>", "run": "<run-id>", "task": {"id": "ZD3", "summary": "<one line>"},
 "light_test": {"KL1": true, "KL2": true, "KL3": true, "KL4": true, "KL5": true, "KL6": true},
 "duel_reason": "<DU1 reason>", "reviewer": "codex",
 "contestants": {"A": {"agent": "captain:light-coder", "model": "sonnet", "effort": "high",
   "finished": true, "rounds": 2, "findings_per_round": [5, 1], "fix_now": 4,
   "out_of_scope_files": 0, "escalate": null, "minutes": 18, "tokens": 412000,
   "scores": {"SD1": true, "SD2": 0, "SD3": 2, "SD4": 4, "SD5": 4, "SD6": 3}}},
 "winner": "A", "judge_reason": "<reason>"}
```

(Written as one line; wrapped here for reading. `contestants` holds A, B and C.)

- `reviewer`: `codex` or `opus-fallback` (R7).
- `escalate`: the `ESCALATE` reason or `null`; `finished: false` carries the reason in
  `escalate` or in a `not_finished` field (timeout, usage limit, bound, trap, park).
- `tokens`: the total for the whole duel. Claude contestants: the sum of usage over every model
  call in the agent's transcript, resumes included. The integration agent (a subagent) runs
  `python3 '<skill root>/scripts/agent-context.py' --total <agentId>...` for every agent that
  held the contestant and sums the lines. Each line is `<id> <N> tokens total`, or
  `<id> unknown` / `<id> not found` (record `null` then); usage is deduplicated by message id.
  Never the main session: its allow-list and `audit-main.py` accept only the default form
  without `--total`. Sol: the sum of the `tokens used` lines across all exec and resume logs,
  as the wrapper reports it (the wrapper's own Sonnet tokens are not Sol's).
- `minutes`: the `Minutes` column of `run.md` `## Agents` (accumulated at each completion),
  summed over every agent that held the contestant.

`python3 '<skill root>/scripts/experiment-summary.py'` prints per contestant agent: duels,
win rate, mean rounds, minutes and tokens, and the out-of-scope count. It computes only; a
change of routing is decided with the owner once about 10 duels exist.
