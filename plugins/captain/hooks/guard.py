#!/usr/bin/env python3
"""Keep a captain session a coordinator (R1) for the whole session, not only the run.

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
model's Skill call `captain base <branch>` at start when the KB9 start-branch checks hold, see
`start_base_check`), or the branch of a live grant; never on a detached HEAD, and
main/master/the origin default branch only with the grant. `commit --no-edit` and `merge --abort` only while a merge is in
progress; `switch` and `push` only for the branch the owner named in a typed
`/captain merge <branch>`. The grant is bound to the repository (git common dir), the branch
and the run, and ends at `/captain off`, a new `/captain` start or a new `/captain merge`
(audit-main.py `ends_grant` is the one place for these signals). The grant comes only from
UserPromptSubmit: a Skill call made by the model never records it; the base is never
main/master/the origin default. The source of a merge is a local branch, or the remote-tracking
`origin/<default>` (`--no-ff --no-edit` or `--ff-only` into a `captain/*` or base HEAD,
`--ff-only` only into a granted HEAD).

Cowboy mode (KB8) adds a merge gate that no grant lifts: a `merge` (or the `commit --no-edit`
that concludes one) whose source brings a cowboy commit no green record covers is denied unless
it lands on the cowboy branch itself or on one of its own agent branches (`<branch>-*`).
The records are keyed by repository (git common dir) and branch, in <state dir>/cowboy/, and
come only from the model's Skill calls `captain cowboy on [<branch>]` (that branch, else
HEAD's, becomes the cowboy branch; later commits on it and its agent branches are cowboy
commits), `captain cowboy off` (cowboy mode ends; the record stays and keeps gating up to the
branch tip) and `captain cowboy green <sha>` (a checkout has HEAD at <sha>, a cowboy branch tip
is <sha>, and tmp/captain/<run>/tests/<sha>.json in any worktree shows every command exit 0).
`/captain off`, the end of the run, a handoff and a new session leave them; an unreadable record
denies every gated merge of its repository (`cowboy_problem`). The gate also runs with no
session marker, alone, in a repository that has a cowboy record (`cowboy_gate_only`).

A deny caused by the command form or the checkout state names the canonical forms and says to
fix the form; only a protected HEAD or a missing grant tells the coordinator to ask the owner.

Captain mode is a marker file per session: ~/.claude/captain/sessions/<session_id>
(CAPTAIN_STATE_DIR overrides the directory). The end of the run (R17) does not remove
it; only `/captain off` does. After a handoff (R21) the owner's /clear starts a new session with
no marker: the first message `/captain resume` starts with `/captain`, so the same prompt rule
turns the mode back on for the successor, and takes over the predecessor's live grant and
recorded base (`carry_grant`: same repository and working directory, the run ID carried, never
a new grant).

Like the audit, this is a guard against the coordinator's own habits, not a security
boundary. Bad or unknown input never blocks anything: the hook exits 0 without output.
"""
from __future__ import annotations

import hashlib
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
          "owns the file. Captain mode is on in this session, also after the run ended. "
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
FETCH_SECONDS = 12  # KB9; hooks.json gives the PostToolUse entry 30 s in all
REMOTE_SECONDS = 8
MERGE_SECONDS = 8  # the KB9 fast-forward of a start branch behind origin/<default>


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
    (`/captain base <branch>`, or `base=<branch>` among the start arguments): any branch, the
    override. Made by the model at start step 5 (a Skill call `captain base <branch>`, KB9):
    only while the start-branch checks hold, checked now; then a start branch behind
    origin/<default> with no commits of its own is fast-forwarded. main, master and the origin
    default are never recorded (they stay behind the grant). Returns a line for the model on
    the Skill path, else None."""
    branch = base_arg(args)
    if branch is None or not cwd or not os.path.isabs(cwd):
        return None
    identity = repo_identity(cwd)
    if identity is None:
        return None
    check = None
    if not typed:
        kept = typed_base(session, identity[1])
        if kept:  # the owner's override of this run wins over the start branch (r1 F2)
            return (f"captain guard: base `{branch}` NOT recorded: the owner's typed base "
                    f"`{kept}` of this run stays (the override). Skip § Auto base.")
        check = start_base_check(cwd, branch)
        if check.problem:
            return refused_note(branch, check)
    elif protected(cwd, branch):
        return None
    state_dir().mkdir(parents=True, exist_ok=True)
    base_file(session).write_text(json.dumps({"branch": branch, "repo": identity[0],
                                              "common_dir": identity[1],
                                              "auto": not typed, "run": current_run(session),
                                              "since": int(time.time())}) + "\n",
                                  encoding="utf-8")
    if check is None:
        return None
    return f"captain guard: base `{branch}` recorded (KB9 checks hold){fast_forward(cwd, check)}."


def typed_base(session: str, common_dir: str) -> str | None:
    """The branch of a base the owner typed in this run for this repository, else None."""
    try:
        base = json.loads(base_file(session).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(base, dict) or base.get("auto") is not False \
            or base.get("common_dir") != common_dir or base.get("run") is None \
            or base.get("run") != current_run(session) or not isinstance(base.get("branch"), str):
        return None
    return base["branch"]


class StartCheck:
    """The outcome of `start_base_check`: `problem` (None when every check holds) and whether
    the branch is protected (ask the owner) or only failed a check (the fallback); on success
    the origin default, its fetched tip and the HEAD SHA the checks saw."""

    def __init__(self, problem: str | None = None, guarded: bool = False, default: str = "",
                 tip: str = "", head: str = "", branch: str = ""):
        self.problem, self.guarded = problem, guarded
        self.default, self.tip, self.head, self.branch = default, tip, head, branch


def start_base_check(directory: str, branch: str) -> StartCheck:
    """KB9: may `branch`, the branch this session started on, become the run's base now? The
    checks that stay of AB1–AB6: AB1 HEAD is that branch, not main, master, the origin default
    (also the default origin names now, r1 F2) or detached; origin is readable; origin has no
    `<branch>`, or origin/<branch> is an ancestor of (or equal to) HEAD; AB5 it is not checked
    out in another worktree. AB3 (HEAD on the fetched tip) and AB6 (clean tree) are dropped.
    HEAD is read again after the network calls, right before the record (review r1 F1). The
    integration-branch judgment (develop, staging, release/*) is main's, before this call."""
    head = head_branch(directory)
    if head is None:
        return StartCheck("AB1: HEAD is detached or unreadable")
    if head != branch:
        return StartCheck(f"AB1: HEAD is `{head}`, not `{branch}`",
                          protected(directory, head) or protected(directory, branch))
    if origin_default(directory) is None:  # protected() would let captain/* through
        return StartCheck("AB1: origin/HEAD is unreadable, the default branch is unknown", True)
    if protected(directory, branch):
        return StartCheck(f"AB1: `{branch}` is main, master or the origin default", True)
    sha = git_out(directory, "rev-parse", "-q", "--verify", "HEAD^{commit}")
    remote = remote_state(directory, branch)  # the default origin names now (r1 F2)
    if sha is None or remote is None:
        return StartCheck("origin: `git ls-remote --symref origin HEAD` failed or named no "
                          "default branch")
    default, remote_branch = remote
    if branch == default:
        return StartCheck(f"AB1: `{branch}` is the default branch origin names now", True)
    tips = fetched_tips(directory, [default] + ([branch] if remote_branch else []))
    if tips is None or tips.get(default) is None \
            or (remote_branch and tips.get(branch) != remote_branch):
        return StartCheck(f"origin: `git fetch origin {default}` failed (origin unreachable)")
    if remote_branch and not is_ancestor(directory, remote_branch, sha):
        return StartCheck(f"origin/{branch} ({remote_branch[:12]}) is not an ancestor of HEAD: "
                          "origin is ahead or diverged")
    if checked_out_elsewhere(directory, branch):
        return StartCheck(f"AB5: `{branch}` is checked out in another worktree")
    if head_branch(directory) != branch \
            or git_out(directory, "rev-parse", "-q", "--verify", "HEAD^{commit}") != sha:
        return StartCheck("AB1: HEAD moved during the check")
    return StartCheck(default=default, tip=tips[default], head=sha, branch=branch)


def refused_note(branch: str, check: StartCheck) -> str:
    """The line for the model when the start branch is not recorded: a protected branch → ask
    the owner; any other failed check → the fallback with no question (KB9)."""
    if check.guarded:
        return (f"captain guard: base `{branch}` NOT recorded ({check.problem}). Protected "
                "start branch: present → ask the owner about a new worktree or branch "
                "(KB9); away → bootstrap makes a new captain/* branch from origin/<default>. "
                "Never the fallback from this branch's HEAD.")
    return (f"captain guard: base `{branch}` NOT recorded ({check.problem}). Fallback, no "
            f"question: bootstrap makes a new captain/* feature branch from the HEAD of "
            f"`{branch}`; write this reason to run.md. No base is recorded: the merge back "
            f"into `{branch}` needs the owner's `/captain merge {branch}` (R10).")


def fast_forward(directory: str, check: StartCheck) -> str:
    """KB9, after the record: a start branch behind origin/<default> with no commits of its own
    (HEAD a strict ancestor of the fetched tip) gets `merge --ff-only` to that tip, with HEAD
    read again right before it. The text appended to the recorded line ("" when HEAD is not
    behind, or has commits of its own). A failed fast-forward leaves the base recorded."""
    if check.head == check.tip or not is_ancestor(directory, check.head, check.tip):
        return ""
    target = f"origin/{check.default} ({check.tip[:12]})"
    if head_branch(directory) != check.branch \
            or git_out(directory, "rev-parse", "-q", "--verify", "HEAD^{commit}") != check.head:
        return (f"; fast-forward to {target} NOT run: HEAD moved after the record. Stop and "
                "tell the owner")
    try:
        out = subprocess.run(["git", "-C", directory, "merge", "--ff-only", "--quiet",
                              check.tip], capture_output=True, text=True,
                             timeout=MERGE_SECONDS, env=git_env())
    except (OSError, subprocess.SubprocessError) as error:
        return (f"; fast-forward to {target} FAILED ({type(error).__name__}). Stop and tell "
                "the owner")
    if out.returncode != 0:
        reason = " ".join((out.stderr or out.stdout).split())[:300] or f"exit {out.returncode}"
        return f"; fast-forward to {target} FAILED ({reason}). Stop and tell the owner"
    return f"; fast-forwarded to {target}"


def is_ancestor(directory: str, older: str, newer: str) -> bool:
    """`older` is an ancestor of, or equal to, `newer` (both commit SHAs)."""
    return git_out(directory, "merge-base", "--is-ancestor", older, newer) is not None


def head_branch(directory: str) -> str | None:
    """The branch HEAD names, else None (detached or unreadable)."""
    head = git_out(directory, "symbolic-ref", "-q", "HEAD")
    if not head or not head.startswith("refs/heads/"):
        return None
    return head[len("refs/heads/"):]


def git_env() -> dict:
    """No terminal prompt for a password can hang the hook; the timeouts bound the rest."""
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def fetched_tips(directory: str, branches: list[str]) -> dict[str, str | None] | None:
    """One `git fetch origin <branch>...` into refs of its own, so no other fetch can change
    the SHAs it compares (FETCH_HEAD is shared, review r1 F3); {branch: SHA}, else None."""
    refs = {name: f"refs/captain-guard/fetch-{os.getpid()}-{os.urandom(4).hex()}"
            for name in branches}
    try:
        out = subprocess.run(["git", "-C", directory, "fetch", "--quiet", "--no-tags", "origin",
                              *(f"+refs/heads/{name}:{ref}" for name, ref in refs.items())],
                             capture_output=True, text=True, timeout=FETCH_SECONDS,
                             env=git_env())
        if out.returncode != 0:
            return None
        return {name: git_out(directory, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}")
                for name, ref in refs.items()}
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        for ref in refs.values():
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
    """The base branch recorded in this session's current run for the repository of
    `directory`, else None. A base of an earlier run (a new `/captain` start makes a new run
    ID) does not count (review r1 F1); a handoff carries the run ID with the base."""
    try:
        base = json.loads(base_file(session).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(base, dict) or not isinstance(base.get("branch"), str) \
            or not isinstance(base.get("common_dir"), str) or base.get("run") is None \
            or base.get("run") != current_run(session):
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
    incoming = merge_source_sha(directory, sub, rest)  # KB8, before the grant (r3 F1)
    if incoming is not None:
        problem = cowboy_problem(directory, head, incoming, session)
        if problem:
            return problem, COWBOY_REASON
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


# --- cowboy mode (KB8): the merge gate of untested cowboy commits ------------------------

COWBOY_ARGS = re.compile(r"^\s*cowboy\s+(on|off|green)(?:\s+(\S+))?\s*$", re.I)
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
RUN_STATE = "tmp/captain"  # the run directories, where the test pass writes tests/<sha>.json
COWBOY_REASON = ("Captain cowboy gate (KB8): {detail}. Untested cowboy commits never land outside "
                 "the cowboy branch and its own agent branches; a `/captain merge` grant does not "
                 "lift this. Run the test pass on the cowboy branch tip, have its runner write "
                 "tmp/captain/<run>/tests/<sha>.json, then make the Skill call `captain cowboy "
                 "green <sha>` with that exact tip; or write the KB6 TODO entry and leave the "
                 "branch unmerged. Never rewrite the command around this.")


class CowboyUnreadable(Exception):
    """A cowboy record exists but cannot be read: every gated merge in that repository is
    denied (KB8: an unreadable record → deny)."""


def cowboy_file(common_dir: str) -> Path:
    """The cowboy records of one repository (its git common dir), for every branch. They sit in
    a subdirectory of the state directory: the session archive and cleanup look at files only,
    `/captain off` removes only the session's own files, and the state-directory denial covers
    it."""
    digest = hashlib.sha256(common_dir.encode("utf-8")).hexdigest()[:24]
    return state_dir() / "cowboy" / f"{digest}.json"


def read_cowboy(common_dir: str) -> dict:
    """{branch: record} of the repository; {} without a file; CowboyUnreadable for a file that
    is not a valid record set."""
    path = cowboy_file(common_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CowboyUnreadable(f"{path}: {error}") from error
    branches = data.get("branches") if isinstance(data, dict) else None
    if not isinstance(branches, dict) or data.get("common_dir") != common_dir:
        raise CowboyUnreadable(f"{path}: not a cowboy record set of {common_dir}")
    for branch, record in branches.items():
        if not isinstance(record, dict) or not isinstance(record.get("start"), str) \
                or not FULL_SHA.match(record["start"]) or not isinstance(record.get("on"), bool) \
                or not all(record.get(key) is None or (isinstance(record[key], str)
                                                       and FULL_SHA.match(record[key]))
                           for key in ("end", "green", "tip")):
            raise CowboyUnreadable(f"{path}: the record of `{branch}` is malformed")
    return branches


def write_cowboy(common_dir: str, branches: dict) -> None:
    path = cowboy_file(common_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps({"common_dir": common_dir, "branches": branches}, indent=1) + "\n",
                    encoding="utf-8")
    os.replace(temp, path)


def commit_sha(directory: str, ref: str) -> str | None:
    return git_out(directory, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}")


def rev_list(directory: str, *refs: str) -> set[str] | None:
    out = git_out(directory, "rev-list", *refs, "--")
    return None if out is None else set(out.split())


def untested_commits(directory: str, branch: str, record: dict,
                     bases: tuple[str, ...] = ()) -> set[str] | None:
    """The cowboy commits of `branch` no green record covers: the commits after `start` up to
    the tips of the branch and of its own agent branches (`<branch>-*`, r1 F4; `cowboy off`
    freezes nothing, r1 F2), minus the green commit and its ancestors, and minus what the integration branches already hold (origin/<default>, main,
    master, the record's base and `bases`): a sync of the cowboy branch brings their commits
    in, and those were never cowboy commits. An integration branch that holds a commit made on
    the cowboy branch itself (its first-parent line) is not subtracted. A deleted branch counts
    as ending at its green commit; with no green record its commits are unknown. None when git
    cannot tell (the caller denies)."""
    tip = commit_sha(directory, f"refs/heads/{branch}") or record.get("green")
    agents = agent_tips(directory, branch)
    if tip is None or agents is None:
        return None
    refs = [tip, *agents, f"^{record['start']}"] \
        + ([f"^{record['green']}"] if record.get("green") else [])
    own_line = rev_list(directory, "--first-parent", *refs)
    if own_line is None:
        return None
    default = origin_default(directory)
    names = [f"refs/remotes/origin/{default}"] if default else []
    names += [f"refs/heads/{name}" for name in ("main", "master", record.get("base"), *bases)
              if isinstance(name, str) and name]
    for name in dict.fromkeys(names):
        sha = commit_sha(directory, name)
        if sha is None:
            continue
        held = rev_list(directory, sha, f"^{record['start']}")
        if held is None:
            return None
        if not held & own_line:  # a leak keeps its holder out of the subtraction
            refs.append(f"^{sha}")
    return rev_list(directory, *refs)


def agent_tips(directory: str, branch: str) -> list[str] | None:
    """The tip SHAs of the cowboy branch's own agent branches, None when git cannot list them."""
    out = git_out(directory, "for-each-ref", "--format=%(refname:short) %(objectname)",
                  "refs/heads/")
    if out is None:
        return None
    tips = []
    for line in out.splitlines():
        name, _, sha = line.partition(" ")
        if name != branch and own_branch(name, branch) and sha:
            tips.append(sha)
    return tips


def own_branch(head: str, branch: str) -> bool:
    """`head` is the cowboy branch itself or one of its own agent branches (`<branch>-*`, the
    captain/<run>-<task> naming). The name is enough: untested commits that reach an agent
    branch stay gated on every merge out of it."""
    return head == branch or head.startswith(f"{branch}-")


def cowboy_problem(directory: str, head: str, source: str, session: str) -> str | None:
    """Why merging the commit `source` into the branch `head` would land an untested cowboy
    commit outside its cowboy branch (KB8), else None. No record in the repository → None; an
    unreadable record or a git failure → a problem (deny)."""
    identity = repo_identity(directory)
    if identity is None:
        return None
    try:
        records = read_cowboy(identity[1])
    except CowboyUnreadable as error:
        return f"the cowboy record is unreadable ({error})"
    if not records:
        return None
    incoming = None
    for branch, record in sorted(records.items()):
        if own_branch(head, branch):
            continue
        base = recorded_base(session, directory)
        untested = untested_commits(directory, branch, record, (base,) if base else ())
        if incoming is None:
            incoming = rev_list(directory, source, f"^refs/heads/{head}")
        if untested is None or incoming is None:
            return f"git cannot tell whether `{source[:12]}` holds untested commits of `{branch}`"
        if untested & incoming:
            green = (record.get("green") or "none")[:12]
            return (f"the merge into `{head}` brings {len(untested & incoming)} untested cowboy "
                    f"commit(s) of `{branch}` (green record: {green})")
    return None


def merge_source_sha(directory: str, sub: str, rest: list[str]) -> str | None:
    """The commit a `merge <ref>` brings, or the MERGE_HEAD a `commit --no-edit` concludes."""
    if sub == "merge" and rest and rest != ["--abort"]:
        return commit_sha(directory, rest[-1])
    if sub == "commit" and rest == ["--no-edit"]:
        return commit_sha(directory, "MERGE_HEAD")
    return None


def cowboy_call(session: str, args: str, cwd: str) -> str | None:
    """The model's Skill call `captain cowboy on|off|green <sha>` (KB8); a line for the model,
    else None when the arguments are no cowboy call."""
    match = COWBOY_ARGS.match(args)
    if not match:
        return None
    action, value = match.group(1).lower(), match.group(2)
    if (action == "green" and value is None) or (action == "off" and value is not None) \
            or (action == "on" and value is not None and base_arg(f"base {value}") is None):
        return ("captain guard: cowboy NOT changed: the forms are `cowboy on`, `cowboy on "
                "<branch>`, `cowboy off` and `cowboy green <sha>`")
    identity = repo_identity(cwd) if cwd and os.path.isabs(cwd) else None
    if identity is None:
        return "captain guard: cowboy NOT changed: the working directory is no git checkout"
    try:
        records = read_cowboy(identity[1])
    except CowboyUnreadable as error:
        return (f"captain guard: cowboy NOT changed: the record is unreadable ({error}); every "
                "gated merge in this repository stays denied; ask the owner")
    handler = {"on": cowboy_on, "off": cowboy_off, "green": cowboy_green}[action]
    note = handler(session, cwd, records, value)
    if not note.startswith("captain guard: cowboy NOT"):
        write_cowboy(identity[1], records)
    return note


def cowboy_on(session: str, cwd: str, records: dict, value: str | None) -> str:
    """Mark the run's cowboy feature branch: `value`, else HEAD's branch (main's checkout may
    sit on the start branch while the run checkout holds the feature branch). The commits after
    its tip now are cowboy commits. Never main, master, the origin default or the run's base."""
    head = value or head_branch(cwd)
    if head is None:
        return "captain guard: cowboy NOT on: HEAD is detached or unreadable; name the branch"
    if protected(cwd, head) or head == recorded_base(session, cwd):
        return (f"captain guard: cowboy NOT on: `{head}` is a protected branch or the run's base; "
                "make the cowboy feature branch first, then `cowboy on <branch>`")
    sha = commit_sha(cwd, f"refs/heads/{head}")
    if sha is None:
        return f"captain guard: cowboy NOT on: `{head}` is no local branch with a commit"
    record = records.get(head)
    if record is None:
        records[head] = {"start": sha, "on": True, "end": None, "green": None, "tip": sha,
                         "base": recorded_base(session, cwd), "run": current_run(session),
                         "since": int(time.time())}
        return f"captain guard: cowboy on for `{head}` from {sha[:12]}"
    record.update(on=True, end=None, tip=sha)
    return f"captain guard: cowboy on again for `{head}` (record kept, start {record['start'][:12]})"


def cowboy_off(session: str, cwd: str, records: dict, _value) -> str:
    """End cowboy mode for the run's cowboy branch (HEAD's branch, else the only one this run
    turned on). The record stays and keeps gating every commit up to the branch tip, later
    ones too, until a green record covers the tip: `off` never lifts the gate (KB8: only a
    green record closes it; r1 F2)."""
    head = head_branch(cwd)
    if head not in records:
        mine = [name for name, record in records.items()
                if record["on"] and record.get("run") == current_run(session)]
        head = mine[0] if len(mine) == 1 else None
    if head is None:
        return "captain guard: cowboy NOT off: no cowboy branch of this run is checked out here"
    record = records[head]
    if not record["on"]:
        return f"captain guard: cowboy already off for `{head}`"
    record.update(on=False, end=None,
                  tip=commit_sha(cwd, f"refs/heads/{head}") or record.get("tip"))
    return (f"captain guard: cowboy off for `{head}`; the record stays and its commits stay "
            "gated until a green record covers the branch tip")


def cowboy_green(session: str, cwd: str, records: dict, value: str) -> str:
    """Record a green test pass for exactly the commit `value`: a checkout of this repository
    has it as HEAD, a cowboy branch has it as its tip, and the test-pass runner left a passing
    result file for it (OP5). Any later commit is not covered."""
    sha = commit_sha(cwd, value)
    if sha is None:
        return f"captain guard: cowboy NOT green: `{value}` is no commit"
    if sha not in checkout_heads(cwd):
        return f"captain guard: cowboy NOT green: no checkout of this repository has HEAD at {sha[:12]}"
    problem = test_result_problem(cwd, sha)
    if problem:
        return f"captain guard: cowboy NOT green: {problem}"
    named = [name for name in sorted(records) if commit_sha(cwd, f"refs/heads/{name}") == sha]
    if not named:
        return f"captain guard: cowboy NOT green: no cowboy branch has its tip at {sha[:12]}"
    for name in named:
        records[name].update(green=sha, tip=sha)
    return f"captain guard: cowboy green {sha[:12]} for {', '.join(f'`{n}`' for n in named)}"


def checkout_heads(directory: str) -> set[str]:
    """The HEAD commit of every worktree of the repository of `directory`."""
    listing = git_out(directory, "worktree", "list", "--porcelain", "-z") or ""
    heads = {field[len("HEAD "):] for field in listing.split("\0") if field.startswith("HEAD ")}
    own = commit_sha(directory, "HEAD")
    return heads | ({own} if own else set())


def checkout_tops(directory: str) -> list[Path]:
    """The top level of `directory`'s checkout and of every worktree of its repository: the
    test-pass runner may write its result file in a temporary worktree (r1 F7)."""
    tops = []
    top = git_out(directory, "rev-parse", "--show-toplevel")
    if top:
        tops.append(Path(top))
    listing = git_out(directory, "worktree", "list", "--porcelain", "-z") or ""
    tops += [Path(field[len("worktree "):]) for field in listing.split("\0")
             if field.startswith("worktree ")]
    return tops


def test_result_problem(directory: str, sha: str) -> str | None:
    """OP5: the newest `tmp/captain/<run>/tests/<sha>.json` under any worktree of the
    repository names `sha`, lists at least one command, and every exit code is 0; else why not.
    It catches a mistake, not a forged file."""
    found = sorted({path for top in checkout_tops(directory)
                    for path in top.glob(f"{RUN_STATE}/*/tests/{sha}.json")},
                   key=lambda path: path.stat().st_mtime, reverse=True)
    if not found:
        return f"no test result file {RUN_STATE}/<run>/tests/{sha}.json"
    path = found[0]
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f"the test result file {path} is unreadable"
    if not isinstance(result, dict) or result.get("sha") != sha:
        return f"the test result file {path} names another SHA"
    commands = result.get("commands")
    if not isinstance(commands, list) or not commands:
        return f"the test result file {path} lists no commands"
    for entry in commands:
        if not isinstance(entry, dict) or not isinstance(entry.get("cmd"), str) \
                or isinstance(entry.get("exit"), bool) or entry.get("exit") != 0:
            cmd = entry.get("cmd") if isinstance(entry, dict) else entry
            return f"the test result file {path} has a failed or malformed command ({cmd!r})"
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


UNKNOWN_HEAD = object()  # a switch or checkout in the chain whose target the guard cannot tell
SWITCH_NEW = {"-c", "-C", "-b", "-B", "--create", "--force-create", "--orphan"}
SWITCH_QUIET = {"-q", "--quiet", "--no-track", "--track", "--no-guess", "--guess"}


def cowboy_gate_only(name: str, tool_input: dict, cwd: str | None, session: str) -> None:
    """Outside captain mode (no session marker: after `/captain off`, or a plain session) only
    the cowboy gate runs, and only in a repository with a cowboy record; nothing else of captain
    mode applies (r1 F1). The command is split on the shell separators (audit-main.py `parse`:
    &&, ||, ;, |, newlines) and every `git merge` / `git commit` part is checked against the
    HEAD a preceding `cd` and `git switch` / `git checkout <branch>` of the same chain set
    (OP9, r2 F1). A chain whose target the guard cannot tell is denied. pull, rebase and
    cherry-pick are not seen."""
    command = tool_input.get("command") if name == "Bash" else None
    if not isinstance(command, str) or "git" not in command \
            or not ("merge" in command or "commit" in command):
        return
    problem = chain_problem(load_audit(), command, cwd, session)
    if problem:
        deny(problem, COWBOY_REASON)


def gated_repo(directory: str | None) -> bool:
    """`directory` is absolute and in a repository with a cowboy record."""
    if not directory or not os.path.isabs(directory) or not os.path.isdir(directory):
        return False
    identity = repo_identity(directory)
    return identity is not None and cowboy_file(identity[1]).exists()


def chain_problem(audit, command: str, cwd: str | None, session: str) -> str | None:
    """The cowboy problem of the first gated `git merge` / `git commit` in the chain, else None.
    Fail closed (OP10, r3 F1-F3): HEAD is tracked per checkout (its top level), not per
    directory; a `cd` the guard cannot resolve to a checkout, or a switch, checkout or cd joined
    to a later merge by anything but `&&` (it may have failed), denies that merge."""
    try:
        audit.parse(command)  # the grammar check; the walk below keeps the separators
        tokens = audit._Lexer(command, strict=True).run()
    except audit.Unverifiable as error:
        return (f"the command `{command[:120]}` cannot be split into its parts ({error}) and "
                "the repository has a cowboy record; run the merge as its own command"
                if gated_repo(cwd) and "merge" in command else None)
    state = {"dir": cwd, "heads": {}, "moved": False, "fragile": False, "lost": False,
             "cwd_gated": None}
    words: list[str] = []
    for token in [*tokens, ("OP", "")]:
        if token[0] == "W":
            words.append(token[1])
            continue
        if token[0] != "OP":
            continue
        if token[1] == "\n" and not words:
            continue  # a line break after `&&` or between commands
        problem = chain_part(words, state, cwd, session)
        if problem:
            return problem
        words = []
        if token[1] not in {"&&", ""} and state["moved"]:
            state["fragile"] = True  # the move before may have failed, the next part still runs
    return None


def chain_part(words: list[str], state: dict, cwd: str | None, session: str) -> str | None:
    """One command of the chain: `cd` and `git switch`/`checkout` update `state`; a merge or a
    commit concluding one is checked."""
    while words and (words[0] in {"command", "exec"} or re.match(r"^\w+=", words[0])):
        words = words[1:]
    if not words:
        return None
    if words[0] == "cd":
        target = words[1] if len(words) > 1 else "~"
        state["dir"] = None if target == "-" else \
            os.path.normpath(os.path.join(state["dir"] or "", os.path.expanduser(target)))
        state["moved"] = True
        return None
    if words[0] != "git":
        return None
    return git_part_problem(words[1:], state, cwd, session)


def checkout_top(directory: str | None) -> str | None:
    """The real top level of the checkout at `directory`, else None."""
    if not directory or not os.path.isabs(directory) or not os.path.isdir(directory):
        return None
    top = git_out(directory, "rev-parse", "--show-toplevel")
    return os.path.realpath(top) if top else None


def git_part_problem(args: list[str], state: dict, cwd: str | None, session: str) -> str | None:
    """One `git ...` part of a chain: a switch or checkout records the HEAD it sets per checkout;
    a merge or a commit concluding one is checked with the cowboy gate."""
    directory = state["dir"]
    while args and args[0].startswith("-"):
        if args[0] in {"-C", "-c"} and len(args) > 1:
            if args[0] == "-C":
                directory = os.path.join(directory or "", os.path.expanduser(args[1])) \
                    if directory or os.path.isabs(args[1]) else None
            args = args[2:]
        else:
            args = args[1:]
    if not args or args[0] not in {"switch", "checkout", "merge", "commit"}:
        return None
    sub, rest = args[0], args[1:]
    top = checkout_top(directory)
    if sub in {"switch", "checkout"}:
        state["heads"][top] = switch_target(rest)
        state["moved"] = True
        return None
    if state["cwd_gated"] is None:
        state["cwd_gated"] = gated_repo(cwd)
    if top is None:  # a `cd` or `-C` the guard cannot resolve to a checkout
        return ("the merge runs in a directory the guard cannot resolve to a checkout, in a "
                "command started in a repository with a cowboy record; run it as its own "
                "command" if sub == "merge" and state["cwd_gated"] else None)  # r4 F3
    if not gated_repo(top):
        return None
    concludes = sub == "commit" or "--continue" in rest
    if state["fragile"] and (sub == "merge" and not concludes
                             or concludes and commit_sha(top, "MERGE_HEAD")):  # r4 F2
        return ("a `cd`, `git switch` or `git checkout` earlier in this command is joined to "
                "the merge or its concluding commit by a separator other than `&&`: if it "
                "failed, the merge lands on another branch; run the move and the merge as "
                "separate commands")
    head = state["heads"][top] if top in state["heads"] else head_branch(top)
    if head is UNKNOWN_HEAD:
        return ("a `git switch`/`git checkout` earlier in this command moves HEAD to a branch "
                "the guard cannot tell, before a merge in a repository with a cowboy record; "
                "run the switch and the merge as separate commands")
    if concludes:
        sources = [commit_sha(top, "MERGE_HEAD")]
    elif "--abort" in rest or "--quit" in rest:
        return None
    else:
        named = merge_sources(rest)
        if "-" in named:
            return "`git merge -` names the previous branch, which the guard cannot tell"
        if not named:  # git merges the upstream of HEAD (r3 F3)
            upstream = commit_sha(top, f"{head}@{{upstream}}") \
                if isinstance(head, str) else None
            if upstream is None:
                return ("`git merge` with no source merges the upstream of HEAD, which the "
                        "guard cannot resolve; name the branch")
            named = [upstream]
        sources = [commit_sha(top, word) for word in named]
    sources = [sha for sha in sources if sha]
    if not sources or head is None:
        return None  # nothing to merge, or a detached HEAD: the merge lands on no branch
    for source in sources:
        problem = cowboy_problem(top, head, source, session)
        if problem:
            return problem
    return None


MERGE_VALUE_OPTIONS = {"-m", "-F", "-s", "-X", "--message", "--file", "--strategy",
                       "--strategy-option", "--into-name", "--cleanup"}


def merge_sources(rest: list[str]) -> list[str]:
    """The source words of `git merge <rest>`: the positional words, without the values of the
    options that take one as the next word (-m <msg>, -s <strategy>, ..., r4 F1); attached
    values (`-mmsg`, `--message=msg`, `-S<key>`) are part of their option word. `-` stays."""
    sources, i = [], 0
    while i < len(rest):
        word = rest[i]
        if word == "--":
            sources += rest[i + 1:]
            break
        if word in MERGE_VALUE_OPTIONS:
            i += 2
            continue
        if word.startswith("-") and word != "-":
            i += 1
            continue
        sources.append(word)
        i += 1
    return sources


def switch_target(rest: list[str]):
    """The branch `git switch` / `git checkout` with `rest` puts HEAD on, None for a detach, or
    UNKNOWN_HEAD when the words do not tell (paths, `-`, unknown options)."""
    if any(word in {"--detach", "-d"} for word in rest):
        return None
    for i, word in enumerate(rest):
        if word in SWITCH_NEW:
            return rest[i + 1] if i + 1 < len(rest) else UNKNOWN_HEAD
    plain = [word for word in rest if word not in SWITCH_QUIET]
    if len(plain) == 1 and not plain[0].startswith("-") and plain[0] != "-" \
            and BRANCH_NAME.match(plain[0]):
        return plain[0]
    return UNKNOWN_HEAD


def pre_tool_use(event: dict, session: str) -> None:
    name, tool_input = event.get("tool_name"), event.get("tool_input")
    if not isinstance(name, str) or not name or not isinstance(tool_input, dict):
        return  # malformed input never blocks
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) and event.get("cwd") else None
    if not (state_dir() / session).is_file():
        cowboy_gate_only(name, tool_input, cwd, session)  # KB8 also outside captain mode (r1 F1)
        return
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


def post_note(note: str | None) -> None:
    """A line for the model after its Skill call, when there is one."""
    if note:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                 "additionalContext": note}}, ensure_ascii=False))


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
            if COWBOY_ARGS.match(args):
                # KB8: a cowboy call changes only its record, never the mode: `cowboy off`
                # after a typed `/captain off` must not turn captain mode back on
                post_note(cowboy_call(session, args, cwd))
                return
            # a model call never grants; a start it makes ends the grant with a new run ID
            audit = load_audit()
            if audit.ends_grant(args, typed=False):
                end_grant(session)
            set_mode(session, not wants_off(args), cwd, audit.starts_run(args))
            if not wants_off(args):
                post_note(set_base(session, args, cwd, typed=False))  # KB9: the start branch as base
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
