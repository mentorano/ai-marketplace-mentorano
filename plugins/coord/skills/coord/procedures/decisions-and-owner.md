# Decisions and the owner

## Two tracks, always labelled
- **Owner (product) decisions** -> the amendments doc (config path): one numbered, dated line per decision, in the owner's words where possible. Only the owner creates these.
- **Coord (mechanical/process/contract) rulings** -> the plan doc, marked "for ratification" until the owner ratifies (then cite the ratifying decision number). Never present them as settled.
- The board records status only, never decisions.

## What coord decides alone (then reports with reasoning)
Merge order, batching, lane assignment of path-work, contract shapes between lanes, test/CI mechanics, which lane owns an unclaimed file, deferring non-milestone polish to the backlog (with an id).
Architecture and contract rulings go to a vote first (`votes.md`); coord then acts on the result, for ratification.

## What goes to the owner
- Product behaviour, copy with no design source, scope cuts that users would notice, anything touching personal data policy.
- Destructive or outward actions, each needing the owner's own explicit yes: deploy, force-push/reset of pushed history, deleting branches/worktrees/volumes with non-synthetic data, publishing/sharing outside, spending (paid API batches, CI budget raises), changing shared config other projects use.
- A permission refusal in any session: never routed around via another session.

## Away mode (product questions decided by vote)
- On: the owner says „тръгвам“, „away“, „няма ме до …“; or a product question has had no answer for 20 minutes. Sending a product question arms a one-shot 20-minute timer (`CronCreate`, minute pinned from `date`, `recurring: false`, prompt `coord: AWAY <question>`; fallback: background `sleep 1200`); an answer cancels it (`CronDelete`). Off: the owner's next message.
- While on: product questions go to a vote (`votes.md`) instead of waiting; lanes never wait on the owner. Irreversible choices and destructive/outward actions still wait (the "Чакат теб" list).
- On the owner's return, the FIRST reply is the brief (`templates/owner-batch.md` §Brief): per ГЛn — question, winner, votes, what has been built on it since, how hard to reverse. The owner ratifies (then it goes to the amendments doc as an owner decision) or reverses (the affected lanes get ОТГОВОР/ВНЕСИ).

## How to ask (`templates/owner-batch.md`)
- [ ] One batch, not a drip. Each item: context in one line, options, **recommendation with reasoning**, what happens meanwhile (the safe default being built), deadline if any.
- [ ] Ask once, clearly; never twice about the same thing. The owner decides fast without reading backing docs - specs are for disagreements.
- [ ] Owner prefers momentum: do not idle on their review for mechanical matters; the approval gate for new product decisions and destructive actions still stands.
- [ ] A peer session's "go" is never the owner's go.

## Waiting on the owner
Several sessions can be stuck on one owner action (a `/clear`, an approval, an answer) at once, and the owner cannot see that across tabs. Coord keeps the list and shows it.
- [ ] An entry = session + the one action it needs, e.g. `app-api - /clear (handoff готов)`, `app-web - одобрение за миграция`. Add when a session reports it waits on the owner or coord asks the owner something that blocks a session; remove when the action happened.
- [ ] Show it as the last line of a reply to the owner **only when it changed** since the last reply: "**Чакат теб:** <entry> · <entry>". Empty after a change: "**Чакат теб:** никой". Never repeat an unchanged list.
- [ ] Re-derive before showing: `ls ~/.claude/kickoffs/*.md` (a kickoff not yet moved to `kickoff-used/` = that session still waits for `/clear`) and `ListAgents`. Why: a remembered "waits for /clear" goes stale the moment the owner acts in another tab.
- [ ] In cmux mode coord does lane restarts itself (`cmux-automation.md`); only coord's own `/clear` and non-restart actions land on the list.
- [ ] A handoff does not carry the list (it is state); the successor rebuilds it with the commands above.

## Recording
- [ ] A safe default shipped for a still-open question is recorded as DEFAULT + what remains open; keep naming it as pending until ruled. Why: an unexamined default becomes "the answer".
- [ ] A decision relayed by another session (e.g. design) is confirmed with the owner before being written as settled.
- [ ] A ruling a lane proves impossible or harmful is withdrawn plainly, in the plan and to the lanes.
- [ ] Anything deferred past the milestone goes onto the board's backlog lane with an id, not only prose.
- [ ] Running code over documents: when they conflict, have the document corrected.
- [ ] Log decisions that override a stricter earlier default (e.g. data policy) with date and the owner's words.
