#!/usr/bin/env python3
"""Tally per-item verdicts from several voters' JSON answers (triage mode).

Usage: tally.py --list KEY --id ID_FIELD --fields F1,F2 [--voters N] VOTER.json [VOTER.json ...]

Pass an explicit file list (the answers whose panel.py status line said "ok", from a run or --check), never a glob: tally.json
lives in the same directory and must not be read back in. The voter's name is the file name
without ".json"; two files with the same name, or more files than --voters, are an error (exit 2,
nothing written).

--voters N is the expected panel size (default: number of files; must be at least 1); majorities are computed
against N, so missing voters cannot manufacture consensus. A file that is not JSON, or whose KEY
is missing or not a list, is skipped (listed in "skipped" with the reason) and counts as a
missing voter.

Item ids are compared as strings (12 and "12" are one item) and sorted naturally (digit runs by
value: 2 < 10, "F2" < "F10"). Field values are compared after stripping and casefolding strings ("Keep " == "keep");
lists and objects compare by content. The FIRST field in --fields is the primary verdict and
alone decides the item's kind:
  agree        every one of the N voters voted and all agree on it (N >= 2)
  majority     more than N/2 voters agree on it, and at least 2
  split        two or more votes present but no such majority, or a tie for the top (decision null)
  insufficient only one valid vote present (decision null)
Every other field is compared only among the voters that share the winning primary value; its
kind is agree (all of them), majority (more than half) or split (decision value null).

A voter's item is invalid (excluded, counted in "invalid") when its id is null or duplicated
within that file, or any --fields key is missing. Writes tally.json next to the first file. Each
row: {"id","decision": {field: value|null}|null,"kind","details": {secondary field: {"value",
"kind"}},"votes": {voter: item}}. Ids and values are shown as the first (winning) voter wrote
them. Prints a summary: item count, count per kind, "invalid", "skipped" [{"file","why"}],
"missing" {voter: [ids other voters voted on but this one did not validly; a skipped voter
misses them all]} and the file path.
"""
import argparse
import collections
import json
import os
import re


def canon(value):
    """Comparison key for a field value: strings stripped and casefolded, containers by content."""
    if isinstance(value, str):
        value = value.strip().casefold()
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def id_order(key):
    """Natural sort key for a string id: digit runs compare as numbers ("F2" < "F10", 2 < 10)."""
    return tuple(int(p) if n % 2 else p for n, p in enumerate(re.split(r"(\d+)", key)))


def load(path, key, id_field, fields):
    """Return ({str id: item}, invalid_count) for one voter file; raise ValueError if unusable."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        raise ValueError(f"not readable JSON: {e}") from None
    rows = doc.get(key) if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"key {key!r} is missing or not a list")

    def ident(x):
        i = x.get(id_field) if isinstance(x, dict) else None
        return None if i is None else str(i)

    ids = collections.Counter(ident(x) for x in rows)
    items, bad = {}, 0
    for x in rows:
        i = ident(x)
        if i is None or ids[i] > 1 or any(f not in x for f in fields):
            bad += 1  # a duplicated id is untrustworthy, every copy is dropped
        else:
            items[i] = x
    return items, bad


def top_value(votes, field):
    """Return (voters holding the most common value of field, that count, tied for the top?)."""
    groups = collections.defaultdict(list)
    for name, item in votes.items():
        groups[canon(item[field])].append(name)
    ranked = sorted(groups.values(), key=len, reverse=True)
    tied = len(ranked) > 1 and len(ranked[1]) == len(ranked[0])
    return ranked[0], len(ranked[0]), tied


def judge(votes, fields, panel):
    """Return (kind, decision, details) for one item's valid votes."""
    winners, n, tied = top_value(votes, fields[0])
    if len(votes) < 2:
        return "insufficient", None, {}
    if tied or n < 2 or n * 2 <= panel:
        return "split", None, {}
    kind = "agree" if n == panel else "majority"
    decision = {fields[0]: votes[winners[0]][fields[0]]}
    details = {}
    among = {name: votes[name] for name in winners}
    for f in fields[1:]:
        holders, m, f_tied = top_value(among, f)
        if f_tied or m * 2 <= len(among):
            details[f] = {"value": None, "kind": "split"}
        else:
            details[f] = {"value": among[holders[0]][f], "kind": "agree" if m == len(among) else "majority"}
        decision[f] = details[f]["value"]
    return kind, decision, details


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--fields", required=True)
    ap.add_argument("--voters", type=int, help="expected panel size (default: number of files)")
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()
    fields = a.fields.split(",")
    panel = len(a.files) if a.voters is None else a.voters
    if panel < 1:
        ap.error(f"--voters {panel}: the panel size must be at least 1")
    if len(a.files) > panel:
        ap.error(f"{len(a.files)} files but --voters {panel}: pass only the panel's files")
    names = [os.path.basename(f).rsplit(".", 1)[0] for f in a.files]
    dup = sorted(n for n, c in collections.Counter(names).items() if c > 1)
    if dup:
        ap.error(f"duplicate voter name(s) {', '.join(dup)}: each voter needs its own file name")

    voters, invalid, skipped = {}, 0, []
    for name, f in zip(names, a.files):
        try:
            voters[name], bad = load(f, a.list, a.id, fields)
        except ValueError as e:
            skipped.append({"file": f, "why": str(e)})
            continue
        invalid += bad
    keys = sorted({i for v in voters.values() for i in v}, key=id_order)
    out, kinds = [], collections.Counter()
    shown = {}  # str id -> the id as the first voter wrote it
    for i in keys:
        votes = {name: v[i] for name, v in voters.items() if i in v}
        shown[i] = next(iter(votes.values()))[a.id]
        kind, decision, details = judge(votes, fields, panel)
        kinds[kind] += 1
        out.append({"id": shown[i], "decision": decision, "kind": kind, "details": details, "votes": votes})
    missing = {name: [shown[i] for i in keys if i not in voters.get(name, {})] for name in names}
    path = os.path.join(os.path.dirname(os.path.abspath(a.files[0])), "tally.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(json.dumps({"items": len(keys), **kinds, "invalid": invalid, "skipped": skipped,
                      "missing": {n: ids for n, ids in missing.items() if ids}, "file": path},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
