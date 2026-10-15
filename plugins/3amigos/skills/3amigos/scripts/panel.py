#!/usr/bin/env python3
"""Run the external voter of a 3amigos panel (Codex) on one task with a JSON contract.

Usage: panel.py --task TASK.md --input DATA.md --out DIR [--voters codex]
                [--deadline 300] [--effort medium] [--require KEY=N ...]
       panel.py --check ANSWER.json [--require KEY=N ...]

The task and the data are inlined into ONE prompt file, so the voter never has to read files
itself. Each voter's answer must be one JSON object; --require KEY=N checks that answer[KEY] is a list of exactly N items (N=* any length).
Prints one JSON line per voter as soon as that voter finishes (completion order):
{"voter","status":"ok|missing","why","file"}. Failures are data, exit code 0; a bad command line
exits 2 before any voter runs. One retry per voter, but none after the deadline, a usage limit or
a missing binary. Each voter runs in its own empty work dir <out>/work-<voter>/, so it never sees
another voter's answer. --check validates one answer file (an Opus or Fable voter) against the
same --require rules, runs no voter and prints the same status line. --deadline (alias --timeout) is the voter's total time,
retry included; a voter still running then is killed and reported missing with why "deadline",
so the caller can start a Fable voter in its place instead of waiting.
"""
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

VOTERS = ("codex",)
CODEX_MODEL = os.environ.get("AMIGOS_CODEX_MODEL", "gpt-6-astra")


def find_bin(name):
    for cand in (shutil.which(name), os.path.expanduser(f"~/.{name}/bin/{name}"),
                 os.path.expanduser(f"~/.local/bin/{name}")):
        if cand and os.path.exists(cand):
            return cand
    return None


def command(voter, out_dir, work, effort):
    """The voter's command line; the prompt goes on stdin and the answer to <out>/<voter>.final.txt."""
    return [find_bin("codex"), "exec", "-m", CODEX_MODEL, "-c", f"model_reasoning_effort={effort}",
            "-s", "read-only", "--skip-git-repo-check", "-C", work,
            "-o", os.path.join(out_dir, f"{voter}.final.txt"), "-"]


def extract(text):
    """Largest dict that decodes from any '{' in the ORIGINAL text (strings and fences are respected)."""
    dec, best, best_len = json.JSONDecoder(), None, -1
    for m in re.finditer(r"\{", text):
        try:
            obj, end = dec.raw_decode(text, m.start())
        except ValueError:
            continue
        if isinstance(obj, dict) and end - m.start() > best_len:
            best, best_len = obj, end - m.start()
    return best


def check(obj, require):
    if not isinstance(obj, dict):
        return "no JSON object"
    for key, n in require:
        val = obj.get(key)
        if not isinstance(val, list):
            return f"missing list '{key}'"
        if n != "*" and len(val) != int(n):
            return f"'{key}' has {len(val)} items, expected {n}"
    return ""


def require_arg(text):
    key, sep, n = text.partition("=")
    if not key or not sep or not (n == "*" or re.fullmatch(r"[0-9]+", n)):
        raise argparse.ArgumentTypeError(f"expected KEY=N with N a non-negative integer or *, got {text!r}")
    return key, n


def voters_arg(text):
    names = text.split(",")
    bad = [n for n in names if n not in VOTERS]
    if bad or len(set(names)) != len(names):
        raise argparse.ArgumentTypeError(f"voters are a comma list of {', '.join(VOTERS)} without repeats, got {text!r}")
    return names


def limit_hit(*paths):
    for path in paths:
        if os.path.exists(path):
            low = open(path, errors="replace").read().lower()
            if "usage limit" in low or "rate limit" in low:
                return True
    return False


def work_dir(out_dir, voter):
    """An empty directory of the voter's own, so its cwd shows no other voter's files."""
    work = os.path.join(out_dir, f"work-{voter}")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    return work


def run_once(voter, prompt, out_dir, timeout, effort):
    """One attempt. Returns (obj, why); previous final/json files of this voter are removed first."""
    for suffix in ("final.txt", "json"):
        try:
            os.remove(os.path.join(out_dir, f"{voter}.{suffix}"))
        except FileNotFoundError:
            pass
    work = work_dir(out_dir, voter)
    cmd = command(voter, out_dir, work, effort)
    if not cmd[0]:
        return None, "missing-binary"
    log = stdin = None
    try:
        log = open(os.path.join(out_dir, f"{voter}.log"), "wb")
        stdin = open(prompt, "rb")
        proc = subprocess.Popen(cmd, stdin=stdin, stdout=log, stderr=log, cwd=work, start_new_session=True)
        try:
            proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:  # the group already exited
                pass
            proc.communicate()
            return None, "deadline"
        final = os.path.join(out_dir, f"{voter}.final.txt")
        text = open(final, errors="replace").read() if os.path.exists(final) else ""
        obj = extract(text) if proc.returncode == 0 else None
        if obj is None:  # any failed answer: a usage limit (log or final file) wins, never retried
            if limit_hit(os.path.join(out_dir, f"{voter}.log"), final):
                return None, "usage-limit"
            return None, f"exit {proc.returncode}" if proc.returncode != 0 else "empty" if not text.strip() else ""
        return obj, ""
    except OSError as exc:
        return None, f"launch error: {type(exc).__name__}"
    finally:
        if log:
            log.close()
        if stdin:
            stdin.close()


def run(voter, prompt, out_dir, deadline, effort, require):
    why = ""
    end = time.monotonic() + deadline
    for attempt in (1, 2):
        left = end - time.monotonic()
        if left <= 0:
            why = "deadline"
            break
        obj, why = run_once(voter, prompt, out_dir, left, effort)
        if not why:
            why = check(obj, require)
        if not why:
            path = os.path.join(out_dir, f"{voter}.json")
            with open(path, "w") as fh:
                json.dump(obj, fh, ensure_ascii=False, indent=1)
            return {"voter": voter, "status": "ok", "why": "", "file": path}
        if why in ("deadline", "missing-binary", "usage-limit"):
            break
    return {"voter": voter, "status": "missing", "why": why, "file": ""}


def check_file(path, require):
    """Status line for an answer file written by an Opus or Fable voter; the voter is the file stem."""
    path = os.path.abspath(path)
    voter = os.path.splitext(os.path.basename(path))[0]
    try:
        with open(path) as fh:
            obj = json.load(fh)
    except FileNotFoundError:
        why = "no file"
    except (OSError, ValueError) as exc:
        why = f"bad JSON: {type(exc).__name__}"
    else:
        why = check(obj, require)
    return {"voter": voter, "status": "missing" if why else "ok", "why": why, "file": "" if why else path}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task")
    ap.add_argument("--input")
    ap.add_argument("--out")
    ap.add_argument("--voters", type=voters_arg, default=list(VOTERS))
    ap.add_argument("--deadline", "--timeout", dest="deadline", type=int, default=300)
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--require", type=require_arg, action="append", default=[])
    ap.add_argument("--check", metavar="ANSWER.json", help="validate one answer file; run no voter")
    a = ap.parse_args()
    if a.check:
        print(json.dumps(check_file(a.check, a.require), ensure_ascii=False))
        return 0
    if not (a.task and a.input and a.out):
        ap.error("--task, --input and --out are required unless --check is given")
    out_dir = os.path.abspath(a.out)
    os.makedirs(out_dir, exist_ok=True)
    prompt = os.path.join(out_dir, "prompt.full.md")
    tmp = f"{prompt}.{os.getpid()}"  # one panel.py per voter may share out_dir: replace atomically
    with open(tmp, "w") as fh:
        fh.write(open(a.task).read().rstrip() + "\n\nAll the data is below; do not read any files.\n\n"
                 "=== DATA ===\n" + open(a.input).read())
    os.replace(tmp, prompt)
    require = a.require
    lock = threading.Lock()

    def work(v):
        try:
            res = run(v, prompt, out_dir, a.deadline, a.effort, require)
        except Exception as exc:  # a voter must always produce a result line
            res = {"voter": v, "status": "missing", "why": f"error: {type(exc).__name__}", "file": ""}
        with lock:
            print(json.dumps(res, ensure_ascii=False), flush=True)

    threads = [threading.Thread(target=work, args=(v,)) for v in a.voters]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    sys.exit(main())
