#!/usr/bin/env python3
"""Spend report over Claude Code transcripts. Read-only; prints numbers only, never message content.

Usage: cost-report.py <projects dir, or glob of them> [--since YYYY-MM-DD] [--threshold N]

Main sessions are *.jsonl directly in each matched project dir; subagents are <dir>/*/subagents/*.jsonl
plus any record flagged isSidechain. Assistant records are de-duplicated by message.id (last record
wins). Sections: spend by model, main sessions by context bucket, small tool-use calls, cache rewrites
after an idle gap, top sessions. --threshold N (default 250000) adds the share of main spend that
happened above N tokens of context.
"""
import glob
import json
import os
import sys
from datetime import datetime

# $/MTok by model-family substring (first match wins): in, out, write 1h, write 5m, read
PRICES = {
    "opus-5-5": (4.0, 20.0, 8.0, 5.0, 0.20),
    "opus-5": (5.0, 25.0, 10.0, 6.25, 0.50),
    "sonnet-5": (2.0, 10.0, 4.0, 2.5, 0.20),
    "haiku": (1.0, 5.0, 2.0, 1.25, 0.10),
}
FALLBACK = (5.0, 25.0, 10.0, 6.25, 0.50)
BUCKETS = [(0, 100e3), (100e3, 200e3), (200e3, 300e3), (300e3, 400e3), (400e3, 600e3), (600e3, float("inf"))]
GAPS = [("<60 min", 0, 3600), ("1-3h", 3600, 3 * 3600), ("3-12h", 3 * 3600, 12 * 3600), (">12h", 12 * 3600, float("inf"))]
SMALL_CHARS = 2000
UNKNOWN = set()


def prices(model):
    for key, p in PRICES.items():
        if key in (model or ""):
            return p
    if model != "<synthetic>":
        UNKNOWN.add(model or "(none)")
    return FALLBACK


def parse_ts(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def result_chars(content):
    """Size of the tool_result blocks in a user message (0 if none, -1 if there are no tool_results)."""
    if not isinstance(content, list):
        return -1
    total, seen = 0, False
    for b in content:
        if isinstance(b, dict) and b.get("type") == "tool_result":
            seen = True
            c = b.get("content")
            if isinstance(c, str):
                total += len(c)
            elif isinstance(c, list):
                total += sum(len(x.get("text") or "") for x in c if isinstance(x, dict))
    return total if seen else -1


def session_name(path):
    name = None
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if '"customTitle"' not in line and '"agentName"' not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            name = rec.get("customTitle") or rec.get("agentName") or name
    return name


def make_call(rec, since, sub):
    m = rec["message"]
    u = m.get("usage") or {}
    inp, out = u.get("input_tokens") or 0, u.get("output_tokens") or 0
    rd, cw = u.get("cache_read_input_tokens") or 0, u.get("cache_creation_input_tokens") or 0
    cc = u.get("cache_creation") or {}
    c5, c1 = cc.get("ephemeral_5m_input_tokens"), cc.get("ephemeral_1h_input_tokens")
    if c5 is None and c1 is None:
        c5, c1 = 0, cw
    pin, pout, w1, w5, prd = prices(m.get("model"))
    parts = dict(i=inp * pin / 1e6, r=rd * prd / 1e6, w=((c5 or 0) * w5 + (c1 or 0) * w1) / 1e6, o=out * pout / 1e6)
    tools = any(isinstance(b, dict) and b.get("type") == "tool_use" for b in (m.get("content") or []) if True) \
        if isinstance(m.get("content"), list) else False
    return dict(model=m.get("model") or "(none)", ts=parse_ts(rec.get("timestamp")), ctx=inp + rd + cw, cw=cw,
                parts=parts, cost=sum(parts.values()), sub=sub, tools=tools, res=None)


def load(files, since):
    """files: [(path, is_subagent_file)]. Returns (calls by id, name per session path)."""
    calls, names = {}, {}
    for path, subfile in files:
        sid = os.path.basename(path)[:-6][:8]
        names[path] = (sid, session_name(path))
        last = None
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if '"usage"' not in line and '"tool_result"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict):
                    continue
                msg = rec.get("message")
                if not isinstance(msg, dict):
                    continue
                if rec.get("type") == "user":
                    n = result_chars(msg.get("content"))
                    if last is not None and n >= 0 and last["res"] is None:
                        last["res"] = n
                    continue
                if rec.get("type") != "assistant" or not isinstance(msg.get("usage"), dict):
                    continue
                if (rec.get("timestamp") or "")[:10] < since:
                    continue
                c = make_call(rec, since, subfile or bool(rec.get("isSidechain")))
                c["path"] = path
                mid = msg.get("id") or rec.get("uuid") or "%s:%d" % (path, len(calls))
                old = calls.get(mid)
                if old is not None and old["tools"] and not c["tools"]:
                    c["tools"] = True  # tool_use block may sit in an earlier record of the same message
                if old is not None and old["res"] is not None and c["res"] is None:
                    c["res"] = old["res"]
                calls[mid] = c
                last = c
    return calls, names


def collect(arg):
    files = []
    for d in sorted(glob.glob(os.path.expanduser(arg))):
        if not os.path.isdir(d):
            continue
        files += [(p, False) for p in sorted(glob.glob(os.path.join(d, "*.jsonl")))]
        files += [(p, True) for p in sorted(glob.glob(os.path.join(d, "*", "subagents", "*.jsonl")))]
    return files


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def main(argv):
    since, threshold, args = "", 250000, []
    it = iter(argv)
    for a in it:
        if a in ("--since", "--threshold"):
            try:
                v = next(it)
                if a == "--since":
                    since = v
                else:
                    threshold = int(v)
            except (StopIteration, ValueError):
                print("%s requires a valid value" % a, file=sys.stderr)
                return 2
        else:
            args.append(a)
    if not args:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    files = collect(args[0])
    calls, names = load(files, since)
    allc = list(calls.values())
    main_c = [c for c in allc if not c["sub"]]
    sub_c = [c for c in allc if c["sub"]]
    tot_main = sum(c["cost"] for c in main_c)
    print("files %d, calls %d (main %d, subagent %d), since %s" % (len(files), len(allc), len(main_c), len(sub_c), since or "start"))
    if UNKNOWN:
        print("WARNING: unknown models priced at fallback opus rates: " + ", ".join(sorted(UNKNOWN)))

    print("\n1. Spend by model")
    for label, group in (("main", main_c), ("subagents", sub_c)):
        print("%s: %d calls, $%.2f" % (label, len(group), sum(c["cost"] for c in group)))
        by = {}
        for c in group:
            n, s = by.get(c["model"], (0, 0.0))
            by[c["model"]] = (n + 1, s + c["cost"])
        for mdl, (n, s) in sorted(by.items(), key=lambda kv: -kv[1][1]):
            print("  %-28s %7d calls  $%.2f" % (mdl, n, s))
    print("total: $%.2f" % (tot_main + sum(c["cost"] for c in sub_c)))

    print("\n2. Main sessions by context bucket")
    print("%-10s %7s %8s %6s  read/write/output %%" % ("bucket", "calls", "$/call", "share"))
    for lo, hi in BUCKETS:
        g = [c for c in main_c if lo <= c["ctx"] < hi]
        if not g:
            continue
        s = sum(c["cost"] for c in g)
        lab = "%d-%s" % (lo / 1e3, "" if hi == float("inf") else "%dk" % (hi / 1e3))
        lab = "%dk+" % (lo / 1e3) if hi == float("inf") else lab
        print("%-10s %7d %8.3f %5.1f%%  %.0f/%.0f/%.0f" % (lab, len(g), s / len(g), pct(s, tot_main),
              *[pct(sum(c["parts"][k] for c in g), s) for k in "rwo"]))
    over = sum(c["cost"] for c in main_c if c["ctx"] > threshold)
    print("above threshold %d tokens: %.1f%% of main $" % (threshold, pct(over, tot_main)))

    small = [c for c in main_c if c["tools"] and c["res"] is not None and c["res"] < SMALL_CHARS]
    print("\n3. Small calls (tool-use turn, next tool_result < %d chars)" % SMALL_CHARS)
    print("%d of %d main calls (%.1f%%), $%.2f = %.1f%% of main $" % (len(small), len(main_c), pct(len(small), len(main_c)),
          sum(c["cost"] for c in small), pct(sum(c["cost"] for c in small), tot_main)))

    print("\n4. Cache rewrites (cache_creation > 50% of context, context > 20k)")
    bysess = {}
    for c in main_c:
        bysess.setdefault(c["path"], []).append(c)
    rw = {g[0]: [0, 0.0] for g in GAPS}
    for lst in bysess.values():
        lst.sort(key=lambda c: c["ts"] or 0)
        for prev, c in zip(lst, lst[1:]):
            if c["cw"] > 0.5 * c["ctx"] and c["ctx"] > 20000 and c["ts"] and prev["ts"]:
                gap = c["ts"] - prev["ts"]
                for lab, lo, hi in GAPS:
                    if lo <= gap < hi:
                        rw[lab][0] += 1
                        rw[lab][1] += c["cost"]
                        break
    for lab, (n, s) in rw.items():
        print("gap %-8s %6d rewrites  $%.2f" % (lab, n, s))

    print("\n5. Top 5 sessions by $")
    per = {}
    for c in allc:
        n, s = per.get(c["path"], (0, 0.0))
        per[c["path"]] = (n + 1, s + c["cost"])
    for p, (n, s) in sorted(per.items(), key=lambda kv: -kv[1][1])[:5]:
        sid, nm = names[p]
        print("%s %-24s %6d calls  $%.2f%s" % (sid, nm or "(unnamed)", n, s, "  (subagent)" if "subagents" in p else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
