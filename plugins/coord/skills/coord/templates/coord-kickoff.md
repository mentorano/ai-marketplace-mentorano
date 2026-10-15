You ARE `<prefix>-coord`, the coordinator of the <project> parallel sprint - the successor of the
previous coord session, not a helper writing for a later one. Invoke `/coord` (skill `coord`).

1. Read `<repo>/.coord/project.md`.
2. Read <newest handoff> - it is self-contained; earlier handoffs only where it points to them. Nothing in it is status.
3. Re-derive state: `<skill dir>/scripts/derive-state.sh <repo> --fetch`, `<skill dir>/scripts/measure-context.py <repo> 24`, `git -C <repo> status` (a staged merge?), the board.
4. Start with: <the first concrete action, e.g. "the КАЦНА queue: verify each against git, then batch">.
5. Open owner questions to carry: <ids or "see handoff §3">.

Name swap: <"the owner has renamed the old session to <prefix>-coord-old" / "none">.
