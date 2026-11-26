---
name: 3amigos-setup
description: Use when the 3amigos panel report says there is no config, or the user asks to set up or change the 3amigos panel or its Gemini voter, e.g. "/3amigos:3amigos-setup", "set up 3amigos", "change the 3amigos panel", "configure the Gemini fallback". Detects agy, a working gcloud login and a Gemini key variable, looks for what the project already uses for Gemini, asks for the default panel and the Gemini fallback (vertex, key or none), and writes the per-user ~/.claude/3amigos/config.json and the per-project .claude/3amigos.local.json, then tests each chosen scope with one tiny panel run, in which Codex may try twice and Gemini may make up to two paid fallback requests, and shows which models answer. Never writes a secret.
argument-hint: ""
---

# 3amigos-setup - the panel and the Gemini fallback, per user and per project

**Language:** write every user-facing line in the user's language. Commands, paths and errors
are verbatim.

`<panel skill dir>` below = the sibling directory `3amigos` next to this skill's base directory.

Output: at most three files.

- The user config `~/.claude/3amigos/config.json`.
- The project config `<main checkout>/.claude/3amigos.local.json`. It is local and never
  committed, because it can hold a cloud project id.
- One line in `<main checkout>/.gitignore`, only with the owner's yes.

Nothing else changes. Detect, Ask, Write and Verify call no model and send no paid request.
Only section 6 (Test) calls models: one tiny panel run per chosen scope, and it says so before
it runs. In that run Codex can retry once, and Gemini can walk its backend chain, so a Gemini
vote can make up to two paid fallback requests. The setup never writes, prints or logs a
secret: no API key value, no token. It never commits or pushes.

A panel never waits for this setup. Without a config the panel runs with the defaults: panel
`codex, gemini, fable`, `agy` only, fallback `none`. Its report then names this skill. A captain
run in away mode has no owner to answer the questions, so it never runs this setup.

## 1. Detect

Read only. Run each check exactly in these forms. Do not guess a result.

- **agy.** `~/.local/bin/agy --help >/dev/null 2>&1`; if that fails, `command -v agy`, then
  `agy --help >/dev/null 2>&1`. It counts only when `--help` exits 0. Then run `<agy> models`
  with the Bash tool timeout set to 15 s (macOS has no `timeout` binary). Note whether it lists
  an id that starts with `gemini-4-carbon` and one that starts with `gemini-4-argon`. These are
  the default `gemini.model` and `gemini.model_fallback`. When
  `python3 <panel skill dir>/scripts/panel.py --show-config` shows other values, check and name
  those two models instead of Carbon and Argon everywhere in this skill.
- **Vertex.** `command -v gcloud`, then a real token call with its output discarded:
  `gcloud auth application-default print-access-token >/dev/null 2>&1`. It passes only on
  exit 0. The ADC file alone proves nothing: an expired login keeps the file. When it passes,
  also read the gcloud default project, a not-secret id offered in question 3:
  `gcloud config get-value project 2>/dev/null`.
- **Key.** For `GEMINI_API_KEY` and `GOOGLE_API_KEY`, run
  `[ -n "${GEMINI_API_KEY:-}" ] && echo set || echo unset` (and the same for the other name).
  Report each only as set or unset.
  The key detect also passes when the variable is unset but project detection (section 2) finds
  a non-empty assignment of it in a real env file. The setup never checks the key itself:
  that would read the value. A bad key shows as `auth` in the first panel.

Never run `echo`, `printenv` or `env` on a key variable. Never Read or `cat` a `.env*` file.

## 2. Project detection

Only inside a git repo. Find the main checkout:

- Run `git rev-parse --path-format=absolute --git-common-dir`.
- The main checkout is that directory's parent when its basename is `.git`. A linked worktree
  (every captain agent works in one) gets the same main checkout this way.
- Not a git repo, or the basename is not `.git`: there is no main checkout. Skip this section,
  and do not offer the project config in section 3.

Look for what the project already uses for Gemini, in `.env.example`, `.env*`, config files and
code, with one command and the Bash tool timeout at 600000 ms (`<main checkout>` is the
absolute path; `<skill dir>` is this skill's base directory):

`python3 "<skill dir>/scripts/project_scan.py" "<main checkout>"`

Never search by hand instead: never run `grep -r` over the main checkout (on 2026-11-18 one pass
over a repo with 87 GB of media ran for more than five minutes), and never put a `.env` file
name in a Bash command (CC Safety Net blocks such a command with `secret.basename.env`). The
script searches two file sets and skips binary files:

- the repo's text files, through `git grep --untracked`: tracked files and untracked ones that
  are not ignored;
- the env files, which are usually ignored: every file whose name starts with `.env`.

Both sets leave out `.git`, `node_modules`, `.venv` and `.claude`. The script does not see
ignored files whose name does not start with `.env`, nor the text files of a git submodule (its
env files are seen); ask the owner when the project keeps its Gemini settings there.
`unreadable_dirs` lists the directories the script could not read: name them to the owner, as
an env file there was not seen.

It prints one JSON object. Each file entry has the absolute `file` and its `kind`: `env` (a real
env file), `env-example` (`.env.example`), `doc` (`*.md`, `*.html`, `*.txt`) or `text`. Exit 2
names a bad argument or a failed search; show it to the owner. The names come in two classes.

- **Not secret** (`not_secret`): `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`,
  `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_GENAI_USE_ENTERPRISE`, with the value. The match is
  anchored on these exact names and covers `NAME=value`, `export NAME=value`, YAML
  `NAME: value` and JSON `"NAME": "value"`. The value class `[A-Za-z0-9._-]` holds a project id,
  a location or a boolean, and nothing else, so the match never prints a second assignment on
  the same line.
- **Vertex in code** (`vertex_in_code`): code often calls Vertex with no env assignment at all,
  for example `process.env.GOOGLE_CLOUD_PROJECT || "my-project"` or
  `os.getenv("GOOGLE_CLOUD_PROJECT", "my-project")`. Only text files are searched, without
  env files and docs. Between the name and the id only a closing quote or bracket, spaces and
  one of `||`, `??`, `or`, `,`, `:`, `=` may stand, so the match never prints other code. The
  id is project id shaped (6–30 lowercase letters, digits and hyphens), so an API key never
  matches. A match `aiplatform.googleapis.com` is the Vertex host.
- **Secret:** `GEMINI_API_KEY`, `GOOGLE_API_KEY`, and anything else in a `.env` file. The script
  prints only file names, never a value. `key_named.<name>` lists the files that name the
  variable: that only says the project uses a key. `key_assigned.<name>` lists the files with a
  non-empty assignment, so a comment, an empty `NAME=` or empty quotes (`NAME=""`, `NAME=''`)
  do not count.

The patterns live in the script, and its value classes and the gap are what keep a secret out
of the output; never widen them.

Read the signals:

- **Vertex:** `GOOGLE_GENAI_USE_VERTEXAI` or `GOOGLE_GENAI_USE_ENTERPRISE` set to a true value,
  or a `GOOGLE_CLOUD_PROJECT` value, or a project id from the Vertex-in-code search. The
  proposal is `fallback: vertex` with that project id, and the `GOOGLE_CLOUD_LOCATION` value as
  the location (`global` when there is none). A Vertex host in code with no project id is a
  Vertex signal without an id.
- **Key:** a file that names `GEMINI_API_KEY` or `GOOGLE_API_KEY`. The proposal is
  `fallback: key` with that variable name.
- A name found only in docs (kind `doc`) is no signal: plans and notes mention names the
  project does not use.
- A real env file is a file of kind `env`, that is any `.env*` file except `.env.example`. Only
  a real env file in `key_assigned.<name>` makes the key detect pass for an unset variable;
  `.env.example` holds no key.

**One signal:** propose it as the recommended answer in section 3. The owner confirms before
anything is written.

**Conflicting signals:** the signals point to more than one backend, project id or key variable
(for example Vertex in `.env.example` and a key in `.env.local`). Then propose nothing by
yourself. List what was found per file: the names, and values only for the not-secret names.
Ask one question with those findings as the options. A real env file over `.env.example` is
only the marked recommendation.

A finding is one backend with one project id or one key variable; the files that hold the same
finding are one option, named with up to three of its files. So many files that call Vertex
with one project id are one option. The dialog holds four options, and "No fallback" takes
one, so at most three findings are options: the marked recommendation first. List any further
findings in the text before the question; the owner picks one of them with the dialog's own
"Other".

A project signal whose detect failed in section 1 is shown, but its fallback is not offered,
and it does not make the signals conflict. Example: code names `GEMINI_API_KEY` but the key
detect failed, and code calls Vertex with a project id: that is one signal, Vertex.

## 3. Ask

Use AskUserQuestion, one question per call. Mark the recommended option "(recommended)".

Before the first question, show the detect results in the user's language, one line each. A key
variable is shown only as "set" or "not set". For each failed detect, show the command that
repairs it, each command in its own code block:

```bash
gcloud auth application-default login
```

```bash
export GEMINI_API_KEY=<your key>
```

For `agy`, say that the owner installs and logs in to the Antigravity CLI by its own guide.

1. "Which three vote by default?"
   - "codex, gemini, fable" (recommended) — three providers.
   - "opus, codex, gemini" — design, architecture, specs and code triage, by the table
     "Choosing the panel" in `<panel skill dir>/REFERENCE.md`.
   - "gemini, opus, fable" — writing in Bulgarian, by the same table.
   - The dialog's own "Other" takes any other panel: exactly three different names from
     `codex`, `gemini`, `opus`, `fable`; reject anything else and ask again.
   When `gemini` is on the panel but no Gemini path passed detect, say so: the Gemini voter
   will be `missing`, and a Fable stand-in takes its place. The why is `missing-binary` when the
   `agy` binary was not found (the setup leaves `gemini.agy` at its default `true`). It is
   `no-backend` when `agy` was found but lists neither Gemini model.
2. "What should Gemini fall back to when agy does not answer?" Offer a fallback only when its detect
   passed:
   - `vertex` — Vertex AI with the `gcloud` login.
   - `key` — a Gemini API key from an environment variable.
   - "No fallback" → `none`.
   The dialog can hide the detect lines shown before it, so each option's description repeats
   its own detect result in a few words. When `agy` passed detect and `agy models` lists a
   `gemini-4-argon` id but no `gemini-4-carbon` id, ask instead: "agy has no Carbon, so
   Carbon comes only through the fallback. What should Gemini fall back to?" The `none` option
   then says that Gemini will answer only with Argon through `agy`.
   The recommendation is the project's signal (section 2) when its detect passed; else
   `vertex` when it passed; else `key` when it passed; else `none`.
   On conflicting signals (section 2), ask this question instead of questions 2–4:
   "Which of the project's findings should I use?" One option per finding whose detect passed, at
   most three (section 2): the file, the backend, and the project id with its location, or the
   key variable name.
   Add "No fallback" → `none`. A real env file over `.env.example` is the marked
   recommendation. The chosen option fills only what that finding holds. A missing project id
   or location is asked with the normal question 3, a missing key variable with question 4.
   Question 5 still applies to a chosen key.
3. Only for `vertex`: "Which cloud project?" The options are the project ids found, each with
   where it came from: the project's `GOOGLE_CLOUD_PROJECT` value (env or config file), a
   project id from the Vertex-in-code search (with its file), and the gcloud default project
   from section 1. The first of these that exists, in that order, is the recommended option.
   The dialog's own "Other" lets the owner type the `<gcp project id>`; with no id found, the
   owner types it. Then "Which location?"
   - `global` (recommended, unless the project names another).
   - The project's `GOOGLE_CLOUD_LOCATION` value, when found.
   - "Other location" → the owner types it.
4. Only for `key`: "Which variable holds the key?" Offer a name only when its key detect passed
   (set, or a non-empty assignment in a real env file):
   - `GEMINI_API_KEY` — recommended when it passed.
   - `GOOGLE_API_KEY`.
   - "Other name" → the owner types a variable name. It must match `[A-Za-z_][A-Za-z0-9_]*`
     and pass the same set/unset check, or have a real env file in `key_assigned.<name>` of
     the section 2 script run again with `--key-name <name>`. Otherwise say why and ask again.
5. Only for `key`, when that variable is unset and section 2 found a real env file in
   `key_assigned.<variable>`:
   "Should I read `<variable>` from `<file>` on every vote?"
   - "Yes" → `key_dotenv` is that file's path.
   - "No" → `"key_dotenv": null`, written explicitly, so an older value stops applying. The key
     must be in the environment when the panel runs.
   `key_dotenv` gets a path only on an explicit "Yes". The panel then reads that one variable
   from that file at call time, and nothing else from it.
6. "Where should I write the settings?" (skip when there is no main checkout; the user config is then
   the only choice)
   - "In my user config" → `~/.claude/3amigos/config.json`, for every repo. Recommended when
     the answers did not come from project detection.
   - "In the project config" → `<main checkout>/.claude/3amigos.local.json`, for this repo only.
     Recommended when the fallback answers came from project detection.
   - "In both".
   A project value wins over a user value, key by key. When the project config already holds a
   `key_dotenv` path, offer only "In the project config" and "In both", so a "No" clears it there.
7. Only when the project config is written and
   `git -C <main checkout> check-ignore -q .claude/3amigos.local.json` exits non-zero:
   "Should I add `.claude/3amigos.local.json` to `.gitignore`?"
   - "Yes" (recommended) — the file can hold a cloud project id.
   - "No".

## 4. Write

The JSON shape, with every key the panel reads:

```json
{
  "version": 1,
  "panel": ["codex", "gemini", "fable"],
  "gemini": {
    "agy": true,
    "model": "gemini-4-carbon",
    "model_fallback": "gemini-4-argon",
    "effort": "high",
    "fallback": "vertex",
    "vertex": {"project": "<gcp project id>", "location": "global"},
    "key_env": "GEMINI_API_KEY",
    "key_dotenv": null
  },
  "updated": "YYYY-MM-DD"
}
```

Write key by key:

- Read the target file first, if it exists. Keep every key this setup did not ask about.
- Write only the keys the owner answered: `panel`, `gemini.fallback`, and with it
  `gemini.vertex` (for `vertex`) or `gemini.key_env` and `gemini.key_dotenv` (for `key`):
  the path on the explicit yes, `null` on "No". Never write a guessed value: a wrong type or value is
  exit 2 at Verify.
- `gemini.agy`, `gemini.model`, `gemini.model_fallback` and `gemini.effort` are not asked.
  Leave them out of a new file, so the defaults pinned in `amigos_config.py` apply.
- `version` is 1. `updated` is today.
- Never write a key or token value. `key_env` is a variable name; `key_dotenv` is a path.

The files:

1. User config: `mkdir -p ~/.claude/3amigos`, then Write `~/.claude/3amigos/config.json`.
2. Project config: `mkdir -p <main checkout>/.claude`, then Write
   `<main checkout>/.claude/3amigos.local.json`.
3. With "In both", both files get the same keys. One exception: `key_dotenv` goes only to the
   project config, as a path relative to the main checkout. A relative path in the user config
   would point into every repo. A "No" writes `"key_dotenv": null` in every file this run
   writes. When only the project config is written and the user config holds a `key_dotenv`
   path, say so; the project's `null` overrides it, key by key.
4. On the "Yes" to question 7, add the line `.claude/3amigos.local.json` to
   `<main checkout>/.gitignore` as a line of its own (create the file when it is missing).
   When the file does not end with a newline, add one first, so the two lines never merge.
   Then rerun `git -C <main checkout> check-ignore -q .claude/3amigos.local.json`; a non-zero
   exit is reported to the owner. Do not commit it.

## 5. Verify

From the repo (or any directory when only the user config was written), run:

`python3 <panel skill dir>/scripts/panel.py --show-config`

It prints the effective config as one JSON line, with the source of each value: `run`,
`project`, `user` or `default`. It never prints a key or a token. Only `panel.py` reads and
merges the configs; never merge them by hand here.

- Exit 2 means a config error. It names the file path and the error. Show both, fix that file,
  and run the check again.
- Exit 0: show the effective config to the owner, as in section 7. The `files` key names the
  two files read: `{"user": <path>, "project": <path> | "none (no main checkout)"}`.

## 6. Test

Test each scope the owner chose to write in question 6: the user config, the project config, or
both. Use the existing panel with a tiny task; write no new code.

1. Tell the owner first, in one line: "I am running one short test panel for <scope> (Codex,
   Gemini); Codex may try twice, and Gemini may make up to two paid requests through the
   fallback."
2. Make a temp dir with `mktemp -d`. In it, write `task.md`, which asks for exactly the JSON
   object `{"ok": ["yes"]}` and nothing else, and an empty `data.md`.
3. Run the panel once per scope, with absolute paths, and the Bash tool timeout above 150 s:
   - user config: from the temp dir (outside any git repo), so only the user config applies;
   - project config: from the main checkout.

   In that same directory, first run `python3 <panel skill dir>/scripts/panel.py --show-config`.
   Its `panel` is that scope's panel for the table in step 4; never take it from section 5.

   `python3 <panel skill dir>/scripts/panel.py --task <temp dir>/task.md --input <temp dir>/data.md --out <temp dir>/<scope> --require ok=1 --deadline 120`

   It runs the external voters of that scope's effective panel (Codex and Gemini, when on it).
   A scope whose panel has no external voter skips the run.
4. Show one status table per scope, from the status lines and that scope's `--show-config`
   panel only:

   ```
   | Voter | Status | Backend | Model | Reason |
   ```

   - Codex and Gemini: `ok` or `missing`. For Gemini add `backend` and `model` from its status
     line, and `why` and `note` when present. The Codex status line has no `backend` or
     `model`: write "—" there, never a guessed value.
   - `opus` and `fable` on the panel are agents of the main session: list them as
     "available (agent)". They are not called.
5. For a missing voter, give the repair advice the panel skill gives for that why:
   - `auth`: by the scope's `gemini.fallback`. For `vertex`, log in again with
     `gcloud auth login` and `gcloud auth application-default login`. For `key`, set the
     variable named by `key_env`, or fix the `key_dotenv` file.
   - `no-backend`: no Gemini path; run this setup again and choose a fallback.
   - `missing-binary`: install the missing CLI (`agy` or `codex`).
   - A Gemini `missing` (for example `exit <n>`) when
     `command grep -c "Eligibility check failed" <temp dir>/<scope>/gemini.log` is above 0:
     log in to `agy` once by its own guide.
   - Any other why: show it verbatim.
   Never print a key, a token or lines of `gemini.log`; count with `grep -c` only.
6. Remove the temp dir: `command rm -rf <temp dir>`.

## 7. Report

Seven lines, then the test tables of section 6, then one line: "You can run the setup again with `/3amigos:3amigos-setup`."

```
Panel: <a, b, c> (<source>)
agy: <yes, Carbon <yes|no>, Argon <yes|no> | not found>
Fallback: <vertex <project>/<location> | key <variable>[, from <file>] | none> (<source>)
Gemini answers: <model> through <backend> | not on the panel | missing (<why>)
Key variable: GEMINI_API_KEY <set|not set>, GOOGLE_API_KEY <set|not set>
.gitignore: <line added | already ignored | no | no project config>
Files: user <files.user>, project <files.project>
```

The sources and the file paths come from the `--show-config` line of section 5, never from
memory and never from the line run in a test temp dir (that one shows no project config). The
"Gemini answers" line comes from the Gemini status line of the test; with two scopes, name each.
When Gemini is `ok`, compare its model with that scope's `gemini.model` from its
`--show-config` line of section 6. When they differ and the scope's fallback is not `none`, add
one sentence: the fallback did not answer with `<gemini.model>` in the test, and the status
line's `note` says why when it has one. The owner then knows that `<gemini.model>` is not in
use.
