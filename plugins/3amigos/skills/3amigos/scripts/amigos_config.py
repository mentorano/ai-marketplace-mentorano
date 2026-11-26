"""Load and merge the 3amigos config: default < user < project < run, key by key.

User config: <home>/.claude/3amigos/config.json. Project config: <main checkout>/.claude/3amigos.local.json,
where the main checkout is the parent of `git rev-parse --path-format=absolute --git-common-dir` only when
that dir's basename is `.git`; a linked worktree therefore reads its main checkout's file. load() never
prints and never raises: a file that is not valid JSON, an unknown key or a bad value is left out for that
key and named in "errors" as "<file>: <problem>". The config holds names and paths only, never a key or a
token, and an error message names keys but never echoes a value from the file.
"""
import copy
import json
import os
import re
import subprocess

POOL = ("codex", "gemini", "opus", "fable")
EXTERNAL = ("codex", "gemini")
EFFORTS = ("low", "medium", "high")
FALLBACKS = ("vertex", "key", "none")
USER_FILE = os.path.join(".claude", "3amigos", "config.json")
PROJECT_FILE = os.path.join(".claude", "3amigos.local.json")
NO_MAIN_CHECKOUT = "none (no main checkout)"

DEFAULTS = {
    "panel": ["codex", "gemini", "fable"],
    "gemini": {
        "agy": True,
        "model": "gemini-4-carbon",
        "model_fallback": "gemini-4-argon",
        "effort": "high",
        "fallback": "none",
        "vertex": {"project": None, "location": "global"},
        "key_env": "GEMINI_API_KEY",
        "key_dotenv": None,
    },
}
META_KEYS = ("version", "updated")  # written by the setup, not merged


def validate_panel(names):
    """"" for exactly three different names from POOL, else the reason."""
    if not isinstance(names, (list, tuple)) or not all(isinstance(n, str) for n in names):
        return "panel must be a list of voter names"
    if any(n not in POOL for n in names):
        return f"unknown voter name; the pool is {', '.join(POOL)}"
    if len(names) != 3 or len(set(names)) != 3:
        return f"a panel is exactly three different voters from {', '.join(POOL)}"
    return ""


def _non_empty(v):
    return isinstance(v, str) and v.strip() != ""


def _env_name(v):
    return isinstance(v, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v) is not None


CHECKS = {  # dotted key -> (is valid, what a valid value is)
    "gemini.agy": (lambda v: isinstance(v, bool), "true or false"),
    "gemini.model": (_non_empty, "a model name"),
    "gemini.model_fallback": (_non_empty, "a model name"),
    "gemini.effort": (lambda v: v in EFFORTS, "one of " + ", ".join(EFFORTS)),
    "gemini.fallback": (lambda v: v in FALLBACKS, "one of " + ", ".join(FALLBACKS)),
    "gemini.vertex.project": (lambda v: v is None or _non_empty(v), "a cloud project id or null"),
    "gemini.vertex.location": (_non_empty, "a location"),
    "gemini.key_env": (_env_name, "an environment variable name"),
    "gemini.key_dotenv": (lambda v: v is None or _non_empty(v), "a file path or null"),
}


def project_root(cwd):
    """The main checkout of the git repo at cwd, or None (not a repo, or a git dir not named .git)."""
    try:
        res = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                             cwd=cwd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    common = res.stdout.strip()
    if res.returncode != 0 or not common:
        return None
    common = os.path.normpath(common)
    return os.path.dirname(common) if os.path.basename(common) == ".git" else None


def read_file(path, errors):
    """The file's top-level object, or {} when it is missing or broken (broken goes to errors)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        if os.path.lexists(path):  # a link whose target is gone is broken, not absent
            errors.append(f"{path}: cannot read (broken link)")
        return {}
    except (ValueError, RecursionError) as exc:
        errors.append(f"{path}: not valid JSON ({type(exc).__name__})")
        return {}
    except OSError as exc:
        errors.append(f"{path}: cannot read ({type(exc).__name__})")
        return {}
    if not isinstance(data, dict):
        errors.append(f"{path}: the config must be a JSON object")
        return {}
    return data


def flatten(data, path, errors):
    """{dotted key: value} of the valid values in one config object; every problem goes to errors."""
    out = {}
    for key, val in data.items():
        if key in META_KEYS:
            if key == "version" and (type(val) is not int or val != 1):  # bool is an int
                errors.append(f"{path}: version must be 1")
        elif key == "panel":
            why = validate_panel(val)
            if why:
                errors.append(f"{path}: panel: {why}")
            else:
                out["panel"] = list(val)
        elif key == "gemini":
            _flatten_section(val, "gemini", DEFAULTS["gemini"], path, errors, out)
        else:
            errors.append(f"{path}: unknown key {key!r}")
    return out


def _flatten_section(section, prefix, default, path, errors, out):
    if not isinstance(section, dict):
        errors.append(f"{path}: {prefix} must be an object")
        return
    for key, val in section.items():
        dotted = f"{prefix}.{key}"
        if key not in default:
            errors.append(f"{path}: unknown key {dotted!r}")
        elif isinstance(default[key], dict):
            _flatten_section(val, dotted, default[key], path, errors, out)
        elif CHECKS[dotted][0](val):
            out[dotted] = val
        else:
            errors.append(f"{path}: {dotted} must be {CHECKS[dotted][1]}")


def _set(cfg, dotted, val):
    node = cfg
    *parents, last = dotted.split(".")
    for part in parents:
        node = node[part]
    node[last] = val


def _default_keys(node, prefix=""):
    for key, val in node.items():
        dotted = f"{prefix}{key}"
        if isinstance(val, dict):
            yield from _default_keys(val, dotted + ".")
        else:
            yield dotted


def load(cwd=None, home=None, panel=None):
    """The effective config dict: panel, external, gemini, sources, files, project_root, errors."""
    errors = []
    cfg = copy.deepcopy(DEFAULTS)
    sources = {k: "default" for k in _default_keys(DEFAULTS)}
    try:
        home = home or os.environ.get("HOME") or os.path.expanduser("~")
        root = project_root(cwd or os.getcwd())
        user_path = os.path.join(home, USER_FILE)
        project_path = os.path.join(root, PROJECT_FILE) if root else None
        layers = [("user", user_path)] + ([("project", project_path)] if project_path else [])
        for source, path in layers:
            for dotted, val in flatten(read_file(path, errors), path, errors).items():
                _set(cfg, dotted, val)
                sources[dotted] = source
        if panel is not None:
            why = validate_panel(panel)
            if why:
                errors.append(f"--panel: {why}")
            else:
                cfg["panel"], sources["panel"] = list(panel), "run"
    except Exception as exc:  # the loader never raises; the caller exits 2 on errors
        errors.append(f"config: unexpected {type(exc).__name__}")
        root, user_path, project_path = None, "", None
    cfg["external"] = [n for n in cfg["panel"] if n in EXTERNAL]
    cfg["sources"] = sources
    cfg["files"] = {"user": user_path, "project": project_path or NO_MAIN_CHECKOUT}
    cfg["project_root"] = root
    cfg["errors"] = errors
    return cfg
