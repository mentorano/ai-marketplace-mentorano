---
name: captain-setup
description: Use when the captain skill finds no ~/.claude/captain/config.json, or the user asks to set up or change captain notifications, tools or dev targets, e.g. "/captain:captain-setup", "change how captain notifies me". Detects codex, agy and msg-notify, asks how to notify, when to stay quiet and how long the owner must be away, and writes the per-user config.json and notify.sh wrapper.
argument-hint: ""
---

# captain-setup - per-user notifications and tools for captain

**Language:** every user-facing line is in the user's language. Software terms stay in English,
uninflected; commands, paths and errors are verbatim.

Output: `~/.claude/captain/config.json` and `~/.claude/captain/notify.sh`. Nothing else changes.
Asked only to add a dev target (the captain calls it so, or the user asks): run section 5 alone.

## 1. Detect

Run each check exactly in these forms; the captain audit allows nothing else. Do not guess.

- codex: `command -v codex`, then `codex --help >/dev/null 2>&1`.
- agy: `~/.local/bin/agy --help >/dev/null 2>&1`; if that fails, `command -v agy`, then
  `agy --help >/dev/null 2>&1`.
- A tool counts only when its `--help` exits 0.
- msg-notify (the directory `~/.claude/skills/msg-notify/`): Read
  `~/.claude/skills/msg-notify/SKILL.md`; if it is missing, msg-notify is not there. Take the
  `notify.sh` path that file names (expand `$HOME`) and check it with `stat -L <path>`: it
  counts only when it exists and is executable. Keep the absolute path.
- supacode: `command -v supacode`; it counts when that prints a path. No `--help` call.
- cmux: `command -v cmux`; it counts when that prints a path. No `--help` call. (cmux's bundled
  CLI may be missing from PATH; the owner can still pick the cmux option by hand in question 5.)

## 2. Ask

Use AskUserQuestion, one question per call, in the user's language. Mark the recommended option
"(recommended)".

1. "How should I notify you when the Captain is waiting for a decision or the report is ready?"
   - `msg-notify` — only when detected; recommend it then.
   - "My own shell command" — the user types one line; `{message}` marks where the message
     goes, unquoted (the wrapper quotes it). Without `{message}` the message is the last
     argument. Recommend it when msg-notify is missing. The wrapper runs the command with
     `eval`, but only after `{message}` becomes the literal `"$1"`, so the message itself is
     never parsed as shell code.
   - "No notifications (chat only)" → method `none`.
2. "Quiet hours with no notifications?" (skip when the method is `none`)
   - "22:00–06:00" (recommended).
   - "No quiet hours".
   - "Another window" → ask for `HH:MM–HH:MM`; a window may cross midnight. Hours must be
     00–23 and minutes 00–59; reject anything else (e.g. `24:00`) and ask again.
3. "Notify only when you are away from the computer?" (skip when the method is `none`)
   - "Yes, after 15 minutes without activity" (recommended) → `15`. The wrapper returns at once and
     waits in the background; any keyboard, mouse or trackpad input in the 15 minutes after
     the event drops the message, because the owner is at the computer and sees the chat.
   - "No, at once" → `0`.
   - "Another number of minutes" → ask for a whole number 1–120; reject anything else and ask again.
   The check reads macOS `HIDIdleTime`. Where the idle time cannot be read, the wrapper sends
   at once, as with `0`.
4. "At what context size should I offer a handoff to a new session?" (optional; the
   default is fine)
   - "45% of the model's context" (recommended) → `"45%"`. It follows the model: 450k on a 1M
     window, 90k on a 200k one, and it changes by itself if the model's window changes.
   - "Another percentage" → ask for a whole percentage from 10 to 90; write it as `"<N>%"`.
   - "A fixed number of tokens" → ask for tokens (`150000`, or `150k`); a whole number from 50000
     to 900000; reject anything else and ask again.
   The plugin hooks `hooks/handoff_at_boundary.py` and `hooks/kickoff_on_clear.py` use it (R21,
   `reference/handoff.md` of the captain skill); they need nothing else from this setup.
5. "Where should the new session start on a handoff?" (skip it when neither supacode nor cmux was detected,
   and leave the key out)
   - "In a new Supacode tab in the same directory" (recommended) → `supacode`. A `captain:runner`
     opens the tab with the successor's `/captain resume`; the old session stops only after the
     new one confirms; the owner types nothing.
     Needs a Supacode that fails `tab new` when the display is off: one whose Ghostty contains
     `a177ba90a` (upstream, or a fork that carries that fix). Other builds still work; the successor-tab script then catches the dead tab. No
     version check runs here.
   - "In a new cmux tab in the same workspace" → `cmux` (recommend it instead of the Supacode option
     when only cmux was detected). Same flow; the tab opens in
     this session's workspace without taking focus.
   - "I type /clear and `/captain resume`" → `none`.
   Only `supacode`, `cmux` and `none` exist now; other terminals (tmux, iTerm, Warp) would be new values
   of the same key. The setting is per user: a colleague on another laptop may use another
   terminal. With no key, a session that runs in Supacode still gets a Supacode tab, and one that runs in
   cmux a cmux tab (`reference/handoff.md` of the captain skill); `none` turns that off.
6. "Should I put `command` before `rm`, `cp` and `mv` in the commands I give you for `!`?"
   - "Yes" (recommended) → `true`. `command rm` skips a shell alias (e.g. `rm -i`) that would
     stop a pasted command on a prompt, and works the same without one.
   - "No, I have no such aliases" → `false`.
   The captain's `!` command rules use it (`reference/queue.md` of the captain skill). No
   detection command runs for it.

## 3. Write

1. `~/.claude/captain/config.json` with the Write tool, exactly this shape:
   `{"version":1,"notify":{"method":"msg-notify|command|none","quiet_hours":{"from":"22:00","to":"06:00"},"away_minutes":15},"tools":{"codex":true,"agy":false},"context_threshold":250000,"successor_terminal":"supacode|cmux|none","shell":{"command_prefix":true},"updated":"YYYY-MM-DD"}`.
   No quiet hours → `"quiet_hours":null` (that means no quiet hours). Method `none` →
   `"away_minutes":0`. `context_threshold` is the answer to question 4, a string like `"45%"`
   or a number of tokens; question 4 skipped → `250000`.
   `successor_terminal` is the answer to question 5; question 5 skipped → leave the key out.
   A config without it means: a Supacode tab when the session runs in Supacode, a cmux tab when it
   runs in cmux, else `/clear`. `shell.command_prefix` is the answer to question 6 (`true` or
   `false`); a config without it means `true`. So `version` stays 1. `updated` is today. An
   existing config's `dev_targets` is kept unchanged (section 5); a new config has none.
2. `~/.claude/captain/notify.sh`: read `notify.sh.tmpl` next to this file, replace every
   placeholder, then Write it and run `chmod +x ~/.claude/captain/notify.sh`.
   While captain mode is on, the guard denies main this Write: hand the rendered file and the
   `chmod` to one `captain:runner`; config.json and the test ping stay with main.
   - `@@METHOD@@` → `msg-notify`, `command` or `none`.
   - `@@QUIET_FROM@@`, `@@QUIET_TO@@` → `HH:MM`, or empty for no quiet hours.
   - `@@MSG_NOTIFY_SCRIPT@@` → the absolute notify script path, or empty.
   - `@@COMMAND@@` → the user's command line verbatim, or empty. Do not escape it.
   - `@@AWAY_MINUTES@@` → the answer to question 3 (`15`, `0` or the number).
   - No `@@` may remain.
3. Test it (skip for `none`): `CAPTAIN_NOW=<quiet to, or 12:00> CAPTAIN_SEND_NOW=1
   ~/.claude/captain/notify.sh "captain-setup: test"`. The end of the window is outside it,
   so the test is never silenced, and `CAPTAIN_SEND_NOW=1` skips the away check, which would
   otherwise drop the test while the owner sits at the computer.
   Ask whether the message arrived. On failure show the error and go back to question 1.

## 4. Report

Eight lines, in the user's language, then one line: "You can run the setup again with
`/captain:captain-setup`."

```
Notifications: <msg-notify | command `<command>` | none>
Quiet hours: <22:00–06:00 | none>
Only when away: <after N minutes without activity | no, at once>
Tools: codex <yes|no>, agy <yes|no>
Handoff at context: <N>k tokens
New session on handoff: <Supacode tab | cmux tab | /clear by you | by terminal (no setting)>
`command` before rm/cp/mv: <yes | no>
Files: ~/.claude/captain/config.json, ~/.claude/captain/notify.sh
```

## 5. Dev targets (optional, `dev_targets`)

Commands or scripts the user allows a captain run to execute against a dev or test
environment (captain `reference/queue.md`, dev targets). Never asked in a first setup unless the
user brings it up; added when the user asks or a captain run proposes an entry.

1. One AskUserQuestion per entry, with the entry shown in full: the repository key, the exact
   command or script, and the endpoint, account or project it must hit. Options:
   "Yes, allow it for dev/test" / "No". Never an entry for production, `terraform apply`, shared
   infra or a shared DB: refuse it with one line why.
2. On yes, Write the config with the entry added under
   `"dev_targets":{"<repo key>":[{"id":"DTS1","command":"<exact command>","target":"<endpoint, account or project>","confirmed":"YYYY-MM-DD"}]}`,
   keeping every other key. `<repo key>` is `<owner>/<repo>` from `git remote get-url origin`
   (no scheme, user, host or `.git`); no origin → the absolute git common dir. The `id` takes the
   next free `DTS<n>` in the file. A changed `command` or `target` is a new entry.
3. Report one line: "Dev target DTS<n>: `<command>` → `<target>` (<repo key>)."
