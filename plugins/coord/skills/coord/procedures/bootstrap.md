# Bootstrap a new sprint (no config yet)

Goal: from a repo + spec/plan to N running lane sessions the owner has opened by name.
Nothing is created before the owner approves the lane proposal.
Precondition: `phase-0.md` §5 readiness gate passed. The lane proposal below is `templates/sprint-plan.md` §2–§6 filled from the plan; where the plan already has them, propose them as written.

## 1. Recon (delegate; keep coord thin)
- [ ] Dispatch 1-3 recon agents (`model: sonnet`), each returning <= 60 lines with `file:line`:
  - spec/plan: milestones, slices, dependencies, what real users touch and when;
  - code: modules/packages, data model (tables/entities and who writes them), registries/route lists/shared CSS/dependency manifests (hotspot candidates), migration tool and head(s);
  - tooling: test commands and required flags/env, test roots, e2e configs and ports, DB bootstrap scripts, CI workflows and triggers, secrets read from env.
- [ ] Read the house rules (`~/.claude/CLAUDE.md`, repo `CLAUDE.md`) yourself.

## 2. Propose lanes (to the owner, one message, `templates/owner-batch.md` shape)
For each lane: short code (e.g. `PL`), session name (`<prefix>-<lane>`), mission, owned files/modules, owned data (tables/entities), migration number range, slices in order with the critical path marked, dependencies on other lanes (contracts it consumes/produces; ask producers for a types-only commit first).
Also propose:
- [ ] Hotspot list (append-only files), and one owner for any shared stylesheet/theme.
- [ ] Merge order constraints: pairing rules (A makes a state reachable that only B resolves - merge as a pair, nothing between), migration-bearing slices one at a time.
- [ ] Whether a design/prototype session is needed (`design-interplay.md`).
- [ ] Owner questions that block lanes, each with a recommendation.
- [ ] Budget estimate: sessions x expected agents/week; CI changes needed (`ci-budget.md`).
Wait for approval. Apply corrections; do not re-ask what was answered.

## 3. Create (after approval)
- [ ] Config: copy `templates/project-config.md` to `<repo>/.coord/project.md`, fill every field; add `.coord/` to `.git/info/exclude` unless the owner wants it tracked.
- [ ] Worktrees, per-lane test DBs and ports: `worktrees-and-dbs.md` steps 1-4. Verify each DB with the config's migration-heads command.
- [ ] CI: restrict triggers per `ci-budget.md` (one commit, owner-approved if it changes CI files).
- [ ] Decision documents: create the amendments file (owner decisions) and the plan file (coord decisions, "for ratification") if missing.
- [ ] Board: `board.md` §Create. Put its URL in the config.
- [ ] Hooks: check `~/.claude/settings.json` for `kickoff-on-clear.py` and `handoff-at-boundary.py`; if missing, ask the owner to run `scripts/install-hooks.sh`.
- [ ] Kickoffs: for each lane write `~/.claude/kickoffs/<session name>.md` from `templates/lane-kickoff.md`.

## 4. Hand the sessions to the owner
With `automation: cmux` in the config, coord opens each lane tab itself (`cmux-automation.md` §Open) and reports the names. Otherwise coord cannot open sessions; send the owner, per lane, exactly:
```
cd <worktree> && claude          # then: /rename <session name>
/coord lane <session name>
```
`/coord lane` reads `~/.claude/kickoffs/<session name>.md` itself on a fresh session (the kickoff-on-clear hook fires only on `/clear`; at startup the session has no name yet).
Then the design session if any. Ask the owner to reply when all are open; do not message a lane that does not exist yet.

## 5. First wave
- [ ] Expect СТАРТ from each lane; answer hotspot waits with ЧИСТО.
- [ ] A seam-hardening slice (registries made append-only, shared types extracted) lands first if proposed.
- [ ] Switch to `operate.md`.

## Traps
- Lanes proposed by module boundaries only, ignoring data ownership -> "who may write X" gets re-litigated per slice. Write the ownership table once.
- Creating worktrees with `-b x origin/<integration>` -> upstream trap; see `worktrees-and-dbs.md`.
- Two lanes on one DB port -> silent cross-migration.
