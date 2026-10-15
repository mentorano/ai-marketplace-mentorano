# Board

A claude.ai Artifact page that renders from its own database. Status goes through data writes,
never by editing the page. Its rows are **reported, not verified**: a lane's "landed" is a claim
until git shows the merge; coord reconciles against git on resume and after each batch.

## Create (bootstrap)
1. [ ] Load `artifact-design` and `artifact-capabilities` skills; publish a thin page with the `db` capability that reads collections `tasks`, `lanes` and doc `meta/state` (schema: `templates/board-schema.json`). Group by lane; top totals exclude the `backlog` lane; a backlog filter shows it.
2. [ ] Seed with one `ArtifactData batch` (<= 50 writes per call): `lanes/<code>` for each lane + `lanes/backlog`; `tasks/<ID>` per slice; `meta/state`.
3. [ ] Put the URL in the project config.

## Update (on protocol events only)
| Event | Writes |
|---|---|
| START | task `status: wip`, `branch` |
| LANDED | task `status: ready`, `sha`, `tryIt` |
| BLOCKED | task `status: blocked`, `waiting` |
| merge batch pushed | each task `status: landed`, `mergedAs`; `meta/state.integrationSha`, `updatedAt` |
| deploy | task `status: deployed`; `meta/state.deployedSha` |
| deferred item | new `tasks/BL<n>` with `lane: backlog`, `status: todo` |

- Batch all writes of one event into ONE `ArtifactData` `batch`, each entry pinned with `if_version` from the last read. A refused pinned write means someone changed it: re-read that doc, redo.
- No timer updates. If a periodic tick exists: cheap shell precheck first, dispatch a `haiku` board agent only if something changed, at most every 2 hours.
- Delegate large board edits to a `haiku` agent with the exact writes; coord does small batches itself.

## Rules
- Status only. Decisions live in the amendments/plan docs; a board note may link them.
- A design/delta doc is not state either; check `git log` before assigning from it.
- Never hand-edit the HTML for status; republishing the page is for layout changes only.
