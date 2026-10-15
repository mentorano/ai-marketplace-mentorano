#!/usr/bin/env python3
# Health check and defragment brief ported from worca-cc (MIT, (c) 2026 Sinisha Djukic).
"""Committed project memory: layout, health and prune for `.agent-memory/`.

Commands (all take `--cwd <dir>`, default the current directory; the repo root is
`git rev-parse --show-toplevel` from there, and memory is looked up only at that root):

  init                 create `.agent-memory/`, its README.md rule and the relative symlink
                       `.claude/rules/project-memory -> ../../.agent-memory`; idempotent; never commits
  status [--json]      layout state, per-file format violations and the health level
  brief                the `## Memory health` section for the defragmenter
  prune --before <B>   delete files that had content in the before listing and are empty now;
                       <B> is a path to a file holding `status --json` output, or that JSON inline
                       (an argument starting with `{`)

`status --json` shape (stable; consumed by the skills and session_start.py):

  {
    "cwd": "<abs --cwd>",
    "repo_root": "<abs>" | null,
    "memory_dir": "<abs>/.agent-memory" | null,
    "layout": "ok" | "absent" | "broken",
    "layout_reason": "<text>" | null,
    "level": "fresh" | "ok" | "due" | "overdue" | null,    # null only when layout is absent
    "reasons": ["<text>", ...],
    "totals": {"files": n, "bytes": n, "always_on_files": n, "always_on_bytes": n,
               "violations": n},
    "files": [{"file": "x.md", "name": "x" | null, "kind": "file" | "dir" | "symlink" | "other",
               "bytes": n, "paths": [...], "has_frontmatter": bool, "has_content": bool,
               "violations": ["ФМ4: ...", ...]}, ...]
  }

Choices the design leaves open:
  - `files` lists every regular `*.md` file except README.md, plus every subdirectory, symlink,
    non-regular entry or regular non-`.md` file (kind `other`), each an ФМ7 violation; a
    README.md that is not a regular file is listed the same way. Dotfiles that do not end in
    `.md` (`.DS_Store`, `.gitkeep`) are ignored.
  - `prune` refuses a before listing whose `memory_dir` is not the current memory directory.
  - Totals count only regular `*.md` files. A format violation makes the level `due` even when
    no topic file exists, so a directory holding only a subdirectory is `due`, not `fresh`.
  - A file that cannot be read or decoded counts as a file without `paths` (always-on).
  - `has_content` is "not empty and not whitespace-only"; prune works from it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

MEMORY_DIR = ".agent-memory"
README = "README.md"
LINK_REL = os.path.join(".claude", "rules", "project-memory")
LINK_TARGET = "../../.agent-memory"

DUE_FILES = 30
SOFT_BYTES = 8192
HARD_BYTES = 32768
ALWAYS_ON_DUE = 16384
ALWAYS_ON_OVERDUE = 32768
DESCRIPTION_MAX = 160

NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)\s*:(.*)$")
ITEM_RE = re.compile(r"^\s*-(?:\s+(.*))?$")

README_TEXT = """\
# Project memory

Other `*.md` files here are durable repo rules; Claude Code loads them (a file with `paths` when you touch a matching file).

**Only the main session writes here.** A subagent never writes (except the defragment subagent of `/project-memory:memory-defrag`); it ends its report with `Memory candidate: <one line>` items. Edit only under `.agent-memory/`; `.claude/rules/project-memory/` is a protected view, never write there.

**Write trigger.** Write a file only when what you learned (a) cost you a cycle, or would have cost the next session one, or (b) contradicted what you assumed, AND will still be true next month. Worth a file: a trap; a verification recipe (exact command, env var, fixture step); an invariant the code depends on but never states; a settled user decision with its reason and the ruled-out approaches; a defect class reviews keep flagging. Never: session summaries or progress notes, restatements of code, one-off task facts, anything in CLAUDE.md / CONTRIBUTING / README, machine paths, secrets, facts about the user (auto memory), unverified guesses.

**Format.** Prefer editing an existing file. One topic per `<topic>.md`, frontmatter `name` (= filename stem), `description` (one line, max 160 chars, *when* to read it), `paths` (YAML list of globs) when file-specific. Under ~8 KB. To remove a file, delete it. Tell the user in one line what you wrote and why. Memory never overrides the user or CLAUDE.md.
"""


# ── repo and layout ───────────────────────────────────────────────────────────

def git(cwd: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=4)


def repo_root(cwd: str) -> str | None:
    try:
        p = git(cwd, "rev-parse", "--show-toplevel")
    except (OSError, subprocess.SubprocessError):
        return None
    out = p.stdout.strip()
    return out if p.returncode == 0 and out else None


def same_path(a: str, b: str) -> bool:
    return os.path.realpath(a) == os.path.realpath(b)


def layout_state(cwd: str, root: str | None) -> tuple[str, str | None]:
    if root is None:
        return "absent", "not a git repository"
    mem = os.path.join(root, MEMORY_DIR)
    if not os.path.lexists(mem):
        return "absent", f"no {MEMORY_DIR}/ at the repo root"
    if os.path.islink(mem) or not os.path.isdir(mem):
        return "broken", f"{MEMORY_DIR} at the repo root is not a real directory"
    link = os.path.join(root, LINK_REL)
    if not os.path.lexists(link):
        return "broken", f"the link {LINK_REL} is missing"
    if not os.path.islink(link):
        return "broken", f"{LINK_REL} is not a symlink"
    target = os.readlink(link)
    if not os.path.exists(link):
        return "broken", f"the link {LINK_REL} is dangling (points to {target})"
    if target != LINK_TARGET or not same_path(link, mem):
        return "broken", f"the link {LINK_REL} points to {target}, not {LINK_TARGET}"
    if not same_path(cwd, root):
        return "broken", ("the session started in a subdirectory, not at the repo root, "
                          "so path-scoped memory rules do not load")
    return "ok", None


# ── frontmatter ───────────────────────────────────────────────────────────────

def unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1]
    return s


ESCAPES = {'"': '"', "\\": "\\", "/": "/", "n": "\n", "t": "\t"}


def scalar(raw: str, problems: list[str], n: int) -> str:
    """A plain or quoted YAML scalar: quotes removed, an inline ` # comment` dropped."""
    s = raw.strip()
    if s[:1] in ("'", '"'):
        quote, out, i = s[0], [], 1
        while i < len(s):
            c = s[i]
            if quote == "'" and c == "'":
                if s[i + 1:i + 2] != "'":
                    break
                out.append("'")  # '' is an escaped single quote
                i += 2
                continue
            if quote == '"' and c == "\\" and i + 1 < len(s):
                out.append(ESCAPES.get(s[i + 1], "\\" + s[i + 1]))
                i += 2
                continue
            if quote == '"' and c == '"':
                break
            out.append(c)
            i += 1
        else:
            problems.append(f"frontmatter line {n}: unterminated quote")
            return "".join(out)
        rest = s[i + 1:].strip()
        if rest and not rest.startswith("#"):
            problems.append(f"frontmatter line {n}: text after the closing quote")
        return "".join(out)
    s = "" if s.startswith("#") else re.split(r"\s+#", s, maxsplit=1)[0].rstrip()
    if s.startswith("[") and not s.endswith("]"):
        problems.append(f"frontmatter line {n}: unclosed `[` list")
    return s


def split_paths(value: str) -> list[str]:
    v = value.strip()
    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]
    return [unquote(p) for p in v.split(",") if unquote(p)]


def parse_frontmatter(text: str) -> tuple[dict | None, str, list[str]]:
    """Return (fields or None, body, problems). A field is a str, or a list for a YAML list.

    Supports the subset memory files use: `key: scalar`, `key:` followed by `  - item` lines,
    and indented continuation lines (kept, joined, and flagged by the caller as multi-line).
    """
    t = text.lstrip("﻿").replace("\r\n", "\n")
    lines = t.split("\n")
    if not lines or lines[0].rstrip() != "---":
        return None, t, []
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip() in ("---", "...")), None)
    if end is None:
        return None, t, ["frontmatter has no closing `---`"]
    fields: dict = {}
    multiline: set[str] = set()
    problems: list[str] = []
    key = None
    for n, line in enumerate(lines[1:end], start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = ITEM_RE.match(line)
        if item and key is not None and key not in multiline and (
                fields.get(key) == "" or isinstance(fields.get(key), list)):
            if not isinstance(fields[key], list):
                fields[key] = []
            fields[key].append(scalar(item.group(1) or "", problems, n))
            continue
        if line[:1] in (" ", "\t") and key is not None:
            prev = fields.get(key)
            fields[key] = f"{prev} {line.strip()}".strip() if isinstance(prev, str) else line.strip()
            multiline.add(key)
            continue
        m = KEY_RE.match(line)
        if not m:
            problems.append(f"frontmatter line {n} is not `key: value`")
            key = None
            continue
        key, value = m.group(1), m.group(2).strip()
        if value in ("|", ">", "|-", ">-"):
            fields[key] = ""
            multiline.add(key)
        else:
            fields[key] = scalar(value, problems, n)
    fields["__multiline__"] = multiline
    return fields, "\n".join(lines[end + 1:]), problems


def paths_of(fields: dict | None) -> list[str]:
    if not fields or "paths" not in fields:
        return []
    v = fields["paths"]
    if isinstance(v, list):
        return [p for p in v if p]
    return split_paths(v)


# ── listing and format rules ──────────────────────────────────────────────────

def valid_name(name: str) -> bool:
    return (bool(NAME_RE.match(name)) and not name.startswith(".") and not name.endswith(".")
            and not name.lower().endswith(".md"))


def inspect_file(path: Path) -> dict:
    stem = path.name[:-3]
    rec = {"file": path.name, "name": None, "kind": "file", "bytes": 0, "paths": [],
           "has_frontmatter": False, "has_content": False, "violations": []}
    v = rec["violations"]
    if not valid_name(stem):
        v.append("ФМ2: the file name may use only letters, digits, '.', '_' and '-', "
                 "with no leading or trailing dot and no extra .md")
    try:
        raw = path.read_bytes()
    except OSError as err:
        v.append(f"read error: {err.strerror or err}")
        try:
            rec["bytes"] = path.stat().st_size
        except OSError:
            pass
        return rec
    rec["bytes"] = len(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as err:
        v.append(f"read error: not UTF-8 text ({err.reason} at byte {err.start})")
        rec["has_content"] = bool(raw.strip())
        return rec
    rec["has_content"] = bool(text.strip())
    if not rec["has_content"]:
        v.append("ФМ8: the file is empty")
        return rec
    try:
        fields, body, problems = parse_frontmatter(text)
    except Exception as err:  # noqa: BLE001 - one bad file must never stop the listing
        v.append(f"parse error: {err}")
        return rec
    v.extend(problems)
    if fields is None:
        v.append("ФМ1: no frontmatter (`name`, `description`)")
        return rec
    rec["has_frontmatter"] = True
    multiline = fields.pop("__multiline__", set())
    name = fields.get("name")
    rec["name"] = name if isinstance(name, str) and name else None
    if rec["name"] != stem:
        v.append(f"ФМ1: `name` is {rec['name']!r}, not the file name stem {stem!r}" if rec["name"]
                 else f"ФМ1: `name` is missing (expected {stem!r})")
    if rec["name"] and rec["name"] != stem and not valid_name(rec["name"]):
        v.append("ФМ2: `name` may use only letters, digits, '.', '_' and '-', "
                 "with no leading or trailing dot and no .md")
    desc = fields.get("description")
    if not isinstance(desc, str) or not desc.strip():
        v.append("ФМ4: `description` is missing")
    elif "description" in multiline or "\n" in desc:
        v.append("ФМ4: `description` must be one line")
    elif len(desc) > DESCRIPTION_MAX:
        v.append(f"ФМ4: `description` is {len(desc)} characters (max {DESCRIPTION_MAX})")
    if "paths" in fields:
        rec["paths"] = paths_of(fields)
        if not rec["paths"]:
            v.append("ФМ5: `paths` is present but lists no glob")
    for k in ("source", "updated"):
        if k in fields:
            v.append(f"ФМ6: drop the `{k}` key (git keeps author and date)")
    if not body.strip():
        v.append("ФМ8: the file holds frontmatter only")
    return rec


def list_memory(mem: Path) -> list[dict]:
    out: list[dict] = []
    try:
        entries = sorted(os.scandir(mem), key=lambda e: e.name)
    except OSError as err:
        return [{"file": ".", "name": None, "kind": "other", "bytes": 0, "paths": [],
                 "has_frontmatter": False, "has_content": False,
                 "violations": [f"read error: {err.strerror or err}"]}]
    for e in entries:
        try:
            if e.is_symlink():
                kind = "symlink"
            elif e.is_dir(follow_symlinks=False):
                kind = "dir"
            elif e.is_file(follow_symlinks=False):
                kind = "file"
            else:
                kind = "other"
        except OSError:
            kind = "other"
        if kind == "file" and e.name == README:
            continue
        if kind == "file" and e.name.endswith(".md"):
            out.append(inspect_file(Path(e.path)))
            continue
        if kind == "file" and e.name.startswith("."):
            continue  # .DS_Store, .gitkeep: Claude Code never loads them
        if kind == "file":
            kind = "other"
            what = "not a *.md file, so it never loads"
        else:
            what = {"symlink": "a symlink", "dir": "a subdirectory"}.get(kind, "not a regular file")
        out.append({"file": e.name, "name": None, "kind": kind, "bytes": 0, "paths": [],
                    "has_frontmatter": False, "has_content": False,
                    "violations": [f"ФМ7: {what}; only regular *.md files may sit directly "
                                   f"in {MEMORY_DIR}/"]})
    mark_case_twins(out)
    return out


def mark_case_twins(recs: list[dict]) -> None:
    """ФМ3: names that differ only by letter case collide on macOS and Windows checkouts.

    README.md is a reserved name here even though it is not listed.
    """
    for rec in recs:
        if rec["file"] != README and rec["file"].lower() == README.lower():
            rec["violations"].append(f"ФМ3: differs only by letter case from {README}")
    by_lower: dict[str, list[dict]] = {}
    for rec in recs:
        if rec["kind"] == "file":
            by_lower.setdefault(rec["file"].lower(), []).append(rec)
    for group in by_lower.values():
        if len(group) > 1:
            for rec in group:
                others = ", ".join(r["file"] for r in group if r is not rec)
                rec["violations"].append(f"ФМ3: differs only by letter case from {others}")


# ── health (port of the upstream memoryHealth, file state only) ──────────────

def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def names(recs: list[dict]) -> str:
    return ", ".join(r["file"] for r in recs[:3]) + (", …" if len(recs) > 3 else "")


def health(files: list[dict]) -> dict:
    topics = [r for r in files if r["kind"] == "file"]
    oversized = [r for r in topics if r["bytes"] > SOFT_BYTES]
    over_hard = [r for r in topics if r["bytes"] > HARD_BYTES]
    flagged = [r for r in files if r["violations"]]
    always_on = [r for r in topics if not r["paths"]]
    always_on_bytes = sum(r["bytes"] for r in always_on)
    n = len(topics)
    reasons = []
    if n >= DUE_FILES:
        reasons.append(f"{plural(n, 'file')} in project memory (due at {DUE_FILES})")
    if oversized:
        reasons.append(f"{plural(len(oversized), 'file')} over the {SOFT_BYTES}-byte soft cap: "
                       f"{names(oversized)}")
    if over_hard:
        reasons.append(f"{plural(len(over_hard), 'file')} over the {HARD_BYTES}-byte hard cap: "
                       f"{names(over_hard)}")
    if flagged:
        reasons.append(f"{plural(len(flagged), 'file')} with format violations: {names(flagged)}")
    if always_on_bytes >= ALWAYS_ON_DUE:
        reasons.append(f"{always_on_bytes} bytes of memory load into the context of every session "
                       f"({plural(len(always_on), 'file')} without paths; due at {ALWAYS_ON_DUE})")
    if not files:
        level = "fresh"
    elif over_hard or always_on_bytes >= ALWAYS_ON_OVERDUE:
        level = "overdue"
    elif reasons:
        level = "due"
    else:
        level = "ok"
    return {"level": level, "reasons": reasons,
            "totals": {"files": n, "bytes": sum(r["bytes"] for r in topics),
                       "always_on_files": len(always_on), "always_on_bytes": always_on_bytes,
                       "violations": sum(len(r["violations"]) for r in files)}}


def status(cwd: str) -> dict:
    cwd = os.path.abspath(cwd)
    root = repo_root(cwd) if os.path.isdir(cwd) else None
    layout, reason = layout_state(cwd, root)
    mem = os.path.join(root, MEMORY_DIR) if root else None
    report = {"cwd": cwd, "repo_root": root, "memory_dir": mem, "layout": layout,
              "layout_reason": reason, "level": None, "reasons": [],
              "totals": {"files": 0, "bytes": 0, "always_on_files": 0, "always_on_bytes": 0,
                         "violations": 0},
              "files": []}
    if layout == "absent" or not mem or not os.path.isdir(mem) or os.path.islink(mem):
        return report
    files = list_memory(Path(mem))
    report.update(health(files))
    report["files"] = files
    return report


def render_status(rep: dict) -> str:
    lines = [f"layout: {rep['layout']}" + (f" ({rep['layout_reason']})" if rep["layout_reason"] else "")]
    if rep["level"] is None:
        return "\n".join(lines) + "\n"
    t = rep["totals"]
    lines.append(f"level: {rep['level']}")
    lines.append(f"files: {t['files']}, {t['bytes']} bytes; always-on: {t['always_on_files']} "
                 f"files, {t['always_on_bytes']} bytes; violations: {t['violations']}")
    for r in rep["reasons"]:
        lines.append(f"- {r}")
    for f in rep["files"]:
        for v in f["violations"]:
            lines.append(f"  {f['file']}: {v}")
    return "\n".join(lines) + "\n"


def render_brief(rep: dict) -> str:
    """Port of the upstream renderDefragBrief, without the write-counter sentence."""
    t = rep["totals"]
    level = rep["level"] or "fresh"
    lines = ["## Memory health", ""]
    if rep["reasons"]:
        lines.append(f"Level: {level}. Project memory is flagged for the reasons below; the "
                     "defragment is finished only when none of them still holds:")
        lines.append("")
        lines.extend(f"- {r}" for r in rep["reasons"])
    else:
        lines.append(f"Level: {level}. No threshold is crossed; keep it that way.")
    lines.append("")
    lines.append(
        f"Budgets: always-on memory (files WITHOUT `paths`, loaded into every session's context) "
        f"under {ALWAYS_ON_DUE} bytes, now {t['always_on_bytes']} in "
        f"{plural(t['always_on_files'], 'file')}; fewer than {DUE_FILES} files, now {t['files']}; "
        f"each file under {SOFT_BYTES} bytes (hard cap {HARD_BYTES}); no format violations, "
        f"now {t['violations']}.")
    return "\n".join(lines) + "\n"


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_init(cwd: str) -> int:
    root = repo_root(cwd) if os.path.isdir(cwd) else None
    if root is None:
        print(f"init: {cwd} is not inside a git repository", file=sys.stderr)
        return 1
    mem = os.path.join(root, MEMORY_DIR)
    link = os.path.join(root, LINK_REL)
    if os.path.lexists(link) and not (os.path.islink(link) and os.readlink(link) == LINK_TARGET):
        kind = "symlink" if os.path.islink(link) else "directory" if os.path.isdir(link) else "file"
        print(f"init: refusing to replace the foreign {kind} at {LINK_REL}; move it away and "
              "rerun", file=sys.stderr)
        return 1
    if os.path.lexists(mem) and (os.path.islink(mem) or not os.path.isdir(mem)):
        print(f"init: {MEMORY_DIR} exists and is not a real directory; move it away and rerun",
              file=sys.stderr)
        return 1
    done = []
    if os.path.isdir(mem):
        done.append(f"kept {MEMORY_DIR}/")
    else:
        os.mkdir(mem)
        done.append(f"created {MEMORY_DIR}/")
    readme = os.path.join(mem, README)
    if os.path.lexists(readme) and (os.path.islink(readme) or not os.path.isfile(readme)):
        print(f"init: {MEMORY_DIR}/{README} is not a regular file; move it away and rerun",
              file=sys.stderr)
        return 1
    if os.path.lexists(readme):
        done.append(f"kept {MEMORY_DIR}/{README}")
    else:
        with open(readme, "w", encoding="utf-8") as fh:
            fh.write(README_TEXT)
        done.append(f"created {MEMORY_DIR}/{README}")
    if os.path.islink(link):
        done.append(f"kept {LINK_REL} -> {LINK_TARGET}")
    else:
        try:
            os.makedirs(os.path.dirname(link), exist_ok=True)
            os.symlink(LINK_TARGET, link)
        except OSError as err:
            print(f"init: cannot create {LINK_REL}: {err.strerror or err}", file=sys.stderr)
            return 1
        done.append(f"created {LINK_REL} -> {LINK_TARGET}")
    for line in done:
        print(line)
    for path, negation in ((os.path.join(MEMORY_DIR, README), f"!{MEMORY_DIR}/"),
                           (LINK_REL, f"!{LINK_REL}")):
        try:
            ignored = git(root, "check-ignore", "-q", path).returncode == 0
        except (OSError, subprocess.SubprocessError):
            ignored = False
        if ignored:
            print(f"git ignores {path}; add this line to .gitignore: {negation}")
            print(f"  (git cannot re-include a path whose parent directory is excluded; check "
                  f"with: git check-ignore -v {path})")
    print(f"to commit: git -C {shlex.quote(root)} add {MEMORY_DIR}/{README} {LINK_REL}")
    return 0


def load_before(arg: str) -> dict:
    text = arg if arg.lstrip().startswith("{") else Path(arg).read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        raise ValueError("the before listing has no `files` list")
    return data


def safe_basename(name) -> bool:
    return (isinstance(name, str) and name.endswith(".md") and name.lower() != README.lower()
            and "/" not in name and "\\" not in name and name not in (".", "..")
            and not name.startswith(".."))


def cmd_prune(cwd: str, before_arg: str) -> int:
    try:
        before = load_before(before_arg)
    except (OSError, ValueError) as err:
        print(f"prune: cannot read the before listing: {err}", file=sys.stderr)
        return 1
    root = repo_root(cwd) if os.path.isdir(cwd) else None
    mem = os.path.join(root, MEMORY_DIR) if root else None
    if not mem or os.path.islink(mem) or not os.path.isdir(mem):
        print(f"prune: no {MEMORY_DIR}/ at the repo root", file=sys.stderr)
        return 1
    listed = before.get("memory_dir")
    if not isinstance(listed, str) or not same_path(listed, mem):
        print(f"prune: the before listing is for {listed}, not {mem}; nothing deleted",
              file=sys.stderr)
        return 1
    deleted = []
    for rec in before["files"]:
        if not isinstance(rec, dict) or rec.get("kind") != "file" or not rec.get("has_content"):
            continue
        name = rec.get("file")
        if not safe_basename(name):
            continue
        path = os.path.join(mem, name)
        try:
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            with open(path, "rb") as fh:
                raw = fh.read()
            try:
                if raw.decode("utf-8").strip():
                    continue
            except UnicodeDecodeError:
                continue
            os.remove(path)
            deleted.append(name)
        except OSError as err:
            print(f"prune: {name}: {err.strerror or err}", file=sys.stderr)
    for name in deleted:
        print(f"deleted {MEMORY_DIR}/{name}")
    if not deleted:
        print("nothing to prune")
    for rec in list_memory(Path(mem)):
        for v in rec["violations"]:
            if v.startswith("ФМ8: the file holds frontmatter only"):
                print(f"left for the user: {MEMORY_DIR}/{rec['file']}: {v}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="memory.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("init", "status", "brief", "prune"):
        p = sub.add_parser(name)
        p.add_argument("--cwd", default=os.getcwd())
        if name == "status":
            p.add_argument("--json", action="store_true")
        if name == "prune":
            p.add_argument("--before", required=True)
    args = ap.parse_args(argv)
    cwd = os.path.abspath(args.cwd)
    if args.cmd == "init":
        return cmd_init(cwd)
    if args.cmd == "prune":
        return cmd_prune(cwd, args.before)
    rep = status(cwd)
    if args.cmd == "status":
        sys.stdout.write(json.dumps(rep, ensure_ascii=False, indent=2) + "\n" if args.json
                         else render_status(rep))
    else:
        sys.stdout.write(render_brief(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
