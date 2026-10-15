#!/usr/bin/env bash
# Install the coord hooks into ~/.claude/hooks/ and register them in ~/.claude/settings.json.
# Idempotent: re-running changes nothing if both are registered. Backs up settings.json first.
#   SessionStart, matcher "clear"      -> kickoff-on-clear.py
#   PreToolUse,   matcher "Agent|Task" -> handoff-at-boundary.py (timeout 10)
# Honours $HOME, so it can be tested against a temp HOME copy.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/hooks" && pwd)"
DEST="$HOME/.claude/hooks"
SETTINGS="$HOME/.claude/settings.json"
command -v python3 >/dev/null || { echo "python3 required" >&2; exit 2; }

mkdir -p "$DEST"
for f in kickoff-on-clear.py handoff-at-boundary.py; do
  if [ -f "$DEST/$f" ] && cmp -s "$SRC/$f" "$DEST/$f"; then
    echo "hook up to date: $DEST/$f"
  else
    [ -f "$DEST/$f" ] && cp -p "$DEST/$f" "$DEST/$f.bak.$(date +%Y%m%d%H%M%S)" && echo "backed up old $f"
    cp "$SRC/$f" "$DEST/$f"; chmod +x "$DEST/$f"; echo "installed: $DEST/$f"
  fi
done
mkdir -p "$HOME/.claude/kickoffs"

[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
python3 - "$SETTINGS" "$DEST" <<'PY'
import json, os, shlex, shutil, sys, time
settings, dest = sys.argv[1], sys.argv[2]
with open(settings) as fh:
    data = json.load(fh)
wanted = [
    ("SessionStart", "clear", os.path.join(dest, "kickoff-on-clear.py"), None),
    ("PreToolUse", "Agent|Task", os.path.join(dest, "handoff-at-boundary.py"), 10),
]
hooks = data.get("hooks") or {}  # setdefault alone leaves an existing `"hooks": null` as None
data["hooks"] = hooks
changed = False
for event, matcher, command, timeout in wanted:
    groups = hooks.setdefault(event, [])
    quoted = shlex.quote(command)  # the path is run through a shell; unquoted, spaces split it
    present = any(g.get("matcher") == matcher and
                  any(h.get("command") == quoted for h in g.get("hooks", []))
                  for g in groups)
    if present:
        print(f"already registered: {event} [{matcher}] -> {command}")
        continue
    hook = {"type": "command", "command": quoted}
    if timeout:
        hook["timeout"] = timeout
    groups.append({"matcher": matcher, "hooks": [hook]})
    changed = True
    print(f"registered: {event} [{matcher}] -> {command}")
if changed:
    backup = f"{settings}.bak.{time.strftime('%Y%m%d%H%M%S')}"
    shutil.copy2(settings, backup)
    print(f"backup: {backup}")
    # settings.json may be a symlink (e.g. into dotfiles); replace what it points at, not the
    # symlink itself, and carry over its mode - os.replace on the link path would swap in a plain
    # file and silently drop both.
    target = os.path.realpath(settings)
    tmp = target + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    shutil.copymode(settings, tmp)
    os.replace(tmp, target)
else:
    print("settings.json unchanged")
PY
echo "Done. New sessions pick up hooks at start; restart running sessions to load them."
