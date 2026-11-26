#!/usr/bin/env python3
"""Find what a project already uses for Gemini, without printing a secret.

Usage: project_scan.py <main checkout> [--key-name NAME ...]

Searches two file sets, never the whole tree with `grep -r` (a repo with 87 GB of media made
that run for more than five minutes):

- text files through `git grep -I --untracked`: tracked files and untracked ones that are not
  ignored, without `.claude`, `node_modules`, `.venv` and `.env*` files;
- env files: every regular file whose name starts with `.env`, found by walking the tree
  without `.git`, `node_modules`, `.venv` and `.claude`, each read by `grep -I`.

It does not see ignored files whose name does not start with `.env`, nor the text files of a git
submodule (its env files are seen). A directory the walk cannot read is listed in
`unreadable_dirs`. Prints one JSON object; every file entry names its path (absolute) and its kind:
`env` (a real env file), `env-example` (`.env.example`), `doc` (`*.md`, `*.html`, `*.txt`) or
`text`. Values are printed only for the not-secret names, through anchored patterns whose
value class holds a project id, a location or a boolean. For a key name only the files are
printed. Exit 2 on a bad argument or a failed search.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

KEY_NAMES = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SKIP_DIRS = {".git", "node_modules", ".venv", ".claude"}
DOC_SUFFIXES = (".md", ".html", ".txt")

TEXT_PATHSPEC = ["--", ".", ":(exclude,glob)**/.claude/**", ":(exclude,glob)**/node_modules/**",
                 ":(exclude,glob)**/.venv/**", ":(exclude,glob)**/.env*"]
CODE_PATHSPEC = TEXT_PATHSPEC + [":(exclude,glob)**/*.md", ":(exclude,glob)**/*.html",
                                 ":(exclude,glob)**/*.txt"]

# Never widen a value class or the gap: they are what keeps a secret out of the output.
NOT_SECRET = (r'^[[:space:]]*(export[[:space:]]+)?"?(GOOGLE_CLOUD_PROJECT|GOOGLE_CLOUD_LOCATION'
              r'|GOOGLE_GENAI_USE_VERTEXAI|GOOGLE_GENAI_USE_ENTERPRISE)"?[[:space:]]*[:=]'
              r'[[:space:]]*"?[A-Za-z0-9._-]*')
VERTEX_IN_CODE = (r'''(GOOGLE_CLOUD_PROJECT["']?[])]?[[:space:]]*(\|\||\?\?|or|,|:|=)[[:space:]]*'''
                  r'''["'][a-z][a-z0-9-]{4,28}[a-z0-9]["']|aiplatform\.googleapis\.com)''')


class ScanError(Exception):
    """A search command failed; the message names the command, never a file's content."""


def key_assigned(name: str) -> str:
    """A non-empty assignment: no comment, no empty `NAME=`, no empty quotes."""
    return r'''^[[:space:]]*(export[[:space:]]+)?''' + name + r'''=("[^"]|'[^']|[^[:space:]#"'])'''


def file_kind(path: str) -> str:
    base = os.path.basename(path)
    if base == ".env.example":
        return "env-example"
    if base.startswith(".env"):
        return "env"
    if base.endswith(DOC_SUFFIXES):
        return "doc"
    return "text"


def run(cmd: list[str]) -> str:
    """stdout of a grep; exit 1 means no match."""
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                          env={**os.environ, "LC_ALL": "C"})
    if proc.returncode not in (0, 1):  # also a signal, which is a negative code
        last = (proc.stderr.strip().splitlines() or [""])[-1]
        raise ScanError(f"{cmd[0]} failed with exit {proc.returncode}: {last}")
    return proc.stdout


def git_grep(root: str, flags: list[str], pattern: str, pathspec: list[str]) -> str:
    return run(["git", "-C", root, "grep", "-IE", "--untracked", "-z", *flags, "-e", pattern,
                *pathspec])


def text_matches(root: str, pattern: str, pathspec: list[str]) -> list[tuple[str, str]]:
    """(absolute path, matched text) pairs from `git grep -z -o`.

    The output is `path NUL match LF` per match. A path may hold a line feed, a match never
    does, so each NUL-separated part after the first is `match LF next path`.
    """
    parts = git_grep(root, ["-o"], pattern, pathspec).split("\0")
    pairs, rel = [], parts[0]
    for part in parts[1:]:
        match, _, next_rel = part.partition("\n")
        pairs.append((os.path.join(root, rel), match))
        rel = next_rel
    return pairs


def text_files(root: str, pattern: str) -> list[str]:
    out = git_grep(root, ["-l"], pattern, TEXT_PATHSPEC)
    return [os.path.join(root, rel) for rel in out.split("\0") if rel]


def is_env_file(path: str) -> bool:
    """A regular file whose name starts with `.env`; a symlink is never followed."""
    return (os.path.basename(path).startswith(".env") and os.path.isfile(path)
            and not os.path.islink(path))


def env_files(root: str, unreadable: list[str]) -> list[str]:
    """Every env file under root; a directory the walk cannot read goes to `unreadable`."""
    found = []
    for top, dirs, files in os.walk(root, onerror=lambda err: unreadable.append(err.filename)):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        found += [os.path.join(top, f) for f in sorted(files)
                  if is_env_file(os.path.join(top, f))]
    return found


def env_matches(envs: list[str], pattern: str) -> list[tuple[str, str]]:
    return [(path, match) for path in envs
            for match in run(["grep", "-IEo", "-e", pattern, path]).splitlines()]


def env_holding(envs: list[str], pattern: str) -> list[str]:
    return [path for path in envs if run(["grep", "-IEl", "-e", pattern, path])]


def entries(pairs: list[tuple[str, str]]) -> list[dict]:
    unique = sorted(set(pairs))
    return [{"file": path, "kind": file_kind(path), "match": match} for path, match in unique]


def file_entries(paths: list[str]) -> list[dict]:
    return [{"file": path, "kind": file_kind(path)} for path in sorted(set(paths))]


def scan(root: str, names: list[str]) -> dict:
    unreadable: list[str] = []
    envs = env_files(root, unreadable)
    return {
        "unreadable_dirs": sorted(unreadable),
        "not_secret": entries(text_matches(root, NOT_SECRET, TEXT_PATHSPEC)
                              + env_matches(envs, NOT_SECRET)),
        "vertex_in_code": entries(text_matches(root, VERTEX_IN_CODE, CODE_PATHSPEC)),
        "key_named": {name: file_entries(text_files(root, name) + env_holding(envs, name))
                      for name in names},
        "key_assigned": {name: file_entries(text_files(root, key_assigned(name))
                                            + env_holding(envs, key_assigned(name)))
                         for name in names},
    }


def main_checkout(path: str) -> str:
    root = os.path.abspath(path)
    proc = subprocess.run(["git", "-C", root, "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True)
    if proc.returncode != 0 or os.path.realpath(proc.stdout.strip()) != os.path.realpath(root):
        raise ScanError(f"not the top of a git checkout: {root}")
    return root


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", help="the absolute path of the main checkout")
    ap.add_argument("--key-name", action="append", default=[],
                    help="one more key variable name to look for (repeatable)")
    a = ap.parse_args(argv)
    bad = [n for n in a.key_name if not NAME_RE.fullmatch(n)]
    if bad:
        print(f"project_scan.py: not a variable name: {', '.join(bad)}", file=sys.stderr)
        return 2
    names = list(dict.fromkeys([*KEY_NAMES, *a.key_name]))
    try:
        result = scan(main_checkout(a.root), names)
    except ScanError as err:
        print(f"project_scan.py: {err}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
