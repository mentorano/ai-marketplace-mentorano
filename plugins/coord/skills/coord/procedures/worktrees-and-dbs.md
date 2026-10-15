# Worktrees, test DBs, ports

## 1. Layout
- One persistent worktree per lane under the config's worktree root (`<root>/<lane>`); branches change inside it. Extra worktrees for a second concurrent branch: `<root>/<lane>-<slice>`.
- Coord uses the primary checkout on the integration branch.
- Kickoffs, lane handoffs and scratch live outside git: kickoffs in `~/.claude/kickoffs/`; lane handoffs at the config's lane handoff path (default `<worktree>/.superpowers/handoffs/`); scratch in `<worktree>/.superpowers/`, excluded via `.git/info/exclude`. Coord handoffs are the exception: in git, at the config's handoff path. Never in a system temp dir or a session scratchpad (they vanish).

## 2. Create a lane worktree
```sh
git -C <repo> fetch -q
git -C <repo> worktree add --no-track -b <lane>/<slice> <root>/<lane> origin/<integration>
git -C <root>/<lane> push -u origin <lane>/<slice>
```
- [ ] `--no-track` or `push -u`. Why: `-b x origin/<integration>` sets the integration branch as upstream; a bare push then targets it.
- [ ] Install dependencies per the config. If a shared registry config (`.npmrc`, pip index) points at a private/expiring endpoint the lockfile does not need, override on the command line; never edit the shared config file.

## 3. Test DB per lane
- [ ] One port and one compose project name per lane (e.g. `<prefix>-<lane>`), fixed in the config. e2e API/web ports per lane too.
- [ ] One idempotent script keyed by `<lane> <port>`: up (wait), migrate, provision restricted roles, print the export line. Safe to re-run.
- [ ] A lane's DB is lane-scoped, not branch-scoped: a second branch of the lane shares it. Decide which branch may migrate, or give it its own port.
- [ ] Export DB URLs each on its own line; copy the script's printed line.

## 4. Verify
- [ ] Migration current == heads (config's command). If not, rebuild.

## Rebuild (the only real one)
```sh
<compose cmd> -p <project> down -v   # drops volumes
<db script> <lane> <port>            # up + migrate + roles
```
- The script alone only migrates a RUNNING container; stale rows/roles survive.
- A stopped container restarted with plain `compose up` comes back EMPTY; hundreds of "relation does not exist" follow. Use the script.
- After ANY change to a migration's parent, rebuild; `upgrade head` in place is a silent no-op.
- After e2e, rebuild before pytest-style suites; e2e leaves rows.

## Where a session starts
- Open each lane session WITH its worktree as the working directory (`cd <worktree> && claude`). Why: a lane opened in the primary checkout runs its tests, installs and tools there - observed as lane pytest runs inside the primary checkout while coord was verifying a batch.

## Subagents in worktrees
- Always ABSOLUTE worktree paths in briefs; the shell cwd resets to the primary checkout between calls and same-named files exist in both at different versions.
- Tools bound to a project root (e.g. Serena) may edit the primary checkout; use direct absolute-path edits and check the test count moved.

## Cleanup (owner approval)
Removing a worktree, dropping a DB volume that holds anything but synthetic data, deleting remote branches: ask first. `git worktree prune` for already-removed temp worktrees is fine.
