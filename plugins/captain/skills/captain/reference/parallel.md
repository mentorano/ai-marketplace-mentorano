# parallel - the parallel plan, test groups, the time box

## Contents

- [The parallel plan (PL1)](#the-parallel-plan-pl1)
- [Split the plan into tasks (PL2)](#split-the-plan-into-tasks-pl2)
- [What each task touches (PL1)](#what-each-task-touches-pl1)
- [How main judges a pair of tasks (PL1)](#how-main-judges-a-pair-of-tasks-pl1)
- [What stays serial (PL1)](#what-stays-serial-pl1)
- [No box - the default (VR1)](#no-box---the-default-vr1)
- [The time box - box end and hard end (VR1)](#the-time-box---box-end-and-hard-end-vr1)
- [Work extensions (VR1)](#work-extensions-vr1)
- [Outage extension (VR1)](#outage-extension-vr1)
- [Strict time mode (VR1)](#strict-time-mode-vr1)
- [Cuts and the hard stop (VR1, R18)](#cuts-and-the-hard-stop-vr1-r18)
- [Worked example - /captain 2h from 10:00](#worked-example---captain-2h-from-1000)
- [Test groups (TS1)](#test-groups-ts1)
- [The group flow (TS1)](#the-group-flow-ts1)
- [The group's tests and the full build (TS1)](#the-groups-tests-and-the-full-build-ts1)
- [Parallel group runs (TS1)](#parallel-group-runs-ts1)

## The parallel plan (PL1)

**When.** Start step 4 splits a plan that exists at start; step 6 writes it to `run.md`. A
new spec: after its review round 1 (R5).

**What.** Main splits the plan (PL2, below) into `run.md` `## Tasks`, with three columns:

- `Group`: the service or module the task touches (TS1, below).
- `Touches`: what the task changes, file by file (below).
- `After`: the task it waits for and the concrete overlap or output, `After: ZDn — <what>`, or
  `-`.

**Rule.** Launch every task whose `After` is met at once, in the same turn. Serial work needs a
reason in `After`. There is no fixed cap on parallel writers; the only limits are the resources
under "What stays serial". A task whose `After` row merges starts in the turn of that merge.
**Why:** the owner, 20.10.2026: a large subscription and enough CPU and memory; the work should
be done faster. Runs had kept doable tasks serial that could run side by side.

## Split the plan into tasks (PL2)

**When.** A spec or plan exists and the work starts (start step 4, before the checkout mode;
a new spec: after its review round 1, R5). From then on the work runs in parallel by default.

**How.** The smallest tasks that each pass a review alone: one per plan step, module or file
area. A plan step too big for one review is split again. For a new feature:

- New files of one feature split by file or module (app code, build script, config, docs),
  even when they are "one coupled piece": the spec is the contract between them.
- The contract is what the tasks share: names, signatures, CLI flags, file formats, routes,
  env variables. A contract the spec fixes is copied into the task prompts (the same text in
  each). A part the spec leaves open is a decision: main takes it by R9 (its tier: main, a
  mini-consensus, a panel or the owner) and records it in `decisions.md` before the tasks that
  depend on it start; the independent tasks start at once.
- Tasks joined by a contract share one `Group` (TS1), so the group test runs only after both
  are merged. When they belong to different modules, the consumer's group row in `## Groups`
  names every producer task it builds on, directly or through another producer (A uses B, B
  uses C → A's row names B and C), and its test run waits for all of those merges.
- Docs and tests the plan asks for are their own tasks, written from the spec in parallel with
  the code.

**Not a reason for one writer or for serial work:** "one coupled piece", "few files", "new
files", "simpler with one writer", "same file". Each `After` names the real overlap.
`shared` mode (one writer) only when the plan has one coding task after the split.
**Why:** the owner, 22.10.2026: a run with a ready plan still gave the whole plan to one
writer ("the app, script and docs are one coupled piece"; "files are new and few"), and later
tasks waited on "same file"; the work should run in parallel as soon as a plan exists.

## What each task touches (PL1)

Before the launch, main fills `Touches` for every coding task: per file, the functions,
sections or line areas the task changes, or `new` for a new file. Source: the plan; else a
quick read of the file (`get_symbols_overview`, `grep` of the symbol). Main does this itself
(DL1 reads); a large plan → a read-only recon agent fills it.

A file in two tasks' `Touches` is a pair to judge (below). Each writer's prompt names the
shared file, the other task and its own `Touches` entry (`reference/prompts.md`).
**Why:** the owner, 22.10.2026: judge the conflict by what each task will change, not by the
file name; most tasks on one file touch different parts of it.

## How main judges a pair of tasks (PL1)

| Pair | Mode | Run |
|---|---|---|
| Disjoint files | `shared-multi` (declared, disjoint) or `worktree` | parallel |
| Same file, different functions or sections, or both add separate lines in one place (a new option, a new branch, a new route, a new test, a new list entry) | `worktree` + the integration agent at merge | parallel |
| One task needs the other's output, but the spec or the prompts fix the contract (signature, name, schema, flag) | `worktree` | parallel, each writes against the contract |
| One task needs an output the contract cannot fix: a generated file, a measured value, a design the other task decides | - | serial, `After: ZDn — <what it needs>` |
| Both rewrite the same lines or the same logic, or a shared lockfile, migration or snapshot | - | serial, `After: ZDn — both rewrite <function / lines>` or `— same <lockfile / migration>` |

"Same file" alone is never an `After` reason. In doubt between a parallel row and a serial
row, pick parallel in `worktree` mode: a merge
conflict costs one conflict prompt (`reference/prompts.md`); a serial chain costs the whole
earlier task.
**Why:** the owner, 20.10.2026: do as much as possible in parallel; a small conflict at merge
is cheaper than waiting.

## What stays serial (PL1)

- Test runs that share a resource: a test DB, a port, a container, a build directory (TS1).
- Parallel `git worktree add`: the locked `.git/config` retry in the R3 frame stays.
- A task that waits on an owner answer (present mode) or on a recorded decision.

**Why:** these are the real shared resources; two runs on one test DB or one port fail each
other, and the owner's answer cannot be guessed.

## No box - the default (VR1)

The owner named no time (R11) → the run has no box. `run.md` says `Box: none` and holds no
`Box end`, `Hard end`, `Park` or `Deadline`; `## Timers` holds only the health job. The rest of
this time section, the work extensions, the outage extension, strict mode and the cuts below
apply only with a box.

- **No time boundary.** R6 bounds re-reviews only by their count (3). A Codex review keeps its
  `timeout 1200`; a panel's Codex deadline is 300 s; a mini-consensus opinion gets 240 s; the
  NP1 extra writer always runs (`reference/triage.md`). Agent prompts carry no park time
  (`reference/prompts.md`).
- **No cut for time.** Nothing goes to TODO because of time; the other TODO reasons stay.
- **End.** The run ends when no open work is left (finished, below): R17.
- **Outages.** A confirmed outage still gets its `## Outages` line for the report and
  `outage_min`; it moves nothing.
- **Status line.** `42 minutes gone; 7 of 12 tasks done (58%); ZD3 running (12/35 min).`
  The done share is counted as below.

**Why:** the owner, 22.10.2026: self-chosen boxes, timers and hard ends slowed the runs down;
a box only when the owner asks for one ("for 1 hour", "for 2 hours").

## The time box - box end and hard end (VR1)

With a box only. The box is informative. `run.md` holds two times:

- `Box end` = start + box.
- `Hard end` = start + 1.3 × box (normal mode). Strict mode: hard end = box end. Outages and
  extensions move `Hard end`; `Box end` never moves.

Park and the deadline timer follow the current `Hard end` (`reference/health.md`, timer table):
park = hard end − 10% of the box, at least 5 min before it; deadline = hard end.

**Between box end and hard end** the run works only on open work (below) and its review
loops. It starts no new scope. The one-shot `box-end` timer prints one status line and checks
this.

**Status line.** It shows both times and the done share: `42 of 120 minutes gone (+36
tolerance); 7 of 12 tasks done (58%); ZD3 running (12/35 min).` The `(+N tolerance)` part is the
current hard end − box end in minutes, so it grows with each extension and outage. Strict mode
with no outage leaves it out. The done share counts the `## Tasks` rows of `run.md`: done =
`merged`, the total = every row except `cut`, the percent rounded down. A total of 0 (no plan
yet, or every row cut) leaves the part out. It counts tasks, not
their size; when the owner asks for more, give each open task its own estimate in the report.
**Why:** the owner, 17–20.10.2026: asked eight times in two runs for the progress as a percent
of the plan ("give the status as a percent of the spec/plan, what is left?").

**Finished.** No open work (below): all tasks merged or cut, their groups green → R17 at
once, with or without a box. Do not fill the box with new work.

**One time boundary.** R6 ("no re-review when the time to park is shorter than its timeout"),
the review timeout, the health-check step 4 and R18 all read the same park: the park of the
last possible hard end. Normal mode with open work and extensions left: the current hard end
plus the extensions left (the open work is what extends it); strict mode, or no extension
left: the current park. So a re-review may start and run past the current park; that park
becomes an extension. After each extension or outage main sends every running agent its new
`Park time (absolute)` and `Hard end (absolute)` by `SendMessage`, and new prompts carry them.
**Why:** the owner, 20.10.2026: the time is only informative; do not leave in TODO work that
fits; +30% to finish all of it. Runs had deferred doable work only to keep the box.

## Work extensions (VR1)

**Open work.** An open row of `## Tasks` (not `merged` and not `cut`), or a group in
`## Groups` with merged tasks whose test run, its fixes or the full build is not green yet.

**When.** With a box only. The park timer of the current hard end fires in normal mode, open
work remains, and fewer than 3 extensions are used → extend instead of parking. No open work →
no extension: R17.

**What.**
- Hard end moves by +30% of the box. At most 3 extensions per run.
- An extension takes only the open rows. It starts no new scope.
- Ceiling without outages: start + 2.2 × box (+30% automatic, then 3 × 30%).
- Each extension: one status line, one `decisions.md` line (`VRn | extension k/3 | open: ZD3,
  ZD5`), the new `Hard end`, `Park` and `Deadline` in `run.md`, and park and deadline re-armed
  (`CronDelete` the old jobs, record the new ids in `## Timers`).
- The deadline timer of a hard end that was extended never fires: its job is deleted with the
  re-arm. If it fires anyway (a late delete), check `run.md` `Hard end` first.

**Why:** the owner's answer VR4 = OP5, 20.10.2026: up to three more times +30% while work is
left, so open tasks finish instead of going to TODO.

## Outage extension (VR1)

A network or API outage moves hard end by its length, in every time mode, on top of the work
extensions; no box: it is only recorded. Main measures it, never estimates it.

- **Start** = the last successful event before the gap: the `Last check:` time in `run.md`, or
  the first agent report with a network or API error.
- **End** = the first successful call after the gap.
- **Candidate.** The R13 health check writes `Last check: <HH:MM>` to `run.md` every time. A gap
  of more than 20 min between two checks while an agent runs is an outage candidate.
- **Confirm** from an error: `API Error`, `Connection error`, `ECONNRESET`, a failed agent with
  a network error. Else a `captain:runner` reads the timestamps of the error entries in the
  session transcript. No error found → no outage (a long main turn also delays a check).
- **Record** one line in `run.md` `## Outages`: `<from>–<to>, <N> min, evidence: <...>`. Hard end
  moves by N; park and deadline are re-armed as for a work extension.
- The end report and the `runs.jsonl` line carry `outage_min`, the sum of the lines.

**Why:** the owner, 20.10.2026: a night network outage extends the run by its length. Two away
runs in one week lost about 160 min and about 6 h to outages.

## Strict time mode (VR1)

**What.** With a box only. A task that fills a time with work without an end runs in `time:
strict`: "make as many stories / games / sounds as you can in at most 1 hour", "maximum N",
"exactly by 12:00".

- Hard end = box end: no +30% and no work extensions. Only the outage extension applies.
- Park comes at the current hard end − 10% of the box, at least 5 min before it; with no
  outage that is box end − 10% of the box. No separate `box-end` job: the deadline covers it.
- Main infers the mode from the kickoff wording and writes `time: strict — <reason>` (else
  `time: normal — <reason>`) in `run.md`.
- Present mode: shown with the plan; the owner may flip it. Away mode: logged in
  `decisions.md`.
- The argument word `strict` sets it directly. With no time named: present → ask once for the
  time; away → ignore the word and log it (R11).

**Why:** the owner's answers RS3 = OP6 and MS1 = OP8, 20.10.2026: a creative task with a time
limit keeps an exact end; without one, extensions would let it run on forever.

## Cuts and the hard stop (VR1, R18)

**Cut.** With a box only (no box: no cut for time). A task goes to TODO only when, with every
independent task already running in parallel (PL1), its estimate does not fit the time to the
current hard end. Before a cut in normal mode, count the extensions left: a task with an open
row that fits the current hard end plus the extensions left is not cut. "To be safe" is not a
reason. The TODO reason names the numbers: `does not fit: needs ~40 min, 25 min to hard end`.

**Hard stop.** With a box, the last hard end (after the extensions and outages) is a hard
stop in both modes: park, then R17.
**Why:** the owner, 20.10.2026: do not leave in TODO work that fits. Runs had cut tasks "to be
safe" with time left, and the reason named no numbers to check.

## Worked example - /captain 2h from 10:00

Box 120 min, start 10:00. 10% of the box = 12 min; 30% = 36 min.

| Moment | Normal | Strict |
|---|---|---|
| Box end (`box-end` timer) | 12:00 | 12:00 |
| Hard end, park | 12:36, park 12:24 | 12:00, park 11:48 |
| Extension 1/3 | 13:12, park 13:00 | - |
| Extension 2/3 | 13:48, park 13:36 | - |
| Extension 3/3 (ceiling 2.2 × box) | 14:24, park 14:12 | - |
| Outage 11:10–11:50 recorded, 40 min | every hard end above + 40 min | 12:40, park 12:28 |

Compute every time with `date`, never by hand (`reference/health.md`).
**Why:** every time comes from one formula and `date`; the example makes the arithmetic
checkable.

## Test groups (TS1)

**Groups.** At start step 6 main gives each coding task a `Group` in `## Tasks`: the service or
module it touches (`backend-auth`, `web-app`). A task that touches two modules belongs to the
group of its main module and adds the other module to the group's test command. Each group gets
one row in `run.md` `## Groups` with its test command.

**Writers run nothing**, in every mode: no tests, no build, no compile check. The group's
runner runs them (R3 frame, `reference/prompts.md`).
**Why:** the owner's answer OP2, 20.10.2026: every writer ran tests and waited; grouping by
service or module and testing the group once after review and fixes speeds the run up a lot.

## The group flow (TS1)

1. Writers commit; each task runs its own review loop (R6) as before.
2. A clean loop merges at once (`reference/queue.md`, the merge flow), but the test run after
   that merge waits.
3. When every task of the group is `merged` or `cut` (and every contract producer the group row
   names, PL2, is merged), one `captain:runner` gets the group test
   prompt (`reference/prompts.md`) and runs the group's tests on the merged head, logged to a
   timestamped file under `tmp/claude-logs/`. A `cut` task closes its place in the group: the
   merged range is tested without it. All tasks of a group cut → no group run.
   The runner works in a clean temporary worktree at that SHA (a throwaway branch
   `group-<run-id>-<group>-<n>`, because `record-created.py` refuses a detached HEAD), recorded
   for the run's cleanup, never in the run checkout, so later merges do not change what it
   tests.
4. A failure is an observed fact, like a verifier failure: FIX NOW in every round
   (`reference/triage.md`). Main maps the failing test to a task by the files in the group's
   merge range and sends it to that task's writer (or a fresh `captain:worker` when the writer
   is gone). The fix gets one delta review of the fix commit only; then the runner reruns the
   group's tests. Two failed reruns of the same test → the R6 trap rules, which then win over
   FIX NOW (`reference/triage.md`, priority); data loss in normal use still comes first.
5. The R5 push of the group's range waits for a green group run.

**Trade-off.** A review can now see code that does not compile. Codex usually catches that in
round 1, and the group run catches the rest before any push.
**Why:** the owner, 20.10.2026: tests once per group, after review and fixes, instead of one
run per writer and per round.

## The group's tests and the full build (TS1)

- The group's tests: the test command of the touched service or module, with the env variables
  the repo's own docs name.
- The repo's full-build script (`build-project.sh`, `build-dev.sh`, `run-tests.sh` or the like)
  runs once on the feature branch before the first push, over all merged groups, by a
  `captain:runner`, logged, in the same kind of clean temporary worktree. A failure there goes
  back through step 4 of the group flow; after the fix, the runner reruns the group's tests and
  then the same full-build command. The push waits for a green full build.

**Why:** a change can pass its own module and break a downstream one; the full build catches it
once, before any push, instead of after each writer.

## Parallel group runs (TS1)

Two group runs run in parallel only when they share no resource: test DB, port, container,
build directory. In doubt, one after the other. Owner constraints from the kickoff ("the tests
one after the other") win over this.
**Why:** two suites on one test DB or one port fail each other, and the rerun costs more than
the wait.
