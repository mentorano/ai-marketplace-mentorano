# handoff - a new session continues the run (R21)

The captain stays one captain: the successor is the same role in a cleared session, and
`/captain off` still ends captain mode (R1). The end of the run (R17) is a different event; both
may happen.

## Contents

- [Never mid-operation](#never-mid-operation)
- [When](#when)
- [How](#how)
- [Successor terminal](#successor-terminal)
- [Session name](#session-name)
- [Handoff template](#handoff-template)
- [Kickoff template](#kickoff-template)
- [`/captain resume`](#captain-resume)
- [The hooks](#the-hooks)

## Never mid-operation

Finish or abort a merge before writing a handoff: no staged merge, no unpushed verified batch,
no running verification, no writer running without a recorded hand-back (`notified: yes` in
`run.md`, R14). If the owner forces a handoff mid-operation, the handoff names the operation
("the integration branch is N ahead: merges X, Y; tests not finished") as an open operation,
not as state.

## When

- At a TASK boundary (the next writer is about to start a new task, or a merge is pushed) once
  the context is at or above the threshold: config `context_threshold`, default 250000. Tokens
  (`450000`, `450k`) or a percentage (`45%`): that share of the context window of the model the
  session runs on, as Claude Code reports it (`contextWindow` of a one-word `claude -p` call,
  cached per model for 24 hours by `scripts/measure-context.py`; the hook uses a stale value at
  once and refreshes it in the background), so it follows the model and a change of its window.
  A percentage whose window cannot be learned counts as 250000. Reviews,
  fix rounds and re-reviews are inside a task (R6), not boundaries.
- Measured, never guessed. The hook `hooks/handoff_at_boundary.py` measures it and holds the
  next writer dispatch once; re-issuing the same dispatch goes through when the owner says to
  continue. At a phase change, main asks a `captain:runner` to run
  `python3 <skill root>/scripts/measure-context.py <repo> 24` (the live session, its ctx, `OVER`
  at the threshold); main cannot run it itself (R1).
- At a phase boundary regardless of size: the next work has little to do with what is in the
  window.
- A conflict resolver (the merge conflict prompt) is never held at a boundary: a merge is in
  progress until main's `commit --no-edit`, so the boundary comes after it.
- Why a ceiling: every turn re-reads the whole window.

## How

1. [ ] An agent commits and pushes the finished work through the R5 gate; running agents have
   reported; no merge is staged. A UI group's commits the push gate holds back (no passed UI
   check, `reference/ui-check.md`) are committed, not pushed, and listed in the handoff with
   their SHAs and reason.
2. [ ] Main writes the handoff with `Write` to `./tmp/captain/<run>/handoff-<YYYYMMDD-HHMM>.md`
   from the template below. SELF-CONTAINED: every decision, ruling and lesson from the run's
   earlier handoff that still stands is carried forward, shortened, so the successor reads only
   this file. The run goes on, so every `decisions.md` line that still stands is carried, with
   its `scope` and `source`; a `source: denial` line names the one denied call, never a rule
   (R16). Only at run end (R17) do `scope: run` lines expire; a new run inherits only
   `source: owner` or `scope: permanent` (`reference/queue.md`, decisions.md).
   Never branch positions, "X is merged" or "agent Y is running", anywhere. No "done", "green"
   or sha in §4 and §6: the only SHAs are the §2 `done <sha>` and the held-back commits of
   step 1 (`Held back:` under the header). Put the command that shows the rest.
   An approval gate or a stop appears in the handoff, the kickoff or the `ACK` message only as
   the owner's own words, quoted; routine steps (commit, push of reviewed work to the feature
   branch, the checks) need none.
   Then the self-review (SV1), at once and in this session, before step 3 or the successor
   terminal: the Skill call `utils:self-review` on the written handoff (not in the Skill
   list → the same checks by hand). Its sources: `Read` the written handoff, `decisions.md`,
   `run.md` and `queue.md`; never check from memory. Its checks:
   - files → handoff: every `decisions.md` line that still stands is in §1 or §3, every
     `source: owner` line with a `status:` is a §2 row as the §2 rule asks (a `done <sha>` row
     only in the first handoff after it was done), every held-back commit of step 1 is
     under `Held back:`;
   - window → files: whatever lives only in this window is now in the handoff or in the run
     files: an owner instruction, answer or feedback, a question the owner has not answered
     (§4), a piece of work the owner asked for that is no `## Tasks` row, a lesson (§5), an
     open operation;
   - form: no status outside §2, gates only as quoted owner words, §6 is one concrete action.
   `Edit` in what is missing, then fill the template's `Self-review (SV1):` line with the
   counts. The kickoff text gets its own `utils:self-review` before the runner writes it, with the
   handoff as the source: the newest handoff's absolute path, the first action equal to §6,
   gates quoted. The one-line `ACK` is checked against the same points by eye. It is not a
   review and replaces none (R5).
   Steps 3-5 below are the `/clear` path. When the successor gets a Supacode or cmux tab, they are
   replaced by [Successor terminal](#successor-terminal), and used again as its fallback.
3. [ ] A `captain:runner` writes the kickoff (template below) to `~/.claude/kickoffs/<session
   name>.md`, and ONLY there. Main gives it the kickoff text and the name; the runner needs a
   `Write` permission for `~/.claude/kickoffs/` (R15 step 3; ask the owner once).
4. [ ] Tell the owner one line, in the owner's language, then stop:
   "Context is Nk — handoff at <path>; type /clear, then `/captain resume`".
5. The owner types `/clear`, then `/captain resume`. The kickoff hook injects the file and moves
   it to `~/.claude/kickoffs/kickoff-used/`; the owner's message starts the turn.

A session cannot `/clear` itself. Auto-compaction is rejected: an extra full-context summary
call, and a lingering summary that nobody who knows the next task wrote.

**Why (step 2, 09–11.11.2026):** owner decisions not yet tasks (RSH3, RSH6) vanished from a night
handoff; a run rule born from one denial (NS2) outlived its run; an owner's plain
wording reached writers only as a rule code. Gates: the Why under
the kickoff template.
**Why (self-review, 18.11.2026):** the owner: a handoff must get a self-review, and every output
of a session or an agent is checked at once, in the same context, for what it missed; the review
by a fresh agent stays. A handoff is written when the window is fullest, and what it drops the
successor never learns. The owner chose a real skill for it (`utils:self-review`) over a
sentence in the rule. The line in the file shows the successor that the pass ran.

## Successor terminal

Which terminal the successor gets (`scripts/successor-tab.py` decides; the boundary hook uses the
same rule): config `successor_terminal` `supacode` → a Supacode tab, `cmux` → a cmux tab; `none` →
the `/clear` steps above; NO key → a Supacode tab when this session runs in Supacode
(`TERM_PROGRAM=supacode` and `SUPACODE_WORKTREE_ID` set) and `supacode` is on PATH, else a cmux tab
when it runs in cmux (`CMUX_SOCKET_PATH` set and the cmux CLI found: `$CMUX_BUNDLED_CLI_PATH`, else
`cmux` on PATH), else `/clear`. Supacode wins when both are present. Other values (tmux, iTerm,
Warp) are not implemented and mean `/clear`. A colleague's laptop may use another
terminal, so the setting is per user (`captain-setup`).

With a Supacode or cmux tab, after steps 1-2 and instead of steps 3-5:

1. [ ] Main launches no agent for the run and sends nothing to running ones from here on, until
   step 5 or a fallback. Two sessions must never coordinate one run.
2. [ ] `ListAgents` (load it with `ToolSearch` when deferred): the header line „This session is
   <name>“ gives this session's name, FROM. The successor's name, NEW: FROM without a trailing
   `-r<N>`, plus `-r<N+1>` (`-r2` the first time), not already in the listing. With a
   `session_prefix` in the config, NEW starts with it: the script puts it in front when it is
   missing, and the name on its TAB-OK line is the one to use. Both names must
   match `[A-Za-z0-9][A-Za-z0-9._-]*`; a name with spaces → the `/clear` steps.
3. [ ] A `captain:runner` runs ONE command (DIR: the absolute working directory of this main
   session, not an agent worktree; HANDOFF: the absolute handoff path):

   ```sh
   python3 '<skill root>/scripts/successor-tab.py' --dir='<DIR>' --handoff='<HANDOFF>' --from='<FROM>' --name='<NEW>'
   ```

   The script is a thin wrapper: it writes the prompt file `successor-prompt-<NEW>.md` next to
   the handoff and calls the utils plugin's `new-session-tab.py` (skill `utils:new-session-tab`,
   at least 0.3.0, the highest version under `~/.claude/plugins/cache/*/utils/`), which opens
   the tab ALWAYS with `-w` (the Supacode worktree that contains DIR); with cmux it opens an
   unfocused terminal surface in this session's own workspace (`CMUX_WORKSPACE_ID`), types the
   command and presses enter. The tab runs
   `cd DIR && : > <marker> && claude -n NEW [--permission-mode <this session's>] "$(cat <prompt file>)"`;
   the marker `<NEW>.alive` sits next to the handoff and proves that a shell ran in the
   tab. The script waits up to 20 s for it. It prints one line:
   - `TAB-OK <tab id> <worktree id> <NEW> mode=<mode> prompt=<path>` → step 4 (cmux: `<surface
     ref> <workspace id or ->` instead of the tab and worktree ids). A shell ran in the tab.
   - `TERMINAL-NONE <reason>` → the `/clear` steps 3-5 above, no line about it.
   - `FAILED <CODE> <detail>` → the `/clear` steps 3-5, and one line to the owner with the code
     (`TAB-ELSEWHERE`, `TAB-DEAD`: the STAND-DOWN of step 4 first).
     `FAILED NO-UTILS <why>; owner: claude plugin install|update utils@<marketplace>`: no tab
     was opened; the owner line also carries that command, for the next handoff.
     `FAILED TAB-ELSEWHERE <tab id> in=<worktree id>`: a tab exists in another worktree; also
     give the owner the close command for it.
     `FAILED TAB-DEAD <tab id> in=<worktree id> after=<N>s closed=yes|no`: the tab opened, but no
     marker came in N seconds, so nothing ran in it. The script has closed that tab
     (`closed=yes`); with `closed=no` give the owner the close command. The owner line names the
     cause, e.g. "the successor did not start: the tab opened without a terminal (TAB-DEAD after
     20 s, the tab is closed); the display was probably off — continuing with /clear" (`closed=no`:
     "close the tab with `! supacode tab close -w <worktree id> -t <tab id>`" instead of "the tab
     is closed"). (cmux has no such code; its failures are `NO-CMUX`,
     `CMUX-ERROR`, `TAB-NEW-FAILED` and `TAB-DEAD` with `<surface ref> in=<workspace id or ->`,
     same `/clear` fallback.)
   The close command always names the worktree, since `tab close` without `-w` acts on the
   focused one: `! supacode tab close -w <worktree id> -t <tab id>`. Only the owner runs it: an
   agent's `tab close` may be denied, and a denial is final (R16). The one exception is inside
   the script: it closes a tab it opened in the same call when no marker came (TAB-DEAD), since
   nothing ran there (the owner's decision, 2026-10-07). No agent runs a close command itself.
4. [ ] Wait for the successor's message `STARTED <NEW> pwd=<dir>`; it arrives on its own.
   Arm one fallback: a background `sleep 180` (`run_in_background: true`, like the
   fallback timers in `reference/health.md`). TAB-OK says only that a shell ran in the tab; STARTED
   is the proof that claude runs.
   - `pwd` equals DIR → step 5.
   - `pwd` differs → `SendMessage` NEW `STAND-DOWN <NEW>: wrong directory`; give the owner the
     close command for the tab; the `/clear` steps 3-5.
   - The sleep ends with no STARTED → `SendMessage` NEW `STAND-DOWN <NEW>: no STARTED in 3
     minutes`; then the `/clear` steps 3-5, and one line to the owner with the close command for
     the tab. A session that is still starting gets the message in its queue.
   - A STAND-DOWN that fails with *not reachable* („No agent named … is reachable“) means no
     successor session exists, so nothing waits for it in a queue. Do not retry it and do not
     wait more: go on with the `/clear` steps at once, and say in the owner line that the
     successor never started.
   Every fallback after a tab was opened (TAB-OK, TAB-ELSEWHERE or TAB-DEAD) sends that STAND-DOWN FIRST,
   before the `/clear` steps: after `/clear` this session no longer knows the successor. Every
   STARTED that still arrives before then gets the same STAND-DOWN.
5. [ ] `SendMessage` NEW: `ACK <NEW>`, then every owner instruction given since the handoff was
   written (mode, box, „I am away“), verbatim. End every timer in `run.md` `## Timers`
   (`CronDelete` per job id, `TaskStop` per fallback `sleep` task id, the step-4 sleep too). Tell
   the owner one line, in the owner's language, then stop: "Context is Nk — handoff at <path>;
   successor <NEW> confirmed in <pwd>; this tab can be closed".

The tab command is pure ASCII and all free text lives in the prompt file: Supacode's `-i`
double-encodes UTF-8, so a non-ASCII prompt (Cyrillic text, an em dash) arrives garbled (probe 2026-10-02).
The permission mode is mirrored (auto, acceptEdits, dontAsk; else the default) so the
successor neither stops on approvals at night nor holds cross-session messages.

cmux (verified live on 0.64.25, 2026-10-06). The script runs `cmux new-surface --type terminal
--focus false --workspace $CMUX_WORKSPACE_ID` (prints `OK surface:<n>`), then `cmux send --surface
<ref> <command>` and `cmux send-key --surface <ref> enter`. `send` targets only that ref (`not_found`
when it is not there) and queues the text until the new surface's PTY is up. There is no
`read-screen` check: an unfocused new surface has no PTY yet, so read-screen fails (`Failed to read
terminal text`); that check stopped the first real cmux handoff (2026-10-06, `TAB-NEW-FAILED`). A
failure after the surface was created carries `surface=<ref>`; as with `TAB-ELSEWHERE`, give the
owner the close command, which only the owner runs: `! cmux close-surface --surface <ref>`. A backslash in the command is refused, since `send` turns `\n` into
Enter. A session must not drive its OWN tab; here a runner opens a NEW tab
for a differently-named successor, which is a different action. The owner closes the old tab.

**Why:** 2026-10-01 a runner ran `supacode tab new` without `-w`; Supacode used the focused
worktree, another project's, so a second captain session started in the wrong directory and read
the same handoff. The agent's `supacode tab close` was denied, the CLI cannot type into a running
tab, and the old session could not reach either successor; the owner closed the tab. Probes on
2026-10-02 showed `-w` beats the focus, `claude -n` makes the new session findable in
`ListAgents` within seconds, and messages pass both ways intact.

**Why (2026-10-07):** an away run handed off at 03:49 with the display off. Ghostty could not
create its display link with 0 displays, so the tab's terminal surface was never created;
Supacode still printed a tab id and listed the tab. The script said TAB-OK, no STARTED came, the
STAND-DOWN was „not reachable“, and in the morning the owner found a tab with no terminal. Hence
the marker, TAB-DEAD and the close of that tab. A Supacode build that fails `tab new` in this
case: a Supacode whose Ghostty contains commit `a177ba90a` (upstream, or a fork that
carries that fix); the script then prints `FAILED SUPACODE-ERROR`. On any
other build, and with cmux, the marker is the only guard.

## Session name

The kickoff file is named by the session, never by the directory: two sessions can share a
cwd. The name is the one the owner gave with `/rename`; when the session was renamed later,
the LAST `customTitle` / `agentName` record of its transcript wins. The hook resolves it and
prints it in its denial, so use that name. A session with no name has no kickoff address: ask
the owner "Name the session: `/rename <name>`" before step 3. There is no repo-file fallback.

## Handoff template

```markdown
# <project> - captain handoff, <date> <part of day>

Self-contained: everything from earlier handoffs that still stands is carried into §1-§5,
shortened. Earlier files are for lookup only. **Nothing here is status** except the §2 status
column, whose `done <sha>` a runner checks with `git -C <repo> branch --contains <sha>`.
Re-derive it:

    git -C <repo> status -s && git -C <repo> log -n 10 --oneline   (a runner runs it)
    python3 <skill root>/scripts/measure-context.py <repo> 24      (a runner runs it)
    CronList, then compare with run.md `## Timers`

Held back: <sha> - <reason> per commit the push gate holds (How step 1), or none.
Self-review (SV1): decisions <n> of <n> carried; owner decisions <n> of <n> in §2; added from this window: <items, or none>.

Run dir: ./tmp/captain/<run>/ (run.md, decisions.md, queue.md). Mode, box and deadline (if any): see run.md.
Project memory: the `Project memory` line and `## Memory candidates` stay in run.md; drafts in <run dir>/memory-drafts/.

## 1. Decisions taken (also in decisions.md)
- **<id> - <title>.** <one or two lines: what it binds>.

## 2. Owner decisions
Every owner decision of the run that asks for work (`source: owner` with a `status:` in
decisions.md; this table is its copy; a standing owner rule goes to §3, no status). A
`done <sha>` row appears in the first handoff written after it was done and is left out of
later ones. Main never narrows the owner's agreed scope on its own (R18); a narrowing by the
owner or by R6/TP6 is a `deferred` row here, its reason one of the R18 list.

| ID | the owner's words, verbatim | status |
|----|-----------------------------|--------|
| <id> | "<…>" | `done <sha>` / `deferred to <phase/task>: <reason>` / `open` |

## 3. Rulings and owner answers
- **<id> - <the owner's words, verbatim>.** <what it settled>.
The owner's feedback (text verbatim, their screenshots copied into the run dir, never a temp or clipboard
path): `<run dir>/owner-review-<YYYYMMDD>.md`. Link it; never rewrite those words into rule codes
or summaries.

## 4. Open questions for the owner
1. **<id>:** <question - recommendation - what waits on it>. No "done", "green" or sha: the
   command that shows it.

## 5. Lessons
- **<lesson>.** <the incident in one line, the rule>. An incident, never "do exactly as <X>"
  (a copied pattern spreads a rejected mechanic).

## 6. First action
<the one concrete next step, e.g. "launch the writer for ZD4 with the R3 frame">; no status.
```

## Kickoff template

```markdown
You ARE the <project> captain, the successor of the previous captain session in this run, not a
helper writing for a later one. Invoke `/captain resume` (skill `captain`).

1. Read <abs path of the newest handoff> - it is self-contained; nothing in it is status
   except its §2 status column.
2. Re-derive state before acting: a `captain:runner` runs the commands in its header; `CronList`.
3. Start with: <the first concrete action>.
4. Open owner questions to carry: <ids or "see handoff §4">; owner decisions: handoff §2.
5. Owner gates, quoted: <"…" per gate, or "none">. Routine steps that need no approval: <e.g.
   commit, push reviewed work to the feature branch, run the checks>. A product choice this
   kickoff does not settle: present → ask the owner; away → a panel (R9). R10 outward actions
   and R16 denials still go to the owner.
```

Gates in the handoff, the kickoff and the `ACK` are the owner's, never main's (How step 2).
**Why:** 11.11.2026: kickoff gates the owner never said ("Stop and wait for my choice", "an agent
does X only after my 'yes'") stalled a successor that takes every absolute rule literally.

## `/captain resume`

The run is not new: no bootstrap, no new run directory, no plan.

1. Start steps 1 and 2 only (config, `ToolSearch` of the deferred tools). Captain mode is set by
   `hooks/guard.py` from the prompt itself; the same prompt takes over the predecessor's live
   merge grant and recorded base (same repository and working directory), never a new grant.
   The design assumes one captain run per checkout. A second run there, or a stale one whose
   base is under 12 hours old, may lend its grant or base to the resume. Two or more sessions
   there with a live grant or base → nothing is carried; the owner types `/captain merge <branch>` / `/captain base <branch>` again.
2. Read the handoff the argument names (`/captain resume handoff=<path> from=<FROM> name=<NEW>`,
   from a successor tab) or the kickoff names. Neither in context (hook missing, or the owner typed
   `/captain resume` in another session): `Glob` `tmp/captain/*/handoff-*.md`, take the newest
   by name, and say which one you took.
   With `from=`: before anything else, `SendMessage` FROM one line, `STARTED <NEW> pwd=<this
   session's working directory, as its environment states it>`, then end the turn. Launch
   nothing and arm no timer until `ACK <NEW>` arrives; its owner instructions bind like the
   handoff's. `STAND-DOWN`, also one already queued when this session starts → tell the owner
   one line, "Stopped: <reason>; the run continues in the old session", and do nothing more.
3. Re-arm timers and monitors per the Resume bullet under Timers in `reference/health.md`: `CronList`,
   keep the matching jobs, create the missing ones, record the ids in `run.md`; with a box,
   re-check `date` against park and deadline. Past the last possible hard end (outages and
   extensions counted, `reference/parallel.md`) → R17.
4. Re-derive state through a `captain:runner` (never from the handoff's prose), then do the
   handoff's first action. A handoff with no `Self-review (SV1):` line was not self-reviewed by
   its writer: before the first action, `Read` `decisions.md` and `run.md` in the run dir, take
   from them every standing line and owner decision the handoff lacks, and tell the owner one
   line with what was missing.

## The hooks

Both ship with the plugin (`hooks/hooks.json`) and fail open.

- `hooks/handoff_at_boundary.py` (PreToolUse `Agent|Task`): in a captain session, denies once a
  NEW writer dispatch (`captain:worker`, `captain:light-coder`) whose
  description is not a review, verification, vote, fix, merge or cleanup, when the context is at
  the threshold (env `HANDOFF_CONTEXT_THRESHOLD`, else `~/.claude/captain/config.json`
  `context_threshold`, tokens or a percentage of the model's window, else 250000).
- `hooks/kickoff_on_clear.py` (SessionStart `clear`): injects `~/.claude/kickoffs/<session
  name>.md` and moves it to `kickoff-used/`.
- Log: `~/.claude/captain/handoff-hooks.log`.
