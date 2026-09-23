#!/usr/bin/env python3
"""Collect branch state from a git repo as JSON.

Every number this emits comes from a command recorded in `meta.commands`,
so the page built from it can show how each claim was measured.

usage: collect.py [REPO] [--days 7] [--base origin/main] [--no-fetch]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

CMDS = []


def git(repo, *args, rc=False):
    """Run a git command. Returns stripped stdout, or '' when it fails.

    Every git command in this script goes through here, so `--no-optional-locks`
    is applied without exception: the collector must never take `index.lock` in
    a repository somebody else is working in.

    `rc=True` returns the exit code instead. Callers that must tell "the command
    failed" apart from "the command returned nothing" need it — an empty string
    means both, and that ambiguity turns a broken run into an empty page.

    It also pins `LC_ALL=C`, so every message this script parses is the one it
    was written against rather than the operator's language.
    """
    cmd = ["git", "-C", repo, "--no-optional-locks", *args]
    # LC_ALL=C pins git's message language. `git diff --shortstat` is parsed by
    # looking for the words "insertion" and "deletion", and git translates that
    # line: on a translated build every branch reported +0 −0, a guess wearing
    # the shape of a measurement.
    env = dict(os.environ, LC_ALL="C")
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if rc:
        return p.returncode
    return p.stdout.strip() if p.returncode == 0 else ""


def have_gh():
    return shutil.which("gh") is not None


# Goal headings, best first. A heading that states the goal outright beats one
# that merely introduces the document, so "## Цел" wins over an earlier
# "## Overview" no matter which comes first in the file.
GOAL_HEADS = (
    ("цел", "goal", "objective", "задача"),
    ("проблем", "problem", "why", "защо"),
    ("обхват", "scope", "overview", "summary", "резюме", "какво"),
)
# "## Какво НЕ се строи" is a goal-shaped heading that introduces the opposite
# of the goal. Reading its body as the goal yields a confident wrong answer.
#
# Matched on scope-negation IDIOMS, not on any occurrence of "не"/"no". A bare
# negation fires in the wrong direction: GOAL_HEADS ranks "проблем"/"problem"
# as the second-best goal source, and a problem is almost always stated in the
# negative ("## Проблем: не се вижда кой какво прави"), so the whole group went
# silent. "No" is also an ordinary abbreviation for a number ("## Цел No 2").
NEGATIVE_HEAD_RE = re.compile(
    r"(\bnon-?goals?\b"
    r"|out of scope|извън\s+обхват"
    r"|какво\s+не\b"
    r"|what\s+(?:is|are|we|it)\s+(?:do\s+)?not\b"
    r"|\bне\s+(?:се\s+)?(?:строи|прави|правим|включва|влиза|покрива|пипаме|"
    r"мигрираме|разглежда)\w*"
    r"|\bняма\s+да\b)", re.I)
TASK_RE = re.compile(r"^#{2,4}\s*(?:задача|task|стъпка|step|phase|фаза)\s*(\d+)", re.I)
PLAN_DIR_RE = re.compile(r"(?:^|/)(plans?|specs?)/")
DOC_DIR_RE = re.compile(r"(?:^|/)(plans?|specs?|docs)/")
FLAG_RE = re.compile(
    r"(🔴|⚠️|✅|❌|⏸|паркиран|parked|blocked|блокир|отложен|deferred|open question|отворен въпрос)",
    re.I)


# `gh pr list` pages its answer. A repository with more open PRs than this
# returns exactly this many rows and says nothing about the rest — a silent cap,
# which is the one thing every other measurement here declares.
OPEN_PR_LIMIT = 200


FENCE_OPEN_RE = re.compile(r"^ {0,3}(?P<char>`{3,}|~{3,})(?P<info>.*)$")


def strip_fences(text):
    """Blank out fenced code blocks, keeping line numbering intact.

    A fence with a blank line inside is split by paragraph splitting, so the
    guard "does this paragraph start with ```" misses every chunk after the
    first. Sample checkboxes and the word "blocked" in a shell comment are then
    read as statements the plan makes about itself.

    Scanned line by line rather than matched with one regular expression,
    because CommonMark lets the CLOSING fence be LONGER than the opening one.
    A regex that backreferences the opening run fails to see ```` close ```,
    falls through to end-of-string, and silently blanks the whole rest of the
    document — every checkbox and every flag after the block disappears.
    """
    out, fence = [], None
    for line in text.split("\n"):
        if fence is None:
            m = FENCE_OPEN_RE.match(line)
            # a backtick fence's info string may not contain a backtick, or the
            # line is an inline code span rather than the start of a block
            if m and not (m.group("char")[0] == "`" and "`" in m.group("info")):
                fence = m.group("char")
                out.append("")
                continue
            out.append(line)
        else:
            out.append("")
            m = FENCE_OPEN_RE.match(line)
            # the closing fence is the same character, at least as long, and
            # carries nothing else on the line
            if (m and m.group("char")[0] == fence[0]
                    and len(m.group("char")) >= len(fence)
                    and not m.group("info").strip()):
                fence = None
    return "\n".join(out)


def parse_plan(path, text):
    """Pull the stated goal and the progress markers out of a plan document.

    This reads what the document CLAIMS about itself. It is not a measurement
    of the code: a plan can mark a task done while no commit implements it.
    """
    lines = text.splitlines()
    # Everything this function reads out of the document reads it with the fenced
    # blocks blanked out. Title, goal, checkboxes and flags all did — but the
    # numbered tasks and the title were taken from the RAW lines, so a plan that
    # documents its own heading syntax had the example headings counted as real
    # tasks, and `# Заглавие` inside a ```markdown block became the title.
    prose = strip_fences(text)
    prose_lines = prose.splitlines()
    title = next((l[2:].strip() for l in prose_lines if l.startswith("# ")),
                 path.split("/")[-1])

    # goal = first prose paragraph under the best-ranked goal heading
    def head_rank(head):
        if NEGATIVE_HEAD_RE.search(head):
            return None
        for i, group in enumerate(GOAL_HEADS):
            if any(re.search(rf"(?:^|\W){re.escape(g)}", head) for g in group):
                return i
        return None

    candidates, rank, buf = [], None, []

    def flush():
        nonlocal rank, buf
        if rank is not None and buf:
            candidates.append((rank, len(candidates), " ".join(buf)))
        buf = []

    for l in prose_lines:
        if l.startswith("#"):
            flush()
            rank = head_rank(l.lstrip("#").strip().lower())
            continue
        if rank is None:
            continue
        t = l.strip()
        # a goal stated as a numbered or bulleted list is still the goal; only
        # tables, quotes and checkbox rows are not prose about the goal
        if t.startswith(("|", ">")) or re.match(r"[-*+]\s*\[", t):
            flush()
            rank = None
            continue
        if t:
            buf.append(t)
        elif buf:
            flush()
            rank = None
    flush()

    # best heading wins; ties go to the one that appears first in the document
    goal = min(candidates)[2][:420] if candidates else ""

    # checkboxes are counted outside fenced blocks only: a plan that documents
    # the checkbox syntax must not inflate its own progress. `+` is a valid
    # markdown list marker alongside `-` and `*`.
    done = len(re.findall(r"^\s*[-*+]\s*\[[xX]\]", prose, re.M))
    todo = len(re.findall(r"^\s*[-*+]\s*\[\s\]", prose, re.M))

    tasks = []
    for l in prose_lines:
        m = TASK_RE.match(l)
        if m:
            head = l.lstrip("#").strip()
            tasks.append({
                "n": int(m.group(1)),
                "title": head[:120],
                "marked_done": bool(re.search(r"(✅|готов|done|приключ|complete)", head, re.I)),
            })

    # Flags are read per PARAGRAPH, not per line. Markdown wraps sentences, and a
    # single wrapped line reverses its own meaning when read out of context.
    flags = []
    for para in re.split(r"\n\s*\n", prose):
        body = " ".join(l.strip().lstrip("-*> ").strip() for l in para.splitlines()).strip()
        # table rows carry ✅/❌ as cell values, not as statements about the plan
        if body.startswith(("|", "#", "```")) or "|" in body[:4]:
            continue
        if len(body) > 12 and FLAG_RE.search(body):
            flags.append(body[:300] + ("…" if len(body) > 300 else ""))
        if len(flags) >= 6:
            break

    return {
        "path": path,
        "title": title[:140],
        "goal": goal,
        "checkboxes": {"done": done, "todo": todo},
        "tasks": tasks[:14],
        "tasks_done": sum(1 for t in tasks if t["marked_done"]),
        "flags": flags,
        "lines": len(lines),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--base", default="")
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args()

    repo = os.path.abspath(a.repo)
    if not os.path.isdir(os.path.join(repo, ".git")) and not git(repo, "rev-parse", "--git-dir"):
        sys.exit(f"{repo} is not a git repository")

    # --prune is mandatory: a branch deleted on the remote survives as a
    # remote-tracking ref and every sweep counts it as alive.
    fetch_ok = None
    warnings = []
    if not a.no_fetch:
        fetch_ok = git(repo, "fetch", "--prune", "origin", rc=True) == 0
        CMDS.append("git fetch --prune origin" + ("" if fetch_ok else "   # FAILED"))
    # Without a successful prune, a branch deleted on the remote survives as a
    # remote-tracking ref and is counted as alive. The page must say so rather
    # than present a stale ref as live work.
    pruned = fetch_ok is True
    if not pruned:
        warnings.append(
            "no prune this run (" + ("--no-fetch" if a.no_fetch else "fetch failed") +
            "): a branch deleted on the remote can still appear as live")

    # record the command that actually ran: with --base nothing is resolved,
    # and a page that lists a command nobody ran is not a derivation
    if a.base:
        base = a.base
        CMDS.append(f"# base given on the command line: --base {a.base}")
    else:
        base = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD") or "origin/main"
        CMDS.append("git symbolic-ref --short refs/remotes/origin/HEAD")
    base_sha = git(repo, "rev-parse", "--short", base)
    # An unresolvable base silently drops EVERY branch: merge-base returns ''
    # and each record is skipped. An empty page is not a finding, it is a bug.
    if not base_sha:
        sys.exit(f"base {base!r} does not resolve in {repo} — "
                 f"pass --base explicitly, or check that the remote exists")

    cutoff = datetime.now(timezone.utc) - timedelta(days=a.days)

    # every remote branch plus every local branch, so "written but never
    # pushed" shows up as its own state instead of vanishing
    fmt = "%(refname)\t%(refname:short)\t%(committerdate:iso8601-strict)\t%(authorname)\t%(objectname:short)"
    raw = git(repo, "for-each-ref", "--sort=-committerdate", f"--format={fmt}",
              "refs/heads", "refs/remotes/origin")
    CMDS.append("git for-each-ref --sort=-committerdate refs/heads refs/remotes/origin")

    base_key = base[len("origin/"):] if base.startswith("origin/") else base
    seen, branches = {}, []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) != 5:
            continue
        full, short, iso, author, sha = parts
        if short in (base, "origin", "origin/HEAD") or short.endswith("/HEAD"):
            continue
        try:
            when = datetime.fromisoformat(iso)
        except ValueError:
            continue
        key = short[len("origin/"):] if short.startswith("origin/") else short
        if key == base_key:
            continue
        # Merge the local and the remote copy BEFORE applying the window. A
        # pushed branch whose remote tip is older than the window would
        # otherwise register as local-only, and the page would call pushed work
        # "written and never pushed".
        rec = seen.setdefault(key, {"name": key, "local": False, "remote": False})
        if full.startswith("refs/remotes/"):
            rec["remote"] = True
        else:
            rec["local"] = True
        # keep the newest tip between the local and the remote copy
        if "when" not in rec or when > rec["when"]:
            # the date in UTC, not in the committer's timezone: `iso[:10]` is a
            # local calendar day, and two branches an hour apart in different
            # zones then read as a day apart
            rec.update(when=when, last_date=when.astimezone(timezone.utc).strftime("%Y-%m-%d"),
                       author=author, sha=sha, ref=short)

    # An open PR with recent activity is a branch someone is working on, even
    # when the tip has not moved. Filtering on committerdate alone drops a
    # branch exactly while it is under review — the moment a board is for.
    open_prs = {}
    if have_gh():
        out = subprocess.run(
            ["gh", "pr", "list", "--state", "open",
             "--limit", str(OPEN_PR_LIMIT),
             "--json", "headRefName,updatedAt"],
            cwd=repo, capture_output=True, text=True)
        ok = out.returncode == 0 and out.stdout.strip()
        rows = []
        if ok:
            try:
                rows = json.loads(out.stdout)
                for pr_row in rows:
                    open_prs[pr_row["headRefName"]] = pr_row["updatedAt"]
            except (json.JSONDecodeError, KeyError, TypeError):
                open_prs, rows, ok = {}, [], False
        CMDS.append(f"gh pr list --state open --limit {OPEN_PR_LIMIT} "
                    "--json headRefName,updatedAt" + ("" if ok else "   # FAILED"))
        if not ok:
            warnings.append("gh could not list open PRs: a branch whose tip is "
                            "older than the window is missing from this page")
        elif len(rows) >= OPEN_PR_LIMIT:
            # a full page is what a truncated one looks like from in here
            warnings.append(
                f"the open PR listing came back full at the --limit "
                f"{OPEN_PR_LIMIT} cap and may be truncated: a branch kept on "
                f"the page only by its PR can be missing")

    def in_window(rec):
        """Why this branch is on the page, or None to leave it off."""
        if rec["when"] >= cutoff:
            return "commit"
        stamp = open_prs.get(rec["name"])
        if stamp:
            try:
                if datetime.fromisoformat(stamp.replace("Z", "+00:00")) >= cutoff:
                    return "pr"
            except ValueError:
                pass
        return None

    # the window is a question about the branch, not about one of its two refs
    for key in list(seen):
        why = in_window(seen[key])
        if why is None:
            del seen[key]
        else:
            seen[key]["in_window_by"] = why

    # A per-branch `gh pr list --head` that fails is the one thing that could
    # have caught a squash merge. Swallowing it lets the page print "няма PR"
    # as a fact about a branch whose PR was never read.
    pr_lookup_failed = False

    for rec in seen.values():
        ref = rec["ref"]
        mb = git(repo, "merge-base", base, ref)
        if not mb:
            continue
        rng = f"{mb}..{ref}"

        # own commits only — measured from this branch's own merge-base, never
        # from `base..branch`, which a squash merge on base turns into noise
        log = git(repo, "log", "--format=%h\t%an\t%ad\t%s", "--date=short", rng)
        commits = []
        for l in log.splitlines():
            p = l.split("\t", 3)
            if len(p) == 4:
                commits.append({"sha": p[0], "author": p[1], "date": p[2], "subject": p[3]})

        names = git(repo, "diff", "--name-only", rng).splitlines()
        # paths that still exist on the branch tip; `git show <ref>:<path>`
        # fails for anything the branch deleted, and that failure is silent
        alive = set(git(repo, "diff", "--name-only", "--diff-filter=d", rng).splitlines())
        stat = git(repo, "diff", "--shortstat", rng)
        ins = dele = 0
        for token, field in (("insertion", "ins"), ("deletion", "del")):
            for chunk in stat.split(","):
                if token in chunk:
                    n = int(chunk.strip().split()[0])
                    if field == "ins":
                        ins = n
                    else:
                        dele = n

        # Group by each file's DIRECTORY, capped at two segments. Joining the
        # first two path segments instead labelled every file at depth 0 or 1 a
        # directory: the real board printed `dirs: CLAUDE.md (1), README.md (1)`.
        # A file at the repo root is reported under ".", git's name for it.
        dirs = {}
        for n in names:
            parts = n.split("/")[:-1]
            top = "/".join(parts[:2]) if parts else "."
            dirs[top] = dirs.get(top, 0) + 1
        top_dirs = sorted(dirs.items(), key=lambda kv: -kv[1])[:6]

        behind = git(repo, "rev-list", "--count", f"{ref}..{base}") or "0"

        pr = None
        if have_gh():
            out = subprocess.run(
                ["gh", "pr", "list", "--head", rec["name"], "--state", "all",
                 "--json", "number,state,title,isDraft,url", "--limit", "10"],
                cwd=repo, capture_output=True, text=True)
            if out.returncode != 0:
                pr_lookup_failed = True
            elif out.stdout.strip():
                try:
                    arr = json.loads(out.stdout)
                    # `gh` returns newest first, and a branch can carry more than
                    # one PR: merged by #1, then a follow-up #2 opened and closed.
                    # Taking the newest reported that branch as never landed —
                    # and the merged PR is the ONLY thing that catches a squash.
                    pr = next((x for x in arr if x.get("state") == "MERGED"), None)
                    if pr is None:
                        pr = next((x for x in arr if x.get("state") == "OPEN"), None)
                    if pr is None:
                        pr = arr[0] if arr else None
                except json.JSONDecodeError:
                    pr = None
                    pr_lookup_failed = True

        # "Landed" has exactly two admissible sources: the tip is an ancestor of
        # the base, or a PR for this branch is merged. A squash merge rewrites
        # the commits, so --is-ancestor alone reports already-landed work as
        # open. The diff is never evidence — an identical tree can also mean a
        # branch that changed nothing.
        is_ancestor = git(repo, "merge-base", "--is-ancestor", ref, base, rc=True) == 0
        pr_merged = bool(pr and pr.get("state") == "MERGED")
        landed_by = "ancestor" if is_ancestor else ("pr" if pr_merged else None)
        merged = landed_by is not None

        # the branch's own plan/spec documents — what it says it is trying to do
        plans = []
        docs = [n for n in names
                if n.endswith(".md") and n in alive and DOC_DIR_RE.search(n)]
        # A plan or a spec outranks any other doc the branch happened to touch.
        # The directory may sit at the repo root, so anchor on start-or-slash;
        # `/(plans?|specs?)/` alone misses a top-level `plans/`.
        docs.sort(key=lambda n: 0 if PLAN_DIR_RE.search(n) else 1)
        for path in docs[:3]:
            body = git(repo, "show", f"{ref}:{path}")
            if body:
                doc = parse_plan(path, body)
                # the page must be able to say "this branch carries no plan of
                # its own" — an incidental doc is not a stand-in for one
                doc["kind"] = "plan" if PLAN_DIR_RE.search(path) else "incidental"
                plans.append(doc)

        # A branch with no commits of its own is not work in flight: it points
        # into the base, whether it is a release pointer, a merged feature
        # branch or one nobody ever started. git cannot tell those apart, so
        # classify by shape and let the page group them. Nothing is dropped —
        # "branched and never started" is a finding, not noise.
        role = "work" if commits else "pointer"

        branches.append({
            "name": rec["name"],
            "role": role,
            "in_window_by": rec["in_window_by"],
            "plans": plans,
            "author": rec["author"],
            "last_date": rec["last_date"],
            "tip": rec["sha"],
            # local_only is a claim about the WORK: nobody but its author can
            # see it. There is deliberately no remote_only counterpart — "on
            # origin but not checked out here" describes the reader's clone,
            # not the branch, and a field like that reads as a measurement.
            "local_only": rec["local"] and not rec["remote"],
            "merge_base": mb[:9],
            "ahead": len(commits),
            "behind": int(behind or 0),
            "merged": merged,
            "landed_by": landed_by,
            "files": len(names),
            "insertions": ins,
            "deletions": dele,
            "top_dirs": [{"path": d, "files": c} for d, c in top_dirs],
            "commits": commits[:12],
            "pr": pr,
        })

    # Ordered by the absolute instant, not by the printed date. SKILL.md picks
    # recency because it "needs no judgement" — a string sort over local
    # calendar days reverses it across timezones.
    order = {rec["name"]: rec["when"] for rec in seen.values()}
    branches.sort(key=lambda b: order[b["name"]], reverse=True)
    # these ran once per branch; list them only if there was a branch to run on
    if branches:
        if have_gh():
            CMDS.append("gh pr list --head <branch> --state all"
                        + ("   # FAILED" if pr_lookup_failed else ""))
            if pr_lookup_failed:
                warnings.append(
                    "gh could not read PR state for at least one branch: a squash "
                    "merge is invisible here, so \"no PR\" is not a measurement")
        CMDS.extend([
            "git merge-base <base> <branch>",
            "git log --format=... <merge-base>..<branch>",
            "git diff --name-only [--diff-filter=d] <merge-base>..<branch>",
            "git diff --shortstat <merge-base>..<branch>",
            "git rev-list --count <branch>..<base>",
            "git merge-base --is-ancestor <branch> <base>",
            "git show <branch>:<plan-path>",
        ])

    json.dump({
        "meta": {
            "repo": repo,
            "repo_name": os.path.basename(repo),
            "base": base,
            "base_sha": base_sha,
            "days": a.days,
            "generated": datetime.now().strftime("%d.%m.%Y, %H:%M"),
            "gh": have_gh(),
            "fetched": fetch_ok,
            "pruned": pruned,
            "warnings": warnings,
            "commands": CMDS,
        },
        "branches": branches,
    }, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
