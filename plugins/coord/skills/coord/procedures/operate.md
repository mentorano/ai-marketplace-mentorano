# Operate: the steady-state loop

Coord is event-driven. Each wake: handle the message, act, update the board in one batch, stop.
No timers that resend context; a periodic check (if any) runs a cheap shell precheck first
(`derive-state.sh`) and wakes nothing unless something changed, at most every 2 hours.

**Waking a lane costs money.** A session idle for over an hour has lost its cache: the next message re-writes its whole context (~$1 per 150k at $8/MTok). Wake a lane at once only for: a task, the answer it waits for, STOP, PARK, or a contract change it is building on. Everything else for an idle lane (FYI, a MERGED that changes nothing for it, a MERGE-IN for later work) waits and goes together with its next task.

## On each message

**coord: SCOPE 50% / PARK / DEADLINE** (a timer) - `scope-deadline.md`. **coord: AWAY** (a product question unanswered 20 min) - away mode, `decisions-and-owner.md`.

**START** - check paths against ownership and hotspots; check no other in-flight branch touches the same hotspot (`derive-state.sh` branches ahead + `git diff --stat`). Reply ALL-CLEAR only if a hotspot was named and it is free; otherwise no reply. Hotspot NOT free: ANSWER naming the conflicting branch, what the lane waits for (that branch's MERGED), and what it does meanwhile; send ALL-CLEAR when it is free. Two in-flight branches on one path: STOP to the later one (paths, reason, what unblocks). Board: task -> `wip`, branch.

**LANDED** - validate the fields (`templates/kacna.md`); a missing flag, count or base sha, or commits after the reviewed range -> reply with exactly what is missing, do not merge. Then queue it for the next batch (`merge-and-verify.md`) and reply ACCEPTED (which batch, what else is in it, when MERGED is expected, what the lane does meanwhile). Board: `ready` (reported). If a contract changed, list consumer lanes for MERGE-IN after merge.

**QUESTION** - in order: (1) does running code answer it? Read it (or a haiku lookup) and answer with ANSWER. (2) Mechanical/process? Decide, answer, record in the plan "for ratification". (2b) An architecture/contract ruling: vote first (`votes.md`), then answer with GLn. (3) Product? Owner present: owner batch with a recommendation, arm the 20-minute timer, tell the lane what to do meanwhile. Owner away (or the timer fired): vote (`votes.md`), ANSWER with GLn. Never leave a lane idle without a meanwhile.

**BLOCKED** - re-derive the blocker from source (it may be stale). Unblock, reassign, or park the lane with a handoff. When unblocked: ANSWER to the lane, board `blocked` -> `wip`. A lane that finishes or blocks early gets shared path-work or a measurement task, not its own next full-scope slice.

**ACCEPTED** - note on the board if it changes a date/branch; no reply.

**Owner message** - decisions go to the amendments doc (numbered, dated, owner's words) and to the lanes they affect (ANSWER/MERGE-IN). A decision relayed by a third session: confirm with the owner before writing it down.

**Design session message** - `design-interplay.md`.

**Nothing incoming but a lane is silent** - measure its context before nudging; it is usually at the ceiling.

## Each merge batch (`merge-and-verify.md`)
Stage and commit per slice -> verify the combined tree once -> push once -> MERGED to owners -> MERGE-IN to affected -> board batch.

## Keep
- One migration head on integration at all times.
- The contracts between lanes: coord absorbs cross-lane traffic; batch what a lane needs into one message.
- The "Waiting on you" list (`decisions-and-owner.md`): shown at the end of a reply to the owner when it changed.
- The owner batch: collect product questions; send when a lane would otherwise block or at natural pauses.
- No silent process growth: before adding a recurring stage (review round, per-step agent, board tick), tell the owner with an agents/week estimate.
- Your own context: the hook never stops coord (coord dispatches no implementer tasks), so measure it yourself with `scripts/measure-context.py` after every merge batch; at >= threshold, `handoff-and-sessions.md`.

## Traps
- Assigning from a delta/design doc without `git log` - the row may have merged already.
- Relaying a lane's diagnosis as fact when nobody reproduced it - label it a hypothesis.
- Ordering a change to a line without asking who owns it.
- Withdrawing a disproven ruling silently - say plainly it is withdrawn and why.
