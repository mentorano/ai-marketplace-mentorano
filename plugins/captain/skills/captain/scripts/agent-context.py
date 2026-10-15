#!/usr/bin/env python3
"""Print how full each captain agent's context is, and whether to replace the agent.

Usage: python3 agent-context.py [--total] <agentId> [<agentId> ...]

Finds ~/.claude/projects/*/*/subagents/agent-<agentId>.jsonl (the newest one when several
match; CAPTAIN_PROJECTS_DIR overrides the projects directory) and reads the usage of the
agent's last model call: input + cache read + cache creation + output tokens. That sum is
what the agent's next turn starts from.

One line per agent:
  <agentId> <tokens> tokens <percent>% keep|replace
  <agentId> unknown replace      (no usable usage record: treat as full)
  <agentId> not found replace    (no transcript: treat as full)
`replace` means the agent used at least 20% of a 1M-token context window: when its current
task ends, the coordinator stops it and gives the next task to a fresh agent (R6).

--total prints instead the tokens the agent spent in all: the sum of the usage of every model
call in its transcript, resumed periods included (a writer duel's `tokens`). Claude Code writes
one line per content block and repeats the call's usage on each, so a call is counted once per
message id; a call without an id counts once per line.
  <agentId> <tokens> tokens total
  <agentId> unknown              (no usable usage record)
  <agentId> not found            (no transcript)

Exit codes: 0 every agent measured; 1 at least one not found or unknown; 2 bad arguments.
The main session may run the default form (R1): it reads only the usage numbers, never the
transcript text, and prints no agent output. `--total` is run only by the integration agent
(a subagent) for a duel record, never by main: the main allow-list and audit-main.py accept
only the default form.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

WINDOW = 1_000_000
REPLACE_AT = 0.20
AGENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
USAGE_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
              "output_tokens")


def projects_dir() -> Path:
    override = os.environ.get("CAPTAIN_PROJECTS_DIR")
    return Path(override) if override else Path.home() / ".claude" / "projects"


def transcript(agent: str) -> Path | None:
    found = list(projects_dir().glob(f"*/*/subagents/agent-{agent}.jsonl"))
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def usage_records(path: Path):
    """(message id or None, token sum) for every assistant line with a usable usage record."""
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if '"usage"' not in line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict) or entry.get("type") != "assistant":
                continue
            message = entry.get("message")
            usage = message.get("usage") if isinstance(message, dict) else None
            if not isinstance(usage, dict):
                continue
            counts = [usage[key] for key in USAGE_KEYS if key in usage]
            # a record with any bad count (a bool, a negative, a string) is not a measurement
            if counts and all(type(count) is int and count >= 0 for count in counts):
                message_id = message.get("id")
                yield (message_id if isinstance(message_id, str) else None), sum(counts)


def last_context(path: Path) -> int | None:
    """Context of the last model call with a usable usage record; None when there is none."""
    tokens = None
    for _, tokens in usage_records(path):
        pass
    return tokens


def total_tokens(path: Path) -> int | None:
    """Sum over every model call, each message id once (its last record); None when none."""
    by_id: dict[str, int] = {}
    anonymous: list[int] = []
    for message_id, tokens in usage_records(path):
        if message_id is None:
            anonymous.append(tokens)
        else:
            by_id[message_id] = tokens
    if not by_id and not anonymous:
        return None
    return sum(by_id.values()) + sum(anonymous)


def main(argv: list[str]) -> int:
    total = bool(argv) and argv[0] == "--total"
    if total:
        argv = argv[1:]
    if not argv or not all(AGENT_ID.match(agent) for agent in argv):
        print("usage: agent-context.py [--total] <agentId> [<agentId> ...]", file=sys.stderr)
        return 2
    verdict_suffix = "" if total else " replace"
    missing = False
    for agent in argv:
        path = transcript(agent)
        if path is None:
            print(f"{agent} not found{verdict_suffix}")
            missing = True
            continue
        tokens = total_tokens(path) if total else last_context(path)
        if tokens is None:
            print(f"{agent} unknown{verdict_suffix}")
            missing = True
            continue
        if total:
            print(f"{agent} {tokens} tokens total")
            continue
        verdict = "replace" if tokens >= WINDOW * REPLACE_AT else "keep"
        print(f"{agent} {tokens} tokens {tokens * 100 // WINDOW}% {verdict}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
