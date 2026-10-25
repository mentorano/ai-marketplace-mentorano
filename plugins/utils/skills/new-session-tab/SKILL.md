---
name: new-session-tab
description: Use when the user asks to open a new terminal tab with a new Claude Code session, or to write a handover prompt and start a new session from it — usually because the context is full — e.g. "write a handover prompt and start a new session", "open a new tab with claude", "continue in a new session". Opens a Supacode or cmux tab that runs `claude -n <name> "$(cat <prompt file>)"` in the given directory, reports TAB-OK only when a shell ran in it, and has the new session message back `STARTED <name>` as its first step.
---

# New Claude Code session in a new terminal tab

Opens a NEW terminal tab (Supacode or cmux) in which a new Claude Code session starts from a
prompt file. For a background session to reach from a phone, use `bg-claude-rc` instead.

## Handover: "write a handover prompt and start a new session"

1. Write the prompt to `./tmp/handover-<topic>-<date>.md` in the repository (`<date>` as
   `YYYYMMDD`, `<topic>` a short slug). Make it self-contained: the goal, what is done (commits,
   files), what is left, open decisions, and the first step. The new session knows nothing else.
2. Pick the session name: `<repo-slug>-<topic>`, letters, digits, `.`, `_`, `-` only.
3. Open the tab with the script below, `--dir` the repository (or worktree) root, `--prompt-file`
   the absolute path of that file. Do not write a "message me when you start" line into the
   prompt: the script adds the handshake (see [The handshake](#the-handshake)).
4. Tell the user the result line. After `TAB-OK`, wait for `STARTED` as in
   [After TAB-OK](#after-tab-ok-wait-for-started). On `TAB-NONE <reason> prompt=<file>`, give them
   the command to paste into a new tab of their own, with that `prompt=` file (the handshake
   copy), then wait for `STARTED` the same way:
   `cd '<dir>' && claude -n <name> "$(cat '<file>')"`. After a `FAILED` from before any tab opened
   (`NON-ASCII`, `NO-SUPACODE`, `NO-CMUX`, `NOT-IN-A-SUPACODE-WORKTREE`, `MARKER`, `BAD-PATH`),
   run the script again with `--terminal=none`: it writes the copy and prints `TAB-NONE` with
   it. The other pre-tab failures (the other `BAD-*` codes, `NO-CLAUDE-PATH`, `HANDSHAKE-FILE`) need their cause fixed
   first; `HANDSHAKE-FILE` means a file of the copy's name that the script did not write, so pick
   another `--name` or move that file. After any other `FAILED`
   (`TAB-ELSEWHERE`, `TAB-DEAD`, `TAB-NEW-FAILED`, `SUPACODE-ERROR`, `CMUX-ERROR`) a tab may
   exist and its session may already run: have the user check
   that tab and close it (and stop any session in it) before a second start, never two
   sessions on one handover. `FAILED NO-REPLY-TO` comes before any tab opens: call `ListAgents` and run the
   script again with `--reply-to=<the name after "This session is">`.

## The handshake

`TAB-OK` proves only that a shell ran in the tab, not that claude started or took the prompt. The
proof is a message from the new session. The script writes `<name>.handshake.md` next to the prompt
file: one paragraph that makes the new session's first step a `SendMessage` to this session, then
the prompt file's bytes unchanged. The tab reads that copy. The new session sends one line,

    STARTED <name> pwd=<its working directory>: <what it starts with>

and goes on with the task at once: it does not wait for an answer. The format is the one of the
captain successor tab, without its wait for `ACK`: a handover is often written because this
session's context is full, and the new session must not stall when the answer never comes.

- The name to answer to is `--reply-to`, else this session's own name, which the script looks up
  in `claude agents --json` by `$CLAUDE_CODE_SESSION_ID`. It is the name `ListAgents` shows as
  "This session is <name>". `FAILED NO-REPLY-TO` means neither worked; no tab was opened. Call
  `ListAgents` and pass that name as `--reply-to`.
- The user's prompt file is never written. A retry rewrites the copy from it, so the copy never
  holds two handshakes, and the fallback command below still starts from the user's own text.
- Not a system prompt (`--append-system-prompt-file`): it would stay for the whole session and
  could ask for `STARTED` again after every `/clear`.
- A prompt whose first word is `/<command>` is a slash command, which works only as the first
  thing in the message. It runs as it is (`HANDSHAKE-NONE slash-command`), and that command has
  to send its own `STARTED`; otherwise do not wait for one. A first word with a second `/`, such
  as `/repo/src/main.py`, or one that exists on disk, such as `/tmp`, is a path, and that prompt
  gets the handshake.
- An existing `<name>.handshake.md` that does not start with the handshake paragraph is not
  overwritten: `FAILED HANDSHAKE-FILE`.
- The permission mode is mirrored (see `--permission-mode`) so that the new session does not hold
  this session's `ACK`, or stop on its own `SendMessage`, for an approval nobody gives.

**Why:** on 2026-10-23 a session opened a new session through this skill and got `TAB-OK`. The
new session sent nothing back, because its prompt did not ask for it, and the only sign of life
was a `waiting` row in `ListAgents`. The owner asked why the new session did not report that it
started, and asked for the handshake on every use of the skill.

## After TAB-OK: wait for STARTED

With `HANDSHAKE <name> reply-to=<reply-to>` before `TAB-OK`:

1. Arm one fallback: a background `sleep 180` (Bash with `run_in_background: true`), then end the
   turn or go on with other work. Do not poll `ListAgents` in a loop. `STARTED` arrives on its
   own, as a cross-session message from `<name>`.
2. `STARTED <name> pwd=<dir>` with `pwd` the `--dir` (after symlinks, e.g. `/private/var`) →
   reply with `SendMessage` to its `from`: `ACK <name>`, plus, verbatim, every instruction the user
   gave since the prompt was written, if any. Stop the fallback (`TaskStop`). Tell the user one
   line: the new session `<name>` started in `<dir>`.
3. `pwd` differs → tell the user; the session works in the wrong directory. Send no `ACK`; ask
   the user whether to stop it (the close command of the tab, below).
4. The sleep ends with no `STARTED` → `ListAgents`, and report to the user what it shows for
   `<name>`:
   - `waiting`: claude runs and waits for the user, e.g. an approval, a trust prompt, or a held
     cross-session message. The user looks at the tab.
   - `busy` or `idle`: claude runs but sent nothing, or the message waits in this session for the
     user's approval. The user looks at the tab.
   - no row: claude did not start or has exited. The shell ran (`TAB-OK`), so the tab is still
     there; the user looks at it and closes it with the close command below.
   Do not open a second tab and do not resend the prompt: never two sessions on one handover. A
   `STARTED` that comes later is handled as in step 2.
5. `ACK` is one line and optional for the new session: it confirms that messages go both ways
   and carries late instructions. Send nothing else to the new session unless the user asks.

With `HANDSHAKE-NONE slash-command` wait only when that command is known to send `STARTED`.
After `TAB-NONE` the same steps apply once the user has pasted the command; there is no tab
the script opened, so on a miss the user looks at the tab they opened.

## New worktree, then a new session in it (Supacode)

`supacode repo worktree-new` always opens its own bootstrap tab in the new worktree; a plain
`tab new` after it leaves two tabs there. So:

1. `supacode repo worktree-new --branch <branch> [--base <ref>] --background`, then find the new
   worktree in `supacode worktree list` (the URL-encoded path with a trailing slash).
2. Write the prompt file as in the handover, inside the new worktree.
3. Run the script with `--dir` the new worktree root and `--fresh-worktree`. After `TAB-OK` it
   closes the bootstrap tab (`supacode tab close -w <worktree> -t <id> --background`), only when
   that worktree held exactly that one tab before `tab new` and the repository has no setup
   script: the setup script runs in the bootstrap tab, so then it prints
   `BOOTSTRAP-KEPT setup-script` and the tab stays.

Use `--fresh-worktree` only right after `worktree-new`, never in a handover: there the calling
session runs in the only tab of its worktree.

## The script

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/new-session-tab/scripts/new-session-tab.py" \
  --dir=<abs dir> --prompt-file=<abs file> --name=<session name> [--reply-to=<this session's name>] \
  [--terminal=auto|supacode|cmux|none] [--permission-mode=<mode>] [--wait=20] [--fresh-worktree]
python3 "${CLAUDE_PLUGIN_ROOT}/skills/new-session-tab/scripts/new-session-tab.py" --version
```

`CLAUDE_PLUGIN_ROOT` is this plugin's directory. Run it with the Bash tool directly.

- `--terminal=auto` (default): Supacode when this session runs in Supacode, else cmux when it
  runs in cmux, else none.
- `--name` becomes `claude -n <name>` and names the alive marker `<name>.alive` and the handshake
  copy `<name>.handshake.md` next to the prompt file.
- `--reply-to`: the name the new session sends `STARTED` to, as `ListAgents` shows this session.
  Without it the script looks it up (see [The handshake](#the-handshake)). Spaces are fine; a
  backtick, a control character or more than 300 characters is `FAILED BAD-REPLY-TO`.
- `--permission-mode` is passed to `claude --permission-mode`; without it the new session gets
  the mode of this one when that is `auto`, `acceptEdits` or `dontAsk`.
- `--fresh-worktree` (Supacode only, opt-in): close the bootstrap tab of a just-made worktree,
  see above. A setup script counts when `supacode worktree script list` has a `setup` row or the
  repository settings (`<repo root>/supacode.json`, else `~/.config/supacode/repos.json`) hold a
  non-empty `setupScript`; `script list` alone does not show it. Unreadable settings keep the tab.

What it keeps from earlier failures:

- The tab command is pure ASCII; all free text stays in the prompt file, read with
  `"$(cat file)"` (Supacode's `-i` garbles non-ASCII text). Every argument is shell-quoted.
- A Supacode tab always opens with `-w`, the longest listed worktree that contains `--dir`;
  without it Supacode uses whatever worktree is focused.
- The tab first writes the alive marker, then starts claude. No marker within `--wait` seconds
  means nothing ran: the script closes that one tab it opened and reports `TAB-DEAD`. It never
  closes any other tab.
- cmux: an unfocused new surface in this session's workspace; `send` and `send-key enter`, no
  `read-screen`. A backslash in the command is refused.

It prints one result line. With `TAB-OK` or `TAB-NONE` one or two lines come BEFORE it, so the
result stays the last line: first `HANDSHAKE <name> reply-to=<reply-to>` (the tab reads
`<name>.handshake.md`) or `HANDSHAKE-NONE slash-command`; then, with `--fresh-worktree` and
`TAB-OK`, `BOOTSTRAP-CLOSED <tab>`,
`BOOTSTRAP-KEPT setup-script|setup-script-unknown|close-failed <tab>` or
`BOOTSTRAP-NONE no-tab|tabs=<N>|gone <tab>|list-failed`. `FAILED` stays one line.

- `TAB-OK <tab> <worktree|workspace|-> <name> mode=<mode> prompt=<path>`: a shell ran in the tab;
  `prompt=` is the file the tab reads. It does not prove that claude started or accepted the
  prompt: `STARTED` does.
- `TAB-NONE <reason> prompt=<path>` (exit 3): no terminal to open a tab in; `prompt=` is the file
  the pasted command reads.
- `FAILED <CODE> <detail>` (exit 1), e.g. `FAILED TAB-DEAD <tab> in=<where> after=<N>s
  closed=yes|no`; with `closed=no` give the user the close command:
  Supacode `supacode tab close -w <worktree> -t <tab>`, cmux `cmux close-surface --surface <ref>`.
