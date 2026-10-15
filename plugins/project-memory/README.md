# project-memory

Committed project memory for Claude Code. Durable rules about the code — traps,
verification recipes, invariants the code depends on, settled decisions — live in the
repository, one topic per markdown file, are committed and reviewed with the code, follow
the branch, and reach the whole team. Personal memory stays in Claude Code's own auto memory.

## Layout in a project

```
.agent-memory/
  README.md                 # path-less rule: the write rules; excluded from health
  <topic>.md                # one topic per file; no subdirectories
.claude/rules/project-memory -> ../../.agent-memory     # committed relative symlink
```

Claude Code loads `.claude/rules/**/*.md` itself. Through the symlink, a memory file without
`paths` loads at session start, and a file with `paths` loads when a matching file is read
or edited. Writes go to `.agent-memory/`, outside the protected `.claude/` directory.

A memory file:

```markdown
---
name: pty-install-scripts
description: Read before debugging the pty spawn helper or adding install steps.
paths:
  - src/terminal/pty.ts
  - docs/terminal.md
---

- The pty package's install scripts do not chmod the macOS prebuilt spawn helper. ...
```

`name` equals the filename stem; `description` is one line of at most 160 characters that
says when the file is worth reading; `paths` is optional, a YAML list of globs.

## Use

1. Install the plugin, then run `/project-memory:memory-init` at the repository root. It
   creates `.agent-memory/`, its `README.md` with the write rules, and the symlink — only
   what is missing. Creating the symlink inside `.claude/` asks for approval once. When
   `.claude/` is git-ignored, it prints the `!.claude/rules/project-memory` line to add to
   `.gitignore`.
2. Commit the paths it lists, then start a new session.
3. Work as usual. The main session writes a memory file when what it learned cost a cycle or
   contradicted an assumption and will still be true next month, and it tells you which.
   There is no limit on how many files one session writes. Subagents never write memory; they end their reports
   with `Memory candidate: <one line>` items for the main session to decide on. The rules
   are in `.agent-memory/README.md`, so teammates without the plugin get them too.
4. At session start the plugin checks the memory. It is silent when all is well. It prints
   one line when the layout does not fully load (for example a session started in a
   subdirectory, where path-scoped rules do not load) or when the health is `due` or
   `overdue`.
5. Run `/project-memory:memory-defrag` when the health asks for it. One general-purpose
   subagent merges, splits and trims the files; the skill then deletes the files it emptied
   and shows the full diff. Run it on its own branch when working with a team, and start a
   new session afterwards to load the new rules.

The plugin never commits. Commit the memory yourself, or ask the session to.

Health uses the file state only: `due` at 30 files, a file over 8 KB, any format violation,
or 16 KB of always-on files; `overdue` at a file over 32 KB or 32 KB always-on.

The plugin does nothing in a repository without `.agent-memory/`.

## Review it like CLAUDE.md

`.agent-memory/` holds instructions with the same power as CLAUDE.md: every file in it is
loaded into sessions as a rule. Review changes to it like changes to CLAUDE.md, and add it
to CODEOWNERS next to `.claude/`:

```
/.claude/           @your-team/leads
/.agent-memory/     @your-team/leads
```

A wrong rule is rejected in review like any other change.

## Not covered in 0.1.0

- `claude -p`, CI and other headless runs.
- Windows checkouts (symlinks need `core.symlinks`).
- Per-repo thresholds; the numbers above are fixed.
- The symlink is the one part a Claude Code release can break silently. Re-run the manual
  gate in `tests/manual/project-memory-gate.md` after a Claude Code update.

## Attribution

The defragment prompt, the write trigger, the format rules and the health thresholds are
ported from the memory system of [worca-cc](https://github.com/SinishaDjukic/worca-cc)
(`src/core/memory-store.mjs`, `src/core/memory-sync.mjs`,
`agents/worca-cc-memory-defragmenter.md`), used under the MIT License:

```
MIT License

Copyright (c) 2026 Sinisha Djukic

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
