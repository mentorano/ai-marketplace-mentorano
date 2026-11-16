"""Find the `typescript` package the clean-code TypeScript tests run against.

Order: the CLEAN_CODE_TS_PACKAGE variable, then the repo's own
`node_modules/typescript` (installed from the root package.json; run-tests.sh
runs `npm ci` when it is missing). The first candidate that exists wins, as
an absolute path, because the tests symlink it into temporary projects. When
none exists the TypeScript tests skip with SKIP_REASON.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

ENV_VAR = "CLEAN_CODE_TS_PACKAGE"
REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_TS_PACKAGE = REPO_ROOT / "node_modules" / "typescript"


def _skip_reason() -> str:
    env_hint = f"set {ENV_VAR} to a node_modules/typescript directory"
    if (REPO_ROOT / "package.json").is_file() and (REPO_ROOT / "package-lock.json").is_file():
        return f"needs node on PATH and a typescript package: run `npm ci` in the repo root, or {env_hint}"
    return f"needs node on PATH and a typescript package: {env_hint}"


SKIP_REASON = _skip_reason()


def find_ts_package() -> Path:
    configured = os.environ.get(ENV_VAR)
    candidates = [Path(configured)] if configured else []
    candidates.append(REPO_TS_PACKAGE)
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    return candidates[0].resolve()


TS_PACKAGE = find_ts_package()
TS_READY = TS_PACKAGE.is_dir() and bool(shutil.which("node"))


# --- The plugin's typescript cache --------------------------------------------

CACHE_ENV = "CLEAN_CODE_CACHE_DIR"
STUBS = REPO_ROOT / "tests" / "stubs"


def _tool_bin(tmp: Path) -> Path:
    """A directory with node and git alone: either may sit next to npm, and that directory leaves the PATH."""
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    for tool in ("node", "git"):
        link = bin_dir / tool
        real = shutil.which(tool)
        if link.exists() or link.is_symlink():
            continue
        if real:
            os.symlink(real, link)
        else:
            # No test runs this one: the runs that need the tool skip without it.
            link.write_text("#!/bin/sh\nexit 1\n")
            link.chmod(0o755)
    return bin_dir


def _path_without_npm() -> list[str]:
    directories = os.environ.get("PATH", "").split(os.pathsep)
    return [directory for directory in directories if directory and not (Path(directory) / "npm").exists()]


def cache_env(tmp: Path, npm_stub: str | None = None) -> dict[str, str]:
    """An environment with an empty clean-code cache under tmp and the named stub as npm, or no npm.

    No test may reach the real npm: a run that finds no typescript package
    would download one, and the result would depend on the network.
    """
    env = dict(os.environ)
    path = [str(_tool_bin(tmp)), *_path_without_npm()]
    if npm_stub:
        path.insert(0, str(STUBS / npm_stub))
    env.update(
        {
            "PATH": os.pathsep.join(path),
            CACHE_ENV: str(tmp / "cache"),
            "NPM_STUB_LOG": str(tmp / "npm.log"),
            "NPM_STUB_TYPESCRIPT": str(TS_PACKAGE),
        }
    )
    return env
