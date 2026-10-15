# Resume a sprint (start of every coord session)

## With a config
1. [ ] Kickoff: if none was injected (a fresh session), read `~/.claude/kickoffs/<your session name>.md` if present and move it to `kickoff-used/`. Then read `<repo>/.coord/project.md` fully.
2. [ ] Read the newest coord handoff in the config's handoff dir - it is self-contained. Open an earlier file only when the newest one points to a section for detail, or when it is an old-style handoff that still names a chain (then read the chain once and make your own handoff self-contained). Nothing in them is status.
3. [ ] Confirm identity: if your kickoff says you are the successor, you ARE coord now. If the old coord session may still be alive under the same name, ask the owner to confirm the name swap (`handoff-and-sessions.md` §Name swap).
4. [ ] Re-derive state: `<skill dir>/scripts/derive-state.sh <repo> --fetch` (first-parent log, branches ahead, worktrees, CI, migration heads, containers). Plus `git status` in the primary checkout: a staged merge means your predecessor left one mid-flight - finish or abort it deliberately, never commit over it.
5. [ ] **In-flight work first, before any action.** `derive-state.sh` flags `!! LOCAL … AHEAD` (merges committed but not pushed) and `!! RUNNING in checkout` (test processes). `!! process scan unavailable` means the process check could not run (e.g. a sandbox denies the process list): treat it as unknown, not as "nothing running", and check from an unsandboxed shell. Background shells survive `/clear`, so a running verification may be your OWN predecessor's (trace `ps -o ppid=` up to the claude process; another session showing busy in ListAgents is not evidence that the process is theirs). Its result is not in your context: stop it and verify the unpushed batch yourself before pushing. Never push a batch you did not verify.
6. [ ] Measure the lanes: `<skill dir>/scripts/measure-context.py <repo> 24` - who is alive, who is near the ceiling.
7. [ ] Read the board (`ArtifactData list tasks` + `get meta/state`); reconcile against git: landed rows vs actual merges. Board = reported, not verified.
8. [ ] Re-check every "expected КАЦНА" / "open thread" from the handoff against git before acting on it.
9. [ ] A scope with a deadline in the plan: reconcile its timers (`scope-deadline.md` §Resume); an armed away timer likewise (`CronList`: keep, re-create or delete, never twice).
10. [ ] Propose to the owner which lanes to wake, with reasoning: critical path first; a lane with nothing unblocked stays asleep. Include any open owner questions (batched).
11. [ ] Go to `operate.md`.

## No config (old project, or one run without this method)
1. [ ] Look for existing handoffs (`docs/**/handoffs/`, `.superpowers/handoffs/`), plans, worktrees (`git worktree list`), branch prefixes (`git branch -r`), a board URL in memory.
2. [ ] If lanes already exist (worktrees + prefixes): reconstruct the lane table from them, draft `.coord/project.md` from `templates/project-config.md`, mark every guessed field `(unverified)`, and send it to the owner for approval.
3. [ ] If not: run `bootstrap.md` from step 1.

## Traps
- Trusting "expected КАЦНА X" from a handoff: X may have merged or been withdrawn. Git first.
- A handoff's citations (`file:line`) rot within hours; re-grep.
- Waking every lane "to check in" - each wake is a full-context turn. Wake only lanes with unblocked work.
