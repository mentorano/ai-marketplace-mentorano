#!/usr/bin/env python3
"""Keep a captain session a coordinator (R1) for the whole session, not only the time box.

Wired in hooks.json to three events; reads the hook JSON on stdin:
  - UserPromptSubmit: a prompt that starts with `/captain` or `/captain:captain` turns
    captain mode on for this session; with the argument `off` it turns it off.
  - PostToolUse (Skill): the same for a Skill call of `captain` or `captain:captain` made by
    the main session (the owner named the skill in words, e.g. "Captain, ...", "stop the captain").
  - PreToolUse: while captain mode is on, a main-session tool call outside the R1 light work
    (DL1: reads, search, git inspection, short read-only commands, edits of run state, TODO,
    docs and the local settings) is agent work (DL2) and is denied, with the reason fed back
    to the model. The allow-list is the one scripts/audit-main.py checks after a run
    (`classify`), so the live guard and the audit agree. Subagent calls (they carry
    `agent_id`) always pass.

The merge flow (R1, R10) gets live checks the audit cannot make afterwards: a merge-flow git
command runs alone in its Bash call; `merge` and `commit --no-edit` land only on an allowed
HEAD: a `captain/*` branch, the run's base branch for the same repository (set by the owner
with a typed `/captain base <branch>` or `base=<branch>` among the start arguments, or by the
model's Skill call `captain base <branch>` when the auto-base conditions AB1–AB6 hold, see
`auto_base_problem`), or the branch of a live grant; never on a detached HEAD, and
main/master/the origin default branch only with the grant. `commit --no-edit` and `merge --abort` only while a merge is in
progress; `switch` and `push` only for the branch the owner named in a typed
`/captain merge <branch>`. The grant is bound to the repository (git common dir), the branch
and the run, and ends at `/captain off`, a new `/captain` start or a new `/captain merge`
(audit-main.py `ends_grant` is the one place for these signals). The grant comes only from
UserPromptSubmit: a Skill call made by the model never records it; the base is never
main/master/the origin default. The source of a merge is a local branch, or the remote-tracking
`origin/<default>` (`--no-ff --no-edit` or `--ff-only` into a `captain/*` or base HEAD,
`--ff-only` only into a granted HEAD).

A deny caused by the command form or the checkout state names the canonical forms and says to
fix the form; only a protected HEAD or a missing grant tells the coordinator to ask the owner.

Captain mode is a marker file per session: ~/.claude/captain/sessions/<session_id>
(CAPTAIN_STATE_DIR overrides the directory). The end of the time box (R17) does not remove
it; only `/captain off` does. After a handoff (R21) the owner's /clear starts a new session with
no marker: the first message `/captain resume` starts with `/captain`, so the same prompt rule
turns the mode back on for the successor, and takes over the predecessor's live grant and
recorded base (`carry_grant`: same repository and working directory, the run ID carried, never
a new grant).

Like the audit, this is a guard against the coordinator's own habits, not a security
boundary. Bad or unknown input never blocks anything: the hook exits 0 without output.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILL_ROOT = PLUGIN_ROOT / "skills" / "captain"
CAPTAIN_SKILLS = {"captain", "captain:captain"}
SLASH = re.compile(r"^\s*/(?:captain:)?captain(?=\s|$)(.*)$", re.S)
SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
REASON = ("This is agent work (R1, DL2): delegate it to a captain:runner or the writer that "
          "owns the file. Captain mode is on in this session, also after the time box ended. "
          "Main does inline only the DL1 light work of reference/tools.md: Read, Grep, Glob, "
          "read-only commands (cat, head, tail, wc, ls, find, date, stat, ps), git inspection, "
          "Write or Edit of tmp/captain/, TODO, docs/ and .claude/settings.local.json, and the "
          "merge flow; never an agent's output_file (DL4). A denial means delegate, never "
          "rewrite the call. Only the owner ends captain mode, with `/captain off`. "
          "Blocked: {detail}")
MERGE_REASON = ("Captain merge flow (R1, R10): {detail}. The allowed forms are in "
                "reference/tools.md, one per Bash call. Merge or push into main, master or the "
                "default branch only after the owner types `/captain merge <branch>`; ask the "
                "owner once, with that exact text. The grant holds for this run, in this "
                "repository and for that branch only, and ends at {ends}. Never rewrite the "
                "command around this.")
FORM_REASON = ("Captain merge flow (R1, R10): {detail}. This is the command form or the checkout "
               "state, not a missing permission. The canonical forms (reference/tools.md), each "
               "alone in its Bash call: `git -C '<abs dir>' merge --no-ff --no-edit <branch>`; "
               "`git -C '<abs dir>' commit --no-edit` (only while a merge is in progress); "
               "`git -C '<abs dir>' merge --abort`. A merge lands only on the run's working branch "
               "(captain/* or the run's base). Fix the form and retry once. Never rewrite the "
               "command around this.")
MERGE_ARGS = re.compile(r"^\s*merge\s+(\S+)\s*$")
BASE_ARGS = re.compile(r"^\s*base\s+(\S+)\s*$")
BASE_START = re.compile(r"(?:^|\s)base=(\S+)(?=\s|$)")
BRANCH_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
WRITERS = {"cp", "mv", "tee", "ln", "install", "rsync", "touch", "dd", "truncate", "rm", "sed"}
GRANT_MAX_SECONDS = 12 * 3600  # audit-main.py keeps the same backstop
STATE_DENIAL = ("{name}: the captain state files are written only by the guard, from "
                "`/captain` commands")
FETCH_SECONDS = 15  # AB2; hooks.json gives the PostToolUse entry 30 s in all
REMOTE_SECONDS = 10
RUN_STATE = "tmp/captain"  # the run's own state, written before start step 5 (AB6)
LOCAL_SETTINGS = ".claude/settings.local.json"  # start step 3 writes it (AB6)


def state_dir() -> Path:
    override = os.environ.get("CAPTAIN_STATE_DIR")
    return Path(override) if override else Path.home() / ".claude" / "captain" / "sessions"


def grant_file(session: str) -> Path:
    return state_dir() / f"{session}.merge"


def set_grant(session: str, args: str, cwd: str) -> None:
    """`/captain merge <branch>` typed by the owner in a repository: main may switch to, merge
    into and push that branch of that repository for the rest of the run (MG1)."""
    match = MERGE_ARGS.match(args)
    if not match or not cwd or not os.path.isabs(cwd):
        return
    identity, run = repo_identity(cwd), current_run(session)
    if identity is None or run is None:
        return
    grant_file(session).write_text(json.dumps({"branch": match.group(1), "common_dir": identity[1],
                                               "run": run, "since": int(time.time())}) + "\n",
                                   encoding="utf-8")


def end_grant(session: str) -> None:
    grant_file(session).unlink(missing_ok=True)


def granted_branch(session: str, directory: str | None = None) -> str | None:
    """The granted branch of this run, else None; with `directory`, only when that checkout
    belongs to the repository the grant was typed in (a grant does not cross repos)."""
    try:
        grant = json.loads(grant_file(session).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(grant, dict) or not all(isinstance(grant.get(k), str)
                                              for k in ("branch", "common_dir", "run")) \
            or grant["run"] != current_run(session) or not isinstance(grant.get("since"), int) \
            or time.time() - grant["since"] > GRANT_MAX_SECONDS:
        return None
    if directory is not None:
        identity = repo_identity(directory)
        if identity is None or identity[1] != grant["common_dir"]:
            return None
    return grant["branch"]


def carry_grant(session: str, cwd: str) -> None:
    """R21 handoff: `/captain resume` in a new session takes over the run it continues. The
    candidates are the other sessions with a marker for the same working directory that hold a
    live grant (valid under that session's own run ID, typed in the same repository, the git
    common dir) or a live base (`live_base`, GN2). With exactly one candidate the successor
    takes its run ID, its grant and its base, with their original time; the predecessor's copies
    are removed, so a grant or a base is never held twice and never carried twice. Two or more
    candidates (ZD2 r1 F1: also one grant beside another session's live base) → nothing; the
    owner types `/captain merge <branch>` or `/captain base <branch>` again. A carry never creates a grant
    (MG1). The pick is by cwd and repository, not by run ID: one captain run per checkout is
    assumed, and a second or stale run there may lend its grant or base (GN1, accepted)."""
    identity = repo_identity(cwd) if cwd and os.path.isabs(cwd) else None
    if identity is None:
        return
    grants, bases = {}, {}
    for other, marker in same_cwd_sessions(session, cwd):
        try:
            grant = json.loads(grant_file(other).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            grant = None
        if isinstance(grant, dict) and granted_branch(other) is not None \
                and grant.get("common_dir") == identity[1]:
            grants[other] = grant
        base = live_base(other, marker, identity[1])
        if base is not None:
            bases[other] = base
    candidates = set(grants) | set(bases)
    if len(candidates) != 1:
        return
    other = candidates.pop()
    marker_path = state_dir() / session
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["run"] = current_run(other)  # a live grant and a live base both match it
    marker_path.write_text(json.dumps(marker) + "\n", encoding="utf-8")
    if other in grants:
        grant_file(session).write_text(json.dumps(grants[other]) + "\n", encoding="utf-8")
        end_grant(other)
    if other in bases:
        base_file(session).write_text(json.dumps(bases[other]) + "\n", encoding="utf-8")
        base_file(other).unlink(missing_ok=True)


def same_cwd_sessions(session: str, cwd: str) -> list[tuple[str, dict]]:
    """(session ID, marker) of every other captain session whose marker names `cwd`."""
    found = []
    for path in state_dir().iterdir() if state_dir().is_dir() else ():
        other = path.name
        if other == session or not SESSION_ID.match(other) or not path.is_file():
            continue
        try:
            marker = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(marker, dict) and isinstance(marker.get("cwd"), str) and marker["cwd"] \
                and os.path.realpath(marker["cwd"]) == os.path.realpath(cwd):
            found.append((other, marker))
    return found


def live_base(other: str, marker: dict, common_dir: str) -> dict | None:
    """The base `other` recorded in its current run for the repository `common_dir`, within
    GRANT_MAX_SECONDS, else None. A marker is removed only by `/captain off`, so an abandoned
    session keeps its base; the run and the age keep such a base from being carried (GN2)."""
    try:
        base = json.loads(base_file(other).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(base, dict) or not isinstance(base.get("branch"), str) \
            or base.get("common_dir") != common_dir or not isinstance(base.get("run"), str) \
            or base["run"] != marker.get("run") or not isinstance(base.get("since"), int) \
            or time.time() - base["since"] > GRANT_MAX_SECONDS:
        return None
    return base


def base_file(session: str) -> Path:
    return state_dir() / f"{session}.base"


def repo_identity(directory: str) -> tuple[str, str] | None:
    """(toplevel, git common dir) of the checkout at `directory`, both real paths; the common
    dir is the same for every worktree of one repository."""
    top = git_out(directory, "rev-parse", "--show-toplevel")
    common = git_out(directory, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not top or not common:
        return None
    return os.path.realpath(top), os.path.realpath(common)


def base_arg(args: str) -> str | None:
    """The branch of `base <branch>` or `base=<branch>` in the arguments, when it is a valid
    branch name, else None."""
    match = BASE_ARGS.match(args) or BASE_START.search(args)
    if not match:
        return None
    branch = match.group(1)
    if not BRANCH_NAME.match(branch) or ".." in branch or branch.endswith((".", "/", ".lock")):
        return None
    return branch


def set_base(session: str, args: str, cwd: str, typed: bool = True) -> str | None:
    """Record the run's base branch: main may merge into it without a grant. Typed by the owner
    (`/captain base <branch>`, or `base=<branch>` among the start arguments): any branch. Made
    by the model (a Skill call `captain base <branch>`, BR1): only while AB1–AB6 hold, checked
    now. main, master and the origin default are never recorded (they stay behind the grant).
    Returns a line for the model on the Skill path, else None."""
    branch = base_arg(args)
    if branch is None or not cwd or not os.path.isabs(cwd):
        return None
    identity = repo_identity(cwd)
    if identity is None:
        return None
    if not typed:
        problem = auto_base_problem(cwd, branch)
        if problem:
            return (f"captain guard: base `{branch}` NOT recorded ({problem}). No automatic "
                    "base: present → one question to the owner (a typed `/captain base "
                    "<branch>` sets it); away → bootstrap makes a new captain/* branch.")
    elif protected(cwd, branch):
        return None
    state_dir().mkdir(parents=True, exist_ok=True)
    base_file(session).write_text(json.dumps({"branch": branch, "repo": identity[0],
                                              "common_dir": identity[1],
                                              "auto": not typed, "run": current_run(session),
                                              "since": int(time.time())}) + "\n",
                                  encoding="utf-8")
    return None if typed else (f"captain guard: base `{branch}` recorded (AB1–AB6 hold).")


def auto_base_problem(directory: str, branch: str) -> str | None:
    """Why `branch` cannot become the run's base from a model Skill call now, else None (BR1).
    Every condition is checked at this moment, never from a cache; HEAD is read again after
    the network calls, right before the record (review r1 F1)."""
    head = head_branch(directory)
    if head is None:
        return "AB1: HEAD is detached or unreadable"
    if head != branch:
        return f"AB1: HEAD is `{head}`, not `{branch}`"
    if origin_default(directory) is None:  # protected() would let captain/* through
        return "AB1: origin/HEAD is unreadable, the default branch is unknown"
    remote = remote_state(directory, branch)  # the default origin names now (r1 F2)
    if remote is None:
        return "AB2: `git ls-remote --symref origin HEAD` failed or named no default branch"
    default, remote_branch = remote
    if protected(directory, branch) or branch == default:
        return f"AB1: `{branch}` is main, master or the origin default"
    tip = fetched_tip(directory, default)
    if tip is None:
        return f"AB2: `git fetch origin {default}` failed"
    if git_out(directory, "rev-parse", "-q", "--verify", "HEAD^{commit}") != tip:
        return f"AB3: HEAD is not the fetched origin/{default} ({tip[:12]})"
    if remote_branch and remote_branch != tip:
        return f"AB4: origin/{branch} exists on another commit"
    if checked_out_elsewhere(directory, branch):
        return f"AB5: `{branch}` is checked out in another worktree"
    problem = dirty_problem(directory)
    if problem:
        return problem
    if head_branch(directory) != branch \
            or git_out(directory, "rev-parse", "-q", "--verify", "HEAD^{commit}") != tip:
        return "AB1: HEAD moved during the check"
    return None


def head_branch(directory: str) -> str | None:
    """The branch HEAD names, else None (detached or unreadable)."""
    head = git_out(directory, "symbolic-ref", "-q", "HEAD")
    if not head or not head.startswith("refs/heads/"):
        return None
    return head[len("refs/heads/"):]


def dirty_problem(directory: str) -> str | None:
    """AB6: any change refuses, except untracked files of the run's own state under
    tmp/captain/ (main writes recon and run.md before start step 5; bootstrap adds the
    exclude only later) and an untracked .claude/settings.local.json (start step 3 writes it).
    A tracked change to either still refuses."""
    try:
        out = subprocess.run(["git", "-C", directory, "status", "--porcelain", "-z",
                              "--untracked-files=all"], capture_output=True, text=True,
                             timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "AB6: `git status` failed"
    if out.returncode != 0:
        return "AB6: `git status` failed"
    entries = out.stdout.split("\0")
    while entries:
        entry = entries.pop(0)
        if not entry:
            continue
        code, path = entry[:2], entry[3:]
        if "R" in code or "C" in code:
            entries.pop(0)  # the source path of a rename or copy
        if code != "??" or not (path.startswith(f"{RUN_STATE}/") or path == LOCAL_SETTINGS):
            return f"AB6: the working tree has changes ({code} {path})"
    return None


def git_env() -> dict:
    """No terminal prompt for a password can hang the hook; the timeouts bound the rest."""
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def fetched_tip(directory: str, default: str) -> str | None:
    """AB2: `git fetch origin <default>` into a ref of its own, so no other fetch can change
    the SHA it compares (FETCH_HEAD is shared, review r1 F3); the SHA, else None."""
    ref = f"refs/captain-guard/fetch-{os.getpid()}-{os.urandom(4).hex()}"
    try:
        out = subprocess.run(["git", "-C", directory, "fetch", "--quiet", "--no-tags", "origin",
                              f"+refs/heads/{default}:{ref}"], capture_output=True, text=True,
                             timeout=FETCH_SECONDS, env=git_env())
        if out.returncode != 0:
            return None
        return git_out(directory, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}")
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        git_out(directory, "update-ref", "-d", ref)


def remote_state(directory: str, branch: str) -> tuple[str, str] | None:
    """(the default branch origin names now, the SHA of `branch` on origin or "") from one
    `git ls-remote --symref origin HEAD refs/heads/<branch>`; None when origin cannot be read
    or names no default branch."""
    try:
        out = subprocess.run(["git", "-C", directory, "ls-remote", "--symref", "origin", "HEAD",
                              f"refs/heads/{branch}"], capture_output=True, text=True,
                             timeout=REMOTE_SECONDS, env=git_env())
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    default, sha = None, ""
    for line in out.stdout.splitlines():
        value, _, ref = line.partition("\t")
        if ref == "HEAD" and value.startswith("ref: refs/heads/"):
            default = value[len("ref: refs/heads/"):]
        elif ref == f"refs/heads/{branch}":
            sha = value
    return (default, sha) if default else None


def checked_out_elsewhere(directory: str, branch: str) -> bool:
    """AB5: another worktree of this repository has `branch` checked out. `-z` keeps paths
    with quotes or newlines verbatim (review r1 F5)."""
    listing = git_out(directory, "worktree", "list", "--porcelain", "-z")
    top = git_out(directory, "rev-parse", "--show-toplevel")
    if listing is None or not top:
        return True
    here, path = os.path.realpath(top), None
    for field in listing.split("\0"):
        if field.startswith("worktree "):
            path = os.path.realpath(field[len("worktree "):])
        elif field == f"branch refs/heads/{branch}" and path != here:
            return True
    return False


def recorded_base(session: str, directory: str) -> str | None:
    """The base branch the owner set for the repository of `directory`, else None."""
    try:
        base = json.loads(base_file(session).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(base, dict) or not isinstance(base.get("branch"), str) \
            or not isinstance(base.get("common_dir"), str):
        return None
    identity = repo_identity(directory)
    if identity is None or identity[1] != base["common_dir"]:
        return None
    return base["branch"]


def wants_off(args: str) -> bool:
    # only the whole argument: free-text Skill arguments may say "turn the debug flag off"
    return args.strip().lower() == "off"


def current_run(session: str) -> str | None:
    """The run ID in the session marker: a new `/captain` start makes a new one."""
    try:
        marker = json.loads((state_dir() / session).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    run = marker.get("run") if isinstance(marker, dict) else None
    return run if isinstance(run, str) and run else None


def set_mode(session: str, on: bool, cwd: str, start: bool = False) -> None:
    """Captain mode on or off. A start, or a marker without a run ID, gets a new run ID; any
    other `/captain` call (merge, base, resume) keeps the run."""
    directory = state_dir()
    marker = directory / session
    if not on:
        marker.unlink(missing_ok=True)
        end_grant(session)
        base_file(session).unlink(missing_ok=True)
        return
    run = None if start else current_run(session)
    directory.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"since": int(time.time()), "cwd": cwd,
                                  "run": run or os.urandom(8).hex()}) + "\n", encoding="utf-8")


def load_audit():
    spec = importlib.util.spec_from_file_location("audit_main",
                                                  SKILL_ROOT / "scripts" / "audit-main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def deny(detail: str, reason: str = REASON, ends: str = "") -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason.format(detail=detail, ends=ends),
    }}, ensure_ascii=False))


def git_out(directory: str, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", directory, *args], capture_output=True, text=True,
                             timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def protected(directory: str, head: str) -> bool:
    """main, master and the origin default are protected; with no readable origin/HEAD every
    branch outside captain/* is, since the default branch is unknown (Codex r1 F4)."""
    if head in {"main", "master"}:
        return True
    default = git_out(directory, "symbolic-ref", "-q", "refs/remotes/origin/HEAD")
    if not default or not default.startswith("refs/remotes/origin/"):
        return not head.startswith("captain/")
    return head == default[len("refs/remotes/origin/"):]  # full refs, never --short (r3 F14)


def merge_flow(audit, command: str) -> list[str] | None:
    """The git words (after `git`) of the merge-flow command in a call, else None."""
    for pipeline in audit.parse(command):
        for words, _ in pipeline:
            words = words[1:] if words and words[0] == "command" else words
            if words and words[0] == "git" and audit.git_subcommand(words[1:]) in audit.MERGE_SUBS:
                return words[1:]
    return None


def origin_default(directory: str) -> str | None:
    """The origin default branch name from refs/remotes/origin/HEAD, else None."""
    default = git_out(directory, "symbolic-ref", "-q", "refs/remotes/origin/HEAD")
    if not default or not default.startswith("refs/remotes/origin/"):
        return None
    return default[len("refs/remotes/origin/"):]


def merge_source(directory: str, rest: list[str]) -> tuple[str | None, str | None]:
    """(kind, problem) of the source of `merge <flags> <ref>`: kind `local` for a local branch,
    `origin` for the remote-tracking origin/<default>; problem is a form/state deny, else None."""
    ref, flags = rest[-1], rest[:-1]
    default = origin_default(directory)
    if default and ref == f"origin/{default}":
        remote = git_out(directory, "rev-parse", "-q", "--verify",
                         f"refs/remotes/origin/{default}^{{commit}}")
        named = git_out(directory, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}")
        if remote is None:
            return None, f"`{ref}` does not exist in {directory} (a runner fetches it first)"
        if named != remote:  # a local branch or tag named origin/<default> wins in git
            return None, f"`{ref}` is ambiguous: another ref of that name points elsewhere"
        if sorted(flags) not in (["--no-edit", "--no-ff"], ["--ff-only"]):
            return None, (f"merge `{ref}` only as `merge --no-ff --no-edit {ref}` or "
                          f"`merge --ff-only {ref}`")
        return "origin", None
    if "--ff-only" in flags:
        return None, f"`--ff-only` is only for `origin/<default>`, not for `{ref}`"
    branch = git_out(directory, "rev-parse", "-q", "--verify", f"refs/heads/{ref}^{{commit}}")
    named = git_out(directory, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}")
    if branch is None:
        return None, (f"`{ref}` is not a local branch (r2 F13: no SHA, tag, FETCH_HEAD or "
                      "remote ref other than origin/<default>)")
    if named != branch:  # a tag of the same name wins in git (r3 F15)
        return None, f"`{ref}` is ambiguous: another ref of that name points elsewhere"
    return "local", None


def merge_problem(audit, command: str, cwd: str | None, session: str) -> tuple[str, str] | None:
    """(why, reason template) an allowed merge-flow git command must not run now, else None.
    The template is FORM_REASON for a form or checkout-state problem and MERGE_REASON when the
    owner must act (protected HEAD, no grant). classify has already checked its form, and that
    it runs alone in its call (see the module docstring)."""
    args = merge_flow(audit, command)
    if args is None:
        return None
    directory = cwd
    while args[0].startswith("-"):
        if args[0] == "-C":  # git resolves each -C against the one before it (Codex r1 F2)
            if args[1].startswith("~"):  # quoted or not, the lexer cannot tell (r2 F12)
                return "write the -C directory as an absolute path, without ~", FORM_REASON
            directory = os.path.join(directory or "", args[1])
            args = args[2:]
        else:
            args = args[1:]
    if not directory or not os.path.isabs(directory):
        return "the working directory of this git command is unknown", FORM_REASON
    grant = granted_branch(session, directory)  # bound to this repository (MG1)
    sub, rest = args[0], args[1:]
    if sub in {"switch", "push"}:
        if rest[-1] != grant:
            return f"the owner has not allowed `{rest[-1]}` (git {sub})", MERGE_REASON
        if sub == "push" and (git_out(directory, "config", "--get-all", f"remote.{rest[0]}.push")
                              or git_out(directory, "config", "--bool", f"remote.{rest[0]}.mirror")
                              == "true"  # a mapping may push elsewhere (r2 F11)
                              or git_out(directory, "config", "--bool", "push.followTags")
                              == "true"):  # tags would go out too (r3 F16)
            return (f"remote `{rest[0]}` has a push mapping or mirror, or push.followTags is on; "
                    "push by hand"), MERGE_REASON
        return None
    source = None
    if sub == "merge" and rest != ["--abort"]:
        source, problem = merge_source(directory, rest)
        if problem:
            return problem, FORM_REASON
    merge_head = git_out(directory, "rev-parse", "--path-format=absolute", "--git-path",
                         "MERGE_HEAD")
    in_merge = bool(merge_head) and os.path.isfile(merge_head)  # the file, not a ref (r1 F8)
    if rest == ["--abort"]:
        return None if in_merge else (f"no merge is in progress in {directory}", FORM_REASON)
    if sub == "commit" and rest != ["--no-edit"]:  # the R18 TODO-only commit (kp1 r1 F8)
        problem = todo_commit_problem(directory, rest[3:], in_merge)
        if problem:
            return problem, FORM_REASON
    elif sub == "commit" and not in_merge:
        return f"no merge is in progress in {directory}", FORM_REASON
    head = git_out(directory, "symbolic-ref", "-q", "HEAD")
    if not head or not head.startswith("refs/heads/"):
        return f"HEAD is detached or unreadable in {directory}", FORM_REASON
    head = head[len("refs/heads/"):]
    # an allow-list, also for the commit (r1 F3): the grant, then captain/* or the base
    # protected first: a default branch named captain/* is no run branch (Codex r2 F3)
    guarded = protected(directory, head)
    run_branch = not guarded and (head.startswith("captain/")
                                  or head == recorded_base(session, directory))
    if head == grant:  # a granted run branch keeps both sync forms (Codex r1 F3)
        if source == "origin" and rest[0] != "--ff-only" and not run_branch:
            return (f"into the granted `{head}` only `merge --ff-only {rest[-1]}`",
                    FORM_REASON)
        return None
    if guarded:
        return f"HEAD is `{head}` in {directory}", MERGE_REASON
    if run_branch:
        return None
    return (f"HEAD `{head}` in {directory} is not the run's working branch (captain/* or the "
            "run's base)"), FORM_REASON


def todo_commit_problem(directory: str, files: list[str], in_merge: bool) -> str | None:
    """`commit -m <msg> -- <TODO file>...`: no merge in progress, -C names the top level, and
    each file is a regular file git already tracks (a new TODO file needs a runner's `git add`).
    Pathspec magic and globs are refused: the pathspec must name exactly that file."""
    if in_merge:
        return f"a merge is in progress in {directory}: conclude it with `commit --no-edit` first"
    identity = repo_identity(directory)
    if identity is None or identity[0] != os.path.realpath(directory):
        return "run the TODO-only commit with -C set to the repository top level"
    for name in files:
        path = os.path.join(directory, name)
        if name.startswith(":") or any(c in name for c in "*?[\\") or os.path.islink(path) \
                or not os.path.isfile(path) \
                or git_out(directory, "ls-files", "--error-unmatch", "--", name) is None:
            return (f"`{name}` is not a tracked TODO file at the top level; a new TODO file is "
                    "added and committed by a captain:runner")
    return None


FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def in_state_dir(path: str, cwd: str | None) -> bool:
    """True when `path` lies under the state directory, by path or by file identity."""
    target = Path(os.path.realpath(os.path.join(cwd or "", os.path.expanduser(path))))
    state = Path(os.path.realpath(state_dir()))
    if target == state or state in target.parents:
        return True
    # by file identity too: a path in another letter case names the same directory on a
    # case-insensitive filesystem (Codex r2 F1)
    for part in (target, *target.parents):
        try:
            if part.exists() and os.path.samefile(part, state):
                return True
        except OSError:
            continue
    return False


def writes_state(name: str, tool_input: dict, cwd: str | None) -> bool:
    """True when a file tool would write under the state directory: the grant (.merge), the
    base (.base) and the mode marker come only from the owner's typed prompt, also when
    CAPTAIN_STATE_DIR points into a directory main may otherwise write, such as tmp/captain
    (Codex r1 F1)."""
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if name not in FILE_TOOLS or not isinstance(path, str) or not path:
        return False
    return in_state_dir(path, cwd)


def bash_writes_state(audit, command: str, cwd: str | None) -> bool:
    """True when a Bash call names the state directory as a redirection target or as an
    operand of a program that writes, moves or removes files (cp, mv, tee, ...)."""
    targets: list[str] = []
    words: list[str] = []
    for token in [*audit._Lexer(command, strict=False).run(), ("OP", ";")]:
        if token[0] == "R":
            match = re.match(r"^\d*(&>|>>|>&|>|<&|<)(.*)$", token[1])
            if match and match.group(1) != "<" and match.group(2) and \
                    not match.group(2).isdigit() and match.group(2) != "-":
                targets.append(match.group(2))
        elif token[0] == "W":
            words.append(token[1])
        else:
            program = [w for w in words if w not in {"command", "sudo", "exec"}][:1]
            if program and os.path.basename(program[0]) in WRITERS:
                targets += [w.split("=", 1)[1] if w.startswith(("of=", "if=")) else w
                            for w in words[1:] if not w.startswith("-")]
            words = []
    return any(in_state_dir(target, cwd) for target in targets)


def pre_tool_use(event: dict, session: str) -> None:
    name, tool_input = event.get("tool_name"), event.get("tool_input")
    if not isinstance(name, str) or not name or not isinstance(tool_input, dict):
        return  # malformed input never blocks
    if not (state_dir() / session).is_file():
        return
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) and event.get("cwd") else None
    if writes_state(name, tool_input, cwd):
        deny(STATE_DENIAL.format(name=name))
        return
    audit = load_audit()
    if name == "Skill" and isinstance(tool_input.get("skill"), str) \
            and tool_input["skill"] in CAPTAIN_SKILLS:
        args = tool_input.get("args") if isinstance(tool_input.get("args"), str) else ""
        if audit.ends_grant(args, typed=False):  # `captain end` before the end report (R17)
            end_grant(session)
    command = tool_input.get("command") if name == "Bash" else None
    if isinstance(command, str) and bash_writes_state(audit, command, cwd):
        deny(STATE_DENIAL.format(name=name))
        return
    root = audit.repo_root(cwd)
    grant = granted_branch(session)  # the form check only; the repository is checked live
    kind, detail = audit.classify(name, tool_input, root, SKILL_ROOT, Path(cwd) if cwd else None,
                                  grant)
    try:
        flow = isinstance(command, str) and merge_flow(audit, command) is not None
    except audit.Unverifiable:
        flow = False
    if kind != audit.OK:
        # the form check comes first, so a bare `git push` never reaches the live checks (r1 F1)
        deny(f"{name} ({kind}): {detail[:300]}",
             (MERGE_REASON if needs_grant(audit, name, tool_input, root, cwd, command)
              else FORM_REASON) if flow else REASON, audit.GRANT_ENDS)
    elif flow:
        problem = merge_problem(audit, command, cwd, session)
        if problem:
            deny(*problem, audit.GRANT_ENDS)


def needs_grant(audit, name: str, tool_input: dict, root, cwd: str | None, command: str) -> bool:
    """True when a denied `switch`/`push` would pass with a grant for its branch: the owner
    must act, not the form."""
    args = merge_flow(audit, command)
    while args and args[0].startswith("-"):
        args = args[2:] if args[0] == "-C" else args[1:]
    if not args or args[0] not in {"switch", "push"} or len(args) < 2:
        return False
    kind, _ = audit.classify(name, tool_input, root, SKILL_ROOT, Path(cwd) if cwd else None,
                             args[-1])
    return kind == audit.OK


def handle(event: dict) -> None:
    session, name = event.get("session_id"), event.get("hook_event_name")
    if not isinstance(session, str) or not SESSION_ID.match(session) or "agent_id" in event:
        return
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else ""
    if name == "UserPromptSubmit" and isinstance(event.get("prompt"), str):
        match = SLASH.match(event["prompt"])
        if match:
            args, audit = match.group(1), load_audit()
            fresh = current_run(session) is None  # a new session: /clear or a successor tab
            if audit.ends_grant(args):
                end_grant(session)
            set_mode(session, not wants_off(args), cwd, audit.starts_run(args))
            if fresh and audit.first_word(args) == "resume":
                carry_grant(session, cwd)
            if not wants_off(args):
                set_grant(session, args, cwd)
                set_base(session, args, cwd)
    elif name == "PostToolUse" and event.get("tool_name") == "Skill":
        tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
        if tool_input.get("skill") in CAPTAIN_SKILLS:
            args = tool_input.get("args") if isinstance(tool_input.get("args"), str) else ""
            # a model call never grants; a start it makes ends the grant with a new run ID
            audit = load_audit()
            if audit.ends_grant(args, typed=False):
                end_grant(session)
            set_mode(session, not wants_off(args), cwd, audit.starts_run(args))
            if not wants_off(args):
                note = set_base(session, args, cwd, typed=False)  # BR1: the auto base
                if note:
                    print(json.dumps({"hookSpecificOutput": {
                        "hookEventName": "PostToolUse", "additionalContext": note}},
                        ensure_ascii=False))
    elif name == "PreToolUse":
        pre_tool_use(event, session)


def main() -> int:
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    if isinstance(event, dict):
        try:
            handle(event)
        except Exception as error:  # a broken guard must never block the session
            print(f"captain guard: {type(error).__name__}: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
