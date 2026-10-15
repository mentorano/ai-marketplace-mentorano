# Review and model choice

## Every dispatched agent names its `model`
| Model | Use |
|---|---|
| `haiku` | lookups, extraction, file/code search, board writes, status checks |
| `sonnet` | implementation, recon, plan drafting/revision |
| `opus` | the fallback code reviewer when Codex fails, architecture, security, concurrency, migrations, personal-data handling, fix-loop escalation |

Code review is Codex first: `gpt-6-astra` through its own CLI (no plugin, no Claude agent), so a review costs no Claude tokens. Measured 21.09-01.10: ~340 subagent reviews cost ~$250-280 of Claude spend in 10 days. The fallback is opus, not sonnet: cache reads cost the same on both models, so a Sonnet call is only ~0.65x an Opus call (~0.97x in reviews), and Sonnet reviews took 1.3x the calls. Re-measure with `scripts/cost-report.py`.

## Review policy
- Default: ONE review per slice by Codex (recipe below, prompt `templates/review-prompt.md`), all lenses in one pass (correctness, security, spec/contract compliance, tests that actually test). One fix round, one scoped re-review. Never "until APPROVED".
- High-risk slices (auth, payments, migrations, concurrency, personal data) marked in the plan: per-lens reviews, each a separate Codex run with a lens-specific prompt, one skeptic pass per lens (not per finding); opus only where a Codex run fails.
- Plan review: one round + one revision; a second round only if the first had blocking findings.
- Coord reads small diffs itself instead of spawning a reviewer.
- Codex review: write the review prompt (`templates/review-prompt.md`) to a file, then
  `python3 <skill dir>/scripts/vote.py codex <prompt> <log dir> --contract review --timeout 1200 --effort medium --cwd <worktree>`
  (background Bash). Valid = `status: voted`, answer `approve|changes`; findings are in `<log dir>/codex.out`.
  `missing` (timeout, usage-limit, missing-binary, login, empty, invalid): ONE fallback reviewer (opus), one line to the owner naming `why`. Never a retry loop, never "until APPROVED".
- Settled-findings register: every finding rejected in round 1 gets one line (`F<n>: rejected — reason`); the round-2 prompt carries the list and says "a re-raise needs a line starting NEW EVIDENCE:". A re-raise without it is settled.
- Triage each finding: reachable in normal use? (yes/no); origin (this slice / earlier); impact (data loss, wrong result, cosmetic). After round 1 fix only real defects reachable in normal use; the rest go to the backlog. A fix that breaks the previous fix (fix-of-a-fix): stop, ask the owner (away: vote).
- No silent process growth: adding a recurring stage needs the owner told, with agents/week estimate. Why: review/board stages crept into handoffs and tripled weekly agents in one week.

## Briefing any agent
- [ ] Absolute paths (worktree), `file:line`, contracts it cannot know, hotspots to avoid, exact test commands with ports and flags.
- [ ] Binding rules quoted verbatim; no added allowances.
- [ ] Fix agents: symptom + evidence, never a hypothesis; mechanism by observation before editing; forbid loosened selectors, deleted assertions, lowered thresholds, skips; "a real regression found is a good outcome".
- [ ] Return format: short summary + `file:line`, or a schema; never raw diffs or file dumps.
- [ ] Negative claims must state where and on which branch they searched.
- [ ] "Done" needs evidence: log path, the result line, the sha. A "done" without it goes back.
