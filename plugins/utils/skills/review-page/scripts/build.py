#!/usr/bin/env python3
"""Build the owner review page: <review folder>/sections.json -> <review folder>/index.html.

Usage: build.py <review folder>

sections.json:
  {"title": "Review — <topic>", "intro": "<optional paragraph>",
   "sections": [{"id": "LH1", "title": "<short name>", "task": "<optional, e.g. ZD3>",
                 "text": ["<what changed, paragraph>", ...], "look": "<what to look at>",
                 "links": [{"href": "http://127.0.0.1:5173/x", "label": "<optional>"}],
                 "notes": ["<a warning, e.g. what no screenshot shows>"],
                 "shots": [{"src": "LH1/dialog-390x844-dark.png", "caption": "<what and size>"}],
                 "code": "<optional preformatted text, e.g. a small diff>"}]}
Every text is plain text (HTML-escaped). A shot path is relative to the review folder.
Exit 0: built (prints BUILT <index.html> <n> sections). Exit 1: a screenshot is missing (one
MISSING line each, nothing written). Exit 2: bad input.
"""
from __future__ import annotations

import html
import re
import sys
from urllib.parse import quote
from pathlib import Path

from review_common import SECTIONS, BadInput, as_list, as_seq, load_sections

TEMPLATE = Path(__file__).resolve().parent / "page.html"


def e(text) -> str:
    return html.escape(str(text), quote=True)


def section_html(section: dict) -> str:
    sid = section["id"]
    small = e(section["title"]) + (f" ({e(section['task'])})" if section.get("task") else "")
    out = [f'<section id="{e(sid)}" data-title="{e(section["title"])}">',
           f"<h2>{e(sid)} <small>{small}</small></h2>"]
    out += [f"<p>{e(p)}</p>" for p in as_list(section.get("text"))]
    if section.get("look"):
        out.append(f'<p class="look">Look at: {e(section["look"])}</p>')
    for link in as_seq(section.get("links")):
        label = link.get("label") or link["href"]
        out.append(f'<p><a href="{e(link["href"])}" target="_blank" rel="noopener">{e(label)}</a></p>')
    out += [f'<div class="warn">{e(n)}</div>' for n in as_list(section.get("notes"))]
    shots = as_seq(section.get("shots"))
    if shots:
        out.append('<div class="shots">')
        for shot in shots:
            caption = shot.get("caption") or shot["src"]
            out.append(f'<figure><img src="{e(quote(shot["src"]))}" alt="{e(caption)}" loading="lazy">'
                       f"<figcaption>{e(caption)}</figcaption></figure>")
        out.append("</div>")
    if section.get("code"):
        out.append(f"<pre>{e(section['code'])}</pre>")
    out.append("</section>")
    return "\n".join(out)


def render(data: dict) -> str:
    parts = {
        "TITLE": e(data["title"]),
        "INTRO": f"<p>{e(data['intro'])}</p>" if data.get("intro") else "",
        "SECTIONS": "\n\n".join(section_html(s) for s in data["sections"]),
    }
    template = TEMPLATE.read_text(encoding="utf-8")
    # one pass, so a placeholder inside the owner's text is never expanded
    return re.sub(r"\{\{(TITLE|INTRO|SECTIONS)\}\}", lambda m: parts[m.group(1)], template)


def missing_shots(folder: Path, data: dict) -> list[str]:
    return [f"MISSING {s['id']} {shot['src']}" for s in data["sections"]
            for shot in as_seq(s.get("shots")) if not (folder / shot["src"]).is_file()]


def build(folder: Path) -> tuple[int, str]:
    folder = Path(folder).resolve()
    try:
        data = load_sections(folder / SECTIONS)
    except BadInput as error:
        return 2, str(error)
    missing = missing_shots(folder, data)
    if missing:
        return 1, "\n".join(missing)
    index = folder / "index.html"
    index.write_text(render(data), encoding="utf-8")
    return 0, f"BUILT {index} {len(data['sections'])} sections"


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] in ("-h", "--help"):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    code, text = build(Path(argv[0]))
    print(text, file=sys.stdout if code == 0 else sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
