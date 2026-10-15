# Design / prototype session (optional)

A peer session that produces UI structure, states and copy. Not a lane: it writes no product code
and messages coord, not lanes. Its session name and paths are in the config. It starts with `/coord design` if it uses the skill (never `/coord`, which would make it a second coordinator).

## One source per kind of question (write it in the config)
| Question | Source |
|---|---|
| Structure, components, class names, visuals | the approved design canvas/spec |
| Exact copy (target language) | the per-screen design spec; none yet -> ask coord; ship as draft |
| Flow and business rules | product/flow documents + the amendments doc |
| Demoted older artifacts | last resort only; never their transitions or class names; say so in LANDED |
No lane should ever guess which document answers what. Never copy code from a prototype.

## Rules
- The canvas never becomes a clickable prototype; the running product in local dev mode is the only clickable reference. Why: two "looks like the product" references drift.
- The canvas binds work started after it was approved; earlier screens are reconciled in a dedicated pass, screen by screen, each lane on its own screens, once the end-to-end path works - never mid-sprint.
- A lane needing a shared component name before the owning lane lands it defines it locally under the agreed name and tells coord, who reconciles.
- Copy/behaviour shipped with no spec is marked with the config's **draft marker** and named in LANDED, so the reconciliation pass finds it by search.
- Strings/behaviours invented mid-sprint get the config's **return-to-design marker** (e.g. "new — return to the canvas"), so the design source catches up.
- Design text contradicting an accepted backend/data design: escalate to coord; decide case by case (often the design description is corrected).

## Delta document
- The design session keeps a delta doc: design vs built, row per screen/element, with the commit it was checked against.
- It is not state: check `git log` before assigning from it (a row "open" had merged 40 minutes earlier).
- Decisions the design session relays from the owner are confirmed with the owner before being recorded.
- When its context goes stale, the design session writes a proper handoff (flagging its own earlier wrong claims) instead of rebuilding the delta from memory.
- Under `automation: cmux`, when coord asks the design session to hand off, the request says: write the kickoff, send coord "handoff at <path>; kickoff ready", do NOT ask the owner for /clear; coord restarts it (`cmux-automation.md`). A session without the skill does not know this rule unless the request carries it.
