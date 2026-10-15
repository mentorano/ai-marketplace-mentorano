"""Shared helpers of the two captain handoff hooks (R21): the log, the check for the global
coord hooks, the successor terminal setting, and the plugin's measure-context script. Imported by
the hooks that sit next to it."""
from __future__ import annotations

import importlib.util
import json
import os
from datetime import datetime
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
MEASURE = PLUGIN_ROOT / "skills" / "captain" / "scripts" / "measure-context.py"
SUCCESSOR_TAB = PLUGIN_ROOT / "skills" / "captain" / "scripts" / "successor-tab.py"
CAPTAIN_DIR = Path.home() / ".claude" / "captain"
LOG = CAPTAIN_DIR / "handoff-hooks.log"


def log(entry: dict) -> None:
    entry = {"at": datetime.now().isoformat(timespec="seconds"), **entry}
    try:
        CAPTAIN_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _commands(node):
    """Every `command` string in the hooks section of settings.json, at any depth."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "command" and isinstance(value, str):
                yield value
            else:
                yield from _commands(value)
    elif isinstance(node, list):
        for item in node:
            yield from _commands(item)


def coord_hook_installed(script: str) -> bool:
    """True when ~/.claude/settings.json registers coord's global hook `script` (e.g.
    `handoff-at-boundary.py`). The captain copy then stays silent: one denial or injection, not two."""
    try:
        with open(Path.home() / ".claude" / "settings.json", encoding="utf-8") as fh:
            settings = json.load(fh)
    except (OSError, ValueError):
        return False
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    return any(script in command for command in _commands(hooks))


def successor_terminal() -> str:
    """`supacode`, `cmux` or `none`, by the rule of the plugin's successor-tab script: config
    `successor_terminal` `supacode` or `cmux`; no key → Supacode when this session runs in it, else
    cmux when it runs in cmux."""
    try:
        tab = _load(SUCCESSOR_TAB, "captain_successor_tab")
        return tab.choose_terminal(tab.read_config(Path.home()), os.environ)[0]
    except Exception:  # a broken helper must not break the hook: the /clear path still works
        return "none"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_measure():
    return _load(MEASURE, "captain_measure_context")
