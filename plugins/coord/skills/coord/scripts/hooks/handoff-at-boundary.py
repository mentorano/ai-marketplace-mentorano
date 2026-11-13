#!/usr/bin/env python3
"""PreToolUse hook on Agent: before the NEXT task starts with a large context, hand off first.

In the user's subagent-driven workflow, a task inside a scope starts when the main session
dispatches its implementer ("Implement Task 3: ...", "Implement PL2-B: ...", "PR2 T1 ...").
Reviews, fix waves and re-reviews happen inside a task and are not boundaries.
If a new task is about to start and the main-session context is at or above the threshold (env
HANDOFF_CONTEXT_THRESHOLD, else the project config's `context_threshold`, else 250000), the
dispatch is denied once, with an instruction to write a handoff and hand over: to a successor in a new
tab when the session runs in Supacode or cmux (procedures/handoff-and-sessions.md §Successor terminal),
else to /clear.
Re-dispatching the same task goes through, so the user can choose to continue in place.
Subagents are skipped. Fails open: any error means no output.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

DEFAULT_THRESHOLD = 250000
LOG = os.path.expanduser("~/.claude/hooks/handoff-boundary.log")
STATE_DIR = os.path.expanduser("~/.claude/hooks/state")
# A bare task code ("T1: ...") must be PR-prefixed to count as a task START: reviews and fix waves
# inside an existing task are also dispatched with that task's own code (e.g. "T1: address review
# comments"), and must not be mistaken for the task starting.
# The Bulgarian alternates are matched words, not text: a task described in Bulgarian still counts.
TASK_START = re.compile(r"^\s*(implement|имплементирай|имплементация)\b|^\s*PR\d+\s+T\d+\b", re.IGNORECASE)
TAIL_BYTES = 4 * 1024 * 1024


def log(entry):
    try:
        with open(LOG, "a") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def main_context_tokens(transcript_path):
    """Context size of the last main-chain assistant turn, from the transcript tail."""
    size = os.path.getsize(transcript_path)
    with open(transcript_path, "rb") as fh:
        fh.seek(max(0, size - TAIL_BYTES))
        lines = fh.read().decode("utf-8", errors="ignore").splitlines()
    for line in reversed(lines):
        if '"usage"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") != "assistant" or entry.get("isSidechain"):
            continue
        usage = (entry.get("message") or {}).get("usage") or {}
        return sum(usage.get(k) or 0 for k in
                   ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return 0


def already_denied(session_id, task_key):
    """True if this task was already held once in this session; records it otherwise."""
    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, f"handoff-{session_id}.json")
    try:
        with open(path) as fh:
            denied = set(json.load(fh))
    except (OSError, ValueError):
        denied = set()
    if task_key in denied:
        return True
    denied.add(task_key)
    with open(path, "w") as fh:
        json.dump(sorted(denied), fh)
    return False


def primary_checkout(cwd):
    """<primary checkout> for cwd's repo (the dir holding .coord/), or None if git fails."""
    try:
        common = subprocess.run(["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, timeout=5).stdout.strip()
        return os.path.dirname(common) if common else None
    except (OSError, subprocess.SubprocessError):
        return None


def project_config_lines(cwd):
    """Lines of <primary checkout>/.coord/project.md for this cwd's repo, or [] if there is none."""
    primary = primary_checkout(cwd)
    if not primary:
        return []
    try:
        with open(os.path.join(primary, ".coord", "project.md")) as fh:
            return fh.readlines()
    except OSError:
        return []


def config_value(cwd, key):
    """First `key: value` line in the project config, trailing ` # comment` stripped; None if absent."""
    pattern = re.compile(rf"^\s*{re.escape(key)}:\s*(.*)$")
    for line in project_config_lines(cwd):
        m = pattern.match(line.rstrip("\n"))
        if m:
            value = re.sub(r"\s*#.*$", "", m.group(1)).strip()
            return value or None
    return None


def cmux_automation(cwd):
    """True when the project's coord config (<primary checkout>/.coord/project.md) says `automation: cmux`."""
    return config_value(cwd, "automation") == "cmux"


def config_threshold(cwd):
    """HANDOFF_CONTEXT_THRESHOLD env, else the project config's `context_threshold`, else DEFAULT_THRESHOLD.
    Accepts plain digits (`250000`) or a `250k`-style suffix."""
    raw = os.environ.get("HANDOFF_CONTEXT_THRESHOLD") or config_value(cwd, "context_threshold")
    if raw:
        m = re.match(r"^(\d+)([kK]?)$", raw.strip())
        if m:
            return int(m.group(1)) * (1000 if m.group(2) else 1)
    return DEFAULT_THRESHOLD


def successor_terminal(env=None, home=None):
    """`supacode`, `cmux` or None: the terminal a successor tab would open in. Same rule as
    scripts/successor-tab.py: `successor_terminal` in ~/.claude/captain/config.json when the key is
    there, else Supacode when this session runs in it, else cmux, else None (the /clear path)."""
    env = os.environ if env is None else env
    home = home or os.path.expanduser("~")
    try:
        with open(os.path.join(home, ".claude", "captain", "config.json"), encoding="utf-8") as fh:
            config = json.load(fh)
    except (OSError, ValueError):
        config = None
    if isinstance(config, dict) and "successor_terminal" in config:
        value = config["successor_terminal"]
        return value if value in ("supacode", "cmux") else None
    if env.get("TERM_PROGRAM") == "supacode" and env.get("SUPACODE_WORKTREE_ID") and shutil.which("supacode"):
        return "supacode"
    bundled = env.get("CMUX_BUNDLED_CLI_PATH")
    if env.get("CMUX_SOCKET_PATH") and ((bundled and os.path.isfile(bundled) and os.access(bundled, os.X_OK)) or shutil.which("cmux")):
        return "cmux"
    return None


def kickoff_line(cwd, terminal):
    """Where the successor's kickoff goes and how the successor starts."""
    clear = ("Then write the successor's kickoff instruction (who it is, the one self-contained handoff file to read, "
             "what to start with) to `~/.claude/kickoffs/<your session name>.md`: the kickoff-on-clear hook injects "
             "it after /clear. ")
    if not terminal:
        return clear
    lane_note = (" (a coord LANE or the design/prototype session of an `automation: cmux` project skips this, writes its kickoff to "
                 "`~/.claude/kickoffs/<your session name>.md` and is restarted in place by coord)"
                 if cmux_automation(cwd) else "")
    return (f"The successor terminal is {terminal}, so the successor starts in a NEW tab under a new name{lane_note}: "
            "follow procedures/handoff-and-sessions.md §Successor terminal (kickoff in "
            "`~/.claude/kickoffs/successor/<your session name>.md`, then scripts/successor-tab.py, STARTED -> ACK). "
            "Only when the script prints no TAB-OK, or no STARTED comes, fall back to /clear: rewrite that kickoff for "
            "this session (it keeps its own name after /clear, so: you ARE <your session name>, and WITHOUT the "
            "successor-tab paragraph, since no one will send an ACK) into `~/.claude/kickoffs/<your session name>.md` "
            "(the kickoff-on-clear hook injects it after /clear), delete the copy under successor/, and: ")


def handover_line(k, cwd):
    """What the session says after writing its handoff: to the owner, or, for a cmux lane, to coord."""
    # The role is not guessed from cwd: sessions often run from the primary checkout whatever their role.
    manual = (f"Tell the user in one line: 'Context is at {k}k — the handoff is ready at <path>; type /clear, then "
              "<first message> — the kickoff loads by itself.', where <first message> is `/coord` if you are coord, "
              "`/coord lane` if you are a coord lane, else \"go\"; then stop. ")
    if not cmux_automation(cwd):
        return manual
    return ("This project runs `automation: cmux`. If you are a coord LANE or the sprint's design/prototype "
            "session: tell coord one line ('handoff at <path>; kickoff ready') and do NOT ask the user to /clear - "
            "coord restarts you in place; stop and stay idle. If you are coord itself or outside the sprint: " + manual)


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") not in ("Agent", "Task"):
        return
    transcript = data.get("transcript_path") or ""
    if data.get("agent_id") or data.get("agent_type") or "/subagents/" in transcript:
        return
    description = ((data.get("tool_input") or {}).get("description") or "").strip()
    if not TASK_START.search(description) or not os.path.exists(transcript):
        return
    cwd = data.get("cwd") or os.getcwd()
    threshold = config_threshold(cwd)
    ctx = main_context_tokens(transcript)
    entry = {"ts": datetime.now().isoformat(timespec="seconds"), "session": data.get("session_id"),
             "cwd": data.get("cwd"), "task": description[:80], "ctx": ctx}
    if ctx < threshold:
        entry["action"] = "allow-below-threshold"
        log(entry)
        return
    if already_denied(data.get("session_id") or "unknown", description.lower()):
        entry["action"] = "allow-retry"
        log(entry)
        return
    entry["action"] = "hold-for-handoff"
    log(entry)
    k = ctx // 1000
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"[handoff gate] You are about to start a NEW task ('{description}') with ~{k}k tokens of "
            f"context (threshold {threshold // 1000}k). Every turn re-reads the whole context, so this "
            "task would run at a high cost per turn. Do NOT start it here. Instead: make sure the previous "
            "task's work is committed and no subagents are still running, then write the handoff (the "
            "`handoff` skill if installed, else the coord skill's procedures/handoff-and-sessions.md). "
            f"The next session starts with exactly this task: '{description}'. "
            + kickoff_line(cwd, successor_terminal()) + handover_line(k, cwd) +
            "If the user explicitly says to continue in this session, re-issue the same Agent call: it "
            "will go through."
        ),
    }}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
