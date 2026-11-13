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
4. [ ] Tell the owner one line: "Context is at Nk - handoff at <path>; type /clear, then `/coord`" (a lane: "/clear, then `/coord lane`"; a session not using the skill: "/clear, then `go`"). Stop.
5. The owner types `/clear`, then that first message - it starts the turn and, for `/coord`, loads the skill. The `kickoff-on-clear.py` hook (SessionStart, matcher `clear`) injects the file and moves it to `kickoff-used/`. Injected context does not start a turn - the owner's message does.

Steps 3-5 are the `/clear` path. When this session runs in Supacode or cmux, [Successor terminal](#successor-terminal) replaces them, and they stay its fallback.

## Successor terminal
The successor starts in a NEW tab of the same terminal, under a new name, and the old session stops after a STARTED → ACK handshake. Not for a lane or the design/prototype session of an `automation: cmux` project: coord restarts those in place (`cmux-automation.md`).

Which terminal (`scripts/successor-tab.py` decides, the boundary hook detects the same way): `successor_terminal` in the owner's `~/.claude/captain/config.json` when that file has the key (`supacode`, `cmux`; any other value means `/clear`); otherwise Supacode when this session runs in it (`TERM_PROGRAM=supacode`, `SUPACODE_WORKTREE_ID` set, `supacode` on PATH), else cmux (`CMUX_SOCKET_PATH` set, the cmux CLI found), else the `/clear` path. The file is only read; without it the detection decides.

After steps 1-2 of How, instead of steps 3-5:
1. [ ] Send nothing to lanes and dispatch no agent from here until step 5 or a fallback: two sessions must never hold one role.
2. [ ] Names. `ListAgents` (load it with `ToolSearch` when deferred): the header "This session is <name>" is FROM. The successor, NEW: FROM without a trailing `-r<N>`, plus `-r<N+1>` (`-r2` the first time), with the config's `session_prefix` in front when NEW does not start with it yet, and not already listed. Settle NEW, prefix included, before the kickoff is written: the script also adds a missing prefix, so a NEW without it would start under a name the kickoff does not carry. Both must match `[A-Za-z0-9][A-Za-z0-9._-]*`; a name with spaces → the `/clear` path.
3. [ ] Write the kickoff (step 3's template, with its successor-tab line; "you ARE NEW, the successor of FROM") to `~/.claude/kickoffs/successor/<FROM>.md`. The subdirectory matters: `kickoff-on-clear.py` reads only `~/.claude/kickoffs/<name>.md`, so a later `/clear` in the old session cannot start a second successor from it. The script refuses a kickoff placed directly in `~/.claude/kickoffs/`.
4. [ ] Run ONE command (DIR: this session's absolute working directory):
   ```sh
   python3 '<skill dir>/scripts/successor-tab.py' --dir='<DIR>' --kickoff="$HOME/.claude/kickoffs/successor/<FROM>.md" --from='<FROM>' --name='<NEW>'
   ```
   It is a thin wrapper around the utils plugin's `new-session-tab.py` (skill `utils:new-session-tab`, at least 0.5.0, the highest version under `~/.claude/plugins/cache/*/utils/`). That script opens the tab ALWAYS with `-w` (the Supacode worktree that contains DIR; cmux: an unfocused surface in this workspace), keeps the tab command pure ASCII with all free text in the prompt file (`claude -n NEW "$(cat <file>)"`; Supacode's `-i` garbles UTF-8), mirrors the permission mode, and puts a handshake paragraph in front of the kickoff: the successor's first act is `STARTED <NEW> pwd=<dir>: ...` to FROM. The tab first writes the marker `<NEW>.alive` next to the kickoff; it waits up to 20 s for it. The last line is the result:
   - `TAB-OK <tab> <worktree|workspace|-> <NEW> mode=<mode> prompt=<path>` → step 5. A shell ran in the tab; that is not yet proof that claude started.
   - `TERMINAL-NONE <reason>` → the fallback, no line about it.
   - `FAILED <CODE> <detail>` → the fallback and one line to the owner with the code. `FAILED NO-UTILS ...; owner: claude plugin install|update utils@<marketplace>`: no tab was opened; the line carries that command. `FAILED TAB-DEAD <tab> in=<where> after=<N>s closed=yes|no`: the tab opened but nothing ran in it (e.g. the display was off); the script closed it, and with `closed=no` the owner gets the close command. `TAB-ELSEWHERE` and the other errors after a tab may exist: STAND-DOWN first (step 5), plus the close command.
   The close command names the tab, and only the owner runs it: Supacode `! supacode tab close -w <worktree id> -t <tab id>`, cmux `! cmux close-surface --surface <ref>`. The script closes only a tab it opened in the same call that never wrote the marker.
5. [ ] Wait for `STARTED <NEW> pwd=<dir>`; it arrives on its own. Arm one fallback: a background `sleep 180`, then stop polling.
   - `pwd` equals DIR (after symlinks) → step 6.
   - `pwd` differs → `SendMessage` NEW `STAND-DOWN <NEW>: wrong directory`, the close command to the owner, the fallback.
   - No STARTED when the sleep ends → `SendMessage` NEW `STAND-DOWN <NEW>: no STARTED in 3 minutes`, the fallback, and the close command to the owner. A STAND-DOWN that fails as *not reachable* means no successor exists: do not retry, go on with the fallback.
   Every fallback after a tab may have opened sends that STAND-DOWN first: after `/clear` this session no longer knows NEW.
6. [ ] `SendMessage` NEW: `ACK <NEW>`, plus, verbatim, every owner instruction given since the handoff was written. Stop the fallback sleep. Tell the owner one line, then stop: "Context is at Nk - handoff at <path>; successor <NEW> confirmed in <pwd>; this tab can be closed".
7. After ACK the successor tells every live peer its new name in one line (`NAME <FROM> -> <NEW>`; coord: each live lane and the design session; a lane: coord), since they address it by name. Coord updates the session table in the config: its own row, or the lane's row when a lane tells it.

**Fallback** (`/clear` path): the kickoff must fit the cleared session, which keeps the name FROM and has no one to send it ACK. Write it to `~/.claude/kickoffs/<FROM>.md` with "you ARE <FROM>" and WITHOUT the successor-tab paragraph, delete `~/.claude/kickoffs/successor/<FROM>.md`, then steps 4-5 of How.

**Why:** a successor tab opened without `-w` landed in another project's focused worktree and started a second session on the same handoff; a non-ASCII `-i` command arrived garbled; a tab opened with the display off had no terminal while the CLI still printed a tab id, so a plain TAB-OK hid a dead tab. Hence `-w`, the prompt in a file, the alive marker and TAB-DEAD.

## Name swap (coord, or any session replaced by a NEW session under the SAME name instead of /clear)
A successor under a new name (`-r<N>`, [Successor terminal](#successor-terminal)) needs no swap.
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
- A session cannot `/clear` itself, and self-driving its own terminal is blocked by the auto-mode classifier (tested). The manual design is one cheap human action (`/clear` + first message). Opening a NEW tab for a differently-named successor is a different action ([Successor terminal](#successor-terminal)): the owner only closes the old tab.
- **cmux: coord restarts lanes in place (verified on a live lane, adopted as an option).** Coord types `/clear` + `/coord lane` into an idle lane's tab; the session keeps its name and tab. Coord never drives its own tab: its own handoff opens a successor tab ([Successor terminal](#successor-terminal)), with the manual `/clear` as the fallback. See `cmux-automation.md`.
