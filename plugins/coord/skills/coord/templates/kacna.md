LANDED | <lane>/<slice> @ <sha> | <one-line what it delivers, self-contained>

- Base: merged `origin/<integration>` @ <sha> (merge, not rebase); `git merge-base --is-ancestor` true.
- Files/areas: <paths or globs>; hotspots touched: <list or none>.
- Contract changes: <added/changed types, endpoints, enums, fields - consumers: <lanes>> or none.
- Migration: <id>, chained onto head <exact id>; round-trip done | none.
- Checks (exact commands, flags, counts):
  - touched area: `<cmd>` from <dir> -> <N passed, M skipped (reasons)>
  - typecheck + build: `<cmd>` -> ok
  - full suites: only if `high_risk_paths` touched -> <counts> | not run (not high-risk)
- Review: <model/Codex>, range `<base sha>..<sha>`, <findings fixed / rejected (register) / none blocking>. No commits after the reviewed sha except LANDED-only docs.
- Not done / deferred: <items, backlog ids> | none.
- Drift: <draft-marker items, return-to-design items, known env-only failures (control run done)> | none.
- OPEN questions (not decided here): <question - owner> | none.
- Try it: 1) ... 2) ... 3) ...
