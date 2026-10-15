# <Project> - coord project config

Lives at `<repo>/.coord/project.md` (excluded via `.git/info/exclude` unless the owner wants it tracked).
Holds project FACTS and decisions about the process, never status. Keep it current when lanes or commands change.

## Machine-read keys (read by `scripts/derive-state.sh`; one `key: value` per line, no quotes)

```
repo: ~/Projects/<project>
remote: origin
automation: manual   # manual | cmux (coord opens/restarts lane tabs; owner-approved, see procedures/cmux-automation.md)
integration_branch: <e.g. main or develop>
worktree_root: ~/Projects/<project>-wt
lane_prefixes: <space-separated branch prefixes, e.g. api web>
session_prefix: <e.g. proj>
migration_heads_cmd: <command printing migration heads, run from repo root; empty if none>
migration_current_cmd: <command printing the DB's current revision; empty if none>
docker_filter: <substring of compose project names, e.g. proj->
ci_workflow: <e.g. ci.yml>
context_threshold: 250000
```

## Sessions and lanes

| Session name | Role | Code | Worktree | Branch prefix | Test DB port | e2e ports (API/web) |
|---|---|---|---|---|---|---|
| `<prefix>-coord` | coordinator, no product code | - | `<repo>` on `<integration>` | - | <port> | - |
| `<prefix>-<lane>` | lane | `XX` | `<root>/<lane>` | `<lane>/` | <port> | <api>/<web> |
| `<prefix>-design` | design/prototype (optional) | - | `<path>` | - | - | - |

## Ownership

| Lane | Owned files/modules | Owned data (tables/entities) | Migration numbering (range, or "next in chain") |
|---|---|---|---|
| XX | `src/<module>/**`, `web/src/features/<x>/**` | `<table>`, ... | `0100-0199` |

Others read owned data through the owner's service functions/API only.

## Hotspots (append-only; name in СТАРТ)
- e.g. router list, model registry, job handler registry, route/nav array, dependency manifests.
- e.g. a shared stylesheet: append-only for all; or give it one owner and list it under that lane's owned files instead of here.
- Frozen files (extend via new per-feature files): ...

## Commands (exact; run from the directory given)

| Purpose | Directory | Command |
|---|---|---|
| Test DB up/migrate/roles (idempotent) | repo root | `scripts/<db-script> <lane> <port>` |
| Test DB rebuild | repo root | `docker compose -p <project> -f <compose file> down -v && scripts/<db-script> <lane> <port>` |
| Backend full suite (flags!) | repo root | `<FLAG=1> <cmd>` - baseline: N passed, accepted skips: ... |
| Frontend unit | `<frontend dir>` | ... |
| Frontend typecheck / build | `<frontend dir>` | ... |
| e2e suite `<domain>` | `<frontend dir>` | `<ENV=...> npx playwright test -c <config>` (ports ...) |
| Migration round-trip | repo root | ... |

The test commands above are the FULL suites (end of scope, high-risk batches).

smoke_commands: <3-5 critical e2e paths + build, ~3 min; e.g. `npx playwright test -c <config> --grep @smoke`>
high_risk_paths: <globs; e.g. `**/migrations/**`, `app/auth/**`, `**/roles/**`, `app/personal_data/**`>

Env notes: which vars must be set/unset (e.g. unset paid API keys), export each DB URL on its own line.

## CI
- Workflow: `<path>`; triggers: push to `<integration>` only, docs ignored; `workflow_dispatch`.
- Budget: <minutes or $ per month>; not-yet-in-CI suites and their owners: ...

## Documents
- Owner decisions (amendments): `<path>`
- Plan (coord rulings, "for ratification"): `<path>`
- Coord handoffs: `<dir>`; lane handoffs: `<dir or per-worktree path>`
- Kickoffs: `~/.claude/kickoffs/<session name>.md`
- Board: `<claude.ai artifact URL>` (schema: `templates/board-schema.json`)

## Design sources (only if a design session exists)
| Question | Source |
|---|---|
| Structure/components/class names | ... |
| Copy | ... |
| Flow/rules | ... |
| Demoted (last resort) | ... |
- Draft marker: `<e.g. DRAFT-COPY>`; return-to-design marker: `<text>`

## Protected actions (owner's explicit yes each time)
Deploy (`<how>`), force-push / reset of pushed history, deleting branches/worktrees/volumes with non-synthetic data, paid API batches, CI budget changes, editing shared machine config, publishing outside.

## Data policy
- Personal/sample data location and exclusion: ...
- Vendor data decisions (with decision ids): ...
- Secrets in the shell that tests must not see: ...
