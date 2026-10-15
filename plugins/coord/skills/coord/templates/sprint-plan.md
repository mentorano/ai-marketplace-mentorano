# <Project> - parallel sprint plan

Dates: code <from>–<to>; first real users <date>; dress rehearsal <date>.
Integration branch: `<branch>`. Owner decisions: `<amendments path>`. Coord decisions ("for ratification") are recorded in THIS file, in §7.

## 1. Goal and "done"
- What real users must be able to do at the milestone, as user-visible steps.
- "Done" = usable in the UI (backend + frontend), not backend-only.

## 2. Lanes
| Code | Session name | Mission | Owned files/modules | Owned data (tables/entities) | Migration numbering (range or "next in chain") | Worktree |
|---|---|---|---|---|---|---|
| e.g. WB | <prefix>-web | shell, auth, shared UI | `app/shell/**`, `web/src/shell/**` | users, orgs | 01xx | `<wt root>/web` |

## 3. Hotspots (shared files)
| File | Rule | Owner of structural changes |
|---|---|---|
| e.g. `main.py` router list | append-only, one line per lane, СТАРТ names it | coord |

## 4. Contracts between lanes
| Producer → Consumer | Contract (types/functions/endpoints/statuses) | Where it is defined | Types-only commit first? |
|---|---|---|---|
Rule: a consumer never keeps its own copy of a producer's enum/status; a widened enum triggers a grep of all consumers.

## 5. Slices, in order
Per lane: numbered slices, each with its user-visible outcome, dependencies (lane + slice), and a risk flag (high-risk = auth, payments, migrations, concurrency, personal data). Mark the critical path.
Pairing rules: slices that must merge together or in a fixed order (A makes a state reachable that only B resolves).

## 6. Data, migrations, environments
- Migration tool, single-head rule, numbering ranges per lane, who may re-point (a lane whose migration copies a shared SQL body refreshes and re-points itself).
- Per-lane test DB (compose project, port), e2e ports per suite.
- Full verification command set (with every required flag/env) - copied into the project config.
- Secrets and paid APIs: how tests are kept off real keys; real personal data rules.

## 7. Decisions log
- Coord decisions, each "for ratification" until the owner ratifies (then moved to/confirmed in the amendments).

## 8. Open questions for the owner
- Each with options and a recommendation.

## 9. Backlog (after the milestone)
- Lives on the board's `backlog` lane; this section only points there.
