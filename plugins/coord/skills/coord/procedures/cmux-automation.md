# cmux automation (optional): coord opens and restarts lane sessions itself

Only when the owner runs the sessions in **cmux** (`CMUX_SOCKET_PATH` is set; CLI at `$CMUX_BUNDLED_CLI_PATH`, usually `/Applications/cmux.app/Contents/Resources/bin/cmux`). Anywhere else: the manual path (`/clear` + first message by the owner) in `handoff-and-sessions.md`.

Status: verified on a live lane (coord restarted a lane after its handoff; the owner confirmed it continued from its kickoff).

What it does: coord types into a lane's terminal tab exactly what the owner would type - `/clear`, then `/coord lane`. The sessions stay ordinary visible tabs with their names; nothing runs in the background.

## Enable (once per project)
- [ ] The owner says yes to this mode explicitly; record it in the config (`automation: cmux`).
- [ ] The owner allows coord's `cmux send` / `send-key` / `new-surface` / `read-screen` commands if the permission mode asks. If the auto-mode classifier refuses an action on a live lane, stop and tell the owner - never route around it, never ask another session to do it.
- [ ] First real use in the project happens with the owner watching.

## Open a lane session (bootstrap, or a lane that is not running)
```sh
C="${CMUX_BUNDLED_CLI_PATH:-cmux}"
S=$($C new-surface --type terminal --focus false | awk '{print $2}')   # e.g. surface:103
$C send --surface "$S" "cd <worktree> && claude -n <session name> '/coord lane'"
$C send-key --surface "$S" Enter
```
- [ ] Write the kickoff file first (`~/.claude/kickoffs/<session name>.md`); `/coord lane` reads it on a fresh session.
- [ ] Record `<session name> → <surface ref>` in the config's lane table; refs change when tabs are closed - re-list with `$C list-pane-surfaces` (tab titles carry the session name) before each use.
- [ ] Verify with `$C read-screen --surface "$S" --lines 20` that the name shows in the prompt box and the session started.

## Restart a lane after its handoff (replaces the owner's `/clear` + message)
Applies to every sprint session in the config's session table except coord itself: lanes and the design/prototype session. The first message after `/clear` is the one the owner would type: `/coord lane` for a lane, `/coord design` for a design session that uses the skill, „давай“ for a session that does not (its kickoff is injected by the hook). Why: a design session without the skill was once left to the owner because only `/coord lane` was allowed.
Preconditions, all of them:
- [ ] The session sent its handoff line to coord ("handoff в <path>; kickoff готов").
- [ ] `~/.claude/kickoffs/<session name>.md` exists and is fresh (minutes, not hours).
- [ ] The lane is idle: `ListAgents` shows it idle AND `read-screen` shows an empty prompt with no "esc to interrupt". Why: `/clear` typed into a busy session wipes its working context mid-task. The lane's "ГОТОВ ЗА CLEAR" is not idle: Stop hooks still run after its last reply ("Working… running Stop hooks", `ListAgents` shows `shell`). Subscribe with `SendMessage(to=<lane>, notify_when_idle=true)` (no message) and send `/clear` after the notice.
Then:
```sh
$C send --surface "$S" "/clear";       $C send-key --surface "$S" Enter
# wait until read-screen shows the line "❯ /clear" (poll, do not sleep blindly; took ~2 s on the first live restart)
$C send --surface "$S" "<first message>"; $C send-key --surface "$S" Enter   # /coord lane | /coord design | давай
```
- [ ] Confirm with `read-screen` that the kickoff was picked up (the session names its handoff files). On the first live restart the lane was already reading its handoff 40 s after `/coord lane`; no permission prompt appeared on either side, no retry was needed.
- [ ] Tell the owner one line: "Рестартирах <name> след handoff (Nk → нов контекст)."

## Hard limits
- **Only coord** drives other tabs, and **only** `/clear`, the first message above (`/coord lane`, `/coord design`, or „давай“ for a session without the skill whose fresh kickoff exists) and the start command above. Never task content, never answers to a session's questions, never `/exit` on a live lane. Why: typing into another session's terminal acts with the owner's authority.
- **A session never drives its own tab.** The auto-mode classifier blocks self-driving (tested: a session scheduling its own `/clear` was refused as "self drive"). Coord's own handoff stays manual: coord writes its kickoff and asks the owner for `/clear` + `/coord`.
- **Never two live sessions with one name.** Opening a successor in a NEW tab while the old one lives is forbidden; restart in place (same tab) instead.
- A lane never uses these commands - not on coord, not on another lane.

## Traps
- The tab title shows a status glyph before the name (`✳ app-design`, `◑ app-coord`); match on the name, not the whole title.
- The subagent panel under the prompt ("◯ general-purpose … 32m 31s") survives `/clear`, so a cleared tab looks almost unchanged. Check for the "❯ /clear" line, not for an empty screen. A frozen timer in that panel means the subagent finished; it is not a sign the session is busy.
- `close-surface` may print the ref of the newly focused tab; re-list to confirm what was closed.
- A background shell started by a session survives `/clear` in that tab; check `derive-state.sh` "RUNNING in checkout" before restarting a lane that ran long tests.
