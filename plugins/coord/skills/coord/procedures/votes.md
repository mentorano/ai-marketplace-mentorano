# Votes (Codex, Opus, Fable)

Coord's own architecture/contract rulings, and product questions while the owner is away
(`decisions-and-owner.md`), are decided by a vote of three. Mechanical matters (merge order,
lane assignment) coord decides alone. Never voted: destructive/outward actions and anything
irreversible - they wait for the owner on the "Waiting on you" list. Code-review findings are not voted.

## Ballot (write it to `<config handoff dir>/votes/<GLn>.md`)
```
<one-paragraph question>. Context (<= 15 lines): <facts, file:line, constraints, what is built>.
Options:
A) <option> - <consequence>
B) <option> - <consequence>
Reversibility: <which option is easier to undo>
Answer with exactly one first line: `Vote: <letter> — <reason in one sentence>`.
```

## Run a round (8 min max)
1. [ ] In ONE message: a background Bash call
   `python3 <skill dir>/scripts/vote.py codex <ballot> <votes dir>/<GLn> --timeout 300 --cwd <primary checkout>`,
   an Opus voter `Agent(model: "opus", description: "Vote GLn (Opus)")` and a Fable voter
   `Agent(model: "fable", description: "Vote GLn (Fable)")`. Each agent's prompt = the ballot + "you are
   one of three independent voters; read the files named if needed; you have 5 minutes; answer with
   the Vote line only".
2. [ ] Wait for all three (never poll), at most 5 minutes after the start: an agent still running then
   is stopped with `TaskStop` and counts as missing. vote.py prints one JSON line for Codex (`status`, `answer`, `reason`, `why`).
   An agent's answer counts as `voted` only when its first line is a valid `Vote:` line.
3. [ ] Count only `status: voted` answers with a letter among the options:
   - majority wins;
   - two voters that split, or no majority: the option marked easier to reverse wins, marked `contested`;
   - only one vote: it decides, marked `single voter`;
   - none: coord's safe default, marked `no vote`.
4. [ ] Codex `missing` with `why` = `missing-binary`, `login` or `usage-limit`: one line to the owner, once per session. No retry.

## Record
- [ ] In the plan, "for ratification": `GLn (date, voted): <question> -> <winner> [contested|single voter|no vote]; Codex <X — reason>, Opus <X — reason>, Fable <X — reason>`.
- [ ] Tell affected lanes with ANSWER naming GLn ("voted, for the owner's ratification").
- [ ] A settled GLn reopens only on new evidence or the owner's word.

## Cost
A round = 1 CLI call + 1 Opus agent + 1 Fable agent. Expect 3-10 rounds per scope. The owner
accepted this (29 Sep; Fable replaced Grok on 12 Oct); do not add other recurring vote stages
without telling the owner.
