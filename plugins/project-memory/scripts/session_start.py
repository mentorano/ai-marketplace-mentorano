#!/usr/bin/env python3
"""SessionStart hook (matcher "startup"): one line about project memory, or nothing.

Reads the hook JSON on stdin and checks the memory at the repo root of its `cwd` (memory.py):
  - layout absent  -> no output;
  - layout broken  -> one warning line with the reason;
  - level due/overdue -> one line with the level and the top reasons, asking the session to
    suggest the defragment to the user once;
  - otherwise no output.
Output: {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "<text>"}},
the text capped at 1,000 characters. Any error, malformed input included: exit 0, no output.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CAP = 1000
LINE_BREAKERS = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029]")
TOP_REASONS = 3
INIT = "`/project-memory:memory-init`"
DEFRAG = "`/project-memory:memory-defrag`"


def clip_middle(head: str, middle: str, tail: str, cap: int = CAP) -> str:
    """head + middle + tail within cap characters; only the middle is shortened."""
    middle = LINE_BREAKERS.sub(" ", middle)
    room = cap - len(head) - len(tail)
    if len(middle) > room:
        middle = middle[:max(room - 1, 0)] + "…"
    return (head + middle + tail)[:cap]


def message(rep: dict) -> str | None:
    if rep.get("layout") == "absent":
        return None
    if rep.get("layout") == "broken":
        return clip_middle("project memory is not fully loading in this session: ",
                           str(rep.get("layout_reason") or "unknown reason"),
                           f"; start the session at the repo root, or run {INIT} to repair")
    level = rep.get("level")
    if level in ("due", "overdue"):
        reasons = "; ".join(rep.get("reasons", [])[:TOP_REASONS]) or "thresholds crossed"
        return clip_middle(f"project memory health is {level}: ", reasons,
                           f". Suggest {DEFRAG} to the user once; do not run it yourself.")
    return None


def main() -> None:
    data = json.loads(sys.stdin.read())
    if not isinstance(data, dict) or not isinstance(data.get("cwd"), str) or not data["cwd"]:
        return
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import memory  # noqa: E402

    text = message(memory.status(data["cwd"]))
    if text:
        out = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}
        sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    try:
        main()
    except BaseException:  # noqa: BLE001 - a hook must never fail the session
        pass
    sys.exit(0)
