# health - timers, agent lifecycle, the 15-minute check

## Contents

- [Timers (R11, R13) - armed when run.md is written](#timers-r11-r13---armed-when-runmd-is-written)
- [Agent lifecycle (R13)](#agent-lifecycle-r13)
- [One task per writer, fresh writer at 20% context (R6)](#one-task-per-writer-fresh-writer-at-20-context-r6)
- [The 15-minute check - one status line (R13)](#the-15-minute-check---one-status-line-r13)
- [Correction ladder](#correction-ladder)
- [Leftover processes (R14)](#leftover-processes-r14)
- [Worktree cleanup - after the merge into the default branch](#worktree-cleanup---after-the-merge-into-the-default-branch)

## Timers (R11, R13) - armed when run.md is written

All three job ids (or fallback task ids) go into `run.md` under `## Timers`.

| Timer | When | Primary | Fallback |
|---|---|---|---|
| health | every 15 min while any agent runs | `CronCreate` recurring `4,19,34,49 * * * *` | background `sleep 900` Bash, re-armed after each check |
| park | deadline − 10% of the box, at least 5 min before the deadline | `CronCreate` one-shot pinned to that minute | background `sleep <seconds until park>` |
| deadline | deadline | `CronCreate` one-shot pinned to that minute | background `sleep <seconds until deadline>` |

- Compute the minutes with `date`, never estimate. Example: start 14:02, box
  30 min → park 14:27 (10% = 3 min, so the 5-min floor applies), deadline 14:32.
- One-shot cron: pin minute, hour, day and month of the target time, taken from `date` of
  that time, not from today (a box that crosses midnight lands on the next day):
  macOS `date -v+<N>M '+%M %H %d %m'`, Linux `date -d '+<N> min' '+%M %H %d %m'`; strip
  leading zeros. Load the Cron tools with `ToolSearch` first. `CronCreate` takes exactly `cron`
  (5 fields, local time), `prompt` and `recurring` (bool, default true; `false` = fire once,
  then auto-delete); `durable` exists but has no effect. `CronDelete` takes `id`. Payloads:

  ```json
  {"cron": "27 14 26 9 *", "prompt": "captain: PARK signal - act per reference/health.md", "recurring": false}
  {"cron": "4,19,34,49 * * * *", "prompt": "captain: health check - run it per reference/health.md", "recurring": true}
  ```

  The deadline job is the same with "captain: DEADLINE signal". If `CronCreate` is not
  available, use the fallback `sleep` for all three timers.
- Cron jobs are session-only, fire only while the REPL is idle (never
  mid-turn), get up to 10% jitter and expire after 7 days. A signal can
  arrive late: act on it at once and note the delay for the R17 report.
- The fallback `sleep` re-invokes the session when it exits.
- Resume (the session was restarted, compacted, or `run.md` exists from this run): first
  `CronList`, compare with the ids in `run.md` `## Timers`, keep the matching jobs, re-create
  only the missing ones, and `CronDelete` any extra captain job, so no timer fires twice. A
  blank health id stays blank (and an extra health job is deleted) while no agent in `run.md`
  has `notified: no`; the next agent launch re-arms it.
  Record the new ids. Also re-check `date` against park and deadline.
- End (R17): `CronDelete` every job id, or `TaskStop` every fallback task id.

**On park:** `SendMessage` to every running agent: "Park signal: commit your
work in progress on your branch now, do not push or merge unreviewed work,
and report." No new review starts after park (R6).
**On deadline:** start R17. When nothing runs and only the owner's `!` commands wait
(`reference/queue.md`), first say in one line what R17 does now (e.g. "Deadline: stopping
all timers and writing the runs.jsonl line; your commands stay valid"), then do it; or wait
for the owner's next output.
**Why:** 30.09.2026: at the deadline main deleted the health timer and launched a runs.jsonl
agent without a word while the owner waited on `!` commands; the owner wrote "stop, something
got stuck and I did not see what is happening".

## Agent lifecycle (R13)

- At start, `ToolSearch` loads `SendMessage` and `TaskStop` (and the Cron
  tools, `AskUserQuestion`).
- `Agent` returns an `agentId`, an `output_file` path and a task id for `TaskStop`; record
  all of them in the `run.md` agent table at once, with task, absolute worktree, model,
  prompt time limit, launch time, and `notified: no`. Use the ids exactly as the launch result
  gives them; do not assume the task id equals the `agentId`.
- Completion arrives as a task-notification → set `notified: yes`. `TaskList`
  is the todo list, not agent status; do not use it.
- `SendMessage(to: <agentId>)` reaches a running agent at its next tool round
  and resumes a finished one with its context intact (R6 review rounds).
- Every resume opens a new work period: set `notified: no`, the new start time and the new
  time limit in the agent's row, and update the ids or `output_file` if the tool returns new
  ones. The health check then covers it again until its next completion notification.
- No `SendMessage` available → launch a new agent with the old agent's report
  plus the message.
- `TaskStop` with the recorded task id stops a stalled agent.

## One task per writer, fresh writer at 20% context (R6)

A writer holds one task at a time. Its context grows with every task it gets, and a writer
past ~20% of its window gets slower and starts to drop older instructions.

- A new owner request while the writer is busy → a new `run.md` `## Tasks` row, state
  `queued`, and one line to the owner with its ID. Do not `SendMessage` it to the busy
  writer. A correction or clarification of the task in progress ("do not merge them, just
  order them") is not a new task: send it at once.
- The writer's completion notification → measure it:
  `python3 '<skill root>/scripts/agent-context.py' <agentId>`. The line ends in `keep` or
  `replace` (`replace` = at least 20% of a 1M-token window; `unknown replace` and
  `not found replace` = no measurement, treat it as full). Write it in the agent's `Context` column.
- `keep` → `SendMessage` the next queued task, or the review findings (R6), to the same
  writer. A loop that ended clean (no FIX NOW) is merged first, either way: main merges at once
  (`reference/queue.md`, the merge flow step 1), the `ZDn` row becomes `merged`, a runner runs
  the tests on the merged head, and the R5 push gate comes after.
- `replace` → `TaskStop` the writer if it has not ended, mark its row `replaced`, and launch
  a fresh `captain:worker` with the hand-off prompt (`reference/prompts.md`) and the next
  task or findings. The fresh writer takes over the old writer's files and review rounds.
  Inside a duel (R20) the replacement is instead the contestant's own agent type, and a fresh
  `captain:light-coder-sol` resumes the same Codex session id (Codex compacts its own context).
- Never stop a writer in the middle of a task only for its context; wait for its report.
  The park signal and the correction ladder still apply as usual.

## The 15-minute check - one status line (R13)

**When.** Every 15 min while any agent in `run.md` has `notified: no`. When an agent's time
limit (launch time + limit) or park falls before the next recurring check, also arm a one-shot
check pinned to that minute (`CronCreate`, `recurring: false`, the same health prompt). No
agent running at a check → `CronDelete` the health job and blank its id in `## Timers`; the
next agent launch re-arms it. A check with nothing to watch prints no empty line.

**Output.** Every check ends with exactly one line to the owner, built from `run.md` in the
R11 status format, e.g. `42 of 120 minutes gone; ZD3 running (12/35 min); ZD4 waiting for review.`
This line is the explicit exception to R12's "one line per real event": it is printed even
when nothing changed. It is not a report: no `Remaining:` list, no next-step line. A correction
or cut made in this check goes into this same line with its R19 ID (e.g. `ZD3 idle 20 min →
restarted (KR1)`), never a second line.
**Why:** 15 sessions, 09–13.10.2026: a silent health check drew 4 harness nags "Your previous
response had no visible output"; 43 checks in 15 sessions also filled the context.

1. `date`; compare with park and deadline in `run.md`. A missed signal →
   act on it now.
2. Per agent with `notified: no`, using only these three signals (never `Read` the
   `output_file`, not even with `offset`/`limit`):
   - output file mtime through the symlink:
     macOS `stat -L -f %m '<output_file>'`, Linux `stat -L -c %Y '<output_file>'`;
     compare with `date +%s`. Unchanged for 5+ min is only a trigger to look closer, not a
     verdict: an agent that waits on a background Codex run (up to its `timeout`, reviews
     take up to 14 min) or a long build is quiet by design. Weigh it against its task and
     its tool timeout.
     One `stat` per Bash call with the literal path: no `for` loop, no variable, no glob.
     **Why:** 30.09.2026: `for a in …; do stat -L -f %m …/$a.output; done` was denied by
     `guard.py` as UNVERIFIABLE (parameter expansion).
   - past its prompt time limit (launch time + limit)?
   - its completion notification.
   For anything more, `SendMessage` the agent for a one-line progress report, or launch a
   Sonnet diagnosis agent that reads the output and returns a short verdict.
   - a reviewer (the runner that waits on Codex, or an Opus reviewer) running 12+ min since
     its launch: `SendMessage` it for its state; no verdict by the next check → the R7 Opus
     fallback. **Why:** 01.10.2026: a Codex review ran 32 min to a timeout with no verdict, and
     the 15-minute check only pinged the writer.
3. Apply the correction ladder (below) to each stalled agent.
4. Compare time left with work left; when it no longer covers it, cut scope
   (R18).
5. Re-arm the fallback `sleep 900` if it is in use and an agent still runs; arm the one-shot
   check for the earliest agent limit or park that falls before the next check.
6. Print the one status line (above), with any correction or cut of this check and its R19
   ID inside it. Nothing else: never "nothing new", never a report.

## Correction ladder

1. First stall sign → `SendMessage`: "Progress report now, one line. Your
   limit is <N> min, <M> left."
2. No progress by the next check → `TaskStop`, relaunch with narrower scope
   and a note of what stalled; update `run.md` (old agent `stopped`, new row).
3. A stalled external tool (Codex hang, agy timeout) → relaunch with the
   specific fix: no-web line repeated, shorter timeout, or the fallback tool
   (see R7, R8).

## Leftover processes (R14)

Before any "nothing is running" claim: every `run.md` agent has
`notified: yes`, and a `ps` check runs (main may run `ps` itself; the
`lsof` lookup and any stop go to a Sonnet agent):

```bash
command ps -axo pid,lstart,command | command grep -E \
  'tail -f|emulator|qemu-system|GradleDaemon|gradle|codex app-server|codex exec|agy|node .*(vite|next|server)|java .*spring' \
  | command grep -v grep
```

Working directory of a PID: `command lsof -a -p <PID> -d cwd -Fn`.

- The run records every long-running process it starts (PID, start time,
  working directory, agent) in `run.md` under `## Processes`.
- Cleanup (R17) stops only processes whose PID, start time and working
  directory all match `run.md`. Every other match is listed to the owner as
  "not verified as ours, not stopped".

## Worktree cleanup - after the merge into the default branch

**Manifest.** The run deletes only what `tmp/captain/<run>/created.jsonl` lists. The bootstrap
agent and every writer append to it with `python3 '<skill root>/scripts/record-created.py'
--run-dir='<abs run dir>' --worktree='<abs worktree>'` right after their `git worktree add`
(`reference/prompts.md`); it reads repo common dir, branch and SHA from git. Nobody writes the
file by hand; a worktree missing from it is not the run's and goes to the queue (R10).

**The script.** A `captain:runner` runs `cleanup-run.py` at R14/R17 cleanup, and again when
the owner has merged the feature branch into the default branch or asks for it, exactly as
start step 3 allowed it (no other quoting, no extra argument):

    python3 '<skill root>/scripts/cleanup-run.py' --run-dir='<abs run dir>'

Start step 3 adds this exact command as one allow rule in `.claude/settings.local.json`, the
script path and run dir filled in, no wildcard in the arguments:
`Bash(python3 '<skill root>/scripts/cleanup-run.py' --run-dir='<abs run dir>')`. Main fixes the
run ID (`<YYYYMMDD-HHMMSS>`) when it writes the rule; step 5 creates `tmp/captain/<run-id>/`
with that same ID.

`--dry-run` lists `WOULD-REMOVE` and changes nothing; the allow rule does not cover it, so use it
only when asked. One line per item, `REMOVED`, `SKIPPED ... reason=<reason>` or `WOULD-REMOVE`;
the runner reports every line. It skips: the working directory of a captain main session or of
the runner; the run checkout while captain mode is on; a worktree with tracked or
untracked changes; a branch not merged into the feature branch, its base or `origin/<default>`;
a worktree whose `run.md` agent row has `notified` other than `yes`; a lock by anything but
Supacode; any step git refuses. It runs `git worktree unlock` only for a lock reason with
`"owner":"supacode"`, `git worktree remove` never `-f` (`--force`), `git branch -d` never `-D`.
Every `SKIPPED` line goes into the end report (R17) with its reason; the owner decides.

It does not call `supacode worktree delete`: that command takes a Supacode worktree ID, not a
path, falls back to the calling session's own `$SUPACODE_WORKTREE_ID` without one, and its help
does not say whether it deletes the directory too (not verified). A Supacode entry left behind
is the owner's to delete.

Not at R17 for the run checkout: follow-up work uses the same feature branch and worktree
(R1), and captain mode stays on, so the script keeps it; a cleanup after `/captain off` removes it.

A final classifier denial of the runner (R16) → one `!` block for the owner with the same
script command plus `--dry-run`; after its output, the script command itself. Git commands as
`!` steps only for an item that output reports (`reference/queue.md`).
**Why:** 30.09.2026: a worktree app had locked the run's worktrees; `git worktree remove` failed
with "cannot remove a locked working tree", and cleanup went through only after `unlock`.
09.–13.10.2026: in one session the captain handed over `!` commands 21 times, mostly `git
worktree remove` / `git branch -d` of worktrees the run had created itself.
