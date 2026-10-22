# light-test - the light test and routing of a coding task (R4)

## Contents

- [Light test (R4)](#light-test-r4)
- [Routing (R4)](#routing-r4)

## Light test (R4)

MR1. For every coding task main fills the light test in `run.md` `## Tasks`, each answered yes/no:

- KL1 A command decides "done": a named test, a lint, or a failing test to make pass.
- KL2 The owned files are known up front: about 5 at most, in one module or layer.
- KL3 The change follows a pattern that already exists in the repo, named in the prompt.
- KL4 No decision is left: the spec or plan step fixes names, behaviour and data shape.
- KL5 No risky mechanism: no concurrency, locks, timeouts, retries, hardware, auth or
  security, migrations or data deletion.
- KL6 Not a bug fix, or the bug's root cause is known.

Row shape: `reference/queue.md` (run.md).

## Routing (R4)

- MR2 Six yes → `captain:light-coder`; its prompt carries the frame's `ESCALATE` line
  (`reference/prompts.md`). Any no → `captain:worker`, as before.
- MR3 `ESCALATE` → a fresh `captain:worker` with the hand-off prompt and its ESCALATE addition.
- MR4 Trap escalation: a mechanism with findings in two rounds under a light coder → the next
  fix goes to a fresh `captain:worker` (hand-off), instead of the usual trap handling (R6).
- MR5 Sonnet never runs above effort `high`.
- Without the plugin agent types: a light task goes to `Agent` with `model: sonnet` at default
  effort (the light writers' effort `high` cannot be set); `run.md` records the reason.
