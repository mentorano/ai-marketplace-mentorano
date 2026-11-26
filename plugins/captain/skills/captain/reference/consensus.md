# consensus - decision tiers and mechanics (R9)

When the config `tools` has it, Codex reviews specs and code (R7), votes in every 3amigos
panel that has it and gives the first mini-consensus opinion. Use it freely; the only limit is the R7
usage-limit fallback. A consensus result never unlocks an R10 action. Output contracts and
commands: see R7 and R8.

## Contents

- [Tiers](#tiers)
- [Mini-consensus](#mini-consensus)
- [Escalation](#escalation)
- [Full consensus: a 3amigos panel](#full-consensus-a-3amigos-panel)
- [Fallback without 3amigos](#fallback-without-3amigos)
- [Cost](#cost)

## Tiers

| Tier | What | Who decides | The owner hears |
|---|---|---|---|
| Complex technical | complex questions; choices that drastically change the architecture | full consensus (3amigos panel) | one line: what and why |
| Judged complex | any other problem main judges complex enough: several plausible options, an architecture effect, or a hard-to-undo choice; any mode | full consensus (3amigos panel); the reason for the call goes into `decisions.md` | one line: what and why |
| Review bound (R6) | after the 3rd re-review, FIX NOW findings with impact `data loss`, `security`, `build/test broken` or `wrong result` left outside the trap; any mode | full consensus (3amigos panel) main runs: "2 more rounds or TODO" | present: one line, no question; away: `decisions.md` |
| Other technical | a choice visible outside the file (interface, data or output format, behaviour) or hard to undo | the responsible agent + mini-consensus before executing | nothing, unless escalated; it is in `decisions.md` |
| Not a decision | purely local naming, comment wording | the agent | nothing; no review |
| Product / scope | what to build, what to drop | present: the owner; away: full consensus (3amigos panel), every question | present: the question; away: `decisions.md` |

**Present mode:** product and scope questions go to the owner one at a time with
`AskUserQuestion`: the question with an R19 ID, options with their own IDs (`OP1`, `OP2`),
one marked recommended. When time allows (see Time below), main runs a 3amigos panel on the
question first, and the panel result is the recommendation shown with the options
("recommendation after 3amigos: OP2"). No time → main's own recommendation, marked as such. Act on
each answer at once. An answer that touches files a running writer owns goes to that writer
by `SendMessage`; otherwise launch an agent. Related follow-ups go to one agent.

**Away mode** (only when the owner passed `away`; never inferred from silence): every product
and scope question goes to a 3amigos panel; the run takes the result and continues. Every
decision goes into `decisions.md`.

**Review-bound panel** (R6, `reference/triage.md`, When the loop stops). Main runs it, in
both modes, as one item with options A (re-reviews 4–5) and B (TODO). `data.md` carries the
open FIX NOW findings, the new real defects per round and the fix-of-fix count. A trapped
mechanism goes to the trap, never to this panel. Majority A → rounds 4–5; B, `split`,
`no consensus` or no time → TODO, reason `review bound (3 re-reviews)`. After the 5th re-review
→ TODO, reason `review bound (5 re-reviews)`, no second panel. The owner is not asked; in
present mode main shows one line with the result.

**Settled:** a decision recorded in `decisions.md` is settled. Reopen it only on new evidence
or when the owner asks. Only `source: owner` or `scope: permanent` lines outlive the run
(`reference/queue.md`, decisions.md).

## Mini-consensus

One voter at a time, never a panel.

1. The agent writes each decision, its reason and the rejected alternatives.
2. With a box, the agent gets the absolute park time from its prompt. Before each opinion in
   the chain it recomputes the time left with `date`; each opinion's timeout is the smaller of
   240 s and the time left before park. No box: 240 s each.
3. The chain, one opinion at a time (mini-consensus prompt): Codex (effort `medium`,
   `command timeout 240`); if it fails, hits its usage limit or returns no valid
   `D<n>: AGREE|DISAGREE — reason` lines, a Fable agent (`captain:worker` with
   `model: "fable"`) told the same time budget; if Fable fails too, a `captain:worker` agent.
   An agent that cannot launch a nested agent says so at once in its report; the main session
   launches that opinion, stops it with `TaskStop` when the budget is over, and passes the
   answer back by `SendMessage`. A tool the config `tools` marks `false` is skipped, not tried.
4. With a box, no time left before park → defer the decision and the work that depends on it:
   commit what is independent, and report the decision as open (it goes to TODO per R18).
5. Several decisions may go in one batch.
6. AGREE → execute. DISAGREE → that decision escalates (below); the agent continues with the
   other parts.
7. The agent lists every decision in its report; the main session copies it into
   `decisions.md` (tier `mini`).

## Escalation

The writer records the question and the options in its report and goes on with the parts
that do not depend on it, using the safer, more reversible option meanwhile. The main session
runs a 3amigos panel (below); when the result comes, it goes back to the writer by
`SendMessage` to its `agentId`, and the writer applies it.

## Full consensus: a 3amigos panel

The voter mechanics are the `3amigos` skill's workflow (the three voters of the panel main
chooses per decision class, **Panel choice** below, a Fable stand-in for a missing voter, `panel.py`,
`tally.py`). Main invokes the
`3amigos:3amigos` skill and follows it, with these captain rules on top; the base directory
the skill shows on load is the `<skill dir>` passed to the runner.

**Mapping.** A captain question becomes a 3amigos triage task:

- each decision ID (`OV1`, `OV2`) is one item; several open decisions of one class go in one
  panel, decisions of different classes in one panel each;
- `verdict` is the option letter (`A`, `B`, `C`), the options listed per item in `data.md`;
- `reason` is one sentence;
- `tally.py --list items --id id --fields verdict --voters 3`;
- the majority from `tally.py` (`agree` or `majority`) decides;
- `split` or `insufficient`, an ID with no valid vote (absent from `tally.json`), no `ok`
  answer at all, or a winning letter or ID not in `data.md` → the safer, more reversible
  option, marked `no consensus`;
- a consensus never unlocks an R10 action.

**Panel choice.** For each panel main classifies the decision itself, with no question to the
owner, and passes the matching panel with `--panel` to every `panel.py` call of that panel
(the config runner's `--show-config` too):

- technical: design and architecture trade-offs, spec critique, code-related triage (bugs,
  review findings, the R6 review bound) → `opus,codex,gemini`;
- product and scope, UX, naming, creative proposals → `codex,gemini,fable`;
- anything else → the panel of the 3amigos `REFERENCE.md` "Choosing the panel" table for its
  task class; with no matching row, the default `codex,gemini,fable`.

The run's `--panel` wins over the project and the user config (3amigos precedence: run >
project > user > default), so a project config panel never overrides captain's choice.
`decisions.md` gets the class and the panel with the decision ID, one field:
`panel: technical — opus,codex,gemini`.
**Why:** 2026-11-18, the owner: captain decides by itself whether a decision is technical and
picks the panel automatically; the "Choosing the panel" table ranks Opus strongest for design,
architecture and code triage, which are captain's usual decisions.

**Who runs what.** One panel runner (`captain:runner`) per external voter on the panel,
launched in parallel, each running `panel.py --panel <the panel> --voters <that one voter>` (`--no-agy` per
**Tools** below, `--effort high`) and reporting when its voter ends, so a missing voter's
stand-in starts as soon as that voter ends. Exactly one of them, the one main marks
`config: yes` and launches first, runs `panel.py --show-config` first (DL2) and sends that line (`panel`,
`external`) to main at once by `SendMessage`, then goes on without waiting; its voter is
Gemini when Gemini is on the panel, else Codex when Codex is on it and not dropped, else none.
Main launches the other external runner and the Opus and Fable voters of the panel when that
line arrives, so all voters run in parallel: the Opus voter (`captain:deep`) only when `opus`
is on the panel, the Fable voter (`captain:worker` with `model: "fable"`) when `fable` is,
and any Fable stand-in, in the background; a subagent cannot nest them. A config error
(exit 2) is the config runner's final report and it runs nothing; main then takes the safer
option, as for a panel with no time. A panel without external voters needs no runner for
voters; the config runner still runs `--show-config` and the tally. The report on a
runner's own voter is its final report, the config runner's too. Each Opus or Fable voter
(and stand-in) runs `panel.py --check <its file> --require items=<N>` itself as its last step
and reports that status line; main starts a stand-in at once on `missing`. After all voters
end, main resumes the config runner by `SendMessage` to its `agentId` with the answer files
and their status lines; it runs the `--check` of an agent answer that has none and
`tally.py --voters 3`, and reports one line per item: ID, winning letter or `no consensus`,
kind, one reason. Main reads only the status lines and the
runners' reports, never the raw answers.

**Files.** Each panel gets its own dir `tmp/captain/<run>/amigos-<ID>/` (`<ID>` = the first
decision ID in it), passed as `--out`; `task.md` and `data.md` live there.

**Time.**

- No box (R11): no park, so every panel may start; the deadline of the external voters
  (Codex, Gemini) is 600 s, and the agent voters are told the same 600 s and stopped with `TaskStop` when it is over. The two
  rules below apply with a box.
- No panel starts when the time to park is shorter than its deadline, or when park − 5 min
  is under 60 s; the decision then takes the safer, more reversible option, marked
  `no consensus (no time)`.
- The deadline of every external voter is min(600 s, park − 5 min) (`--deadline`, the same
  for each runner's `panel.py` call); the agent voters are told the same budget and stopped with `TaskStop` when it is over.
- Writers continue with the safer option while a panel runs, and apply the result after it.

**Why:** 2026-11-18, the owner: the panel deadline went from 300 s to 600 s to guard against
temporary network issues. The mini-consensus 240 s and the Codex review `timeout 1200` stay.

**Tools.** Each external voter of the panel gets its runner, minus Codex when it is marked
`false` in the config `tools` or at its usage limit in this run; captain drops only Codex. A
dropped Codex → its Fable stand-in starts at once with the other voters, not after a
timeout. Gemini is a 3amigos voter; it uses agy first when the config `tools` has it:
`agy: false` adds `--no-agy` to the Gemini runner, and Gemini stays on the panel and runs on
its fallback. A
Gemini status line with `note` `agy usage limit` → `run.md` records `agy: usage limit` and
every later panel of the run gets `--no-agy`. With fallback `none` and agy off, Gemini ends
at once as `missing` with why `no-backend`, and its stand-in starts then, as for any missing
voter. No external voter left (a panel without Gemini, Codex dropped) → no voter runner; the
config runner runs `--show-config` and the tally. A Gemini runner that reports why `auth`,
`note` `fallback auth failed` or an agy login failure carries the repair advice; main passes
it to the owner.
**Why:** 2026-11-18: the panel has three providers now (Codex, Gemini, Fable), and an
exhausted agy quota must not slow every later panel.

**Result.** `decisions.md` gets per decision ID: the options, the votes (`agree`,
`majority` or `no consensus`), the reason, the panel dir, the `panel:` field, and for a judged-complex problem
why main sent it to a panel.

## Fallback without 3amigos

The `3amigos` skill is not installed → main puts the full consensus prompt (lettered options,
one `Vote: <letter> — <reason>` line) in parallel to Codex (effort `high`,
`command timeout 300`) through a `captain:runner`, a Fable voter and a `captain:deep`
voter, and agy when the config `tools` has it. Same time rules as above.
At least 2 valid votes; a missing voter counts as missing. The majority wins; a tie or fewer
than 2 votes → the safer, more reversible option, `no consensus`.

## Cost

A panel takes up to the external voters' deadline plus the tally, about 11 min. In a 30-min box it is for
the complex tiers, the review-bound panel and away-mode product questions only; everything
else is mini-consensus.
