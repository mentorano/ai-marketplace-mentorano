# Handoff and sessions

## Never hand off mid-operation
Finish or abort a merge batch before writing a handoff: no staged merge, no unpushed verified batch, no running verification. If the owner forces a handoff mid-batch, the handoff names the operation explicitly ("local integration branch is N ahead: merges X, Y; verification not finished") - this is an open operation, not state, and its omission cost a successor a false alarm about another session.

## Document classes a successor reads
- Coord handoffs (in git, dated, each corrects the earlier ones).
- Lane handoffs at the config's lane handoff path, default `<worktree>/.superpowers/handoffs/` (outside git; the lanes' own truth about their lane).
- Coord addenda written INTO a lane's handoff dir, marked second-hand; the lane's own file wins where they differ.

## When
- At a TASK BOUNDARY (a new bounded task/slice is about to start, a merge batch is pushed) once context >= threshold (config; default 250k). Not mid-task: reviews, fix waves, re-reviews are inside a task.
- Measured, never guessed: `scripts/measure-context.py <repo> [hours]` (last main-chain assistant usage: input + cache_read + cache_creation). The `handoff-at-boundary.py` hook denies the next implementer dispatch once at the threshold; re-issuing the same dispatch goes through if the owner says continue.
- Also at a phase boundary: when the next work has little to do with what is in the window.
- Why a ceiling: every turn re-reads the whole window; long tool-heavy sessions at 400-650k were the largest share of spend.

## How (any session)
1. [ ] Commit and push; wait for running subagents; no merge left staged (coord: finish or abort it).
2. [ ] Write the handoff (`templates/handoff.md`) at the config's handoff path: banner "nothing here is status"; SELF-CONTAINED: carry forward every decision, ruling and lesson from earlier handoffs that still stands (shortened), so the successor reads only this file - earlier files stay for lookup, never as required reading; decisions taken (with ids/links); rulings for ratification; open questions (labelled, with owner); lessons; the COMMANDS that re-derive state. Never: branch positions, "X is merged", who is on what - put the command instead.
3. [ ] Write the successor's kickoff to `~/.claude/kickoffs/<session name>.md` (`templates/coord-kickoff.md` / `lane-kickoff.md`): who it is ("you ARE <name>, the successor"), the one self-contained handoff to read, what to start with, the rule to re-derive state. Named by session, not cwd - two sessions can share a cwd.
4. [ ] Tell the owner one line: "Контекстът е Nk - handoff в <path>; напиши /clear, после `/coord`" (a lane: "/clear, после `/coord lane`"; a session not using the skill: "/clear, после „давай“"). Stop.
5. The owner types `/clear`, then that first message - it starts the turn and, for `/coord`, loads the skill. The `kickoff-on-clear.py` hook (SessionStart, matcher `clear`) injects the file and moves it to `kickoff-used/`. Injected context does not start a turn - the owner's message does.

## Name swap (coord, or any session replaced by a NEW session instead of /clear)
- [ ] Owner renames the old session first (e.g. `<name>-old`), then the new session takes `<name>`. Two live sessions with one name make messages ambiguous.
- [ ] Verify via each session's start time; messages around a restart may land in the dying one.

## Restart hygiene
- [ ] After any restart (especially a mass one, e.g. a model switch), coord re-sends every decision-bearing message from the last ~30 minutes to its intended session.
- [ ] A restarted session that keeps writing "for the next session" must be told plainly: you ARE that session - do the work.
- [ ] A fresh session may rebuild a contract from an older spec: cross-check against the consumer's handoff before relaying.

## Second-hand handoff
If a session cannot write its own (hard usage limit), coord may write an addendum built ONLY from that session's outbound protocol messages plus git, labelled "reconstructed, second-hand". The lane's own later handoff wins any contradiction.

## Evaluated alternatives (do not re-litigate without new facts)
- **Auto-compact: rejected.** An extra full-context summarization call plus a lingering, possibly stale summary that is paid for on every later turn; the summary's codec is not chosen by anyone who knows what the next task needs.
- **Background sessions that replace themselves (`claude --bg --name ...`): optional, untested.** Unknowns: permission prompts with nobody watching; `.claude/worktrees` layout vs this worktree layout; attach/visibility ergonomics for the owner. Try only on one non-critical lane with the owner's agreement.
- A session cannot `/clear` itself, and self-driving its own terminal is blocked by the auto-mode classifier (tested). The manual design is one cheap human action (`/clear` + first message).
- **cmux: coord restarts lanes in place (verified on a live lane, adopted as an option).** Coord types `/clear` + `/coord lane` into an idle lane's tab; the session keeps its name and tab. Coord's own handoff stays manual. See `cmux-automation.md`.
