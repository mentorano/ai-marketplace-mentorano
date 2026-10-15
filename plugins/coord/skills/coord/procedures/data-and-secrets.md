# Data and secrets

## Real/sample personal data in the repo tree
- Exclude via `.git/info/exclude` (local), not the tracked `.gitignore`: protects every worktree sharing that `.git`, NOT a fresh clone. If it must travel, move it out of the repo; never commit it.
- Derived data (extracts, exports) from real people is torn down with the environment that made it; record the teardown.

## Data policy decisions
- An explicit, dated owner decision on a data-sharing policy overrides a stricter earlier plan default. Do not add anonymization/region gates unasked after such a decision; log it with date and the owner's words.
- Regardless: keys never in logs, frontend code, commits or messages.
- Broad read access for a role never widens its write access; whether the people read about are told is the data owner's decision - ask, never assume.
- Responses carrying personal data default to non-cacheable (`Cache-Control: no-store`); an exception needs its own reasoning.

## Paid/shared API keys
- A key exported in the developer's shell must not leak into tests: tests pass an explicit env (e.g. `env -u <KEY_VAR> <cmd>`) or use a stub/offline client; redact when printing env.
- Verify a key's rate/cost tier before a real batch; a free-tier cap can die mid-run and failed jobs may not retry. Compare keys by hash, never print them.
- A key shared by two projects: schedule heavy batches so one does not starve the other.
- Spending real money (paid batch) is an owner-approved action.

## Real-data harnesses
- A separate read-only DB role for any reporting/measurement job on real data, plus an explicit read-only transaction in the harness itself (two independent guards).
