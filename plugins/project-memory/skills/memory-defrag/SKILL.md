---
name: memory-defrag
description: Use when the user asks to defragment, consolidate, clean up or restructure the committed project memory in `.agent-memory/`, e.g. "/project-memory:memory-defrag", "defrag the project memory", "memory is overdue", or after the project-memory session-start line reported the memory health as due or overdue and the user agreed. Dispatches one general-purpose subagent that merges, splits and trims the memory files, then prunes emptied files and shows the full diff. Never commits.
---

# Defragment project memory

`.agent-memory/` holds one topic per markdown file, loaded as rules through the
`.claude/rules/project-memory` symlink. Over time topics overlap, files grow, and the
always-on files (those without `paths`) cost context in every session. A defragment
restructures the files in one reviewable diff: it merges, splits, tightens descriptions and
moves file-specific rules behind `paths`. It never invents rules and never drops one that is
still true.

All commands below use the plugin script:

```bash
MEM="${CLAUDE_PLUGIN_ROOT}/scripts/memory.py"
ROOT="$(git rev-parse --show-toplevel)"
python3 "$MEM" <command> --cwd "$ROOT"
```

`CLAUDE_PLUGIN_ROOT` is set by Claude Code to this plugin's directory. If it is empty, check
with `echo "$CLAUDE_PLUGIN_ROOT"` and use the plugin directory two levels above the directory
this `SKILL.md` sits in. The prompt file for the subagent is `defragmenter.md`, next to this
`SKILL.md` (`${CLAUDE_PLUGIN_ROOT}/skills/memory-defrag/defragmenter.md`).

Shell variables do not survive from one Bash call to the next. Either repeat the `MEM=` and
`ROOT=` lines in every call, or resolve them once and write the absolute paths into each
command. The same holds for `BEFORE` in step 1: print it and reuse the printed path.

Follow the steps in order. Do not skip one.

## 0. Permission mode

- In **plan mode**, refuse: a defragment edits files. Tell the user to leave plan mode and
  run the skill again.
- In **default** mode, say that each memory edit asks once, and suggest switching to
  `acceptEdits` for the run (Shift+Tab). Edits in `.agent-memory/` then pass without a
  prompt. Continue when the user is ready; do not change the mode yourself.

## 1. Take the *before* listing

Save the status as JSON in a temporary file and keep its path for step 4:

```bash
BEFORE="$(mktemp "${TMPDIR:-/tmp}/memory-before.XXXXXX")"
python3 "$MEM" status --json --cwd "$PWD" >| "$BEFORE"
echo "$BEFORE"
```

`>|` overwrites the file `mktemp` just created even when the shell has `noclobber` set.

This one call takes `--cwd "$PWD"`, the directory the session started in, not `$ROOT`:
`status` reports the layout `broken` when the session did not start at the repo root, where
path-scoped rules do not load. Run it before any `cd`. Every other command uses `$ROOT`.

Read the layout and the health level from that file:

- layout not `ok` → stop and give the reason. For a broken layout, suggest starting the
  session at the repo root or running `/project-memory:memory-init`.
- level `fresh` (no memory files) → stop; there is nothing to defragment.
- level `ok` → ask the user whether to run anyway, and stop unless they say yes.
- level `due` or `overdue` → continue.

## 2. Require a clean memory directory

```bash
git -C "$ROOT" status --porcelain -- .agent-memory
```

When it prints anything, ask the user to commit or stash those changes first, so the
defragment diff stands alone and can be reviewed and reverted on its own. Stop until it is
clean.

## 3. Dispatch the defragmenter

Get the brief:

```bash
python3 "$MEM" brief --cwd "$ROOT"
```

Dispatch **one general-purpose subagent** with the Agent tool (`subagent_type:
general-purpose`, no model override: it runs on the session's model). Its prompt is, in
this order:

1. the full text of `defragmenter.md`, read from disk;
2. the line `Memory directory: <ROOT>/.agent-memory` with the absolute path;
3. the output of `memory.py brief` (the `## Memory health` section).

Run it in the foreground and wait for its final message: that message is the report. The
subagent writes nothing outside `.agent-memory/` and no report file. Do not edit memory
files yourself while it runs.

## 4. Prune and re-check — always

Whether the subagent succeeded, failed or stopped half way, run:

```bash
python3 "$MEM" prune --before "$BEFORE" --cwd "$ROOT"
python3 "$MEM" status --cwd "$ROOT"
```

`prune` deletes only files that had content in the *before* listing and are empty now (the
subagent removes a file by emptying it). It never deletes `README.md`, a file that was
already empty before the run, or a frontmatter-only leftover; it reports the leftover as a
violation instead.

## 5. Show the result

Show the user:

- the subagent's report (**Merged**, **Split**, **Removed**, **Still flagged**, the counts);
- the health level and reasons before (from step 1) and after (from step 4);
- every format violation still open after the run;
- the full change, new and deleted files included:

```bash
git -C "$ROOT" status --porcelain -- .agent-memory
git -C "$ROOT" diff -- .agent-memory
git -C "$ROOT" ls-files --others --exclude-standard -- .agent-memory |
  while IFS= read -r f; do git -C "$ROOT" diff --no-index -- /dev/null "$f"; done
```

`git diff` covers tracked files only; the loop prints the content of every new file (a split
creates them). `git diff --no-index` exits 1 when it finds a difference; that is normal here.

When the subagent failed, say so plainly, and show the same diff: whatever it changed before
it failed is still there, and git holds the originals.

## 6. Close

Say: the current session still holds the old rules — start a new session to use the new
ones.

Propose a commit of `.agent-memory/` with a message that names the defragment. When working
with a team, propose it on its own branch, merged fast, because a defragment touches many
files and conflicts with any parallel memory edit. Never commit unless the user asks; to undo
the whole run before a commit, `git checkout -- .agent-memory` plus removing new files is
enough.

## What you do not do

- Do not commit, push or open a pull request.
- Do not run the defragmenter as a plugin agent or a background agent; one general-purpose
  subagent in the foreground.
- Do not let the run touch `README.md`, files outside `.agent-memory/`, or the
  `.claude/rules/project-memory` view.
- Do not skip step 4 after a failure.
