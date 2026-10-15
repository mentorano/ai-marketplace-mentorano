---
name: memory-init
description: Use when the user asks to set up, enable, initialise or repair committed project memory in this repository, e.g. "/project-memory:memory-init", "set up project memory", "enable .agent-memory", "repair the project-memory symlink", or when the project-memory session-start line says the layout is broken. Creates `.agent-memory/`, its `README.md` with the write rules and the `.claude/rules/project-memory` symlink, only what is missing. Never commits.
---

# Set up project memory

Project memory lives in the repository, next to the code it describes:

```
.agent-memory/
  README.md                 # path-less rule: the write rules; excluded from health
  <topic>.md                # one topic per file; no subdirectories
.claude/rules/project-memory -> ../../.agent-memory     # committed relative symlink
```

Claude Code loads `.claude/rules/**/*.md` natively, so the symlink makes every file in
`.agent-memory/` a rule: a file without `paths` loads at session start, a file with `paths`
loads when a matching file is read or edited. Writes go to `.agent-memory/`, outside the
protected `.claude/` directory, so they do not raise the protected-path prompt.

## How

One command does the work. It is idempotent: it checks `.agent-memory/`, its `README.md` and
the symlink separately and creates only what is missing.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/memory.py" init --cwd "$(git rev-parse --show-toplevel)"
```

`CLAUDE_PLUGIN_ROOT` is set by Claude Code to this plugin's directory. If it is empty, the
command looks for `/scripts/memory.py` and fails. Check it first with
`echo "$CLAUDE_PLUGIN_ROOT"`; if it is empty, use the plugin directory two levels above the
directory this `SKILL.md` sits in (`<plugin>/skills/memory-init/SKILL.md` →
`<plugin>/scripts/memory.py`).

Run it from the repository root, or pass the root as `--cwd`. In a git worktree the root is
the worktree's own root, and the memory goes there.

## Relay the output

Show the user what `init` printed, as it printed it. In particular:

- what it created and what was already there;
- a refusal: when something foreign already sits at `.claude/rules/project-memory` (a file,
  a directory, or a symlink to another target), `init` refuses to replace it. Do not remove
  it yourself; tell the user what is there and let them decide;
- the `!.claude/rules/project-memory` negation line, when `.claude/` is git-ignored. Without
  it the symlink is never committed and teammates get no memory;
- the `git add` line it prints. Give it word for word; do not rebuild the list of paths.

## The symlink needs one approval

Creating the symlink writes inside `.claude/`, which Claude Code protects. In `default` and
`acceptEdits` mode the user is asked once; approve it. When the permission mode denies it
(for example `dontAsk`), do not look for a way around the protection. Tell the user to run
the command themselves with the `!` prefix in the prompt, with the absolute path filled in,
because `CLAUDE_PLUGIN_ROOT` is not set in their own shell:

```
! python3 <absolute plugin directory>/scripts/memory.py init --cwd <absolute repo root>
```

## End with the next two steps

1. Commit the three paths with the `git add` line `init` printed (`.agent-memory/`, its
   `README.md`, and `.claude/rules/project-memory`), then commit. The user commits, or you
   commit only when the user asks. The plugin never commits.
2. Start a new session at the repository root. The current session scanned `.claude/rules/`
   before the symlink existed, so it has not loaded the memory.

Say also, in one line: `.agent-memory/` holds instructions with the same power as
CLAUDE.md, so it should be reviewed like CLAUDE.md and listed in CODEOWNERS next to `.claude/`.

## What you do not do

- Do not commit, push or open a pull request.
- Do not write memory topic files here; `init` creates only the layout and the README.
- Do not create the symlink with an absolute target or point it outside the repository;
  only the relative in-repo link is known to load.
- Do not edit `.claude/settings.json` or any permission rule to avoid the prompt.
