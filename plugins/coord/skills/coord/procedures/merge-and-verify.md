# Merge and verify (coord only)

## Checks that are easy to skip (each cost a real incident)
- [ ] A batch touching UI runs at least the smoke e2e paths; the full acceptance suite runs at the end of the scope.
- [ ] Before verifying, dependency dirs in the checkout (`node_modules`, `.venv`, …) are real directories, not symlinks into another worktree (a symlinked dir tests someone else's install).
- [ ] After every push: `gh run list --branch <integration> --limit 1` until the run is picked up and green; a job with zero steps and no log did not run (billing/limits), read the annotations.

## Batch cycle
1. [ ] `git -C <repo> fetch -q`; confirm the primary checkout is clean (`git status`): a staged merge from before must be finished first.
2. [ ] For each queued КАЦНА, check the ancestor FIRST: `git merge-base --is-ancestor origin/<integration> <branch@sha>`. Not an ancestor -> ВНЕСИ to the lane, drop from batch. Why: a verification of a branch tens of commits behind is thrown away.
3. [ ] Merge the reported sha, not the branch head: `git merge --no-ff --no-commit <sha>`; inspect `git diff --cached --stat`; commit with a message naming what changed, why, the slice id, `<branch>@<sha>`, and decisions it implements. Repeat per slice (several merge commits, one push).
   - Only ONE migration-bearing branch per batch; re-check heads after it (config's heads command) - exactly one.
   - Conflicts: assemble the real result from both parents; deleting markers is not resolving (an empty test "passes").
   - Never make any other commit while a merge is staged. Why: the next commit completes the merge under its message.
4. [ ] While the long suite runs, more КАЦНА may join; frontend-only branches may join until the frontend phase starts.
5. [ ] Verify the combined tree ONCE, by tier (`SKILL.md` rule 3):
   - Every batch: build + the config's `smoke_commands`. No `smoke_commands` in the config yet: build only, and ask the owner once which 3-5 critical paths form the smoke set.
   - Full (the config's test commands, every flag; pytest-style before e2e, each e2e on a clean DB): when the batch touches `high_risk_paths` (migrations, auth/roles, personal data), and at the end of a scope (`scope-deadline.md`).
   - Smoke red: take only the failing slice out (bisect by slice), return it to its lane as symptoms + evidence; merge the rest.
   Redirect output to files; check exit codes, counts, skip reasons.
6. [ ] Semantic checks the suites miss:
   - [ ] Enum/status/Literal widened? grep every consumer for its own local copy.
   - [ ] A shared type mirror gained a required field? fix call sites, never make it optional.
   - [ ] Two lanes touched one file? read the combined hunks; zero conflicts can still break.
   - [ ] Slow I/O under a shared write lock? pattern: authorize under lock -> commit -> slow work outside -> re-lock, re-check, write.
7. [ ] Push once. CI runs on the integration branch (`ci-budget.md`).
8. [ ] СЛИТО to each owning lane (with the explicit next action); ВНЕСИ only to lanes the change touches; board batch.

## When the merged tree fails
- [ ] Environment first: migration current vs heads, required env vars, DB freshness. Mass errors in one module's tests -> schema; scattered assertion failures -> code.
- [ ] Compare trees: `git diff <lane sha> HEAD --stat` (staged vs lane). If only docs or unrelated files differ from what the lane verified, the failure is environmental.
- [ ] A lane's green CI ages: it was green against integration AT THAT MOMENT. `merge-tree` answers "conflicts?", not "passes?".
- [ ] Bisect by slice: unstage the batch (`git merge --abort` / reset to the pre-batch sha, owner not needed for local unpushed state), re-merge one at a time.
- [ ] Return the failure to the owning lane as symptoms + evidence, not a theory.

## Migrations
- Numbering per the config: reserved ranges per lane, or simply the next number in one linear chain. The invariant is ONE head, not the range.
- Each migration round-trips (upgrade -> downgrade -1 -> upgrade); migration tests read the parent from the chain, never hardcode it.
- Coord may re-point a migration's parent at merge ONLY if it carries no copy of a shared SQL object; otherwise the owning lane refreshes the body from the CURRENT full definition, re-points, and names the exact head in КАЦНА.
- Re-provision restricted role fixtures after migrations that touch their objects. Rebuild DBs after any re-point.

## Contracts
- Before relaying a contract a freshly cleared session restated, grep the consumer's handoff/plan for the symbol; compare parameter names.
- Ask producers for a types-only commit early; refuse local protocol stand-ins and permissive monkeypatching in consumers.
- A guard for a constraint that only exists after another slice merges: keep a temporary stand-in in the guard's test that disables itself once the real one lands.

## Pairing rule
If slice A makes a state reachable that only slice B resolves, merge A and B in one batch; no deploy between.

## Destructive (owner approval)
Force-push, reset of pushed history, deleting branches, reverting a pushed merge, deploy.
