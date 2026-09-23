# ai-marketplace-mentorano

A Claude Code plugin marketplace for tools that read the state of a repository —
what work is in flight, who moved it, how far each piece got — and keep its
code clean.

## Install

```bash
/plugin marketplace add mentorano/ai-marketplace-mentorano
/plugin install branch-board@ai-marketplace-mentorano
/plugin install clean-code@ai-marketplace-mentorano
```

To work on the marketplace itself, point Claude Code at a local clone instead:

```bash
/plugin marketplace add <path-to-your-clone>
```

## Plugins

### branch-board

Builds a live status page for a repository's recent branches: what exists, who
moved it, how far it got, what it touches, and what its own plan documents say
the goal is.

It exists because `git branch -a` is a list of names with no state attached, so
nobody reads it. The skill turns the last N days of branch activity into one
page, and every number on that page comes from a command the page names.

The board is a three-stage pipeline, and **`BOARD.md` is the source of truth**.
Git is measured once, the markdown carries the result, and the page is rendered
from the markdown:

```
git ──collect.py──▶ board.json ──board.py──▶ BOARD.md ──render.py──▶ board.html ──▶ Artifact
      measurement                 skeleton      ▲ you write the prose here
```

```bash
S=plugins/branch-board/skills/branch-board
python3 $S/collect.py <repo> --days 7 > board.json   # git and gh -> measurements
python3 $S/board.py board.json --out BOARD.md        # measurements -> markdown
#   fill in one TODO per branch — the only place judgement is allowed
python3 $S/render.py BOARD.md --out board.html       # markdown -> page
```

Then publish `board.html` with the Artifact tool. Re-publishing the same file
path replaces the page at the same URL, so a link a colleague bookmarked keeps
working as the board is re-run. Commit `BOARD.md`: its diff between two runs is
a readable record of what moved.

The page and the `BOARD.md` skeleton are in Bulgarian. The plan reader
understands goal and task headings in Bulgarian and English.

What the collector guarantees, in one line each:

- It fetches with `--prune`, and says in `meta.pruned` when it could not —
  a branch deleted on the remote otherwise survives as a live-looking ref.
- "Landed" comes from `merge-base --is-ancestor` **or** a merged PR, never from
  how complete the diff looks. `landed_by` names which one.
- A squash merge rewrites the commits, so `--is-ancestor` alone reports landed
  work as open. Only the merged PR catches it, and without `gh` the page must
  say it cannot tell.
- The window keeps a branch whose open PR moved inside it, even when its tip
  did not. `in_window_by` says which put it there.
- Plan documents are read from the branch itself with `git show`, and each is
  marked `plan` or `incidental` so the page can say when a branch carries no
  plan of its own.
- The plan's title, goal, checkboxes, numbered tasks and flags measure the
  document, not the code, and every one of them ignores whatever is inside a
  fenced code block — including a block closed by a longer fence than it opened.
- `gh` that fails is declared, not silently read as "no PR", and a full open-PR
  listing says it may be truncated. Numbers are never guessed into place.
- An unresolvable base is fatal. An empty page is a bug, not a finding.

Full contract, and the rules that keep the output honest, in
[`plugins/branch-board/skills/branch-board/SKILL.md`](plugins/branch-board/skills/branch-board/SKILL.md).

### clean-code

Three skills and two scripts. The skills carry Clean Code and Clean
Architecture rules shaped for Python / FastAPI and TypeScript / React;
`measure.py` measures function length, complexity, parameters, nesting and
file size, `boundaries.py` measures the import graph — dependency direction,
cycles between modules, framework types in the domain, SQL in handlers — and
the agent runs them before and after every change so the verdict comes from
a command. With `--compare` both scripts measure the same files a second
time at the merge-base and give a verdict per function, file and boundary
rule, so a trade that the totals hide still shows. An audit mode runs both
over a whole tree and keeps shape and boundaries as two lists. See
`plugins/clean-code/README.md` for the thresholds, the rules and a
sample run.

## Tests

```bash
./run-tests.sh
```

Six suites. The collector suite builds real throwaway repositories — squash
merges, refs deleted behind the clone's back, plans full of fenced blocks — and
asserts on the JSON. The pipeline suite asserts that the markdown really is the
source: a value edited in `BOARD.md` reaches the page, and the renderer never
reaches back into the JSON. The measure and boundaries suites measure fixtures
with known numbers and scratch packages that each break one boundary. The
revisions suite builds scratch repositories and checks `--at` and every
`--compare` verdict of both scripts. The skills suite checks every `SKILL.md`
frontmatter and the two manifests.

The TypeScript tests need `node` and the `typescript` package. They look for
it at `CLEAN_CODE_TS_PACKAGE`, then at `node_modules/typescript` in the repo
root (`npm install --no-save typescript@5`), and skip with one line when neither
is there. TypeScript 7 ships without the JavaScript compiler API that
`measure-ts.mjs` loads, so the tests pin 5.x.

```bash
BB_COLLECT=<path-to-another-collect.py> ./run-tests.sh
```

runs the same suite against another copy of the collector. That is how the suite
was shown to be red before the fixes it pins down. A test that has never failed
proves nothing.

## Layout

```
.claude-plugin/marketplace.json    the marketplace manifest
plugins/<name>/
  .claude-plugin/plugin.json       the plugin manifest
  skills/<name>/SKILL.md           the skill itself
  skills/<name>/*.py               scripts the skill runs
run-tests.sh                       runs every suite in tests/
tests/                             fixtures build real git repos; stubs fake `gh`
```

## License

MIT, copyright Mentorano Ltd. See [`LICENSE`](LICENSE).
