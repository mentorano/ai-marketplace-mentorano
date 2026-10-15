#!/usr/bin/env bash
# Print the re-derivable state of a coord sprint. Read-only unless --fetch is given
# (which only runs `git fetch`, updating remote-tracking refs).
#
# Usage: derive-state.sh <repo> [--config <path>] [--fetch] [--log N]
# Config default: <repo>/.coord/project.md; keys read: remote, integration_branch,
# lane_prefixes, migration_heads_cmd, migration_current_cmd, docker_filter, ci_workflow.
set -uo pipefail
export GIT_OPTIONAL_LOCKS=0  # never let status/diff rewrite the index

usage() { echo "Usage: $(basename "$0") <repo> [--config <path>] [--fetch] [--log N]" >&2; exit 2; }
[ $# -ge 1 ] || usage
REPO="${1/#\~/$HOME}"; shift
CONFIG="" FETCH=0 LOGN=15
while [ $# -gt 0 ]; do
  case "$1" in
    --config) [ $# -ge 2 ] || usage; CONFIG="${2/#\~/$HOME}"; shift 2 ;;
    --fetch) FETCH=1; shift ;;
    --log) [ $# -ge 2 ] || usage; LOGN="$2"; shift 2 ;;
    *) usage ;;
  esac
done
[ -d "$REPO" ] || { echo "No such repo: $REPO" >&2; exit 2; }
REPO="$(cd "$REPO" && pwd)"  # absolute, so cwd-based comparisons below are exact, not string prefixes
[ -n "$CONFIG" ] || CONFIG="$REPO/.coord/project.md"

key() {  # first `key: value` line in the config, trailing ` # comment` stripped; empty if absent
  [ -f "$CONFIG" ] || return 0
  sed -n "s/^$1:[[:space:]]*//p" "$CONFIG" | head -1 | sed -e 's/[[:space:]]*#.*$//' -e 's/[[:space:]]*$//'
}

REMOTE="$(key remote)"; REMOTE="${REMOTE:-origin}"
INTEG="$(key integration_branch)"
if [ -z "$INTEG" ]; then
  INTEG="$(git -C "$REPO" symbolic-ref --short "refs/remotes/$REMOTE/HEAD" 2>/dev/null | sed "s#^$REMOTE/##")"
  INTEG="${INTEG:-main}"
  echo "(no config at $CONFIG - integration branch guessed: $INTEG)"
fi
PREFIXES="$(key lane_prefixes)"
HEADS_CMD="$(key migration_heads_cmd)"
CURRENT_CMD="$(key migration_current_cmd)"
DOCKER_FILTER="$(key docker_filter)"
CI_WORKFLOW="$(key ci_workflow)"
T="$REMOTE/$INTEG"

section() { printf '\n== %s ==\n' "$1"; }

section "fetch"
if [ "$FETCH" = 1 ]; then
  git -C "$REPO" fetch -q "$REMOTE" && echo "fetched $REMOTE"
else
  fh="$REPO/.git/FETCH_HEAD"; [ -f "$fh" ] || fh="$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)/FETCH_HEAD"
  if [ -f "$fh" ]; then
    mtime=$(stat -f %m "$fh" 2>/dev/null || stat -c %Y "$fh" 2>/dev/null || echo 0)
    case "$mtime" in ''|*[!0-9]*) mtime=0 ;; esac
    age=$(( ( $(date +%s) - mtime ) / 60 ))
    echo "not fetched (last fetch ${age} min ago); pass --fetch for current remote refs"
  else
    echo "not fetched; pass --fetch"
  fi
fi

section "primary checkout"
git -C "$REPO" status -sb | head -1
staged=$(git -C "$REPO" diff --cached --name-only | wc -l | tr -d ' ')
GITDIR="$(git -C "$REPO" rev-parse --absolute-git-dir)"
[ -f "$GITDIR/MERGE_HEAD" ] && echo "MERGE IN PROGRESS: $(cat "$GITDIR/MERGE_HEAD" | cut -c1-9) staged_files=$staged - finish or abort before any other commit"
[ "$staged" != 0 ] && echo "staged files: $staged"
git -C "$REPO" status --porcelain | grep -v '^??' | head -5
unpushed=$(git -C "$REPO" rev-list --count "$T..$INTEG" 2>/dev/null || echo 0)
if [ "$unpushed" != 0 ]; then
  echo "!! LOCAL $INTEG IS $unpushed COMMITS AHEAD OF $T - unpushed work (a predecessor's batch?). Verify it yourself before pushing:"
  git -C "$REPO" log --first-parent --format='   %h %s' "$T..$INTEG" | cut -c1-150
fi
# Test/verification processes whose cwd is inside the checkout (background shells survive /clear).
# pgrep exits 1 on no match and >= 2 when it cannot list processes (e.g. a sandbox) - never a silent all-clear.
pids=$(pgrep -f 'pytest|playwright|vitest|alembic' 2>/dev/null); rc=$?
[ "$rc" -le 1 ] || echo "!! process scan unavailable (pgrep exit $rc) - cannot check for test runners in the checkout"
for pid in $pids; do
  cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')
  comm=$(ps -o comm= -p "$pid" 2>/dev/null); case "$comm" in *zsh|*bash|*sh) continue;; esac
  case "$cwd" in "$REPO"|"$REPO"/*) echo "!! RUNNING in checkout: pid $pid $(ps -o etime=,command= -p "$pid" | cut -c1-110)";; esac
done

section "first-parent log of $T (last $LOGN)"
git -C "$REPO" log --first-parent --format='%h %cr %s' -n "$LOGN" "$T" 2>/dev/null | cut -c1-160 || echo "no ref $T"

section "branches ahead of $T"
patterns=()
if [ -n "$PREFIXES" ]; then
  for p in $PREFIXES; do patterns+=("$REMOTE/${p%/}/*"); done
else
  patterns=("$REMOTE/*")
fi
found=0
while read -r b; do
  [ -z "$b" ] && continue
  case "$b" in "$T"|"$REMOTE/HEAD"|"$REMOTE") continue ;; esac
  n=$(git -C "$REPO" rev-list --count "$T..$b" 2>/dev/null || echo 0)
  if [ "$n" != 0 ]; then
    behind=$(git -C "$REPO" rev-list --count "$b..$T" 2>/dev/null || echo "?")
    echo "$b ahead=$n behind=$behind $(git -C "$REPO" log -1 --format='%h %cr' "$b")"
    found=1
  fi
done < <(git -C "$REPO" branch -r --format='%(refname:short)' --list "${patterns[@]}")
[ "$found" = 0 ] && echo "(none)"

section "worktrees"
# --porcelain (one "key value" pair per line, blank line between entries) survives paths with spaces;
# the plain `worktree list` table does not, since it is parsed by word-splitting.
path="" sha="" br="" prunable=0 pr=0
while IFS= read -r line; do
  case "$line" in
    "worktree "*) path="${line#worktree }" ;;
    "HEAD "*) sha="${line#HEAD }" ;;
    "branch "*) br="${line#branch }" ;;
    detached) br="(detached)" ;;
    prunable*) prunable=1 ;;
    "")
      if [ -n "$path" ]; then
        if [ "$prunable" = 1 ]; then
          pr=$((pr + 1))
        else
          dirty=$(git -C "$path" status --porcelain 2>/dev/null | grep -vc '^??')
          echo "$path ${sha:0:9} $br dirty=$dirty"
        fi
      fi
      path="" sha="" br="" prunable=0 ;;
  esac
done < <(git -C "$REPO" worktree list --porcelain)
[ "$pr" != 0 ] && echo "($pr prunable worktrees not shown)"

section "CI"
if command -v gh >/dev/null; then
  args=(run list --branch "$INTEG" --limit 3)
  [ -n "$CI_WORKFLOW" ] && args+=(--workflow "$CI_WORKFLOW")
  (cd "$REPO" && gh "${args[@]}" 2>&1 | head -5)
else
  echo "gh not installed"
fi

section "migrations"
if [ -n "$HEADS_CMD" ]; then
  echo "heads:";   (cd "$REPO" && bash -c "$HEADS_CMD" 2>&1 | tail -5)
  if [ -n "$CURRENT_CMD" ]; then echo "current:"; (cd "$REPO" && bash -c "$CURRENT_CMD" 2>&1 | tail -3); fi
else
  echo "(no migration_heads_cmd configured)"
fi

section "containers"
if command -v docker >/dev/null; then
  if [ -n "$DOCKER_FILTER" ]; then
    docker ps -a --format '{{.Names}}\t{{.Status}}\t{{.Ports}}' 2>&1 | grep -- "$DOCKER_FILTER" || echo "(none matching $DOCKER_FILTER)"
  else
    docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}' 2>&1 | head -20
  fi
else
  echo "docker not installed"
fi
