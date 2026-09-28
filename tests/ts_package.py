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
