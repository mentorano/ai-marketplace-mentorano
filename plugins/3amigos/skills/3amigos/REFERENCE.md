# 3amigos: reference

## Tool traps

All of these were verified on 05.10.2026 with codex-cli 0.153.

- **Inline all of the data into the prompt.** `panel.py` does this, so the voter never has
  to read files itself.
- **The model is pinned:** Codex `gpt-6-astra` (`AMIGOS_CODEX_MODEL`). Change it deliberately, never by a CLI default drifting.
- **Codex `-i` swallows the arguments that follow it.** `codex exec -i img.png "text"` treats
  the text as a second image path. Pass the prompt on stdin with `-` instead:
  `codex exec ... -i img.png - < prompt.md`.
- **macOS has no `timeout` command.** `panel.py` kills the whole process group itself. In
  shell, use `perl -e 'alarm 900; exec @ARGV' cmd`.
- **Codex `-o FILE`** writes only the final answer, without the log, so take JSON from there.
- **Long outputs take longer.** For lists of more than about 20 rich items, either give Codex
  `--deadline 900`, or split the list into chunks of 10 and merge the chunks with `tally.py`
  or the synthesizer. Otherwise Codex may miss the default `--deadline 300` and be replaced
  by a Fable stand-in.
- **Images:** Codex has `image_generation`. Use
  `codex exec --skip-git-repo-check -s workspace-write -C <dir> -i style-ref.png - < prompt`,
  and tell it in the prompt to save the result as `<name>.png` in the current directory.
  Each image takes about 1 minute and about 25k tokens. Running 3 in parallel works.

## Task template: triage

Write the task in the owner's language. `panel.py` appends the data under an
`=== DATA ===` header.

```
You are one of three independent experts (<role>) voting on <product/goal>.
Below, DATA holds <N> items and <the frame they are sorted into>.
For EVERY item decide: "<option1>" | "<option2>" | "<option3>" (+ field <x> for <option1>).
Be strict: <expectation, e.g. a large share is cut>.
Write in the user's language. Return ONLY valid JSON, no markdown:
{"items":[{"id":"...","verdict":"...","<x>":"... or null","reason":"one sentence"}]}
items must contain exactly <N> entries.
```

Run it with `--require items=<N>`, then `tally.py --list items --id id --fields verdict,<x>`.
`verdict` must be the first field: it alone decides the item's kind.

## Task template: ideas

```
You are one of three independent experts (<roles>). Context: <product, audience, goal, deadline>.
Task: <what to propose>, with requirements: <concrete, compelling, realistic, ...>.
For each <object> in DATA give ONE proposal. / Propose up to <K> new <things>.
Write in the user's language. Return ONLY valid JSON matching the schema: {"<key>":[{...fields...}]}
<key> must contain exactly <N> entries.
```

The synthesizer never sees who wrote an answer. The main thread copies the ok answers, in a
random order, to `<dir>/blind/A.json`, `B.json`, `C.json` and writes the mapping to
`<dir>/labels.json`, for example `{"A": "codex", "B": "opus", "C": "fable"}`. The synthesizer's
prompt names only the files in `<dir>/blind/`, says not to read any other file, and asks for:

- one merged proposal per object;
- `basis`: which label or labels the proposal came from;
- `alternatives`: the strongest rejected alternative, with its label;
- a `summary` of 5–8 lines: the strongest proposals and where the answers disagreed.

After the merge, the main thread replaces the labels with the authors from `labels.json`.

## Origin

The panel grew out of captain's earlier full consensus (captain `reference/consensus.md`): parallel
voters, a runner that does not vote, a stand-in voter when a voter fails, and failures
counted as missing votes. Here the stand-in is Fable, and a tool that misses its deadline
counts as failed, so the panel never waits on a slow tool. Since 3amigos 0.5.0 captain runs
its full consensus through this panel: its lettered options become the triage `verdict`
(SKILL.md, "Called from captain").
