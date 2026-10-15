# triage - classes, round threshold, the trap, the register (R6)

## Contents

- [Who does what](#who-does-what)
- [Triage fields - the writer fills them per finding](#triage-fields---the-writer-fills-them-per-finding)
- [Classes](#classes)
- [Round threshold - the captain applies it](#round-threshold---the-captain-applies-it)
- [Priority when rules overlap](#priority-when-rules-overlap)
- [Data loss in normal use](#data-loss-in-normal-use)
- [The fix-of-a-fix trap](#the-fix-of-a-fix-trap)
- [`fix-all` runs - TODO is the last resort (ЗД1)](#fix-all-runs---todo-is-the-last-resort-зд1)
- [When the loop stops](#when-the-loop-stops)
- [The register](#the-register)
- [New work between rounds; the verifier](#new-work-between-rounds-the-verifier)

The evidence is one web app project, 27.09.2026: 4 review loops, 73 findings. After round 1,
23 of 41 findings were defects in the previous round's fix, and only 1 was a new real bug.

## Who does what

- **Reviewer**: labels each finding `blocking` or `non-blocking` and states the path. The
  label is input, not the decision.
- **Writer**: revalidates each finding against the source, fills the triage fields, proposes a
  class with evidence. It does not edit or commit in this step.
- **Captain**: applies the round threshold to the fields, mechanically. It never fixes or
  edits code itself (R1). A field that is missing or unclear goes back to the writer. It sends the writer the
  FIX NOW list, and product or policy questions to the owner.

**Why:** in that project the writer fixed 67 findings, rejected 2 and deferred 0, and gave in when
a rejected finding came back. The reviewer called races "high" that need an artificially held
promise.

## Triage fields - the writer fills them per finding

```text
F<n> | reachable: normal use (steps: <user steps>) | artificial (<held promise, injected timing, tampered local store, ...>) | not shown
     | origin: change | round-<k> fix F<m> | pre-existing
     | impact: data loss | security | build/test broken | wrong result | degraded | none (nit/style)
     | mechanism: <name of the lock, timeout, marker, counter, queue or threshold involved | none>
     | proposed: FIX NOW | ACCEPT <reason> | TODO <behaviour | owner decision | hardening | tests>
     | evidence: <failing test, input, or code path file:line>
```

"not shown" means the writer cannot show the defect with an input, a failing test or a
concrete code path. Such a finding is `ACCEPT not confirmed`. No hardening commit "just in
case".
**Why:** a finding there was not confirmed, and a follow-up fix still cost one more review.

## Classes

Every finding gets exactly one class.

- **FIX NOW** — a confirmed defect that meets the round threshold. The fix is minimal.
- **ACCEPT** — no change. One reason from this list: `not confirmed`, `artificial timing or
  input`, `path not used`, `nit/style`, `valid design`, `owner decision`, `settled` (a re-raise,
  see the register).
- **TODO** — a real problem whose action belongs to a later session: a behaviour change, a
  policy (timeout, threshold, retry), a product decision, hardening, tests in round 2+. Entry:
  `reference/queue.md`, TODO entry for a deferred finding.

In round 2+ a fix adds no new mechanism: no new state, timeout, counter, protocol field or new
server check. A type or shape check on an existing input field is not a new mechanism; a new
check that ties a request to state (e.g. a field in the request checked against server state)
is. If a mechanism is needed, the finding goes to the owner (present) or TODO (away), not
to a fix.
**Why:** one run's r3 F1 grew a protocol change (a new request field plus a server check) for a race
under 100 ms; the r3 counter caused r4 F1.

## Round threshold - the captain applies it

| Round | FIX NOW when the fields show | Else |
|---|---|---|
| 1 | reachable `normal use`, or a concrete input with a local fix; origin `change`; impact other than `none`. Also: missing tests for the change, wrong docs, and a `nit/style` whose fix takes under 2 min. | `nit/style` over 2 min → ACCEPT. `not shown` → ACCEPT. New behaviour or `pre-existing` → TODO. |
| 2+ | reachable `normal use` with steps, origin `change` or `round-<k> fix`, impact `data loss`, `security`, `build/test broken` or `wrong result`. Also: a type or shape check on an existing server input field, with a concrete input. | `artificial` → ACCEPT (TODO when it touches data integrity). `pre-existing` → TODO. Tests → one TODO for the loop. `nit/style` → ACCEPT. A policy or a new mechanism → the trap. Any other confirmed finding (e.g. impact `degraded`) → ACCEPT, or TODO when it changes behaviour. |

Round 1 is exhaustive: it finds 10 of 11 real defects in the change. Round 2+ blocks only on
reachable real defects.
**Why:** in that project new real defects per round went 10 → 1 → 0 → 0; rounds 3-4 found only
defects in the loop's own fixes.

**Mock mode.** A task whose output is a throwaway prototype (an HTML mock, a click-through
demo, marked `mock` in `## Tasks`) gets round 1 only, and only for findings reachable in normal
use with steps; everything else is ACCEPT or one TODO line. No round 2 unless the round-1 fixes
changed behaviour the owner looks at.
**Why:** 01.10.2026: 2–3 Codex rounds per micro-task on an HTML mock (about 25 min), and the
captain itself classed the findings as artificial.

## Priority when rules overlap

Apply the first that matches: (1) data loss in normal use → FIX NOW; (2) a verifier failure →
FIX NOW; (3) the trap; (4) the round table. A verifier failure is an observed fact on real
data, so it is reachable in normal use by definition. Its fix still adds no new mechanism: if
it needs one, it goes to the owner (present) or TODO (away).
**Why:** the owner's answer ВК2 (27.09): a verifier failure beats the trap; in that project the
verifier found the real bugs and review rounds 2-4 did not.

## Data loss in normal use

A finding with impact `data loss` and reachable `normal use` with listed user steps is FIX NOW
in every round and every mode. It overrides the round threshold and the trap. An artificially
held promise, injected timing or a tampered local store does not count. No user steps →
ACCEPT or TODO by the table.
**Why:** without this, one run's r3 F3 (an unknown seq lowers the counter) goes to TODO in away mode:
a real bug missed.

## The fix-of-a-fix trap

A mechanism is one piece of state with a policy: a lock, timeout, marker, counter, queue or
threshold. It is in the trap when it has findings in two rounds of one loop. Data loss in normal
use and a verifier failure come first (priority above). Then the writer
does not iterate. It returns `MECHANISM: <name>`, what the code does now, and 2-3 options.

- Present mode: the captain asks the owner one question (R19 IDs on the options).
- Away mode: TODO (queue.md format); the current behaviour (the last reviewed fix) stays. Full
  consensus (R9) only when that behaviour loses data in normal use.
- The owner answered and the mechanism comes back → TODO without a new question, except for
  data loss in normal use.
- A `fix-all` run: first the one extra writer below (time does not cover it → TODO), then the
  line for the mode.

**Why:** a lock timeout went 30 s → 15 s → counter → "blocks forever": r2 F3 "30 s loses the
upload", r3 F2 "15 s still loses", r4 F1 "the counter blocks forever". It should have been an
owner question after r2.

## `fix-all` runs - TODO is the last resort (ЗД1)

**Set once, at start step 6.** Main decides whether the run fixes a given list: the task names
items or TODO IDs to fix ("оправи всички", "fix ВР3–ВР7", a review's open findings). Then it
writes one line in `run.md`: `mode: fix-all — <reason>`; otherwise `mode: normal — <reason>`.
Present: the line is shown with the plan, and the owner may flip it; away: inferred and logged
in `decisions.md`. It does not change during the run unless the owner says so.

**One more writer for a trapped mechanism.** In `fix-all`, a mechanism in the trap gets one
more fresh `captain:worker` (the hand-off prompt, `reference/prompts.md`) before the owner
question or TODO, only when the time to park covers that writer's limit plus one re-review
timeout. Its prompt carries a new hypothesis, written by main in one or two lines: what the
previous fixes assumed, and the different cause to try now. It does not reset the loop's
re-review count (at most 3), and it is the only extra writer per mechanism. Its fix still
goes through the round threshold; new findings on the same mechanism → the trap as usual.
Time does not cover it → TODO with the reason "does not fit the box", in both modes.

**TODO only with a reason.** Every TODO entry the run adds (a cut, R18, or a finding classed
TODO) carries a one-line reason, e.g. "does not fit the box", "needs the owner", "needs
production". The end report lists each new entry with its reason and counts TODO entries
closed and added (`reference/queue.md`, end report).
**Why:** 13.10.2026: in a run whose task was "fix everything", R6 traps and R18 cuts sent work
to TODO; the owner: "the goal was to fix them, and you add new TODOs".

## When the loop stops

The loop stops when triage leaves no FIX NOW. It does not wait for `Verdict: approve`. No new
commit means no unreviewed commit. Once the last round has confirmed that the earlier FIX NOW
findings are closed, `run.md` `## Reviews` records `passed (no FIX NOW)` for the whole loop
range, from the loop's base to its last fix commit, and the R5 push gate treats that range as
passed. The bound of 3 re-reviews stays. After the first runs under these rules, the
coordinator reports the round counts to the owner; only the owner decides to lower the bound.
A clean loop → main merges at once (`reference/queue.md`, the merge flow step 1), without
asking; the task's `ЗДn` row becomes `merged`; then a runner runs the tests on the merged head;
the R5 push gate comes after.
**Why:** in that project one loop's r2-r4 took ~26 min for fixes of fixes.

## The register

- **decisions.md**: one line per ACCEPT or TODO finding (format: `reference/queue.md`). Refuted
  findings and nits live only there and in the reviewer register.
- **Reviewer register**: from round 2 the review prompt carries the register lines. A re-raise
  without `NEW EVIDENCE:` (a new input, a failing test, a new code path) is `ACCEPT settled`;
  the writer does not revalidate it.
- **Accepted risks**: a real risk accepted on purpose also gets one line under
  `Accepted risks:` in the body of the fix commit message:
  `- <loop> r<k> F<n> <risk, one line> (in <sha of the commit that holds the risk>)`.
  A round with no fix commit: the line goes into the next commit of the same task; none → into
  the R17 TODO/docs commit. Never amend, never an empty commit (R5 would see an unreviewed one).

**Why:** one run's r1 F8 came back as r2 F6 and the writer gave in; in another run's r2 the prompt said "do
not re-raise" and F4 did not come back. The owner's answer ВК1 (27.09): accepted risks stay in
git history even when a round has no fix commit; decisions.md lives in ignored tmp/.

## New work between rounds; the verifier

- An owner request between rounds is a new task in `run.md` `## Tasks`, with its own round 1
  and its own 3 re-reviews. The old loop's round 2 reviews only its own fixes. Both reviews may
  run in parallel.
- Work with a path through hardware or real local data gets the verifier right after the
  round-1 fixes, in parallel with review round 2. A verifier failure is FIX NOW in every round
  (priority above).
  Review round 3+ starts only for a FIX NOW. Threshold calibration (a cutoff, a σ) is a
  TODO or an owner question with measurements, not a review round.

**Why:** in one run, "round 2" was round 1 for ~13 new UI commits and ate the old loop's budget. The
verifier on real hardware found the real bugs (a reversed order, an empty result for up to
0.3 s); review r2-r4 found theoretical races.
