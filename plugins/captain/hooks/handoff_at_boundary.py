#!/usr/bin/env python3
"""PreToolUse hook on Agent|Task: before the NEXT task starts with a large context, hand off first (R21).

In a captain session (captain mode on, see guard.py) a task starts when the main session dispatches a
WRITER (`captain:worker`, `captain:light-coder`, `captain:light-coder-sol`) for a new task. Reviews,
verifications, votes, fixes, merges, conflict resolution and the other non-writing agents happen inside a
task and are not boundaries; neither is a dispatch while the session's checkout has a merge in progress. If a task is about to start and the main-session context is at or above the threshold (env
HANDOFF_CONTEXT_THRESHOLD, else `context_threshold` in ~/.claude/captain/config.json, else 250000; a
percentage such as `45%` is that share of the session model's context window), the
dispatch is denied once, with the instruction to write a handoff and hand over to /clear, or to a new
Supacode or cmux tab (config `successor_terminal` `supacode` or `cmux`, or no key and the session
runs in one of them).
Re-issuing the same dispatch goes through, so the owner can choose to continue in place. Subagents are
skipped.

Copy of coord's handoff-at-boundary.py in captain wording. Unlike the kickoff hook it does NOT stay
silent when ~/.claude/settings.json registers coord's global handoff-at-boundary.py: that hook only knows
`Implement ...` / `PR<n> T<n>` descriptions and the coord project threshold, so it never holds a captain
writer and a captain run went to 92% of its window with no gate (2026-10-05).
Fails open: any error means no output.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import handoff_common as common  # noqa: E402

WRITERS = {"worker", "light-coder", "light-coder-sol"}
# Inside a task, not a start: reviews, verification, votes, fixes, merges and their conflicts, cleanup,
# diagnosis, recon. The Cyrillic alternates are deliberate: they match the same words in Bulgarian
# task descriptions, since the captain writes descriptions in the owner's language.
INSIDE_TASK = re.compile(r"review|ревю|ревизи|verif|верифи|vote|глас|judge|съдия|fix|поправ|integrat|интегр|"
                         r"merge|слей|слив|conflict|конфликт|resolv|разреш|clean|почист|diagnos|диагно|"
                         r"recon|разузна|bootstrap", re.IGNORECASE)
SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def state_dir() -> Path:
    override = os.environ.get("CAPTAIN_STATE_DIR")  # the same marker directory guard.py uses
    return Path(override) if override else Path.home() / ".claude" / "captain" / "sessions"


def already_denied(session: str, task_key: str) -> bool:
    """True if this task was already held once in this session; records it otherwise."""
    directory = common.CAPTAIN_DIR / "hook-state"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"handoff-{session}.json"
    try:
        denied = set(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        denied = set()
    if task_key in denied:
        return True
    denied.add(task_key)
    path.write_text(json.dumps(sorted(denied)), encoding="utf-8")
    return False


def is_task_start(tool_input: dict) -> bool:
    kind = str(tool_input.get("subagent_type") or "").split(":")[-1]
    return kind in WRITERS and not INSIDE_TASK.search(str(tool_input.get("description") or ""))


def git_lines(directory: str, *args: str) -> list[str]:
    try:
        out = subprocess.run(["git", "-C", directory, *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    return out.stdout.splitlines() if out.returncode == 0 else []


def merge_in_progress(cwd) -> bool:
    """True when any worktree of the repository at `cwd` has a MERGE_HEAD file: a merge waits for its
    resolver, so the dispatch is inside a task. The run worktree, where main merges, is usually not the
    session's own checkout (Codex r1 F2). Anything unreadable is False."""
    if not isinstance(cwd, str) or not cwd or not os.path.isabs(cwd):
        return False
    trees = [line[len("worktree "):] for line in git_lines(cwd, "worktree", "list", "--porcelain")
             if line.startswith("worktree ")]
    for tree in trees or [cwd]:
        path = git_lines(tree, "rev-parse", "--path-format=absolute", "--git-path", "MERGE_HEAD")
        if path and os.path.isfile(path[0]):
            return True
    return False


def main() -> None:
    data = json.load(sys.stdin)
    if data.get("tool_name") not in ("Agent", "Task"):
        return
    transcript = data.get("transcript_path") or ""
    session = data.get("session_id")
    if data.get("agent_id") or data.get("agent_type") or "/subagents/" in transcript:
        return
    if not isinstance(session, str) or not SESSION_ID.match(session) or not (state_dir() / session).is_file():
        return  # not a captain session
    tool_input = data.get("tool_input") or {}
    if not is_task_start(tool_input) or not os.path.exists(transcript) or merge_in_progress(data.get("cwd")):
        return
    description = str(tool_input.get("description") or "").strip()
    measure = common.load_measure()
    threshold, ctx = measure.config_threshold(transcript, background=True), measure.context_tokens(transcript)
    entry = {"hook": "boundary", "session": session, "task": description[:80], "ctx": ctx}
    if ctx < threshold:
        common.log({**entry, "action": "allow-below-threshold"})
        return
    if already_denied(session, description.lower()):
        common.log({**entry, "action": "allow-retry"})
        return
    common.log({**entry, "action": "hold-for-handoff"})
    k = ctx // 1000
    name = measure.session_name(transcript)
    where = (f"`~/.claude/kickoffs/{name}.md`" if name else
             "`~/.claude/kickoffs/<session name>.md` (this session has no name yet: ask the owner to "
             "`/rename` it first)")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"[handoff gate, R21] You are about to start a NEW task ('{description}') with ~{k}k tokens of "
            f"context (threshold {threshold // 1000}k). Every turn re-reads the whole context. Do NOT start it "
            "here. Instead: make sure no agent is running without a recorded hand-back and no merge is staged, "
            "an agent has committed and pushed the finished work (R5), then follow reference/handoff.md: write "
            "the self-contained handoff to tmp/captain/<run>/ and " + successor_steps(where, k) +
            f" The next session starts with exactly this task: '{description}'. If the owner says to continue "
            "in this session, re-issue the same Agent call: it will go through."
        ),
    }}, ensure_ascii=False))


def successor_steps(where: str, k: int) -> str:
    """How the successor starts, per the config's `successor_terminal`."""
    if common.successor_terminal() in ("supacode", "cmux"):
        return ("follow § Successor terminal there (Supacode or cmux: set in the config or detected): write no "
                "kickoff yet and launch no agent; `ListAgents` gives this session's name; a `captain:runner` "
                "runs `scripts/successor-tab.py --dir --handoff --from --name`; on TAB-OK wait up to 3 minutes "
                "for the successor's STARTED message, check its pwd, reply ACK with any owner words since the "
                "handoff, end your timers (CronDelete, TaskStop for fallback sleeps), tell the owner one line "
                f"\"Context is {k}k — handoff at <path>; successor <name> confirmed in <pwd>; this tab can be "
                "closed\", then stop. TERMINAL-NONE, FAILED (TAB-DEAD: nothing ran in the tab; the script "
                "closed it, or with closed=no give the owner the close command) or no STARTED → (once a tab "
                f"exists, a STAND-DOWN to it first) the /clear steps with the kickoff at {where}. A STAND-DOWN "
                "that is not reachable means no successor exists: no retry, no more waiting.")
    return (f"have a `captain:runner` write the successor's kickoff to {where}; the kickoff-on-clear hook "
            f"injects it after /clear. Tell the owner one line: \"Context is {k}k — handoff at <path>; type "
            "/clear, then `/captain resume`\"; then stop.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # fail open
        common.log({"hook": "boundary", "error": repr(error)})
    sys.exit(0)
