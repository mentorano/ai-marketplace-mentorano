# consensus - decision tiers and mechanics (R9)

When the config `tools` has it, Codex reviews specs and code (R7), votes in every 3amigos
panel and gives the first mini-consensus opinion. Use it freely; the only limit is the R7
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

**Settled:** a decision recorded in `decisions.md` is settled. Reopen it only on new evidence
or when the owner asks.

## Mini-consensus

One voter at a time, never a panel.

1. The agent writes each decision, its reason and the rejected alternatives.
2. The agent gets the absolute park time from its prompt. Before each opinion in the chain it
   recomputes the time left with `date`; each opinion's timeout is the smaller of 240 s and
   the time left before park.
3. The chain, one opinion at a time (mini-consensus prompt): Codex (effort `medium`,
   `command timeout 240`); if it fails, hits its usage limit or returns no valid
   `D<n>: AGREE|DISAGREE — reason` lines, a Fable agent (`captain:worker` with
   `model: "fable"`) told the same time budget; if Fable fails too, a `captain:worker` agent.
   An agent that cannot launch a nested agent says so at once in its report; the main session
   launches that opinion, stops it with `TaskStop` when the budget is over, and passes the
   answer back by `SendMessage`. A tool the config `tools` marks `false` is skipped, not tried.
4. No time left before park → defer the decision and the work that depends on it: commit what
   is independent, and report the decision as open (it goes to TODO per R18).
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

The voter mechanics are the `3amigos` skill's workflow (Codex, an Opus and a Fable voter, a
Fable stand-in for a missing voter, `panel.py`, `tally.py`). Main invokes the
`3amigos:3amigos` skill and follows it, with these captain rules on top; the base directory
the skill shows on load is the `<skill dir>` passed to the runner.

**Mapping.** A captain question becomes a 3amigos triage task:

- each decision ID (`OV1`, `OV2`) is one item; several open decisions go in one panel;
- `verdict` is the option letter (`A`, `B`, `C`), the options listed per item in `data.md`;
- `reason` is one sentence;
- `tally.py --list items --id id --fields verdict --voters 3`;
- the majority from `tally.py` (`agree` or `majority`) decides;
- `split` or `insufficient`, an ID with no valid vote (absent from `tally.json`), no `ok`
  answer at all, or a winning letter or ID not in `data.md` → the safer, more reversible
  option, marked `no consensus`;
- a consensus never unlocks an R10 action.

**Who runs what.** Main runs the panel: it launches the Opus voter (`captain:deep`) and the
Fable voter (`captain:worker` with `model: "fable"`), and any Fable stand-in, in the
background; a subagent cannot nest them. One `captain:runner` runs `panel.py` for the Codex
voter (`--voters codex --effort high`), the `--check` of each agent answer, and `tally.py`,
and reports one line per item: ID, winning letter or `no consensus`, kind, one reason. Main
reads only the status lines and that report, never the raw answers.

**Files.** Each panel gets its own dir `tmp/captain/<run>/amigos-<ID>/` (`<ID>` = the first
decision ID in it), passed as `--out`; `task.md` and `data.md` live there.

**Time.**

- No panel starts when the time to park is shorter than its deadline, or when park − 5 min
  is under 60 s; the decision then takes the safer, more reversible option, marked
  `no consensus (no time)`.
- The Codex deadline is min(300 s, park − 5 min) (`--deadline`); the Opus and Fable voters
  are told the same budget and stopped with `TaskStop` when it is over.
- Writers continue with the safer option while a panel runs, and apply the result after it.

**Tools.** Codex marked `false` in the config `tools`, or at its usage limit in this run →
the second Fable voter (the stand-in) starts at once with the other voters, not after a
timeout. agy is not a 3amigos voter.

**Result.** `decisions.md` gets per decision ID: the options, the votes (`agree`,
`majority` or `no consensus`), the reason, the panel dir, and for a judged-complex problem
why main sent it to a panel.

## Fallback without 3amigos

The `3amigos` skill is not installed → main puts the full consensus prompt (lettered options,
one `Vote: <letter> — <reason>` line) in parallel to Codex (effort `high`,
`command timeout 300`) through a `captain:runner`, a Fable voter and a `captain:deep`
voter, and agy when the config `tools` has it. Same time rules as above.
At least 2 valid votes; a missing voter counts as missing. The majority wins; a tie or fewer
than 2 votes → the safer, more reversible option, `no consensus`.

## Cost

A panel takes up to the Codex deadline plus the tally, about 6 min. In a 30-min box it is for
the complex tiers and away-mode product questions only; everything else is mini-consensus.
