---
name: clean-code-python
description: Use when editing .py files or when Python, FastAPI, SQLAlchemy, Pydantic, or pytest are part of the task. The Python shape of the clean-code rules, with the layer defaults for a FastAPI service and the per-layer smells that no linter catches.
---

# Clean Code — Python

Companion to the `clean-code` skill. That skill owns the process (measure
before, write, measure after, verify, three review passes, report) and
`architecture.md` with the four architecture phases. This one says what the
rules look like in Python and which smell lives in which layer of a FastAPI
service. Rules that ruff or mypy enforce are not repeated here; a rule that
borders one names the tool and stops.

The project's `CLAUDE.md` (root, `backend/CLAUDE.md`) outranks every default
here.

## Rules, Python shape

- **Data crosses a layer boundary as a simple typed structure.** A
  `dataclass`, a `NamedTuple`, or a Pydantic model, in the shape the inner
  layer wants. An ORM row or a request schema does not cross inward into
  the domain, and neither does a `dict`: Clean Code ch. 8 says keep a map
  inside the class that uses it. A `TypedDict` is tolerated inside a
  module, not at a boundary. `Any` or `dict[str, Any]` at a boundary is a
  missing type; inside a function `Any` carries a comment that says why the
  checker cannot know. The hints themselves are the tools' job: ruff `ANN`,
  or mypy `--strict`.
- **Domain errors are exception classes in the domain module.** Not
  strings, not `None` plus a comment, not `(ok, value)` tuples. Framework
  errors (`HTTPException`) exist only in the adapter that speaks HTTP.
- **`async def` never touches a sync database driver.** Ruff catches
  `time.sleep` and `requests` inside `async def` (`ASYNC251`, `ASYNC210`);
  nothing catches `psycopg2`, `sqlite3`, or a sync `Session` there. Use
  `AsyncSession`, or a plain `def` handler so FastAPI runs it in the
  threadpool.
- **Module level is definitions only.** No work at import time: no
  connections, no reads, no environment lookups outside a settings object.
- **One job per module, not one public name.** Related classes and
  functions live together; a module with two reasons to change is split by
  job, not by "helpers". Over 500 lines is the signal to look, not the
  verdict.
- **`# noqa: F401` and `# type: ignore[code]` say why on the same line**
  (`import x  # noqa: F401  # re-exported`). Where line length forces it,
  the reason sits on the line above. No tool checks the reason; a
  suppression whose code does not already explain itself is a finding. The
  missing code is ruff's job: select `PGH003` and `PGH004`.
- **Comprehensions are for building a value.** A comprehension whose body
  has a side effect is a `for`, even when its result is assigned. So is one
  with more than two control subexpressions: a second `for` plus an `if`,
  or two `if`s plus a `for`. Google's style guide is stricter, allowing no
  second `for` and no second filter at all.
- **Early return.** Guard clauses first, the happy path unindented. A depth
  finding is an inverted condition or a block that should be a one-line
  call. Ruff's `SIM102` flattens `if a: if b:`; select `RET505`-`RET508` to
  drop the `else` after a return.
- **Tests: one behaviour, a sentence for a name, real dependencies where
  the project has them.** `test_search_ignores_punctuation_only_query`, not
  `test_search_2`.

## Layer defaults for a FastAPI service

The project's `CLAUDE.md` overrides these names and may group by domain
package (`posts/router.py`, `posts/service.py`) instead of by type; the
arrows hold either way.

```
api/<resource>.py        thin handler: validation, auth, DI, translate domain errors to HTTP
services/<resource>.py   application logic per use case; takes the AsyncSession (or a repository Protocol it defines); no HTTP knowledge
models/<resource>.py     SQLAlchemy ORM classes and queries
schemas/<resource>.py    Pydantic request/response models, mirror of the API contract
domain/<resource>.py     rules that need no IO: plain functions and dataclasses; imports neither sqlalchemy nor fastapi; add it when the first such rule appears
```

Dependency direction: `api` imports `services` and `schemas`; `services`
imports `models` and `domain`; `domain` imports nothing from the app;
nothing imports `api`.

The layout is the FastAPI community's (the SQL tutorial's `crud.py`,
`full-stack-fastapi-template`, `fastapi-best-practices`), not Clean
Architecture ch. 22: a `services/` function that takes `AsyncSession` is
an adapter under `architecture.md` Phase 2, so the "domain module importing
the ORM" smell applies to `domain/`, not to `services/`. A `services/` file
that imports `fastapi` is an adapter in the wrong folder. A rule with no IO
written inside a session-taking function is the Phase 1 smell: lift it into
`domain/`. With import-linter, declare the direction as a `layers` contract
and forbid `fastapi` outside `api/`.

A service that has grown past one resource usually has the second layout:
feature packages, each with the same four layers inside, plus one package
for the framework glue and one for code with no IO.

```
app/core/                   config, database, logging, main.py (the composition root), middleware
app/shared/                 pure code every feature may import: parsers, value types; imports neither sqlalchemy nor fastapi
app/<feature>/api/          one router per resource of the feature
app/<feature>/services/
app/<feature>/models/
app/<feature>/schemas/
```

The arrows inside a feature are the ones above. The layout adds two rules
between packages: **feature packages do not cycle** (`orders` may import
`billing` or the other way round, never both), and **`core` does not import
a feature** except from `main.py`, which wires the app together. Import
direction between features is the project's decision; `boundaries.py`
reports which direction is the rarer one, and that is the one to cut. With
import-linter the two rules are a second `layers` contract over the
features, top to bottom, and a `forbidden` contract for `core` and
`shared`.

| Layer | Smell | How it shows up |
|---|---|---|
| `api/` | SQL in the handler (`select(`, `db.execute`) | the handler imports the ORM and knows table names; SQL stays in `models/` |
| `api/` | business rule in the handler | an `if` on domain state that no service function owns |
| `services/` | `raise HTTPException` | the service knows a status code |
| `services/` | a function that takes `Request` or `Response` | framework type across the boundary |
| `services/` | one function over 20 lines with commented sections | several jobs; each section is a function |
| `services/` | ORM object returned from a service | representation crosses the boundary; return the schema |
| `schemas/` | `dict[str, Any]` field that carries structure | a missing nested model |
| anywhere | `os.environ` or `os.getenv` outside settings | configuration read in two places |

`print(` is not listed: ruff `T201` catches it (select `T20`). The rows
above are what no linter checks: import direction and what crosses a
boundary.

## Measuring

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/clean-code/measure.py" backend/app --changed
```

Python functions are measured with the stdlib `ast`; nothing to install.
`self` and `cls` do not count as parameters. Nested functions are measured
on their own and excluded from the parent's complexity.

The second script reads the import graph of the package and counts the
edges that cross a boundary the wrong way. Run it on the package root
whenever the task touches more than one file or adds an import, and always
in audit mode:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/clean-code/boundaries.py" app
python3 "${CLAUDE_PLUGIN_ROOT}/skills/clean-code/boundaries.py" app --changed --base main
```

Two of its rows are the old greps, made into numbers: `sql_in_api` is a
file under `api/` with a statement that contains `select(`, `.execute(`,
`.where(` or `func.` (text match inside each statement, so one query that
spans three lines is one site; sites per file, so a `SELECT 1` health probe
is not the same row as a dozen queries), and `http_in_services` is a file
under `services/` whose `ast` imports include `fastapi` or `starlette`. The
second one reads imports, not text, because a comment that says a service
never raises `HTTPException` is not a finding. Both work for `app/services/`
and `app/<feature>/services/` alike. The other rows are `upward`, `cycles`,
`core_outward` and `framework_in_domain`; the `clean-code` skill's "Reading
the numbers" says what each one means.

A hit in a file the task touched is a boundary finding: `architecture.md`
Phase 2 for a framework type inside a service, Phase 1 for a handler that
redoes the data-access job. A hit in a file the task did not touch is
context for the report, not a finding — the whole repository does not have
to be clean for the task to be done. In audit mode the same hit **is** a
row: the audit has no touched files, so every row goes into the boundaries
list of the backlog.

## What not to do

- Do not write a `utils.py`. Name the job.
- Do not return `None` to mean "not found" from a service when the API
  needs to distinguish "not found" from "forbidden"; raise a domain error.
- Do not put the validator in the Pydantic model when it needs the
  database; that is a service rule.
- Do not mock the database when the project runs tests against a real one.
- Do not add a parameter to pass a flag through three layers; the flag is
  a missing type or a missing second function.
