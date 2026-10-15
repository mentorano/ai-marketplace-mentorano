#!/usr/bin/env python3
"""Record a worktree and branch the captain run created, for cleanup-run.py.

Usage: python3 record-created.py --run-dir=<abs run-state dir> --worktree=<abs worktree>

Appends one JSON line to <run-dir>/created.jsonl:
  {"run_id", "common_dir", "worktree", "branch", "sha", "created"}
run_id is the name of the run-state directory (tmp/captain/<run-id>); common_dir is the
repository's git common dir; worktree is the canonical (realpath) worktree path; branch is the
branch checked out there; sha is its HEAD at creation. Every value is read from git, so the
model never writes the manifest by hand. The bootstrap agent runs it after it adds the run
worktree, and every writer after its `git worktree add`.

Refuses (exit 2, nothing written): a path that is not a git worktree, the repository's main
worktree, a detached HEAD, or a run directory that does not exist.
Exit codes: 0 recorded; 2 bad arguments or refused.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

MANIFEST = "created.jsonl"


def git(directory: str, *args: str) -> str | None:
    result = subprocess.run(["git", "-C", directory, *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def entry_for(run_dir: Path, worktree: str) -> tuple[dict | None, str]:
    path = os.path.realpath(worktree)
    top = git(path, "rev-parse", "--show-toplevel")
    if top is None or os.path.realpath(top) != path:
        return None, f"not the top of a git worktree: {path}"
    common = git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    own = git(path, "rev-parse", "--path-format=absolute", "--git-dir")
    if common is None or own is None:
        return None, f"cannot read the git dirs of {path}"
    if os.path.realpath(common) == os.path.realpath(own):
        return None, f"the main worktree of its repository, not a created one: {path}"
    branch = git(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    if not branch:
        return None, f"detached HEAD, no branch to record: {path}"
    sha = git(path, "rev-parse", "HEAD")
    if sha is None:
        return None, f"no commit at HEAD: {path}"
    return {"run_id": run_dir.name, "common_dir": os.path.realpath(common), "worktree": path,
            "branch": branch, "sha": sha,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, ""


def append(run_dir: Path, entry: dict) -> None:
    line = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
    # one write on an O_APPEND descriptor: parallel writers do not interleave their lines
    fd = os.open(run_dir / MANIFEST, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--worktree", required=True)
    args = parser.parse_args(argv)
    run_dir = Path(os.path.realpath(args.run_dir))
    if not os.path.isabs(args.run_dir) or not run_dir.is_dir():
        print(f"record-created: --run-dir must be an existing absolute directory: {args.run_dir}",
              file=sys.stderr)
        return 2
    entry, problem = entry_for(run_dir, args.worktree)
    if entry is None:
        print(f"record-created: refused, {problem}", file=sys.stderr)
        return 2
    append(run_dir, entry)
    print(f"RECORDED {entry['worktree']} branch={entry['branch']} sha={entry['sha']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
