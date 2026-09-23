"""Build throwaway git repositories for the collector tests.

Every fixture is a real repository with a real bare `origin`, because the bugs
these tests pin down only appear in real topologies: a squash merge, a remote
ref deleted by somebody else, a branch whose two copies disagree about dates.
A mock of `git` would reproduce the assumptions instead of the behaviour.
"""
import json
import os
import subprocess
import sys

# BB_COLLECT lets the suite run against another copy of the collector. It is
# how the tests were shown to fail against the version before the fixes: a test
# that has never been red is not evidence of anything.
COLLECT = os.environ.get("BB_COLLECT") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "plugins", "branch-board", "skills", "branch-board", "collect.py")


def run(cwd, *args, env=None):
    e = dict(os.environ)
    e.update({"GIT_AUTHOR_NAME": "Tester", "GIT_AUTHOR_EMAIL": "t@t.t",
              "GIT_COMMITTER_NAME": "Tester", "GIT_COMMITTER_EMAIL": "t@t.t"})
    if env:
        e.update(env)
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=e)
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} -> {p.stderr.strip()}")
    return p.stdout.strip()


def write(repo, path, body):
    full = os.path.join(repo, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(body)


def commit(repo, msg, when=None):
    run(repo, "git", "add", "-A")
    env = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when} if when else None
    run(repo, "git", "commit", "-q", "-m", msg, env=env)


def new_repo(tmp, name="lab"):
    """A repo with one commit on `main`, pushed to a bare origin with HEAD set."""
    origin = os.path.join(tmp, f"{name}-origin.git")
    repo = os.path.join(tmp, name)
    run(tmp, "git", "init", "-q", "--bare", origin)
    run(tmp, "git", "init", "-q", repo)
    run(repo, "git", "symbolic-ref", "HEAD", "refs/heads/main")
    write(repo, "a.txt", "base\n")
    commit(repo, "base 1")
    run(repo, "git", "remote", "add", "origin", origin)
    run(repo, "git", "push", "-q", "-u", "origin", "main")
    run(repo, "git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    return repo, origin


STUBS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stubs")


def collect(repo, *extra, gh_stub="gh-none", expect_rc=0, env_extra=None):
    """Run the collector and return the parsed JSON (or the stderr on failure).

    A stub `gh` always goes first on PATH. Without it the tests would ask the
    real GitHub about branch names that only exist in a temp directory, and the
    answer would depend on the machine.
    """
    env = dict(os.environ)
    env["PATH"] = os.path.join(STUBS, gh_stub) + os.pathsep + env["PATH"]
    if env_extra:
        env.update(env_extra)
    p = subprocess.run([sys.executable, COLLECT, repo, "--days", "7", *extra],
                       capture_output=True, text=True, env=env)
    assert p.returncode == expect_rc, f"rc={p.returncode} stderr={p.stderr}"
    if p.returncode != 0:
        return p.stderr
    return json.loads(p.stdout)


def branch(data, name):
    for b in data["branches"]:
        if b["name"] == name:
            return b
    raise AssertionError(f"branch {name!r} not in {[b['name'] for b in data['branches']]}")
