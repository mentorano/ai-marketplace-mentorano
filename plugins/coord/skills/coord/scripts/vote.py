#!/usr/bin/env python3
"""Ask Codex one question and parse the answer contract; used by coord's votes
(procedures/votes.md) and Codex reviews (procedures/review-and-models.md).

Usage: vote.py codex <prompt file> <out dir> [--timeout 300] [--cwd DIR]
               [--effort high] [--contract vote|review]
Prints one JSON line per voter. Failures are data (status "missing" + why), exit code 0.
Own timeout (no `timeout` binary needed); the whole process group is killed on timeout.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading

VOTE_RE = re.compile(r"^\W*Vote:\s*([A-Za-z0-9]+)\b(?:\s*[—–-]+\s*(.*?))?\W*$")
CODEX_MODEL = "gpt-6-astra"  # the owner's choice; COORD_CODEX_MODEL overrides
LOGIN_RE = re.compile(r"not logged in|please (?:re-?)?log ?in|log ?in required|unauthori[sz]ed|\b401\b")
VERDICT_RE = re.compile(r"^\W*Verdict:\s*(approve|changes)\b", re.IGNORECASE)


def find_bin(name):
    override = os.environ.get(f"COORD_{name.upper()}_BIN")
    if override:
        return override
    found = shutil.which(name)
    if found:
        return found
    home_bin = os.path.expanduser(f"~/.{name}/bin/{name}")
    return home_bin if os.path.exists(home_bin) else name


def command(voter, prompt_file, out_file, cwd, effort):
    cmd = [find_bin(voter), "exec", "-m", os.environ.get("COORD_CODEX_MODEL", CODEX_MODEL),
           "-c", f"model_reasoning_effort={effort}", "-s", "read-only",
           "--skip-git-repo-check", "-C", cwd, "-o", out_file, "-"]
    return cmd, open(prompt_file, "rb")


def classify(rc, log_text):
    low = log_text.lower()
    if rc == 127 or "command not found" in low:
        return "missing-binary"
    if "usage limit" in low:
        return "usage-limit"
    if LOGIN_RE.search(low):
        return "login"
    return f"exit {rc}"


def parse(text, contract):
    for line in text.splitlines():
        if contract == "review":
            m = VERDICT_RE.match(line)
            if m:
                return m.group(1).lower(), ""
        else:
            m = VOTE_RE.match(line)
            if m:
                return m.group(1), (m.group(2) or "").strip()
    return None, None


def run_one(voter, prompt_file, out_dir, timeout, cwd, effort, contract):
    out_file = os.path.join(out_dir, f"{voter}.out")
    log_file = os.path.join(out_dir, f"{voter}.log")
    res = {"voter": voter, "status": "missing", "answer": None, "reason": None, "why": None, "log": log_file}
    try:
        cmd, stdin = command(voter, prompt_file, out_file, cwd, effort)
    except OSError:
        res["why"] = "missing-binary"
        return res
    with open(log_file, "wb") as log:
        try:
            proc = subprocess.Popen(cmd, stdin=stdin, stdout=log, stderr=log, cwd=cwd, start_new_session=True)
        except (FileNotFoundError, PermissionError):
            res["why"] = "missing-binary"
            return res
        try:
            proc.communicate(timeout=timeout)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:  # the group exited between the timeout and the kill
                pass
            proc.communicate()
            res["why"] = "timeout"
            return res
        finally:
            if hasattr(stdin, "close"):
                stdin.close()
    with open(os.path.join(out_dir, f"{voter}.exit"), "w") as fh:
        fh.write(str(rc))
    log_text = open(log_file, errors="replace").read()
    answer_text = open(out_file, errors="replace").read() if os.path.exists(out_file) else ""
    if rc != 0:
        res["why"] = classify(rc, log_text + answer_text)
    elif not answer_text.strip():
        res["why"] = "empty"
    else:
        answer, reason = parse(answer_text, contract)
        if answer is None:
            res["why"] = "invalid"
        else:
            res.update(status="voted", answer=answer, reason=reason)
    return res


def main(argv):
    args = list(argv)
    opts = {"--timeout": "300", "--cwd": os.getcwd(), "--effort": "high", "--contract": "vote"}
    pos = []
    while args:
        a = args.pop(0)
        if a in opts:
            if not args:
                sys.exit(f"usage: {a} needs a value")
            opts[a] = args.pop(0)
        else:
            pos.append(a)
    if len(pos) != 3:
        sys.exit(__doc__)
    voters, prompt_file, out_dir = pos[0].split(","), os.path.abspath(pos[1]), pos[2]
    if voters != ["codex"]:
        sys.exit("voters: codex (grok was dropped; the other voters are Opus and Fable agents)")
    os.makedirs(out_dir, exist_ok=True)
    results = {}

    def work(v):
        results[v] = run_one(v, prompt_file, out_dir, int(opts["--timeout"]), opts["--cwd"],
                             opts["--effort"], opts["--contract"])

    threads = [threading.Thread(target=work, args=(v,)) for v in voters]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for v in voters:
        print(json.dumps(results[v], ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
