# health - timers, agent lifecycle, the 15-minute check

## Contents

- [Timers (R11, R13) - armed when run.md is written](#timers-r11-r13---armed-when-runmd-is-written)
- [Agent lifecycle (R13)](#agent-lifecycle-r13)
- [One task per writer, fresh writer at 30% context (R6)](#one-task-per-writer-fresh-writer-at-30-context-r6)
- [The 15-minute check - one status line (R13)](#the-15-minute-check---one-status-line-r13)
- [Correction ladder](#correction-ladder)
- [Leftover processes (R14)](#leftover-processes-r14)
- [Worktree cleanup - after the merge into the default branch](#worktree-cleanup---after-the-merge-into-the-default-branch)

## Timers (R11, R13) - armed when run.md is written

Every job id (or fallback task id) goes into `run.md` under `## Timers`. No box (R11): only
the health timer; box-end, park and deadline exist only with a box. Box end, hard end,
extensions, outages, strict mode and no box: `reference/parallel.md`.

| Timer | When | Primary | Fallback |
|---|---|---|---|
| health | every 15 min while any agent runs | `CronCreate` recurring `4,19,34,49 * * * *` | background `sleep 900` Bash, re-armed after each check |
| box-end | with a box only: box end (start + box), once; strict mode: none, the deadline covers it | `CronCreate` one-shot pinned to that minute | background `sleep <seconds until box end>` |
| park | with a box only: the current `Hard end` − 10% of the box, at least 5 min before it, in both time modes | `CronCreate` one-shot pinned to that minute | background `sleep <seconds until park>` |
| deadline | with a box only: the current `Hard end` (first normal: start + 1.3 × box; strict: box end; outages and extensions move it) | `CronCreate` one-shot pinned to that minute | background `sleep <seconds until deadline>` |

- Compute the minutes with `date`, never estimate. Example: start 14:02, box
  30 min → box end 14:32, hard end 14:41 (1.3 × 30 = 39 min), park 14:36 (10% = 3 min, so the
  5-min floor applies), deadline 14:41. Strict: park 14:27, deadline 14:32.
- With a box, re-arm park and deadline on each work extension and each recorded outage:
  `CronDelete` the old jobs (fallback: `TaskStop` the old `sleep` task ids), arm the new hard
  end's park and deadline, and record the new ids and times in `run.md`. The `box-end` job
  never moves. Then `SendMessage` every running agent its new park and hard end
  (`reference/parallel.md`, one time boundary).
- Every park or deadline signal: first compare `date` with `run.md` `Park` and `Hard end`. A
  signal of an earlier, moved time is stale: ignore it.
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

  The deadline job is the same with "captain: DEADLINE signal", the box-end job with
  "captain: BOX-END signal". If `CronCreate` is not available, use the fallback `sleep` for
  every timer.
- Cron jobs are session-only, fire only while the REPL is idle (never
  mid-turn), get up to 10% jitter and expire after 7 days. A signal can
  arrive late: act on it at once and note the delay for the R17 report.
- The fallback `sleep` re-invokes the session when it exits.
- Resume (the session was restarted, compacted, or `run.md` exists from this run): first
  `CronList`, compare with the ids in `run.md` `## Timers`, keep the matching jobs, re-create
  only the missing ones, and `CronDelete` any extra captain job, so no timer fires twice. A
  blank health id stays blank (and an extra health job is deleted) while no agent in `run.md`
  has `notified: no`; the next agent launch re-arms it.
  Record the new ids. With a box, also re-check `date` against box end, park and deadline.
- End (R17): `CronDelete` every job id, or `TaskStop` every fallback task id.

**Before any box-end, park or deadline signal** (and on resume): run the outage check of the
15-minute check first (`Last check:` gap, error evidence, `reference/parallel.md`), record a
confirmed outage, and with a box move the times and re-arm (no box: record it only); then act
only if the signal still matches `run.md`.
**On box end:** print one status line, and check that only open work (`reference/parallel.md`)
and its review loops run; new scope waits for the next run or goes to TODO with its reason.
**On park:** normal mode with open work (open rows of `## Tasks`, or a group not green) and
fewer than 3 extensions used → a
work extension instead (`reference/parallel.md`): no park signal. Else `SendMessage` to every
running agent: "Park signal: commit your work in progress on your branch now, do not push or
merge unreviewed work, and report." No new review starts after park (R6); "park" is the one
time boundary of `reference/parallel.md`.
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
  all of them in the `run.md` `## Agents` table at once, with task, absolute worktree, model,
  prompt time limit, launch time, and `notified: no`. Use the ids exactly as the launch result
  gives them; do not assume the task id equals the `agentId`.
- `## Agents` is the only agent table in `run.md`; keep no second one. Every agent whose
  prompt creates a worktree gets its row at launch: writers, group test runners, the
  bootstrap agent (`bootstrap`), fresh writers after a handoff. Its prompt passes the same
  `Name` to `record-created.py --agent` (`reference/prompts.md`); the cleanup finds the row
  by `Checkout (abs)` or by that name, and removes nothing whose row has `notified` other
  than `yes`.
  **Why:** a run kept two agent tables; the rows of two agents went only into the other one,
  and the cleanup skipped their worktrees until main added the rows by hand.
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

## One task per writer, fresh writer at 30% context (R6)

A writer holds one task at a time. Its context grows with every task it gets, and a writer
with a large context gets slower and starts to drop older instructions. The line is 30% of the
window. The measure comes only at the end of a task, so a writer just under the line can grow
by one more task.

- A new owner request while the writer is busy → a new `run.md` `## Tasks` row, state
  `queued`, and one line to the owner with its ID. Do not `SendMessage` it to the busy
  writer. A correction or clarification of the task in progress ("do not merge them, just
  order them") is not a new task: send it at once.
- The writer's completion notification → measure it:
  `python3 '<skill root>/scripts/agent-context.py' <agentId>`. The line ends in `keep` or
  `replace` (`replace` = at least 30% of a 1M-token window; `unknown replace` and
  `not found replace` = no measurement, treat it as full). Write it in the agent's `Context` column.
- `keep` → `SendMessage` the next queued task, or the review findings (R6), to the same
  writer. A loop that ended clean (no FIX NOW) is merged first, either way: main merges at once
  (`reference/queue.md`, the merge flow step 1), the `ZDn` row becomes `merged`, the group's
  runner runs the tests after the group's last merge (TS1, `reference/parallel.md`), and the R5
  push gate comes after.
- `replace` → `TaskStop` the writer if it has not ended, mark its row `replaced`, and launch
  a fresh `captain:worker` with the hand-off prompt (`reference/prompts.md`) and the next
  task or findings. The fresh writer takes over the old writer's files and review rounds.
- Never stop a writer in the middle of a task only for its context; wait for its report.
  The park signal and the correction ladder still apply as usual.
**Why:** 27.09: a writer grew to 316k tokens over 20 requests. The owner, 20.10.2026: the line
moved from 20% to 30%. In one run three writers at 24-26% were replaced and lost their working
context; of 1151 Opus subagents in 14 days, 201 peaked at 200k or more and only 22 at 300k.

## The 15-minute check - one status line (R13)

**When.** Every 15 min while any agent in `run.md` has `notified: no`. When an agent's time
limit (launch time + limit) or park (with a box) falls before the next recurring check, also
arm a one-shot check pinned to that minute (`CronCreate`, `recurring: false`, the same health
prompt). No agent running at a check → `CronDelete` the health job and blank its id in `##
Timers`; the next agent launch re-arms it. A check with nothing to watch prints no empty line.

**Output.** Every check ends with exactly one line to the owner, built from `run.md` in the
R11 status format, e.g. `42 of 120 minutes gone (+36 tolerance); 7 of 12 tasks done (58%); ZD3
running (12/35 min).` (the `(+N tolerance)` part and the done share: `reference/parallel.md`).
This line is the explicit exception to R12's "one line per real event": it is printed even
when nothing changed. It is not a report: no `Remaining:` list, no next-step line. A correction
or cut made in this check goes into this same line with its R19 ID (e.g. `ZD3 idle 20 min →
restarted (KR1)`), never a second line.
**Why:** 15 sessions, 09–13.10.2026: a silent health check drew 4 harness nags "Your previous
response had no visible output"; 43 checks in 15 sessions also filled the context.

1. `date`. First the outage: a gap of more than 20 min since the previous `Last check:` while
   an agent runs is an outage candidate; confirm it from an error, record it under
   `## Outages` and move hard end, park and deadline (`reference/parallel.md`, outage
   extension; no box: record it only). Then write `Last check: <HH:MM>` to `run.md`. Only
   then, with a box, compare with box end, park and deadline in `run.md`; a missed signal →
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
4. With a box only (no box: skip; nothing is cut for time). Compare work left with the time
   to the current `Hard end`. Before a cut, count the work
   extensions left (normal mode): a task with an open row that fits the current hard end plus
   the extensions left is not cut. Only what fits neither is cut (R18), with the numbers in the
   TODO reason.
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
agent, every writer and every group test runner append to it with
`python3 '<skill root>/scripts/record-created.py' --run-dir='<abs run dir>'
--worktree='<abs worktree>' --agent='<agent name>'` right after their `git worktree add`
(`reference/prompts.md`). It reads repo common dir, branch and SHA from git, and records the
agent name and the identity of the worktree's `.git` file. Nobody writes the file by hand; a
worktree missing from it is not the run's and goes to the queue (R10).

**The script.** A `captain:runner` runs `cleanup-run.py` at R14/R17 cleanup, and again when
the owner has merged the feature branch into the default branch or asks for it, exactly as
start step 3 allowed it (no other quoting, no argument beyond the two allowed forms):

    python3 '<skill root>/scripts/cleanup-run.py' --run-dir='<abs run dir>'

Start step 3 adds this exact command as one allow rule in `.claude/settings.local.json`, and
the same command with the run checkout flag as a second rule, the script path and run dir
filled in, no wildcard in the arguments:
`Bash(python3 '<skill root>/scripts/cleanup-run.py' --run-dir='<abs run dir>')` and
`Bash(python3 '<skill root>/scripts/cleanup-run.py' --run-dir='<abs run dir>' --include-run-checkout)`.
Main fixes the run ID (`<YYYYMMDD-HHMMSS>`) when it writes the rules; step 5 creates
`tmp/captain/<run-id>/` with that same ID.

`--dry-run` lists `WOULD-REMOVE` and changes nothing; the allow rules do not cover it, so use it
only when asked.

**Output.** The first line is `READ feature=<branch|-> base=<branch|none|-> default=<branch|->
checkout=<path|-> base_sha=<sha|-> agents=<n>`: what the script read from `run.md` (`-`: the
label is missing; `none`: an explicit `Base branch (R10): none`). A missing `Feature branch:`,
`Base branch (R10):`, `Run checkout:` or `Base SHA` adds a line
`WARN run.md has no <label> line; <what that disables>`; fix the label as in the run.md
template (`reference/queue.md`) and run the script again. Then one line per item that still
exists: `REMOVED`, `SKIPPED ... reason=<reason>` or `WOULD-REMOVE`. Items whose worktree and
branch are both gone print no line; when there are any, the last line `ALREADY-REMOVED <n>`
counts them. The runner reports every line.

**Logs.** Before a removal the script copies the worktree's `tmp/claude-logs/` to `<run
dir>/worktree-logs/<name>/`, or `<name>-<n>/` when that directory exists (an earlier copy).
Every line of an item whose worktree was removed names the copy, `logs=<copy>`. An agent
report path `<worktree>/tmp/claude-logs/<file>` is then `<copy>/<file>`, with the `logs=` value
of that line; a line without `logs=` has no copy. The end report (R17) says so once.

**Skips.** It skips:

- the working directory of a captain main session (a marker that is not stale, below) or of
  the runner;
- the run checkout (below);
- a worktree with tracked or untracked changes, or with ignored files that are not disposable
  (disposable: `node_modules/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `tmp/claude-logs/`);
- a worktree in which a process of the current user works (busy), or whose process check is
  incomplete (`ps` or a cwd lookup failed: unknown);
- a worktree at the recorded path that is not the one the run created;
- a branch not merged into the feature branch, its base or `origin/<default>`;
- a worktree whose `## Agents` row has `notified` other than `yes`;
- a worktree with no `## Agents` row for its agent (`no agent row for <agent> (<worktree>)`):
  add that one row and run the script again;
- every item when `run.md` has no readable `## Agents` table;
- a lock by anything but Supacode; any step git refuses.

It runs `git worktree unlock` only for a lock reason with `"owner":"supacode"`, `git worktree
remove` never `-f` (`--force`), `git branch -d` never `-D`. `SKIPPED` lines are only items that
still exist. Every `SKIPPED` line goes into the end report (R17) with its reason; the end report
ignores `ALREADY-REMOVED`. The owner decides.

**Session markers.** A marker in `~/.claude/captain/sessions/` counts for the cleanup only
while it is not stale: the newest mtime of the marker, its `.merge` and `.base` files and the
session's transcript is under 5 days old. Captain mode is on for the cleanup when such a
marker has its `cwd` in the same repository as the run. Nothing moves or removes a stale
marker automatically, and the guard is unchanged: for a session that is still open, a stale
marker keeps captain mode on.

Only when the owner asks, a runner archives old markers with
`python3 '<skill root>/scripts/archive-sessions.py' --older-than-days=<n> [--dry-run]`: it moves
each stale marker with its `.merge` and `.base` files to
`~/.claude/captain/sessions-archive/<YYYYMMDD>/`, prints one `ARCHIVE <id> <files>` or `KEEP <id>
<reason>` line per session. When it moved files (or would move them, `--dry-run`), it then
prints the command that moves everything back, and last a `NOTE` line: a session that is
still open and whose marker was archived needs `/captain resume` (or `/captain`) to turn
captain mode on again.

**Run checkout.** Not at R17: follow-up work uses the same feature branch
and worktree (R1). Without the flag the script always keeps it, `reason=run checkout kept;
pass --include-run-checkout on the owner's request`, with or without a live marker. Only when
the owner asks, the runner runs `git -C '<abs repo>' fetch origin` and then the second allowed
command, with `--include-run-checkout`. The script then removes the run checkout when all hold:
the feature branch has commits beyond the run's `Base SHA`, and its head is an ancestor of
`origin/<default>`; no marker that is not stale has its `cwd` inside it, and no process works
in it; the tree is clean; no other tool locks it. It deletes the feature branch only from a
checkout whose HEAD has it; otherwise the worktree goes, and the branch stays with the reason
`merged into ... but no checkout of the repository has it in HEAD`.

Nothing else is cleaned automatically: the merge flow has no cleanup step of its own, and
markers move only with the archive script above.

It does not call `supacode worktree delete`: that command takes a Supacode worktree ID, not a
path, falls back to the calling session's own `$SUPACODE_WORKTREE_ID` without one, and its help
does not say whether it deletes the directory too (not verified). A Supacode entry left behind
is the owner's to delete.

A final classifier denial of the runner (R16) → one `!` block for the owner with the same
script command plus `--dry-run`; after its output, the script command itself. Git commands as
`!` steps only for an item that output reports (`reference/queue.md`).
**Why:** 30.09.2026: a worktree app had locked the run's worktrees; `git worktree remove` failed
with "cannot remove a locked working tree", and cleanup went through only after `unlock`.
09.–13.10.2026: in one session the captain handed over `!` commands 21 times, mostly `git
worktree remove` / `git branch -d` of worktrees the run had created itself.
