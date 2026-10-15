#!/usr/bin/env python3
"""SessionStart hook (matcher "clear"): load the kickoff the previous captain session left (R21).

At a handoff boundary the captain writes the successor's kickoff to
`~/.claude/kickoffs/<session name>.md` (the name from /rename, never the cwd: two sessions can
share one). After /clear this hook resolves the session's name from the transcript (the LAST
customTitle/agentName record wins, so a session renamed later resolves to its latest name),
injects that file as additional context and moves it to `~/.claude/kickoffs/kickoff-used/`, so a
later /clear never replays it. Only /clear triggers it. There is no fallback to a repo file.

Copy of coord's kickoff-on-clear.py, named kickoffs only. It stays silent when ~/.claude/settings.json
already registers coord's global kickoff-on-clear.py (that hook does the same job).
Fails open: any error means no output.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import handoff_common as common  # noqa: E402

STALE_HOURS = 24


def kickoff_dir() -> Path:
    return Path.home() / ".claude" / "kickoffs"


def main() -> None:
    data = json.load(sys.stdin)
    if data.get("source") != "clear" or common.coord_hook_installed("kickoff-on-clear.py"):
        return
    name = common.load_measure().session_name(data.get("transcript_path"))
    if not name or "/" in name or name.startswith("."):
        return
    path = kickoff_dir() / f"{name}.md"
    if not path.is_file():
        return
    kickoff = path.read_text(encoding="utf-8").strip()
    if not kickoff:
        return
    age_h = (time.time() - path.stat().st_mtime) / 3600
    used = kickoff_dir() / "kickoff-used"
    used.mkdir(parents=True, exist_ok=True)
    # Microseconds + pid: two sessions cleared in the same second must not overwrite each other's archive.
    stamp = datetime.now().strftime("%Y-%m-%dT%H%M%S-%f") + f"-{os.getpid()}"
    os.replace(path, used / f"{stamp}.md")
    stale = (f" WARNING: it was written {age_h:.0f} hours ago; re-derive state before trusting anything it implies."
             if age_h > STALE_HOURS else "")
    context = ("CAPTAIN KICKOFF FOR THIS SESSION. The owner just ran /clear; before that, the previous captain "
               f"session wrote this kickoff for its successor (file {path}, now moved to kickoff-used/).{stale} "
               "Follow it when the owner sends the next message (`/captain resume`):\n\n" + kickoff)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}},
                     ensure_ascii=False))
    common.log({"hook": "kickoff", "name": name, "age_h": round(age_h, 1), "session": data.get("session_id")})


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # fail open
        common.log({"hook": "kickoff", "error": repr(error)})
    sys.exit(0)
