---
name: branch-board
description: Use when asked what branches are in flight in a repository, who is working on what, how far each has got, or for a live status page of recent branch activity — including "what happened this week", "who is on what", or a shareable branch overview for a repo with no written status doc.
---

# Branch Board

## Overview

A repository already knows what everyone is working on. Nobody reads it, because
`git branch -a` is a list of names with no state attached. This skill turns the
last N days of branch activity into one page: what exists, who moved it, how far
it got, and what it touches.

**Core principle: every claim on the page comes from a command, and the page
says which one.** The page is a derivation, not a memory.

## When to Use

- "What branches do we have and where is each one?"
- "Who is working on what right now?"
- A repo with no `HANDOVER.md`, no board, no written status — the state has to be
  built from git itself.
- Before a standup, a handover, or picking up someone else's work.

**Not for:** a single branch you already know (just read its log), or a project
whose truth lives in an issue tracker rather than in branches.

## Workflow

The board is a three-stage pipeline, and **`BOARD.md` is the source of truth**.
Git is measured once, the markdown carries the result, and the page is rendered
from the markdown. Editing the HTML edits an output; edit the markdown instead.

```
git ──collect.py──▶ board.json ──board.py──▶ BOARD.md ──render.py──▶ board.html ──▶ Artifact
      measurement                 skeleton      ▲ you write the prose here
```

**1. Collect.** The script is the whole data layer:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/branch-board/collect.py" <repo> --days 7 > /tmp/board.json
```

`CLAUDE_PLUGIN_ROOT` is set by Claude Code to this plugin's directory. Use it —
a hard-coded `~/.claude/skills/...` path does not exist for a plugin install.

Flags: `--days N`, `--base origin/main`, `--no-fetch`. It fetches with
`--prune`, measures each branch from **its own merge-base**, and reads PR state
through `gh` when `gh` is installed.

It exits non-zero when the base does not resolve, rather than emitting an empty
page. Check `meta.warnings` before rendering. It is non-empty whenever the run
could not prune, whenever `gh` failed to read PR state, and whenever the open-PR
listing came back full at its `--limit` and may be truncated. Each of those means
some branch on the page is measured less well than it looks.

**2. Build the markdown skeleton**, then write the prose:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/branch-board/board.py" /tmp/board.json --out BOARD.md
```

Every measured value arrives filled in. What is left is one `TODO:` per branch
plus one for the summary — **the only places judgement is allowed**. Write one
honest line per branch: what it is and how far it got, read from the branch
name, the commit subjects and the touched directories. Mark inference as
inference. Do not delete a `TODO:` without replacing it; an unanswered one
renders in muted italics so the gap is visible rather than silent.

Commit `BOARD.md`. It is the artifact under version control, and its diff
between two runs is a readable record of what moved.

The skeleton and the page are written in Bulgarian: the field values, most
section headings, the fixed notes and the `TODO:` prompts. The field keys
(`author`, `state`, `position`, ...) stay in English, because `render.py`
reads them back. The
plan reader recognises goal, task and flag words in both Bulgarian and
English. Write the prose in whichever language the team reads.

**3. Render and publish:**

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/branch-board/render.py" BOARD.md --out board.html
```

Then publish `board.html` with the Artifact tool. Never hand-edit either file —
re-run stage 2 or edit `BOARD.md`, then re-render.

The published page is a real URL on claude.ai, private until the owner shares
it, so the board can go to the team without a local file or a static host.
Re-publishing the same file path replaces the page at the same URL: the link a
colleague bookmarked keeps working as the board is re-run. Say in the footer
when it was generated — a shared link outlives the numbers on it.

## Reading the branch's own plan

The collector reads every markdown file the branch touches under `plans/`,
`specs/` or `docs/` — from the branch itself, with `git show <branch>:<path>`,
because the plan of an unmerged branch is not on the base. Per document it
returns the title, the stated goal, the checkbox counts, the numbered tasks, and
up to six flagged paragraphs (🔴 ⚠️ ✅ parked, blocked, deferred, open question).

Three rules keep that section honest:

- **A plan or spec outranks any other doc the branch touched.** A branch that
  edits an unrelated doc in passing must not have that doc shown as its plan.
  Say plainly when a branch carries no plan of its own.
- **Checkboxes measure the document, not the code.** "0 of 22 ticked" is a fact
  about the plan file. A plan can tick a step that no commit implements.
- **Flags are read per paragraph, never per line.** Markdown wraps sentences,
  and a wrapped line can reverse its own meaning out of context.

## The six claims, and what each is allowed to say

| Claim | Measured from | Never say |
|---|---|---|
| on the page at all | tip inside the window, **or** an open PR updated inside it (`in_window_by`) | that a stale tip means nobody is on it |
| exists / is alive | `for-each-ref` after `fetch --prune` | that a stale remote-tracking ref is a live branch |
| how far | own commits, files, insertions from the merge-base | that this is work not yet on the base — a squash merge leaves it here |
| landed | `merge-base --is-ancestor` **or** a merged PR, combined into `landed_by` | "done" because the diff looks complete |
| in review | `gh pr list` state | that no PR means no work |
| its stated goal | the branch's own plan/spec docs via `git show` | that a ticked checkbox means the code exists |
| what it does | branch name + commit subjects + touched dirs | this as fact — it is a reading |

## Rules that keep the page honest

- **`--prune` is mandatory.** A branch deleted on the remote at merge time
  survives as a remote-tracking ref locally, and every sweep over
  `refs/remotes/origin` counts it as alive. A silent false positive that looks
  exactly like real work.
- **Measure from each branch's own merge-base.** Not because `base...branch` is
  wrong — for `git diff` the two are the same command, since `A...B` *is*
  `merge-base(A,B)..B`. The merge-base is spelled out because it is the thing
  being measured from, and the page names it (`merge_base` in the JSON) so a
  reader can re-run the range by hand. Nothing here defends against a squash
  merge; only `landed_by` does.
- **A commit date is not a person working.** It is the last time something was
  written. Say "last commit 3 days ago", never "stalled" or "active".
- **The window is about the branch, not about its last commit.** A branch under
  review for two weeks has a stale tip and a live discussion. The collector
  keeps it when its open PR was updated inside the window, and `in_window_by`
  says which of the two put it there (`commit` or `pr`).
- **A diff cannot say "finished".** Only a merge or a merged PR can. Everything
  else is "N files touched under these paths". An identical tree is not
  evidence either: a branch that changed nothing has one too.
- **A squash merge leaves the branch looking open.** `--is-ancestor` returns
  false because the commits were rewritten, so the branch still reports its own
  commits and its own diff. The merged PR is the only thing that catches it.
  Without `gh`, the page cannot tell a squashed branch from live work — say so
  rather than guess (`meta.gh` records which case you are in). `gh` installed
  but failing is the same blindness wearing a working face: the per-branch
  lookup marks itself `# FAILED` in `meta.commands` and raises a warning, so
  "no PR" is never printed as a measurement that was never taken.
- **Never run plain `git status` in a repo you do not own** — it takes
  `index.lock` and can break a running session's `git add`. Every git command
  the script runs goes through one wrapper that adds `--no-optional-locks`;
  there is no second path. `gh` is the one non-git subprocess: it runs with
  `cwd` set to the repo and reads only the remote configuration.
- **Local-only branches belong on the page**, marked as such. "Written and never
  pushed" is a real state and is invisible to anyone but its author. Merge a
  branch's local and remote copy *before* applying the day window, or a pushed
  branch whose remote tip is older than the window reads as never pushed.
- **There is no `remote_only`.** Whether you happen to have checked a branch out
  is a fact about your clone, not about the work. Emitting it would put a field
  on the page that looks measured and means nothing.

## Page shape

Header: repo name, base branch + short SHA, window in days, generation stamp.
Then one card per branch, newest first by the absolute instant of its tip — not
by the printed date, which is a local calendar day and reverses across
timezones. Each card carries: name, author, last commit date in UTC,
a state pill (landed / in review / open / local only), own commits and diff size,
the top touched directories, and the last few commit subjects. Footer: the exact
commands the numbers came from, so a reader can re-run any of them.

Colour encodes state, not decoration: landed, in review, open, local-only.
Order by last activity — recency is the one ranking that needs no judgement.

## Fields the page must not misread

- `merged` / `landed_by` — `landed_by` names the evidence: `ancestor`, `pr`, or
  `null`. Never render "landed" without one of the two.
- `role` — `work` or `pointer`. A pointer has no commits of its own.
- `in_window_by` — `commit` or `pr`. Say which, when it is `pr`.
- `kind` on each plan — `plan` or `incidental`. A branch whose only documents
  are `incidental` carries no plan of its own, and the page must say so.
- `meta.warnings` — non-empty means something could not be measured: no prune,
  `gh` could not read PR state, or the open-PR listing hit its `--limit`. Show
  every one of them.
- `top_dirs` — real directories. A file at the repo root is grouped under `.`,
  never under its own filename.

## Tests

`./run-tests.sh` in the marketplace root runs every suite; two of them cover
this skill. The collector suite builds real throwaway
repositories — squash merges, refs
deleted behind the clone's back, plans full of fenced blocks — and asserts on
the collector's JSON. `BB_COLLECT=<path> ./run-tests.sh` runs the same suite
against another copy of the collector; that is how the suite was shown to be red
before the fixes. A test that has never failed proves nothing.

The pipeline suite asserts the markdown really is the source: a value edited in
`BOARD.md` must reach the page, and the renderer must never reach back into the
JSON. It also checks what the Artifact viewer needs — balanced tags, no root
document tags, every colour token defined in the bare `:root` so the default
"system" theme resolves, and no external asset host but Google Fonts.

## Common Mistakes

- Publishing without saying when it was generated. The page then looks live
  forever and quietly becomes wrong.
- Writing a progress percentage. Nothing in git measures it; it reads as
  measurement and is a guess.
- Dropping branches with zero own commits. A branch pointing at the base is a
  finding — someone made it and never started. The collector marks these
  `role: "pointer"` instead of dropping them; a release pointer, a merged
  feature branch and an abandoned one all look identical to git, so group them
  rather than guess which is which.
- Rebuilding the page by editing the HTML instead of re-running the collector.
  Re-run, then re-render; the page is an output.
