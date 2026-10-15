# Scope deadlines

The owner gives a scope a deadline: „обхват <X> до 18:00“, „за 3ч“. Why this file exists: a
deadline said only in conversation did not hold - nothing timed it, nothing stopped new work.

## Start
- [ ] Read the time with `date`; never recall it. Compute: start, 50 %, 85 %, deadline (minute precision).
- [ ] Arm three one-shot timers with `CronCreate` (load it with ToolSearch), each pinned
      minute/hour/day/month, `recurring: false`, prompts: `coord: SCOPE 50% <scope>`,
      `coord: SCOPE PARK <scope>`, `coord: SCOPE DEADLINE <scope>`. No CronCreate: background
      `sleep <seconds>` Bash calls with the same meaning.
- [ ] Write scope, times and timer ids into the plan under `## Scope <X>`; tell the lanes the deadline once.

## 50 % - forecast
- [ ] Per lane: what lands by the deadline (from КАЦНА so far and the lane's current slice).
- [ ] All fits: nothing to say. Not all: propose the cut (which slices to backlog) - owner present: one question with a recommendation; away: vote (`votes.md`).

## 85 % - ПАРК
- [ ] ПАРК to every lane with work in progress: finish the current slice, КАЦНА, start nothing new.
- [ ] Unfinished slices go to the backlog with ids; no new review round starts that cannot finish before the deadline.

## Deadline
- [ ] Merge what has landed (one batch), run the FULL suites (`merge-and-verify.md`), report to the owner:
      done and ready for iteration (with 1-3 steps to try each); cut (backlog ids); decided without the owner (the brief, `templates/owner-batch.md`).
- [ ] A lane still busy 15 minutes after the deadline: proceed without it; its slice goes to the next scope.
- [ ] `CronDelete` any timer left; remove the `## Scope` timer ids from the plan.

## Resume after /clear
- [ ] `CronList`; compare with the ids under `## Scope <X>`; keep matching jobs, re-create only missing ones, delete extras - no timer fires twice. Re-read `date` against the three times; a time already passed: act on it now, once.
