# Phase 0 - before the sprint (spec → plan → review → prototype)

Goal: arrive at bootstrap with a plan that can be parallelized. Coord orders the steps and dispatches the right skill for each; it does not re-implement planning, reviewing or prototyping. Skip any step whose output already exists and is approved - check, do not assume. The skills named below are suggestions: if one is not installed on this machine, do the step inline with the same output and tell the owner which skill was missing.

## 0. Decide where we are (one message to the owner)
- [ ] Look for: a spec/PRD, a plan, a design/canvas or prototype, owner decisions. Name each found file with its date.
- [ ] Tell the owner which steps below are done, which are missing, and the one you propose to start with. An existing approved plan (e.g. a project started mid-way) jumps to step 4.

## 1. Spec (what and why)
- [ ] If there is no spec: interview the owner - `grill-me-codex` (Act 1 only) or `grill-with-docs-codex` when the repo has a glossary/ADRs; or `to-prd` from a discussion. Output: a spec file in the repo.
- [ ] Record owner decisions in the amendments file from day one, with the owner's words.

## 2. Plan
- [ ] Draft with `superpowers:writing-plans`, then extend it to `templates/sprint-plan.md` - the parallel-sprint sections (lanes, ownership, hotspots, contracts, migration rules, order) are what a generic plan lacks and what bootstrap needs.
- [ ] High-stakes areas (auth, payments, migrations, concurrency, personal data) are marked high-risk in the plan; they get stricter review later (`review-and-models.md`).

## 3. Plan review
- [ ] ONE review round plus ONE revision (`codex-review`, or one opus reviewer if Codex is unavailable; `expert-panel` when product trade-offs dominate). A second round only if the first returned blocking findings. No "until APPROVED" loops. Why: review rounds that crept into handoffs tripled the weekly agent count.
- [ ] The owner approves the reviewed plan. Unanswered product questions go in one batch (`templates/owner-batch.md`).

## 4. Prototype / design
- [ ] If the product has a UI and no design source: a throwaway `prototype` for flow/state questions, or a design session producing a canvas. Decide with the owner which one; a canvas is the structure/copy source during the sprint (`design-interplay.md`), a code prototype is thrown away.
- [ ] Keep the design session alive into the sprint only if it will own the canvas and the delta doc.

## 5. Readiness gate (coord checks before bootstrap)
- [ ] Every section of `templates/sprint-plan.md` is filled, or explicitly marked "none".
- [ ] No lane depends on an unanswered owner question for its first slice.
- [ ] Test and CI commands are known (they go into the project config).
- [ ] The first real-user milestone has a date, and a dress rehearsal is scheduled before it (`quality-and-rehearsal.md`).
Then `bootstrap.md`.

## Traps
- A plan written without data ownership → every slice re-litigates who may write a table. Fill the ownership table before any lane starts.
- Treating a design doc's description as the built state → assignments for work that already landed. Before assigning from any doc, check git.
- Porting review/planning procedures into this skill → two versions that drift. Call the owning skill; keep here only when and how it plugs in.
