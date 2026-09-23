---
name: clean-code-typescript
description: Use when editing .ts or .tsx files or when TypeScript, React, hooks, components, Vite, or vitest are part of the task. The TypeScript and React shape of the clean-code rules, with the layer defaults for a React app and the per-layer smells that no linter catches.
---

# Clean Code — TypeScript and React

Companion to the `clean-code` skill. That skill owns the process (measure
before, write, measure after, verify, three review passes, report) and
`architecture.md` with the four architecture phases. This one says what the
rules look like in TypeScript and React and which smell lives in which
layer of a React app. Rules that `tsc --strict`, typescript-eslint
`recommended`, or `eslint-plugin-react-hooks` enforce are not repeated
here; where one borders a rule, the rule names the tool and moves on.

The project's `CLAUDE.md` (root, `frontend/CLAUDE.md`) outranks every
default here.

## Rules, TypeScript shape

- **`strict` on in `tsconfig.json`.** A project setting no lint rule reads,
  so check the file. Once it is on, `tsc` catches the implied `any` and
  `no-explicit-any` the written one, so this skill does not list `any`. A
  value whose shape is not known at the boundary is `unknown` plus a
  narrowing guard, not an `as` cast. An `as` cast carries a comment that
  says why the compiler is wrong.
- **Discriminated unions, not flags.** Two optional fields that travel
  together, or a boolean prop that switches the render, are one union with
  a `kind`.
- **A named `Props` type per component.** `type` or `interface`, not
  inline past a field or two, and never the type that is also the API
  response: the component owns its contract, the wire shape stays in the
  hook that fetched it.
- **Data comes through a hook.** `useQuery` / `useMutation` in `hooks/`;
  no `axios`, no `fetch`, no `useEffect` + request in a component or page.
  Unless the framework owns fetching (a route loader, a server component),
  which is then that layer's job.
- **Query keys are constants or a key factory in the hook file.** An
  inline key array in a component is a cache bug waiting for a rename.
- **Every dependency array entry traces to a stable source.**
  `exhaustive-deps` flags a literal object, array, function, or `x ?? []`
  declared in the component body; it cannot see a value that comes back
  from a call (`.filter()`, `.map()`, a `useMutation()` result) or through
  props. Those change identity every render: the memo misses, dependent
  effects re-run, `memo()` children re-render. Nothing remounts unless the
  value is a `key`. Prefer a primitive (`items.length`, the stable
  `mutate`) or derive inside the hook; `useMemo` last.
- **A component is one job.** It is a function, so the script's `lines`
  threshold applies to it; JSX and inline callbacks count. A file over 500
  lines is several modules. Extract the piece that owns its own state
  first: it leaves with its handlers.
- **Loading, error, and empty are explicit branches.** `data?.map(...)`,
  `?? []` and `data!` all satisfy `tsc --strict`: the first two render the
  same blank list for a pending query, a failed one, and zero rows, and
  `data!` crashes instead. Only `no-non-null-assertion`, in typescript-eslint
  `strict` and not `recommended`, catches the `!`. Each state gets its own
  JSX.
- **`eslint-disable` carries a reason after ` -- `.** ESLint accepts the
  syntax but no recommended set demands it; enable
  `@eslint-community/eslint-comments/require-description`. The reason says
  why the rule is wrong here, not what the rule says. `@ts-ignore` and a
  bare `@ts-expect-error` are already errors under `ban-ts-comment`.
- **Early return.** Guards first; the JSX at the bottom is the happy path.
- **Tests: one behaviour, a sentence for a name, render the real component.**
  `renders empty state when there are no rows`, not `test 3`.

## Layer defaults for a React app

The project's `CLAUDE.md` overrides these names and may group by feature
(`features/<resource>/{api,hooks,components,types}`) instead of by layer;
the arrows hold either way.

```
pages/        route components: call hooks, compose components, no rules
hooks/        one hook file per resource; query keys as constants in that file; invalidation on mutation; `select` turns the wire shape into the app's type
api/          one HTTP client with interceptors, and the wire types beside it (generated or mirrored from the backend contract)
components/   presentational and project components; no data fetching; consume the app's types, never the wire shape
types/        the app's own domain and view types: what hooks hand to components
utils/        pure functions that a second caller needs, one job per file named for it (`formatMoney.ts`, `isApiError.ts`); with one caller the function stays in that caller's file
```

Dependency direction: `pages` import `hooks` and `components`; `hooks`
import `api` and `types`; `components` import `types` and `utils`; `api`
imports nothing above it; nothing imports `pages`. A component that imports
the HTTP client is an adapter in the wrong folder. A component that reads a
backend field name is Phase 3 in `architecture.md`: the translation belongs
in the hook. When the project groups by feature, the same arrows hold inside
each feature; across features the direction is shared → features → pages,
and features do not import each other. When the project has
`import/no-restricted-paths` zones or another dependency checker, run it
(`architecture.md`, Automated checks).

| Layer | Smell | How it shows up |
|---|---|---|
| `pages/` | business rule in the page (`if (row.status === ...)` deciding permissions) | Phase 1 in `architecture.md`: the page is the humble object; the rule belongs in a hook or a domain helper |
| `pages/` | 500+ lines | several pages, or a page carrying a component |
| `components/` | `axios` / `fetch` / `useEffect` request | Phase 1 in `architecture.md`: the component can no longer be tested without IO |
| `components/` | inline props type, or a `Props` that is the API response type | representation leaks across the boundary; name the `Props` |
| `components/` | reads a backend field name (`row.created_at` straight from the DTO) | Phase 3 in `architecture.md`: translate in the hook's `select` |
| `hooks/` | query key typed inline (`['users']`) instead of the hook's key constant | a rename or typo in one copy and `invalidateQueries` no longer matches |
| `hooks/` | mutation that neither invalidates nor updates the cache (no `invalidateQueries` in `onSuccess` / `onSettled`, no `setQueryData`) | mounted lists keep the old rows until a refocus, reconnect, or remount refetch |
| anywhere | memo or effect dep held in a variable that is fresh each render (`const rows = data ?? []`, `.filter()`, an inline object) | the memo misses every render and every dependent effect or child re-runs; `exhaustive-deps` only catches the expression written inline in the array |

`console.log`, `as any` and `@ts-ignore` are not listed: `as any` and
`@ts-ignore` are errors under typescript-eslint `recommended`
(`no-explicit-any`, `ban-ts-comment`); core `no-console` covers the log but
is not in `eslint:recommended`, so turn it on.

## Measuring

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/clean-code/measure.py" frontend/src --changed
```

TypeScript is parsed with the project's own `typescript` package, found in
the nearest `node_modules` above each file, so the parser matches what the
project compiles. If it is missing the script prints the `npm ci` command
and stops; it never skips the language. TypeScript 7 has no JavaScript
compiler API, so on a 7.x project the script stops and asks for a 5.x
package (`npm install --no-save typescript@5`).

What counts as a function: declarations, methods, constructors, accessors,
and an arrow or function expression that is the initializer of a `const`,
a property, or `export default`. A callback passed to `.map`, `useMemo`,
or `useEffect` belongs to the enclosing function; its branches count
toward that function's complexity. A component with a large inline
callback is therefore measured as one large function, which is the honest
reading.

In a test file, `describe` (and `suite`, `context`) is a container like
the file itself: its callback is not measured and owns nothing, so every
`it`, `test` and hook is measured on its own. A callback that nothing
names takes the name of its call and the title, cut at 60 characters:
`it("adds numbers")`, `it.each("row %s is positive")`,
`vi.mock("./api")`, `beforeEach()`. A test over 20 lines is a finding
like any function; a long `describe` is not.

Two cheap greps that complement the script, from the frontend directory:

```bash
command grep -rln "axios\.\|fetch(" src/components src/pages           # fetching outside hooks
command grep -rn "queryKey: \[['\"]" src/components src/pages          # inline query keys outside hooks
```

Run them over the files the task touches. A hit in a touched file is a
boundary finding: `architecture.md` Phase 1 for a component that fetches,
Phase 3 for a wire shape read in the UI. A hit in a file the task did not
touch is context for the report, not a finding — the whole repository does
not have to be clean for the task to be done.

## What not to do

- Do not write a `helpers.ts` or `utils.ts`. `utils/` is a layer, not a
  name; each file in it is named for its job.
- Do not duplicate URL state into React state; one owner.
- Do not put the fetch in `useEffect` because the hook file "is not there
  yet"; create the hook.
- Do not fix an unstable dependency by removing it from the array; the
  linter flags it, and the array describes the code. Fix the source: hoist
  a constant out of the component, build the object inside the effect, read
  the primitive out of the object, and only then `useMemo` / `useCallback`.
- Do not silence `react-hooks/exhaustive-deps`; the warning is a bug
  report.
