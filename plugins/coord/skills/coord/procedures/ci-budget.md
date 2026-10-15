# CI and budget

## Workflow shape (set once at bootstrap; owner approves CI file changes)
- [ ] `push` trigger on the integration branch only, with `paths-ignore` for docs (`docs/**`, `**/*.md`). No `pull_request` trigger if lanes keep draft PRs (it doubles runs). `workflow_dispatch` for by-hand runs.
- [ ] Concurrency: cancel superseded runs on other refs, but key the integration branch's group per commit (e.g. `group: ci-${{ github.ref == 'refs/heads/<integration>' && github.sha || github.ref }}`). Why: a per-ref group on the trunk silently drops the middle run of quick successive merges.
- [ ] One matrix entry per e2e suite, each with its own fresh service-container DB, `fail-fast: false`. Correctness ("each suite on its own clean DB") beats minutes saved by a shared sequential job.
- [ ] A suite joins the matrix only once proven green on its own; until then list it in a "not yet in CI" comment with an owner lane.
- [ ] A spending limit / stop-usage switch as a backstop once a budget line is set.

## Rules
- Lanes do not trigger CI by pushing (triggers exclude lane branches). They dispatch by hand only when coord asks; coord usually verifies locally.
- GitHub reads triggers from the PUSHED branch's workflow file: a lane branch cut before a trigger change burns minutes until it merges integration in.
- Coord pushes integration once per code batch. Docs-only pushes cost nothing when `paths-ignore` excludes docs - push handoffs and decision records immediately (a successor reads them from origin).
- When minutes run hot, measure where they go (`gh run list --limit 100 --json headBranch,event,...`); the lever is usually lane-branch runs.

## Reading a red check
- [ ] Zero steps, no log -> billing/usage block, not a test failure; read annotations (`gh api repos/<o>/<r>/check-runs/<id>/annotations`).
- [ ] CI-only failure -> reproduce by widening the gap (inject a delay), not by re-running. Local green is weak evidence either way.
- [ ] A run on an old sha is not evidence for the current head.

## Session budget
- Coordination traffic, not code writing, is the main cost; coord absorbs cross-lane questions.
- Every wake of a session is a full-context turn: no FYI messages, no unconditional timers.
- Hand off at a task boundary once context >= threshold (`handoff-and-sessions.md`).
