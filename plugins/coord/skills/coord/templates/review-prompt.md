# Review prompt (Codex, or the fallback reviewer)

Write it to a file and pass it to
`python3 <skill dir>/scripts/vote.py codex <file> <log dir> --contract review --timeout 1200 --effort medium --cwd <worktree>`
(`--effort high` only for a very complex spec or implementation). The fallback reviewer gets the same text.

```
Review <slice id - title> in <absolute worktree path>. Read-only: do not edit files, do not search the web.
Range: <base sha>..<head sha> (`git diff <base>..<head>`). Nothing after <head sha> is in scope.
Spec / brief: <path> §<n>. Contracts this range must keep: <list, or "none">.
Check in one pass: correctness, security, spec and contract compliance, tests that actually test
(a test that cannot fail is a finding).
Settled findings (round 2 only, else omit): <F1: rejected - reason; F2: ...>. A re-raise needs a line
starting `NEW EVIDENCE:`; without it the finding stays settled.
For each finding: number, file:line, the defect in one sentence, a concrete failure scenario,
reachable in normal use (yes/no), origin (this range / earlier), impact (data loss / wrong result / cosmetic).
Answer format, first line exactly `Verdict: approve` or `Verdict: changes` (changes only for a finding
reachable in normal use), then `Findings:` (numbered, or "none"), then one line `Non-blocking: ...` or `Non-blocking: none`.
```
