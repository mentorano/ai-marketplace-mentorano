#!/usr/bin/env python3
"""Project memory in a captain run (PK3, PK6): detect, then check and commit memory files.

A `captain:runner` runs it (scripts are agent work, DL2). It never writes memory text itself:
main writes `.agent-memory/<topic>.md`; this script validates the files with the
project-memory plugin's own `memory.py` and commits them by path.

  detect      --checkout=<c> [--installed-json=<f>]
              one line, exit 0: `on <memory.py>` | `off: <reason>`
  commit      --checkout=<c> --branch=<b> --memory-py=<m> --files=<a.md[,b.md...]> --message=<m>
              check the listed files (FM1-FM8) and commit them alone, by path
  restore     --checkout=<c> --files=<a.md[,b.md...]>
              put the listed files back to HEAD; a new file is removed (a `drop`, no time)

Exit codes: 0 done (detect always 0), 1 refused or check failed, nothing committed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MEMORY_DIR = ".agent-memory"
INSTALLED_JSON = os.path.join("~", ".claude", "plugins", "installed_plugins.json")
PLUGIN_KEY = "project-memory@"
NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class Refused(Exception):
    """A refusal: exit 1, nothing changed."""


def git(cwd: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=60)


def git_ok(cwd: str, *args: str) -> str:
    result = git(cwd, *args)
    if result.returncode != 0:
        raise Refused(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


# ── detect (PK6) ──────────────────────────────────────────────────────────────

def version_key(value) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", value)) if isinstance(value, str) else ()


def registered_memory_py(installed_json: str) -> str | None:
    """memory.py of the installed project-memory plugin, else None. Any unexpected shape of
    installed_plugins.json is None, never an error (RS3)."""
    try:
        with open(os.path.expanduser(installed_json), encoding="utf-8") as handle:
            data = json.load(handle)
        plugins = data.get("plugins") if isinstance(data, dict) else None
        if not isinstance(plugins, dict):
            return None
        entries = []
        for key, value in plugins.items():
            if not (isinstance(key, str) and key.startswith(PLUGIN_KEY)):
                continue
            if not isinstance(value, list) or not all(isinstance(e, dict) for e in value):
                return None
            entries.extend(value)
        if not entries:
            return None
        entry = max(entries, key=lambda e: version_key(e.get("version")))
        install = entry.get("installPath")
        if not isinstance(install, str) or not install:
            return None
        memory_py = os.path.join(os.path.expanduser(install), "scripts", "memory.py")
        return memory_py if os.path.isfile(memory_py) else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def memory_status(memory_py: str, cwd: str) -> dict:
    result = subprocess.run([sys.executable, memory_py, "status", "--json", "--cwd", cwd],
                            capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
    if result.returncode != 0:
        raise Refused(f"memory.py status failed: {result.stderr.strip()[:300]}")
    report = json.loads(result.stdout)
    if not isinstance(report, dict):
        raise Refused("memory.py status printed no JSON object")
    return report


def detect(checkout: str, installed_json: str) -> str:
    checkout = os.path.abspath(checkout)
    no_memory = f"off: no {MEMORY_DIR}/"
    try:
        if not os.path.isdir(checkout) or git(checkout, "rev-parse", "--show-toplevel").returncode:
            return no_memory
    except (OSError, subprocess.SubprocessError):
        return no_memory
    if not os.path.lexists(os.path.join(checkout, MEMORY_DIR)):
        return no_memory  # checked first: a repo without memory never reads the registry
    memory_py = registered_memory_py(installed_json)
    if memory_py is None:
        return "off: project-memory plugin not installed"
    try:
        report = memory_status(memory_py, checkout)
    except (Refused, OSError, ValueError, subprocess.SubprocessError) as error:
        return f"off: layout broken: {error}"
    layout = report.get("layout")
    if layout == "ok":
        return f"on {memory_py}"
    if layout == "absent":
        return no_memory
    return f"off: layout broken: {report.get('layout_reason')}"


# ── shared checks ─────────────────────────────────────────────────────────────

def topic_names(files: str | list[str]) -> list[str]:
    """Validated memory file names: `<name>.md`, never README.md (FM2)."""
    names = [n.strip() for n in files.split(",")] if isinstance(files, str) else list(files)
    names = [n for n in names if n]
    if not names:
        raise Refused("no memory file named")
    if len({n.lower() for n in names}) != len(names):
        raise Refused("a file is named twice")
    for name in names:
        if name.lower() == "readme.md":
            raise Refused(f"{name} is the plugin's rule file; a run never edits it")
        stem = name[:-3]
        if not name.endswith(".md") or not NAME_RE.match(stem) or stem.startswith(".") \
                or stem.endswith(".") or stem.lower().endswith(".md"):
            raise Refused(f"{name!r} is not a valid memory file name (<name>.md, [A-Za-z0-9._-])")
    return names


def require_memory_dir(checkout: str) -> None:
    """Refuse a `.agent-memory` that is a symlink or not a real directory (r1 F3): a write or
    delete through it would land outside the checkout."""
    mem = os.path.join(checkout, MEMORY_DIR)
    if os.path.islink(mem) or not os.path.isdir(mem):
        raise Refused(f"{mem} is not a real directory")


def path_status(checkout: str, path: str) -> str:
    """The two-letter `git status` code of one path, ignored files included (`!!`)."""
    result = git(checkout, "status", "--porcelain", "-z", "--ignored", "--untracked-files=all",
                 "--", path)
    if result.returncode != 0:
        raise Refused(f"git status failed: {result.stderr.strip()}")
    return result.stdout[:2] if result.stdout else ""


def head_branch(checkout: str) -> str | None:
    result = git(checkout, "symbolic-ref", "--quiet", "--short", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else None


def in_head(checkout: str, name: str) -> bool:
    return git(checkout, "cat-file", "-e", f"HEAD:{MEMORY_DIR}/{name}").returncode == 0


def changed_memory_paths(checkout: str) -> list[str]:
    result = git(checkout, "status", "--porcelain", "-z", "--untracked-files=all", "--",
                 MEMORY_DIR)
    if result.returncode != 0:
        raise Refused(f"git status failed: {result.stderr.strip()}")
    out = result.stdout  # not stripped: the first entry starts with a status column
    paths, items = [], out.split("\0")
    i = 0
    while i < len(items):
        item = items[i]
        if len(item) > 3:
            paths.append(item[3:])
            if item[0] in "RC":  # a rename lists its source next
                i += 1
                if i < len(items) and items[i]:
                    paths.append(items[i])
        i += 1
    return paths


def check_report(report: dict, names: list[str]) -> list[str]:
    """Problems that fail the check; violations of untouched files are printed only."""
    problems = []
    if report.get("layout") != "ok":
        problems.append(f"layout {report.get('layout')}: {report.get('layout_reason')}")
    listed = set(names)
    seen = set()
    for rec in report.get("files") or []:
        name, violations = rec.get("file"), rec.get("violations") or []
        if name in listed:
            seen.add(name)
            problems.extend(f"{name}: {v}" for v in violations)
        else:
            for v in violations:
                print(f"untouched {name}: {v}")
    problems.extend(f"{n}: not found by memory.py" for n in names if n not in seen
                    and report.get("layout") == "ok")
    return problems


def commit_files(checkout: str, names: list[str], message: str) -> str:
    paths = [f"{MEMORY_DIR}/{n}" for n in names]
    git_ok(checkout, "add", "--", *paths)
    git_ok(checkout, "commit", "-q", "-m", message, "--", *paths)
    return git_ok(checkout, "rev-parse", "HEAD")


def print_level(report: dict) -> None:
    level = report.get("level")
    print(f"health: {level}" + (" (suggest /project-memory:memory-defrag)"
                                if level in {"due", "overdue"} else ""))


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_commit(args) -> int:
    checkout = os.path.abspath(args.checkout)
    names = topic_names(args.files)
    require_memory_dir(checkout)
    if head_branch(checkout) != args.branch:
        raise Refused(f"HEAD of {checkout} is {head_branch(checkout) or 'detached'}, "
                      f"not {args.branch}")
    paths = [f"{MEMORY_DIR}/{n}" for n in names]
    changed = changed_memory_paths(checkout)
    stray = [p for p in changed if p not in paths]
    if stray:
        raise Refused(f"changed under {MEMORY_DIR}/ but not listed: {', '.join(stray)}")
    for name, path in zip(names, paths):
        full = Path(checkout) / path
        if not full.is_file() or full.is_symlink():
            raise Refused(f"{path} is not a regular file")
        if path not in changed:
            raise Refused(f"{path} has no change to commit")
    report = memory_status(args.memory_py, checkout)
    problems = check_report(report, names)
    if problems:
        for line in problems:
            print(f"violation {line}")
        return 1
    kinds = {n: "edit" if in_head(checkout, n) else "new" for n in names}
    sha = commit_files(checkout, names, args.message)
    for name in names:
        print(f"{kinds[name]} {MEMORY_DIR}/{name} {(Path(checkout) / MEMORY_DIR / name).stat().st_size} bytes")
    print_level(report)
    print(f"commit {sha}")
    return 0


def cmd_restore(args) -> int:
    checkout = os.path.abspath(args.checkout)
    names = topic_names(args.files)
    require_memory_dir(checkout)
    for name in names:  # check every file before changing any
        code = path_status(checkout, f"{MEMORY_DIR}/{name}")
        if not in_head(checkout, name) and code not in {"??", "A ", ""}:
            raise Refused(f"{MEMORY_DIR}/{name} is {code.strip() or 'unknown'} to git, not a new "
                          "file of this run; left as it is")  # r1 F1: never delete an ignored file
    for name in names:
        path = f"{MEMORY_DIR}/{name}"
        if in_head(checkout, name):
            git_ok(checkout, "checkout", "HEAD", "--", path)
            print(f"restored {path}")
            continue
        git_ok(checkout, "rm", "-q", "--cached", "--ignore-unmatch", "--", path)
        full = Path(checkout) / path
        if full.is_file() or full.is_symlink():
            full.unlink()
        print(f"removed {path}")
    return 0


def parse_args(argv: list[str]):
    ap = argparse.ArgumentParser(prog="memory-apply.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("detect")
    p.add_argument("--checkout", required=True)
    p.add_argument("--installed-json", default=INSTALLED_JSON)
    p = sub.add_parser("commit")
    for name in ("--checkout", "--branch", "--memory-py", "--files", "--message"):
        p.add_argument(name, required=True)
    p = sub.add_parser("restore")
    for name in ("--checkout", "--files"):
        p.add_argument(name, required=True)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.cmd == "detect":
        print(detect(args.checkout, args.installed_json))
        return 0
    try:
        return cmd_commit(args) if args.cmd == "commit" else cmd_restore(args)
    except (Refused, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"refused: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
