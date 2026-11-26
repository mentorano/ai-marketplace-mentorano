# tools - the R1 allow-list and verified CLI invocations

## Contents

- [Main-session allow-list (R1)](#main-session-allow-list-r1)
- [Agent types (R4)](#agent-types-r4)
- [Tools availability (R7, R8, R9)](#tools-availability-r7-r8-r9)
- [Verified binaries](#verified-binaries)
- [Codex - the reviewer (R7) and a voter (R9)](#codex---the-reviewer-r7-and-a-voter-r9)
- [agy - specs, consultation, votes (R8, R9); never code review](#agy---specs-consultation-votes-r8-r9-never-code-review)
- [Web research - only when the owner allows web for a research task](#web-research---only-when-the-owner-allows-web-for-a-research-task)
- [timeout](#timeout)

## Main-session allow-list (R1)

The split is by kind of action, not by a guess of its duration. File ownership comes first:
an action on files or a task a running or finished writer already has in its context goes to
that writer by `SendMessage` (DL3), before the DL1 list. In doubt → delegate (DL5).

**DL1 — main does it inline:**

- `Agent`, `SendMessage`, `TaskStop`, `AskUserQuestion`, `ToolSearch` (to load the deferred ones),
  `ReadNotifications`, `ListAgents` (the R21 successor handshake, `reference/handoff.md`),
  `EnterWorktree`.
- `Read`, `Grep` and `Glob` anywhere: the config, handovers, specs in a run worktree, source to
  understand a question. A plan over ~300 lines → a subagent summarizes. The serena lookups
  `find_symbol`, `find_referencing_symbols`, `find_implementations`, `find_declaration` and
  `get_symbols_overview` count as reads; serena edits are DL2. Main checks one place; a survey
  of the code is a subagent's.
- `Write` and `Edit` of the run state (`./tmp/captain/<run>/`), TODO files at the repo root
  (`TODO`, or `TODO*` with a doc suffix below; never `TODO.py`),
  `docs/**` (plans, specs, notes: `.md`, `.mdx`, `.markdown`, `.txt`, `.rst`, `.adoc`),
  `.claude/settings.local.json` (the change the owner approved, R15), the TODO files and
  `docs/**` of the run checkout `.claude/worktrees/captain-run-<id>` (same rules), and the session's auto
  memory `~/.claude/projects/<project>/memory/*.md`. A plugin skill file (`SKILL.md`, anything
  under `plugins/*/skills/`, also under `docs/`, in any letter case) is product code: DL2.
- `Write` / `Edit` of `.agent-memory/<topic>.md` in the run checkout (PK3, PT1, not
  `README.md`): the repo root or `.claude/worktrees/captain-run-<id>`, a flat `.md` file in an
  existing real `.agent-memory/`; never through `.claude/rules/project-memory/`, never in an
  agent worktree, never with Bash (`cp`, `mv`, a redirection stay DL2).
- Read-only Bash: `cat`, `head`, `tail` (never `-f`/`-F`), `wc`, `ls`, `find` (no `-exec`,
  `-ok`, `-delete`, `-fprint`), `grep` (also `-r`, never `-R`, `-A/-B/-C N`, `--include`; never over an agent
  output), `sed -n '<range>p'` (never `-i` or another command), `echo`, `printf` (no `-v`; only `%s`, `%d`, `%b`, `%%`),
  `pwd`, `diff [-u|-q] <file> <file>` (never a directory), `lsof -nP -iTCP:<port> -sTCP:LISTEN`, `date`, `stat`,
  `ps`, `cd`; an unquoted glob only in `ls` and `wc`, never matching an agent output; git inspection: `log -n <N>` or
  `log <a>..<b>` (no `-p`), `status [-- <path>]`, `diff`, `show` (only the options
  `audit-main.py` lists, spelled out in full: no `--output`, `--ext-diff`, `--textconv`), `branch -vv` (also `-v`,
  `-a`, `-r`, `--show-current`, and names only after `--list`, `--contains`, `--merged`),
  `worktree list [--porcelain]`, `remote -v`, `rev-parse`, `merge-base [--is-ancestor]`,
  `rev-list --count`, `grep` (no `-O`, `-f`), `ls-remote`, `check-ignore`, `stash list`,
  `fetch [<remote> [<branch>...]]` (no refspec with `:`, no `+`);
  `python3 '<skill root>/scripts/agent-context.py' <agentId>...` (R6; it prints only token
  counts).
- `CronCreate`, `CronDelete`, `CronList` for the timers; a lone background `sleep N`
  (`run_in_background: true`) as a fallback timer, the only background call main makes; a shell `&` is denied.
- `Skill` for `utils:self-review` (SV1: main's self-review of an output it wrote,
  `reference/queue.md`; the exact name, never a bare `self-review`), `utils:one-by-one` (only
  main talks to the owner) and `utils:new-session-tab`
  (args `prefix=<session_prefix>` when the config has one, so the new session gets it) with its `python3 '<utils>/skills/new-session-tab/scripts/new-session-tab.py' --dir=... ...`
  (never `--fresh-worktree`; the prompt file is the skill's `./tmp/handover-<topic>-<date>.md`).
  `Artifact` `open` and `read`; `SendUserFile` of files under `./tmp/captain/`.
- `Skill` for `captain`, `captain:captain`, `captain:captain-setup` (the config start step) and
  `3amigos:3amigos` (main runs the panel itself; its voters are `Agent` launches; `panel.py`,
  `tally.py` and the external voters (Codex, Gemini) are script runs, so `captain:runner`s run
  them, one per external voter: DL2).
- The merge flow (`reference/queue.md`), each command alone in its Bash call:
  `git [-C '<abs dir>'] merge --no-ff [--no-edit] <local branch>`, the sync forms
  `git -C '<abs dir>' merge --no-ff --no-edit origin/<default>` and
  `git -C '<abs dir>' merge --ff-only origin/<default>`, `git merge --abort` and
  `git commit --no-edit` (both only while a merge is in progress); after the owner typed
  `/captain merge <branch>`, for that branch in that repository only: `git switch <branch>` and
  `git push <remote> <branch>`. The grant is bound to the run (a run ID in the guard's state)
  and the repository (git common dir); it ends at `/captain off`, a new `/captain` start, a new
  `/captain merge`, the skill call `captain end` right before the end report (R17; the hook
  cannot see the report itself), or 12 hours after it was typed, as a backstop. A handoff
  successor's `/captain resume` (R21) takes over the run ID, the live grant and the recorded base
  (one recorded in that session's current run in the last 12 hours) of the one session in the
  same repository and working directory that holds either; with two or more such sessions it
  takes nothing. It never creates a grant. One captain run per checkout is
  assumed: with a second or stale run there, the resume may take that run's grant or base
  (`reference/handoff.md`). The R18 TODO-only
  commit: `git -C '<top level>' commit -m '<msg>' -- <TODO file>...`, alone, of TODO files git
  already tracks (a new one: a runner), never during a merge, on a HEAD a merge may land on. `hooks/guard.py` checks the HEAD of a merge or its
  `commit --no-edit` in this order: a detached HEAD is denied; the granted branch passes; a
  protected HEAD (`main`, `master`, the origin default, or with no readable `origin/HEAD` every
  branch outside `captain/*`) is denied, even one named `captain/*`; then a `captain/*` HEAD or
  the recorded base branch of the current run (a typed `/captain base <branch>`, or the start
  branch of a Skill call `captain base <branch>` while the KB9 checks hold, `reference/prompts.md`
  § Auto base) passes without the grant;
  any other HEAD is denied. The base is never `main`, `master` or the origin default, and it
  is not honoured while `origin/HEAD` is unreadable. A remote-tracking source is only
  `origin/<default>`, and `--ff-only` only for it: into a `captain/*` or base HEAD both sync
  forms pass, with or without the grant; into a protected HEAD opened by the grant, only
  `--ff-only`. `commit --no-edit` and `merge --abort` need a merge in progress in that
  checkout's own worktree. The model's writes to the guard's state files are denied, also
  through a path in another letter case on a case-insensitive disk. A merge with a
  `-m <message>` form is denied as a FORM problem that names the canonical form,
  `merge --no-ff --no-edit`: rewrite it that way once (`reference/queue.md`). A denial that
  needs the owner (a protected HEAD; `switch` or `push` without the grant; a push to a remote
  with a push mapping or mirror, or with `push.followTags` on) says to ask the owner; every
  other merge-flow denial is a form or checkout-state problem.
- `Artifact` with `action: open` or `read` and a `url` (show or read a page; never publish).
- Pipe filters after those reads, stdin only, exactly as `audit-main.py` enforces them:
  - `grep` with only `-E`, `-F`, `-i`, `-v`, `-c`, `-n`, `-o`, `-w`, `-x`, `-h`, `-H`, `-s`,
    `-A/-B/-C/-m N`, `-e PATTERN`, `--`, and a pattern (no file operand, no `-r`);
  - `head -n N`, `tail -n N`, `head -c N`, `tail -c N`;
  - `sed -n '<range>p'` with no file operand;
  - `wc -l`, `wc -w`, `wc -c`;
  - `date` — bare, `+FORMAT`, or the timer forms `date -v±N<unit> '+FORMAT'` (BSD) /
    `date -d '<±N unit | now + N unit>' '+FORMAT'` (GNU); never a positional date or `-s`.
  No env-var prefixes (`VAR=x cmd`), no brace expansion or globs (list the files, or use
  `Glob`), no executable paths with `/`. Anything else counts as "unverifiable" in the audit and goes to a subagent.
- Notifications (R12): exactly `~/.claude/captain/notify.sh "<msg>"` as one Bash call, the
  path written absolute under the user's home (`/Users/<user>/…` or `/home/<user>/…`). It
  applies the config's method, quiet hours and away check and exits 0 silently when the
  method is `none` or within quiet hours. With the away check on it returns at once and sends
  only when the owner gives no input for the chosen minutes after the event. A failure after
  that wait lands only in `~/.claude/captain/notify.log`, so write every notified message in
  the chat as well. On failure the message stays in the chat and no other notification
  service is tried.
- Writing agent prompts.

**DL2 — delegate to a new agent:** every edit of a source, test, config or script file (and
of a plugin skill file); every commit, except the merge flow and the R18 TODO-only commit;
every build, test suite, script run (also `memory-apply.py`, a `captain:runner` runs it),
install, publish, delete, kill, codex/agy call or Codex job poll; every Bash call with `run_in_background` (except the timer `sleep`) or a `timeout`
above 120 s.

**DL4:** main never reads an agent's `output_file` or transcript, not even with
`offset`/`limit` or through `cat`, `head`, `tail`, `git diff` or `Grep` (also by a relative
`.output` name after `cd`, or a `Grep`, also one without `path` in its cwd, over a temp directory that holds
`tasks/*.output`; `git diff --no-index` is denied); `stat -L` of it (mtime only) is
allowed. For details, `SendMessage` the agent or launch a diagnosis agent.

- The audit (`scripts/audit-main.py`) is a non-adversarial compliance measure for this rule,
  not a security boundary.
- The same check runs live: the plugin hook `hooks/guard.py` denies a DL2 call while captain
  mode is on (from `/captain` until `/captain off`, across the end of the run) with "This
  is agent work (R1, DL2): delegate it to a captain:runner or the writer that owns the file."
  The guard's state files (the mode marker, `.merge`, `.base`) are written only by the guard,
  from `/captain` commands (`.base` also from the checked start branch, KB9): a `Write`/`Edit`, a Bash redirection or a `cp`/`mv`/`tee`/`rm`
  into the state directory is denied. Without the plugin (a symlinked skill) there is no
  hook; the rule still holds.

## Agent types (R4)

Launch agents with the `Agent` tool's `subagent_type`:

- `captain:worker` — Opus, effort `medium`: writers, the integration agent, the verifier, the
  Opus fallback reviewer, the Opus mini-consensus opinion.
- `captain:deep` — Opus, effort `high`: the Opus voter of a 3amigos panel, only when `opus`
  is on the panel (R9, launched by main), and the fallback reviewer when the review is of a very complex spec or
  implementation or assesses a critical action (EF1).

- `captain:light-coder` — Sonnet, effort `high`: the writer of a task that passes the light
  test (`reference/light-test.md`).
- Fable — `captain:worker` launched with `model: "fable"`: spec drafts and consultation,
  the Fable mini-consensus opinion and the Fable voter of a 3amigos panel (R8, R9); never a
  code reviewer. It runs under no `timeout`: its prompt names its time budget, and whoever
  launched it stops it with `TaskStop` when that budget is over; a late answer counts as
  missing.
- `captain:runner` — Sonnet, effort `medium`: bootstrap, builds, tests, scripts, the Codex
  review runner, cleanup, and diagnosis summaries
  (which test failed, the error line, the first stack frame in project code; the cause, when
  not obvious, goes to Opus).

If these agent types are unavailable (e.g. the skill is symlinked, not installed as a plugin),
launch `Agent` with `model: opus` and default effort for the Opus roles, `model: fable` for Fable, `model: sonnet` at
default effort for the runner and light-coder roles, and tell the owner so in one line. The
light writers' effort `high` cannot be set then; `run.md` records the reason.

## Tools availability (R7, R8, R9)

The `tools` object of `~/.claude/captain/config.json` (`codex`, `agy`, each a
boolean) says which external tools this user has; the config start step reads it. A tool set to
`false` is never called in the run. A `grok` key from an older config is ignored. Fable is an
agent, not a tool, and has no key: it is always available.

- `codex: false` → the default reviewer is a fresh `captain:deep` (very complex spec or
  implementation, critical action) or `captain:worker` agent that did not write the code;
  `run.md` records `Codex: off in config`.
- Full consensus voters are the 3amigos panel main picks per decision class (`--panel`;
  technical `opus,codex,gemini`, product `codex,gemini,fable`: `reference/consensus.md`) minus
  Codex when it is off; `agy: false` only adds `--no-agy`, and Gemini runs on its fallback.
  Elsewhere consensus voters are only the available tools plus the Fable and Opus voters; the
  mini-consensus chain skips a missing tool (`reference/consensus.md`).
- A tool set to `true` that fails at run time is handled by its failure rules below.

## Verified binaries

Verified on 2026-09-26 against the installed binaries: `~/.local/bin/agy`, `~/.local/bin/codex`, and GNU `timeout`
(`/opt/homebrew/bin/timeout` from coreutils here). Every flag below is listed by the tool's
own `--help`. Before the first run, the runner checks `command -v timeout` (macOS: coreutils
installed; Linux: also `command -v lsof`); missing → fallback reviewer and one line to the
owner. These paths are from the machine they were verified on; another user's may differ,
so the runner resolves each
with `command -v` first.

## Codex - the reviewer (R7) and a voter (R9)

The shell aliases `codex` to `codex --approve-for-me`. `command timeout 1200 codex exec …`
bypasses the alias, because `codex` is an argument of `timeout`, not a shell word; this is
also portable to Linux, where `timeout` cannot exec the shell builtin `command`. (Typed
directly without a timeout, the equivalent is `command codex exec …`.)

Model id (KB7): `gpt-6.1-terra` by default, for every review, consult and mini-consensus vote;
`gpt-6-astra` only for complex creative or research work (a creative draft, a research
consult, a hard architecture vote). Always the full id: a bare short name ("terra", "astra")
fails with HTTP 400 "The 'astra' model is not supported when using Codex with a ChatGPT
account".

**Model choice:** the agent that launches the Codex call chooses the model itself: the
`captain:runner` for a review or a consult, a writer for its own mini-consensus, main for a
direct call. Terra unless the task is creative or research; then astra. Every such agent
writes the choice and a one-line reason to its report (`Model: <full id> <effort> — <reason>`)
and main records that line in `run.md`; for its own call main writes the line there itself. Main's prompt to a runner states this rule and the
task, never a chosen model.

**Effort (EF1):** terra `-c model_reasoning_effort=high` for a review (R6, R7), `medium` for a
quick consult and a mini-consensus vote (R9); a full consensus vote runs through `panel.py`
at `high` (EF2). Astra: `medium`, `high` only for a very complex creative or research task. The flag is always passed: `~/.codex/config.toml` defaults to
`high`. Use Codex freely; there is no quota to save. Only the usage-limit fallback below
applies.
**Why:** 30.10.2026: the owner moved the captain skill's Codex calls to terra: it reviews
faster. 30.09.2026 the owner had confirmed `medium` for astra reviews (EF3): no source measures
review quality by effort, and the one index by level shows +1 point for +22% cost from
`medium` to `high`.

The runner (`captain:runner`) chooses the model and effort (above), then works in three steps:

1. One Bash call fixes the log prefix and prints it:
   `mkdir -p ./tmp/claude-logs && echo "./tmp/claude-logs/codex-review-<slug>-$(date +%Y%m%d-%H%M%S).log"`.
2. `Write` the review prompt (see R6/R7 templates) to `<that prefix>.prompt.md`.
3. Start this as a **background** Bash command (`run_in_background: true`; a foreground call
   is capped at 10 min), with the literal prefix and every path quoted:

```bash
LOG='<literal log prefix from step 1>'
(command timeout 1200 codex exec -m gpt-6.1-terra -c model_reasoning_effort=high \
   -s read-only -C '<abs repo or worktree>' -o "$LOG.final.md" - < "$LOG.prompt.md" \
   > "$LOG" 2>&1; echo $? > "$LOG.exit")
```

- `-m` and the effort are the runner's choice: `-m gpt-6-astra -c model_reasoning_effort=medium`
  for a creative or research task.

- With a box, when the R6 bound applies, replace `1200` with the time left before park, in
  seconds, never under 300; below 300 no review starts (R6). Park here is the one time boundary
  of `reference/parallel.md`: in normal mode with open work and extensions left, the park of
  the last possible hard end.
- The runner ends its turn; it is re-invoked when the command exits. It then reads
  `$LOG.exit`, `$LOG.final.md` and, on failure, the last 40 lines of `$LOG`.
- That command is the runner's only background call, and the re-invocation is its only wait:
  no `Monitor`, no second background command, no `sleep`, `pgrep` or `tail -f` loop on the
  codex process or on `.final.md`. `$LOG.exit` exists once the command has exited; a runner
  resumed earlier by a message answers it and ends its turn again, with no hand-back. The final
  hand-back is its last action, with no background child of its own left alive.
  **Why:** 20.10.2026: four review runners handed back, then kept their own monitor or `pgrep`
  loop alive; the harness showed them running for 10–60 min until main stopped them, and one
  loop matched its own command line.
- Review success = exit `0` **and** a non-empty `$LOG.final.md` whose verdict line is exactly
  `Verdict: approve` or `Verdict: changes`. Any other value is a failure (empty output row).
  Only a review checks `Verdict:`; votes have their own contracts (below).
  The runner returns the verdict line, the count of findings (blocking / non-blocking), the
  path of the `-o` final file, the exit code and its `Model:` line; the findings go to the
  writer by that path, never through main (KT1).
- The runner's prompt carries the model rule, unchanged (it holds without the plugin agent
  types, R4):
  `Choose the Codex model yourself: gpt-6.1-terra (effort high for a review, medium for a consult or vote) by default, gpt-6-astra only for a creative or research task.`
- The runner's prompt ends with this line, unchanged:
  `Your final report (after re-invocation, not an interim one): the verdict line VERBATIM, the count of findings (blocking / non-blocking), the path of the -o final file, and the exit code. Not the findings themselves. No commentary. Add one line: Model: <full id> <effort> — <one-line reason for the choice>.`
  A hand-back that says it waits on background work is interim: it carries no verdict. Main
  keeps the agent at `notified: no`, records nothing from it, and waits for the next
  notification of the same agent.
  **Why:** 30.09.2026: runners handed back "waiting on background work" first; once no final
  report followed and main had to ask for the verdict. With this line every later runner sent
  its final report.
- Reviews take 1.5–6 min, sometimes 14.

Alternative: the `codex:codex-rescue` agent with a prompt starting
`--model gpt-6.1-terra --effort high` (astra for a creative or research task, as above).
When it returns only the first log lines, the main session sends a subagent to wait for the
rest; it never polls.

### Failure table (R7)

| Outcome | Signature | Handling |
|---|---|---|
| Timeout | `.exit` holds `124` | With a box, recompute the time left before park. Retry once only if a timeout of at least 300 s that is shorter than the first one still fits (no box: retry once at 600 s); repeat the no-web line. Else, or on a second timeout → Opus fallback reviewer if it fits (no box: always), otherwise park per R6. |
| Usage limit | `You've hit your usage limit … try again at <time>` in the log | Fallback at once; no wait, no retry timer. Record the reset time in `run.md`; the first review started after it goes to Codex again. |
| Missing binary | `.exit` holds `127`, or `command not found` | Fallback at once; one line to the owner naming the error. |
| Login or model error | `401`, `not logged in`, `HTTP 400`, `model … not supported` | Fallback at once; one line to the owner naming the error. |
| Empty output | exit 0 but `.final.md` missing, empty, or no exact `Verdict: approve` / `Verdict: changes` line | Fallback at once; one line to the owner naming the error. |
| Other non-zero exit | anything else | Fallback at once; one line to the owner with the last log lines. |

**Fallback reviewer:** a new `captain:worker` agent (`captain:deep` for a very complex spec or
implementation) that did not write the code, with the same review prompt. It becomes the
current reviewer for that loop (R6).

**As a voter (R9):** in a full consensus Codex is the 3amigos panel's Codex voter, beside
the Gemini voter when both are on the panel: one `captain:runner` per external voter, in
parallel, runs `panel.py --panel <the panel> --voters <that voter>` (Codex only when not off or at its usage
limit), `--no-agy` for Gemini when it applies, `--effort high` and `--deadline` min(600 s,
park − 5 min), 600 s with no box, and reports when its voter ends (`reference/consensus.md`). Each voter keeps its 3amigos model (Codex
`gpt-6-astra`, set in `panel.py`; Gemini from the 3amigos config), not captain's choice. For a mini-consensus opinion: the
same command as a review with terra `medium` and `command timeout 240` (with a box, never past
the park deadline) and the mini-consensus template. A usage limit or any failure → that vote counts as
missing; in a panel the Fable stand-in replaces it.

### Output contracts - checked per use, for every voter (Codex, Gemini, agy, Fable, Opus)

| Use | Valid output | Invalid → |
|---|---|---|
| Review (R6, R7) | exactly one `Verdict: approve` or `Verdict: changes` line, then `Findings:` | failure table above |
| Mini-consensus (R9) | one line per decision: `D<n>: AGREE — <reason>` or `D<n>: DISAGREE — <reason>` | next opinion in the chain |
| Full consensus (R9) | 3amigos panel: JSON `{"items":[{"id","verdict","reason"}]}` that passes `panel.py --check`; fallback without 3amigos: exactly one line `Vote: <option letter> — <reason>`, letter among the options | vote counts as missing |

Exit `0` with an invalid output counts as a failure for that use.

## agy - specs, consultation, votes (R8, R9); never code review

Run it from the repo or worktree directory; it reads the files the prompt names itself.
agy is also the first backend of the 3amigos panel's Gemini voter, called by `panel.py`, not by
captain (`--no-agy` per `reference/consensus.md`); the rules below are captain's own agy calls.
The permission rules below were verified on 2026-09-28 with agy 1.2.12.

```bash
~/.local/bin/agy -p "<prompt naming the files to read>" \
  --model gemini-3.8-flash-high --sandbox --print-timeout 600s
```

- Consensus vote: `--print-timeout 300s`.
- Needs a browser login; `GEMINI_API_KEY` is ignored → "Eligibility check failed". A login
  error means agy is unavailable for this run.
- Headless mode (`-p`) cannot ask for a permission. A tool without an allow rule is denied
  and the whole output is one line: `jetski: no output produced — a tool required the
  "<permission>" permission …`. One-time setup, in `~/.gemini/antigravity-cli/settings.json`
  under `permissions.allow`: `read_file(<abs code root>)` for the file tool, `read_url(*)` for
  web pages (web search itself needs no rule), and read-only `command(...)` rules
  (`command(cat)`, `command(grep)`, `command(git log)`, `command(git diff)`, …).
- Under `--sandbox` every shell command asks for `unsandboxed` and is denied, even an allowed
  one; the file tool and web still work. Never allow `unsandboxed`. A task that needs shell
  runs without `--sandbox`; then only the `command(...)` rules pass and anything else is denied.
- A `jetski: no output produced` line means that permission has no rule on this machine.
  `read_file` or `command` → rerun once with the file contents inline in the prompt;
  `read_url` → agy is unavailable for web research in this run. Either way, tell the owner
  which rule is missing.
- agy has no flag that turns web off: after the setup above, the prompt's "Do not browse the
  web." line is the only guard.
- Never pass `--dangerously-skip-permissions`.

## Web research - only when the owner allows web for a research task

The default for every tool is no web (R7, R8). When the owner allows it for a research task,
`run.md` records that, and each tool is started like this:

- Codex: add `-c tools.web_search=true` to the `codex exec` command; the prompt says web
  search is allowed and asks for source URLs.
- agy: the command above, unchanged; needs the `read_url(*)` rule, or it can search but not
  open a page. The prompt says web is allowed and asks for source URLs.

## timeout

GNU `timeout`; exit `124` means the limit was hit. Wrap every Codex run in it
(`command timeout …`, see above).
