#!/usr/bin/env python3
"""Turn the collector's JSON into a BOARD.md skeleton.

BOARD.md is the source of truth for the page. This script fills in everything
that was measured; the one line of prose per branch is left for a human (or the
skill) to write, because *what a branch is for* is a reading, not a measurement.

Every measured value lands in a `key: value` field line. Prose lives in the
paragraphs between those lines. `render.py` reads the same shape back.

usage: board.py board.json [--out BOARD.md]
"""
import argparse
import json
import sys

# how a branch's state is named on the page, most decisive first
STATE_RULES = (
    ("landed", lambda b: b["merged"]),
    ("in review", lambda b: b["pr"] and b["pr"]["state"] == "OPEN" and not b["pr"]["isDraft"]),
    ("draft PR", lambda b: b["pr"] and b["pr"]["state"] == "OPEN" and b["pr"]["isDraft"]),
    ("local only", lambda b: b["local_only"]),
    ("open", lambda b: True),
)

TODO = "TODO: one honest line — what this is and how far it got."


def state_of(b):
    for name, test in STATE_RULES:
        if test(b):
            return name
    return "open"


def size_of(b):
    if not b["ahead"]:
        return "no commits of its own"
    bits = [f"{b['ahead']} commits", f"{b['files']} files"]
    if b["insertions"] or b["deletions"]:
        bits.append(f"+{b['insertions']} −{b['deletions']}")
    return " · ".join(bits)


def evidence_of(b):
    """Say what makes the state true, never just that it is true."""
    if b["landed_by"] == "ancestor":
        return "the tip is an ancestor of the base"
    if b["landed_by"] == "pr":
        return f"PR #{b['pr']['number']} is merged (squash — the commits do not match)"
    if b["pr"]:
        return f"PR #{b['pr']['number']} {b['pr']['state']}"
    return "no PR"


def field(key, value):
    return f"- {key}: {value}\n"


def render_branch(b):
    out = [f"## {b['name']}\n\n"]
    out.append(field("state", state_of(b)))
    out.append(field("evidence", evidence_of(b)))
    out.append(field("author", b["author"]))
    out.append(field("last", f"{b['last_date']} ({b['in_window_by']})"))
    out.append(field("size", size_of(b)))
    out.append(field("position", f"{b['ahead']} ahead / {b['behind']} behind the base"))
    if b["role"] == "pointer":
        out.append(field("role", "pointer — points into the base, no work of its own"))
    if b["local_only"]:
        out.append(field("local-only", "written and never pushed"))
    if b["top_dirs"]:
        dirs = ", ".join(f"{d['path']} ({d['files']})" for d in b["top_dirs"])
        out.append(field("dirs", dirs))
    if b["pr"]:
        out.append(field("pr", f"[#{b['pr']['number']} {b['pr']['state']}]({b['pr']['url']}) "
                               f"— {b['pr']['title']}"))

    plans = [p for p in b["plans"] if p["kind"] == "plan"]
    incidental = [p for p in b["plans"] if p["kind"] == "incidental"]
    if plans:
        for p in plans:
            cb = p["checkboxes"]
            ticks = f"{cb['done']}/{cb['done'] + cb['todo']} ticked" if cb["done"] + cb["todo"] else "no checkboxes"
            out.append(field("plan", f"`{p['path']}` — {ticks}"))
            if p["goal"]:
                out.append(field("goal", p["goal"]))
    elif incidental:
        out.append(field("plan", "no plan of its own — the touched documents are incidental "
                                 f"({', '.join('`' + p['path'] + '`' for p in incidental)})"))
    else:
        out.append(field("plan", "no plan of its own"))

    out.append("\n" + TODO + "\n")

    for p in plans:
        for f in p["flags"][:3]:
            out.append("\n> " + f.replace("\n", " ") + "\n")

    if b["commits"]:
        out.append("\n### recent commits\n\n")
        for c in b["commits"][:5]:
            out.append(f"- `{c['sha']}` {c['date']} — {c['subject']}\n")
    out.append("\n")
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path")
    ap.add_argument("--out", default="-")
    a = ap.parse_args()

    with open(a.json_path, encoding="utf-8") as f:
        d = json.load(f)
    m = d["meta"]

    out = ["---\n"]
    out.append(field("repo", m["repo_name"]))
    out.append(field("base", f"{m['base']} @ {m['base_sha']}"))
    out.append(field("window", f"{m['days']} days"))
    out.append(field("generated", m["generated"]))
    out.append(field("branches", str(len(d["branches"]))))
    out.append(field("gh", "yes" if m["gh"] else "no — the PR state is missing"))
    out.append(field("pruned", "yes" if m["pruned"] else "NO"))
    for w in m["warnings"]:
        out.append(field("warning", w))
    out.append("---\n\n")

    out.append(f"# Branch Board — {m['repo_name']}\n\n")
    out.append("TODO: two or three lines on what the board shows right now.\n\n")

    work = [b for b in d["branches"] if b["role"] == "work"]
    pointers = [b for b in d["branches"] if b["role"] != "work"]

    for b in work:
        out.append(render_branch(b))

    if pointers:
        out.append("# Pointers\n\n")
        out.append("These point into the base and have no commits of their own. Git cannot tell "
                   "a release pointer from a merged branch — both look like this.\n\n")
        for b in pointers:
            out.append(render_branch(b))

    out.append("# Where the numbers come from\n\n")
    for c in m["commands"]:
        out.append(f"- `{c}`\n")

    text = "".join(out)
    if a.out == "-":
        sys.stdout.write(text)
    else:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"written: {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
