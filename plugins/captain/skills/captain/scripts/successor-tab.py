#!/usr/bin/env python3
"""Open the R21 successor's terminal tab (captain, reference/handoff.md § Successor terminal).

A `captain:runner` runs it; the main session never does (R1):

    python3 successor-tab.py --dir=<abs dir> --handoff=<abs handoff> --from=<old name> --name=<new name> [--wait=20]

A thin wrapper around the utils plugin's `new-session-tab.py` (skill `utils:new-session-tab`),
which opens the tab, waits for the alive marker and closes a tab that ran nothing.

1. Chooses the terminal: config `successor_terminal` `supacode` → Supacode, `cmux` → cmux; `none` or
   any other value → none; no key (or no readable config) → Supacode when this session runs in it
   (TERM_PROGRAM=supacode and SUPACODE_WORKTREE_ID set) and `supacode` is on PATH; else cmux when
   CMUX_SOCKET_PATH is set and the cmux CLI is found ($CMUX_BUNDLED_CLI_PATH if it is an executable
   file, else `cmux` on PATH); else none. hooks/handoff_common.py uses the same rule.
2. Finds the utils script: under `~/.claude/plugins/cache/*/utils/<version>/` (CAPTAIN_PLUGIN_CACHE
   overrides the cache root) the highest version that has
   `skills/new-session-tab/scripts/new-session-tab.py`; it must answer `--version` with at least
   0.3.0. Not found or too old → `FAILED NO-UTILS`, with the command that installs or updates it.
3. Writes the successor's prompt next to the handoff, `successor-prompt-<name>.md`, one line:
   `/captain resume handoff=<abs handoff> from=<old name> name=<new name>`.
4. Runs the utils script with --terminal set to the chosen one; its alive marker is `<name>.alive`
   next to the prompt.

Prints exactly one line and exits:
    TAB-OK <tab id|surface ref> <worktree id|workspace id|-> <name> mode=<mode|default> prompt=<prompt path>   exit 0
    TERMINAL-NONE <reason>                                                          exit 3
    FAILED <CODE> <detail>                                                          exit 1
    (FAILED TAB-ELSEWHERE <tab id> in=<worktree id|unknown>: the tab exists, elsewhere)
    (FAILED TAB-DEAD <tab id|surface ref> in=<worktree id|workspace id|-> after=<N>s closed=yes|no)
    (FAILED NO-UTILS <why>; owner: claude plugin install|update utils@<marketplace>)
TAB-OK means a shell ran in the tab (the marker), not that claude started: the successor's
STARTED message is the proof (handoff.md).
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
VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
MIN_UTILS = (0, 3, 0)
UTILS_SCRIPT = Path("skills") / "new-session-tab" / "scripts" / "new-session-tab.py"
ALIVE_WAIT = 20  # seconds for the tab's shell to write the marker
SLACK = 600  # seconds on top of --wait for the utils script's own terminal calls


class Failed(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code, self.detail = code, detail


def read_config(home: Path) -> dict | None:
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
    """(`supacode` | `cmux` | `none`, reason). Shared with hooks/handoff_common.py."""
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


def check_args(args) -> None:
    if not os.path.isabs(args.dir) or not os.path.isdir(args.dir):
        raise Failed("BAD-DIR", args.dir)
    handoff = args.handoff
    if not os.path.isabs(handoff) or not os.path.isfile(handoff) or any(c.isspace() for c in handoff):
        raise Failed("BAD-HANDOFF", f"{args.handoff!r} must be an absolute file path without spaces")
    for flag, value in (("--from", args.from_name), ("--name", args.name)):
        if not NAME.match(value):
            raise Failed("BAD-NAME", f"{flag} {value!r} must match {NAME.pattern}")
    if args.from_name == args.name:
        raise Failed("BAD-NAME", "--name must differ from --from")


def parse_version(text: str) -> tuple[int, int, int] | None:
    found = VERSION.match(text.strip())
    return tuple(int(part) for part in found.groups()) if found else None


def marketplace() -> str:
    """This plugin's marketplace, from its install path `cache/<marketplace>/captain/<version>/`."""
    parts = Path(__file__).resolve().parts
    if "cache" in parts and len(parts) > parts.index("cache") + 2:
        return parts[parts.index("cache") + 1]
    return "<marketplace>"


def answered_version(script: Path) -> tuple[int, int, int] | None:
    try:
        result = subprocess.run([sys.executable, str(script), "--version"],
                                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_version(result.stdout) if result.returncode == 0 else None


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
    owner = f"utils@{script.parents[5].name}"  # the marketplace utils came from, not captain's
    answered = answered_version(script)
    if answered is None or answered < MIN_UTILS:
        shown = ".".join(map(str, answered)) if answered else "no answer"
        raise Failed("NO-UTILS", f"utils {'.'.join(map(str, version))} answers --version with {shown}, "
                                 f"needs {'.'.join(map(str, MIN_UTILS))}; owner: claude plugin update {owner}")
    return script


def write_prompt(prompt: Path, text: str) -> None:
    try:
        prompt.write_text(text, encoding="utf-8")
    except OSError as error:
        raise Failed("RUN-DIR", f"{type(error).__name__}: {error.filename}")


def run_utils(script: Path, args, terminal: str, prompt: Path) -> tuple[str, int]:
    command = [sys.executable, str(script), f"--dir={args.dir}", f"--prompt-file={prompt}",
               f"--name={args.name}", f"--terminal={terminal}", f"--wait={args.wait}"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=args.wait + SLACK)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Failed("UTILS-ERROR", f"new-session-tab.py: {type(error).__name__}")
    lines = result.stdout.strip().splitlines()
    if not lines:
        detail = (result.stderr.strip().splitlines() or [""])[-1]
        raise Failed("UTILS-ERROR", f"new-session-tab.py rc={result.returncode}: {detail}")
    line = lines[-1]
    if line.startswith("TAB-NONE"):
        return "TERMINAL-NONE" + line[len("TAB-NONE"):], 3
    return line, result.returncode


def open_tab(args, env, home: Path) -> tuple[str, int]:
    terminal, reason = choose_terminal(read_config(home), env)
    if terminal == "none":
        return f"TERMINAL-NONE {reason}", 3
    check_args(args)
    cache = Path(env.get("CAPTAIN_PLUGIN_CACHE") or home / ".claude" / "plugins" / "cache")
    script = find_utils(cache)
    prompt = Path(args.handoff).parent / f"successor-prompt-{args.name}.md"
    write_prompt(prompt, f"/captain resume handoff={args.handoff} from={args.from_name} name={args.name}\n")
    return run_utils(script, args, terminal, prompt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dir", required=True)
    parser.add_argument("--handoff", required=True)
    parser.add_argument("--from", dest="from_name", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--wait", type=int, default=ALIVE_WAIT, help="seconds to wait for the marker")
    args = parser.parse_args()
    if args.wait < 1:
        parser.error("--wait must be at least 1")
    try:
        line, code = open_tab(args, os.environ, Path.home())
    except Failed as error:
        line, code = f"FAILED {error.code} {error.detail}".rstrip(), 1
    print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
