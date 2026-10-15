# project-memory — manual release gate

Run by hand before project-memory 0.1.0 is announced, and again after every Claude Code
update before memory is trusted. The symlink `.claude/rules/project-memory -> ../../.agent-memory`
is the one part of the layout a Claude Code release can break silently. On a failure of the
loading checks, fall back to copying `.agent-memory/` into `.claude/rules/project-memory/`
from a `SessionStart` hook and record it here.

## Probe repository

1. A scratch git repo with the plugin installed and `/project-memory:memory-init` run.
2. `.agent-memory/plain.md` — no `paths`, a body with a codeword.
3. `.agent-memory/scoped.md` — `paths:` as a YAML list (`src/a.ts`, `lib/**`).
4. `.agent-memory/scoped-comma.md` — `paths: docs/x.md, cfg/*.json` (comma form).
5. Files `src/a.ts`, `lib/b.ts`, `docs/x.md`, `cfg/c.json`.
6. An `InstructionsLoaded` hook logger in the probe repo's `.claude/settings.json` that
   appends each event's `file_path` and `load_reason` to a log file. Optionally also log
   `PermissionRequest` and `PostToolUse` to see the prompts.

"Loads" is checked in the logger output, never by asking the model: a pass needs a log line
with the `.agent-memory/` path and the expected `load_reason`.

## The five checks (per row)

- Г1. **Loads path-less rule** — a log line for `.agent-memory/plain.md` (and `README.md`)
  with `load_reason` `session_start`.
- Г2. **Loads path-scoped rule on Read** — ask the session to read `src/a.ts`; a log line for
  `.agent-memory/scoped.md` with `path_glob_match`.
- Г3. **Write without prompt** — ask the session to create `.agent-memory/new-topic.md`; no
  permission request in `acceptEdits` and `auto` (in `default`, one ordinary prompt is the
  expected result).
- Г4. **Edit existing without prompt** — ask the session to edit `.agent-memory/plain.md`;
  same expectation as Г3.
- Г5. **Delete** — ask the session to delete `.agent-memory/new-topic.md`; same expectation
  as Г3.

Mark each check `pass`, `fail` or `n/a`, with the log line or the prompt seen.

## Rows

### РП1. Interactive CLI at the repo root — `default`, `acceptEdits`, `auto`

One session per mode, started at the repo root.

Claude Code version: ____

| Check | default | acceptEdits | auto |
|---|---|---|---|
| Г1 loads path-less | | | |
| Г2 loads path-scoped on Read | | | |
| Г3 write | | | |
| Г4 edit existing | | | |
| Г5 delete | | | |

Also: the session-start hook prints nothing on a healthy memory, and one `due` line after
adding a file over 8 KB.

### РП2. Interactive CLI started in a subdirectory

Start the session in `src/`.

Claude Code version: ____

| Check | Result |
|---|---|
| Broken-layout warning from the session-start hook (says path-scoped rules do not load) | |
| Г1 loads path-less | |
| Г2 loads path-scoped on Read (expected: does not load) | |
| Г3 write | |
| Г4 edit existing | |
| Г5 delete | |

Also record whether the plugin hook ran at all in a subdirectory session.

### РП3. Desktop app, local session

Claude Code version: ____

| Check | Result |
|---|---|
| Г1 loads path-less | |
| Г2 loads path-scoped on Read | |
| Г3 write | |
| Г4 edit existing | |
| Г5 delete | |
| Session-start hook ran | |
| Skills `/project-memory:memory-init` and `/project-memory:memory-defrag` listed | |
| A general-purpose subagent gets the path-less rule | |

### РП4. A captain worker in `.claude/worktrees/<name>`

A real captain run whose worker works in `.claude/worktrees/<name>`.

Claude Code version: ____

| Check | Result |
|---|---|
| Г1 loads path-less (worker) | |
| Г2 loads path-scoped on Read of `.claude/worktrees/<name>/src/a.ts` (worker) | |
| Г3 write (main session, in the worktree's `.agent-memory/`) | |
| Г4 edit existing (main session) | |
| Г5 delete (main session) | |
| The worker writes no memory and reports `Memory candidate:` lines instead | |

### РП5. A rule edited during a session

Edit `.agent-memory/plain.md` (change the codeword) during a session, then run `/clear` in
one session and `/compact` in another, and ask for the codeword.

Claude Code version: ____

| Check | Result |
|---|---|
| Г1 loads path-less | |
| Г2 loads path-scoped on Read | |
| Г3 write | |
| Г4 edit existing | |
| Г5 delete | |
| After `/clear`: old text, new text, or both in context (logger + answer) | |
| After `/compact`: old text, new text, or both in context (logger + answer) | |

The result decides the wording of step 6 of `/project-memory:memory-defrag`.

### РП6. Multi-glob `paths` in YAML list and comma form

Claude Code version: ____

| Check | Result |
|---|---|
| Г1 loads path-less | |
| Г2 YAML list: Read `src/a.ts` and Read `lib/b.ts` each load `scoped.md` | |
| Г2 comma form: Read `docs/x.md` and Read `cfg/c.json` each load `scoped-comma.md` | |
| Г3 write | |
| Г4 edit existing | |
| Г5 delete | |
