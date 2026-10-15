#!/usr/bin/env python3
"""Per-session context size for a project's Claude Code sessions. Read-only. Copy of coord's script;
the threshold comes from the captain config (`context_threshold`). A `captain:runner` runs it for main (R21).

Usage: measure-context.py <repo path> [hours=24] [--threshold N] [--all]

The threshold is --threshold, else the config's `context_threshold`; both take tokens (250000,
250k) or a percentage of the context window of each session's model (45%, `config_threshold`).

Reads ~/.claude/projects/<project dir>/*.jsonl for the repo and every worktree of it (a session is
filed under the directory it was started in). By default only the newest transcript per name (the live session); --all shows history. For each transcript modified in the last N hours:
context = last main-chain assistant usage (input + cache_read + cache_creation), name from the
custom-title / agent-name records. Subagent transcripts are skipped.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

TAIL_BYTES = 4 * 1024 * 1024
PROJECTS = os.path.expanduser("~/.claude/projects")


def project_dir_name(path):
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(path))


DEFAULT_THRESHOLD = 250000
PERCENT = re.compile(r"^(\d{1,2}(?:\.\d+)?)\s*%$")
MODEL = re.compile(r"^claude-[A-Za-z0-9._-]+$")
WINDOWS = os.path.expanduser("~/.claude/captain/context-windows.json")
WINDOW_MAX_AGE = 24 * 3600
PROBE_RETRY_AFTER = 3600  # a failed probe is not repeated for an hour: the hook must stay fast
PROBE_TIMEOUT = 15  # the boundary hook's own timeout is 30 s (hooks/hooks.json)


def raw_threshold():
    """HANDOFF_CONTEXT_THRESHOLD env, else `context_threshold` in ~/.claude/captain/config.json."""
    raw = os.environ.get("HANDOFF_CONTEXT_THRESHOLD")
    if raw:
        return raw
    try:
        with open(os.path.expanduser("~/.claude/captain/config.json"), encoding="utf-8") as fh:
            return (json.load(fh) or {}).get("context_threshold")
    except (OSError, ValueError, AttributeError):
        return None


def config_threshold(transcript=None, background=False):
    """The handoff threshold in tokens. A number (`250000`) or `250k` is absolute. A percentage
    (`45%`) is that share of the context window of the model the session in `transcript` runs on
    (`context_window`), so it follows the model and any change of its window. Anything else, or a
    percentage whose window is unknown, → 250000. The same rule as the handoff_at_boundary hook,
    so both agree on what "over" means."""
    return resolve_threshold(raw_threshold(), transcript, background)


def resolve_threshold(raw, transcript=None, background=False):
    """`raw` (a config value or a --threshold argument) in tokens for the session in `transcript`;
    see config_threshold."""
    if raw is None or isinstance(raw, bool):
        return DEFAULT_THRESHOLD
    text = str(raw).strip()
    percent = PERCENT.match(text)
    if percent:
        window = context_window(session_model(transcript), background=background) if transcript else None
        share = float(percent.group(1))
        return int(window * share / 100) if window and 0 < share < 100 else DEFAULT_THRESHOLD
    m = re.match(r"^(\d+)([kK]?)$", text)
    if m:
        return int(m.group(1)) * (1000 if m.group(2) else 1)
    return DEFAULT_THRESHOLD


def session_model(path):
    """The model of the last main-chain assistant message in the transcript, or None."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - TAIL_BYTES))
            lines = fh.read().decode("utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if '"model"' not in line or '"assistant"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        model = (entry.get("message") or {}).get("model")
        if entry.get("type") == "assistant" and not entry.get("isSidechain") and MODEL.match(str(model)):
            return model
    return None


def context_window(model, now=None, background=False, force=False):
    """The model's context window in tokens, as Claude Code itself reports it: `contextWindow` in
    `modelUsage` of a one-word `claude -p --output-format json` call (no tools, no settings, no
    session kept; a few seconds, about two cents). Cached per model in
    ~/.claude/captain/context-windows.json for 24 hours. A stale value is used as it is while it is
    refreshed: in a detached process when `background` (the boundary hook must stay fast), else
    in place. Only a model with no value at all waits for the probe. A probe is tried at most once
    an hour; a failed one keeps the stale value."""
    if not model or not MODEL.match(model):
        return None
    now = time.time() if now is None else now
    try:
        with open(WINDOWS, encoding="utf-8") as fh:
            cache = json.load(fh)
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, ValueError):
        cache = {}
    entry = cache.get(model) if isinstance(cache.get(model), dict) else {}
    window = entry.get("window") if isinstance(entry.get("window"), int) and entry["window"] > 0 else None
    if not force:
        if window and now - _number(entry.get("at")) < WINDOW_MAX_AGE:
            return window
        if now - _number(entry.get("tried_at")) < PROBE_RETRY_AFTER:
            return window
    cache[model] = {**entry, "tried_at": int(now)}
    if window and background:
        _write_cache(cache)
        _refresh_detached(model)
        return window
    probed = probe_window(model)
    if probed:
        cache[model] = {"window": probed, "at": int(now)}
    _write_cache(cache)
    return probed or window


def _write_cache(cache):
    try:
        os.makedirs(os.path.dirname(WINDOWS), exist_ok=True)
        tmp = f"{WINDOWS}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cache, fh)
        os.replace(tmp, WINDOWS)
    except OSError:
        pass


def _refresh_detached(model):
    """`measure-context.py --refresh-window <model>` in its own session, so it outlives the hook."""
    try:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "--refresh-window", model],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError:
        pass


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def probe_window(model):
    claude = shutil.which("claude")
    if not claude:
        return None
    try:
        out = subprocess.run(
            [claude, "-p", "Reply with the single word OK.", "--model", model, "--output-format", "json",
             "--no-session-persistence", "--tools", "", "--strict-mcp-config", "--setting-sources", ""],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT, stdin=subprocess.DEVNULL).stdout
        usage = json.loads(out).get("modelUsage") or {}
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return None
    entry = usage.get(model) if isinstance(usage, dict) else None  # never another model's window
    window = entry.get("contextWindow") if isinstance(entry, dict) else None
    return window if isinstance(window, int) and not isinstance(window, bool) and window > 0 else None


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
    if len(argv) == 2 and argv[0] == "--refresh-window":
        return 0 if context_window(argv[1], force=True) else 1
    threshold, latest, args = None, True, []  # newest transcript per name by default; --all shows history
    it = iter(argv)
    for a in it:
        if a == "--threshold":
            threshold = next(it, None)
            if threshold is None or not (PERCENT.match(threshold) or re.match(r"^\d+[kK]?$", threshold)):
                print("--threshold requires tokens (250000, 250k) or a percentage (45%)", file=sys.stderr)
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
            rows.append((context_tokens(p), session_name(p) or "(unnamed)", wt, fn[:8], mtime, p))
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
    for ctx, name, wt, sid, mtime, path in rows:
        age = time.time() - mtime
        last = f"{age / 60:.0f}m" if age < 3600 else f"{age / 3600:.1f}h"
        limit = resolve_threshold(threshold, path) if threshold is not None else config_threshold(path)
        flag = "OVER" if ctx >= limit else ""
        print(f"{name[:28]:<28} {ctx // 1000:>5}k {last:>8}  {flag:<4}  {wt} / {sid}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
