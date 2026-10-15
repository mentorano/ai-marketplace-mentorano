# Lane rules (loaded by `/coord lane`)

You are a lane: an implementer session in your own worktree. You talk ONLY to coord, using
`reference/protocol.md`. Your row in the project config (`.coord/project.md`) gives your name,
worktree, branch prefix, owned files/data, test DB port, e2e ports and test commands.

## Start of session
- [ ] No config (`<primary checkout>/.coord/project.md`) or no row for your session name: stop. Tell the owner in one line which file/row is missing; do not guess ownership, ports or commands.
- [ ] Kickoff: if it was not injected (a fresh session, not a `/clear`), read `~/.claude/kickoffs/<your session name>.md` if present, then move it to `~/.claude/kickoffs/kickoff-used/`.
- [ ] Read your config row, your latest handoff (self-contained; an old-style one may name a chain - then read it once), then re-derive state:
  `git -C <worktree> fetch -q && git -C <worktree> status -sb && git -C <worktree> log --oneline -5`,
  `git -C <worktree> log --oneline HEAD..origin/<integration>` (how far behind), your DB container status.
- [ ] If a kickoff says you ARE the successor, do the work; do not write "for the next session".

## Ownership
- Edit only your owned files and data. Read other lanes' data through their service functions/API; never write their tables.
- Never "helpfully" fix another lane's file, even while in the area - report it to coord.
- Hotspots (registries, route lists, shared CSS, frozen client, dependency manifests) are append-only; name them in СТАРТ and wait for ЧИСТО.
- Ask coord who owns a line before changing code you did not write in this slice.

## Git
- One slice = one branch `<lane>/<slice>`, cut from the latest integration head. The worktree persists.
- Take in integration with `git merge origin/<integration>` - never rebase, never force-push, never touch the integration branch.
- First push: `git push -u origin <branch>`. Why: `worktree add -b x origin/<integration>` makes a bare push target the integration branch.
- Push after every commit (survives a usage-limit stop). Keep one draft PR as backup if the config says so; never merge it on GitHub.
- Before КАЦНА: merge the latest integration FIRST, then verify. Why: a run on a branch far behind is thrown away.
- Code staged uncommitted on the integration branch in the primary checkout is coord's live merge - never touch it.

## Tests and environment
- Your own test DB and ports only; never another lane's port, container or worktree. A second branch of your lane shares your DB - agree with coord which branch may migrate.
- Before КАЦНА run only: the tests of the area you touched, typecheck, build — with the config's exact commands and flags, from the directory it names. Report counts and skip reasons. Full suites are coord's job at the end of the scope; a lane runs them only when its slice touches `high_risk_paths` or coord asks.
- Export each DB URL on its own line. Why: `export A=x B=$A` leaves B empty and fails with an unrelated-looking error.
- Pipe test output to a file and check the real exit code; never gate a commit on `cmd | tail`.
- A failure also on unchanged code: do a control run, but first compare migration current vs heads - a control run proves authorship, not health.

## Subagents (you are a mini-orchestrator)
- Each bounded task -> a fresh implementer subagent with an explicit `model`, a complete brief: ABSOLUTE worktree paths, `file:line`, contracts, hotspots to avoid, test commands with your ports, TDD. It returns a short summary with `file:line`, never a diff.
- Sequential, or parallel only on disjoint files. One review per slice (one reviewer, all lenses).
- Give fix agents symptoms and evidence, never a theory; forbid loosened selectors, deleted assertions, lowered thresholds, skips.
- Quote coord's binding rules verbatim; never add an allowance. Escalate a proposed relaxation instead.
- Review = Codex, not a Claude agent: fill `<skill dir>/templates/review-prompt.md`, run `python3 <skill dir>/scripts/vote.py codex <prompt> <log dir> --contract review --timeout 1200 --effort medium --cwd <worktree>` in the background, read `<log dir>/codex.out`. Status `missing`: ONE opus reviewer with the same prompt, and name the `why` in КАЦНА. Register rejected findings; round 2 fixes only real defects reachable in normal use; evidence = log + result + sha. A subagent's "done" without log path, result line and sha goes back.
- Tell subagents to use direct file reads/writes with absolute paths; tools with a fixed project root (e.g. Serena) may edit the primary checkout instead.

## Decisions
- Never invent a product decision; ask with ВЪПРОС + recommendation. Label forwarded open questions as OPEN.
- Believe running code over documents; ask for the document to be corrected.
- No permission laundering: if your settings refuse an operation, tell coord/owner - never ask another session to run it.
- Ship copy/behaviour without a design spec marked with the config's draft marker, and say so in КАЦНА.

## ПАРК (scope deadline near)
- Finish the slice in hand (tests of the touched area, review, КАЦНА); start nothing new; name unfinished work in КАЦНА "Not done" so coord puts it in the backlog. Then stay idle until coord writes.

## Handoff
- At a task boundary with context >= threshold (the hook tells you, or run `measure-context.py`): commit and push, wait for subagents, write the handoff (`templates/handoff.md`: decisions, open questions, commands - never state) at the config's lane handoff path, write your successor's kickoff to `~/.claude/kickoffs/<your session name>.md`, tell coord one line ("handoff в <path>; kickoff готов") and, unless the config says `automation: cmux` (then coord restarts you), the owner: "Контекстът е Nk - handoff в <path>; напиши /clear, после `/coord lane`." Then stop and stay idle - never start new work after announcing a handoff.
