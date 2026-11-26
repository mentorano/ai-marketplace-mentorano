---
name: 3amigos
description: Use when the owner says "3amigos", asks to convene the amigos, or asks for independent second opinions on ideas, a shortlist, a triage of many items (keep/cut/assign) or a creative proposal. Convenes a one-round panel of three independent experts from a pool of four (Codex, Gemini, a Claude Opus agent and a Claude Fable agent; the default panel is Codex, Gemini and Fable) that each answer the same brainstorm or triage task as JSON, then one non-voting Opus synthesizer merges the answers by majority and agreement. A voter that fails or misses its deadline is replaced by a Fable stand-in with its own framing instead of being waited for. Captain uses it for its complex decisions: full consensus and away-mode product questions. Not for code review (one Codex review covers that).
---

# 3amigos: a panel for ideas and triage

`<skill dir>` below = the base directory shown when this skill loads (a plugin cache path, or `~/.claude/skills/3amigos`).

Three independent voters get the same task and the same data. The pool has four voters:
Codex (`gpt-6-astra`), Gemini (`gemini-4-carbon`, then `gemini-4-argon`), a Claude Opus agent
and a Claude Fable agent. The panel is always three of them. The default panel is Codex,
Gemini and Fable: three providers. Each voter answers once in
JSON. One synthesizer then merges the answers, and the owner gets proposals with their
authorship and level of agreement. The panel never deletes or overwrites anything itself:
everything it produces is a proposal.

## Budget (fixed)

- One round: at most 3 voters plus 1 synthesizer per call. A second round only when the owner asks.
- Codex gets at most one retry, all within its deadline (`--deadline`, default 600 s).
  No retry after the deadline or a usage limit (`panel.py` enforces this).
- Gemini has no outer retry: its backend chain is the retry. It tries `agy` and the fallback,
  with the preferred and the second model, all within the same deadline.
- A missing voter is replaced once, by a Fable stand-in. Never wait for or restart a voter that
  missed its deadline. A stand-in that fails too is not replaced: the panel goes on with fewer answers.
- Never loop "until they agree". Disagreement is a result, and it goes to the owner.

## Workflow

1. **The panel.** Run `python3 <skill dir>/scripts/panel.py --show-config`. It prints the
   effective config as one JSON line: the panel, its external voters, the Gemini settings,
   and where each value came from. It never prints a key or a token.
   - The panel comes from, in this order: the `--panel` the caller names for this run, the
     project config, the user config, the default (`codex`, `gemini`, `fable`).
   - The caller may name a panel for this run with `--panel a,b,c`: three different names
     from `codex`, `gemini`, `opus`, `fable`. Pass the same `--panel` to every `panel.py`
     call of this run.
   - Which voters fit which task: REFERENCE.md "Choosing the panel".
   - The `3amigos:3amigos-setup` skill writes the config. There is no config when the `files`
     entry of that line names no file that exists.
     With no config the panel runs with the defaults, and the report adds one line that names
     the setup skill.
   - This step catches a bad panel or a config error before any voter starts. A `--voters`
     list, when given, holds only names from the `external` of that line.
   - `panel.py` exits 2 on a bad panel, a bad `--voters` or a config error: the panel does not
     run, no voter or stand-in starts, and the report gives the owner the stderr line verbatim
     and names the `3amigos:3amigos-setup` skill to repair a config.
2. **Task file.** Write `task.md` in the owner's language:
   - the context (product, audience, goal);
   - what each voter decides;
   - the quality bar ("be strict", "concrete, not generic");
   - **the exact JSON schema with counts**, for example "items: exactly 20 items".
   Templates are in [REFERENCE.md](REFERENCE.md).
3. **Data file.** Write `data.md`: everything the voters need, as compact text. It is inlined
   into the prompt. Never ask a voter to read files.
   Then self-review both files with the skill `utils:self-review` (not in the Skill list → the
   same steps by hand), reading them as a voter who sees nothing else: every item and option
   is in `data.md`, the schema counts in `task.md` equal the items, nothing refers to this
   conversation. A voter cannot ask back.
4. **Run the three voters of the panel in parallel, in one message:**
   - The external voters on the panel (Codex, Gemini), as one background Bash command:
     `python3 <skill dir>/scripts/panel.py --task task.md --input data.md --out <dir> --require <key>=<N>`.
     No `--voters` is needed: it defaults to the external voters of the panel. Codex and
     Gemini run in parallel inside this one call, each in its own empty work dir, with the
     same deadline (`--deadline`, default 600 s). Codex runs in `<dir>/work-codex/`,
     Gemini in `<dir>/work-gemini/`.
     Raise `--deadline` only for large lists (see REFERENCE.md).
   - `panel.py` prints one status line per voter. The Gemini line also carries `backend`
     (`agy`, `vertex` or `key`), `model` (the API model name, never the `agy` id) and `note`
     (`""` by default).
   - Opus, when it is on the panel: an `Agent` with `model: "opus"`. It reads `task.md` and
     `data.md` and writes `<dir>/opus.json`. Its prompt says: read only these two files;
     never list or read any other file in `<dir>`.
   - Fable, when it is on the panel: an `Agent` with `model: "fable"`, with the same prompt
     rules and the plain task, no extra framing. It writes `<dir>/fable.json`.
   - Check each agent's answer with the same contract:
     `python3 <skill dir>/scripts/panel.py --check <dir>/<voter>.json --require <key>=<N>`
     for each Opus or Fable voter on the panel. It prints the same status line as `panel.py`
     and runs no voter.
5. **A voter is missing** (`panel.py` prints `"status":"missing"`: a failure, a usage limit, a
   bad answer, or `"why":"deadline"` when Codex or Gemini did not answer in time; or an Opus
   or Fable agent fails or its `--check` says `missing`): as soon as that arrives, start a
   stand-in `Agent` with `model: "fable"`, with the same task, contract and prompt rules. Do
   not wait for the other voters first. Reserve the stand-in's file name when you start the
   Agent, so two stand-ins never share a file.
   - When Fable is on the panel, each stand-in, whoever it replaces, writes the next free name
     of `fable2.json`, `fable3.json`, `fable4.json`. The regular Fable already sits on the
     panel, so each stand-in gets its own framing: the first argues from risk and
     reversibility, the second from impact and delight, the third from cost and effort.
   - When Fable is not on the panel, the first stand-in is the plain Fable task without
     framing and writes `fable.json`. Later stand-ins write `fable2.json` … with the framings
     above, in that order.
   - The panel still has 3 answers. The stand-in's file gets the same `--check`.
   Tell the owner in one line which voter was replaced and why.
6. **Merge:**
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
7. **Deliver:**
   - write the proposals where the owner works (board, document);
   - each proposal carries its authorship and agreement level;
   - nothing gets deleted;
   - report to the owner in at most 10 lines: the counts, the strongest proposals, where the
     voters disagreed, which voters were missing, and who replaced them;
   - before that report, self-review the written proposals with `utils:self-review` against
     the tally or the synthesizer summary: each count, author and agreement level equals its
     source. It is no vote and changes no verdict.
8. **Report rules for Gemini and the config:**
   - Say which backend and which model answered for Gemini (`backend`, `model` of its line).
   - `note` `fallback auth failed`, or `missing` with why `auth`: the advice follows the
     effective `gemini.fallback` shown by `panel.py --show-config`.
     - Fallback `vertex`: tell the owner to log in again with these two commands, each in its
       own code block:

       ```
       gcloud auth login
       ```

       ```
       gcloud auth application-default login
       ```

     - Fallback `key`: tell the owner to set the variable named by `key_env`, or to fix the
       file named by `key_dotenv`. Never print the key's value.
   - `note` `agy usage limit`: say that `agy` hit its usage limit in this run.
   - Gemini `missing` with why `exit <n>`, and `<dir>/gemini.log` names "Eligibility check
     failed": say "agy is not logged in: open agy once and log in".
   - Why `no-backend`: no Gemini backend is set up; name the `3amigos:3amigos-setup` skill.
   - No config: add one line that names the `3amigos:3amigos-setup` skill.

## Called from captain

A captain run uses this panel for its full consensus (captain `reference/consensus.md`).
Captain's main session runs the workflow above as a triage task, with these settings:

- `--out` is the run dir `tmp/captain/<run>/amigos-<ID>/`, one per panel.
- Captain picks the panel itself, per decision class, with no question to the owner, and
  passes it with `--panel` to every `panel.py` call of that panel (`--show-config` too):
  technical (design, architecture, spec critique, code-related triage) → `opus,codex,gemini`;
  product and scope, UX, naming, creative → `codex,gemini,fable`; anything else → the row of
  "Choosing the panel" in `REFERENCE.md`, else the default. The run's `--panel` wins over
  the project and the user config.
- The park time caps the deadline: the external voters get min(600 s, park − 5 min); no
  panel starts when park is nearer than that or park − 5 min is under 60 s.
- The captain config `tools` is honoured: Codex marked `false`, or at its usage limit in the
  run, is not started, and the Fable stand-in starts at once. Each other external voter runs
  in its own `panel.py --voters <that voter>` call, one captain runner each; with none left,
  no voter call runs.
- Captain passes `--no-agy` when its config `tools` has `agy: false`, and for the rest of the
  run after a Gemini status line carried `"note": "agy usage limit"`. Gemini stays on the
  panel: with fallback `none` it ends at once as `missing` with why `no-backend`, and its
  stand-in then starts.
- Each item is a decision ID, `verdict` the option letter, `tally.py --voters 3`; a `split`
  or `insufficient` item takes the safer, more reversible option, marked `no consensus`.

## Rules

- Voters are independent. Never show one voter another voter's answer in the same round.
  The answers share `<dir>`, so no voter may list or read files there beyond its inputs.
- Raw voter output stays in `<dir>`. The main thread reads only `panel.py`'s status lines and
  the summary from `tally.py` or the synthesizer, never whole answers.
- Panel data holds no secrets. The prompt of an external voter is visible in the local
  process list while it runs (`agy -p` takes it as an argument).
- Write the outputs in the owner's language.
