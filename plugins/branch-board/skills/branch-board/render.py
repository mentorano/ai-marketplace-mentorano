#!/usr/bin/env python3
"""Render BOARD.md into a self-contained HTML page for the Artifact tool.

BOARD.md is the source of truth. This script never invents a value: it reads the
same shape board.py writes, and any edit made to the markdown by hand shows up
on the next render. Re-publishing the same HTML path replaces the page at the
same URL, so a shared link keeps working as the board is re-run.

The page encodes where each claim came from in the typeface itself: measured
values are monospaced, the human sentence about a branch is set in a serif, and
structure is a grotesque. A reader can see which is which before reading a word.

usage: render.py BOARD.md --out board.html
"""
import argparse
import html
import re
import sys

# state name -> (css class, label). Anything unlisted falls back to "open".
STATES = {
    "landed": ("landed", "landed"),
    "in review": ("review", "in review"),
    "draft PR": ("draft", "draft PR"),
    "local only": ("local", "local only"),
    "open": ("open", "open"),
}

INLINE_CODE = re.compile(r"`([^`]+)`")
LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
BOLD = re.compile(r"\*\*([^*]+)\*\*")
FIELD = re.compile(r"^-\s+([A-Za-zА-Яа-я][\w -]*):\s*(.*)$")

# The keys `board.py` writes for a branch. Anything else shaped like
# "- word: text" is a human sentence, and the page sets measurements in a
# monospace face — so an unlisted key must never become a field row, or a
# judgement is rendered in the typeface reserved for measurement.
RECORD_KEYS = frozenset((
    "state", "evidence", "author", "last", "size", "position",
    "role", "local-only", "dirs", "pr", "plan", "goal",
))


def inline(text):
    """Escape, then re-introduce the small markdown subset the board uses."""
    out = html.escape(text)
    out = LINK.sub(
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}" '
                  f'target="_blank" rel="noopener">{m.group(1)}</a>', out)
    out = INLINE_CODE.sub(r"<code>\1</code>", out)
    out = BOLD.sub(r"<strong>\1</strong>", out)
    return out


def parse(text):
    """BOARD.md -> {meta, sections}. A section is a heading plus its records."""
    lines = text.splitlines()
    meta, i = [], 0
    if lines and lines[0].strip() == "---":
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            m = FIELD.match(lines[i].strip())
            if m:
                meta.append((m.group(1), m.group(2)))
            i += 1
        i += 1

    sections, cur, rec = [], None, None

    def close_rec():
        nonlocal rec
        if rec and cur is not None:
            cur["records"].append(rec)
        rec = None

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("# "):
            close_rec()
            cur = {"title": s[2:].strip(), "intro": [], "records": []}
            sections.append(cur)
        elif s.startswith("## "):
            close_rec()
            rec = {"name": s[3:].strip(), "fields": [], "prose": [],
                   "flags": [], "commits": []}
        elif s.startswith("### "):
            if rec is not None:
                rec["in_commits"] = True
        elif s.startswith(">"):
            if rec is not None:
                rec["flags"].append(s.lstrip("> ").strip())
        elif FIELD.match(s):
            m = FIELD.match(s)
            if rec is not None:
                if rec.get("in_commits"):
                    rec["commits"].append((m.group(1), m.group(2)))
                elif m.group(1) in RECORD_KEYS:
                    rec["fields"].append((m.group(1), m.group(2)))
                else:
                    rec["prose"].append(s[2:])
            elif cur is not None:
                cur["intro"].append(s)
        elif s.startswith("- ") and rec is not None and rec.get("in_commits"):
            rec["commits"].append(("", s[2:]))
        elif s.startswith("- ") and rec is not None:
            # a bullet a human wrote under a branch belongs to THAT branch. It
            # used to fall through to the section handler and surface at the top
            # of the section, read as a statement about the whole board.
            rec["prose"].append(s[2:])
        elif s.startswith("- ") and cur is not None:
            cur["intro"].append(s[2:])
        elif s:
            if rec is not None:
                rec["prose"].append(s)
            elif cur is not None:
                cur["intro"].append(s)
        i += 1
    close_rec()
    return meta, sections


def state_chip(fields):
    for k, v in fields:
        if k == "state":
            cls, label = STATES.get(v.strip(), ("open", v.strip()))
            return f'<span class="chip chip--{cls}">{html.escape(label)}</span>'
    return ""


def render_record(rec):
    hidden = {"state"}
    rows = "".join(
        f'<div class="k">{html.escape(k)}</div><div class="v">{inline(v)}</div>'
        for k, v in rec["fields"] if k not in hidden)
    parts = [f'<article class="rec">',
             f'<header class="rec__head">',
             f'<h3 class="rec__name">{html.escape(rec["name"])}</h3>',
             state_chip(rec["fields"]),
             '</header>']
    if rows:
        parts.append(f'<div class="fields">{rows}</div>')
    for p in rec["prose"]:
        cls = "prose prose--todo" if p.startswith("TODO:") else "prose"
        parts.append(f'<p class="{cls}">{inline(p)}</p>')
    for f in rec["flags"]:
        parts.append(f'<blockquote class="flag">{inline(f)}</blockquote>')
    if rec["commits"]:
        items = "".join(f"<li>{inline(v)}</li>" for _, v in rec["commits"] if v)
        parts.append(f'<details class="commits"><summary>последни commits</summary>'
                     f'<ul>{items}</ul></details>')
    parts.append("</article>")
    return "".join(parts)


CSS = """
:root{
  --paper:#F5F6F7; --ink:#191C20; --ink-2:#4B535C;
  /* --muted carries every field label, every section heading, the footer
     generation stamp and the unanswered TODO. At #767E88 it measured
     3.80:1 on --paper, below WCAG AA's 4.5:1 for text under 18.66px.
     #626B76 measures 5.00:1 and stays below --ink-2 in the hierarchy. */
  --muted:#626B76; --rule:#DDE1E4; --rule-2:#EAEDEF;
  --accent:#2E6B62; --accent-soft:#E3EDEA;
  --landed:#3F6B4E; --landed-bg:#E4EDE6;
  --review:#8A5D1C; --review-bg:#F4EADA;
  --open:#525C67;  --open-bg:#E9ECEF;
  --local:#5B4A7A; --local-bg:#EBE7F2;
  --warn:#9B4227;  --warn-bg:#F6E5E0;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --paper:#14171A; --ink:#E8EBED; --ink-2:#B3BBC3;
    --muted:#8A939C; --rule:#2C3238; --rule-2:#23282D;
    --accent:#6FB3A6; --accent-soft:#1E2E2B;
    --landed:#8CC29C; --landed-bg:#1D2A21;
    --review:#D9AB68; --review-bg:#2E2517;
    --open:#9AA5B0;  --open-bg:#232930;
    --local:#B4A0D6; --local-bg:#251F31;
    --warn:#E39177;  --warn-bg:#31201A;
  }
}
:root[data-theme="dark"]{
  --paper:#14171A; --ink:#E8EBED; --ink-2:#B3BBC3;
  --muted:#8A939C; --rule:#2C3238; --rule-2:#23282D;
  --accent:#6FB3A6; --accent-soft:#1E2E2B;
  --landed:#8CC29C; --landed-bg:#1D2A21;
  --review:#D9AB68; --review-bg:#2E2517;
  --open:#9AA5B0;  --open-bg:#232930;
  --local:#B4A0D6; --local-bg:#251F31;
  --warn:#E39177;  --warn-bg:#31201A;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:"Source Serif 4",Georgia,"Times New Roman",serif;
  font-size:16px; line-height:1.6;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:52rem; margin:0 auto; padding:3rem 1.25rem 5rem}
h1,h2,h3,.chip,.k,.eyebrow,summary{
  font-family:Archivo,"Helvetica Neue",Arial,sans-serif;
}
code,.v,.commits li,.cmds li{
  font-family:"JetBrains Mono",ui-monospace,"SFMono-Regular",Menlo,monospace;
  font-variant-numeric:tabular-nums;
}

/* ---- masthead ---- */
.masthead{border-bottom:2px solid var(--ink); padding-bottom:1.25rem; margin-bottom:.5rem}
.eyebrow{
  font-size:.6875rem; letter-spacing:.14em; text-transform:uppercase;
  color:var(--accent); font-weight:600; margin:0 0 .5rem;
}
h1{
  font-size:clamp(1.75rem,5vw,2.5rem); line-height:1.12; margin:0;
  font-weight:700; letter-spacing:-.02em; text-wrap:balance;
}
.meta{
  margin:1.25rem 0 0; padding:0;
  display:grid; grid-template-columns:repeat(auto-fit,minmax(11rem,1fr)); gap:.75rem 1.5rem;
}
.meta div{display:flex; flex-direction:column; gap:.15rem}
.meta dd{margin:0}
.meta .k{font-size:.625rem; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); font-weight:600}
.meta .v{font-size:.875rem; color:var(--ink-2)}
.banner{
  margin:1.5rem 0 0; padding:.75rem 1rem; border-left:3px solid var(--warn);
  background:var(--warn-bg); color:var(--warn); font-size:.875rem;
}
.banner strong{font-family:Archivo,sans-serif}

/* ---- sections ---- */
.section{margin-top:3.5rem}
h2{
  font-size:.75rem; letter-spacing:.16em; text-transform:uppercase;
  color:var(--muted); font-weight:600; margin:0 0 .25rem;
  padding-bottom:.5rem; border-bottom:1px solid var(--rule);
}
.section__intro{color:var(--ink-2); font-size:.9375rem; margin:1rem 0 0; max-width:60ch}

/* ---- record ---- */
.rec{
  border-bottom:1px solid var(--rule); padding:1.75rem 0;
  display:flex; flex-direction:column; gap:.875rem;
}
.rec:last-child{border-bottom:none}
.rec__head{display:flex; align-items:baseline; gap:.75rem; flex-wrap:wrap}
.rec__name{
  font-size:1.0625rem; font-weight:700; margin:0; letter-spacing:-.01em;
  font-family:"JetBrains Mono",ui-monospace,monospace;
}
.chip{
  font-size:.625rem; letter-spacing:.1em; text-transform:uppercase; font-weight:600;
  padding:.2rem .5rem; border-radius:2px; white-space:nowrap;
}
.chip--landed{color:var(--landed); background:var(--landed-bg)}
.chip--review{color:var(--review); background:var(--review-bg)}
.chip--draft {color:var(--open);   background:var(--open-bg)}
.chip--local {color:var(--local);  background:var(--local-bg)}
.chip--open  {color:var(--open);   background:var(--open-bg)}

.fields{
  display:grid; grid-template-columns:7.5rem minmax(0,1fr); gap:.35rem 1rem;
  font-size:.8125rem; align-items:baseline;
}
.fields .k{
  font-size:.625rem; letter-spacing:.1em; text-transform:uppercase;
  color:var(--muted); font-weight:600; padding-top:.15rem;
}
.fields .v{color:var(--ink-2); line-height:1.55; word-break:break-word}
.fields .v code{background:none; padding:0; color:var(--ink)}

.prose{margin:0; max-width:64ch; color:var(--ink)}
.prose--todo{color:var(--muted); font-style:italic}
.flag{
  margin:0; padding:.625rem 0 .625rem 1rem; border-left:2px solid var(--accent);
  color:var(--ink-2); font-size:.875rem; background:var(--accent-soft);
  padding-right:1rem; border-radius:0 2px 2px 0;
}
.commits{font-size:.8125rem}
.commits summary{
  cursor:pointer; color:var(--accent); font-size:.6875rem;
  letter-spacing:.1em; text-transform:uppercase; font-weight:600;
}
.commits summary:focus-visible{outline:2px solid var(--accent); outline-offset:3px}
.commits ul{margin:.625rem 0 0; padding-left:1.1rem; color:var(--ink-2)}
.commits li{margin:.3rem 0; line-height:1.5}

a{color:var(--accent); text-decoration-thickness:1px; text-underline-offset:2px}
a:focus-visible{outline:2px solid var(--accent); outline-offset:2px; border-radius:2px}
code{background:var(--rule-2); padding:.1em .3em; border-radius:2px; font-size:.9em}

.cmds{list-style:none; margin:1rem 0 0; padding:0; overflow-x:auto}
.cmds li{
  font-size:.75rem; color:var(--ink-2); padding:.3rem 0;
  border-bottom:1px solid var(--rule-2); white-space:nowrap;
}
.cmds li:last-child{border-bottom:none}
.foot{margin-top:3rem; padding-top:1.25rem; border-top:1px solid var(--rule);
      color:var(--muted); font-size:.8125rem}
@media (max-width:34rem){
  .fields{grid-template-columns:1fr; gap:.1rem}
  .fields .k{padding-top:.5rem}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important; transition:none!important}}
"""


def build(meta, sections):
    mdict = {k: v for k, v in meta}
    repo = mdict.get("repo", "repository")
    warnings = [v for k, v in meta if k == "warning"]
    shown = [(k, v) for k, v in meta
             if k in ("base", "window", "generated", "branches", "gh", "pruned")]

    # the repo name is the identity; "Branches" says what the page is. No dash
    # explainer — the gallery shows the description under the title.
    out = [f"<title>{html.escape(repo)} Branches</title>",
           '<link rel="preconnect" href="https://fonts.googleapis.com">',
           '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
           '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
           'family=Archivo:wght@500;600;700&family=JetBrains+Mono:wght@400;500;700&'
           'family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&'
           'display=swap">',
           f"<style>{CSS}</style>",
           '<div class="wrap">',
           '<header class="masthead">',
           '<p class="eyebrow">състояние на branches</p>',
           f"<h1>{html.escape(repo)}</h1>",
           '<dl class="meta">']
    for k, v in shown:
        out.append(f'<div><dt class="k">{html.escape(k)}</dt>'
                   f'<dd class="v">{inline(v)}</dd></div>')
    out.append("</dl>")
    for w in warnings:
        out.append(f'<p class="banner"><strong>внимание:</strong> {inline(w)}</p>')
    out.append("</header>")

    for idx, sec in enumerate(sections):
        title = sec["title"]
        is_cmds = title.lower().startswith("откъде")
        out.append('<section class="section">')
        # the first section's title repeats the masthead; the records are the point
        if idx > 0 or not sec["records"]:
            out.append(f"<h2>{html.escape(title)}</h2>")
        if is_cmds:
            out.append('<ul class="cmds">')
            for line in sec["intro"]:
                out.append(f"<li>{inline(line)}</li>")
            out.append("</ul>")
        else:
            for line in sec["intro"]:
                if not line.startswith("TODO:"):
                    out.append(f'<p class="section__intro">{inline(line)}</p>')
                else:
                    out.append(f'<p class="section__intro prose--todo">{inline(line)}</p>')
            for rec in sec["records"]:
                out.append(render_record(rec))
        out.append("</section>")

    out.append(f'<p class="foot">Всяко число тук идва от команда, изброена по-горе. '
               f'Страницата е изход на <code>BOARD.md</code>, не се редактира на ръка. '
               f'Генерирана {html.escape(mdict.get("generated", "—"))}.</p>')
    out.append("</div>")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md_path")
    ap.add_argument("--out", default="-")
    a = ap.parse_args()
    with open(a.md_path, encoding="utf-8") as f:
        meta, sections = parse(f.read())
    page = build(meta, sections)
    if a.out == "-":
        sys.stdout.write(page)
    else:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(page)
        print(f"написан: {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
