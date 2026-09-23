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

TODO = "TODO: една честна линия — какво е това и докъде е стигнало."


def state_of(b):
    for name, test in STATE_RULES:
        if test(b):
            return name
    return "open"


def size_of(b):
    if not b["ahead"]:
        return "няма собствени commits"
    bits = [f"{b['ahead']} commits", f"{b['files']} files"]
    if b["insertions"] or b["deletions"]:
        bits.append(f"+{b['insertions']} −{b['deletions']}")
    return " · ".join(bits)


def evidence_of(b):
    """Say what makes the state true, never just that it is true."""
    if b["landed_by"] == "ancestor":
        return "върхът е ancestor на base-а"
    if b["landed_by"] == "pr":
        return f"PR #{b['pr']['number']} е merged (squash — commits не съвпадат)"
    if b["pr"]:
        return f"PR #{b['pr']['number']} {b['pr']['state']}"
    return "няма PR"


def field(key, value):
    return f"- {key}: {value}\n"


def render_branch(b):
    out = [f"## {b['name']}\n\n"]
    out.append(field("state", state_of(b)))
    out.append(field("evidence", evidence_of(b)))
    out.append(field("author", b["author"]))
    out.append(field("last", f"{b['last_date']} ({b['in_window_by']})"))
    out.append(field("size", size_of(b)))
    out.append(field("position", f"{b['ahead']} напред / {b['behind']} назад от base-а"))
    if b["role"] == "pointer":
        out.append(field("role", "pointer — сочи в base-а, няма собствена работа"))
    if b["local_only"]:
        out.append(field("local-only", "написан и никога не push-нат"))
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
            ticks = f"{cb['done']}/{cb['done'] + cb['todo']} отметнати" if cb["done"] + cb["todo"] else "без чекбокси"
            out.append(field("plan", f"`{p['path']}` — {ticks}"))
            if p["goal"]:
                out.append(field("goal", p["goal"]))
    elif incidental:
        out.append(field("plan", "няма собствен план — докоснатите документи са мимоходом "
                                 f"({', '.join('`' + p['path'] + '`' for p in incidental)})"))
    else:
        out.append(field("plan", "няма собствен план"))

    out.append("\n" + TODO + "\n")

    for p in plans:
        for f in p["flags"][:3]:
            out.append("\n> " + f.replace("\n", " ") + "\n")

    if b["commits"]:
        out.append("\n### последни commits\n\n")
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
    out.append(field("window", f"{m['days']} дни"))
    out.append(field("generated", m["generated"]))
    out.append(field("branches", str(len(d["branches"]))))
    out.append(field("gh", "да" if m["gh"] else "не — PR състоянието липсва"))
    out.append(field("pruned", "да" if m["pruned"] else "НЕ"))
    for w in m["warnings"]:
        out.append(field("warning", w))
    out.append("---\n\n")

    out.append(f"# Branch Board — {m['repo_name']}\n\n")
    out.append("TODO: два-три реда какво показва бордът точно сега.\n\n")

    work = [b for b in d["branches"] if b["role"] == "work"]
    pointers = [b for b in d["branches"] if b["role"] != "work"]

    for b in work:
        out.append(render_branch(b))

    if pointers:
        out.append("# Pointers\n\n")
        out.append("Тези сочат в base-а и нямат собствени commits. Git не различава "
                   "release pointer от merge-нат branch — и двата изглеждат така.\n\n")
        for b in pointers:
            out.append(render_branch(b))

    out.append("# Откъде идват числата\n\n")
    for c in m["commands"]:
        out.append(f"- `{c}`\n")

    text = "".join(out)
    if a.out == "-":
        sys.stdout.write(text)
    else:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"написан: {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
