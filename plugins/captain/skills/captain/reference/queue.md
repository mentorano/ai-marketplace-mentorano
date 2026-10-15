# queue - run state, the queue, decisions, TODO, the end report

## Contents

- [R19 IDs](#r19-ids)
- [run.md](#runmd)
- [queue.md (R10)](#queuemd-r10)
- [Dev targets (Scope, R10)](#dev-targets-scope-r10)
- [Owner `!` commands (R16)](#owner--commands-r16)
- [Memory step (R17, PK2-PK4) - only with `Project memory: on`](#memory-step-r17-pk2-pk4---only-with-project-memory-on)
- [decisions.md (R9, R18)](#decisionsmd-r9-r18)
- [TODO entry (R18)](#todo-entry-r18)
- [TODO entry for a deferred finding (R6, R18)](#todo-entry-for-a-deferred-finding-r6-r18)
- [Status, park and end reports - `Remaining:` (R12)](#status-park-and-end-reports---remaining-r12)
- [End report (R17) - in the user's language, in this order, every item with its ID](#end-report-r17---in-the-users-language-in-this-order-every-item-with-its-id)
- [runs.jsonl (R17)](#runsjsonl-r17)

All run state lives in `./tmp/captain/<YYYYMMDD-HHMMSS>/` in the repository.
The main session writes these files with `Write` (R1).

## R19 IDs

Two capital letters plus a number on every item shown to the owner and every TODO
entry the run writes. The letters name the area; items in one area count up;
an item keeps its ID in later messages and later runs. Before choosing
letters, read the IDs already in the TODO file and continue an area's letters
from its highest number. Answer options get their own IDs (`OP1`, `OP2`),
unique within the reply. Review findings may keep `F1`, `F2`.

Example area letters (this table is an example; the run never edits this file):

| ID | Area |
|---|---|
| `VR` | time box |
| `GR` | scope boundary |
| `PR` | pull request |
| `KN` | consensus |
| `OP` | answer options |
| `AR` | architecture / technical decisions |
| `ZD` | tasks of the plan split (`run.md` `## Tasks`) |

A new area: pick two letters from the area's name; record them in `run.md` under
`## IDs`, and the TODO entries the agent writes carry them into the project for later runs.

## run.md

```markdown
# captain run <YYYYMMDD-HHMMSS>
- Repo: <abs path>   Start branch: <branch>   Default branch: <name>
- Feature branch: captain/<YYYYMMDD>-<slug>, based on <origin/<default> | <owner's branch>, chosen OP2> | none: auto base (R2)
- Mode: present | away   Box: <N> min (<given | chosen: reason>)
- Start: <HH:MM>   Park: <HH:MM>   Deadline: <HH:MM>
- Uncommitted changes at start: <none | list, untouched>
- Checkout mode (R2): shared | shared-multi | worktree — <one-line reason>
- Run checkout: <abs run worktree .claude/worktrees/captain-run-<run-id>, every mode | the session's own checkout, auto base>   Writers: <the run worktree | per-writer worktrees>
- Base branch (R10): <branch, recorded by the guard (typed | auto: base: <branch> — <reason>), checkout <abs> | none: feature branch only>
- Base SHA (bootstrap): <sha>   Last pushed SHA (feature branch): <sha | none>
- Config: read | setup done | missing, away (notify none, tools from `command -v`)
- Tools: codex on/off, agy on/off   Notify: <method> | none
- Codex: available | off in config | usage limit, resets at <time>
- Experiment (R20): on | off   Agent types: plugin | fallback (no duel)
- mode: fix-all | normal — <one-line reason> (ZD1, start step 6; present: shown with the plan)
- Dev targets: <IDs confirmed for this repo | none>   Other repos named by the owner: <list | none>
- Project memory (PK6): on (<abs memory.py path>) | off: <reason>

## Timers
| Timer | Kind | Id |
|---|---|---|
| health | cron / sleep | <id> |
| park | cron / sleep | <id> |
| deadline | cron / sleep | <id> |

## Reviews (R5 push gate)
| Commits (base..head) | Files | Reviewer | Result |
|---|---|---|---|
| <sha>..<sha> | <files> | Codex / Opus | passed / passed (no FIX NOW, whole loop range) / changes / open |

## Tasks
| ID | Task | Agent | State |
|---|---|---|---|
| ZD1 | <one line> | w-auth | todo / queued / running / review k/3 / merged / cut |
| ZD2 | <one line> · KL 6/6 · duel: yes — <reason> | duel A/B/C | running |

The plan-split start step writes the plan here; every event updates the row. An owner request
that arrives while its writer is busy gets a new row with state `queued` (R6). Status (R12) is
read from
this table, not from the chat scrollback.

A coding task carries its light test and, with `Experiment: on`, its duel line
(`reference/experiment.md`).

## Duels
| Task | Letter | Agent | Worktree / branch | Codex session | State |
|---|---|---|---|---|---|
| ZD2 | A | captain:light-coder | duel-<run-id>-ZD2-A | - | review 1/3 / not finished: <reason> / winner / lost |

The letter mapping lives only here; no prompt names it.

## Agents
| Name | agentId | Task id (TaskStop) | Task | Checkout (abs) | Model | Limit | Period start | Minutes | output_file | notified | Context |
|---|---|---|---|---|---|---|---|---|---|---|---|
| w-auth | <id> | <id> | <one line> | <abs> | opus | 15m | 14:05 | 12 | <path> | no | 9% keep |

On every resume by `SendMessage`: new period start and limit, `notified: no`. On every
completion notification: add the minutes from period start to `date` to `Minutes` (the
duel record's `minutes`, R20).

## IDs
| Letters | Area |
|---|---|

## Processes
| PID | Start time | Working dir | Agent |
|---|---|---|---|

## Memory candidates
| ID | Candidate | From | Verdict |
|---|---|---|---|
| MK1 | `<abs draft path>` — <why, verbatim> | w-auth ZD1 | open / accept → `<topic>.md` (new / edit / merged with MK3) / reject: <one-line reason> / not written: no time / not written: dirty .agent-memory |
```

`## Memory candidates` exists only with `Project memory: on`; `off` → no section, no memory
step, today's `runs.jsonl` record.

## queue.md (R10)

What goes here: push or merge to `main`/`master`, any force push; deleting branches, tags or
worktrees the run did not create; deleting or largely rewriting files outside the task scope;
history rewrites over others' commits (rebase, `reset --hard`); applying a migration or
changing data on a shared or cloud DB; any external write (GitHub issues and comments, cloud,
deploy, publish, `gh repo create`, CI settings, secrets or runners). Local edits of
`.github/workflows/*` are code and stay in scope. One line per action; the command is ready
to run.

```markdown
# Queue for the owner
- GR1 | merge feature branch into <default> | `git -C <repo> merge --no-ff captain/<...>` | why: task done, reviewed
- GR2 | stopped at an external system: apply migration on staging DB | `<command>` | why: shared DB
```

A listed dev target is not queued (below); a write to another repository is queued unless the
owner named that repository for this run.

Also here: actions denied by a permission rule in away mode (R16). The merge into the
owner-confirmed base branch is not queued: main runs it in the merge flow below.

Never a pull request: not opened, not queued, not proposed in the end report, unless the owner
asked for one. The way into the default branch is the merge line above.
**Why:** the owner, 02.10.2026: "we stop making PRs … a PR only if the person asked for it".

## Dev targets (Scope, R10)

A dev target is one command or script the owner allows against a dev or test environment, for
example a site deploy script for a shared dev instance. Two sources:

- `~/.claude/captain/config.json` key `dev_targets` (written by `captain-setup`):
  `{"<repo key>":[{"id":"DTS1","command":"<exact command or script path>","target":"<endpoint, account or project it must hit>","confirmed":"YYYY-MM-DD"}]}`.
  The repo key is `<owner>/<repo>` from `git remote get-url origin` (no scheme, user, host or
  `.git`, so SSH and HTTPS clones match); no origin → the absolute git common dir.
- The repo's own `CLAUDE.md`, a `captain` section listing the same fields. Such an entry counts
  only after the owner confirms it once: present mode → at start the captain runs the
  `captain:captain-setup` skill section 5 with that entry; its one question is the
  confirmation, and on yes it adds the entry with `confirmed`. Away mode → not listed. A
  changed `command` or `target` is a new entry and needs a new confirmation.

Rules:

- Only a listed target, and only after the R5 review gate for the code it deploys.
- Before it runs, the agent checks the real endpoint, account or project the command will use
  (the config file, the CLI's current account or project) against `target`. A mismatch, or a
  check it cannot make → it does not run; the item goes to the queue.
- A temporary probe (a config value changed for a test) is reverted by the same agent, and the
  revert is checked and reported with evidence. "Reverted by the run" does not apply to a
  deploy itself.
- Out, to the queue: everything not listed, production, `terraform apply` and shared infra,
  shared DBs, and every write to another repository (issues, PRs, comments, pushes) unless the
  owner names that repository for this run.

The agent prompt names the target ID, its command and its `target` in the frame's external
systems line (`reference/prompts.md`).
**Why:** 13.10.2026: deploys were out of scope, so the owner ran dev deploys, dev push scripts and
a config `sed` by hand; the same run closed an issue in another team's production repository,
which it must never touch.

## The merge flow (R1, R10)

Main runs the merges itself; an agent's merge is denied by the auto-mode classifier too often.
Trigger: when a loop ends clean (no FIX NOW), main merges the agent branch in the same turn,
without asking. `<abs checkout>` is the run worktree from `run.md` `Run checkout`, in every R2
mode, worktree mode too.

1. A reviewed agent branch into the feature branch: main runs
   `git -C '<abs checkout>' merge --no-ff --no-edit '<agent-branch>'`, one command per Bash call (the
   canonical forms: `reference/tools.md`; the guard denies a `-m` message form). In shared modes
   the agent's commits are already on the feature branch: nothing to merge. With an auto base
   (R2) there is no feature branch: the agent branch merges straight into the base in the run
   checkout, and the R5 push gate pushes the base (step 3). Else the feature branch then goes
   into the owner-confirmed base branch (R10; never `main`, `master` or the default
   branch), without asking: `git -C '<abs base checkout>' merge --no-ff --no-edit '<feature-branch>'`, in
   the checkout where that branch is checked out, and only when a runner reported
   `git -C '<abs base checkout>' status --porcelain` empty there. The captain never stashes;
   dirty → the merge waits and the status line says so. Checked out nowhere → a runner adds
   `.claude/worktrees/captain-base-<run-id>` for it. `hooks/guard.py` checks the HEAD in this
   order: detached → denied; the granted branch → allowed; `main`, `master` or the origin
   default (with no readable `origin/HEAD`, every branch outside `captain/*`) → denied; a
   `captain/*` HEAD or the recorded base (a typed `/captain base <branch>`, or the auto base,
   `reference/prompts.md`) → allowed;
   anything else → denied (`reference/tools.md`).
2. A conflict → main does not resolve it. A `captain:worker` gets the conflict prompt
   (`reference/prompts.md`): it resolves the listed files, stages them by path and does not
   commit. Then main runs `git -C '<abs checkout of that merge>' commit --no-edit`. A resolution that needs a
   product choice → `git merge --abort` and the question goes to the owner.
3. The full test suite on the merged head, and the push of the feature branch, go to an agent
   (R5 push gate), as before. A runner runs the tests on the merged head first. The push of a
   base branch: the agent checks the upstream with `git -C '<abs base checkout>' branch -vv`,
   then pushes an explicit refspec, `git push <remote> <sha>:refs/heads/<branch>`. Agents never
   push a base branch that is `main`, `master` or the default branch.
4. Sync with the remote (R1), without asking: a `captain:runner` runs
   `git -C '<abs repo>' fetch origin`; main merges `origin/<default>` into the working branch
   in its checkout, `git -C '<abs checkout>' merge --no-ff --no-edit origin/<default>` or
   `git -C '<abs checkout>' merge --ff-only origin/<default>`. When: before a push, and after a
   push rejected with "fetch first". A conflict → step 2, with a new `captain:worker` and the
   conflict prompt. The push to the remote `main` stays with `/captain merge` (step 5). Into a
   protected HEAD opened by the grant (even one named `captain/*`), the guard takes only the
   `--ff-only` form; into a `captain/*` or base HEAD both forms, with or without the grant. A push of the base
   branch rejected because the remote base itself moved (`origin/<base>` has commits the local
   base lacks) is not fixed by this sync: the guard covers only `origin/<default>`, not a merge
   of `origin/<base>`, so main does not run one. A `captain:runner` reports
   `git -C '<abs base checkout>' log --oneline '<base>..origin/<base>'`, and the merge of
   `origin/<base>` goes to the queue (R10) for the owner's yes. Never a force push.
5. Into `main`/`master`/the default branch (R10): ask the owner once, with a recommendation, to
   type exactly `/captain merge <branch>`. Only that typed prompt grants it; a Skill call made by
   the model does not. For the rest of the run main may then run `git switch <branch>`,
   `git merge --no-ff <feature-branch>` and `git push <remote> <branch>` for that branch, in the
   repository where the owner typed it, one per Bash call. Before the push, a runner reports
   `git remote -v` and the branch tracking (a fork: the owner's branch is not always `main`).
   The grant ends at `/captain off`, a new `/captain` start, a new `/captain merge`, the skill
   call `captain end` right before the end report (R17), or 12 hours after it was typed; a
   handoff successor (R21) takes it over with its `/captain resume` (same repository and
   working directory). Ask again only
   after one of these.

A guard denial caused by the command FORM (a chain, a `-m` message, a `-C` with `~` or an
unknown working directory, a source other than a local branch or `origin/<default>`) or the
checkout STATE (a detached HEAD, an unprotected HEAD that is not `captain/*` or the recorded base, no merge in
progress, `origin/<default>` not fetched) is fixed once in the canonical
form from `reference/tools.md` and retried. A second FORM/STATE denial stops that operation,
never as an owner question: a `captain:runner` reports the exact denial text, the HEAD and the
form used; the operation waits in `run.md` with that diagnosis and the status line says so.
Only a protected-branch denial (`main`, `master` or the default branch without the grant;
with no readable `origin/HEAD`, any branch outside `captain/*`, the base too), a
push or switch denial (no grant, or a remote with a push mapping, mirror or `push.followTags`)
and a classifier denial are final (R16): give the owner the `!` commands.
**Why:** 02.10.2026: the classifier denied the integration agent's reviewed merge, the guard
denied main's own `git merge`, and the owner ran it by hand 38 min later ("why don't you merge them
yourself?"); in 5 of 8 sessions of 01–02.10 the owner merged or pushed reviewed work with `!`; 05.10.2026,
two real runs: `/captain merge main` typed 10 times, 6 pushes rejected (fetch first), 3 `-m`
form denials, 12+ manual `!` commands.

## Owner `!` commands (R16)

The owner's approval in the main chat does not reach an agent: an agent treats a forwarded
approval as the coordinator's words, and the auto-mode classifier denied a merge even with
the approval quoted. So an action that needs the owner and main may not run itself, or any
action denied finally (a classifier, protected-branch, push or switch denial, the merge flow
above), goes to the owner at once as `!` commands. Never send it to an agent
again, with or without the approval quoted.

- All steps in one message, numbered with an R19 ID and "step k of n", each command alone in
  its own code block, with nothing else on its line: the owner copies it as is.
- Each command states the output it expects (e.g. `Merge made by the 'ort' strategy.` and
  the changed files; `* [new branch] HEAD -> <branch>`; `<old>..<new>  main -> main`).
- The owner runs them in order and stops at the first output that differs. Compare each
  output with the expectation; a mismatch or an error → say what differs, and give only the
  command that fixes it plus the steps not yet run.
- No `&&` chain over several steps: one failure hides which later steps did not run.
- A step an agent must run between them (the full test suite on the merged head) splits the
  block: the commands after it come in the next message, after the agent's result.

Shell rules for every command handed to the owner:

- `!` is the first character of the line: no leading space, no indent.
- Absolute paths; no `cd`; no `&&` chained to a destructive command.
- No placeholders: the command is ready to paste as is.
- `git worktree unlock` only for an item that `cleanup-run.py` reported as locked.
- One command per block when its output decides the next step; the expected output under
  each block.
- `rm`, `cp` and `mv` get the alias-safe prefix (`command rm`, `command cp`, `command mv`)
  when the config has `"shell":{"command_prefix":true}` or no `shell` key; `false` → the bare
  command. Some shells alias them to a prompting form.

Worktree cleanup as `!` commands follows the same shape, one git command per step, only for
items `cleanup-run.py` reported (`reference/health.md`, worktree cleanup).

**Why:** 30.09.2026: the classifier denied the merge of a reviewed branch twice ("Merge Without
Review"), the second time with the owner's approval and the review log path forwarded
verbatim; earlier merges of that run passed. The one-by-one `!` commands then went through in
six steps, and the one chained cleanup command failed at its first step. 01.10.2026: the owner
ran six one-by-one merge commands in 40 s, so the steps now come as one block; 02.10.2026: the
owner pasted a command with the captain's prose after it ("not something we can merge").
09.–13.10.2026: two handed-over `rm` commands stopped on an alias prompt, and one `!` with a
leading space did not run.

## Memory step (R17, PK2-PK4) - only with `Project memory: on`

On receipt: a report with `Memory candidate: <abs draft path> — <why>` lines gets one row per
draft in `## Memory candidates`, verdict `open`, in the same `run.md` edit as its `## Tasks`
row; main does not read the draft yet. Letters `MK` under `## IDs`.

When: after the last merge into the feature branch (shared mode: the last writer's commit) and
before the R17 agent that updates TODO and docs and pushes. Present and away mode alike: no
queue entry and no owner question. The step never pushes park or the deadline: fewer than 10
minutes to the deadline → skip it, a runner `restore`s any written but uncommitted file, and
the kept rows get `not written: no time`.

0. ZP0 Clean check. Main runs `git -C '<abs run checkout>' status --porcelain --ignored
   --untracked-files=all -- .agent-memory` (`--ignored`: an ignored local file counts too). Any output → the memory step is skipped for the
   whole run: every open row gets `not written: dirty .agent-memory`, the drafts stay in the
   run directory; no write, no `restore`, no commit. So `restore` and `commit` only ever touch
   main's own changes.
1. MSH1 Review. Main reads every open draft and the `name` and `description` of each
   `.agent-memory/*.md`. Keep a draft only when it (a) cost a cycle, or would have cost the
   next session one (a trap found before it bit counts), or (b) contradicted an assumption,
   AND it is true next month. Reject with the named class: session summary, restated code,
   one-off task fact, already in CLAUDE.md / CONTRIBUTING / README, machine path or secret,
   fact about the user, unverified guess, already in a memory file, `duplicate of MK<n>` (its
   source goes into the kept row's `From`). Every reject has a one-line reason in the row.
   Prefer editing an existing file; drafts on one topic may be merged into one file.
2. MSH2 Write. Main writes each file itself with `Write` (new) or `Edit` (existing) at
   `<abs run checkout>/.agent-memory/<topic>.md`: `name` = stem, one-line `description`
   ≤ 160 characters saying *when*, `paths` when file-specific (DL1, PT1).
3. MSH3 Revalidate. One `captain:worker` (Opus), single pass, gets the memory revalidation
   prompt (`reference/prompts.md`) and answers `keep`, `fix: <change>` or `drop: <reason>` per
   file; it writes nothing. Main applies it: `fix` → `Edit`; `drop` → a runner's `restore` of
   that file, and the row gets `reject: revalidation: <reason>`. This pass is the R5 review of
   the memory commit: `## Reviews` records `Opus revalidation (MP1) | passed`.
   No kept row after MSH1 → no write, no revalidation, no commit, no `## Reviews` row.
4. MSH4 Commit, only when a file is left after MSH3 (all dropped → no commit, never
   `--files=''`). A `captain:runner` gets the memory commit prompt (`reference/prompts.md`). Exit
   1 → main fixes the file with `Edit`, the runner reruns `commit`. Main sets every row's
   verdict.

Nothing about memory goes into the end report, status or `Remaining:`; main shows the memory
commit (`git show <sha>`) only when the owner asks.
**Why:** a memory file is read as a rule by every later session, so it gets an independent
check before the commit; writing after the merges keeps lessons from work that landed. The
owner (MP1, MP2): memory is written in both modes without asking, one Opus pass instead of a
review loop.

## decisions.md (R9, R18)

```markdown
- KN1 | tier: full | away: product | <question> | options: A <...> / B <...> / C <...>
  | votes: Codex A, agy B, Fable A, Opus A | result: A (majority | no consensus) | reason: <...>
- AR1 | tier: mini | <decision> | reason: <...> | rejected: <...> | second opinion: Codex agree
- VR2 | scope cut | <subtask> → TODO.md | reason: <...>
- ZD1 r2 F6 | ACCEPT artificial timing | <file:line> — <problem, one line>
- ZD1 r3 F2 | TODO owner decision → <TODO ID> | <file:line> — <problem, one line>
```

Review register (R6): one line per ACCEPT or TODO finding, `<task ID> r<k> F<n> | <class>
<reason> | <file:line> — <problem>`. From round 2 the review prompt carries these lines
verbatim. Refuted findings and nits live only here (`reference/triage.md`). In a duel (R20)
the key carries the contestant letter, `<task ID>/<letter> r<k> F<n>` (e.g. `ZD2/A r1 F1`),
and each contestant's review prompt carries only its own letter's lines.

## TODO entry (R18)

The repo's existing TODO file (root `TODO.md` first, else `docs/plans/TODO.md`;
one file only); none → create `TODO.md` in the root.

```markdown
- **<ID>** <what> — deferred: <reason, one line: does not fit the <N>-min box | needs the owner | needs production | ...> (<date>).
  Resume: <files>, branch `<branch>`, spec <section>. Open findings: <F-list or none>.
```

## TODO entry for a deferred finding (R6, R18)

Same file and IDs as above. Tests deferred in round 2+ make one entry for the loop, not one
per finding. ACCEPT never goes to TODO; it is a register line in `decisions.md`.

```markdown
- **<ID>** <what, one line> — deferred from review <task ID> r<k> F<n> (<date>), kind: <behaviour | owner decision | hardening | tests>.
  Now: <current behaviour, one sentence>. Risk: <when it hits: normal use (steps) | artificial timing only>.
  Options: <A / B> or Fix idea: <one line>. Evidence: <review log path>. Resume: <files>, branch `<branch>`.
```

**After park (R5/R18 exception):** only a change to the TODO file itself may be committed
and pushed without review, and the report marks it "pushed unreviewed"; it never pushes
through an unreviewed commit (R5 push gate). Code and other docs
changes made after park are committed on their branch but not pushed or merged.

## Status, park and end reports - `Remaining:` (R12)

A status report (the owner asked), the park report and the end report end with two parts.

1. `Remaining:` — built from run state, never from memory: open rows of `run.md` `## Tasks`,
   `queue.md` items, TODO entries added in this run, commits held back (R17), and cleanup
   items that were skipped. One line each, with its ID. `Nothing remains.` only when all five
   are empty.
2. The last line says what happens next: `Continuing with <ID>.` (only when that action starts
   in the same turn), `Waiting for you on <ID>.`, or at the end of the box
   `Stopping; captain mode stays on.`

The R13 health line is not a report: one line, no `Remaining:`.
**Why:** 15 sessions, 09–13.10.2026: the owner asked "status?" 8 times and "what is left / are
we done" 7 times.

**Notify (R12).** `~/.claude/captain/notify.sh "<message>"`: present mode for a waiting
question and the end report; away mode for the end report only. If it fails, the message stays
in the chat.

## End report (R17) - in the user's language, in this order, every item with its ID

Items blocked on the owner come first. The TODO count line, `TODO: added <n>, closed <m>`,
names added first; when added > 0 it is the report's first line, with each new entry and its
one-line reason under it (`reference/triage.md`, `fix-all`); else it goes into item 6.

1. The queue: ready commands, one per line; the owner says yes per item and runs each
   approved one as a `!` command, in order (owner `!` commands, above).
2. The permissions added to `.claude/settings.local.json` in R15, with the
   proposal to remove them (main writes that after the owner's yes).
3. Subtasks cut to fit the box, and the TODO file they went to.
4. External-system parts that were stopped.
5. Decisions: away mode all; present mode the consensus ones.
6. Short report: done (with evidence: log path + result line, sha) / not done / review
   findings rejected, each with its reason; branches and worktrees the run created; how late
   any timer fired; a TODO-only change pushed unreviewed after park, if any; a missing
   config in away mode (nothing created, notify none, tools from `command -v`); the
   `audit-main.py` exit code if it was run.
7. Duels (R20), when any ran: one line per duel with its ID, the winner (letter and agent)
   or `none`, and the judge's reason; branches, worktrees, logs and Codex session ids that
   stayed (`reference/experiment.md`, cleanup by outcome).
8. `Remaining:` and the last line (above).

After the report, one `~/.claude/captain/notify.sh "<one-line summary>"` call (R12), in both
modes; the wrapper decides whether the owner is away.
**Why:** 02.10.2026: a run ended while the owner was away for 3 h 40 min; the captain never
called the wrapper, so no ping went out.

## runs.jsonl (R17)

The coordinator composes the record and writes it with `Write` to the run state file
`./tmp/captain/<run>/runs-line.json` (valid JSON, so quotes, apostrophes, backslashes and
newlines are escaped by construction). The cleanup agent parses it and appends it
re-serialized as exactly one line with its own newline, the path passed as a quoted argument:

```bash
mkdir -p ~/.claude/captain && python3 -c 'import json, sys, os
record = json.load(open(sys.argv[1]))
with open(os.path.expanduser("~/.claude/captain/runs.jsonl"), "a") as out:
    out.write(json.dumps(record, ensure_ascii=False) + "\n")' '<abs run dir>/runs-line.json'
```

```json
{"date": "2026-09-26", "repo": "<name>", "task": "<one line>", "box_min": 30, "box_reason": "given", "actual_min": 32, "outcome": "partly", "cut": ["VR3"], "review_rounds": 2, "codex_available": true}
```

Duels add one line each to `~/.claude/captain/experiments.jsonl` with the same append
snippet; record format: `reference/experiment.md`.

A run with `Project memory: on` adds `"memory": {"candidates": <n>, "written": ["<topic>.md"]}`; an `off` run writes the record above unchanged.

`outcome` is `done`, `partly` (with the cut items that went to TODO) or `overrun`. `cut`
lists the R19 IDs of the cut items; `[]` when nothing was cut.
