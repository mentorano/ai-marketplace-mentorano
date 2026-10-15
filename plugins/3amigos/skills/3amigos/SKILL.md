---
name: 3amigos
description: Use when the owner says "3amigos", asks to convene the amigos, or asks for independent second opinions on ideas, a shortlist, a triage of many items (keep/cut/assign) or a creative proposal. Convenes a one-round panel of three independent experts (Codex, a Claude Opus agent and a Claude Fable agent) that each answer the same brainstorm or triage task as JSON, then one non-voting Opus synthesizer merges the answers by majority and agreement. A voter that fails or misses its deadline is replaced by a second Fable voter with its own framing instead of being waited for. Captain uses it for its complex decisions: full consensus and away-mode product questions. Not for code review (one Codex review covers that).
---

# 3amigos: a panel for ideas and triage

`<skill dir>` below = the base directory shown when this skill loads (a plugin cache path, or `~/.claude/skills/3amigos`).

Three independent voters get the same task and the same data: Codex (`gpt-6-astra`), a
Claude Opus agent and a Claude Fable agent. Each voter answers once in
JSON. One synthesizer then merges the answers, and the owner gets proposals with their
authorship and level of agreement. The panel never deletes or overwrites anything itself:
everything it produces is a proposal.

## Budget (fixed)

- One round: at most 3 voters plus 1 synthesizer per call. A second round only when the owner asks.
- Codex gets at most one retry, all within its deadline (`--deadline`, default 300 s).
  No retry after the deadline or a usage limit (`panel.py` enforces this).
- A missing voter is replaced once, by a Fable stand-in. Never wait for or restart a voter that
  missed its deadline. A stand-in that fails too is not replaced: the panel goes on with fewer answers.
- Never loop "until they agree". Disagreement is a result, and it goes to the owner.

## Workflow

1. **Task file.** Write `task.md` in the owner's language:
   - the context (product, audience, goal);
   - what each voter decides;
   - the quality bar ("be strict", "concrete, not generic");
   - **the exact JSON schema with counts**, for example "items: exactly 20 items".
   Templates are in [REFERENCE.md](REFERENCE.md).
2. **Data file.** Write `data.md`: everything the voters need, as compact text. It is inlined
   into the prompt. Never ask a voter to read files.
3. **Run all three in parallel, in one message:**
   - Codex, as a background Bash command:
     `python3 <skill dir>/scripts/panel.py --task task.md --input data.md --out <dir> --voters codex --require <key>=<N>`.
     Raise `--deadline` only for large lists (see REFERENCE.md). Codex runs in its own empty
     work dir, `<dir>/work-codex/`.
   - Opus: an `Agent` with `model: "opus"`. It reads `task.md` and `data.md` and writes
     `<dir>/opus.json`. Its prompt says: read only these two files; never list or read
     any other file in `<dir>`.
   - Fable: an `Agent` with `model: "fable"`, with the same prompt rules and the plain task,
     no extra framing. It writes `<dir>/fable.json`.
   - Check each agent's answer with the same contract:
     `python3 <skill dir>/scripts/panel.py --check <dir>/opus.json --require <key>=<N>`
     (and the same for `fable.json`). It prints the same status line as Codex and runs no voter.
4. **A voter is missing** (`panel.py` prints `"status":"missing"`: a failure, a usage limit, a
   bad answer, or `"why":"deadline"` when Codex did not answer in time; or an Opus or Fable
   agent fails or its `--check` says `missing`): as soon as that arrives, start a stand-in
   `Agent` with `model: "fable"`, with the same task, contract and prompt rules. Do not wait
   for the other voters first. Each stand-in, whoever it replaces, writes the next free name
   of `fable2.json`, `fable3.json`, `fable4.json`; reserve that name when you start the Agent,
   so two stand-ins never share a file. The regular Fable already sits on the panel, so each
   stand-in gets its own framing: the first argues from risk and reversibility, the second
   from impact and delight, the third from cost and effort. The panel still has 3 answers. Its file gets the same `--check`.
   Tell the owner in one line which voter was replaced and why.
5. **Merge:**
   - **Triage mode** (each item gets a verdict): run
     `python3 <skill dir>/scripts/tally.py --list <key> --id id --fields <f1,f2> --voters 3 <files>`.
     `<files>` is an explicit list: only the files whose status line said `"status":"ok"`
     (from a run or from `--check`). Never a glob: stale files and `tally.json` would be fed
     in. `--voters 3` is the expected panel size, so missing voters cannot manufacture consensus.
     The result splits the items into `agree`, `majority`, `split` and `insufficient`; items a
     voter sent with a duplicate id or a missing field are counted as `invalid`.
     More files than `--voters`, or two files with one voter name (`a/codex.json` and
     `b/codex.json`), is an error: exit 2, nothing written. A file that is not JSON or lacks
     the `<key>` list is listed under `skipped` with the reason and counts as a missing voter.
     Ids compare as strings (`12` == `"12"`); string values ignore case and outer spaces.
     The FIRST field in `--fields` is the verdict. It alone decides `agree`, `majority`,
     `split` or `insufficient`; a tie for the top is `split`. Each other field is compared
     only among the voters who share the winning verdict. `details.<field>` gives its
     `value` and `kind` (`agree`, `majority` or `split`); a split field is `null` in
     `decision`. So `agree` means agreement on the verdict, not on every field: check
     `details` before acting on a secondary field such as an assignee.
     The summary's `missing` lists, per voter, the ids other voters voted on that this
     voter did not (or sent invalid). Name those gaps in the report.
   - **Ideas mode** (free proposals): one Opus synthesizer (it does not vote) groups similar
     ideas. It reads only blind labels, so it never learns who wrote what. Copy the ok
     answers, in a random order, to `<dir>/blind/A.json`, `B.json`, `C.json`, and keep the
     mapping in `<dir>/labels.json`. The synthesizer reads only `<dir>/blind/`. For each
     item, it picks the best version or merges the best parts, and keeps the strongest
     rejected alternative with its label. After the merge, map the labels back to authors.
     Ideas that two voters proposed independently are the strongest signal; mark them with
     the real authors from `labels.json`, for example "Codex + Opus (independently)". A stand-in is credited as Fable (stand-in), never as the
     voter it replaced.
6. **Deliver:**
   - write the proposals where the owner works (board, document);
   - each proposal carries its authorship and agreement level;
   - nothing gets deleted;
   - report to the owner in at most 10 lines: the counts, the strongest proposals, where the
     voters disagreed, which voters were missing, and who replaced them.

## Called from captain

A captain run uses this panel for its full consensus (captain `reference/consensus.md`).
Captain's main session runs the workflow above as a triage task, with these settings:

- `--out` is the run dir `tmp/captain/<run>/amigos-<ID>/`, one per panel.
- The park time caps the deadline: Codex gets min(300 s, park − 5 min); no panel starts
  when park is nearer than that or park − 5 min is under 60 s.
- The captain config `tools` is honoured: Codex marked `false`, or at its usage limit in the
  run, is not started, and the Fable stand-in starts at once.
- Each item is a decision ID, `verdict` the option letter, `tally.py --voters 3`; a `split`
  or `insufficient` item takes the safer, more reversible option, marked `no consensus`.

## Rules

- Voters are independent. Never show one voter another voter's answer in the same round.
  The answers share `<dir>`, so no voter may list or read files there beyond its inputs.
- Raw voter output stays in `<dir>`. The main thread reads only `panel.py`'s status lines and
  the summary from `tally.py` or the synthesizer, never whole answers.
- Write the outputs in the owner's language.
