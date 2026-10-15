#!/usr/bin/env python3
"""Count main-session tool calls outside the captain R1 allow-list in a Claude Code transcript.

Usage: audit-main.py [--repo <repo root>] [--skill-root <dir>] <session.jsonl | ->

Reads one session transcript (~/.claude/projects/<project>/<session>.jsonl, or `-` for stdin),
keeps the tool calls of the MAIN session only, and prints every call outside the R1 allow-list
with its timestamp and the whole offending part (newlines escaped as \\n).

This is a NON-ADVERSARIAL compliance measure of Claude's own main session, not a security
boundary: it answers "did the coordinator stay a coordinator?", and a determined author can
write a command it does not catch. Its rule is: anything not plainly recognised is
UNVERIFIABLE (exit 3), never OK.

Roots:
  - repo root: --repo, else the git toplevel of each record's `cwd`; without either, path
    checks are unverifiable;
  - skill root: --skill-root, else this script's own skill directory (pass the installed
    plugin's skill directory when auditing a session that loaded another copy).
Paths are checked for containment after `..` and symlinks are resolved.

What it checks (R1: ДЛ1 passes, ДЛ2 is agent work, ДЛ4 never):
  - tools: Agent (and Task, its old name), SendMessage, ListAgents, TaskStop, AskUserQuestion,
    ToolSearch, CronCreate, CronDelete, CronList, ReadNotifications, EnterWorktree pass when
    their required input is present; Skill passes only for the exact names captain,
    captain:captain, captain-setup, captain:captain-setup, 3amigos, 3amigos:3amigos; every
    other tool is a violation;
  - Read, Grep and Glob pass anywhere, except an agent output file (<dir>/tasks/<id>.output),
    which only `stat` may touch (ДЛ4);
  - Write and Edit: <repo>/tmp/captain/**, <repo>/TODO (or TODO* with a doc suffix), <repo>/docs/** with a doc suffix
    (.md .mdx .markdown .txt .rst .adoc; never a SKILL.md or a path with a `skills` part),
    <repo>/.claude/settings.local.json and the auto memory,
    <home>/.claude/projects/<project>/memory/*.md; Artifact with action `open` and a url;
  - Bash with run_in_background (except a lone `sleep N`, the timer) or a timeout above
    120000 ms is a violation (ДЛ2);
  - Bash, as an allow-list grammar: simple commands joined by ; && || & or newline, and
    pipelines into status filters; words plain or in '...' / "..." without $, and without
    unquoted { } * ? [; no VAR=value prefix; redirections only 2>&1 and >/dev/null (also
    1> 2> &>). Allowed commands: cat, head, tail (no -f/-F/--follow), wc, ls, find (no
    -exec, -ok, -delete, -fprint, -fls), never on an agent output file; date with an optional
    +FORMAT and either BSD -v±N<unit> adjustments or one GNU -d/--date relative expression;
    git [-C dir] [--no-pager] log with a positive last count (-n N, -N, --max-count=N) and
    display options only (no -p); git status; git diff and git show (no --output, no
    --ext-diff), a git diff path operand only inside the work tree of its directory (the cwd,
    after cd and -C) and never a directory that holds agent output files; git rev-parse; git fetch [<flags>] [<remote> [<branch>...]] (no refspec);
    git branch with only -v -vv -a -r --show-current; git worktree list [--porcelain]; git
    remote -v; the merge flow (R1): git merge --no-ff [--no-edit] <branch>, git merge
    --ff-only origin/<branch> (the live guard allows only origin/<default>), git merge
    --abort, git commit --no-edit, and, for the branch of the owner's typed
    `/captain merge <branch>` in the same repository (until `/captain off`, a new start, a
    new grant, the model's `captain end` call, or 12 hours), git switch <branch> and git push
    <remote> <branch>; stat; ps; cd; `python3 <skill root>/scripts/agent-context.py` with one
    or more agent ids; the per-user wrapper ~/.claude/captain/notify.sh (written by
    captain-setup) with exactly one argument. An executable given by path is otherwise
    unverifiable. After a pipe: grep with -E -i -v -c, -e PATTERN, -- and one pattern;
    head/tail -n N; wc -l/-w/-c; never a file operand. A leading bare `command` is skipped.
  - captain-setup, which runs in the main session (it needs AskUserQuestion), may do exactly:
    Write <home>/.claude/captain/config.json (never notify.sh: a runner writes it); Read
    <home>/.claude/captain/config.json (the captain skill reads it at start),
    <home>/.claude/skills/msg-notify/SKILL.md and its own template
    <skill root>/../captain-setup/notify.sh.tmpl; Bash `command -v codex|agy|supacode|cmux`;
    `<tool> --help` for codex, agy and ~/.local/bin/agy only;
    `chmod +x <home>/.claude/captain/notify.sh`; the test ping
    `CAPTAIN_NOW=HH:MM [CAPTAIN_SEND_NOW=1] <home>/.claude/captain/notify.sh "<msg>"` (no
    other variable or target).
    <home> is the current user's home directory.

Unverifiable (counted, never allowed, exit 3): syntax outside that grammar ($-expansion,
command substitution, ANSI-C quoting, groups { } ( ), here documents, redirection to or from
a file, a redirection with no command), a tool call without its name or with missing or
mistyped input, a path check without a repo root, a record of unknown type or shape. When
such a command still names a known-forbidden program (git commit, rm, codex, ...), it is a
violation.

What it cannot see:
  - the live merge checks of hooks/guard.py: the branch HEAD was on (captain/*, the owner's
    base, a granted branch), whether a merge was in progress, which branch origin/HEAD named;
  - intent: an allowed call made for the wrong reason passes;
  - a forbidden action hidden inside the arguments of an allowed program;
  - anything a subagent did: sidechain entries, tool results and <session>/subagents/*.jsonl
    are ignored, and a subagent transcript given as input is refused;
  - how symlinks looked when the session ran: paths are resolved as they are now;
  - which repository a grant belongs to beyond the record's cwd (or --repo): the live guard
    binds it to the git common dir and the run ID;
  - whether the owner approved a settings.local.json write;
  - work done by hooks, by the user, or outside this transcript file.

Exit codes: 0 audit complete, no violations; 1 violations found; 2 bad input (no file,
unreadable, no JSON line, bad arguments, or a subagent transcript); 3 incomplete audit (no
violations found, but part of the transcript could not be checked). Only 0 is a pass.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REQUIRED_INPUT = {
    "Agent": ("prompt",), "Task": ("prompt",), "SendMessage": (), "TaskStop": (),
    "AskUserQuestion": ("questions",), "ToolSearch": ("query",),
    "CronCreate": ("cron", "prompt"), "CronDelete": ("id",), "CronList": (),
    "ReadNotifications": (), "ListAgents": (), "EnterWorktree": (),
}
ANY_OF_INPUT = {"SendMessage": ("to", "recipient"), "TaskStop": ("task_id", "shell_id")}
# the captain skill, its setup, and the 3amigos panel main runs itself (АМ1)
ALLOWED_SKILLS = {"captain", "captain:captain", "captain-setup", "captain:captain-setup",
                  "3amigos", "3amigos:3amigos"}
READ_COMMANDS = {"cat", "head", "tail", "wc", "ls", "find"}  # ДЛ1 read-only Bash, file operands
FIND_ACTIONS = re.compile(r"^-(exec|execdir|ok|okdir|delete|fprint\w*|fls|fprintf)$")
DOC_SUFFIXES = {".md", ".mdx", ".markdown", ".txt", ".rst", ".adoc"}
MAX_TIMEOUT_MS = 120_000  # ДЛ2: a longer Bash call is agent work
# the run's timer is the one background call main keeps (R11, R13)
BACKGROUND_TIMER = re.compile(r"^\s*(command\s+)?sleep\s+\d+[smhd]?\s*$")
RECORD_TYPES = {
    "user", "assistant", "system", "attachment", "summary", "progress", "agent-name", "ai-title",
    "artifact-autoreact-ledger", "artifact-comment-monitor", "atis-latch", "bridge-session",
    "cost-state", "custom-title", "file-history-delta", "file-history-snapshot", "frame-link",
    "last-prompt", "mode", "permission-mode", "pr-link", "queue-operation", "relocated",
    "worktree-state",
}
SAFE_REDIRECTS = {"2>&1", ">/dev/null", "1>/dev/null", "2>/dev/null", "&>/dev/null"}
SEPARATORS = {";", "&&", "||", "&", "\n"}
PIPES = {"|", "|&"}
RESERVED = {"{", "}", "!", "if", "then", "else", "elif", "fi", "for", "while", "until", "do",
            "done", "case", "esac", "function", "select", "time", "[[", "]]"}
FORBIDDEN = {
    "rm", "mv", "cp", "kill", "pkill", "killall", "codex", "grok", "agy", "npm", "npx", "pnpm",
    "yarn", "mvn", "mvnw", "gradle", "gradlew", "make", "cargo", "pytest", "python", "python3",
    "node", "docker", "gh", "curl", "wget", "tee", "dd", "truncate", "chmod", "sed", "perl",
    "bash", "sh", "zsh", "eval", "touch", "mkdir", "ln", "rsync", "scp", "ssh", "open",
    "osascript", "build-dev.sh", "build-project.sh",
}
FORBIDDEN_GIT = {
    "commit", "push", "merge", "rebase", "reset", "checkout", "switch", "add", "rm", "mv", "tag",
    "cherry-pick", "revert", "stash", "clean", "restore", "worktree", "branch", "pull", "fetch",
    "clone", "am", "apply",
}
GIT_LOG_FLAGS = re.compile(
    r"^--(oneline|graph|no-decorate|decorate(=\w+)?|abbrev-commit|no-color|color=never|"
    r"first-parent|reverse|all|stat|shortstat|name-only|name-status|no-merges|merges|"
    r"(format|pretty|date|since|until|after|before|author|grep)=.*)$")
GIT_STATUS_FLAGS = re.compile(r"^(-s|-b|-sb|-bs|--short|--branch|--porcelain(=v[12])?|-u\w*|"
                              r"--untracked-files(=\w+)?|--ignored|--no-renames)$")
HOME = os.path.expanduser("~")
NOTIFY = f"{HOME}/.claude/captain/notify.sh"  # the per-user wrapper from captain-setup
# captain-setup's own actions (see the docstring)
# never notify.sh: main must not write the wrapper it may run (Codex kp1 r1 F2, owner ОП1)
SETUP_WRITES = {f"{HOME}/.claude/captain/config.json"}
SETUP_READS = {f"{HOME}/.claude/captain/config.json", f"{HOME}/.claude/skills/msg-notify/SKILL.md"}
SETUP_TOOLS = {"codex", "agy"}
SETUP_DETECT = SETUP_TOOLS | {"supacode", "cmux"}  # `command -v` only; no --help call
SETUP_HELP = SETUP_TOOLS | {f"{HOME}/.local/bin/agy"}
CAPTAIN_NOW = re.compile(r"^CAPTAIN_NOW=([01]\d|2[0-3]):[0-5]\d$")
COUNT = re.compile(r"^\d+$")
AGENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
SKILL_ROOT = Path(__file__).resolve().parent.parent
OK, VIOLATION, UNVERIFIABLE = "ok", "VIOLATION", "UNVERIFIABLE"


class Unverifiable(Exception):
    pass


# ---------------------------------------------------------------- lexer

class _Lexer:
    """Tokens: ("W", word) ("OP", op) ("R", redirection, safe). strict=False never raises."""

    def __init__(self, text: str, strict: bool):
        self.text, self.i, self.strict = text, 0, strict
        self.tokens: list[tuple] = []
        self.word: list[str] | None = None

    def fail(self, why: str):
        if self.strict:
            raise Unverifiable(why)

    def end_word(self):
        if self.word is not None:
            self.tokens.append(("W", "".join(self.word)))
        self.word = None

    def add(self, chars: str):
        self.word = (self.word or []) + [chars]

    def op(self, op: str):
        self.end_word()
        self.tokens.append(("OP", op))
        self.i += len(op)

    def single(self):
        end = self.text.find("'", self.i + 1)
        if end < 0:
            self.fail("unterminated quote")
            end = len(self.text)
        self.add(self.text[self.i + 1:end])
        self.i = end + 1

    def double(self):
        text, i, out = self.text, self.i + 1, []
        while i < len(text) and text[i] != '"':
            ch = text[i]
            if ch == "\\" and i + 1 < len(text):
                nxt = text[i + 1]
                out.append("" if nxt == "\n" else nxt if nxt in '"\\$`' else ch + nxt)
                i += 2
                continue
            if ch == "`" or (ch == "$" and i + 1 < len(text) and re.match(r"[\w{(@*#?$!-]", text[i + 1])):
                self.fail("expansion inside double quotes")
            out.append(ch)
            i += 1
        if i >= len(text):
            self.fail("unterminated quote")
        self.add("".join(out))
        self.i = i + 1

    def redirection(self):
        text = self.text
        if text.startswith("<<", self.i):
            self.fail("here document")
            self.heredoc()
            return
        prefix = ""
        if self.word is not None and "".join(self.word).isdigit():
            prefix, self.word = "".join(self.word), None
        self.end_word()
        match = re.match(r"(&>|>>|>&|<&|>|<)\s*([^\s;|&()<>]*)", text[self.i:])
        self.i += match.end()
        form = prefix + match.group(1) + match.group(2)
        # an unsafe target is marked, not fatal: the program is still checked first
        self.tokens.append(("R", form, form in SAFE_REDIRECTS))

    def heredoc(self):
        match = re.match(r"<<-?\s*['\"]?(\w+)['\"]?", self.text[self.i:])
        if not match:
            self.i += 2
            return
        self.i += match.end()
        end = re.search(rf"(?m)^\s*{match.group(1)}\s*$", self.text[self.i:])
        self.i = len(self.text) if not end else self.i + end.end()

    def run(self) -> list[tuple]:
        text = self.text
        while self.i < len(text):
            ch, rest = text[self.i], text[self.i:]
            if rest.startswith("\\\n"):
                self.i += 2
            elif ch == "\\":
                if self.i + 1 >= len(text):
                    self.fail("trailing backslash")
                self.add(text[self.i + 1:self.i + 2])
                self.i += 2
            elif rest.startswith("$'"):
                self.fail("ANSI-C quoting")
                self.i += 1
                self.single()
            elif ch == "'":
                self.single()
            elif ch == '"':
                self.double()
            elif rest.startswith("$(") or ch == "`":
                self.fail("command substitution")
                self.op("$(" if ch == "$" else "`")
            elif ch == "$" and len(rest) > 1 and re.match(r"[\w{@*#?$!-]", rest[1]):
                self.fail("parameter expansion")
                self.add(ch)
                self.i += 1
            elif ch == "#" and self.word is None:
                while self.i < len(text) and text[self.i] != "\n":
                    self.i += 1
            elif ch in " \t":
                self.end_word()
                self.i += 1
            elif rest.startswith(("<(", ">(")):
                self.fail("process substitution")
                self.op(rest[:2])
            elif ch in "<>" or rest.startswith("&>"):
                self.redirection()
            elif ch in "();\n|&":
                if ch in "()":
                    self.fail("subshell")
                self.op(next(o for o in ("&&", "||", "|&", ";;", "|", "&", ";", "\n", "(", ")")
                             if rest.startswith(o)))
            else:
                if ch in "{}*?[":
                    self.fail("unquoted brace or glob expansion")
                self.add(ch)
                self.i += 1
        self.end_word()
        return self.tokens


# ---------------------------------------------------------------- grammar

def parse(command: str) -> list[list[tuple[list[str], list[tuple]]]]:
    """Parse into pipelines of (words, redirections); raise Unverifiable outside the grammar."""
    tokens = _Lexer(command, strict=True).run()
    pipelines, pipeline = [], []
    words, redirs = [], []
    expect_command = False  # after | && || a command must follow (newlines allowed)

    def close_command():
        nonlocal words, redirs
        if not words and redirs:
            raise Unverifiable("redirection without a command")
        if words:
            pipeline.append((words, redirs))
        words, redirs = [], []

    for token in tokens:
        if token[0] == "W":
            if not words and token[1] in RESERVED:
                raise Unverifiable(f"shell keyword {token[1]!r}")
            words.append(token[1])
            expect_command = False
        elif token[0] == "R":
            redirs.append(token)
        elif token[1] in PIPES:
            close_command()
            if not pipeline or expect_command:
                raise Unverifiable("pipe without a command")
            expect_command = True
        elif token[1] in SEPARATORS:
            if token[1] == "\n" and expect_command and not words and not redirs:
                continue
            close_command()
            if not pipeline:
                if token[1] == "\n":
                    continue
                raise Unverifiable(f"{token[1]!r} without a command")
            pipelines.append(pipeline)
            pipeline = []
            expect_command = token[1] in {"&&", "||"}
        else:
            raise Unverifiable(f"operator {token[1]!r}")
    close_command()
    if expect_command:
        raise Unverifiable("command line ends with an operator")
    if pipeline:
        pipelines.append(pipeline)
    if not pipelines:
        raise Unverifiable("empty command")
    return pipelines


def forbidden_anywhere(command: str) -> str | None:
    """For text outside the grammar: a known-forbidden program at a command position."""
    tokens = _Lexer(command, strict=False).run()
    at_start = True
    for index, token in enumerate(tokens):
        if token[0] != "W":
            at_start = token[0] == "OP"
            continue
        word = token[1]
        if not at_start:
            continue
        if word in {"command", "exec", "nohup", "sudo", "xargs", "env", "timeout", "{", "!"} \
                or re.match(r"^[A-Za-z_]\w*=", word) or COUNT.match(word) or word.startswith("-"):
            continue
        at_start = False
        name = os.path.basename(word)
        if name in FORBIDDEN:
            return word
        if name == "git":
            rest = [t[1] for t in tokens[index + 1:] if t[0] == "W"]
            while rest and rest[0].startswith("-"):
                rest = rest[2:] if rest[0] in {"-C", "-c"} else rest[1:]
            if rest and rest[0] in FORBIDDEN_GIT:
                return f"git {rest[0]}"
    return None


# ---------------------------------------------------------------- Bash rules

MERGE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
MERGE_SUBS = {"merge", "commit", "switch", "push"}  # the merge flow; hooks/guard.py checks live


def git_subcommand(args: list[str]) -> str | None:
    """The git subcommand after the global options (-C takes a value), else None."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in {"-C", "-c"} else 1
    return args[i] if i < len(args) else None


def valid_ref(ref: str) -> bool:
    """A plain branch name: no option, range, revision suffix or trailing dot or slash."""
    return MERGE_REF.match(ref) is not None and ".." not in ref \
        and not ref.endswith((".", "/", ".lock"))


def merge_ref(rest: list[str]) -> str | None:
    """The branch of `merge --no-ff [--no-edit] <branch>`, else None (R1 merge commands)."""
    flags = [a for a in rest if a.startswith("-")]
    refs = [a for a in rest if not a.startswith("-")]
    if "--no-ff" not in flags or not set(flags) <= {"--no-ff", "--no-edit"} \
            or len(flags) != len(set(flags)) or len(refs) != 1:
        return None
    return refs[0] if valid_ref(refs[0]) else None


def _merge_ok(sub: str, rest: list[str], grant: str | None = None) -> bool:
    """R1: main runs the merge of a reviewed branch, its abort, and the conclusion after an
    agent resolved the conflicts; with the owner's `/captain merge <branch>` also the switch
    to that branch and its push (R10). Which branch HEAD is on, whether a merge is in progress
    and whether the owner allowed the branch are checked live by hooks/guard.py, not here."""
    if sub == "commit":
        return rest == ["--no-edit"] or todo_commit(rest)
    if sub == "switch":
        return rest == [grant] and valid_ref(rest[0])
    if sub == "push":
        return len(rest) == 2 and rest[1] == grant and valid_ref(rest[0]) and valid_ref(rest[1])
    if len(rest) == 2 and rest[0] == "--ff-only":  # catching up with origin/<default> (R10)
        return rest[1].startswith("origin/") and valid_ref(rest[1])
    return rest == ["--abort"] or merge_ref(rest) is not None


def todo_commit(rest: list[str]) -> bool:
    """The R18 TODO-only commit: `commit -m <msg> -- <TODO file>...`, files named at the repo
    root (the pathspec commits only them; no `git add`). hooks/guard.py checks live that no
    merge is in progress, that -C names the top level and the HEAD (Codex kp1 r1 F8)."""
    if len(rest) < 4 or rest[0] != "-m" or not rest[1].strip() or rest[2] != "--":
        return False
    files = rest[3:]
    return len(files) == len(set(files)) and all("/" not in f and todo_name(f) for f in files)


FETCH_FLAGS = {"--prune", "-p", "--quiet", "-q", "--all", "--tags", "--no-tags", "--dry-run"}


# diff/show options, each spelled out in full: git accepts abbreviations (`--ext-dif`), so a
# deny-list of --output/--ext-diff/--textconv misses them (Codex kp1 r1 F1); no --no-index, which
# reads whole directories outside the repository (kp1 r2 F2)
DIFF_FLAGS = re.compile(
    r"^(--(stat(=[\d,]+)?|shortstat|numstat|dirstat(=[\w,]+)?|summary|name-only|name-status|raw|"
    r"patch|no-patch|cached|staged|merge-base|no-color|color=never|check|quiet|"
    r"exit-code|no-renames|find-renames(=\d+%?)?|word-diff(=\w+)?|ignore-all-space|"
    r"ignore-space-change|ignore-blank-lines|no-ext-diff|no-textconv|minimal|patience|"
    r"histogram|abbrev(=\d+)?|abbrev-commit|full-index|diff-filter=\w+|unified=\d+|oneline|"
    r"first-parent|no-decorate|(format|pretty|date)=.*)|-[pswbRM]|-U\d+|-M\d+%?|--)$")


def names_output(arg: str) -> bool:
    """An operand that names an agent output file: a `.output` name, relative or not, so a
    `cd` into the tasks directory does not hide it (ДЛ4, Codex kp1 r1 F4)."""
    return agent_output(arg) or os.path.basename(arg.rstrip("/")).endswith(".output")


def _diff_ok(rest: list[str]) -> bool:
    """git diff/show: only the listed options (no --output, external diff or textconv), and
    never an agent output file as an operand."""
    return all(DIFF_FLAGS.match(a) if a.startswith("-") else not names_output(a) for a in rest)


LOST_CWD = Path("/\0lost")  # a `cd` this grammar cannot follow (`cd -`, `cd a b`)


def _diff_base(args: list[str], cwd: Path | None) -> Path | None:
    """The directory git runs in: the cwd, then each -C relative to the one before it."""
    base, i = cwd, 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-C":
            step = Path(os.path.expanduser(args[i + 1]))
            base = step if step.is_absolute() else (base / step if base and base != LOST_CWD
                                                    else LOST_CWD)
            i += 2
        else:
            i += 1
    return base


def _diff_paths(rest: list[str], base: Path | None) -> list[Path]:
    """The diff operands git may read as paths: after `--`, absolute or `~`, or an existing
    file or directory under `base`. Any other operand is a revision (`main`, `a..b`)."""
    paths, after = [], False
    for arg in rest:
        if arg == "--" and not after:
            after = True
            continue
        if arg.startswith("-") and not after:
            continue
        expanded = os.path.expanduser(arg)
        if after or os.path.isabs(expanded):
            paths.append(Path(expanded) if os.path.isabs(expanded) or base is None
                         else base / expanded)
        elif base is not None and os.path.lexists(base / expanded):
            paths.append(base / expanded)
    return paths


def _diff_kind(args: list[str], cwd: Path | None) -> str:
    """ИФ1: a plain `git diff <a> <b>` acts like --no-index when an operand lies outside the
    work tree or git runs outside any repository, and it reads a whole directory operand.
    Every path operand stays inside the work tree of the directory git runs in and is no
    directory above agent output files. hooks/guard.py runs this check live."""
    base = _diff_base(args, cwd)
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] == "-C" else 1
    rest = args[i + 1:]
    operands = [a for a in rest if not a.startswith("-") or a == "--"]
    if not operands:
        return OK
    if base == LOST_CWD:
        return UNVERIFIABLE
    known = base is not None and os.path.isdir(base)
    paths = _diff_paths(rest, base if known else None)
    if not known:  # no cwd, or a directory gone since: only a path that names itself is unclear
        return UNVERIFIABLE if any(p.is_absolute() for p in paths) else OK
    tree = repo_root(str(base))
    if tree is None:
        return VIOLATION  # outside any repository git diff is --no-index
    top = Path(os.path.realpath(tree))
    for path in paths:
        real = Path(os.path.realpath(path))
        if not _inside(real, top) or names_output(str(path)) or os.path.isdir(real) \
                and (real.name == "tasks" or _holds_outputs(real)):
            return VIOLATION
    return OK


def _fetch_ok(rest: list[str]) -> bool:
    """`git fetch [<flags>] [<remote> [<branch>...]]`: no refspec (`a:b` rewrites a local
    branch), no forced `+ref`, no --upload-pack."""
    return all(a in FETCH_FLAGS if a.startswith("-") else valid_ref(a) for a in rest)


GIT_READS = {  # ДЛ1 git inspection
    "branch": lambda rest: set(rest) <= {"-v", "-vv", "-a", "-r", "--show-current"},
    "worktree": lambda rest: rest in (["list"], ["list", "--porcelain"]),
    "remote": lambda rest: rest == ["-v"],
    "diff": _diff_ok,
    "show": _diff_ok,
    "rev-parse": lambda rest: True,
    "fetch": _fetch_ok,
}


def _git_ok(args: list[str], grant: str | None = None) -> bool:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-C" and i + 1 < len(args):
            i += 2
        elif args[i] == "--no-pager":
            i += 1
        else:
            return False
    if i >= len(args):
        return False
    sub, rest = args[i], args[i + 1:]
    if sub in MERGE_SUBS:
        return _merge_ok(sub, rest, grant)
    if sub in GIT_READS:
        return GIT_READS[sub](rest)
    if sub == "status":
        return all(GIT_STATUS_FLAGS.match(a) or not a.startswith("-") for a in rest)
    if sub != "log":
        return False
    count, j = None, 0
    while j < len(rest):
        arg = rest[j]
        if arg == "--":
            break
        if arg in {"-n", "--max-count"}:
            if j + 1 >= len(rest):
                return False
            count, j = rest[j + 1], j + 2
            continue
        match = re.match(r"^(?:-n|--max-count=|-)(-?\d+)$", arg)
        if match:
            count = match.group(1)
        elif arg.startswith("-") and not GIT_LOG_FLAGS.match(arg):
            return False
        j += 1
    return count is not None and COUNT.match(count) is not None and int(count) > 0


def _grep_kind(args: list[str]) -> str:
    patterns, positional, i, options = 0, 0, 0, True
    while i < len(args):
        arg = args[i]
        if options and arg == "--":
            options = False
        elif options and arg == "-e":
            if i + 1 >= len(args):
                return UNVERIFIABLE
            patterns, i = patterns + 1, i + 1
        elif options and arg.startswith("-"):
            if not re.match(r"^-[Eivc]+$", arg):
                return UNVERIFIABLE
        else:
            positional += 1
        i += 1
    return OK if (patterns and not positional) or (not patterns and positional == 1) else UNVERIFIABLE


def _filter_kind(words: list[str]) -> str:
    program, args = words[0], words[1:]
    if "/" in program:
        return UNVERIFIABLE
    if program == "grep":
        return _grep_kind(args)
    if program in {"head", "tail"}:
        ok = not args or args[:1] == ["-n"] and len(args) == 2 and COUNT.match(args[1]) \
            or len(args) == 1 and re.match(r"^-n\d+$", args[0])
        return OK if ok else UNVERIFIABLE
    if program == "wc":
        return OK if all(a in {"-l", "-w", "-c"} for a in args) else UNVERIFIABLE
    return VIOLATION


BSD_ADJUST = re.compile(r"^-v[+-]?\d+[SMHdmwy]$")
GNU_RELATIVE = re.compile(
    r"^(now\s*)?([+-]\s*)?\d+\s*(sec|second|min|minute|hour|day|week|month|year)s?$", re.I)


def _date_kind(args: list[str]) -> str:
    """date [one or more -v±N<unit> | one -d/--date relative expression] [+FORMAT]."""
    if args and args[-1].startswith("+"):
        args = args[:-1]
    if all(BSD_ADJUST.match(a) for a in args):
        return OK  # also covers bare `date`
    if len(args) == 2 and args[0] == "-d":
        expression = args[1]
    elif len(args) == 1 and args[0].startswith("--date="):
        expression = args[0][len("--date="):]
    else:
        return UNVERIFIABLE
    return OK if GNU_RELATIVE.match(expression.strip()) else UNVERIFIABLE


def agent_output(path: str) -> bool:
    """An agent's output file (<tmp>/tasks/<id>.output): main never reads it (ДЛ4)."""
    for candidate in (Path(os.path.expanduser(path)), Path(os.path.realpath(os.path.expanduser(path)))):
        if candidate.suffix == ".output" and candidate.parent.name == "tasks":
            return True
    return False


def _read_kind(name: str, args: list[str]) -> str:
    """ДЛ1 read-only commands with file operands: cat, head, tail, wc, ls, find. Never an
    agent output file (ДЛ4), never `tail -f` (a process that outlives the call), never a find
    action that runs or deletes."""
    if any(names_output(a) for a in args if not a.startswith("-")):
        return VIOLATION
    if name == "tail" and any(a.startswith("--follow") or a == "--retry"
                              or re.match(r"^-[A-Za-z0-9]*[fF]", a) for a in args):
        return VIOLATION
    if name == "find" and any(FIND_ACTIONS.match(a) for a in args):
        return VIOLATION
    return OK


def _context_kind(args: list[str], skill_root: Path) -> str | None:
    """`python3 <skill root>/scripts/agent-context.py <agentId>...`; else None."""
    if not args or os.path.normpath(os.path.expanduser(args[0])) \
            != os.path.normpath(str(skill_root / "scripts" / "agent-context.py")):
        return None
    ids = args[1:]
    return OK if ids and all(AGENT_ID.match(i) for i in ids) else UNVERIFIABLE


def _first_kind(words: list[str], background: bool, skill_root: Path = SKILL_ROOT,
                grant: str | None = None, cwd: Path | None = None) -> str:
    program, args = words[0], words[1:]
    name = os.path.basename(program)
    if program == "python3":
        kind = _context_kind(args, skill_root)
        if kind is not None:
            return kind
    if args == ["--help"] and os.path.expanduser(program) in SETUP_HELP:
        return OK
    if name == "chmod" and "/" not in program:
        return OK if len(args) == 2 and args[0] == "+x" \
            and os.path.expanduser(args[1]) == NOTIFY else VIOLATION
    if "/" in program:
        if os.path.expanduser(program) == NOTIFY:
            return OK if len(args) == 1 else UNVERIFIABLE
        return VIOLATION if name in FORBIDDEN or name.startswith("build-") else UNVERIFIABLE
    if name == "date":
        return _date_kind(args)
    if name in {"stat", "ps", "cd"}:
        return OK
    if name in READ_COMMANDS:
        return _read_kind(name, args)
    if name == "git":
        if not _git_ok(args, grant):
            return VIOLATION
        return _diff_kind(args, cwd) if git_subcommand(args) == "diff" else OK
    if name == "sleep":
        return OK if background else VIOLATION
    return VIOLATION


def _setup_kind(words: list[str], position: int) -> str | None:
    """captain-setup's `command -v <tool>` and its test ping
    `CAPTAIN_NOW=HH:MM [CAPTAIN_SEND_NOW=1] notify.sh <msg>`; else None."""
    if position:
        return None
    if len(words) == 3 and words[:2] == ["command", "-v"] and words[2] in SETUP_DETECT:
        return OK
    if len(words) == 4 and words[1] == "CAPTAIN_SEND_NOW=1":
        words = [words[0], *words[2:]]  # the test ping skips the away check
    if len(words) == 3 and CAPTAIN_NOW.match(words[0]) and os.path.expanduser(words[1]) == NOTIFY:
        return OK
    return None


def _cd(words: list[str], here: Path | None) -> Path | None:
    """The cwd after a plain `cd [<dir>]`; LOST_CWD when it cannot be followed. A `cd` to no
    directory fails and leaves the shell where it was (`cd x; git diff ...` runs here)."""
    if len(words) == 1:
        return Path(HOME)
    target = os.path.expanduser(words[1])
    if len(words) != 2 or target.startswith("-"):
        return LOST_CWD
    if os.path.isabs(target):
        moved = Path(os.path.normpath(target))
    elif here is None or here == LOST_CWD:
        return LOST_CWD
    else:
        moved = Path(os.path.normpath(here / target))
    return moved if os.path.isdir(moved) else here


def bash_violation(command: str, background: bool, skill_root: Path = SKILL_ROOT,
                   grant: str | None = None, cwd: Path | None = None) -> str | None:
    """Return the offending command of a Bash call, or None when allowed; raise Unverifiable.
    `cwd` is where the call starts; a plain `cd` as the first command moves it for the
    commands after it, a later `cd` (which `||` may skip) makes it unknown."""
    try:
        pipelines = parse(command)
    except Unverifiable:
        bad = forbidden_anywhere(command)
        if bad:
            return f"{bad} (in: {command})"
        raise
    unclear = ""
    for index, pipeline in enumerate(pipelines):
        for position, (words, redirs) in enumerate(pipeline):
            if _setup_kind(words, position) == OK and all(safe for _, _, safe in redirs):
                continue
            words = words[1:] if words[0] == "command" else words
            if not words or words[0].startswith("-") or re.match(r"^[A-Za-z_]\w*=", words[0]):
                unclear = unclear or "command option or VAR=value prefix"
                continue
            if not position and len(pipeline) == 1 and words[0] == "cd":
                # only the first command's cd is sure to run: `a || cd x` may skip it (zd3 r1 F3)
                cwd = _cd(words, cwd) if index == 0 else LOST_CWD
            kind = _filter_kind(words) if position \
                else _first_kind(words, background, skill_root, grant, cwd)
            if kind == VIOLATION:
                return " ".join(words)
            if kind == UNVERIFIABLE or any(not safe for _, _, safe in redirs):
                unclear = unclear or f"not plainly recognised: {' '.join(words)}"
    simple = [w[1:] if w and w[0] == "command" else w for p in pipelines for w, _ in p]
    if len(simple) > 1:  # a merge-flow command runs alone in its call (Codex r1 F7)
        for words in simple:
            if words and words[0] == "git" and git_subcommand(words[1:]) in MERGE_SUBS:
                return f"{' '.join(words)} (a merge-flow git command runs alone in its call)"
    if unclear:
        raise Unverifiable(unclear)
    return None


# ---------------------------------------------------------------- paths

def _resolve(path: str, root: Path) -> Path:
    candidate = Path(os.path.expanduser(path))
    if not candidate.is_absolute():
        candidate = root / candidate
    return Path(os.path.realpath(candidate))


def _inside(path: Path, base: Path) -> bool:
    return path == base or base in path.parents


def _writable(path: Path, root: Path) -> bool:
    """ДЛ1 edits: run state, TODO files at the repo root, docs and the local settings. A plugin
    skill file (SKILL.md, anything under a `skills` directory) is product code: agent work."""
    real_root = Path(os.path.realpath(root))
    if _inside(path, real_root / "tmp" / "captain") \
            or path == real_root / ".claude" / "settings.local.json":
        return True
    if path.parent == real_root and todo_name(path.name):
        return True
    docs = real_root / "docs"
    # names compared in lower case: a case-insensitive disk opens docs/SKILL.MD (kp1 r1 F5)
    return _inside(path, docs) and path != docs and path.suffix.lower() in DOC_SUFFIXES \
        and path.name.lower() != "skill.md" \
        and "skills" not in (part.lower() for part in path.relative_to(docs).parts)


MEMORY_DIR = ".agent-memory"


def _lexical(path: str, base: Path) -> Path:
    """The path as written, made absolute and normalized, with no symlink resolved."""
    candidate = Path(os.path.expanduser(path))
    if not candidate.is_absolute():
        candidate = base / candidate
    return Path(os.path.normpath(candidate))


def _memory_file_name(path: Path) -> bool:
    return path.parent.name.lower() == MEMORY_DIR and path.suffix.lower() == ".md" \
        and path.name.lower() != "readme.md"


def _agent_memory_file(lexical: Path, real: Path, root: Path) -> bool:
    """ПТ1: main writes `.agent-memory/<topic>.md` of the repo or of the captain run worktree.
    Both the written path and its realpath must name a flat `.md` file (never README.md) in an
    existing, real `.agent-memory/` directory; so `.claude/rules/project-memory/` (the same
    files through a symlink), agent worktrees and repos without memory stay ДЛ2."""
    if not (_memory_file_name(lexical) and _memory_file_name(real)):
        return False
    if os.path.islink(lexical.parent) or not lexical.parent.is_dir():
        return False
    real_root = Path(os.path.realpath(root))
    owner = real.parent.parent
    run_worktree = owner.parent == real_root / ".claude" / "worktrees" \
        and owner.name.startswith("captain-run-")
    memory = owner / real.parent.name
    return (owner == real_root or run_worktree) and memory.is_dir() \
        and not os.path.islink(memory) \
        and Path(os.path.realpath(lexical.parent)) == memory


def todo_name(name: str) -> bool:
    """A TODO file at the repo root: `TODO` or `TODO*` with a doc suffix, never a source,
    script or config file such as TODO.py (Codex kp1 r1 F3)."""
    return name.startswith("TODO") and (Path(name).suffix.lower() in DOC_SUFFIXES
                                        or Path(name).suffix == "")


def _memory_path(value) -> bool:
    """The session's auto memory: <home>/.claude/projects/<project>/memory/<name>.md."""
    if not isinstance(value, str):
        return False
    expanded = os.path.expanduser(value)
    if not os.path.isabs(expanded) or ".." in Path(expanded).parts:
        return False
    path = Path(os.path.realpath(expanded))
    projects = Path(os.path.realpath(os.path.join(HOME, ".claude", "projects")))
    return path.suffix == ".md" and path.parent.name == "memory" \
        and path.parent.parent.parent == projects


def _setup_path(value: str, name: str, skill_root: Path) -> bool:
    """captain-setup's own files: absolute or ~ paths only, compared after resolving."""
    expanded = os.path.expanduser(value)
    if not os.path.isabs(expanded):
        return False
    real = os.path.realpath(expanded)
    if name == "Write":
        allowed = SETUP_WRITES
    else:
        template = Path(skill_root).parent / "captain-setup" / "notify.sh.tmpl"
        allowed = SETUP_READS | {str(template)}
    return real in {os.path.realpath(path) for path in allowed}


# ---------------------------------------------------------------- calls

def escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")


def _classify_path(name: str, tool_input: dict, root: Path | None, skill_root: Path,
                   cwd: Path | None = None):
    """Read, Glob and Grep pass anywhere except an agent output file (ДЛ4); Write passes on the
    ДЛ1 paths and captain-setup's own files."""
    key = {"Glob": "pattern", "Grep": "pattern"}.get(name, "file_path")
    value, base = tool_input.get(key), tool_input.get("path")
    if not isinstance(value, str) or not value or not isinstance(base, (str, type(None))):
        return UNVERIFIABLE, f"{name} without a valid {key}/path"
    if name == "Write" and not isinstance(tool_input.get("content"), str):
        return UNVERIFIABLE, "Write without content"
    if name in {"Read", "Write"} and (_setup_path(value, name, skill_root) or _memory_path(value)):
        return OK, ""
    if name != "Write":
        target = value if name == "Read" else base or ""
        if name == "Grep" and not base and cwd:  # a path-less Grep searches cwd (kp1 r2 F3)
            base = str(cwd)
        if target and agent_output(target) or name == "Grep" and _greps_outputs(tool_input, base):
            return VIOLATION, escape(f"an agent output_file (ДЛ4): {target or value}")
        return OK, ""
    return _classify_write(value, root, cwd)


def _greps_outputs(tool_input: dict, base: str | None) -> bool:
    """A Grep over a `tasks` directory or with a glob of output files reads them all (ДЛ4)."""
    pattern = tool_input.get("glob")
    if isinstance(pattern, str) and ".output" in pattern:
        return True
    if base and (Path(os.path.realpath(os.path.expanduser(base))).name == "tasks"
                 or Path(os.path.expanduser(base)).name == "tasks"):
        return True
    return bool(base) and _holds_outputs(Path(os.path.realpath(os.path.expanduser(base))))


MAX_WALK_DIRS = 5000


def temp_roots() -> set[Path]:
    """Where agent output files live: the system and Claude temp directories."""
    roots = {"/tmp", tempfile.gettempdir(), os.environ.get("TMPDIR"),
             os.environ.get("CLAUDE_CODE_TMPDIR")}
    return {Path(os.path.realpath(r)) for r in roots if r}


def _holds_outputs(base: Path) -> bool:
    """A recursive Grep over a directory above a `tasks/*.output` file reads it (kp1 r1 F4).
    Only temp directories are walked; a walk too large to finish counts as holding one."""
    seen = 0
    for root in temp_roots():
        if _inside(root, base):
            start = root
        elif _inside(base, root):
            start = base
        else:
            continue
        for directory, _, files in os.walk(start):
            seen += 1
            if seen > MAX_WALK_DIRS:
                return True
            if os.path.basename(directory) == "tasks" and any(f.endswith(".output") for f in files):
                return True
    return False


def _classify_write(value: str, root: Path | None, cwd: Path | None):
    if root is None:
        return UNVERIFIABLE, f"no repo root to check {escape(value)}"
    real = _resolve(value, cwd or root)  # relative to the record's cwd (C33)
    ok = _writable(real, root) or _agent_memory_file(_lexical(value, cwd or root), real, root)
    return (OK, "") if ok else (VIOLATION, escape(value))


def _classify_edit(tool_input: dict, root: Path | None, cwd: Path | None):
    """Edit: the auto memory and the ДЛ1 paths (run state, TODO, docs, local settings)."""
    value = tool_input.get("file_path")
    if _memory_path(value):
        return OK, ""
    if not isinstance(value, str) or not value or not all(
            isinstance(tool_input.get(k), str) for k in ("old_string", "new_string")):
        return UNVERIFIABLE, "Edit without a valid file_path/old_string/new_string"
    return _classify_write(value, root, cwd)


def classify(name: str, tool_input, root: Path | None, skill_root: Path,
             cwd: Path | None = None, grant: str | None = None) -> tuple[str, str]:
    """Return (OK | VIOLATION | UNVERIFIABLE, the part to print). `grant` is the branch the
    owner named in `/captain merge <branch>`: main may switch to it and push it."""
    if not isinstance(name, str) or not name:
        return UNVERIFIABLE, "tool call without a name"
    if not isinstance(tool_input, dict):
        return UNVERIFIABLE, "tool call without input"
    if name in REQUIRED_INPUT:
        want = (list,) if name == "AskUserQuestion" else (str,)
        missing = [k for k in REQUIRED_INPUT[name]
                   if not isinstance(tool_input.get(k), want) or not tool_input.get(k)]
        any_of = ANY_OF_INPUT.get(name)
        if missing or (any_of and not any(isinstance(tool_input.get(k), str) and tool_input.get(k)
                                          for k in any_of)):
            return UNVERIFIABLE, f"{name} without {', '.join(missing or any_of)}"
        return OK, ""
    if name == "Skill":
        skill = tool_input.get("skill")
        if not isinstance(skill, str) or not skill:
            return UNVERIFIABLE, "Skill without a valid skill name"
        return (OK, "") if skill in ALLOWED_SKILLS else (VIOLATION, escape(skill))
    if name == "Bash":
        command, background = tool_input.get("command"), tool_input.get("run_in_background", False)
        if not isinstance(command, str) or not isinstance(background, bool):
            return UNVERIFIABLE, "Bash without a valid command/run_in_background"
        timeout = tool_input.get("timeout")
        if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) \
                and timeout > MAX_TIMEOUT_MS:
            return VIOLATION, escape(f"a timeout above 120 s is agent work (ДЛ2): {command}")
        if background and not BACKGROUND_TIMER.match(command):
            return VIOLATION, escape(f"run_in_background is agent work (ДЛ2): {command}")
        if any(token == ("OP", "&") for token in _Lexer(command, strict=False).run()):
            return VIOLATION, escape(f"a shell `&` runs in the background: agent work (ДЛ2): {command}")
        try:
            bad = bash_violation(command, background, skill_root, grant, cwd)
        except Unverifiable as error:
            return UNVERIFIABLE, f"{error}: {escape(command)}"
        return (OK, "") if bad is None else (VIOLATION, escape(bad))
    if name in {"Read", "Write", "Glob", "Grep"}:
        return _classify_path(name, tool_input, root, skill_root, cwd)
    if name == "Edit":
        return _classify_edit(tool_input, root, cwd)
    if name == "Artifact" and tool_input.get("action") == "open":
        url = tool_input.get("url")
        return (OK, "") if isinstance(url, str) and url else (UNVERIFIABLE, "Artifact open without url")
    return VIOLATION, escape(json.dumps(tool_input, ensure_ascii=False)[:200])


_TOPLEVEL: dict[str, Path | None] = {}


def repo_root(cwd) -> Path | None:
    if not isinstance(cwd, str) or not cwd:
        return None
    if cwd not in _TOPLEVEL:
        try:
            out = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                                 capture_output=True, text=True, timeout=10)
            _TOPLEVEL[cwd] = Path(out.stdout.strip()) if out.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            _TOPLEVEL[cwd] = None
    return _TOPLEVEL[cwd]


BLOCK_FIELDS = {"text": ("text", str), "thinking": ("thinking", str),
                "redacted_thinking": ("data", str), "tool_use": ("input", dict),
                "image": ("source", dict)}


def _block_ok(block) -> bool:
    """Only known assistant content block types, each with its required field."""
    if not isinstance(block, dict) or not isinstance(block.get("type"), str) \
            or block["type"] not in BLOCK_FIELDS:
        return False
    field, kind = BLOCK_FIELDS[block["type"]]
    if block["type"] == "tool_use" and not isinstance(block.get("name"), str):
        return False
    return isinstance(block.get(field), kind)


OWNER_SLASH = re.compile(r"^\s*/(?:captain:)?captain(?=\s|$)(.*)$", re.S)
# the slash-command envelope Claude Code records, only at the start of the text (Codex r1 F5)
COMMAND_TAGS = re.compile(r"^\s*(?:<command-message>[^<]*</command-message>\s*)?"
                          r"<command-name>/(?:captain:)?captain</command-name>\s*"
                          r"<command-args>([^<]*)</command-args>\s*$")
NOT_A_START = {"off", "merge", "base", "resume", "end"}
GRANT_MAX_SECONDS = 12 * 3600  # a backstop for a forgotten `captain end` call
# when the merge grant ends; hooks/guard.py puts it in its denial text
GRANT_ENDS = ("`/captain off`, a new `/captain` start, a new `/captain merge <branch>`, the "
              "`captain end` call before the end report (R17), or 12 hours after the grant")


def first_word(args: str) -> str:
    words = args.split()
    return words[0].lower() if words else ""


START_WORD = re.compile(r"^((\d+h)?(\d+m)?|\d+|away|experiment|експеримент|base=\S+)$", re.I)


def starts_run(args: str) -> bool:
    """A new `/captain` start: `[<timebox>] [away] [experiment] [base=<branch>]` or no
    arguments (SKILL.md Arguments). Free text (a question, a resume note) keeps the run."""
    return all(START_WORD.match(word) for word in args.split())


def ends_grant(args: str, typed: bool = True) -> bool:
    """The `/captain <args>` that end the merge grant (МГ1), the one place for the end signals
    of the live guard and this audit. Typed by the owner: `off`, a new start and a new `merge`
    (which then grants its own branch), `end`. Made by the model (a Skill call): `end`, right
    before the end report (R17), a hook cannot see the report itself; `off`; a new start. A
    model call never creates a grant. Free text (a question) and base/resume keep it."""
    word = first_word(args)
    return word in {"end", "off"} or (typed and word == "merge") or starts_run(args)


def owner_captain_args(entry: dict) -> str | None:
    """The arguments of a `/captain ...` the owner typed in this user record, else None."""
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        content = "".join(b.get("text", "") for b in content
                          if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(content, str):
        return None
    match = COMMAND_TAGS.match(content) or OWNER_SLASH.match(content)
    return match.group(1) if match else None


def epoch(timestamp) -> float | None:
    try:
        return datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def next_grant(grant: tuple | None, args: str, repo: str | None, timestamp,
               typed: bool = True) -> tuple | None:
    """The merge grant (branch, repo, since) after `/captain <args>` in `repo`: typed by the
    owner, or a model Skill call (`typed=False`, which only ends one); a grant without a
    readable time counts for nothing. hooks/guard.py keeps the same rule live."""
    if not ends_grant(args, typed):
        return grant
    words, since = args.split(), epoch(timestamp)
    if typed and len(words) == 2 and words[0] == "merge" and repo and since is not None:
        return words[1], repo, since
    return None


def active_grant(grant: tuple | None, repo: str | None, timestamp) -> str | None:
    """The granted branch for a call in `repo`, else None: a grant does not cross repos and
    ends GRANT_MAX_SECONDS after it was typed."""
    now = epoch(timestamp)
    if not grant or not repo or grant[1] != repo or now is None:
        return None
    return grant[0] if now - grant[2] <= GRANT_MAX_SECONDS else None


_COMMON: dict[str, str | None] = {}


def common_dir(directory: str) -> str | None:
    """The git common dir (real path): one identity for every worktree of a repository, the
    same key hooks/guard.py binds the grant to (Codex kp1 r1 F9)."""
    if directory not in _COMMON:
        try:
            out = subprocess.run(["git", "-C", directory, "rev-parse", "--path-format=absolute",
                                  "--git-common-dir"], capture_output=True, text=True, timeout=10)
            _COMMON[directory] = os.path.realpath(out.stdout.strip()) \
                if out.returncode == 0 and out.stdout.strip() else None
        except (OSError, subprocess.SubprocessError):
            _COMMON[directory] = None
    return _COMMON[directory]


def record_repo(entry: dict, repo: Path | None) -> str | None:
    """The repository of a record: the git common dir of --repo, else of its cwd, else the
    path itself."""
    place = str(repo) if repo else entry.get("cwd")
    if not isinstance(place, str) or not place:
        return None
    return common_dir(place) or place


def carried_grant_call(name, tool_input, root: Path | None, skill_root: Path,
                       cwd: Path | None = None) -> bool:
    """A merge-flow `git switch`/`git push` that a grant for its own branch would allow: after
    an R21 `/captain resume` it may run on a grant carried from the predecessor, which this
    transcript cannot show (kp1 r2 F4). A call no grant allows (a force push) is no such call
    (АУ1)."""
    command = tool_input.get("command") if name == "Bash" and isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return False
    try:
        pipelines = parse(command)
    except Unverifiable:
        return False
    for pipeline in pipelines:
        for words, _ in pipeline:
            words = words[1:] if words and words[0] == "command" else words
            if len(words) > 2 and words[0] == "git" \
                    and git_subcommand(words[1:]) in {"switch", "push"}:
                return classify(name, tool_input, root, skill_root, cwd, words[-1])[0] == OK
    return False


def audit(lines, repo: Path | None, skill_root: Path):
    """Return (rows, stats); a row is (kind, timestamp, tool, detail)."""
    stats = {"json": 0, "malformed": 0, "records": 0, "calls": 0}
    rows = []
    grant = None  # (branch, repo, since) of the owner's last `/captain merge <branch>`
    resumed = typed_grant = False  # an R21 successor may hold a carried grant
    for raw in lines:
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            stats["malformed"] += 1
            continue
        stats["json"] += 1
        kind = entry.get("type") if isinstance(entry, dict) else None
        if not isinstance(kind, str) or kind not in RECORD_TYPES:
            stats["malformed"] += 1
            rows.append((UNVERIFIABLE, "?", "record", escape(f"unknown record type {kind!r}")))
            continue
        stats["records"] += 1
        if kind == "user" and entry.get("isSidechain") is not True:
            args = owner_captain_args(entry)
            resumed = resumed or (args is not None and first_word(args) == "resume")
            resumed = resumed and not (args is not None and ends_grant(args))  # АУ1 F3
            typed_grant = typed_grant or (args is not None and first_word(args) == "merge")
            grant = grant if args is None else next_grant(grant, args, record_repo(entry, repo),
                                                          entry.get("timestamp"))
        if kind != "assistant" or entry.get("isSidechain") is True:
            continue
        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        timestamp = str(entry.get("timestamp", "?"))
        if isinstance(content, str):
            continue
        if not isinstance(content, list):
            rows.append((UNVERIFIABLE, timestamp, "record", "assistant record without content"))
            continue
        root = repo or repo_root(entry.get("cwd"))
        cwd = Path(entry["cwd"]) if isinstance(entry.get("cwd"), str) and entry["cwd"] else None
        for block in content:
            if not _block_ok(block):
                shown = block.get("type") if isinstance(block, dict) else type(block).__name__
                rows.append((UNVERIFIABLE, timestamp, "record",
                             escape(f"unknown or incomplete content block {shown!r}")))
                continue
            if block.get("type") == "tool_use":
                stats["calls"] += 1
                name = block.get("name")
                result, detail = classify(name, block.get("input"), root, skill_root, cwd,
                                          active_grant(grant, record_repo(entry, repo), timestamp))
                tool_input = block.get("input")
                if name == "Skill" and tool_input.get("skill") in ("captain", "captain:captain"):
                    args = tool_input.get("args")
                    args = args if isinstance(args, str) else ""
                    grant = next_grant(grant, args, None, timestamp, typed=False)
                    resumed = resumed and not ends_grant(args, typed=False)  # АУ1 F3
                if result == VIOLATION and resumed and not typed_grant \
                        and carried_grant_call(name, tool_input, root, skill_root, cwd):
                    result, detail = UNVERIFIABLE, f"grant may be carried, R21: {detail}"
                if result != OK:
                    shown = name if isinstance(name, str) and name else "?"
                    rows.append((result, timestamp, shown, detail))
    return rows, stats


def parse_args(argv: list[str]):
    options, positional, i = {"--repo": None, "--skill-root": None}, [], 0
    while i < len(argv):
        if argv[i] in options and i + 1 < len(argv):
            options[argv[i]] = Path(argv[i + 1])
            i += 2
        else:
            positional.append(argv[i])
            i += 1
    return options["--repo"], options["--skill-root"] or SKILL_ROOT, positional


def main(argv: list[str]) -> int:
    if argv and argv[0] in {"-h", "--help"}:
        print(__doc__.strip())
        return 0
    repo, skill_root, positional = parse_args(argv)
    if len(positional) != 1:
        print("usage: audit-main.py [--repo <root>] [--skill-root <dir>] <session.jsonl | ->",
              file=sys.stderr)
        return 2
    path = positional[0]
    if path != "-" and "subagents" in Path(path).parts:
        print(f"error: {path} is a subagent transcript; give the main session file", file=sys.stderr)
        return 2
    try:
        if path == "-":
            rows, stats = audit(sys.stdin, repo, skill_root)
        else:
            with open(path, encoding="utf-8", errors="replace") as handle:
                rows, stats = audit(handle, repo, skill_root)
    except OSError as error:
        print(f"error: cannot read {path}: {error}", file=sys.stderr)
        return 2
    if stats["json"] == 0:
        print(f"error: {path} has no JSON lines; not a transcript", file=sys.stderr)
        return 2
    for kind, timestamp, name, detail in rows:
        print(f"{kind} {timestamp}  {name}: {detail}")
    violations = sum(1 for row in rows if row[0] == VIOLATION)
    unverifiable = len(rows) - violations
    scope = f"{stats['calls']} main-session tool call(s), {stats['malformed']} malformed line(s)"
    if violations:
        print(f"FAIL: {violations} violation(s), {unverifiable} unverifiable; {scope}")
        return 1
    if unverifiable or stats["malformed"] or stats["records"] == 0:
        print(f"incomplete audit: {unverifiable} unverifiable, no violation found in the part "
              f"that could be checked; {scope}")
        return 3
    print(f"PASS: audit complete, no violations; {scope}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
