You ARE `<prefix>-<lane>`, lane `<CODE>` of the <project> sprint - do the work, do not write "for the
next session". Invoke `/coord lane <prefix>-<lane>` (loads only the lane rules and protocol).

- Worktree: `<root>/<lane>` (absolute paths everywhere, also in subagent briefs).
- Your row in `<repo>/.coord/project.md`: owned files/data, DB port <port>, e2e ports <api>/<web>, commands.
- Read: <newest lane handoff> (self-contained). Nothing in it is status.
- Re-derive: `git -C <root>/<lane> fetch -q && git -C <root>/<lane> status -sb && git -C <root>/<lane> log --oneline HEAD..origin/<integration> | wc -l`; DB: `<migration current cmd>` vs heads.
- Start with: <slice id and name>. Send START to `<prefix>-coord` before the first edit.
- Binding rules for this slice (verbatim from coord): <quote or "none beyond lane rules">.
- Open questions you do NOT decide: <list, each labelled OPEN with its owner>.

Successor tab only (delete otherwise): you were started in a new tab by `<FROM>`, which is still alive. The handshake line above this kickoff ("do not wait for an answer", "go on") means: read and re-derive at once; it does not lift this rule: no edit and no START until `ACK <your name>` arrives from `<FROM>` (owner instructions in it bind like this kickoff). Then send coord `NAME <FROM> -> <your name>`. On `STAND-DOWN <your name>`: stop all work, send nothing, stay idle. If `<FROM>` is not reachable, tell the owner in one line and wait for their word before any write.
