---
name: coord
description: Use when starting or resuming a multi-session sprint, when the user says "coord", "/coord", "/coord lane", "/coord design", coordinator session, lanes, worktree lanes, КАЦНА/СЛИТО/ВНЕСИ messages, a handoff or kickoff between sessions, or wants parallel Claude Code sessions to build one repo without stepping on each other. Runs a software project as a parallel sprint of interactive sessions - one coordinator ("coord") that owns the process, merges and the board, implementer "lanes" in their own git worktrees that talk only to coord, an optional design session, and the human owner.
---

# coord - parallel sprint of interactive sessions

## Setup check (coord mode only, once per session)

Skip it for `/coord lane` and `/coord design`, and skip it if this session already asked or the owner declined (after `/clear`, check the kickoff/handoff for "hooks declined"). If `~/.claude/settings.json` does not register `kickoff-on-clear.py` and `handoff-at-boundary.py`, tell the owner once: "Hook-овете на coord не са инсталирани на тази машина. Команда: `bash <skill dir>/scripts/install-hooks.sh` (прави резервно копие на settings.json, идемпотентна). Да я пусна ли?" Run it only on the owner's explicit yes; otherwise continue without the hooks and say that kickoffs must then be pasted by hand.

## Mode detection (do this first)

`<skill dir>` below = the base directory shown when this skill loads (a plugin cache path, or `~/.claude/skills/coord`). Scripts and templates are relative to it.

Config = `<primary checkout>/.coord/project.md` (or the path the owner names). From a lane worktree, the primary checkout is `$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")`.

| Invocation | Config exists? | Mode | Read |
|---|---|---|---|
| `/coord lane` (or `/coord lane <name>`) | must exist | **lane** | `reference/lane-rules.md` + `reference/protocol.md` ONLY, then the config's row for this lane |
| `/coord design` (or `/coord design <name>`) | must exist | **design** | `procedures/design-interplay.md` + `reference/protocol.md` ONLY, then the config's row for this session. Never merges, never drives other tabs |
| `/coord` | no | **phase 0**, then **bootstrap** | `procedures/phase-0.md` (skips what is done), then `procedures/bootstrap.md` |
| `/coord` | yes | **resume**, then **operate** | `procedures/resume.md`, then `procedures/operate.md` |
| `/coord` in an old project with handoffs but no config | no | **resume via recon** | `procedures/resume.md` §"No config" |

**One coord only.** Before entering coord mode (any `/coord` row): if the cwd's git toplevel is not the primary checkout (a lane worktree), or the config names this session as a lane or the design session, or `ListAgents` shows a live session with the config's coord name, do NOT become coord. Tell the owner which mode applies (`/coord lane` / `/coord design`) and stop. Why: nothing else stops `/coord` typed in a lane worktree from starting a second coordinator that merges.

A lane never loads the coordinator procedures - they cost context and tempt it to act as coord.

## Roles

- **Owner** (human): product decisions, approves lanes, approves destructive/outward actions, opens sessions, types `/clear` then `/coord` (coord) or `/coord lane` (a lane).
- **coord**: never writes product code; the only session that merges into the integration branch; keeps one migration head, the board, the contracts between lanes; decides process and reports "for ratification".
- **Lane**: one worktree, one branch at a time, one test DB/port set, owns listed files and data; a mini-orchestrator that dispatches implementer subagents.
- **Design/prototype session** (optional): a peer, not a lane; feeds structure/copy/state through coord.
- **Subagents**: dispatched by coord or a lane, each with an explicit `model`, return compact summaries with `file:line`.
- Traffic is a star: lanes talk only to coord; coord talks to lanes and the owner.

## The 10 core rules

1. **Re-derive state, never recall it.** Git refs, CI, DB heads, who is on what: run the command at the point of use (`scripts/derive-state.sh`). Why: a stale "only tasks 1-2 can start" was repeated as fact hours after it became false.
2. **Only coord merges**, `--no-ff`, batched: stage several КАЦНА, verify the combined tree once, push once; never another commit while a merge is staged. Why: an unrelated docs commit silently completed a staged merge.
3. **Test in three tiers, not everything every time.** Lane: the touched area + typecheck + build. Coord, every batch: build + smoke (config `smoke_commands`, ~3 min). Full suites (every flag, counts and skip reasons checked) at the end of a scope and for batches touching `high_risk_paths`. Why: waiting on full suites after every small slice cost the owner more than the bugs they caught during development; a clean merge is still not a working merge at the end.
4. **Ownership is law.** A lane edits only its own files/data; hotspots are append-only and named in СТАРТ; ask who owns a line before ordering it changed.
5. **Messages are protocol, not chat** (`reference/protocol.md`): first line self-contained, no FYI to idle sessions, open questions labelled AS questions. Why: a relayed "goes to the owner" was implemented as an invented behaviour.
6. **Owner time is batched.** Coord decides mechanical/process matters and reports "for ratification"; product questions go in one batch, each with a recommendation; destructive/outward actions (deploy, force, delete, publish) wait for the owner's own yes. A permission refusal is never routed around. Away (the owner said so, or 20 min without an answer): product questions go to a three-model vote (`procedures/votes.md`) and the owner gets a brief on return; irreversible and destructive actions still wait.
7. **Hand off at a task boundary once context >= threshold** (default 250k, measured by `scripts/measure-context.py`). Handoff = decisions + open questions + commands, never state; write the successor's kickoff to `~/.claude/kickoffs/<session name>.md`.
8. **Budget is a first-class variable.** Every agent names its model; one reviewer per slice; coord reads small diffs itself; CI only on the integration branch; no silent process growth.
9. **Believe the running code over documents, and evidence over theories.** Give fix agents symptoms, never hypotheses; a negative claim is only as wide as its search.
10. **The board is data, reported not verified.** Update on protocol events via batched, version-pinned writes; decisions live in documents, never on the board.

## Index - read WHEN

- `procedures/phase-0.md` - no approved parallel-sprint plan yet: spec → plan → one review round → prototype/design → readiness gate; calls the planning/review/prototype skills, never re-implements them.
- `procedures/bootstrap.md` - no config yet: recon, propose lanes, create worktrees/DBs/config/board, give the owner session names + kickoff lines.
- `procedures/resume.md` - a config or handoffs exist; start of any coord session.
- `procedures/operate.md` - the steady-state loop; what to do on each message type.
- `procedures/worktrees-and-dbs.md` - creating/repairing a worktree, test DB, ports; odd DB failures.
- `procedures/merge-and-verify.md` - every КАЦНА, every merge, migrations, contract relays.
- `procedures/ci-budget.md` - CI config, red/empty checks, minutes budget.
- `procedures/handoff-and-sessions.md` - context near threshold, `/clear`, restarts, name swaps.
- `procedures/cmux-automation.md` - the owner runs sessions in cmux and enabled it: coord opens lane tabs and restarts lanes after handoff itself.
- `procedures/scope-deadline.md` - the owner gives a scope a deadline; a SCOPE timer fires; resuming with one armed.
- `procedures/votes.md` - any vote (architecture/contract rulings; product questions while the owner is away).
- `procedures/decisions-and-owner.md` - anything needing the owner; recording decisions; the "Чакат теб" list of sessions waiting on the owner.
- `procedures/board.md` - creating or updating the board.
- `procedures/review-and-models.md` - dispatching any agent or review.
- `procedures/quality-and-rehearsal.md` - failures, test trust, milestones with real users.
- `procedures/design-interplay.md` - a design/prototype session or design docs exist.
- `procedures/data-and-secrets.md` - personal data, paid API keys, read-only roles.
- `reference/protocol.md` - message keywords and required fields (coord and lanes).
- `reference/lane-rules.md` - everything a lane follows (`/coord lane`).
- `reference/traps.md` - symptom -> cause -> rule; read when something looks wrong.
- `templates/` - `sprint-plan.md` (what a plan needs to be parallelized), `project-config.md`, `coord-kickoff.md`, `lane-kickoff.md`, `handoff.md`, `kacna.md`, `review-prompt.md` (Codex review), `owner-batch.md`, `board-schema.json`.
- `scripts/` - `derive-state.sh <repo> [--fetch] [--config p] [--log N]` (read-only without --fetch), `measure-context.py <repo> [hours] [--threshold N] [--all]` (live sessions by default; threshold defaults to the config's `context_threshold`), `install-hooks.sh` (once per machine; installs `hooks/*.py`), `vote.py codex <prompt> <out dir>` (Codex votes and reviews; own timeout), `cost-report.py <~/.claude/projects/<dir>> [--since DATE]` (spend by model, context buckets, small-call share, cache rewrites; numbers only).
