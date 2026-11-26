# 3amigos: reference

## Tool traps

The Codex traps below were verified on 05.10.2026 with codex-cli 0.153.

- **Inline all of the data into the prompt.** `panel.py` does this, so the voter never has
  to read files itself.
- **The model is pinned:** Codex `gpt-6-astra` (`AMIGOS_CODEX_MODEL`). Change it deliberately, never by a CLI default drifting.
- **Codex `-i` swallows the arguments that follow it.** `codex --search exec -i img.png "text"` treats
  the text as a second image path. Pass the prompt on stdin with `-` instead:
  `codex --search exec ... -i img.png - < prompt.md`.
- **Web search is on.** `panel.py` starts Codex as `codex --search exec …`: the global flag
  goes before `exec`. `agy` may search too (no flag turns it off); it opens a page only with
  the `read_url(*)` rule. The Vertex or key fallback sends no search tool. The `--deadline`
  still caps both external voters. **Why:** 26.11.2026: the owner allowed web for every voter.
- **macOS has no `timeout` command.** `panel.py` kills the whole process group itself. In
  shell, use `perl -e 'alarm 900; exec @ARGV' cmd`.
- **Codex `-o FILE`** writes only the final answer, without the log, so take JSON from there.
- **Long outputs take longer.** For lists of more than about 20 rich items, either give Codex
  `--deadline 900`, or split the list into chunks of 10 and merge the chunks with `tally.py`
  or the synthesizer. Otherwise Codex may miss the default `--deadline 600` and be replaced
  by a Fable stand-in.
- **Images:** Codex has `image_generation`. Use
  `codex --search exec --skip-git-repo-check -s workspace-write -C <dir> -i style-ref.png - < prompt`,
  and tell it in the prompt to save the result as `<name>.png` in the current directory.
  Each image takes about 1 minute and about 25k tokens. Running 3 in parallel works.

### Gemini: `agy` and REST

These were verified on 2026-11-18 with agy 1.5.11.

- **The models are pinned:** Gemini prefers `gemini-4-carbon`, then `gemini-4-argon`, with
  effort `high`. They are the config defaults in `amigos_config.py`, and the config overrides them. Change them
  deliberately, together with "Choosing the panel".
- **`agy` has no Carbon.** `agy models` lists no Carbon id. So a Gemini vote normally takes
  the fallback (Vertex or key) with Carbon. When the fallback has no access to Carbon, the
  voter drops to Argon, `agy` first.
- **The chain is the retry.** One answer walks `agy` (preferred model), the fallback
  (preferred), `agy` (second model), the fallback (second), all within one `--deadline`. A hop
  gets 60 % of the time left when a later hop is still possible, otherwise all of it.
- **The call:** `agy -p <prompt> --model <agy id> --sandbox --print-timeout <budget>s --output-format json`,
  run in the voter's empty work dir.
- **The `agy` id comes from `agy models`:** the id that starts with the model name and ends
  with the effort, for example `gemini-4-argon-high`. An id is never guessed.
- **`-p` does not read stdin.** The prompt is one argument. A prompt over 200 KB skips `agy`
  and goes to the fallback.
- **The prompt is visible in the process list** while `agy` runs. Panel data must hold no
  secrets, as for any external voter.
- **stdout is one JSON envelope:** `{"status", "response", "error", "finished_reason"}`. The
  answer is taken from `response`, never from raw stdout: the envelope is the largest JSON
  object there.
- **Failures are fast or exact.** An unknown model fails in under a second: exit 1, "invalid
  model selection". A reached `--print-timeout` is exit 3 with
  `AGY_ERROR: {…"status":"DEADLINE_EXCEEDED"…}` on stderr. The quota error text is not
  observed yet; any `agy` failure goes to the fallback.
- **`agy` is slow and varies.** Two runs of one tiny prompt took 11 s and 121 s. One tiny call
  used about 11k input tokens.
- **Vertex:** REST `generateContent` on `aiplatform.googleapis.com` (location `global`) or
  `aiplatform.<location>.rep.googleapis.com`. The token comes from
  `gcloud auth application-default print-access-token`, then `gcloud auth print-access-token`.
- **Key:** REST `generateContent` on `generativelanguage.googleapis.com` with the
  `x-goog-api-key` header. The key comes from the variable named by `key_env`, then from the
  file named by `key_dotenv`. This path is not called for real yet.
- **The token and the key go only into a request header.** Never into a command line, a
  config, a log or a file under `<out>`.
- **An expired `gcloud` login keeps the ADC file.** Every Vertex call then answers HTTP 401,
  and the voter goes on to `agy` with the second model. The report advice follows the
  effective `gemini.fallback` (SKILL.md, report rules): for `vertex`, `gcloud auth login`
  and `gcloud auth application-default login`; for `key`, the variable named by `key_env` or
  the file named by `key_dotenv`, never the key's value.
- **Send `thinkingConfig.thinkingLevel`, never `thinking_budget`.** Carbon answers HTTP 400
  to `thinking_budget`.
- **The answer text** is in `candidates[0].content.parts[].text`. A part also carries a long
  `thoughtSignature`; the voter ignores it.
- **REST is slow sometimes too.** On a normal cloud project Carbon and Argon both answered on
  `global` and `eu`. A tiny prompt took 6–8 s in three of four calls and 81 s in one.

## Choosing the panel

Research of 2026-11-18. Marks: [P] = read on a primary page, [S] = secondary or vendor claim,
[A] = assumption. The default panel stays `codex`, `gemini`, `fable`: Opus does the main work
in most sessions, so it is not a default voter. The table says when to swap a voter in.

| Task class | Panel | Why |
|---|---|---|
| Design, architecture, spec critique | `opus` · `codex` · `gemini` | Opus leads the AA Intelligence Index v5 (27.10.2026) and HLE with tools [P]; worth swapping in for Fable here |
| Code-related triage (bugs, findings) | `opus` · `codex` · `gemini` | Opus leads FrontierCode 2.0 and Terminal-Bench 4.0 [P, vendor]; Fable 5.2 instead of Gemini only when raw code strength beats diversity [S] |
| Product, UX, naming, creative | default | Gemini leads human preference on Arena (11.11.2026) [P]; Fable strong at creative work [S] |
| Writing in Bulgarian | `gemini` · `opus` · `fable` | No current eval of these models in Bulgarian found [A]; a native speaker checks the text |
| Factual, current events | default | Codex, `agy` and the Claude agents may search the web; the Gemini fallback (Vertex or key) cannot, and Gemini usually answers through it [A] |
| Long inputs | default | Fable 5.2 and Gemini have 1M token windows [S]; no independent cross-provider eval [A] |
| Math, estimates | default | Carbon and Fable 5.2 lead MathArena (13.11.2026) [S] |

- Why three providers: model errors overlap more as models grow stronger, and a judge model
  prefers models like itself (Goel et al. 2025, arXiv 2502.04313 [P]; measured on
  classification, not free text). So keep at least one voter from each provider when the
  task allows it.
- Score gaps of a few points are inside the noise; the table is a default, not a rule.

Review this table when a provider releases a new model; the model ids in the config defaults (`amigos_config.py`) and in the effective config change with it.

## Config

- Two files: the user config `~/.claude/3amigos/config.json` and the project config
  `<main checkout>/.claude/3amigos.local.json` (local, not committed).
- Precedence: the run's `--panel`, then the project config, then the user config, then the
  defaults. A project value wins over a user value, key by key.
- A linked worktree reads the main checkout's project config.
- Only `panel.py` reads and merges the configs. `panel.py --show-config` prints the effective
  config as one JSON line, with the source of each value and never a key or a token.
- The `3amigos:3amigos-setup` skill writes both files. Without a config the panel runs with
  the defaults: the default panel, `agy` only, fallback `none`.

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
(SKILL.md, "Called from captain"). Since 0.6.0 Gemini is a voter, the default panel is
Codex, Gemini and Fable, and the caller chooses the panel.
