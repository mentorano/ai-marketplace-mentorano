# ui-check - the UI check of a group with visible changes, before its push

## Contents

- [When the check runs (UP1)](#when-the-check-runs-up1)
- [Step 1 - main lists the use cases (UP2)](#step-1---main-lists-the-use-cases-up2)
- [The external-write classifier (UP2)](#the-external-write-classifier-up2)
- [Step 2 - start the app (UP3)](#step-2---start-the-app-up3)
- [Step 3 - the browser tool (UP4)](#step-3---the-browser-tool-up4)
- [Step 3 - one checking runner or several (UP5)](#step-3---one-checking-runner-or-several-up5)
- [Step 4 - results, fix rounds, recheck (UP6)](#step-4---results-fix-rounds-recheck-up6)
- [Order and the push gate (UP7)](#order-and-the-push-gate-up7)
- [Servers after the check (VA5)](#servers-after-the-check-va5)
- [Present mode (UP8)](#present-mode-up8)
- [Away mode (UP9)](#away-mode-up9)
- [Out of scope (UP10)](#out-of-scope-up10)
- [Owner decisions (VA1-VA8)](#owner-decisions-va1-va8)
- [Not confirmed](#not-confirmed)

IDs: `UP` for the steps of this file, `VA` for the owner decisions, `STS` for the use cases a
run lists at run time.

## When the check runs (UP1)

Run the check automatically (VA1) for a `Group` whose feature is done and has visible UI
changes. Ask no question, in either mode.

- **Detected:** the group's diff touches a frontend path (`*.tsx`, `*.jsx`, `*.vue`,
  `*.svelte`, `*.html`, `*.css`/`*.scss`, templates), or the plan names a screen, page or flow.
- **Asked for:** the kickoff says so ("test it in the browser", `ui`), or the owner asks later.
- A detected group is checked. The plan lists the UI groups (start step 6) as information;
  write the detection to `decisions.md`.
- No start command found (UP3): present → one question; away → `not checked: no start
  commands`, a `decisions.md` line and a TODO entry (VA2, UP7).

**Why:** the owner asked for the app to be started and for a test list at the end of every UI
run, and decided: "once a feature is done, let it be checked through the UI".

## Step 1 - main lists the use cases (UP2)

After the group's R6 loops are clean and its tests green (R20), before any server starts, main
writes the use-case list. This is light work (R1): the diff, the plan, `run.md`.

- One line per use case: `STSn | <screen or route> | <steps> | <expected visible result> | ZDn |
  reads/writes <data>`. `ZDn` is the owning task (UP6); the data column drives UP5 and the
  classifier.
- Full use cases (VA4): forms submitted, records created, edited, deleted, on local data (UP3).
- Sources: the plan's acceptance criteria first, then the diff (new routes, changed components,
  API fields shown in the UI). Give each `ZDn` with a frontend file at least one `STSn`.
- Write the list to `tmp/captain/<run>/ui-check.md`. In present mode show it to the owner
  before the check starts, so the owner can test the same list by hand in parallel.
- At most ~12. More → one per changed screen; mark the rest `not checked` with a reason.
- Self-review (SV1, `utils:self-review`) before the list is shown or used, against the plan's
  acceptance criteria and the diff: add what is missing, and end the file with
  `Self-review (SV1): <n> of <n> criteria and <m> of <m> frontend tasks have a use case or a
  `not checked` reason` (the ~12 limit above stands)
  (`reference/queue.md`).

**Why:** the owner asked for the use cases **before** the test, to check them by hand in
parallel.

## The external-write classifier (UP2)

Per project, one `captain:worker` (prompt: "Classifier prompt (UP2)" in `reference/prompts.md`)
reads the env, the config and the code behind each writing `STS`: does a local write reach an
external system (webhook, email, payments, cloud storage, a shared DB, an outbound API)?

- Verdict per `STS`: `local`, `stub: <how>` (the repo's own mail catcher, fake provider, mock
  server or env flag; also when the stub is off by default: how to turn it on and what the
  default reaches) or `external: <what>`.
- Classify every writing `STS` without a verdict in `ui-check.md` before its first run. This
  includes a `STS` of a later group in the same run.
- Redo a verdict when a fix touches env, config or the outbound call.
- Main turns every `stub` verdict on: it goes to the server runner's `Stubs on` (UP3). A stub
  that cannot be turned on, and every `external` one (no stub), → `not checked: external
  write`. Never run it against the external system (R10).
- For each `stub` and `external` verdict the classifier also names the host or log marker
  that only the real external call leaves (not the stub's local request); main greps the server logs for it after the check (UP6).
- Write the answers and the decisions to `ui-check.md` and `decisions.md`.

## Step 2 - start the app (UP3)

**Sources of the start commands** (VA2). Take the first source that has them; all three are in
the repo, read at the check SHA (below):

| Order | Source | What it gives |
|---|---|---|
| 1 | Repo `CLAUDE.md`, a `captain` section `ui_check` entry | `start` (one per server), `port` (per start command: `PORT=`, `--port`, a placeholder, or `fixed`), `health` URL, `url`, `ports`, `seed` |
| 2 | A project `run` skill (`.claude/skills/run*`, or the project skill the built-in `run` skill finds) | the launch command and URL it documents |
| 3 | Package scripts: `package.json` `dev`/`start`, a `Makefile` `run`/`dev`, a repo dev script (one its own comment or the README names as the way to run the app locally) | the command; the port from the script or the framework default |

- No other source: the start commands live in the repo, never in the per-user captain config.
- The built-in `run` skill's own per-type patterns (no project skill found) are a guess
  outside the three sources: not a source.
- A script that starts only a helper service, not the app, is not a dev script.
- Source 3 is a guess: the server runner reports the script and port it used.
- No owner confirmation (unlike dev targets): the commands run on this machine against local
  data only (UP10).
- None clear → present: one question, asked once per run, with a recommendation (add a
  `ui_check` entry to the repo `CLAUDE.md`); away: `not checked: no start commands`, a
  `decisions.md` line and a TODO entry (UP7).

**SHA.** Run the check at one exact SHA: the feature branch tip after the group's merge, or,
with an auto base (`Feature branch: none`, `reference/queue.md`), the run checkout's `HEAD`.
Write the SHA in `ui-check.md` with every result.

**Checkout.** A clean temporary worktree at that SHA, of the kind group runs use (TS1),
recorded with `record-created.py`. Never the owner's checkout.

**Ports.**

- Check each port with `lsof -iTCP:<port> -sTCP:LISTEN` first.
- A busy port that is not a `## Processes` row is the owner's: never stop it (R14).
- How a command takes its port comes from the entry's `port` field; not stated (sources 2
  and 3, or an entry without it) → the runner reads the script; still unclear → fixed.
- The start command takes a port → use the entry's default port when free, else a free one;
  pass the chosen ports to every command that names them (a frontend's backend URL) and report
  them in `READY`. It does not → present: a question; away: skip with a TODO entry.

**Test data.**

- Only a local or in-memory DB, set up by the repo's own seed or migration script; writes go
  there (VA4).
- Do not use a test DB that a group test run uses at the same time (TS1).
- Before the seed and the start the server runner reads the env files, the config and its own
  environment (`env`) each command will use. A DB or auth host that is not
  `localhost`/`127.0.0.1`/a local container → no seed, no start (UP10).
- A `stub` the classifier named and main chose (UP2) is set in the env of every server.
- Judge outbound integrations (mail, payments, webhooks, storage) per use case (the classifier).

**Health check.**

- The `health` URL (or `url`) answers 2xx within 90 s, polled every 3 s, logged.
- A server that exits before the health check passes is a failure at once: no more polling.
- A failure → the server runner stops what it started and reports the log path, the exit code
  of a server that exited and the last lines of the failing log.
- Main decides the cause from that log. The cause is in a file the group's diff
  (`<base>..<SHA>`) changed, or the log names a start error in that code → a startup defect in
  the run's code: FIX NOW for the group's owning tasks, under the UI fix counter (UP6); it holds
  the push. Unclear → the run's code too.
- A cause outside the run's code (a local service or a port the run did not change, even when
  the repo configures it) → every `STS` is `not checked: health` with the reason: a check that
  could not run (UP7).

**Processes.**

- Give each server a `run.md` `## Processes` row (PID, start time, working dir, agent) the
  moment it starts. Logs go under `tmp/captain/<run>/ui-check/`.
- The R14 `ps` pattern in `reference/health.md` covers
  `uvicorn|gunicorn|manage.py runserver|flask|agent-browser`. It is a safety net and may not
  match every stack; the `## Processes` row is the
  record, checked by its PID (`command ps -o pid,lstart,command -p <PID>`).

**The server runner** (a named R3 exception; prompt: "Server runner prompt (UP3)" in
`reference/prompts.md`). It sends **two** messages:

1. `READY <url> <ports> <PIDs> <SHA> <log paths>` once the health check passes; then it idles.
2. Its done report, after main's `SendMessage` with `stop` or `keep`:
   - `stop`: it stops its processes by the recorded PIDs and their process groups (R14 match on
     PID, start time, working dir), each by its literal PID (`kill <PID>`; the group's members
     from `pgrep -g <PID>`), removes the rows, deletes by name the files the seed and the
     servers wrote in the worktree (never `git clean`), so the run's cleanup can remove it, and
     sends its normal done report.
   - `keep` (UP7, VA5): it leaves them running, marks the rows `kept: owner` and reports one
     stop command per process (`kill <PID>`).

When it starts nothing (a non-local host, a fixed busy port, a health failure), it sends no
`READY`: its done report's first line is `NOT STARTED <reason>`.

Main sends `stop` before any recheck at a new SHA (UP6), and `stop` or `keep` after the last
checking runner reported.

**A server runner that ended early** (`TaskStop`, a crash, a context limit) before main's
`stop` or `keep`: its servers keep running. Main hands its `## Processes` rows to the next
runner (the new server runner before a recheck, else a cleanup `captain:runner`), which stops
them by the R14 match as on `stop` and removes the rows, or, on `keep`, marks them
`kept: owner`. `check-run-end.py` passes only after that.

**Why:** the owner started the app by hand or asked for it three times; a source order like the
dev targets' gives one known place per repo and a fallback for repos with plain scripts.

## Step 3 - the browser tool (UP4)

The checking runner uses the prompt "Checking runner prompt (UP4)" in `reference/prompts.md`.
Pick the tool in this order:

1. **The repo's Playwright setup** (VA8), when the repo has Playwright integration tests
   (a `playwright.config.*` that the repo's package scripts, CI or docs run, at any path, or
   one at the repo root or in a workspace package whose `package.json` has
   `@playwright/test`; fixtures). A copy nothing runs is not a setup. The checking runner
   first analyses it: base URL, fixtures, login or seed setup, whether it can run against the
   UP3 servers, and whether `@playwright/test` resolves from the check worktree without an
   install (`node -e "require.resolve('@playwright/test')"`). Install nothing; a Playwright in
   another tool's cache (the npx cache of `@playwright/mcp`) is not the repo's runtime → not
   usable. Usable → run the checks as a throwaway script under
   `tmp/captain/<run>/ui-check/`, outside the repo's test tree (UP10). Write the choice and
   the reason to `decisions.md`.
2. **Default: `agent-browser`** (VA8), when `command -v agent-browser` succeeds. Load its
   guide first with `agent-browser skills get core`.
3. **Fallback: Playwright MCP**, only when `command -v agent-browser` fails, the repo has no
   usable Playwright setup, and a probe passes: the server config carries a headless argument
   (away mode; present may run headed), and no other runner of this run holds the MCP browser.
   A failed probe → `not checked: no browser` and a TODO entry.
   **The probe** reads the `args` of the `playwright` MCP server: a user or project
   `mcpServers.playwright` entry wins; else the `.mcp.json` under the `installPath` that
   `~/.claude/plugins/installed_plugins.json` gives for the Playwright plugin. It passes when
   the args include `--headless` (present: headed allowed).

- **Claude in Chrome: never.** It acts in the owner's real Chrome with their sign-ins
  (production sessions included): R10, and it cannot run away.
- **Availability:** start step 1's runner adds `agent-browser` to its `command -v codex agy`
  probe; `Config:` records `browser: agent-browser | playwright-repo | playwright-mcp | none`.
  Before the classifier and any server runner (UP7 step 2) main checks that one tool of the
  three is there (`agent-browser` on `PATH`, else a repo Playwright setup, else the probe). None
  → every `STS` is `not checked: no browser`; no classifier, no server.
- **Headless** by default; headed only when the owner asks to watch.
- **Login:** a seeded test user only; no stored profile of the owner, no real account.
- **Sessions:** each checking runner names its session `captain-<run>-<agent>` and closes its
  browser with the tool it used (VA8) on every exit path (PASS, FAIL, timeout, an error):
  `agent-browser --session <name> close`, `browser.close()` in a `finally` of the Playwright
  script, or the Playwright MCP `browser_close`. Close it on `keep` too: no browser is kept or
  opened for the owner (VA5). After the close, wait up to 5 s until `agent-browser session
  list` no longer shows the session; a browser process still alive then goes in
  `## Processes`.
- **Evidence:** a screenshot per use case at its expected state,
  `tmp/captain/<run>/ui-check/<SHA7>-s<k>-STSn.png`, `<k>` the number of the server runner
  the check ran against (a second check at the same SHA writes new files; a file a TODO entry
  or the end report cites is never overwritten); a FAIL also
  `<SHA7>-s<k>-STSn-console.txt` with the console errors. The runner reports paths, never
  images.

**Why:** `agent-browser` behaved better in practice (VA8); a runner already has Bash, needs no
MCP load, and runs one named session per runner.

## Step 3 - one checking runner or several (UP5)

- Run checking runners in parallel only over use cases that share no data. By the
  `reads/writes` column: a use case that writes and every use case that reads the same data run
  in one runner, in list order.
- Unclear data → one runner for the whole list.
- At most 3 checking runners, each with its own session, against the one set of servers.

## Step 4 - results, fix rounds, recheck (UP6)

Each checking runner reports in the R3 frame, one line per use case: `STSn PASS <screenshot>` or
`STSn FAIL <screenshot> — <expected> vs <seen>`. Main fills `tmp/captain/<run>/ui-check.md`:

```markdown
| STS | Screen | Steps | Expected | Task | SHA | Result | Evidence |
|---|---|---|---|---|---|---|---|
| STS1 | /login | wrong password | red error under the field | ZD2 | 1a2b3c4 | PASS | ui-check/1a2b3c4-s1-STS1.png |
```

- A FAIL is **FIX NOW** for the writer of its `Task` (R6: a verifier failure is FIX NOW in every
  round). The fix gets its review (R5) and group test (R20).
- **UI fix counter** (VA3): a separate counter per group, at most 3 UI fix rounds, under the R6
  rules (triage, the same writer). Where it is kept and how impact is rated:
  `reference/triage.md`, UI fix counter.
  - A FAIL is a verifier failure: FIX NOW in every round; the R6 trap does not apply.
  - It does not use up the task's review rounds.
  - After the 3rd round a critical FAIL goes first to a 3amigos panel under the R6 rule: 2 more
    rounds or TODO (VA3, clarified 2026-10-30). No 4th round without the panel
    (`reference/triage.md`, UI fix counter).
  - The rest, and a panel's TODO, go to TODO, ordered by impact (critical, major, minor), each
    with its screenshot path as evidence (TD1).
- **Recheck** (VA7): send `stop` to the server runner; start a new server runner at the new SHA
  (UP3: new worktree, ports, health), and check the whole use-case list again there. A PASS
  counts only at the SHA that is pushed.
- `not checked` (no start commands, external, external write, health, no browser, port) is not
  a PASS. It goes to the end report with its reason and a TODO ID; it does not hold the push
  (UP7).
- **Outbound calls:** after the last checking runner reported, main greps the log paths of the
  current server runner's `READY` (older logs are history) for the host or log marker the
  classifier named for each
  `stub` or `external` verdict. A hit → FAIL of that `STS` (FIX NOW) and a line in the end
  report; a hit for a skipped `STS` also goes to the owner as an R10 incident.

## Order and the push gate (UP7)

1. A UI group (UP1): R6 loops clean, group tests green (R20); the full build where TS1 needs it.
2. The UP2 list. Then main checks that a start source (UP3) and a browser tool (UP4) exist.
   No start source → present: the UP3 question (once per run), then its answer; away, or no
   usable answer → every `STS` is `not checked: no start commands`. No browser → every `STS`
   is `not checked: no browser`. Either one → no classifier or server runs. Else the classifier.
3. UP3 servers, UP4-UP5 checks, UP6 results; UI fix rounds until no FAIL or the UP6 bound.
4. Servers stopped (`stop`), browser sessions closed, `## Processes` rows removed, unless the
   owner said he will test too (VA5): then `keep` (UP3).
5. **Push gate (R5)** (VA6): a commit range that touches a UI group is pushed only when that
   group's check passed at the range's last SHA.
   - **Does not hold the push** (owner, 2026-10-30): a check that could not run at all for a
     cause outside the run's code: no start commands (VA2), no browser, a busy foreign port the
     command cannot move, a stopped local service at health, a DB or auth host in the env or
     config that is not local (`not checked: external`; the run's own diff introduced that
     host → it holds the push). Also a use case skipped as
     `not checked: external write` (VA4). Each gets its reason in `decisions.md` and a TODO
     entry, as the line `- <group> <STS IDs> | TODO not checked: <reason> → <TODO ID> |
     <evidence>`, so that `check-run-end.py` (R17) checks it.
   - **Holds the push:** a FAIL, a health failure caused by the run's code (FIX NOW, UP3), or a
     check not yet run. Also at the UP6 bound: commit, no push, TODO.
   - A handoff push (R21) follows the same gate and lists the held-back UI commits in the
     handoff.
6. R17 as today. By now the run has no server left except `kept: owner` rows;
   `check-run-end.py` checks the `## Processes` rows (`PROCESS <PID>`, exit 1; a `kept: owner`
   row gives `KEPT <PID>`) as a safety net, not as the stop step.

## Servers after the check (VA5)

- Stop them, unless the owner said he will test too, in either mode.
- Keep → the servers and the check worktree stay on. No browser is kept or opened for the owner.
- The end report gives the URL, the kept PIDs and the stop commands as `!` blocks, one per
  command.
- R14/R17 cleanup never stops a `kept: owner` row and keeps the check worktree
  (`reference/health.md`).

## Present mode (UP8)

- Show the list as one block with `STS` IDs. Do not wait for the owner's results.
- Screens the owner must see before the check, several at once: the R23 review page
  (`reference/review-page.md`), one link instead of shots in the chat.
- An owner reply "STS3 does not work" is a FAIL with the owner as evidence (UP6).
- Headed on request.
- "I will test too" (or the like) at any point before the stop → `keep` (VA5).
- A port clash or a missing start command → one question with a recommendation (UP3).

## Away mode (UP9)

- No question, no wait. The list goes to `ui-check.md` and the end report; checks run headless.
- A FAIL left at the UP6 bound follows UP6 and holds the push (UP7).
- Stop the servers, unless the owner said beforehand (at the kickoff or before he left) that he
  will test too: then `keep` (UP7, VA5).
- The end report lists each `STSn` with its result.

## Out of scope (UP10)

- Production and staging URLs, shared or cloud DBs, any external account (OAuth providers,
  payment, mail): R10. Do not start the server, or mark the use case `not checked: external` /
  `not checked: external write` (UP2); a queue line only when the owner must act.
- The owner's browser profiles and stored sessions; the owner's own running servers.
- Visual regression baselines and pixel diffs; new E2E test files (a normal coding task).
- Mobile and desktop apps; only web UIs served locally.

## Owner decisions (VA1-VA8)

- **VA1 Trigger:** automatic when a feature with visible UI changes is done, no question (UP1).
- **VA2 Start commands:** the three repo sources; none → present: ask once, away: TODO (UP3).
- **VA3 Fix rounds:** a separate UI counter of 3; the rest to TODO by impact (UP6). Clarified
  2026-10-30: a FIX NOW of a critical impact after the 3rd round keeps the R6 rule, a 3amigos
  panel: 2 more rounds or TODO.
- **VA4 Writes:** full use cases on local data; the classifier flags external writes, which run
  only with the repo's stub or are skipped, never against the external system (UP2).
- **VA5 Servers:** stopped, unless the owner said he will test too, in either mode; then kept,
  PIDs and stop commands in the end report (UP3, UP7). Clarified 2026-10-30: on keep the
  servers and the check worktree stay, the end report gives the URL; no headed browser is kept
  or opened for the owner.
- **VA6 Push gate:** waits for UI PASS; the only exception is a check that could not run at
  all, recorded in `decisions.md` (UP7). Clarified 2026-10-30: that is any cause outside the
  run's code (no start commands, no browser, a busy foreign port, a stopped local service at
  health): push not held, a `decisions.md` line and a TODO entry. A health failure caused by
  the run's code is FIX NOW and holds the push. A `STS` skipped as `not checked: external write`
  does not hold the push either: a `decisions.md` line and a TODO entry. Clarified 2026-10-30
  (OP12): `not checked: external` (a DB or auth host in the env or config that is not local) is
  a cause outside the run's code and does not hold the push, a `decisions.md` line and a TODO
  entry; when the run's own diff introduced that host, it holds the push.
- **VA7 Recheck:** the whole list at a new SHA (UP6).
- **VA8 Browser:** `agent-browser`; a repo Playwright setup is analysed and used when it fits;
  closed with the tool used (UP4).

## Not confirmed

- **UP12** Playwright MCP: the plugin's `.mcp.json` runs `npx @playwright/mcp@latest` with no headless
  argument; whether background agents share one MCP server per session was not checked. Hence
  the probe in UP4.
- `agent-browser` (resolved by a dry run on 2026-10-30, version 0.35.0): headless by default
  (no window); in `ps` its daemon `…/agent-browser-darwin-arm64` and `Google Chrome for Testing`
  under `~/.agent-browser/browsers/` both match the R14 `agent-browser` entry; after
  `agent-browser --session <name> close` none is left and `session list` drops the session.
