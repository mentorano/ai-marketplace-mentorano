# Traps: symptom -> cause -> rule

Stack examples (pytest, alembic, Playwright, vitest, zsh) are illustrations; the pattern is general.

## Environment and test runs
1. **Tests error at fixture setup with an unrelated-looking connection error** -> a DB URL var is empty: back-referenced in the same `export` (`export A=x B=$A`), or only one of two required vars set -> export each var on its own line; pass every required var each run; copy the provisioning script's printed export line.
2. **"N passed, M skipped" looks complete** -> a test class skips silently without an env flag -> always set the config's flags; check skip reasons against the baseline before calling a run "full".
3. **`runner <child> <parent>` is green but ran only the child** -> naming one test root drops the others the config lists -> run the full suite from the repo root with no subpaths.
4. **`ModuleNotFoundError` for a bare helper import when running one test dir alone** -> the helper resolves only after a sibling dir is collected -> collect that dir first or run unscoped.
5. **Migration tool reports current after re-pointing a parent, then hundreds of "relation does not exist"** -> the version table names the old tail; `upgrade head` is a no-op -> drop and recreate the DB after any parent change.
6. **A stashed-diff control run reproduces the same failure counts** -> both runs share one broken environment -> compare migration current vs heads (and env vars) first; a control run proves authorship, not health.
7. **Leftover-row assertions after an e2e run** -> e2e left rows in the shared DB -> `down -v` then the provisioning script (the script alone only migrates a running container); unit/integration before e2e; never re-run an e2e suite on a dirty DB.
8. **An e2e suite reports "0 expected, 0 unexpected"** -> its fixed port is taken by another run -> print the raw error array; wait for the port (`lsof -iTCP:<port>`); never kill an unknown listener.
9. **e2e web server dies with "command not found" for the interpreter** -> the config's default interpreter is not on PATH -> pass the interpreter path and DB vars explicitly.
10. **`document is not defined` in a unit run** -> runner started from the wrong cwd, missed its config -> run from the package root the config names.
11. **A stopped test-DB container comes back empty** -> plain `compose up` recreates without schema/roles -> recreate via the provisioning script.
12. **`pytest $(ls glob*.py)` runs the whole suite** -> an unmatched glob aborts the substitution, leaving no args -> build file lists with find/grep.
13. **`tests | tail` shows failures but the commit/push went out** -> the pipeline's status is `tail`'s -> redirect to a file, check the runner's exit code.
14. **Line numbers in a failure point at unrelated code** -> the runner reports transformed-code positions locally -> navigate by test title; note which environment produced a number.
15. **A live reporter piped through `tail` gives a plausible wrong result** -> cursor-control rewrites get spliced -> use a JSON/line reporter for anything you act on.
16. **Red in CI, green on many local re-runs (or the reverse)** -> a real race that a faster machine outruns -> widen the gap (inject a delay on the suspect request); never relax the assertion.
17. **A local visual/overflow assertion fails on a clean checkout while CI is green** -> local rendering env differs -> control run, name the mismatch in LANDED; re-confirm before trusting an old note.
18. **A command stored in a variable fails oddly in zsh** -> zsh does not word-split `$CMD` -> write the command out or use an array.

## Git and worktrees
19. **A new lane branch's bare push/pull targets the integration branch** -> created from `origin/<integration>`, which became its upstream -> `--no-track` or first push `push -u origin <branch>`.
20. **A subagent says "file not found", then reads an old same-named file** -> shell cwd resets to the primary checkout; paths exist in both at different versions -> absolute worktree paths always; verify a "missing file" yourself.
21. **An editing tool "succeeds", suite green, nothing changed** -> the tool resolves paths against its own root (the primary checkout) -> direct absolute-path edits in worktrees; check the test COUNT moved.
22. **Lane code staged uncommitted on the integration branch** -> coord's live staged merge -> ask coord; never reset/add/commit it.
23. **An unrelated commit published a whole slice under the wrong message** -> a merge was staged with `--no-commit`; the next commit completed it -> never commit anything else while a merge is staged.
24. **Second branch of one lane: "can't locate revision"** -> both share the lane's test DB; the other branch migrated it -> decide who migrates, or give the second branch its own DB.
25. **A lane branch keeps burning CI after the trigger was restricted** -> GitHub reads triggers from the pushed branch's own workflow file -> merge integration into the branch.

## Merges and contracts
26. **A page 500s on a state no test drove, right after a fully green merge** -> the merge widened a producer's enum/status; a consumer kept its own narrower copy -> grep consumers for local copies of a widened type; ask for an imported type or an equality test.
27. **Zero-conflict merge breaks at runtime** -> two lanes edited one file in different places (rename vs old call site) -> build + smoke on every merged batch, plus the touched areas' tests of both slices when they overlap; full suites at the end of the scope; treat overlap warnings as semantic risk.
28. **A test "passes" with a docstring and no body** -> conflict markers were deleted, not resolved -> assemble the real result from both parents.
29. **A fresh session's contract contradicts what its predecessor promised** -> it rebuilt from an older spec -> grep the consumer's handoff for the symbol; compare parameter NAMES.
30. **A required field in a shared type mirror breaks fixtures** -> tempting to make it optional -> fix call sites; never weaken the mirror.

## Communication and reasoning
31. **An open question comes back implemented as an invented behaviour** -> relayed without a question label -> mark non-decisions as OPEN, naming the owner.
32. **A fix agent fixes the wrong thing, suite green** -> the brief stated a theory -> symptoms and evidence only; mechanism by observation; forbid easy greens; say a real regression is a good find.
33. **A slice breaks a binding rule though the implementer followed the brief** -> the brief added an allowance -> quote rules verbatim.
34. **"X does not exist" turns out false** -> the search was narrower (capped listing, one module, wrong branch) -> name where and on which branch; no head/tail-capped proof of absence.
35. **A `file:line` is wrong minutes after it was verified** -> the tree is merging continuously -> re-grep before trusting; record the commit citations were checked against.
36. **Coord assigns work that merged 40 minutes ago** -> a delta/design doc treated as state -> check git log before assigning.
37. **An idle lane with no message** -> usually at its context ceiling, not blocked -> measure before nudging.
38. **Messages around a restart vanish** -> they landed in the dying session -> check the "started" timestamp; re-send decision-bearing messages from the last half hour.

## Data and quality
39. **A real-data walkthrough breaks at the last step despite thousands of green tests** -> fixtures share the code's assumptions -> real-data dress rehearsal before any milestone with real users.
40. **"Logged" telemetry is missing when needed** -> log handlers were never wired -> persist telemetry you will read (e.g. in the job's stored result); guard its writer.
41. **A calibrated threshold does nothing on a larger batch** -> the sample shared one narrow trait -> name the single separating parameter; re-check on the first real batch.
42. **A new test passes with the behaviour removed** -> sample data matched by coincidence -> mutation-check: break the behaviour, see the test fail.
43. **A GitHub check with zero steps and no log** -> billing/limit block, not a failure -> read annotations first.
44. **Two near-identical progress labels disagree** -> a consumer bound to the wrong counter -> bind to the same source function the reference screen uses.
