---
name: bg-claude-rc
description: Use when the user asks to start a new Claude Code session in the background to continue there — usually because the current context is full or they are away from the laptop — e.g. "start a new claude in the background", "new session I can continue from my phone", "remote control session", „пусни нов claude в background", „нова сесия да продължа там", „пусни ми claude instance". Starts `claude --bg --remote-control` in the same repository with the name <repo-slug>-<YYYYMMDD>-rc<N> and returns the session link.
---

# New background Claude Code session with Remote Control

The user wants a new, empty Claude Code session in **the same repository**, to open from
the Claude app on a phone or from the web. The session runs in the background on this
machine and is reachable through Remote Control.

## Not a new terminal tab

Do not open a new terminal tab or window instead, even when a terminal tool offers one.
The user usually asks for this because they are away from the laptop, and a tab there is
no use to them. Open a tab only when they ask for a tab.

## How

One script does everything — the name, the start and the link:

```bash
"${CLAUDE_PLUGIN_ROOT}/skills/bg-claude-rc/start.sh"              # slug derived from the repository name
"${CLAUDE_PLUGIN_ROOT}/skills/bg-claude-rc/start.sh" web          # or given explicitly
"${CLAUDE_PLUGIN_ROOT}/skills/bg-claude-rc/start.sh" --dry-run    # only prints the name, starts nothing
"${CLAUDE_PLUGIN_ROOT}/skills/bg-claude-rc/start.sh" --dry-run web   # argument order does not matter
"${CLAUDE_PLUGIN_ROOT}/skills/bg-claude-rc/start.sh" --model sonnet --effort medium   # another model and effort
```

`CLAUDE_PLUGIN_ROOT` is set by Claude Code to this plugin's directory. If it is empty, the
command looks for `/skills/...` and fails. Check it first with `echo "$CLAUDE_PLUGIN_ROOT"`;
if it is empty, use the absolute path of the directory this `SKILL.md` sits in.

**Model and effort.** The default is `--model opus --effort high`. Pass another model or
effort only when the user asks for it: `--model <model>` (an alias such as `opus`,
`sonnet`, `haiku`, or a full model name) and `--effort <level>` (`low`, `medium`, `high`,
`xhigh`, `max`). The form `--model=<model>` works too. An unknown effort stops the script
before it starts anything.

Run it from any directory inside the repository. The session starts in the **git root**
(in a worktree, the root of that worktree), not in the current directory. Outside a git
repository it starts in the current directory and takes the slug from its name. The slug is
`[a-z0-9]` only; any other value, and any unknown option, stops the script before it
starts anything. Underneath it calls:

```bash
claude --bg --remote-control <name> -n <name> --model <model> --effort <level>
```

`--remote-control <name>` is the name in the Remote Control list of the Claude app, and
`-n <name>` is the session name in `claude agents`. They are the same on purpose.

On success the output ends with the lines `name=`, `model=`, `effort=`, `id=` and `url=`,
and the exit code is 0. Give the user the **URL** and the name. The session stays empty
and waits for their first prompt. When `url=` is empty, the session did start but Remote
Control had not shown the link yet; a `note=` line then says where to look (see below).

On failure the script exits non-zero with a `start.sh: …` line on stderr. That happens
when `claude` or `jq` is missing, when `claude agents --json` does not answer (without the
live names the choice of number is blind), or when `claude --bg` fails. Then do not say
the session started. Show the error.

Choosing the number and starting the session run under a lock
(`$TMPDIR/bg-claude-rc.lock`), so two parallel starts never take the same name. If the
lock is still held after 30 s, the script stops without touching it and prints the
`rmdir` command that removes it, for the case where no other start is running.

## The name: `<slug>-<YYYYMMDD>-rc<N>`

- **slug** — a short name for the repository. A name with dashes or underscores becomes
  its initials: `my-web-app` → `mwa`, `data_pipeline` → `dp`. A single word stays, up to 8
  characters: `devops` → `devops`. A leading dot is dropped: `.claude` → `claude`. If the
  initials are ambiguous or ugly, pass the slug explicitly.
- **date** — today, `YYYYMMDD`, taken once.
- **`-rcN`** — N is the **first unused number** for this slug and this date. Taken are the
  names of live sessions (`claude agents --json`, field `name`) and the names of stopped
  sessions from today, which the transcripts keep as `"customTitle":"<name>"` in
  `~/.claude/projects/*/*.jsonl`. The script reads only the transcripts touched today: the
  name carries the start date, and reading every transcript takes minutes.

Example: today already has `mwa-20260922-rc1` and `mwa-20260922-rc2` → the new one is
`mwa-20260922-rc3`.

## Checking and managing

```bash
claude agents --json         # live sessions: name, id, kind=background, status
claude logs <id>             # the session's last screen; the URL is there too
claude attach <id>           # opens the session in this terminal
claude stop <id>             # stops it
```

`claude agents` without `--json` needs a TTY and fails from the Bash tool.

If `url=` is empty after the 20 seconds the script waits, Remote Control is still connecting. Check
again with `claude logs <id>` and look for the session link (it contains `/session_`).
The log is a pty buffer: the URL shows while the session is empty and scrolls away once
it has done some work. The same URL can also be partly redrawn, so the script takes the
longest match. The id after `session_` has no fixed length (24 and 26 characters have
been seen).

## What you do not do

- Do not send a prompt to the new session unless the user gave a task for it. They write
  the first prompt themselves.
- Do not start the session in another repository or worktree unless the user says so.
- Do not reuse a name: two sessions with the same name get mixed up in the Remote Control
  list.
