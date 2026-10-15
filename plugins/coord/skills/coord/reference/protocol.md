# Message protocol

Star topology: a lane messages only coord; coord messages lanes and the owner. Messages go by
session name (e.g. SendMessage to `<prefix>-<lane>`). The keyword is the first word. The first line
must be self-contained: a reader who sees only that line knows who, what, and what to do.

Use the keywords exactly as written in the tables - they are grep-able markers, and renaming them breaks old handoffs.

## Lane -> coord

| Keyword | When | Required fields |
|---|---|---|
| **START** | Before the first edit of a slice. | branch; paths it will touch; hotspots/dependency manifests it will touch; migration yes/no. If a hotspot is named, wait for ALL-CLEAR. |
| **LANDED** | Slice ready to merge (template `templates/kacna.md`). | `branch@sha`; base integration sha it merged in (merged, never rebased); files/areas; contract changes (added/changed types, endpoints, enums - name consumers); migration id + head it chained onto, or "none"; checks run WITH exact commands and flags, and counts (passed/skipped + skip reasons); review done (model, findings fixed); NOT done / deferred (with backlog ids); drift (design markers, draft copy, env-only failures); 1-3 steps to try it in the UI. |
| **QUESTION** | A contract or product question the running code does not answer. | the question; options; the lane's recommendation; what it does meanwhile. Label forwarded non-decisions: "OPEN question for <owner/coord> - choose no behaviour yet". |
| **BLOCKED** | Cannot continue. | what blocks; evidence; who/what would unblock; what the lane does meanwhile (or "idle"). |
| **ACCEPTED** | Acknowledges a coord instruction that changes its work (MERGE-IN with a deadline, STOP, a ruling). | what it will do and when. Not needed for plain MERGED. |

## Coord -> lane

| Keyword | When | Required fields |
|---|---|---|
| **MERGED** | Slice merged. ONLY to the owning lane. | `branch@sha` merged as `<integration sha>`; what the lane does next, stated explicitly (next slice / wait / handoff). Never let MERGED double as "start now". Why: a paused lane read it that way. |
| **MERGE-IN** | Integration moved in a way that touches a lane. ONLY to affected lanes. | integration sha; why it affects them (file/contract); deadline: "before your next LANDED" or "now". Means `git merge`, never rebase. Why: the earlier verb "rebase" made a lane ask for force-push. |
| **ANSWER** | Answer to a QUESTION or BLOCKED. | quote the question's first line; the answer; whether it is a coord ruling (for ratification), an owner decision (with its id), or still OPEN. |
| **ALL-CLEAR** | Go-ahead on a hotspot wait after START. | the hotspot; any constraint. |
| **ACCEPTED** | LANDED validated and queued (same word as the lane's ACCEPTED; the sender tells which). | which batch it joins, what else is in it, when MERGED is expected; what the lane does meanwhile. Keeps a lane from idling or re-dispatching CI while coord verifies. |
| **STOP** | Stop editing named paths. | paths; reason; what unblocks. |
| **PARK** | 85 % of a scope's time box (`scope-deadline.md`). | scope; deadline; "finish the current slice, LANDED, start nothing new"; what goes to the backlog. |

Coord -> owner messages are not keyworded; use `templates/owner-batch.md`.

No `SendMessage` in this Claude Code (older version, or the session is not listed by `ListAgents`): write the message as one block starting with the keyword and ask the owner to paste it into the other session. Do not invent another channel (files, git commits).

## When NOT to send

- No FYI to an idle session: every message costs it a full-context turn.
- No MERGED broadcast; no MERGE-IN to lanes the change does not touch.
- No QUESTION when the running code answers it - read the code (or ask coord to).
- A critical-path lane gets only questions about its own code; coord absorbs cross-lane contract traffic. Why: one lane burned most of its context on others' questions before its own work began.
- No status re-sends; the board and git carry status.

## Writing rules

- Quote binding rules verbatim; never add "unless ..." when relaying. Why: an added allowance got the opposite design implemented.
- Mark hypotheses as hypotheses and name what was searched (path, branch) behind any "does not exist".
- A LANDED's text becomes other lanes' instructions: coord builds briefs from it. Write it for a reader who never saw the code.
- Name exact shas and heads, never "the current one".
- At most ~12 lines. Logs, file lists and long reasoning go to a file; the message names its path. Why: measured 21.09-01.10, messages between sessions were ~16% of the context sessions carry and re-read on every turn.
- SendMessage answered "Failed to send": the message has usually arrived (a busy receiver acknowledged late). Never resend the same text - the receiver drops an identical repeat and both sides see a scary notice. If the message expects a reply (LANDED, QUESTION, a task, a MERGE-IN with a deadline) and none has come by the next time you act, send one short, different line ("did you get <keyword> <id>?"). A message that expects no reply (plain MERGED, ANSWER, FYI) gets no follow-up.
