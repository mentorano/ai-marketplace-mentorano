#!/usr/bin/env python3
"""Archive stale captain session markers, only when the owner asks for it.

Usage: python3 archive-sessions.py --older-than-days=<n> [--dry-run] [--keep-session=<id> ...]

A session marker is a file in the state directory whose name matches ^[A-Za-z0-9_-]+$; its
sidecars are <id>.merge and <id>.base. The state directory is $CAPTAIN_STATE_DIR, else
~/.claude/captain/sessions (the guard's rule). A session is stale when the newest of these
mtimes is older than <n> days: the marker, its .merge, its .base, and the session transcript
<projects root>/*/<id>.jsonl when one is found (projects root: $CAPTAIN_PROJECTS_DIR, else
~/.claude/projects). An orphan .merge or .base (no marker) follows the same rule.

A stale session's files move to <parent of the state dir>/sessions-archive/<YYYYMMDD>/
(today), which is ~/.claude/captain/sessions-archive/<YYYYMMDD>/ for the default state dir.
Kept, with the reason printed:
  - the calling session: $CLAUDE_CODE_SESSION_ID (set by Claude Code for its child
    processes; hooks get the id from their input instead) and every --keep-session=<id>;
  - a session whose .merge or .base has a JSON "since" (epoch seconds) under 12 hours old;
  - a session with a file of the same name already in the archive directory (never
    overwritten).

Output: one line per session, `ARCHIVE <id> <files>` or `KEEP <id> <reason>`. When anything
was (or with --dry-run would be) moved, then the shell command that moves it all back, alone
on its line, and a last line: a session still open whose marker was archived needs
`/captain resume` (or `/captain`) to turn captain mode on again. --dry-run moves nothing and
prints the same lines. Nothing here runs automatically; the guard is not involved.

Exit codes: 0 done; 1 a move failed (the lines printed so far are true); 2 bad arguments.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import sys
import time
from pathlib import Path

SESSION_ID = re.compile(r"^[A-Za-z0-9_-]+$")
SIDECARS = (".merge", ".base")
SINCE_GUARD_SECONDS = 12 * 3600  # the guard's GRANT_MAX_SECONDS for .merge and .base
DAY_SECONDS = 86400


def state_dir() -> Path:
    override = os.environ.get("CAPTAIN_STATE_DIR")
    return Path(override) if override else Path.home() / ".claude" / "captain" / "sessions"


def projects_dir() -> Path:
    override = os.environ.get("CAPTAIN_PROJECTS_DIR")
    return Path(override) if override else Path.home() / ".claude" / "projects"


def sessions(directory: Path) -> dict[str, list[Path]]:
    """Session id -> its files in the state dir (marker first, then .merge, .base)."""
    found: dict[str, list[Path]] = {}
    for path in directory.iterdir():
        if not path.is_file() or path.is_symlink():
            continue
        name, suffix = path.name, ""
        for sidecar in SIDECARS:
            if name.endswith(sidecar):
                name, suffix = name[: -len(sidecar)], sidecar
                break
        if SESSION_ID.match(name):
            found.setdefault(name, []).append(path)
    order = {"": 0, ".merge": 1, ".base": 2}
    for files in found.values():
        files.sort(key=lambda p: order.get(p.suffix, 0))  # an id has no dot: suffix is the sidecar
    return found


def mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def newest_activity(sid: str, files: list[Path], projects: Path) -> tuple[float, str]:
    """(newest mtime, what it belongs to) over the session's files and its transcript."""
    best, what = 0.0, "-"
    candidates = list(files)
    if projects.is_dir():
        candidates += sorted(projects.glob(f"*/{sid}.jsonl"))
    for path in candidates:
        stamp = mtime(path)
        if stamp is not None and stamp > best:
            best, what = stamp, path.name
    return best, what


def fresh_since(files: list[Path], now: float) -> str | None:
    """The name of a .merge or .base whose JSON since is under 12 hours old, else None."""
    for path in files:
        if not path.name.endswith(SIDECARS):
            continue
        try:
            since = json.loads(path.read_text(encoding="utf-8").strip() or "null").get("since")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(since, (int, float)) and not isinstance(since, bool) \
                and now - since < SINCE_GUARD_SECONDS:
            return path.name
    return None


def decide(sid: str, files: list[Path], keep: set[str], max_age: float, now: float,
           projects: Path, archive: Path) -> str | None:
    """The KEEP reason for a session, or None when it is to be archived."""
    if sid in keep:
        return "calling session"
    newest, what = newest_activity(sid, files, projects)
    age = now - newest
    if age < max_age:
        return f"active {age / DAY_SECONDS:.1f} days ago ({what})"
    grant = fresh_since(files, now)
    if grant:
        return f"{grant} since is under 12 hours old"
    taken = [p.name for p in files if os.path.lexists(archive / p.name)]  # a dangling link too
    if taken:
        return f"already in archive: {archive / taken[0]}"
    return None


def move_no_replace(source: Path, target: Path) -> None:
    """Move source to target, never replacing target: os.link and O_EXCL both fail with
    FileExistsError when target exists, a dangling symlink included, at the moment of the call."""
    try:
        os.link(source, target)  # sessions() skips symlinks: source is a regular file
    except FileExistsError:
        raise
    except OSError:  # another filesystem (EXDEV) or one without hard links: copy into O_EXCL
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as writer, open(source, "rb") as reader:
                shutil.copyfileobj(reader, writer)
            shutil.copystat(source, target)
        except OSError:
            os.unlink(target)
            raise
    os.unlink(source)


def restore_command(archive: Path, moved: list[str], directory: Path) -> str:
    sources = " ".join(shlex.quote(str(archive / name)) for name in moved)
    return f"mv -n {sources} {shlex.quote(str(directory))}/"


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Archive stale captain session markers.")
    parser.add_argument("--older-than-days", type=float, required=True,
                        help="archive a session with no activity for this many days")
    parser.add_argument("--dry-run", action="store_true", help="move nothing, print the same lines")
    parser.add_argument("--keep-session", action="append", default=[],
                        help="a session id never to move (repeatable); the caller's "
                             "CLAUDE_CODE_SESSION_ID is always kept")
    args = parser.parse_args(argv)
    if not args.older_than_days > 0:
        parser.error("--older-than-days must be greater than 0")
    for sid in args.keep_session:
        if not SESSION_ID.match(sid):
            parser.error(f"--keep-session is not a session id: {sid}")
    return args


def main(argv: list[str]) -> int:
    args = parse(argv)
    directory = state_dir()
    if not directory.is_dir():
        print(f"no state directory: {directory}")
        return 0
    keep = set(args.keep_session)
    caller = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if SESSION_ID.match(caller):
        keep.add(caller)
    now = time.time()
    archive = directory.resolve().parent / "sessions-archive" / time.strftime("%Y%m%d")
    projects = projects_dir()
    moved: list[str] = []
    for sid, files in sorted(sessions(directory).items()):
        reason = decide(sid, files, keep, args.older_than_days * DAY_SECONDS, now, projects,
                        archive)
        if reason:
            print(f"KEEP {sid} {reason}")
            continue
        names = [p.name for p in files]
        if not args.dry_run:
            archive.mkdir(parents=True, exist_ok=True)
            for path in files:
                try:
                    move_no_replace(path, archive / path.name)
                except OSError as error:
                    print(f"ERROR {sid} cannot move {path}: {error}")
                    if moved:
                        print(restore_command(archive, moved, directory))
                    return 1
                moved.append(path.name)
        else:
            moved.extend(names)
        print(f"ARCHIVE {sid} {' '.join(names)}")
    if moved:
        print(restore_command(archive, moved, directory))
        print("NOTE a session still open whose marker was archived needs `/captain resume` "
              "(or `/captain`) to turn captain mode on again")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
