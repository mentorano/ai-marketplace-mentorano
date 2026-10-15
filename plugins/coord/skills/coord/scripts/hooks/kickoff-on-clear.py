#!/usr/bin/env python3
"""SessionStart hook (matcher "clear"): load the kickoff the previous session left for this session.

When a coordinated session (coord or a lane) reaches a handoff boundary, it writes the successor's
kickoff to `~/.claude/kickoffs/<session name>.md` (named by /rename, not by worktree - two sessions
can share a cwd). The human then only types /clear in that session: this hook reads the session's
name from the transcript (the LAST customTitle/agentName record wins, so a session renamed after the
fact resolves to its latest name), looks up that file, injects it as additional context, and moves it
to `~/.claude/kickoffs/kickoff-used/` so a later /clear never replays it. A session with no name, or
no matching file, falls back to `<repo root>/.superpowers/kickoff-next.md` (moved to
`.superpowers/kickoff-used/`).
Only /clear triggers it; startup, resume and compact are ignored. Fails open: any error means no output.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime

LOG = os.path.expanduser("~/.claude/hooks/kickoff-on-clear.log")
STALE_HOURS = 24


def log(entry):
    try:
        with open(LOG, "a") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def repo_root(cwd):
    try:
        out = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return cwd


NAMED_DIR = os.path.expanduser("~/.claude/kickoffs")


def session_name(transcript_path):
    """The session's /rename name: the LAST custom-title / agent-name record wins, since a session
    can be renamed later (e.g. the owner renames an old session to `<name>-old` before its
    successor takes `<name>`). A streaming line-by-line scan of the whole transcript - names are
    small JSON lines, so this stays cheap even for a long transcript."""
    if not transcript_path or not os.path.isfile(transcript_path):
        return None
    name = None
    with open(transcript_path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if '"customTitle"' not in line and '"agentName"' not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            name = rec.get("customTitle") or rec.get("agentName") or name
    return name


def main():
    data = json.load(sys.stdin)
    if data.get("source") != "clear":
        return
    cwd = data.get("cwd") or os.getcwd()
    # A session opened outside its own worktree is found by name: ~/.claude/kickoffs/<name>.md wins.
    name = session_name(data.get("transcript_path"))
    named = os.path.join(NAMED_DIR, f"{name}.md") if name else None
    if named and os.path.isfile(named):
        root, path = NAMED_DIR, named
    else:
        root = repo_root(cwd)
        path = os.path.join(root, ".superpowers", "kickoff-next.md")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        kickoff = fh.read().strip()
    if not kickoff:
        return
    age_h = (time.time() - os.path.getmtime(path)) / 3600
    used_dir = os.path.join(root, "kickoff-used") if root == NAMED_DIR else os.path.join(root, ".superpowers", "kickoff-used")
    os.makedirs(used_dir, exist_ok=True)
    # Microseconds + pid keep two sessions /clear-ing in the same second from colliding and one
    # archived kickoff silently overwriting the other.
    stamp = datetime.now().strftime("%Y-%m-%dT%H%M%S-%f") + f"-{os.getpid()}"
    os.replace(path, os.path.join(used_dir, stamp + ".md"))
    stale = (f" WARNING: it was written {age_h:.0f} hours ago; re-derive state before trusting anything it implies."
             if age_h > STALE_HOURS else "")
    context = ("KICKOFF FOR THIS SESSION. The user just ran /clear in this worktree; before that, the previous "
               f"session here wrote this kickoff for its successor (file {path}, now moved to kickoff-used/).{stale} "
               "Follow it as the user's kickoff instruction as soon as the user sends any message (e.g. \"go\"):\n\n" + kickoff)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}},
                     ensure_ascii=False))
    log({"at": datetime.now().isoformat(timespec="seconds"), "root": root, "name": name, "age_h": round(age_h, 1),
         "session": data.get("session_id")})


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # fail open
        log({"at": datetime.now().isoformat(timespec="seconds"), "error": repr(exc)})
