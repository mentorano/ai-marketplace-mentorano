"""Shared by build.py, serve.py and comments.py of the owner review page.

The review folder holds sections.json (the input), index.html (built), the screenshots, and
comments.jsonl (one JSON object per line: ts, id, verdict, text). Standard library only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SECTIONS = "sections.json"
COMMENTS = "comments.jsonl"
SERVER = "server.json"
VERDICTS = ("ok", "change", "question")
# R19: two capital letters and a number (LH1, KD12)
ID_RE = re.compile(r"[A-Z]{2}\d+")


class BadInput(ValueError):
    pass


def load_sections(path: Path) -> dict:
    """Read and validate sections.json; raise BadInput with every problem found."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BadInput(f"{path}: {error}") from error
    problems = []
    if not isinstance(data, dict):
        raise BadInput(f"{path}: the top level must be an object")
    if not isinstance(data.get("title"), str) or not data["title"].strip():
        problems.append("title: a non-empty string is needed")
    sections = data.get("sections")
    if not isinstance(sections, list) or not sections:
        problems.append("sections: a non-empty list is needed")
        sections = []
    seen = set()
    for n, section in enumerate(sections):
        where = f"sections[{n}]"
        if not isinstance(section, dict):
            problems.append(f"{where}: an object is needed")
            continue
        sid = section.get("id")
        if not isinstance(sid, str) or not ID_RE.fullmatch(sid):
            problems.append(f"{where}.id: {sid!r} is not an ID like LH1 (two capital letters and a number)")
        elif sid in seen:
            problems.append(f"{where}.id: {sid} is used twice")
        else:
            seen.add(sid)
        if not isinstance(section.get("title"), str) or not section["title"].strip():
            problems.append(f"{where}.title: a non-empty string is needed")
        for key in ("text", "notes"):
            value = section.get(key, [])
            if isinstance(value, str):
                continue
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                problems.append(f"{where}.{key}: a string or a list of strings is needed")
        for key in ("look", "code", "task"):
            if key in section and not isinstance(section[key], str):
                problems.append(f"{where}.{key}: a string is needed")
        for key in ("links", "shots"):
            if not isinstance(section.get(key, []), list):
                problems.append(f"{where}.{key}: a list is needed")
        for k, link in enumerate(as_seq(section.get("links"))):
            href = link.get("href") if isinstance(link, dict) else None
            if not isinstance(href, str) or not re.match(r"https?://[^\s]+\Z", href):
                problems.append(f"{where}.links[{k}].href: an http:// or https:// URL is needed")
        for k, shot in enumerate(as_seq(section.get("shots"))):
            src = shot.get("src") if isinstance(shot, dict) else None
            if not isinstance(src, str) or not safe_relative(src):
                problems.append(f"{where}.shots[{k}].src: {src!r} must be a relative path inside the review folder")
    if problems:
        raise BadInput("\n".join(problems))
    return data


def safe_relative(src: str) -> bool:
    if not src or src.startswith(("/", "\\")) or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", src):
        return False
    return ".." not in re.split(r"[\\/]", src)


def as_seq(value) -> list:
    return value if isinstance(value, list) else []


def as_list(value) -> list[str]:
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def read_comments(folder: Path) -> list[dict]:
    """Every well-formed row of comments.jsonl, in file order, with its 1-based `line` number;
    a broken line is skipped (it still counts as a line, like `wc -l`). Split on newlines only:
    the owner's text may hold U+2028, which json.dumps(ensure_ascii=False) writes raw."""
    return parse_comments(comments_text(folder))


def comments_text(folder: Path) -> str:
    """The complete lines of comments.jsonl: read as bytes, cut after the last newline, then
    decoded, so a line (or a multibyte character) still being written waits for the next read.
    A byte that is not UTF-8 inside a complete line (a write cut by a crash) becomes U+FFFD: that
    line fails to parse and is skipped, the rest of the file still reads."""
    path = Path(folder) / COMMENTS
    if not path.exists():
        return ""
    data = path.read_bytes()
    return data[:data.rfind(b"\n") + 1].decode("utf-8", errors="replace")


def parse_comments(text: str) -> list[dict]:
    """The rows of one snapshot of comments.jsonl (see read_comments)."""
    rows = []
    for number, line in enumerate(text.split("\n"), 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append({**row, "line": number})
    return rows
