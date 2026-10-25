#!/usr/bin/env python3
"""Remove the worktrees and branches a captain run created, and only those.

Usage: python3 cleanup-run.py --run-dir=<abs run-state dir> [--dry-run] [--include-run-checkout]

Reads only <run-dir>/created.jsonl (written by record-created.py) and <run-dir>/run.md.
The first line says what it read from run.md (`-`: the label is missing; `none`: an explicit
`Base branch (R10): none`), followed by one WARN line per missing label:
  READ feature=<branch|-> base=<branch|none|-> default=<branch|-> checkout=<path|-> base_sha=<sha|-> agents=<n>
  WARN run.md has no <label> line; <what that disables>
Then, for each recorded worktree and branch that still exists, exactly one line:
  REMOVED <worktree> branch=<branch> [logs=<copy>]
  WOULD-REMOVE <worktree> branch=<branch>            (--dry-run: nothing changes)
  SKIPPED <worktree> branch=<branch> [logs=<copy>] reason=<reason>
`logs=` names <run-dir>/worktree-logs/<worktree name>[-<n>], the copy of the worktree's
tmp/claude-logs/, on every line of an item whose worktree was removed (REMOVED, or SKIPPED when
only the branch step failed); a symlink in tmp/claude-logs/ or a failed copy skips the item.
Items whose worktree and branch are both gone (git read the repository and found neither)
print no line of their own; the last line is then `ALREADY-REMOVED <n>` (n > 0).

An item is skipped when:
- its worktree is not the one the run created: the manifest line has `git_ino`/`git_dev` and
  the worktree's `.git` file is missing or has another inode or device (no check when only the
  branch is left, or for manifest lines without these fields);
- its worktree is or contains the working directory of a captain main session (the `cwd` in
  a non-stale guard session marker, $CAPTAIN_STATE_DIR or ~/.claude/captain/sessions) or of
  this script;
- it is the run checkout (`Run checkout:` in run.md) and --include-run-checkout is not given
  (`run checkout kept; pass --include-run-checkout on the owner's request`), whatever the
  session markers say; the runner passes the flag only on the owner's request;
- it is the run checkout, the flag is given, and the feature branch has no commits beyond the
  run's `Base SHA (bootstrap):` (missing or not a commit: kept too) or its head is not an
  ancestor of origin/<default> (the script does not fetch; the runner fetches first). With the
  flag the run checkout goes even while a captain session is open, once the checks below pass;
- its worktree has tracked or untracked changes, or ignored files other than the disposable
  ones (node_modules/, __pycache__/, *.pyc, .pytest_cache/, tmp/claude-logs/); the
  tmp/claude-logs/ copy failed;
- a process of the current user has its working directory inside the worktree (busy), or that
  cannot be told: `ps` failed, or the cwd of a live pid could not be read (macOS: one `lsof`
  call, Linux: /proc/<pid>/cwd; 10 s timeout per call; this script and its parent do not
  count; a pid that ended meanwhile is ignored);
- its branch is not merged into the run's feature branch, its base branch or
  origin/<default> (the branch itself does not count);
- its writer is still running: its row of the run.md `## Agents` table has `notified` other
  than `yes`. The row is the one whose `Checkout (abs)` is the worktree, else the one whose
  `Name` is the manifest's `agent` (manifest lines without `agent`: by Checkout only);
- it is locked by anything but Supacode, or git refuses a step.

A marker is stale when the newest mtime of the marker, its `<id>.merge`, its `<id>.base` and
the transcript `<projects root>/*/<id>.jsonl` (when found; $CAPTAIN_PROJECTS_DIR or
~/.claude/projects) is older than MARKER_MAX_AGE (5 days). A stale marker is read as if it
were absent; nothing moves or deletes a marker.

An item is also skipped when run.md has no readable `## Agents` table (no heading, no table,
no data rows, or no `Checkout (abs)` and `notified` columns), or when the worktree (other than
the run checkout) has no row there (`no agent row for <agent> (<worktree>)`).

Removal: `git worktree unlock` only when the lock reason is JSON with top-level owner
"supacode" (the lock is put back if the remove then fails), `git worktree remove` without
--force, `git branch -d` (never -D) from a checkout of the same repository whose HEAD has the
branch: the run checkout first, then the other worktrees; when none has it, the branch stays.
Git runs without optional locks, so --dry-run does not even refresh the index. The Supacode CLI is not called: see reference/health.md.
Exit codes: 0 every item handled (removed, would remove or skipped); 2 bad arguments, a missing
manifest or a missing run.md.
"""
from __future__ import annotations

import argparse
import codecs
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

SESSION_ID = re.compile(r"^[A-Za-z0-9_-]+$")
MARKER_MAX_AGE = 5 * 24 * 3600  # seconds; the same stale rule as archive-sessions.py
PROCESS_TIMEOUT = 10  # seconds, for each ps and lsof call
LOGS_DIR = "tmp/claude-logs"
DISPOSABLE_DIRS = {"node_modules", "__pycache__", ".pytest_cache"}


def run_git(directory: str, *args: str) -> subprocess.CompletedProcess:
    # no optional locks: `git status` must not refresh the index, so --dry-run writes nothing
    return subprocess.run(["git", "--no-optional-locks", "-C", directory, *args],
                          capture_output=True, text=True,
                          env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))


def supacode_lock(reason: str) -> bool:
    """Only a JSON object whose top-level owner is exactly "supacode"."""
    try:
        value = json.loads(reason)
    except ValueError:
        return False
    return isinstance(value, dict) and value.get("owner") == "supacode"


def same_repo(directory: str, common_dir: str) -> bool:
    found = git_out(directory, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return found is not None and real(found) == common_dir


def git_out(directory: str, *args: str) -> str | None:
    result = run_git(directory, *args)
    return result.stdout.strip() if result.returncode == 0 else None


def first_line(result: subprocess.CompletedProcess) -> str:
    text = (result.stderr or result.stdout).strip()
    return text.splitlines()[0] if text else f"exit {result.returncode}"


def real(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path.strip().strip("`'\"")))


def inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


# --- run.md -----------------------------------------------------------------------------

def field_value(text: str, label: str) -> str | None:
    """The value after `<label>:` on a run.md header line, up to a 3-space gap or line end."""
    match = re.search(rf"(?m){re.escape(label)}:[ \t]*(.+?)(?:\s{{3,}}|$)", text)
    return match.group(1).strip() if match else None


def table(text: str, heading: str) -> list[dict[str, str]]:
    """Rows of the first markdown table under `## <heading>`, keyed by header name."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == f"## {heading}")
    except StopIteration:
        return []
    rows, header = [], None
    for line in lines[start + 1:]:
        stripped = line.strip()
        if stripped.startswith("#"):
            break
        if not stripped.startswith("|"):
            if header is not None:
                break
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if header is None:
            header = cells
        elif not all(re.fullmatch(r":?-+:?", cell) for cell in cells if cell):
            rows.append(dict(zip(header, cells)))
    return rows


@dataclass
class Run:
    feature: str | None
    base: str | None
    default: str | None
    checkout: str | None
    agents: set[str] | None = None  # every `Checkout (abs)` in ## Agents; None: unreadable
    base_sha: str | None = None
    base_label: bool = True  # False: run.md has no `Base branch (R10):` line at all
    rows: list[dict[str, str]] = field(default_factory=list)  # data rows of ## Agents


def read_run(text: str) -> Run:
    feature = field_value(text, "Feature branch")
    base = field_value(text, "Base branch (R10)")
    checkout = field_value(text, "Run checkout")
    rows = table(text, "Agents")
    readable = bool(rows) and all("Checkout (abs)" in row and "notified" in row for row in rows)
    agents = {real(row["Checkout (abs)"]) for row in rows if row.get("Checkout (abs)")}
    return Run(feature=feature.split(",")[0].strip() if feature else None,
               base=None if not base or base.lower().startswith("none")
               else base.split(",")[0].strip(),
               default=field_value(text, "Default branch"),
               checkout=real(checkout) if checkout else None,
               agents=agents if readable else None,
               base_sha=field_value(text, "Base SHA (bootstrap)"),
               base_label=base is not None, rows=rows)


MISSING_LABELS = (
    ("feature", "Feature branch:", "the feature branch is not a merge target"),
    ("base", "Base branch (R10):", "the base branch is not a merge target"),
    ("checkout", "Run checkout:", "the run checkout is not recognised and needs an agent row"),
    ("base_sha", "Base SHA (bootstrap):", "a fresh run checkout cannot be told from a used one"),
)


def read_lines(run: Run) -> list[str]:
    """The READ line and one WARN line per missing run.md label (D8)."""
    base = run.base or ("none" if run.base_label else "-")
    lines = [f"READ feature={run.feature or '-'} base={base} default={run.default or '-'} "
             f"checkout={run.checkout or '-'} base_sha={run.base_sha or '-'} agents={len(run.rows)}"]
    for attribute, label, effect in MISSING_LABELS:
        missing = not run.base_label if attribute == "base" else not getattr(run, attribute)
        if missing:
            lines.append(f"WARN run.md has no {label} line; {effect}")
    return lines


def agent_rows(run: Run, path: str, agent: str | None) -> list[dict[str, str]]:
    """The ## Agents rows of a worktree: every `Checkout (abs)` match, else every `Name` = agent."""
    rows = [row for row in run.rows
            if row.get("Checkout (abs)") and real(row["Checkout (abs)"]) == path]
    if not rows and agent:
        rows = [row for row in run.rows if row.get("Name", "").strip("`") == agent]
    return rows


# --- the main session -------------------------------------------------------------------

def state_dir() -> Path:
    override = os.environ.get("CAPTAIN_STATE_DIR")
    return Path(override) if override else Path.home() / ".claude" / "captain" / "sessions"


def projects_dir() -> Path:
    override = os.environ.get("CAPTAIN_PROJECTS_DIR")
    return Path(override) if override else Path.home() / ".claude" / "projects"


def mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def marker_stale(marker: Path, now: float) -> bool:
    """The newest of the marker, its .merge and .base, and its transcript is too old."""
    paths = [marker, marker.with_name(f"{marker.name}.merge"),
             marker.with_name(f"{marker.name}.base")]
    paths += projects_dir().glob(f"*/{marker.name}.jsonl")
    times = [found for found in map(mtime, paths) if found is not None]
    return not times or now - max(times) > MARKER_MAX_AGE


def cwd_common_dir(cwd: str) -> str | None:
    """The git common dir of the nearest existing directory at or above `cwd`."""
    directory = cwd
    while not os.path.isdir(directory):
        parent = os.path.dirname(directory)
        if parent == directory:
            return None
        directory = parent
    found = git_out(directory, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return real(found) if found else None


def session_cwds(run_common: str | None = None) -> tuple[bool, set[str]]:
    """(captain mode on for the run's repository, the cwd of every non-stale session marker).

    Mode is on when a non-stale marker's cwd lies in the repository whose git common dir is
    `run_common`; stale markers are read as if absent.
    """
    directory, now = state_dir(), time.time()
    on, cwds = False, set()
    if directory.is_dir():
        for marker in directory.iterdir():
            if not marker.is_file() or not SESSION_ID.match(marker.name):
                continue  # .merge and .base files carry a suffix
            if marker_stale(marker, now):
                continue
            try:
                cwd = json.loads(marker.read_text(encoding="utf-8")).get("cwd")
            except (OSError, ValueError, AttributeError):
                cwd = None
            if isinstance(cwd, str) and cwd:
                cwds.add(real(cwd))
                if run_common and not on and cwd_common_dir(real(cwd)) == run_common:
                    on = True
    return on, cwds


# --- git --------------------------------------------------------------------------------

def unquote(value: str) -> str:
    """git C-quotes a porcelain value that holds a quote or a special byte."""
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return codecs.escape_decode(value[1:-1].encode("ascii", "backslashreplace"))[0].decode(
            "utf-8", "replace")
    return value


def worktrees(common_dir: str) -> dict[str, dict[str, str]]:
    """`git worktree list --porcelain` keyed by real path; values: branch, locked, main."""
    out = git_out(common_dir, "worktree", "list", "--porcelain")
    found: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for line in (out or "").splitlines():
        key, _, value = line.partition(" ")
        if key == "worktree":
            current = {"main": "yes" if not found else ""}
            found[real(unquote(value))] = current
        elif current is not None and key == "branch":
            current["branch"] = value.removeprefix("refs/heads/")
        elif current is not None and key == "locked":
            current["locked"] = unquote(value) or "(no reason)"
    return found


def origin_default(common_dir: str, run: Run) -> str | None:
    """origin/HEAD, else origin/<`Default branch:` of run.md>; not checked to exist."""
    default = git_out(common_dir, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if not default and run.default:
        default = f"origin/{run.default}"
    return default


def merge_targets(common_dir: str, run: Run, branch: str) -> list[str]:
    default = origin_default(common_dir, run)
    targets = [name for name in (run.feature, run.base, default) if name and name != branch]
    return [name for name in targets
            if git_out(common_dir, "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}")]


def merged(common_dir: str, run: Run, branch: str) -> bool:
    return any(run_git(common_dir, "merge-base", "--is-ancestor", branch, target).returncode == 0
               for target in merge_targets(common_dir, run, branch))


def branch_exists(common_dir: str, branch: str) -> bool:
    return git_out(common_dir, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}") is not None


# --- the worktree tree (D4) -------------------------------------------------------------

def worktree_status(path: str) -> tuple[list[str], list[str]] | None:
    """(changed or untracked paths, ignored paths) of a worktree; None when git status fails."""
    result = run_git(path, "status", "--porcelain", "--ignored", "--untracked-files=all")
    if result.returncode != 0:
        return None
    changed, ignored = [], []
    for line in result.stdout.splitlines():
        if line:
            (ignored if line.startswith("!! ") else changed).append(unquote(line[3:]))
    return changed, ignored


def disposable(path: str) -> bool:
    """An ignored path removed without a question; tmp/claude-logs/ is copied first."""
    # git lists files (--untracked-files=all), so the names count only as parent directories
    return (path.startswith(f"{LOGS_DIR}/") or path.endswith(".pyc")
            or any(part in DISPOSABLE_DIRS for part in path.split("/")[:-1]))


def ignored_problem(ignored: list[str]) -> str | None:
    """The skip reason for ignored files that are not disposable, naming the first three."""
    kept = [path for path in ignored if not disposable(path)]
    return f"ignored files that are not disposable: {', '.join(kept[:3])}" if kept else None


def tree_problem(path: str) -> str | None:
    """None when the worktree is clean: no changes, no untracked and no kept ignored files."""
    status = worktree_status(path)
    if status is None:
        return "git status failed"
    changed, ignored = status
    if changed:
        return "worktree has tracked or untracked changes"
    return ignored_problem(ignored)


def copy_logs(worktree: str, run_dir: str) -> tuple[str | None, str | None]:
    """(copy, problem): tmp/claude-logs/ to <run dir>/worktree-logs/<worktree name>[-<n>]/;
    a symlink inside makes it a problem, so the copy never depends on files outside it."""
    source = Path(worktree) / LOGS_DIR
    if not source.is_dir():
        return None, None
    try:
        link = next((item for item in source.rglob("*") if item.is_symlink()), None)
    except OSError as error:
        return None, f"copy of {LOGS_DIR}/ failed: {str(error)[:200]}"
    if link is not None:  # its target may go with the worktree; the copy would not keep it
        return None, f"{LOGS_DIR}/ holds a symlink: {link.relative_to(worktree)}"
    name, number = Path(worktree).name, 1
    target = Path(run_dir) / "worktree-logs" / name
    while target.exists() or target.is_symlink():  # never merge into another worktree's copy
        number += 1
        target = target.with_name(f"{name}-{number}")
    try:
        shutil.copytree(source, target, symlinks=True)
    except OSError as error:  # shutil.Error is an OSError
        return None, f"copy of {LOGS_DIR}/ failed: {str(error)[:200]}"
    return str(target), None


# --- processes (D2) ---------------------------------------------------------------------

def stderr_line(result: subprocess.CompletedProcess) -> str:
    text = (result.stderr or "").strip()
    return text.splitlines()[0] if text else f"exit {result.returncode}"


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:  # PermissionError: it exists, under another user
        return True
    return True


def user_processes() -> tuple[dict[int, str], str | None]:
    """({pid: command} of the current user's live processes but this one and its parent, error)."""
    columns = "pid=,uid=,stat=,comm="
    command = ["ps", "-axo", columns] if sys.platform == "darwin" else ["ps", "-eo", columns]
    try:
        result = subprocess.run(command, capture_output=True, text=True, errors="replace",
                                timeout=PROCESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {}, f"ps timed out after {PROCESS_TIMEOUT} s"
    except OSError as error:
        return {}, f"ps failed: {error}"
    if result.returncode != 0:
        return {}, f"ps failed: {stderr_line(result)}"
    uid, own = os.getuid(), {os.getpid(), os.getppid()}
    found: dict[int, str] = {}
    for line in result.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 3 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        pid = int(parts[0])
        if int(parts[1]) != uid or pid in own or parts[2].startswith("Z"):
            continue  # a zombie has no cwd to read
        found[pid] = os.path.basename(parts[3].strip()) if len(parts) > 3 else "?"
    return found, None


def cwds_from_lsof(pids: list[int]) -> tuple[dict[int, str], str | None]:
    """macOS: one lsof call; a live pid missing from its output is an error."""
    try:
        lsof = shutil.which("lsof") or "/usr/sbin/lsof"  # /usr/sbin may be off PATH
        result = subprocess.run([lsof, "-a", "-d", "cwd", "-Fpn", "-p", ",".join(map(str, pids))],
                                capture_output=True, text=True, errors="replace",
                                timeout=PROCESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {}, f"lsof timed out after {PROCESS_TIMEOUT} s"
    except OSError as error:
        return {}, f"lsof failed: {error}"
    # lsof exits 1 when a pid ended meanwhile, so the exit code says nothing on its own
    cwds: dict[int, str] = {}
    pid = None
    for line in result.stdout.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            cwds.setdefault(pid, line[1:])
    for pid in pids:
        if pid not in cwds and alive(pid):
            return cwds, f"lsof gave no cwd for pid {pid} ({stderr_line(result)})"
    return cwds, None


def cwds_from_proc(pids: list[int]) -> tuple[dict[int, str], str | None]:
    """Linux: /proc/<pid>/cwd; a failed lookup of a pid that still exists is an error."""
    cwds: dict[int, str] = {}
    error = None
    for pid in pids:
        try:
            cwds[pid] = os.readlink(f"/proc/{pid}/cwd")
        except OSError as problem:
            if error is None and alive(pid):
                error = f"cwd of pid {pid}: {problem}"
    return cwds, error


def process_cwds(pids: list[int]) -> tuple[dict[int, str], str | None]:
    if not pids:
        return {}, None
    if sys.platform == "darwin":
        return cwds_from_lsof(pids)
    if os.path.isdir("/proc"):
        return cwds_from_proc(pids)
    return {}, f"no way to read process cwds on {sys.platform}"


def process_check(path: str) -> tuple[str, str]:
    """("busy" | "free" | "unknown", detail) for the current user's processes whose cwd is
    inside path; detail is "pid <n>, <command>" when busy and the first error when unknown."""
    commands, error = user_processes()
    if error:
        return "unknown", error
    cwds, error = process_cwds(sorted(commands))
    for pid, cwd in sorted(cwds.items()):
        if inside(os.path.realpath(cwd), path):
            return "busy", f"pid {pid}, {commands[pid]}"
    if error:
        return "unknown", error
    return "free", ""


# --- one item ---------------------------------------------------------------------------

@dataclass
class Context:
    run_id: str
    run: Run
    protected_cwds: set[str]
    dry_run: bool
    include_run_checkout: bool = False  # --include-run-checkout: the owner asked for it
    run_dir: str = ""  # where worktree-logs/ goes


def identity_reason(entry: dict, listed: dict[str, str] | None) -> str | None:
    """A worktree at the path that is not the one record-created.py saw (its .git inode)."""
    if listed is None or not isinstance(entry.get("git_ino"), int) \
            or not isinstance(entry.get("git_dev"), int):
        return None  # only the branch is left, or a manifest line from before the inode
    try:
        found = os.stat(os.path.join(entry["worktree"], ".git"))
    except OSError:
        found = None
    if found is None or (found.st_ino, found.st_dev) != (entry["git_ino"], entry["git_dev"]):
        return "worktree at this path is not the one the run created"
    return None


def resolve_commit(common_dir: str, name: str) -> str | None:
    return git_out(common_dir, "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}")


def run_checkout_reason(entry: dict, ctx: Context) -> str | None:
    """Why the run checkout stays even with --include-run-checkout (D6); None: it may go.

    Only the branch rules; the cwd, tree, lock and process checks of skip_reason still follow.
    """
    common, branch = entry["common_dir"], entry["branch"]
    if not ctx.run.base_sha:
        return "run checkout kept: run.md has no Base SHA (bootstrap): line"
    base = resolve_commit(common, ctx.run.base_sha)
    if base is None:
        return f"run checkout kept: Base SHA {ctx.run.base_sha} is not a commit"
    head = resolve_commit(common, f"refs/heads/{branch}")
    if head is None:
        return f"run checkout kept: branch {branch} not found"
    if head == base or run_git(common, "merge-base", "--is-ancestor", head, base).returncode == 0:
        return "run checkout kept: the feature branch has no commits beyond Base SHA"
    default = origin_default(common, ctx.run)
    if not default or resolve_commit(common, default) is None:
        return "run checkout kept: no origin/<default> to check the feature branch against"
    if run_git(common, "merge-base", "--is-ancestor", head, default).returncode != 0:
        return (f"run checkout kept: the feature branch is not in {default} "
                f"(the runner fetches first)")
    return None


def skip_reason(entry: dict, ctx: Context, listed: dict[str, str] | None) -> str | None:
    common, path, branch = entry["common_dir"], entry["worktree"], entry["branch"]
    if entry.get("run_id") != ctx.run_id:
        return f"recorded for run {entry.get('run_id')}, not {ctx.run_id}"
    if any(inside(cwd, path) for cwd in ctx.protected_cwds):
        return "worktree is the working directory of a main session or of this script"
    if ctx.run.checkout and path == ctx.run.checkout:
        if not ctx.include_run_checkout:
            return "run checkout kept; pass --include-run-checkout on the owner's request"
        reason = run_checkout_reason(entry, ctx)
        if reason:
            return reason
    if ctx.run.agents is None:
        return "run.md has no readable ## Agents table"
    agent = entry.get("agent") if isinstance(entry.get("agent"), str) else None
    rows = agent_rows(ctx.run, path, agent)
    if not rows and path != ctx.run.checkout:
        if agent:
            return f"no agent row for {agent} ({path})"
        return "no agent row for this worktree in run.md"
    if any(row.get("notified", "").lower() != "yes" for row in rows):
        return "writer still running in run.md"
    if listed is not None:
        if listed.get("main"):
            return "main worktree of the repository"
        if listed.get("branch") != branch:
            return f"worktree is on {listed.get('branch') or 'a detached HEAD'}, not {branch}"
        lock = listed.get("locked")
        if lock and not supacode_lock(lock):
            return f"locked by another tool: {lock}"
        problem = tree_problem(path)
        if problem:
            return problem
    if branch_exists(common, branch) and not merged(common, ctx.run, branch):
        return "branch not merged into the feature branch, its base or origin/<default>"
    if listed is not None:
        state, detail = process_check(path)
        if state == "busy":
            return f"a process works in it ({detail})"
        if state != "free":
            return f"process check incomplete: {detail}"
    return None


def remove_worktree(entry: dict, listed: dict[str, str]) -> str | None:
    common, path = entry["common_dir"], entry["worktree"]
    lock = listed.get("locked")
    if lock:
        result = run_git(common, "worktree", "unlock", path)
        if result.returncode != 0:
            return f"git worktree unlock failed: {first_line(result)}"
    result = run_git(common, "worktree", "remove", path)
    if result.returncode != 0:
        if lock:
            run_git(common, "worktree", "lock", "--reason", lock, path)
        return f"git worktree remove refused: {first_line(result)}"
    return None


def delete_branch(entry: dict, ctx: Context) -> str | None:
    common, branch = entry["common_dir"], entry["branch"]
    if not branch_exists(common, branch):
        return None
    # `branch -d` checks the merge against HEAD of the directory it runs in, so it runs in a
    # checkout whose HEAD has the branch: the run checkout first (writer branches merge into
    # the feature branch), then the other worktrees of the repository.
    candidates = [ctx.run.checkout] if ctx.run.checkout else []
    candidates += [path for path in worktrees(common) if path != ctx.run.checkout]
    for where in candidates:
        if (where != entry["worktree"] and os.path.isdir(where) and same_repo(where, common)
                and run_git(where, "merge-base", "--is-ancestor", branch, "HEAD").returncode == 0):
            result = run_git(where, "branch", "-d", branch)
            if result.returncode == 0:
                return None
            return f"git branch -d refused: {first_line(result)}"
    targets = [target for target in merge_targets(common, ctx.run, branch)
               if run_git(common, "merge-base", "--is-ancestor", branch, target).returncode == 0]
    return (f"merged into {', '.join(targets) or 'a merge target'} but no checkout of the "
            f"repository has it in HEAD; branch not deleted")


def gone_check(entry: dict) -> tuple[str | None, bool]:
    """(problem, branch exists) for an item whose worktree git does not list; a git failure
    is a problem, so an item git could not read is never counted as already removed."""
    common = entry["common_dir"]
    listing = run_git(common, "worktree", "list", "--porcelain")
    if listing.returncode != 0:
        return f"git cannot read the repository: {first_line(listing)}", False
    result = run_git(common, "rev-parse", "--verify", "--quiet", f"refs/heads/{entry['branch']}")
    if result.returncode not in (0, 1):
        return f"git cannot read the repository: {first_line(result)}", False
    return None, result.returncode == 0


def handle(entry: dict, ctx: Context) -> str | None:
    """The output line of one item; None when its worktree and branch are both gone."""
    path, branch = entry["worktree"], entry["branch"]
    item = f"{path} branch={branch}"
    listed = worktrees(entry["common_dir"]).get(path)
    if listed is None:
        problem, exists = gone_check(entry)
        if problem:
            return f"SKIPPED {item} reason={problem}"
        if not exists:
            return None
    reason = identity_reason(entry, listed) or skip_reason(entry, ctx, listed)
    if reason:
        return f"SKIPPED {item} reason={reason}"
    if ctx.dry_run:
        return f"WOULD-REMOVE {item}"
    if listed is not None:
        copied, problem = copy_logs(path, ctx.run_dir)
        if problem:
            return f"SKIPPED {item} reason={problem}"
        problem = remove_worktree(entry, listed)
        if problem:
            return f"SKIPPED {item} reason={problem}"
        if copied:
            item += f" logs={copied}"
    problem = delete_branch(entry, ctx)
    if problem:
        state = "worktree removed; " if listed is not None else ""
        return f"SKIPPED {item} reason={state}{problem}"
    return f"REMOVED {item}"


# --- input ------------------------------------------------------------------------------

def read_manifest(path: Path) -> tuple[list[dict], list[str]]:
    entries, bad, seen = [], [], set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            entry = None
        if not isinstance(entry, dict) or not all(
                isinstance(entry.get(key), str) and entry.get(key)
                for key in ("common_dir", "worktree", "branch")):
            bad.append(f"SKIPPED {path.name}:{number} reason=bad manifest line")
            continue
        entry["worktree"] = real(entry["worktree"])
        entry["common_dir"] = real(entry["common_dir"])
        if entry["worktree"] not in seen:
            seen.add(entry["worktree"])
            entries.append(entry)
    return entries, bad


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-run-checkout", action="store_true",
                        help="also remove the run checkout; only on the owner's request")
    args = parser.parse_args(argv)
    run_dir = Path(real(args.run_dir))
    manifest, run_md = run_dir / "created.jsonl", run_dir / "run.md"
    if not os.path.isabs(args.run_dir) or not manifest.is_file() or not run_md.is_file():
        print(f"cleanup-run: need an absolute --run-dir with created.jsonl and run.md: "
              f"{args.run_dir}", file=sys.stderr)
        return 2
    run = read_run(run_md.read_text(encoding="utf-8"))
    entries, bad = read_manifest(manifest)
    _, cwds = session_cwds()  # captain mode does not decide anything here (D6), only the cwds
    ctx = Context(run_id=run_dir.name, run=run, protected_cwds=cwds | {real(os.getcwd())},
                  dry_run=args.dry_run, run_dir=str(run_dir),
                  include_run_checkout=args.include_run_checkout)
    for line in read_lines(ctx.run):
        print(line)
    for line in bad:
        print(line)
    # the run checkout last: writer branches are deleted while it still holds the feature branch
    entries.sort(key=lambda entry: entry["worktree"] == ctx.run.checkout)
    gone = 0
    for entry in entries:
        line = handle(entry, ctx)
        if line is None:
            gone += 1
        else:
            print(line, flush=True)
    if gone:
        print(f"ALREADY-REMOVED {gone}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
