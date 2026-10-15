#!/usr/bin/env python3
"""Per-session context size for a project's Claude Code sessions. Read-only.

Usage: measure-context.py <repo path> [hours=24] [--threshold N] [--all]

Reads ~/.claude/projects/<project dir>/*.jsonl for the repo and every worktree of it (a session is
filed under the directory it was started in). By default only the newest transcript per name (the live session); --all shows history. For each transcript modified in the last N hours:
context = last main-chain assistant usage (input + cache_read + cache_creation), name from the
custom-title / agent-name records. Subagent transcripts are skipped.
"""
import json
import os
import re
import subprocess
import sys
import time

TAIL_BYTES = 4 * 1024 * 1024
PROJECTS = os.path.expanduser("~/.claude/projects")


def project_dir_name(path):
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(path))


def config_threshold(repo):
    """HANDOFF_CONTEXT_THRESHOLD env, else <primary checkout>/.coord/project.md's `context_threshold`,
    else 250000. Accepts plain digits (`250000`) or a `250k`-style suffix. Same rule as the
    handoff-at-boundary hook, so both agree on what "over" means for this project."""
    raw = os.environ.get("HANDOFF_CONTEXT_THRESHOLD")
    if not raw:
        try:
            common = subprocess.run(["git", "-C", repo, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                    capture_output=True, text=True, timeout=5).stdout.strip()
            with open(os.path.join(os.path.dirname(common), ".coord", "project.md")) as fh:
                for line in fh:
                    m = re.match(r"^\s*context_threshold:\s*(.*)$", line.rstrip("\n"))
                    if m:
                        raw = re.sub(r"\s*#.*$", "", m.group(1)).strip()
                        break
        except (OSError, subprocess.SubprocessError):
            pass
    if raw:
        m = re.match(r"^(\d+)([kK]?)$", raw.strip())
        if m:
            return int(m.group(1)) * (1000 if m.group(2) else 1)
    return 250000


def worktree_paths(repo):
    try:
        out = subprocess.run(["git", "-C", repo, "worktree", "list", "--porcelain"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return [repo]
    paths = [line[9:] for line in out.splitlines() if line.startswith("worktree ")]
    return paths or [repo]


def context_tokens(path):
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
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


def session_name(path):
    """Last custom-title / agent-name record wins (a session can be renamed)."""
    name = None
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if '"customTitle"' not in line and '"agentName"' not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            name = rec.get("customTitle") or rec.get("agentName") or name
    return name


def main(argv):
    threshold, latest, args = None, True, []  # newest transcript per name by default; --all shows history
    it = iter(argv)
    for a in it:
        if a == "--threshold":
            try:
                threshold = int(next(it))
            except StopIteration:
                print("--threshold requires a value", file=sys.stderr)
                return 2
        elif a == "--latest":
            latest = True
        elif a == "--all":
            latest = False
        else:
            args.append(a)
    if not args:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    repo = os.path.expanduser(args[0])
    if threshold is None:
        threshold = config_threshold(repo)
    hours = float(args[1]) if len(args) > 1 else 24.0
    cutoff = time.time() - hours * 3600

    dirs = {}
    for wt in worktree_paths(repo):
        d = os.path.join(PROJECTS, project_dir_name(wt))
        if os.path.isdir(d):
            dirs[d] = wt
    rows = []
    for d, wt in dirs.items():
        for fn in os.listdir(d):
            p = os.path.join(d, fn)
            if not fn.endswith(".jsonl") or not os.path.isfile(p):
                continue
            mtime = os.path.getmtime(p)
            if mtime < cutoff:
                continue
            rows.append((context_tokens(p), session_name(p) or "(unnamed)", wt, fn[:8], mtime))
    if not rows:
        print(f"no transcripts modified in the last {hours:g}h for {repo} and its worktrees")
        return 0
    rows.sort(key=lambda r: -r[4])
    if latest:
        # Group by name, except unnamed sessions ("(unnamed)") all share that one label and would
        # otherwise collapse into a single row; group those by session id (the transcript file) instead.
        seen, kept = set(), []
        for r in rows:
            group_key = r[3] if r[1] == "(unnamed)" else r[1]
            if group_key not in seen:
                seen.add(group_key)
                kept.append(r)
        rows = kept
    print(f"{'session':<28} {'ctx':>6} {'last':>8}  flag  worktree / transcript")
    for ctx, name, wt, sid, mtime in rows:
        age = time.time() - mtime
        last = f"{age / 60:.0f}m" if age < 3600 else f"{age / 3600:.1f}h"
        flag = "OVER" if ctx >= threshold else ""
        print(f"{name[:28]:<28} {ctx // 1000:>5}k {last:>8}  {flag:<4}  {wt} / {sid}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
