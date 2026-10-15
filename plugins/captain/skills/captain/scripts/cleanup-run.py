#!/usr/bin/env python3
"""Remove the worktrees and branches a captain run created, and only those.

Usage: python3 cleanup-run.py --run-dir=<abs run-state dir> [--dry-run]

Reads only <run-dir>/created.jsonl (written by record-created.py) and <run-dir>/run.md.
For each recorded worktree and branch it prints exactly one line:
  REMOVED <worktree> branch=<branch>
  WOULD-REMOVE <worktree> branch=<branch>            (--dry-run: nothing changes)
  SKIPPED <worktree> branch=<branch> reason=<reason>

An item is skipped when:
- its worktree is or contains the working directory of a captain main session (the `cwd` in
  the guard's session markers, $CAPTAIN_STATE_DIR or ~/.claude/captain/sessions) or of this
  script;
- it is the run checkout (`Run checkout:` in run.md) while captain mode is on (any marker);
- its worktree has tracked or untracked changes;
- its branch is not merged into the run's feature branch, its base branch or
  origin/<default> (the branch itself does not count);
- its writer is still running: a row of the run.md `## Agents` table whose `Checkout (abs)`
  is the worktree and whose `notified` is not `yes`;
- it is locked by anything but Supacode, or git refuses a step.

An item is also skipped when run.md has no readable `## Agents` table, or when the worktree
(other than the run checkout) has no row there.

Removal: `git worktree unlock` only when the lock reason is JSON with top-level owner
"supacode" (the lock is put back if the remove then fails), `git worktree remove` without
--force, `git branch -d` (never -D; from the run checkout only when it is the same repository).
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
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

SESSION_ID = re.compile(r"^[A-Za-z0-9_-]+$")


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
    match = re.search(rf"(?m){re.escape(label)}:\s*(.+?)(?:\s{{3,}}|$)", text)
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
    running: set[str] = field(default_factory=set)
    agents: set[str] | None = None  # every `Checkout (abs)` in ## Agents; None: unreadable


def read_run(text: str) -> Run:
    feature = field_value(text, "Feature branch")
    base = field_value(text, "Base branch (R10)")
    checkout = field_value(text, "Run checkout")
    rows = table(text, "Agents")
    readable = bool(rows) and all("Checkout (abs)" in row and "notified" in row for row in rows)
    agents = {real(row["Checkout (abs)"]) for row in rows if row.get("Checkout (abs)")}
    running = {real(row.get("Checkout (abs)", "")) for row in rows
               if row.get("Checkout (abs)") and row.get("notified", "").lower() != "yes"}
    return Run(feature=feature.split(",")[0].strip() if feature else None,
               base=None if not base or base.lower().startswith("none")
               else base.split(",")[0].strip(),
               default=field_value(text, "Default branch"),
               checkout=real(checkout) if checkout else None,
               running=running, agents=agents if readable else None)


# --- the main session -------------------------------------------------------------------

def session_cwds() -> tuple[bool, set[str]]:
    """(captain mode on in any session, the cwd of every session in captain mode)."""
    override = os.environ.get("CAPTAIN_STATE_DIR")
    directory = Path(override) if override else Path.home() / ".claude" / "captain" / "sessions"
    on, cwds = False, set()
    if directory.is_dir():
        for marker in directory.iterdir():
            if not marker.is_file() or not SESSION_ID.match(marker.name):
                continue  # .merge and .base files carry a suffix
            on = True
            try:
                cwd = json.loads(marker.read_text(encoding="utf-8")).get("cwd")
            except (OSError, ValueError, AttributeError):
                cwd = None
            if isinstance(cwd, str) and cwd:
                cwds.add(real(cwd))
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


def merge_targets(common_dir: str, run: Run, branch: str) -> list[str]:
    default = git_out(common_dir, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if not default and run.default:
        default = f"origin/{run.default}"
    targets = [name for name in (run.feature, run.base, default) if name and name != branch]
    return [name for name in targets
            if git_out(common_dir, "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}")]


def merged(common_dir: str, run: Run, branch: str) -> bool:
    return any(run_git(common_dir, "merge-base", "--is-ancestor", branch, target).returncode == 0
               for target in merge_targets(common_dir, run, branch))


def branch_exists(common_dir: str, branch: str) -> bool:
    return git_out(common_dir, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}") is not None


# --- one item ---------------------------------------------------------------------------

@dataclass
class Context:
    run_id: str
    run: Run
    mode_on: bool
    protected_cwds: set[str]
    dry_run: bool


def skip_reason(entry: dict, ctx: Context, listed: dict[str, str] | None) -> str | None:
    common, path, branch = entry["common_dir"], entry["worktree"], entry["branch"]
    if entry.get("run_id") != ctx.run_id:
        return f"recorded for run {entry.get('run_id')}, not {ctx.run_id}"
    if any(inside(cwd, path) for cwd in ctx.protected_cwds):
        return "worktree is the working directory of a main session or of this script"
    if ctx.mode_on and ctx.run.checkout and path == ctx.run.checkout:
        return "run checkout while captain mode is on"
    if ctx.run.agents is None:
        return "run.md has no readable ## Agents table"
    if path != ctx.run.checkout and path not in ctx.run.agents:
        return "no agent row for this worktree in run.md"
    if path in ctx.run.running:
        return "writer still running in run.md"
    if listed is not None:
        if listed.get("main"):
            return "main worktree of the repository"
        if listed.get("branch") != branch:
            return f"worktree is on {listed.get('branch') or 'a detached HEAD'}, not {branch}"
        lock = listed.get("locked")
        if lock and not supacode_lock(lock):
            return f"locked by another tool: {lock}"
        status = git_out(path, "status", "--porcelain", "--untracked-files=all")
        if status is None:
            return "git status failed"
        if status:
            return "worktree has tracked or untracked changes"
    if branch_exists(common, branch) and not merged(common, ctx.run, branch):
        return "branch not merged into the feature branch, its base or origin/<default>"
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
    # `branch -d` checks the merge against HEAD of the directory it runs in: the run checkout
    # holds the feature branch, into which writer branches merge.
    where = common
    if (ctx.run.checkout and ctx.run.checkout != entry["worktree"]
            and os.path.isdir(ctx.run.checkout) and same_repo(ctx.run.checkout, common)):
        where = ctx.run.checkout
    result = run_git(where, "branch", "-d", branch)
    return None if result.returncode == 0 else f"git branch -d refused: {first_line(result)}"


def handle(entry: dict, ctx: Context) -> str:
    path, branch = entry["worktree"], entry["branch"]
    item = f"{path} branch={branch}"
    listed = worktrees(entry["common_dir"]).get(path)
    if listed is None and not branch_exists(entry["common_dir"], branch):
        return f"SKIPPED {item} reason=already removed"
    reason = skip_reason(entry, ctx, listed)
    if reason:
        return f"SKIPPED {item} reason={reason}"
    if ctx.dry_run:
        return f"WOULD-REMOVE {item}"
    if listed is not None:
        problem = remove_worktree(entry, listed)
        if problem:
            return f"SKIPPED {item} reason={problem}"
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
    args = parser.parse_args(argv)
    run_dir = Path(real(args.run_dir))
    manifest, run_md = run_dir / "created.jsonl", run_dir / "run.md"
    if not os.path.isabs(args.run_dir) or not manifest.is_file() or not run_md.is_file():
        print(f"cleanup-run: need an absolute --run-dir with created.jsonl and run.md: "
              f"{args.run_dir}", file=sys.stderr)
        return 2
    mode_on, cwds = session_cwds()
    ctx = Context(run_id=run_dir.name, run=read_run(run_md.read_text(encoding="utf-8")),
                  mode_on=mode_on, protected_cwds=cwds | {real(os.getcwd())},
                  dry_run=args.dry_run)
    entries, bad = read_manifest(manifest)
    for line in bad:
        print(line)
    # the run checkout last: writer branches are deleted while it still holds the feature branch
    entries.sort(key=lambda entry: entry["worktree"] == ctx.run.checkout)
    for entry in entries:
        print(handle(entry, ctx), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
