# prompts - templates

## Contents

- [Agent frame (R3) - every agent prompt](#agent-frame-r3---every-agent-prompt)
- [Bootstrap prompt (`captain:runner`) - add the R3 frame](#bootstrap-prompt-captainrunner---add-the-r3-frame)
- [Memory commit prompt (`captain:runner`) - add the R3 frame](#memory-commit-prompt-captainrunner---add-the-r3-frame)
- [Memory revalidation prompt (R5) - one `captain:worker`, single pass](#memory-revalidation-prompt-r5---one-captainworker-single-pass)
- [Verification prompt (R6) - separate `captain:worker` agent, real local data](#verification-prompt-r6---separate-captainworker-agent-real-local-data)
- [Review prompt (R6, R7) - Codex and the Opus fallback](#review-prompt-r6-r7---codex-and-the-opus-fallback)
- [Revalidation message (R6) - by SendMessage to the writer's agentId](#revalidation-message-r6---by-sendmessage-to-the-writers-agentid)
- [Fix list message (R6) - after main applies the round threshold](#fix-list-message-r6---after-main-applies-the-round-threshold)
- [Merge conflict prompt (R1) - to a `captain:worker`, add the R3 frame](#merge-conflict-prompt-r1---to-a-captainworker-add-the-r3-frame)
- [Group test prompt (TS1) - to a `captain:runner`](#group-test-prompt-ts1---to-a-captainrunner)
- [Hand-off prompt (R6) - a fresh writer replaces one at 30% context](#hand-off-prompt-r6---a-fresh-writer-replaces-one-at-30-context)
- [Mini-consensus prompt (R9) - Codex (medium), else Fable, else `captain:worker`](#mini-consensus-prompt-r9---codex-medium-else-fable-else-captainworker)
- [Full consensus prompt (R9) - 3amigos `task.md` for a captain decision](#full-consensus-prompt-r9---3amigos-taskmd-for-a-captain-decision)
- [Panel runner prompt (R9) - to the `captain:runner` of a 3amigos panel](#panel-runner-prompt-r9---to-the-captainrunner-of-a-3amigos-panel)

Fill every `<...>`. Keep the wording of the fixed lines; the rules rely on it. Quote every
path in a command with single quotes (`'<abs path>'`).

Every `record-created.py` call passes `--agent='<agent name>'`: the agent's `Name` in
`run.md` `## Agents` (the bootstrap agent: `bootstrap`; a group test runner: its row name).
Main adds that row when it launches the agent (`reference/health.md`, Agent lifecycle).

## Agent frame (R3) - every agent prompt

```text
<Task, one paragraph: what to build or check.>
<code writer while the spec loop runs (R5):> The approved spec changes listed at the end of
this prompt are authoritative where the spec file differs; a spec writer applies them in
parallel.
Done means: <a verifiable finish line, e.g. "commit on <branch>; the group runner runs the tests">.
Stop and report early only if: <task-specific blocker>, or the work reaches an external system
other than a dev target listed under Scope below.
<light coders only (captain:light-coder, R4):> If you need a file outside the owned list, or a
design decision the task did not make, stop: do not commit, and make report item 1
"ESCALATE: <reason>", with your uncommitted files and your last commit (or the base SHA).
Do not launch subagents or invoke review skills.

Hard time limit: finish within <N> minutes. If you cannot, commit what works on your branch
and report what is left.
<with a box (R11):> Park time (absolute): <HH:MM>. Hard end (absolute): <HH:MM>.
Main may send you a later park time and hard end; the latest message wins.
<no box:> The run has no park time or hard end; only your own time limit above applies.

Scope:
- Checkout mode (R2): <shared | shared-multi | worktree>. Checkout: '<abs checkout>'.
  Never write on main/master, in any mode; never switch the owner's main checkout.
  shared, shared-multi: work in the run worktree '<abs checkout>' on feature branch
  '<feature-branch>'; the bootstrap agent created it and every agent of the run shares it.
  Commit only the files you own, by path, on that branch. Writers report the base SHA (the
  feature-branch HEAD when they started) and the head SHA of their last commit.
  Writers, every mode (TS1): run no tests, no build, no compile check; the group's runner
  runs them after the group's last merge.
  shared-multi, writers also: other writers work in this checkout now. Do not touch shared
  generated files (lockfiles, migrations, snapshots).
  worktree, first step (writers only):
  git -C '<abs repo>' worktree add '<abs repo>/.claude/worktrees/<name>' -b '<agent-branch>' '<feature-branch>'
  If it fails on a locked .git/config (another agent is adding a worktree), wait 5 s and
  retry; if '<agent-branch>' already exists by then, retry without -b:
  git -C '<abs repo>' worktree add '<abs repo>/.claude/worktrees/<name>' '<agent-branch>'
  Then record it for the run's cleanup (never write created.jsonl by hand):
  python3 '<skill root>/scripts/record-created.py' --run-dir='<abs run dir>' --worktree='<abs repo>/.claude/worktrees/<name>' --agent='<agent name>'
  Tools do not move into the checkout: use absolute paths under '<abs checkout>' for every
  edit, and run every command there (cd '<abs checkout>' && ... or git -C '<abs checkout>' ...),
  including tests and the paths you give a reviewer.
- Files you own: <list>. Do not touch: <list>, and anything outside scope.
  <a file shared with a parallel task (PL1):> You share <file> with <task ID>; change only
  <its Touches entry>, and leave the rest of that file as it is. A change you need outside it
  → report it, do not make it.
  <the spec is the contract (PL2):> Other tasks build against the names, signatures, flags
  and formats the spec fixes; keep them exactly. Need a change to one → stop and report.
- External systems are out of scope: no deploy, cloud, shared DB, GitHub issues/comments,
  publish, pull request, and no write to another repository. If the task reaches one, stop
  that part and report it. <only with a listed dev target, R10:> Exception: dev target
  <ID> `<command>` against `<target>`, after the review gate; check the real endpoint, account
  or project first, revert any probe yourself and check the revert (`reference/queue.md`).

House rules:
- Prefix standard shell commands with `command` (command ls, command grep ...).
- POSIX `head -n N` / `tail -n N`.
- Log every build/test/script run to ./tmp/claude-logs/<name>-$(date +%Y%m%d-%H%M%S).log,
  then read the log; never pipe a build straight into tail.
- Self-review your code before you run any script on it.
- A new test file is also added to the repo's test runner script (e.g. `run-tests.sh`), if
  the repo has one that names test files.
- Stage only the files you own, by path. Never `git add -A` or `git add .`.
- Stop every long-running process you started before you report. List any you leave
  running with PID, start time and working directory.
- When a step needs no decision from the coordinator, keep going. Do not end with a next
  step you could take yourself, an offer to continue, or non-blocking choices.
- Decisions (R9): a choice visible outside a file or hard to undo gets a mini-consensus
  before you execute it (Codex, else a Fable agent, else a captain:worker agent — if you cannot
  launch an agent, ask main for that opinion — skipping tools the
  config marks off; with a park time, recompute
  the time to park before each; none left → defer it); list each decision with reason and rejected
  alternatives.
- Mark anything you could not confirm or check, and say where you looked.
- Your final message carries the evidence itself (output lines, log path, sha), never a
  placeholder or "see above".
- A needed secret (API key, token): check the process environment (`printenv <NAME>`; report
  only set or unset, never the value) and the repo's env files before you report it missing.
- An artifact that exists: read it first and publish with its `url`; a new file path creates a
  second page.
- Owner constraints from the kickoff, verbatim: <e.g. "the tests one after another"; the repo's
  canonical test command with its env variables; or "none">.

Approvals: <e.g. "commit on <agent-branch> allowed; push to feature branch <x> allowed;
NO merge or push to main/master; no force push">. An action the owner asked for (a cleanup
with unlock, a delete) is listed here with the owner's words verbatim, in the first prompt.

Messages: send one message, when done or blocked; never routine progress. Send at once only
for: blocked, ESCALATE, a permission denial, a data risk, a time limit reached. Review rounds
(triage and fix reports) are not progress messages.
Report in the owner's language (software terms in English), at most 8 lines, numbered, in this order
(review, mini-consensus and full-consensus prompts and the revalidation message replace this
report section with their own exact output contract, below); detail (full logs, long lists, per-file notes) goes to
'<abs run dir>/reports/<agent name>-<task ID>.md', and the report names that path:
1. blocked on the coordinator / open questions;
2. done, each item with evidence (log path + result line, commit sha);
3. not done; 4. files changed; 5. commits (sha); 6. processes left running;
7. decisions; 8. not confirmed (and where you looked).
<only with "Project memory: on" in run.md (PK6):> Project memory: never create, edit or
delete anything under `.agent-memory/` or `.claude/rules/project-memory/`; main decides what
goes there. When you learned something that meets the write trigger in
`.agent-memory/README.md`, write it as a draft memory file, one per topic, to
'<abs run dir>/memory-drafts/<agent name>-<task ID>-<n>.md' (n = 1, 2, ...), in the format
of a memory file: frontmatter `name` (the topic file name you propose, without `.md`),
`description` (one line, at most 160 characters, when to read it), `paths` (YAML list of
globs) when the rule is file-specific; then the rule text, under ~8 KB. After item 8 add one
line per draft: `Memory candidate: <abs draft path> — <one line why>`; these lines do not
count toward the 8 lines. No such lesson → no draft, no line.
```

The `Project memory` paragraph goes into every prompt with this report section (writers, fix
rounds, runners), never into bootstrap; with `Project memory: off` main leaves it out and the
frame is today's. Main finds the lines by the `Memory candidate:` prefix (`reference/queue.md`,
memory step).
**Why (project memory):** the project-memory design lets only the main session write
`.agent-memory/`; a lesson a worker paid for was lost at the end of the run.
**Why (messages, 8 lines):** 15 sessions, 09–13.10.2026: 466 agent messages and 43 health
checks filled the context; the owner asked for a handover because "this one overflowed". Main
reads only these reports and `run.md`, never an agent's detail file unless a decision needs it.
**Why (test runner line):** 30.09.2026: the integration agent found that `run-tests.sh` did not
run a new test file; the writer needed one more task and one more review for it.
**Why (evidence, secret, artifact, constraints, approvals):** 01–02.10.2026: a runner handed
back "placeholder" twice; an agent stopped twice on a key the owner had exported in the shell;
a publish from a new path made a second page; a runner ran the suites in parallel against
"one after another" and without the test DB variable; an agent refused a cleanup the owner had
asked for, because its first prompt forbade the unlock, and the consent had to be relayed.

**Spec first (R5).** A run that starts from a new spec, or from one no review loop has passed,
makes the spec's Codex review loop (R6) its first task. Code writers start after round 1;
their prompt carries the round-1 approved change list, one line per change, with the
"authoritative" line above. A later spec round that changes a writer's part goes to that
writer as a correction of the task in progress (R6).
**Why:** 30.09.2026: the owner asked "we will review the spec, right?"; the code writers
started after spec round 1 and the spec loop ended (r3 approve) while they worked.

## Auto base (R2 exception, start step 5)

Before bootstrap, main compares the name of the session's current branch with the task (the
prompt, the handover, the spec). Clear match → `base: <branch> — <one-line reason>` in
`run.md`, then the Skill call `captain` with args `base <branch>`. `hooks/guard.py` records the
base only while these hold at that moment: AB1 HEAD is that named branch, not `main`, `master`,
the origin default or detached; AB2 `git fetch origin <default>` succeeds; AB3 HEAD is the
fetched tip (no commits of its own); AB4 origin has no `<branch>`, or has it on the same SHA;
AB5 it is not checked out in another worktree; AB6 the tree is clean (untracked run state under
`tmp/captain/` and an untracked `.claude/settings.local.json` aside). Only the hook's line ``captain guard: base `<branch>` recorded`` in the
context counts; any other result, also no line at all (no plugin hook, a hook timeout), means
not recorded. Use the args form `base <branch>`: `base=<branch>` is a start argument and
begins a new run. Recorded → one line to the owner,
`Base branch: <branch> (automatic: a new branch on top of origin/<default>, <reason>)`, and bootstrap
gets `auto base <branch>`. Not recorded, or a match main is not sure of →
present: one question with a recommendation (the base question below); away: the normal
bootstrap with a new `captain/*` branch. With an auto base the run works on the base: no
`captain/*` feature branch; the run checkout is the session's own checkout; writer worktrees
branch off the base; reviewed merges land in it; the R5 push gate pushes it.

## Bootstrap prompt (`captain:runner`) - add the R3 frame

```text
Prepare '<abs repo>' for a captain run. Do not switch, stash or stage anything in the main
checkout, and do not touch uncommitted changes.
1. Report: current branch, `git -C '<abs repo>' status -s`.
2. git -C '<abs repo>' fetch origin. Default branch = the output of
   git -C '<abs repo>' symbolic-ref --short refs/remotes/origin/HEAD without `origin/`;
   if that fails: main if `git -C '<abs repo>' rev-parse --verify --quiet origin/main`
   succeeds, else master if the same check on origin/master succeeds; neither → stop here
   and report the blocker "no origin/HEAD, origin/main or origin/master; base unknown".
   Count `git -C '<abs repo>' rev-list --count 'origin/<default>..HEAD'`. Count above 0 (any
   current branch, a local default branch ahead of origin included) → present mode: stop
   here and report the branch and count (the coordinator asks the owner); away mode: go on
   with origin/<default>, report it.
3. With `auto base <branch>` (R2): skip steps 3 and 5; the base SHA is
   `git -C '<abs repo>' rev-parse HEAD` and the run checkout is '<abs repo>'. Else create the
   feature branch from the chosen base (default: origin/<default>) without checking it out:
   git -C '<abs repo>' branch --no-track 'captain/<YYYYMMDD>-<slug>' '<base>'
   Report the base SHA: `git -C '<abs repo>' rev-parse 'captain/<YYYYMMDD>-<slug>'`.
4. For each of tmp/ and .claude/worktrees/: if git -C '<abs repo>' check-ignore -q '<path>'
   fails, append the path to the file named by
   git -C '<abs repo>' rev-parse --git-path info/exclude (never the literal
   .git/info/exclude; in a linked worktree .git is a file).
5. In every R2 mode (shared, shared-multi and worktree): create the one run worktree for the
   feature branch (no -b, the branch exists; on a locked .git/config wait 5 s and retry). Main
   runs every merge of the run there, so worktree mode needs it too:
   git -C '<abs repo>' worktree add '<abs repo>/.claude/worktrees/captain-run-<run-id>' 'captain/<YYYYMMDD>-<slug>'
   (<run-id> is the run's unique ID, `<YYYYMMDD-HHMMSS>`, the name of its run-state directory.)
   Then record it for the run's cleanup (never write created.jsonl by hand):
   python3 '<skill root>/scripts/record-created.py' --run-dir='<abs repo>/tmp/captain/<run-id>' --worktree='<abs repo>/.claude/worktrees/captain-run-<run-id>' --agent='bootstrap'
6. Report `git -C '<abs repo>' remote -v`, `git -C '<abs repo>' branch -vv` for the current
   branch, and the captain versions in the plugin cache: `command ls ~/.claude/plugins/cache/*/captain/`.
7. Report the base-branch candidates (R10): the start branch when it is not main, master or
   the default branch, and the local branches from
   git -C '<abs repo>' for-each-ref --sort=-committerdate --count=5 --format='%(refname:short)' refs/heads
   that are not main, master, the default branch or captain/*; for each, the checkout where it
   is checked out (`git -C '<abs repo>' worktree list`), or none.
8. python3 '<skill root>/scripts/memory-apply.py' detect --checkout='<abs run checkout>'
   Report its one line verbatim.
Report in the owner's language: branch, uncommitted changes (full list), default branch, base of the
feature branch and its base SHA, feature branch, excludes added, run worktree path (every
mode) and its RECORDED line, remotes and tracking, captain versions in the cache, base-branch
candidates, the step 8 line.
```

Main copies the step 8 line into `run.md` (`Project memory (PK6): ...`).

After the report: uncommitted changes in present mode → one `AskUserQuestion` to the owner before
any code agent starts (they are never touched either way); in away mode → note them in
`run.md` and the end report. Bootstrap stopped at step 2 (the owner's branch has commits not in
`origin/<default>`) → present mode: one `AskUserQuestion` with an R19 ID — `OP1` base on
`origin/<default>` (recommended) or `OP2` base on that branch — then `SendMessage` the bootstrap
agent to go on with that base. Away mode: base on the default branch; `run.md` and the end
report note the skipped branch. Worktree-mode agent branches start from the feature branch.

Base branch (R10), present mode, only when no base is recorded yet (an auto base above skips
this paragraph): once bootstrap has reported the branch and the base candidates, one
`AskUserQuestion`, header exactly `Base branch`, one option per candidate,
each labelled `base: <branch>`, the recommended one first. It is only a question: no hook
records its answer. After the answer the captain asks the owner to type
`/captain base <branch>` (or `/captain 1h base=<branch>` at the start); only that typed command
(or the auto base above) is what `hooks/guard.py` records, for this repository. The typed `/captain base <branch>` is the
verified path; if the guard did not record the base, the captain asks the owner to type it.
The guard never records `main`, `master` or the origin default as the base, nor any branch
outside `captain/*` while `origin/HEAD` is unreadable; until a base is recorded, a merge into an
unprotected branch is denied as a checkout-state problem. With no readable `origin/HEAD` every
branch outside `captain/*` is protected: a merge into the base gets the protected-HEAD denial,
typing `/captain base` again does not help, and it goes to the owner (R16). No candidate → no
question; the run merges only into the feature branch. Away mode: no question; without a typed
or auto base the run merges only into the feature branch. `run.md` records the base branch.

## Memory commit prompt (`captain:runner`) - add the R3 frame

Only with `Project memory: on`, at the memory step (`reference/queue.md`). In the R3 frame the
`Project memory` paragraph's first sentence becomes: "Your only commands on `.agent-memory/`
are the `memory-apply.py` command below; you write no memory text." The draft rule stays.

```text
Check and commit the project-memory files main wrote. Run, logged to
./tmp/claude-logs/memory-apply-<timestamp>.log:
python3 '<skill root>/scripts/memory-apply.py' commit --checkout='<abs run checkout>' \
  --branch='<feature branch | auto base branch>' --memory-py='<abs memory.py>' \
  --files='<topic>.md[,<topic>.md...]' \
  --message='docs(memory): <add|update> <topic>.md[, ...] (<MK IDs>)'
Report the exit code, the `new`/`edit`, `violation`, `untouched` and `health` lines and the
commit SHA. Exit 1 → report the lines; do not edit or create memory files yourself.
<a `drop`, or no time only:> python3 '<skill root>/scripts/memory-apply.py' restore \
  --checkout='<abs run checkout>' --files='<topic>.md[,<topic>.md...]'
```

**Why:** main writes memory itself (the project-memory rule: only the main session writes);
commits and scripts stay agent work (DL2), and the script checks with the plugin's own rules.

## Memory revalidation prompt (R5) - one `captain:worker`, single pass

Only with `Project memory: on`, after main wrote the accepted files and before the commit. It
replaces the report section with its own output contract and carries no draft paragraph.

```text
Revalidate the project-memory files main just wrote in '<abs run checkout>/.agent-memory/':
<topic>.md (<new | edit>, from MK<n>), ... Read each file, its diff (git -C '<abs run
checkout>' diff -- .agent-memory; a new file: the file), the other `.agent-memory/*.md` and
'<abs run checkout>/.agent-memory/README.md'. Check each file: every claim is true against
the repo now (open the code, run read-only commands); it meets the README write trigger and
none of its "Never" classes; it neither duplicates nor contradicts another memory file,
CLAUDE.md or the README; the format (`name` = file stem, one-line `description` of at most
160 characters saying when to read it, `paths` when file-specific, under ~8 KB). Do not edit
any file; you write nothing. Reply in English, one line per file, then nothing else:
<topic>.md | keep / fix <what> / drop <why>
```

**Why:** memory is read as a rule by every later session, so a wrong line costs more than a
wrong TODO; one independent Opus pass checks it without a review loop (owner, MP1).

## Verification prompt (R6) - separate `captain:worker` agent, real local data

For work with a path through hardware or real data (local copies or a local test DB; a shared
DB is external): right after the round-1 fixes, in parallel with review round 2, a separate
agent that did not write the code runs it on that data. A failure is FIX NOW in every round
(`reference/triage.md`). Threshold calibration goes to TODO or to the owner with measurements.

```text
Verify <what> on the real local data at '<path or test DB>' in '<abs checkout>'.
Done means: <expected result on the data, e.g. counts, sample rows, no errors>, logged.
Do not change code; report differences with evidence (log path, result lines).
For each difference: the user steps that show it, and the measured values.
```

## Review prompt (R6, R7) - Codex and the Opus fallback

```text
Review <the spec at '<path>' | the changes on branch <agent-branch> vs <feature-branch>
in '<abs checkout>' (R2 worktree) | the commits <base-sha>..<head-sha> in '<abs checkout>',
only the writer's files: git diff <base-sha>..<head-sha> -- <files> (R2 shared modes)>
for correctness bugs, missed requirements and risky changes.
Do not browse the web; review only against the repo code.
Scope: <files / commit range>. Requirements: <spec section or task text>.
<R2 worktree, the work uses files of a sibling branch:> Files from sibling branches, not on
this branch: <path — branch, reviewed, merged into <feature-branch> in <sha> | reviewed, not
merged yet>. They are not in this checkout; read them with git show '<branch>:<path>'. Do not
report them as missing.
Read-only: do not edit files (an Opus reviewer writes only its output file, next line).
<Opus reviewer only:> Write the output below to '<abs run dir>/reviews/<task ID>-r<k>.md' and
hand back only the Verdict line, the finding count and that path.
<round 1:> Report every finding. Label each blocking or non-blocking.
<round 2+:> Scope: the fix commits <range>; code outside the diff stays visible, because a fix
can break an unchanged line. First check that FIX NOW findings <F-list> are closed.
Report as blocking only: a defect reachable in normal use (list the user steps), data loss in
normal use (list the user steps), a security boundary, or a broken build or test. A scenario
that needs an artificially held promise, injected timing or a tampered local store is
non-blocking; still say if it loses data. List every non-blocking finding in one line under
"Non-blocking:".
Settled findings, do not re-raise without "NEW EVIDENCE:" and the evidence:
<register lines from decisions.md, or "none">

Output exactly:
Verdict: approve | changes
Findings:
F1. <blocking|non-blocking> <severity high|medium|low> <file:line> — <problem> — <how to show it fails: test, input or command> — <normal use: user steps | artificial: how> — <origin: change | round-k fix Fn | pre-existing> — <suggested fix>
F2. ...
Non-blocking: <round 2+ only: F-ids with a few words each, or "none">
Round 1: every finding under Findings, no Non-blocking line. Round 2+: only blocking findings
under Findings; each non-blocking one only in the Non-blocking line, not in both.
No findings → "Verdict: approve" and "Findings: none".
```

On a timeout retry, repeat the no-web line at the top as well.

Sibling files: fill the sibling line above. A merge of the sibling into the feature branch
alone does not help: the writer's checkout still lacks the files, and a two-dot diff against
the new feature head shows them as deleted.
**Why:** 30.09.2026: the review of the skill-text branch reported the script from the sibling
script branch as missing (F1, F2: "missing", `--total` not supported): two false findings.

## Revalidation message (R6) - by SendMessage to the writer's agentId

The reviewer's runner reports the verdict line, the finding count and the path of the
review's final message (for Codex the `-o` file, `reference/tools.md`; an Opus reviewer writes
its output to '<abs run dir>/reviews/<task ID>-r<k>.md' and reports that path); main passes
the writer that path, never the findings text.

```text
Review findings <F-list> for your work (reviewer: <Codex|Opus fallback>, round <k>/3) are in
'<abs path of the review's final message>'; read the whole file (F1..., the "Non-blocking:" line).
Do not edit or commit yet. Revalidate each finding against the source first, then write one
triage block per finding to '<abs run dir>/reviews/<task ID>-r<k>-triage.md', in this shape
(reference/triage.md):
F<n> | reachable: normal use (steps: ...) | artificial (how) | not shown
     | origin: change | round-<k> fix F<m> | pre-existing
     | impact: data loss | security | build/test broken | wrong result | degraded | none
     | mechanism: <lock, timeout, marker, counter, queue or threshold | none>
     | proposed: FIX NOW | ACCEPT <reason> | TODO <kind> | evidence: <test, input or file:line>
A finding you cannot show with an input, a failing test or a code path is ACCEPT not
confirmed. The reviewer's severity is input: judge reachability in normal use yourself.
In round 2+ propose no new mechanism (state, timeout, counter, protocol field, new server
check; a type or shape check on an existing input field is allowed). Priority: data loss in
normal use (with steps) > a verifier failure > the trap > the round table. The trap: a
mechanism with findings in an earlier round of this loop → return MECHANISM: <name>, what the
code does now, and 2-3 options, instead of a fix. A fix that needs a new mechanism → the same
MECHANISM report.
Report in the owner's language, at most 8 lines: the triage file path, then one entry per finding,
several per line: `F<n> <normal|artificial|not shown>/<impact>/<mechanism or ->/<origin> →
<class>`; a MECHANISM report adds its name and options in one line each.
```

## Fix list message (R6) - after main applies the round threshold

```text
Fix now, round <k>/3: <F-list>. Start at once; report once, when the fixes are committed; do
not answer this message with a report first. Keep each fix minimal. Commit on your branch, do not push or
merge. In the commit body, list each real risk accepted on purpose under "Accepted risks:",
one line each: - <loop> r<k> F<n> <risk> (in <sha of the commit that holds the risk>),
including risks accepted in earlier rounds that had no fix commit. Report in the owner's language with
the finding IDs and evidence per fix.
Classed ACCEPT or TODO (no change): <F-list with class and reason>.
```

**Why (start at once):** 01.10.2026: a writer answered each fix list with a report and stopped;
the list went out four times.

## Merge conflict prompt (R1) - to a `captain:worker`, add the R3 frame

```text
Main merged '<agent-branch>' into '<target branch>' in '<abs checkout>' and git stopped on
conflicts in: <files>. The merge is in progress. The checkout exists: drop the frame's
`worktree add` step; work only in '<abs checkout>'; do not run git merge, commit, reset,
checkout or stash. Resolve each file so both sides' intent holds (<agent-branch>: <one line
of its task>; <target branch>: <one line>). Run no tests: the group's runner runs them (TS1).
Stage only the resolved files, by path (git -C '<abs checkout>' add -- '<file>'). Do not
commit: main concludes with git commit --no-edit. A conflict that needs a product choice →
stage nothing and report it as item 1, with the two options.
```

Empty FIX NOW list → no message; the loop stops (`reference/triage.md`). Accepted risks of
that round wait for the next commit of the task, else the R17 TODO/docs commit.

## Group test prompt (TS1) - to a `captain:runner`

After the group's last merge (`reference/parallel.md`, the group flow), with the R3 frame.

```text
Run the tests of group <group> on the merged head <sha>. Do not edit, commit, merge or push
anything, and do not run in '<abs checkout>': first
git -C '<abs repo>' worktree add '<abs repo>/.claude/worktrees/group-<run-id>-<group>-<n>' -b 'group-<run-id>-<group>-<n>' '<sha>'
python3 '<skill root>/scripts/record-created.py' --run-dir='<abs run dir>' --worktree='<abs repo>/.claude/worktrees/group-<run-id>-<group>-<n>' --agent='<agent name>'
and run everything in that clean worktree. Leave it there: the run's cleanup removes it (its
branch sits on a merged SHA).
Command: <the group's test command from run.md ## Groups, with its env variables>.
Log: ./tmp/claude-logs/group-<group>-$(date +%Y%m%d-%H%M%S).log, full output; then read the log.
Shared resource: <test DB / port / container / none>; another group run may hold it: <yes, wait
for it | no>.
Report: 1. pass or fail, with the summary line and counts; 2. each failing test, with its
error line; 3. the files each failing test touches, mapped to the group's merge range
<base>..<sha> (`git -C '<abs checkout>' log --name-only <base>..<sha>`), as a hint of the task
(<ZDn: files> per task); 4. the log path.
```

**Why:** the owner's answer OP2, 20.10.2026: writers run nothing; one runner per group runs the
tests once, after the group's review and fixes.

## Hand-off prompt (R6) - a fresh writer replaces one at 30% context

Put this before the R3 frame of the fresh writer; the frame keeps the old writer's checkout,
branch and files. In `worktree` mode, drop the frame's `worktree add` step: the fresh writer
works in the old writer's existing worktree, on its agent branch.

```text
You take over from a writer whose context got full. Its work is committed on
'<the old writer's branch: agent branch (worktree mode) or feature branch (shared modes)>'
in '<abs checkout>'; head <sha>. The checkout exists: do not create a worktree or a branch.
Read only what your task needs.
What the branch does so far, in <= 10 lines: <summary from the old writer's reports>.
Settled decisions you must keep (decisions.md IDs): <list or "none">.
Your task: <the next queued task, or the path of the review findings, their F-IDs and round <k>/3>.
```

The extra writer for a trapped mechanism in a `fix-all` run (`reference/triage.md`) gets this
block too, plus:

```text
Mechanism <name> is in the trap: <what the code does now; the fixes tried so far, one line each>.
New hypothesis to test first: <one or two lines: what the earlier fixes assumed, and the
different cause to try>. This is the last writer for this mechanism; the loop's re-review
count does not reset (round <k>/3).
```

After an `ESCALATE` of a light coder (R4 MR3), add to the block:

```text
The previous writer stopped with ESCALATE: <reason>.
Uncommitted files: <list or "none">; last commit <sha or "base <sha>">.
Decide the escalated point, record it (R9), then finish the task.
```

## Mini-consensus prompt (R9) - Codex (medium), else Fable, else `captain:worker`

```text
Second opinion on technical decisions made in <repo>, task <one line>.
Do not browse the web.
For each decision: the decision, the reason, the rejected alternatives.
D1. <decision> - reason: <...> - rejected: <A: why>, <B: why>
D2. ...
Relevant code (inline): <excerpts>
Output exactly one line per decision:
D<n>: AGREE — <reason, one sentence>
D<n>: DISAGREE — <reason, one sentence>
```

## Full consensus prompt (R9) - 3amigos `task.md` for a captain decision

Written by main into `tmp/captain/<run>/amigos-<ID>/task.md`; `data.md` beside it holds each
decision with its context, constraints and lettered options, inline. Every voter gets this
text: Codex through `panel.py`, the Opus and Fable voters and any Fable stand-in.

```text
You are one of three independent experts voting on technical decisions in <repo>,
task <one line>. Do not browse the web. Read only task.md and data.md in <dir>; never list
or read any other file there.
DATA lists <N> decisions, each with its context, constraints (time box, scope,
reversibility) and lettered options.
For EACH decision pick exactly one option letter. Prefer the safer, more reversible option
when two are close. You have <budget> minutes.
Return ONLY valid JSON, no markdown:
{"items":[{"id":"<decision ID>","verdict":"<option letter>","reason":"one sentence"}]}
items must contain exactly <N> entries. <Agents:> Write it to <dir>/<opus|fable|fableN>.json.
```

Fallback without 3amigos (`reference/consensus.md`), same text to every voter:

```text
Decision needed in <repo>: <question, one paragraph with context>.
Do not browse the web.
Constraints: <time box, scope, reversibility>.
Options:
A. <option>
B. <option>
Relevant code or spec: <file paths to read, or excerpts inline>
You have <budget> minutes. Output exactly one line:
Vote: <option letter> — <reason, one sentence>
```

## Panel runner prompt (R9) - to the `captain:runner` of a 3amigos panel

```text
Run the Codex voter and the tally of a 3amigos panel; do not vote yourself. Read only what
the scripts print, <dir>/data.md and <dir>/tally.json, never a voter's answer file. Panel dir: <dir>. Skill dir: <skill dir>.
Park deadline (absolute): <HH:MM | none: no box>. Decisions: <N>.
1. Unless the config tools mark codex false or it hit its usage limit in this run:
   python3 '<skill dir>/scripts/panel.py' --task '<dir>/task.md' --input '<dir>/data.md'
   --out '<dir>' --voters codex --effort high --deadline <min(300, park - 5 min) in s; 300 with no box>
   --require items=<N>
2. When main sends the agent answer files, run panel.py --check on each with
   --require items=<N>.
3. Tally only the files whose status line said "ok", listed explicitly, never a glob:
   python3 '<skill dir>/scripts/tally.py' --list items --id id --fields verdict --voters 3 <files>
   No "ok" file at all → skip the tally; every decision is "no consensus".
4. Check every decision ID listed in data.md: an ID absent from tally.json, or a winning
   letter that is not one of that decision's options in data.md, is "no consensus".
Report in at most 8 lines plus one line per decision: each status line in short; per
decision ID from data.md the winning letter, the kind (agree, majority) or "no consensus"
(split, insufficient, no valid vote, unknown letter), and one reason of a winning voter;
the missing voters.
```
