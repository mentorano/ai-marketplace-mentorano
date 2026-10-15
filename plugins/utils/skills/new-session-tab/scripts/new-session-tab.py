#!/usr/bin/env python3
"""Open a new terminal tab with a new Claude Code session that starts from a prompt file.

    python3 new-session-tab.py --dir=<abs dir> --prompt-file=<abs file> --name=<session name>
        [--terminal=auto|supacode|cmux|none] [--permission-mode=<mode>] [--wait=20] [--fresh-worktree]
    python3 new-session-tab.py --version          prints the utils plugin version

1. The terminal: `--terminal=supacode` or `cmux` as given, `none` → no tab. `auto` (the default):
   Supacode when this session runs in it (TERM_PROGRAM=supacode and SUPACODE_WORKTREE_ID set) and
   `supacode` is on PATH; else cmux when CMUX_SOCKET_PATH is set and the cmux CLI is found
   ($CMUX_BUNDLED_CLI_PATH if it is an executable file, else `cmux` on PATH); else none.
2. The tab runs `cd <dir> && : > <marker> && <claude> -n <name> [--permission-mode <mode>] "$(cat <prompt>)"`,
   where <marker> is `<name>.alive` next to the prompt file; a stale one is deleted first. Every
   argument is shell-quoted, and the command is pure ASCII: Supacode's `-i` double-encodes UTF-8
   (2026-10-02 probe), so all free text stays in the prompt file. `--permission-mode` is passed
   through; without it the mode of the calling session is mirrored when it is auto, acceptEdits
   or dontAsk, so the new session neither stops on prompts nor holds messages.
3. A Supacode tab opens ALWAYS with `-w`: the listed Supacode worktree that contains --dir, the
   longest one. Without `-w` Supacode uses the focused worktree, whatever the owner looks at.
   `supacode tab list -w` then checks the tab.
4. Waits up to --wait seconds (default 20) for the marker. No marker → the tab is dead: the script
   closes that one tab (`supacode tab close -w <wt> -t <tab>`, `cmux close-surface --surface <ref>`)
   and reports TAB-DEAD. `tab list` is no proof: on 2026-10-07, with the display off, Supacode kept
   a tab whose terminal surface never came up, listed it, and the tab ran nothing. Only a tab this
   call opened is closed, and only when nothing ran in it.

The cmux path (verified live on cmux 0.64.25, 2026-10-06):
    cmux new-surface --type terminal --focus false [--workspace $CMUX_WORKSPACE_ID]
        prints `OK surface:<n> ...`; the `surface:<n>` (or UUID) token is the new tab. Without
        --workspace the tab lands in whatever workspace the owner has focused, so this session's
        own workspace (CMUX_WORKSPACE_ID) is passed whenever it is set.
    cmux send --surface <ref> <command>      types the command; no newline. On a new surface whose
        PTY is not ready yet it prints `queued (terminal starting; ...)` and types it once it is up.
    cmux send-key --surface <ref> enter      runs it
`cmux read-screen` is NOT a usable existence check: an unfocused new surface has no PTY yet and
read-screen fails. `cmux send` turns \n, \r and \t into keys, so a command with a backslash is
refused. The tab is a NEW one; driving a session's OWN tab is a different action.

Prints exactly one line and exits:
    TAB-OK <tab id|surface ref> <worktree id|workspace id|-> <name> mode=<mode|default> prompt=<prompt path>   exit 0
    TAB-NONE <reason>                                                               exit 3
    FAILED <CODE> <detail>                                                          exit 1
    (FAILED TAB-ELSEWHERE <tab id> in=<worktree id|unknown>: the tab exists, elsewhere)
    (FAILED TAB-DEAD <tab id|surface ref> in=<worktree id|workspace id|-> after=<N>s closed=yes|no)
TAB-OK means a shell ran in the tab (the marker), not that claude started or accepted the prompt.

5. `--fresh-worktree` (Supacode only; opt-in, never automatic): the worktree was just made with
   `supacode repo worktree-new`, which always opens its own bootstrap tab. The tab ids are listed
   before `tab new`; when that list held exactly one tab and the new tab is TAB-OK, that one tab is
   closed with `supacode tab close -w <wt> -t <id> --background`. It is kept when the repository has
   a setup script, since the setup script runs in that tab: a `setup` row of
   `supacode worktree script list -w <wt>`, or a non-empty `setupScript` in `<repo root>/supacode.json`
   or, without that file, in `$XDG_CONFIG_HOME|~/.config/supacode/repos.json` under the repo root path
   (that is where Supacode keeps it; `script list` shows only run/test/deploy/lint/format/custom).
   A settings file that cannot be read, or a repo root git cannot name, keeps the tab too. Never automatic: in a handover the calling
   session runs in the only tab of its own worktree. Only a tab of the first list, in `<wt>`, is closed.
   One more line goes out BEFORE the TAB-OK line, so TAB-OK stays the last line:
       BOOTSTRAP-CLOSED <tab id>
       BOOTSTRAP-KEPT setup-script | setup-script-unknown | close-failed <tab id>
       BOOTSTRAP-NONE no-tab | tabs=<N> | gone <tab id> | list-failed
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import unquote

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
TAB_ID = re.compile(r"^[0-9A-Fa-f][0-9A-Fa-f-]{7,63}$")
SURFACE_REF = re.compile(r"surface:\d+|[0-9A-Fa-f]{8}-[0-9A-Fa-f-]{27,}")
MIRRORED_MODES = {"auto", "acceptEdits", "dontAsk"}
PERMISSION_MODES = {"acceptEdits", "auto", "bypassPermissions", "default", "dontAsk", "plan"}
TERMINALS = ("auto", "supacode", "cmux", "none")
TIMEOUT = 60
ALIVE_WAIT = 20  # seconds for the tab's shell to write the marker
PLUGIN_JSON = Path(__file__).parent.parent.parent.parent / ".claude-plugin" / "plugin.json"


class Failed(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code, self.detail = code, detail


def plugin_version() -> str | None:
    """The version in this plugin's manifest; the installed copy sits in a directory of that name."""
    try:
        with open(PLUGIN_JSON, encoding="utf-8") as fh:
            version = json.load(fh).get("version")
    except (OSError, ValueError, AttributeError):
        return None
    return version if isinstance(version, str) else None


def cmux_cli(env, which=shutil.which) -> str | None:
    """The cmux CLI: $CMUX_BUNDLED_CLI_PATH when it is an executable file, else `cmux` on PATH."""
    bundled = env.get("CMUX_BUNDLED_CLI_PATH")
    if bundled and os.path.isfile(bundled) and os.access(bundled, os.X_OK):
        return bundled
    return which("cmux")



def choose_terminal(asked: str, env, which=shutil.which) -> tuple[str, str]:
    """(`supacode` | `cmux` | `none`, reason) for `--terminal`."""
    if asked in ("supacode", "cmux"):
        return asked, "asked"
    if asked == "none":
        return "none", "--terminal=none"
    if env.get("TERM_PROGRAM") == "supacode" and env.get("SUPACODE_WORKTREE_ID") and which("supacode"):
        return "supacode", "detected: this session runs in Supacode"
    if env.get("CMUX_SOCKET_PATH") and cmux_cli(env, which):
        return "cmux", "detected: this session runs in cmux"
    return "none", "not running in Supacode or cmux"


def worktree_id(directory: str, listed: list[str]) -> str | None:
    """The listed Supacode worktree id (URL-encoded path with a trailing slash) whose path is
    `directory` or contains it; the longest wins, so a nested worktree beats its parent."""
    target = directory.rstrip("/") + "/"
    best = None
    for row in listed:
        path = unquote(row)
        if path.endswith("/") and target.startswith(path) and (best is None or len(path) > len(unquote(best))):
            best = row
    return best


def permission_mode(env, projects: Path) -> str | None:
    """This session's last recorded permission mode, when it is one worth mirroring."""
    session = env.get("CLAUDE_CODE_SESSION_ID", "")
    if not SESSION_ID.match(session):
        return None
    mode = None
    for path in projects.glob(f"*/{session}.jsonl"):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"permission-mode"' not in line:
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if record.get("type") == "permission-mode":
                        mode = record.get("permissionMode")
        except OSError:
            continue
    return mode if mode in MIRRORED_MODES else None


def tab_input(directory: str, claude: str, name: str, prompt: str, mode: str | None, marker: str) -> str:
    words = ["cd", shlex.quote(directory), "&&", ":", ">", shlex.quote(marker), "&&",
             shlex.quote(claude), "-n", shlex.quote(name)]
    if mode:
        words += ["--permission-mode", shlex.quote(mode)]
    command = " ".join(words) + ' "$(cat ' + shlex.quote(prompt) + ')"'
    if not all(32 <= ord(ch) < 127 for ch in command):
        raise Failed("NON-ASCII", "the tab command must be ASCII; move the text into the prompt file")
    return command


def supacode(*args: str) -> str:
    try:
        result = subprocess.run(["supacode", *args], capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Failed("SUPACODE-ERROR", f"supacode {args[0]} {args[1]}: {type(error).__name__}")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or [""]
        raise Failed("SUPACODE-ERROR", f"supacode {args[0]} {args[1]} rc={result.returncode}: {detail[0]}")
    return result.stdout


def has_tab(wt: str, tab: str) -> bool:
    try:
        rows = supacode("tab", "list", "-w", wt).splitlines()
    except Failed:
        return False
    return tab.upper() in {row.strip().upper() for row in rows}


def close_supacode_tab(wt: str, tab: str) -> bool:
    """Closes the dead tab this script opened; True only when `tab list` answers without it."""
    try:
        supacode("tab", "close", "-w", wt, "-t", tab)
        rows = supacode("tab", "list", "-w", wt).splitlines()
    except Failed:
        return False
    return tab.upper() not in {row.strip().upper() for row in rows}


def tab_ids(wt: str) -> list[str] | None:
    """The upper-cased tab ids of worktree `wt`; None when `tab list` fails."""
    try:
        rows = supacode("tab", "list", "-w", wt).splitlines()
    except Failed:
        return None
    return [row.strip().upper() for row in rows if TAB_ID.match(row.strip())]


def repo_roots(directory: str, wt: str) -> list[str] | None:
    """Candidate repository roots, each with a trailing slash: the main checkout (git common dir)
    and the Supacode worktree path itself; None when git cannot name the main checkout."""
    try:
        result = subprocess.run(["git", "-C", directory, "rev-parse", "--path-format=absolute",
                                 "--git-common-dir"], capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    common = result.stdout.strip()
    if result.returncode != 0 or not common.endswith("/.git"):
        return None
    roots = [common[: -len(".git")], unquote(wt)]
    real = [os.path.realpath(root).rstrip("/") + "/" for root in roots]  # /var vs /private/var
    return list(dict.fromkeys(roots + real))


def setup_script_state(directory: str, wt: str, env, home: Path) -> str | None:
    """`setup-script`, `setup-script-unknown`, or None when no source shows a setup script."""
    try:
        rows = supacode("worktree", "script", "list", "-w", wt).splitlines()
    except Failed:
        return "setup-script-unknown"
    for row in rows:
        fields = [field.strip().lower() for field in row.split("\t")]
        if "setup" in fields[1:]:
            return "setup-script"
    xdg = (env.get("XDG_CONFIG_HOME") or "").strip()
    config = Path(xdg) if xdg.startswith("/") else home / ".config"
    try:
        repos = json.loads((config / "supacode" / "repos.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        repos = {}
    except (OSError, ValueError):
        return "setup-script-unknown"
    if not isinstance(repos, dict):
        return "setup-script-unknown"
    roots = repo_roots(directory, wt)
    if roots is None:  # the main checkout's settings would go unread
        return "setup-script-unknown"
    for root in roots:
        try:
            settings = json.loads((Path(root) / "supacode.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            settings = repos.get(root)
        except (OSError, ValueError):
            return "setup-script-unknown"
        if settings is None:
            continue
        if not isinstance(settings, dict) or not isinstance(settings.get("setupScript", ""), str):
            return "setup-script-unknown"
        if settings.get("setupScript", "").strip():
            return "setup-script"
    return None


def close_bootstrap(directory: str, wt: str, before: list[str] | None, tab: str, env, home: Path) -> str:
    """Closes the bootstrap tab of a fresh worktree: the only tab listed before `tab new`."""
    if before is None:
        return "BOOTSTRAP-NONE list-failed"
    if not before:
        return "BOOTSTRAP-NONE no-tab"
    if len(before) != 1:
        return f"BOOTSTRAP-NONE tabs={len(before)}"
    bootstrap = before[0]
    if bootstrap == tab.upper():  # never the tab this call opened
        return "BOOTSTRAP-NONE no-tab"
    state = setup_script_state(directory, wt, env, home)
    if state:
        return f"BOOTSTRAP-KEPT {state}"
    now = tab_ids(wt)
    if now is None:
        return "BOOTSTRAP-NONE list-failed"
    if bootstrap not in now:
        return f"BOOTSTRAP-NONE gone {bootstrap}"
    try:
        supacode("tab", "close", "-w", wt, "-t", bootstrap, "--background")
    except Failed:
        return f"BOOTSTRAP-KEPT close-failed {bootstrap}"
    after = tab_ids(wt)
    if after is None or bootstrap in after:
        return f"BOOTSTRAP-KEPT close-failed {bootstrap}"
    return f"BOOTSTRAP-CLOSED {bootstrap}"


def wait_for(marker: Path, seconds: int) -> bool:
    deadline = time.monotonic() + seconds
    while not marker.exists():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)
    return True

def cmux(cli: str, *args: str) -> str:
    try:
        result = subprocess.run([cli, *args], capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Failed("CMUX-ERROR", f"cmux {args[0]}: {type(error).__name__}")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or [""]
        raise Failed("CMUX-ERROR", f"cmux {args[0]} rc={result.returncode}: {detail[0]}")
    return result.stdout


def open_cmux_tab(cli: str, command: str, env) -> tuple[str, str]:
    """A new, unfocused terminal surface that runs `command`: (surface ref, workspace id or "-")."""
    workspace = env.get("CMUX_WORKSPACE_ID") or ""
    scope = ["--workspace", workspace] if workspace else []
    out = cmux(cli, "new-surface", "--type", "terminal", "--focus", "false", *scope)
    found = SURFACE_REF.search(out)
    if not found:
        raise Failed("TAB-NEW-FAILED", repr(out.strip()[:80]))
    surface = found.group(0)
    try:  # `send` targets this ref only (not_found otherwise) and waits for the new surface's PTY
        cmux(cli, "send", "--surface", surface, command)
        cmux(cli, "send-key", "--surface", surface, "enter")
    except Failed as error:
        raise Failed(error.code, f"surface={surface} {error.detail}")
    return surface, workspace or "-"


def close_cmux_surface(cli: str, surface: str) -> bool:
    try:
        cmux(cli, "close-surface", "--surface", surface)
    except Failed:
        return False
    return True


def terminal_cli(terminal: str, env) -> str | None:
    """The cmux CLI for `cmux`; None for Supacode, once `supacode` is known to be on PATH."""
    if terminal == "cmux":
        cli = cmux_cli(env)
        if not cli:
            raise Failed("NO-CMUX", "no executable at $CMUX_BUNDLED_CLI_PATH and cmux is not on PATH")
        return cli
    if not shutil.which("supacode"):
        raise Failed("NO-SUPACODE", "supacode is not on PATH")
    return None


def supacode_target(directory: str) -> tuple[str, list[str]]:
    """(the Supacode worktree that contains `directory`, every listed worktree)."""
    listed = supacode("worktree", "list").split()
    wt = worktree_id(directory, listed)
    if wt is None:
        raise Failed("NOT-IN-A-SUPACODE-WORKTREE", directory)
    return wt, listed


def open_supacode_tab(wt: str, listed: list[str], command: str) -> str:
    """A new tab in worktree `wt` that runs `command`; its id."""
    tab = supacode("tab", "new", "-w", wt, "-i", command).strip()
    if not TAB_ID.match(tab):
        raise Failed("TAB-NEW-FAILED", repr(tab[:80]))
    if not has_tab(wt, tab):
        found = next((row for row in listed if row != wt and has_tab(row, tab)), "unknown")
        raise Failed("TAB-ELSEWHERE", f"{tab} in={found}")
    return tab



def check_args(args) -> None:
    if not os.path.isabs(args.dir) or not os.path.isdir(args.dir):
        raise Failed("BAD-DIR", args.dir)
    if not os.path.isabs(args.prompt_file) or not os.path.isfile(args.prompt_file):
        raise Failed("BAD-PROMPT-FILE", f"{args.prompt_file!r} must be an existing absolute file path")
    if not NAME.match(args.name):
        raise Failed("BAD-NAME", f"--name {args.name!r} must match {NAME.pattern}")
    prompt = Path(args.prompt_file)
    if (prompt.parent / f"{args.name}.alive").resolve() == prompt.resolve():
        raise Failed("BAD-PROMPT-FILE", f"{args.prompt_file!r} is the alive marker of --name {args.name}")
    if args.permission_mode is not None and args.permission_mode not in PERMISSION_MODES:
        raise Failed("BAD-MODE", f"--permission-mode {args.permission_mode!r}: one of {sorted(PERMISSION_MODES)}")


def clear_marker(marker: Path) -> None:
    """Removes a marker left by an earlier attempt: it would read as alive."""
    try:
        marker.unlink(missing_ok=True)
    except OSError as error:
        raise Failed("MARKER", f"{type(error).__name__}: {error.filename}")


def open_tab(args, env, home: Path) -> str:
    terminal, reason = choose_terminal(args.terminal, env)
    if terminal == "none":
        return f"TAB-NONE {reason}"
    check_args(args)
    claude = shutil.which("claude")
    if not claude or not os.path.isabs(claude):
        raise Failed("NO-CLAUDE-PATH", str(claude))
    cli = terminal_cli(terminal, env)
    if cli and args.fresh_worktree:
        raise Failed("BAD-FRESH-WORKTREE", "--fresh-worktree needs Supacode")
    wt, listed = (None, []) if cli else supacode_target(args.dir)
    prompt = Path(args.prompt_file)
    marker = prompt.parent / f"{args.name}.alive"
    mode = args.permission_mode or permission_mode(env, home / ".claude" / "projects")
    command = tab_input(args.dir, claude, args.name, str(prompt), mode, str(marker))
    if cli and "\\" in command:  # `cmux send` turns \n, \r and \t into keys
        raise Failed("BAD-PATH", "a backslash in the tab command would be sent as a key")
    clear_marker(marker)
    before = tab_ids(wt) if args.fresh_worktree else None
    if cli:
        tab, where = open_cmux_tab(cli, command, env)
    else:
        tab, where = open_supacode_tab(wt, listed, command), wt
    if not wait_for(marker, args.wait):
        closed = close_cmux_surface(cli, tab) if cli else close_supacode_tab(where, tab)
        raise Failed("TAB-DEAD", f"{tab} in={where} after={args.wait}s closed={'yes' if closed else 'no'}")
    line = f"TAB-OK {tab} {where} {args.name} mode={mode or 'default'} prompt={prompt}"
    if args.fresh_worktree:
        line = close_bootstrap(args.dir, wt, before, tab, env, home) + "\n" + line
    return line


def parse_args(argv: list[str] | None = None):
    if argv is None:
        argv = sys.argv[1:]
    if "--version" in argv:
        return None
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dir", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--terminal", choices=TERMINALS, default="auto")
    parser.add_argument("--permission-mode", default=None)
    parser.add_argument("--wait", type=int, default=ALIVE_WAIT, help="seconds to wait for the marker")
    parser.add_argument("--fresh-worktree", action="store_true",
                        help="Supacode, only right after `supacode repo worktree-new`: close that worktree's "
                             "bootstrap tab after TAB-OK (in a handover it would close the caller)")
    args = parser.parse_args(argv)
    if args.wait < 1:
        parser.error("--wait must be at least 1")
    return args


def main() -> int:
    args = parse_args()
    if args is None:
        version = plugin_version()
        print(version or "unknown")
        return 0 if version else 1
    try:
        line = open_tab(args, os.environ, Path.home())
    except Failed as error:
        print(f"FAILED {error.code} {error.detail}".rstrip())
        return 1
    print(line)
    return 3 if line.startswith("TAB-NONE") else 0


if __name__ == "__main__":
    sys.exit(main())
