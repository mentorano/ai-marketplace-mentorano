# clean-code

Rules and measurement for clean code in Python and TypeScript, packaged as
three Claude Code skills and two scripts: one for the shape of functions and
files, one for the import boundaries between modules.

Robert C. Martin's answer for agents is rules plus tool gates. The
constitution in `unclebob/swarm-forge` makes every pack install his CRAP,
DRY and mutation tools and forbids home-grown proxies, and the roles after
the coder run them as handoff gates: in the six-pack the `cleaner` runs
CRAP (10 or below) then DRY, and the `hardender` runs mutation, then CRAP
and DRY again. This plugin takes the measurement idea at a smaller scale
and inside one agent: it measures function length, cyclomatic complexity,
parameters, nesting depth and file size, and the imports that cross a
module boundary the wrong way, before it edits and after, and the
after-numbers may not be worse. That is the floor under the Boy Scout Rule,
which asks for cleaner, not merely no worse.

## Install

```bash
/plugin marketplace add mentorano/ai-marketplace-mentorano
/plugin install clean-code@ai-marketplace-mentorano
```

## Skills

| Skill | Loads when | Carries |
|---|---|---|
| `clean-code` | any source edit or review, and an architecture audit | the process, the audit mode, the language-agnostic rules, three review passes, `architecture.md`, `rationalizations.md`, `measure.py`, `boundaries.py` |
| `clean-code-python` | `.py` files, FastAPI, SQLAlchemy, Pydantic, pytest | Python shape of the rules, FastAPI layer defaults, per-layer smells |
| `clean-code-typescript` | `.ts` / `.tsx`, React, hooks, Vite, vitest | TypeScript shape of the rules, React layer defaults, per-layer smells |

The project's own `CLAUDE.md` outranks every rule in the skills. The
language skills carry only what a linter cannot check; a rule that ruff,
typescript-eslint or `tsc --strict` enforces names the tool and stops.

## The scripts

### `measure.py` — shape

```bash
# everything under the paths
python3 "${CLAUDE_PLUGIN_ROOT}/skills/clean-code/measure.py" backend/app frontend/src

# only files that differ from main, plus untracked
python3 "${CLAUDE_PLUGIN_ROOT}/skills/clean-code/measure.py" backend/app --changed --base main

# same data as JSON, thresholds included
python3 "${CLAUDE_PLUGIN_ROOT}/skills/clean-code/measure.py" backend/app --json

# every function, not only offenders
python3 "${CLAUDE_PLUGIN_ROOT}/skills/clean-code/measure.py" backend/app --all

# the changed files against the merge-base with main, one verdict per function and file
python3 "${CLAUDE_PLUGIN_ROOT}/skills/clean-code/measure.py" backend/app frontend/src --changed --base main --compare

# the same, from the committed files only (another session's uncommitted work stays out)
python3 "${CLAUDE_PLUGIN_ROOT}/skills/clean-code/measure.py" backend/app frontend/src --changed --base main --at HEAD --compare
```

From a checkout of this marketplace, the same script is at
`plugins/clean-code/skills/clean-code/measure.py`.

`--at <ref>` reads the files from a git ref instead of the working tree;
`--compare [<ref>]` reads them a second time at `<ref>`, the merge-base
with `--base` by default, and judges each row: `new-over`, `crossed`,
`grew`, `fixed`, `still-over`, `new` for functions, the same for the
500-line cap plus `suppressions-up` for files, and one `VERDICT` line with
the counts. The files are mirrored into a temporary directory with the
repository layout, and every path prints from the repository root, so the
two sides pair up wherever the command runs from. `revisions.py` does the
mirroring and `compare.py` the verdicts.

Python goes through the stdlib `ast`. TypeScript goes through the target
project's own `typescript` package, found in the nearest `node_modules`
above each file; if it is missing the script prints the `npm ci` command
and exits 2. TypeScript 7 is the native compiler and has no JavaScript API
to parse with, so a 7.x package is a broken run too, with a message that
names the version and asks for `typescript@5`. It never skips a language
silently.

| Measure | Default | Flag | Source |
|---|---|---|---|
| lines per function | 20 | `--max-lines` | Clean Code ch. 3, "Small!": functions "should hardly ever be 20 lines long"; the Sparkle functions he holds up were two to four |
| cyclomatic complexity | 10 | `--max-cc` | McCabe 1976 and NIST SP 500-235 §2.5; Clean Code sets no number. Also the floor under the CRAP ≤ 10 gate every `swarm-forge` pack runs |
| parameters | 3 | `--max-params` | Clean Code ch. 3, "Function Arguments": more than three "requires very special justification" |
| nesting depth | 2 | `--max-depth` | Clean Code ch. 3, "Blocks and Indenting": indent level "not greater than one or two" |
| lines per file | 500 | `--max-file-lines` | Clean Code ch. 5, "Vertical Formatting": files typically 200 lines, upper limit 500 |
| suppressions | counted | — | Clean Code ch. 17, G4 "Overridden Safeties"; the reason on the line is the ESLint and typescript-eslint convention |

Every default except complexity is a ceiling Clean Code states, mapped onto
the script's counting: a function's lines run from its `def` or signature
to its last line, blanks and docstrings included; depth starts at 0 in the
function body and adds one per nested block, so depth 2 is the book's "one
or two" indent levels; `self` and `cls` are not parameters. Complexity is
McCabe's number, not his; the book gives none. A project that wants slack
sets the flags in its `CLAUDE.md`.

Complexity is the same definition for both languages: one plus each `if` /
`elif` / `else if`, each loop (a Python comprehension counts), each
`except` / `catch`, each `and` / `or` / `&&` / `||` / `??`, each conditional
expression, each `case`. Exit code is 0 whenever the measurement ran; the
numbers are the verdict.

CRAP itself is Savoia and Evans (Agitar, 2007) with a standard threshold of
30; it equals cyclomatic complexity only at full coverage, which is why 10
is the floor under Uncle Bob's gate. McCabe exempted a large `case`
statement that answers one question, and the `swarm-forge` cleaner says the
same; the script counts every arm, so a flat eleven-arm `match` alone
crosses 10. That is a finding to explain in the report, not to split into
helpers that take booleans the caller already knew.

Suppressions counted: `# noqa` and `# type: ignore` in Python, in comments
only; `eslint-disable`, `@ts-ignore`, `@ts-expect-error` and `as any` in
TypeScript, by text match, so a string that mentions `eslint-disable`
counts. Three other definitions differ slightly between the languages: a
Python `case _` counts as a case while a TypeScript `default:` does not;
each `if` filter inside a Python comprehension adds one; `with` blocks add
nesting depth in Python and have no TypeScript counterpart.

### `boundaries.py` — boundaries

```bash
# the whole package; point it at the package root, a subtree has incomplete cycles
python3 "${CLAUDE_PLUGIN_ROOT}/skills/clean-code/boundaries.py" backend/app

# rows from the files that differ from main; cycles still over the whole package
python3 "${CLAUDE_PLUGIN_ROOT}/skills/clean-code/boundaries.py" backend/app --changed --base main

# every module, layer and module edge, then the rows
python3 "${CLAUDE_PLUGIN_ROOT}/skills/clean-code/boundaries.py" backend/app --all

# the project's own names for the layers, the framework modules and the pure modules
python3 "${CLAUDE_PLUGIN_ROOT}/skills/clean-code/boundaries.py" backend/app --layers api,services,models,schemas,domain,parsers --core core,shared --domain domain,shared,parsers
```

`--at` and `--compare` work as for `measure.py`. With `--compare` the
report is the after side, followed by a `BEFORE` line with the SUMMARY at
the before ref and `VERDICT up=none` or the rule counts that went up, such
as `VERDICT up=upward:0->1`.

`measure.py` sees a function; it never reads an `import`, so a handler of
109 lines that builds four queries is green for it, and so are two modules
that import each other. `boundaries.py` reads every import with the stdlib
`ast` and places every file at (module, layer) from its path:
`app/billing/api/users.py` is module `billing`, layer `api`;
`app/api/users.py` in a flat layout is module `app`, layer `api`; a
directory that is no layer name is layer `root`, reported, never dropped.
Every import is then an edge between two places, and the measures count the
edges that point the wrong way. One package per run, with an `__init__.py`
in the root and in every directory under it: without the top one the files
land under a lower root, no import names it, and the script says so on
stderr next to a SUMMARY of zeros. Python only in this version; a
TypeScript file is a broken run that names `dependency-cruiser`.

| Measure | Rule | Definition | Source |
|---|---|---|---|
| `upward` | 0 | an import from `services`, `models` or `domain` to `api` | Clean Architecture ch. 22, the Dependency Rule |
| `cycles` | 0 | pairs of modules that import each other; the rarer direction is printed as the closing edges, the fix list | Clean Architecture ch. 14, the Acyclic Dependencies Principle |
| `cyclic_modules` | 0 | modules inside any cycle, pairs or longer (the strongly connected components of the module graph); a cycle through three modules has no pair and shows only here | ch. 14 |
| `core_outward` | 0 | an import from a `--core` module (`core`, `shared`) to a feature module; `main.py` is the composition root and is exempt | ch. 22; `architect.prompt` Phase 2 |
| `framework_in_domain` | 0 | `fastapi`, `sqlalchemy` or `starlette` imported under a `--domain` module or layer (`domain`, `shared`, `parsers`; `parsers` is also a default layer so a feature's `parsers/` counts) | ch. 22; `architect.prompt` Phase 2 |
| `sql_in_api` | 0 | files under `api/` with a statement that contains `select(`, `.execute(`, `.where(` or `func.`; text match inside each statement, sites per file, so one query over three lines is one site and a `SELECT 1` health probe is not the same row as fourteen queries | `architect.prompt` Phase 1; `clean-code-python` layer table |
| `http_in_services` | 0 | `fastapi` or `starlette` in the `ast` imports of a file under `services/`; imports, not text, because a comment that mentions `HTTPException` is not a finding | ch. 22; `clean-code-python` layer table |
| `ports` | counted | `Protocol` or `ABC` classes under `services/` or `domain/`; informational, the pattern the other services should follow | ch. 11 (DIP) |

Core modules and the package root are outside the cycle graph, because
their outward edges are already `core_outward`. The names come from the
project: `--layers`, `--core`, `--domain`, with the defaults from
`clean-code-python`, and the project's `CLAUDE.md` carries the flags the
same way it carries the thresholds. The script measures and stops there:
enforcement is `import-linter` (Python) and `dependency-cruiser` or
`eslint-plugin-import` (TypeScript), turned on by the project, as Clean
Architecture ch. 34 has Simon Brown say — let the tool enforce what the
folders only suggest.

## Sources

The skills carry no citations, so the rules stay short. This table says
where each rule comes from.

| Rule | Source |
|---|---|
| Names say what, not how | Clean Code ch. 2 "Use Intention-Revealing Names"; ch. 17 G20 "Function Names Should Say What They Do" and N2 "Choose Names at the Appropriate Level of Abstraction" |
| One job per function; sections are functions | Clean Code ch. 3 "Do One Thing", "Sections within Functions", the Stepdown Rule; ch. 17 G30 |
| No flag arguments | Clean Code ch. 3 "Flag Arguments"; ch. 17 F3; Fowler, bliki "FlagArgument" |
| No hidden side effects | Clean Code ch. 3 "Have No Side Effects", "Command Query Separation" (Meyer) |
| No duplication, second copy; shared mechanism under both names | Clean Code ch. 3 DRY, ch. 12 "No Duplication", ch. 17 G5; blog "An Accidental Doppelganger in Ruby" (2009). The true-vs-accidental carve-out is Clean Architecture ch. 16 and belongs to boundaries, so it sits in `architecture.md` Phase 4 |
| Errors are types | Clean Code ch. 7 "Use Exceptions Rather Than Return Codes", "Don't Return Null" |
| Comments explain why; what only for code you cannot rename | Clean Code ch. 4 "Good Comments", "Bad Comments"; blog "Necessary Comments" (2017) |
| Dead code is deleted | Clean Code ch. 4 "Commented-Out Code"; ch. 17 C5, F4, G9 |
| Tests are code, one behaviour | Clean Code ch. 9 "Single Concept per Test"; sentence names: Dan North, "Introducing BDD"; no logic in tests: Meszaros, "Conditional Test Logic"; real dependencies: blog "When to Mock" (2014) |
| Reading the numbers | Clean Code ch. 3 "Argument Objects", "Switch Statements", "Blocks and Indenting"; ch. 17 G23; guard clauses: Fowler, "Replace Nested Conditional with Guard Clauses" |
| Architecture phases | `swarm-forge` `swarmforge/roles/architect.prompt` (six-pack, four-pack); Clean Architecture ch. 22, 23 |
| Vocabulary, dependency rule, boundaries | Clean Architecture ch. 17, 19, 22; DIP ch. 11 (stable concretions tolerated); ch. 20 for the framework-free request model; Clean Code ch. 8 for the map that may not cross |
| Automated checks | `architect.prompt`; Clean Architecture ch. 14 (no cycles), ch. 34 (Simon Brown: let the compiler enforce) |
| Boundary measures, audit mode | `architect.prompt` Phases 1 and 2; Clean Architecture ch. 14 (acyclic dependencies), ch. 22 (dependency rule), ch. 34 (let the tool enforce); the two greps of `clean-code-python` that became `sql_in_api` and `http_in_services` |
| Three review passes, revalidate before fix | this plugin. He prescribes no passes: for people his answer is pairing (The Clean Coder ch. 12), and his `swarm-forge` reviewer roles (`adversaries`, `squad`) run one review in the same concern order |
| Boy Scout floor | Clean Code ch. 1 "The Boy Scout Rule"; The Clean Coder ch. 1 |
| Python rules and layers | Google Python Style Guide; FastAPI docs; SQLAlchemy asyncio docs; ruff docs; `fastapi-best-practices` |
| TypeScript rules and layers | react.dev; TanStack Query docs and TkDodo; typescript-eslint docs; `labs42io/clean-code-typescript`; `bulletproof-react` |

## Sample output

On a codebase that grew without these rules, expect roughly half of the
functions over at least one threshold. That is the starting point, not a
failure: the plugin exists to stop the numbers getting worse and to bring
touched files under the line one task at a time.

The `branch-board` plugin in this marketplace was written before these
rules and shows the same picture at a smaller scale:

```text
$ python3 plugins/clean-code/skills/clean-code/measure.py plugins/branch-board/skills/branch-board
FUNCTIONS over threshold (lines>20 cc>10 params>3 depth>2): 10 of 21
  lines    cc  params  depth  where
    311    73       0      5  plugins/branch-board/skills/branch-board/collect.py:229 main   [lines cc depth]
     98    23       2      2  plugins/branch-board/skills/branch-board/collect.py:129 parse_plan   [lines cc]
     66    28       1      4  plugins/branch-board/skills/branch-board/render.py:55 parse   [lines cc depth]
     57    16       2      4  plugins/branch-board/skills/branch-board/render.py:310 build   [lines cc depth]
     49    13       0      2  plugins/branch-board/skills/branch-board/board.py:108 main   [lines cc]
     46    20       1      3  plugins/branch-board/skills/branch-board/board.py:60 render_branch   [lines cc depth]
     35    10       1      3  plugins/branch-board/skills/branch-board/collect.py:92 strip_fences   [lines depth]
     12     5       1      3  plugins/branch-board/skills/branch-board/collect.py:345 main.in_window   [depth]
     24     3       3      1  plugins/branch-board/skills/branch-board/collect.py:21 git   [lines]
     23    10       1      1  plugins/branch-board/skills/branch-board/render.py:131 render_record   [lines]
FILES over 500 lines or with suppressions: 1 of 3
  lines  suppr  file
    543      0  plugins/branch-board/skills/branch-board/collect.py
SUMMARY functions=21 over_lines=9 over_cc=6 over_params=0 over_depth=6 files=3 over_file_lines=1 suppressions=0
```

A TypeScript test file used to show one `anonymous` row per top-level
`describe(() => { ... })` block, measured as one long function that owned
every `it()` inside it. Since 0.4.0 a `describe` block is a container and
is not measured; each `it`, `test` and hook is measured on its own and
named after its call and title, such as `it("adds numbers")`.

## Tests

```bash
./run-tests.sh
```

`tests/test_measure.py` measures fixtures with known numbers on both
languages, exercises `--changed` against a scratch git repository, and
checks the failure message when the `typescript` package is missing.
`tests/test_boundaries.py` writes scratch packages that break one boundary
each — an upward import, a two-module cycle, a cycle through three modules,
`select(` in a handler, `fastapi` in a service, `sqlalchemy` under
`shared`, a port, and a clean tree — and asserts the SUMMARY counts and the
printed closing edges. The
TypeScript tests use the `typescript` package at `CLEAN_CODE_TS_PACKAGE`
when that variable is set, and otherwise `node_modules/typescript` in the
repository root (`npm install --no-save typescript@5` puts it there); they
print one line naming the variable and skip when neither is there.
`tests/test_revisions.py` builds scratch git repositories and checks
`--at` (uncommitted and untracked files stay out, `--changed` lists
committed changes only) and every `--compare` verdict, for both scripts.
`tests/test_skills.py` checks every `SKILL.md` frontmatter.

## Not in this version

Coverage-weighted CRAP, mutation testing, and cross-file duplicate
detection. Each needs a tool turned on in the target repo first. The
TypeScript import graph for `boundaries.py`: it needs the project's path
aliases and a layer vocabulary for a React app, and `dependency-cruiser`
already does the job there. Enforcement of the boundary counts: the script
measures, the project's `import-linter` or `dependency-cruiser` gates.
