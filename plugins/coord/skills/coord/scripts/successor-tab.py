#!/usr/bin/env python3
"""Open a coord session's successor in a new terminal tab (procedures/handoff-and-sessions.md
§ Successor terminal).

    python3 successor-tab.py --dir=<abs dir> --kickoff=<abs kickoff file> --from=<this session's name> \
        --name=<successor name> [--wait=20]

A thin wrapper around the utils plugin's `new-session-tab.py` (skill `utils:new-session-tab`),
which opens the tab (Supacode always with `-w`, an ASCII-only command that reads the prompt from a
file, `claude -n`, the permission mode mirrored), waits for the alive marker `<name>.alive` and
closes a tab that ran nothing (TAB-DEAD). coord keeps no copy of that logic.

1. Chooses the terminal with the same rule as captain: `successor_terminal` in
   `~/.claude/captain/config.json` when that file has the key (`supacode`, `cmux`; anything else
   means none); otherwise Supacode when this session runs in it (TERM_PROGRAM=supacode,
   SUPACODE_WORKTREE_ID set, `supacode` on PATH), else cmux when CMUX_SOCKET_PATH is set and the cmux
   CLI is found ($CMUX_BUNDLED_CLI_PATH, else `cmux` on PATH), else none. The file is only read;
   coord works without it.
2. The same file's `session_prefix` goes in front of --name when the name does not start with it.
3. Checks the kickoff: an absolute file without spaces, NOT directly in `~/.claude/kickoffs/`.
   That directory is where the kickoff-on-clear hook looks on /clear; a successor's kickoff there
   would be injected again into the old session by a later /clear, giving two sessions one task.
4. Finds the utils script: the highest version under `~/.claude/plugins/cache/*/utils/<version>/`
   (COORD_PLUGIN_CACHE overrides the cache root) that has
   `skills/new-session-tab/scripts/new-session-tab.py` and answers `--version` with at least 0.5.0
   (the STARTED handshake). Not found or too old: `FAILED NO-UTILS` with the install or update
   command.
5. Runs it with `--prompt-file=<kickoff> --reply-to=<from>`: the tab reads a handshake copy that
   first makes the successor send `STARTED <name> pwd=<dir>: ...` to this session.

Prints the utils lines (`HANDSHAKE ...` first) and ends with exactly one result line:
    TAB-OK <tab id|surface ref> <worktree id|workspace id|-> <name> mode=<mode> prompt=<path>   exit 0
    TERMINAL-NONE <reason>                                                                     exit 3
    FAILED <CODE> <detail>                                                                     exit 1
TAB-OK means a shell ran in the tab, not that claude started: the successor's STARTED is the proof.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
PREFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
MIN_UTILS = (0, 5, 0)  # --reply-to and the STARTED handshake
UTILS_SCRIPT = Path("skills") / "new-session-tab" / "scripts" / "new-session-tab.py"
ALIVE_WAIT = 20  # seconds for the tab's shell to write the marker
SLACK = 600  # seconds on top of --wait for the utils script's own terminal calls


class Failed(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code, self.detail = code, detail


def read_config(home: Path) -> dict | None:
    """The owner's per-user captain config, read only; None when it is missing or unreadable."""
    try:
        with open(home / ".claude" / "captain" / "config.json", encoding="utf-8") as fh:
            config = json.load(fh)
    except (OSError, ValueError):
        return None
    return config if isinstance(config, dict) else None


def cmux_cli(env, which=shutil.which) -> str | None:
    """The cmux CLI: $CMUX_BUNDLED_CLI_PATH when it is an executable file, else `cmux` on PATH."""
    bundled = env.get("CMUX_BUNDLED_CLI_PATH")
    if bundled and os.path.isfile(bundled) and os.access(bundled, os.X_OK):
        return bundled
    return which("cmux")


def choose_terminal(config: dict | None, env, which=shutil.which) -> tuple[str, str]:
    """(`supacode` | `cmux` | `none`, reason). The boundary hook detects the same way."""
    config = config or {}
    if "successor_terminal" in config:
        value = config["successor_terminal"]
        if value in ("supacode", "cmux"):
            return value, "config"
        return "none", f"config successor_terminal={value!r}"
    if env.get("TERM_PROGRAM") == "supacode" and env.get("SUPACODE_WORKTREE_ID") and which("supacode"):
        return "supacode", "detected: this session runs in Supacode"
    if env.get("CMUX_SOCKET_PATH") and cmux_cli(env, which):
        return "cmux", "detected: this session runs in cmux"
    return "none", "no successor_terminal in the config and not running in Supacode or cmux"


def session_prefix(config: dict | None) -> str:
    """The owner's `session_prefix`, or "" when it is missing or not a valid name start."""
    value = (config or {}).get("session_prefix")
    return value if isinstance(value, str) and PREFIX.match(value) else ""


def check_args(args, home: Path) -> None:
    if not os.path.isabs(args.dir) or not os.path.isdir(args.dir):
        raise Failed("BAD-DIR", args.dir)
    kickoff = args.kickoff
    if not os.path.isabs(kickoff) or not os.path.isfile(kickoff) or any(c.isspace() for c in kickoff):
        raise Failed("BAD-KICKOFF", f"{kickoff!r} must be an absolute file path without spaces")
    named_dir = os.path.realpath(home / ".claude" / "kickoffs")
    if os.path.dirname(os.path.realpath(kickoff)) == named_dir:
        raise Failed("BAD-KICKOFF", f"{kickoff} is where /clear looks for kickoffs; "
                                    f"put it in {named_dir}/successor/")
    for flag, value in (("--from", args.from_name), ("--name", args.name)):
        if not NAME.match(value):
            raise Failed("BAD-NAME", f"{flag} {value!r} must match {NAME.pattern}")
    if args.from_name == args.name:
        raise Failed("BAD-NAME", "--name must differ from --from")


def parse_version(text: str) -> tuple[int, int, int] | None:
    found = VERSION.match(text.strip())
    return tuple(int(part) for part in found.groups()) if found else None


def answered_version(script: Path) -> tuple[int, int, int] | None:
    try:
        result = subprocess.run([sys.executable, str(script), "--version"],
                                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_version(result.stdout) if result.returncode == 0 else None


def marketplace() -> str:
    """This plugin's marketplace, from its install path `cache/<marketplace>/coord/<version>/`."""
    parts = Path(__file__).resolve().parts
    if "cache" in parts and len(parts) > parts.index("cache") + 2:
        return parts[parts.index("cache") + 1]
    return "<marketplace>"


def find_utils(cache: Path) -> Path:
    """The utils script of the highest installed version; Failed NO-UTILS when none is new enough."""
    candidates = []
    for script in cache.glob(f"*/utils/*/{UTILS_SCRIPT}"):
        version = parse_version(script.parents[3].name)
        if version:
            candidates.append((version, script))
    if not candidates:
        raise Failed("NO-UTILS", f"no utils plugin with new-session-tab under {cache}; "
                                 f"owner: claude plugin install utils@{marketplace()}")
    version, script = max(candidates)
    owner = f"utils@{script.parents[5].name}"  # the marketplace utils came from
    answered = answered_version(script)
    if answered is None or answered < MIN_UTILS:
        shown = ".".join(map(str, answered)) if answered else "no answer"
        raise Failed("NO-UTILS", f"utils {'.'.join(map(str, version))} answers --version with {shown}, "
                                 f"needs {'.'.join(map(str, MIN_UTILS))}; owner: claude plugin update {owner}")
    return script


def run_utils(script: Path, args, terminal: str) -> tuple[list[str], int]:
    command = [sys.executable, str(script), f"--dir={args.dir}", f"--prompt-file={args.kickoff}",
               f"--name={args.name}", f"--reply-to={args.from_name}", f"--terminal={terminal}",
               f"--wait={args.wait}"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=args.wait + SLACK)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Failed("UTILS-ERROR", f"new-session-tab.py: {type(error).__name__}")
    lines = result.stdout.strip().splitlines()
    if not lines:
        detail = (result.stderr.strip().splitlines() or [""])[-1]
        raise Failed("UTILS-ERROR", f"new-session-tab.py rc={result.returncode}: {detail}")
    if lines[-1].startswith("TAB-NONE"):
        return lines[:-1] + ["TERMINAL-NONE" + lines[-1][len("TAB-NONE"):]], 3
    return lines, result.returncode


def open_tab(args, env, home: Path) -> tuple[list[str], int]:
    config = read_config(home)
    terminal, reason = choose_terminal(config, env)
    if terminal == "none":
        return [f"TERMINAL-NONE {reason}"], 3
    prefix = session_prefix(config)
    if prefix and not args.name.startswith(prefix):
        args.name = prefix + args.name
    check_args(args, home)
    cache = Path(env.get("COORD_PLUGIN_CACHE") or home / ".claude" / "plugins" / "cache")
    return run_utils(find_utils(cache), args, terminal)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dir", required=True)
    parser.add_argument("--kickoff", required=True)
    parser.add_argument("--from", dest="from_name", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--wait", type=int, default=ALIVE_WAIT, help="seconds to wait for the marker")
    args = parser.parse_args()
    if args.wait < 1:
        parser.error("--wait must be at least 1")
    try:
        lines, code = open_tab(args, os.environ, Path.home())
    except Failed as error:
        lines, code = [f"FAILED {error.code} {error.detail}".rstrip()], 1
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
