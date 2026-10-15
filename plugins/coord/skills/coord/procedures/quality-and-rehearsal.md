# Quality and dress rehearsal

## Trusting a test result
- [ ] "Full" = the config's full commands (end of scope or high-risk batch), from the directory named, every flag; collected count and skip reasons match the baseline (only listed environment-dependent skips accepted). "Smoke" is never reported as "full".
- [ ] Output to a file; the runner's exit code checked, not `| tail`'s.
- [ ] Structured reporter for anything acted on; navigate e2e failures by test title, not line number.
- [ ] A control run (stash, re-run, compare) proves "not my diff", never "code is healthy"; exclude the environment first (migration current vs heads, env vars, DB freshness).
- [ ] New tests are mutation-checked: break the behaviour, watch the test fail.
- [ ] CI-only or local-only failures: widen the gap to reproduce; neither environment's green proves absence.
- [ ] Known local-vs-CI mismatches are named in LANDED after a control run, and re-confirmed before trusting an old note.

## Evidence discipline
- Running code beats documents; get the document corrected.
- `file:line` citations are claims about a moment; re-grep before trusting; record the commit a document's citations were verified against; re-pin all at reconciliation.
- "X does not exist" names the path and branch searched; no capped listing as proof.
- An unreproduced diagnosis is a hypothesis; say so when relaying.
- Telemetry you will need later is persisted (e.g. in a job's stored result), not only logged; its writer never blocks the real operation.
- Calibrating a threshold on a sample: name the single separating parameter; flag narrow samples; re-check on the first real batch.

## Shared derived state
- One predicate/value feeds every screen needing the same derived state (e.g. "read-only, and why"); consumers never recompute a local copy.
- Two similar counters from different sources: bind new consumers to the reference screen's source function.
- One accessibility/permission rule applied everywhere (e.g. locked-for-now = disabled with reason; never-allowed = hidden), decided once.

## Real-data dress rehearsal (before ANY milestone with real users)
Why: every suite was green and the real path still broke at its last step - fixtures share the code's assumptions.
1. [ ] Schedule it as its own task on the board, early enough to fix what it finds (days, not hours).
2. [ ] Real inputs (a real sample, with the owner's data policy), the real external model/API, the real UI, end to end, in an isolated env (own compose project/port) - read-only roles for any harness touching real data.
3. [ ] Owner or coord walks the user path; every defect gets an id, an owning lane, and an in-milestone/after-milestone call (owner batch).
4. [ ] Confirmation run after fixes on the same inputs; check no regression on what passed.
5. [ ] Tear down the env, its volume and any derived personal data; record that it was torn down.

## Sprint process
- No formal validation reports during a fast sprint; never drop tests; commit messages say what and why.
