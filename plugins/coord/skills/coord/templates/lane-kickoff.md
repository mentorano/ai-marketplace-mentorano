You ARE `<prefix>-<lane>`, lane `<CODE>` of the <project> sprint - do the work, do not write "for the
next session". Invoke `/coord lane <prefix>-<lane>` (loads only the lane rules and protocol).

- Worktree: `<root>/<lane>` (absolute paths everywhere, also in subagent briefs).
- Your row in `<repo>/.coord/project.md`: owned files/data, DB port <port>, e2e ports <api>/<web>, commands.
- Read: <newest lane handoff> (self-contained). Nothing in it is status.
- Re-derive: `git -C <root>/<lane> fetch -q && git -C <root>/<lane> status -sb && git -C <root>/<lane> log --oneline HEAD..origin/<integration> | wc -l`; DB: `<migration current cmd>` vs heads.
- Start with: <slice id and name>. Send START to `<prefix>-coord` before the first edit.
- Binding rules for this slice (verbatim from coord): <quote or "none beyond lane rules">.
- Open questions you do NOT decide: <list, each labelled OPEN with its owner>.
