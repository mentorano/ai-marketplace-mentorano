#!/usr/bin/env bash
#
# Starts a new background Claude Code session with Remote Control in the current repository.
# The name is <slug>-<YYYYMMDD>-rc<N>, where N is the first number not yet used for this
# slug and this date — neither by a live session nor by a stopped one (transcripts keep
# the name as "customTitle").
#
# Usage:  start.sh [--dry-run] [--model <model>] [--effort <level>] [<slug>]
#         (any order)
#   --dry-run          only prints the name, starts nothing
#   --model <model>    the session's model, default opus
#   --effort <level>   the session's effort (low, medium, high, xhigh, max), default high
#   <slug>             short repository name, [a-z0-9] only; derived from the git root if omitted
#
# BG_CLAUDE_RC_LOCK_WAIT and BG_CLAUDE_RC_URL_WAIT (seconds, default 30 and 20) shorten the
# waits; the tests use them.
#
set -euo pipefail

die() { echo "start.sh: $*" >&2; exit 1; }

# `claude` colours its output even without a TTY: the id comes as `\e[36m79e56fd5\e[39m`.
strip_ansi() { sed $'s/\x1b\\[[0-9;?]*[A-Za-z]//g'; }

dry_run=0
slug=""
model="opus"
effort="high"
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry_run=1 ;;
    --model) [ $# -ge 2 ] && [ -n "$2" ] || die "--model needs a value"; model="$2"; shift ;;
    --model=*) model="${1#--model=}"; [ -n "$model" ] || die "--model needs a value" ;;
    --effort) [ $# -ge 2 ] && [ -n "$2" ] || die "--effort needs a value"; effort="$2"; shift ;;
    --effort=*) effort="${1#--effort=}"; [ -n "$effort" ] || die "--effort needs a value" ;;
    -*) die "unknown option: $1" ;;
    *) [ -z "$slug" ] || die "more than one slug: $slug and $1"; slug="$1" ;;
  esac
  shift
done
case "$effort" in
  low|medium|high|xhigh|max) ;;
  *) die "unknown effort: '$effort' — low, medium, high, xhigh or max" ;;
esac

command -v claude >/dev/null || die "claude is not on PATH"
command -v jq >/dev/null || die "jq is missing — without it the live session names cannot be read"

root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# my-web-app → mwa; data_pipeline → dp; claude → claude (up to 8 characters).
derive_slug() {
  local base="$1"
  base="${base#"${base%%[!.]*}"}"  # drop leading dots (.claude → claude)
  if [[ "$base" == *[-_]* ]]; then
    printf '%s' "$base" | tr '_' '-' | awk -F- '{s=""; for (i=1;i<=NF;i++) if ($i!="") s=s substr($i,1,1); print tolower(s)}'
  else
    printf '%s' "$base" | cut -c1-8 | tr '[:upper:]' '[:lower:]'
  fi
}

[ -n "$slug" ] || slug="$(derive_slug "$(basename "$root")")"
[[ "$slug" =~ ^[a-z0-9]+$ ]] || die "the slug must be [a-z0-9] only, got: '$slug' — pass it explicitly"

today="$(date +%Y-%m-%d)"          # one date for the name and for the transcript search
prefix="$slug-${today//-/}-rc"

# Live sessions (all repositories) plus the names in the transcripts of all projects.
# The name carries the start date, so it can only be in a transcript touched today or later —
# only those are read (all transcripts are gigabytes and grepping them takes minutes).
# A failed `claude agents --json` stops the script: without the live names the choice is blind.
used_names() {
  local live
  live="$(claude agents --json)" || die "claude agents --json did not answer"
  printf '%s\n' "$live" | jq -r '.[].name // empty' || die "claude agents --json did not return JSON"
  find "$HOME/.claude/projects" -name '*.jsonl' -newermt "$today" -print0 2>/dev/null \
    | xargs -0 command grep -hoE "\"customTitle\":\"$prefix[0-9]+\"" 2>/dev/null \
    | sed -E 's/.*:"(.*)"/\1/' || true
}

# Choosing the number and starting the session run under a lock, so two parallel starts
# never take the same name.
lock="${TMPDIR:-/tmp}/bg-claude-rc.lock"
if [ "$dry_run" = 0 ]; then
  wait_s="${BG_CLAUDE_RC_LOCK_WAIT:-30}"
  locked=0
  for _ in $(seq 1 "$wait_s"); do mkdir "$lock" 2>/dev/null && { locked=1; break; }; sleep 1; done
  [ "$locked" = 1 ] || die "the lock $lock has been held for over $wait_s s — if no session is starting, remove it: rmdir $lock"
  trap 'rmdir "$lock" 2>/dev/null || true' EXIT
fi

used="$(used_names | sort -u)"
n=1
while command grep -qxF -- "$prefix$n" <<<"$used"; do n=$((n + 1)); done
name="$prefix$n"

if [ "$dry_run" = 1 ]; then
  echo "name=$name"
  echo "model=$model"
  echo "effort=$effort"
  exit 0
fi

cd "$root"
rc=0
out="$(claude --bg --remote-control "$name" -n "$name" --model "$model" --effort "$effort" 2>&1)" || rc=$?
printf '%s\n' "$out"
[ "$rc" = 0 ] || die "claude --bg exited with code $rc — see the output above"
id="$(printf '%s\n' "$out" | strip_ansi | command grep -oE 'backgrounded · [0-9a-f]+' | awk '{print $3}' || true)"
[ -n "$id" ] || die "NOT STARTED — no 'backgrounded · <id>' line in the output above"

# Remote Control takes a few seconds to connect; the URL then appears in the session log.
# The log is a pty buffer with escape codes and partly redrawn lines, so the same URL can
# also appear cut short; the longest match wins.
url=""
url_wait="${BG_CLAUDE_RC_URL_WAIT:-20}"
for _ in $(seq 1 "$url_wait"); do
  url="$(claude logs "$id" 2>/dev/null \
    | strip_ansi \
    | command grep -oE 'https://claude\.ai/code/session_[A-Za-z0-9]+' \
    | awk '{ if (length($0) > m) { m = length($0); u = $0 } } END { print u }' || true)"
  [ -n "$url" ] && break
  sleep 1
done

echo "name=$name"
echo "model=$model"
echo "effort=$effort"
echo "id=$id"
echo "url=$url"
[ -n "$url" ] || echo "note=the link did not appear within $url_wait s — check with: claude logs $id"
