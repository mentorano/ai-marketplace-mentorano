---
name: new-session-tab
description: Use when the user asks to open a new terminal tab with a new Claude Code session, or to write a handover prompt and start a new session from it — usually because the context is full — e.g. "write a handover prompt and start a new session", "open a new tab with claude", "continue in a new session". Opens a Supacode or cmux tab that runs `claude -n <name> "$(cat <prompt file>)"` in the given directory and reports TAB-OK only when a shell ran in it.
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
   the absolute path of that file.
4. Tell the user the result line. On `TAB-NONE`, or a `FAILED` from before any tab opened
   (`BAD-*`, `NON-ASCII`, `NO-*`, `NOT-IN-A-SUPACODE-WORKTREE`, `MARKER`), give them the
   command to paste into a new tab of their own:
   `cd '<dir>' && claude -n <name> "$(cat '<prompt file>')"`. After any other `FAILED`
   (`TAB-ELSEWHERE`, `TAB-DEAD`, `TAB-NEW-FAILED`, `SUPACODE-ERROR`, `CMUX-ERROR`) a tab may
   exist and its session may already run: have the user check
   that tab and close it (and stop any session in it) before a second start, never two
   sessions on one handover.

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
  --dir=<abs dir> --prompt-file=<abs file> --name=<session name> \
  [--terminal=auto|supacode|cmux|none] [--permission-mode=<mode>] [--wait=20] [--fresh-worktree]
python3 "${CLAUDE_PLUGIN_ROOT}/skills/new-session-tab/scripts/new-session-tab.py" --version
```

`CLAUDE_PLUGIN_ROOT` is this plugin's directory. Run it with the Bash tool directly.

- `--terminal=auto` (default): Supacode when this session runs in Supacode, else cmux when it
  runs in cmux, else none.
- `--name` becomes `claude -n <name>` and names the alive marker `<name>.alive` next to the
  prompt file.
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

It prints one line; with `--fresh-worktree` and `TAB-OK` one more line comes BEFORE it, so
`TAB-OK` stays the last line: `BOOTSTRAP-CLOSED <tab>`,
`BOOTSTRAP-KEPT setup-script|setup-script-unknown|close-failed <tab>` or
`BOOTSTRAP-NONE no-tab|tabs=<N>|gone <tab>|list-failed`.

- `TAB-OK <tab> <worktree|workspace|-> <name> mode=<mode> prompt=<path>`: a shell ran in the tab.
  It does not prove that claude started or accepted the prompt.
- `TAB-NONE <reason>` (exit 3): no terminal to open a tab in.
- `FAILED <CODE> <detail>` (exit 1), e.g. `FAILED TAB-DEAD <tab> in=<where> after=<N>s
  closed=yes|no`; with `closed=no` give the user the close command:
  Supacode `supacode tab close -w <worktree> -t <tab>`, cmux `cmux close-surface --surface <ref>`.
