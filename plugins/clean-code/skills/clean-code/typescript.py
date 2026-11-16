"""Function measurement through the TypeScript parser.

Imported by measure.py and revisions.py; nothing runs this file. TypeScript
files, JavaScript files and the inline scripts of HTML files are parsed by
measure-ts.mjs next to this file. The parser is a `typescript` package: the
measured project's own when it has one with a compiler API, so the parser
matches what the project compiles; otherwise one that this plugin installs
once into its own cache directory. Nothing is ever installed into the
measured repository.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from html_scripts import in_place, script_blocks
from languages import FunctionMeasure, MeasureError, _display, language_of, read_script_text

SCRIPT_DIR = Path(__file__).resolve().parent
# The version the cache installs. A 5.x: TypeScript 7 has no JavaScript API.
TYPESCRIPT_VERSION = "5.9.3"
CACHE_ENV = "CLEAN_CODE_CACHE_DIR"
# npm retries a dead network for minutes; a measurement must not hang on it.
INSTALL_TIMEOUT_SECONDS = 120
# Where the command started. --at and --compare move the working directory into
# a mirror, and a relative cache directory must not move with it.
START_DIR = Path.cwd()


def _note(text: str) -> None:
    print(f"measure.py: {text}", file=sys.stderr)


@dataclass
class UnparsedScript:
    """An inline script of an HTML file the parser could not read; its functions are in no row.

    A page template is the usual case: `{{ value }}` inside a script is not
    JavaScript until the page is rendered. The run goes on, and the report
    lists the script, so the rest of the files are still measured and the
    gap cannot be read as a clean result.
    """

    file: str
    line: int
    message: str


@dataclass(frozen=True)
class Parsed:
    functions: list[FunctionMeasure]
    unparsed: list[UnparsedScript]


# --- The project's own package ------------------------------------------------

def find_typescript_package(file: Path) -> Path | None:
    for parent in file.resolve().parents:
        candidate = parent / "node_modules" / "typescript"
        if (candidate / "package.json").is_file():
            return candidate
    return None


def _why_unusable(package: Path | None, file: Path) -> str | None:
    """Why the project's package cannot parse, or None when it can."""
    if package is None:
        return f"typescript package not found above {file}"
    # TypeScript 7 is the native compiler and ships no JavaScript API: its
    # package.json has no `main`, and measure-ts.mjs would die on a bare
    # "Cannot find module" that names neither the version nor the fix.
    manifest = json.loads((package / "package.json").read_text(encoding="utf-8"))
    main = manifest.get("main")
    if main and (package / main).is_file():
        return None
    return f"typescript {manifest.get('version', '?')} at {package} has no JavaScript compiler API (TypeScript 7 dropped it)"


# --- The plugin's cached package ----------------------------------------------

def cache_root() -> Path:
    """The plugin's own cache directory, as an absolute path: npm and node each resolve a relative one differently."""
    configured = os.environ.get(CACHE_ENV)
    if configured:
        return START_DIR / Path(configured).expanduser()
    base = os.environ.get("XDG_CACHE_HOME")
    return START_DIR / (Path(base) if base else Path.home() / ".cache") / "clean-code"


def _install_arguments(prefix: Path) -> list[str]:
    return ["install", "--prefix", str(prefix), "--no-save", "--no-package-lock", "--no-audit", "--no-fund",
            "--ignore-scripts", f"typescript@{TYPESCRIPT_VERSION}"]


def _install_failed(home: Path, reason: str, why: str) -> MeasureError:
    return MeasureError(
        f"{reason}, and the one-time install of typescript@{TYPESCRIPT_VERSION} into the clean-code cache failed:\n"
        f"{why}\n"
        "Install it by hand (needs npm and network access):\n"
        f"  npm install --prefix {home} --no-save typescript@{TYPESCRIPT_VERSION}\n"
        "or install the measured project's own dependencies (npm ci in its frontend directory).\n"
        f"{CACHE_ENV} moves the cache directory."
    )


def _publish(staging: Path, home: Path) -> None:
    """Move a finished install into place; a parallel run that finished first wins."""
    try:
        os.rename(staging, home)
    except OSError as exc:
        if not (home / "node_modules" / "typescript" / "package.json").is_file():
            raise MeasureError(f"{home}: cannot move the installed typescript package into place: {exc}") from exc


def _npm_install(npm: str, staging: Path) -> str | None:
    """Install into the staging directory; the reason it failed, or None."""
    # A package.json of its own keeps npm from installing into a parent directory's project.
    (staging / "package.json").write_text('{"private": true}\n', encoding="utf-8")
    command = [npm, *_install_arguments(staging)]
    try:
        proc = subprocess.run(command, cwd=staging, capture_output=True, text=True, timeout=INSTALL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return f"npm did not finish in {INSTALL_TIMEOUT_SECONDS} seconds"
    if proc.returncode == 0 and (staging / "node_modules" / "typescript" / "package.json").is_file():
        return None
    return proc.stderr.strip() or f"npm exited with {proc.returncode} and left no typescript package"


def _staged_install(npm: str, home: Path) -> str | None:
    """Install next to the final directory and rename, so a parallel run never sees a half-written package."""
    home.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{home.name}.", dir=home.parent))
    try:
        failure = _npm_install(npm, staging)
        if failure is None:
            _publish(staging, home)
        return failure
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _install(home: Path, reason: str) -> None:
    npm = shutil.which("npm")
    if npm is None:
        raise _install_failed(home, reason, "npm is not on PATH")
    _note(f"{reason}; installing typescript@{TYPESCRIPT_VERSION} once into {home} (the measured repository is not touched)")
    try:
        failure = _staged_install(npm, home)
    except OSError as exc:
        failure = f"cannot write the cache directory: {exc}"
    if failure:
        raise _install_failed(home, reason, failure)


def cached_typescript_package(reason: str) -> Path:
    """The plugin's own typescript package, installed on first use; `reason` says why the project's is not used."""
    home = cache_root() / f"typescript-{TYPESCRIPT_VERSION}"
    package = home / "node_modules" / "typescript"
    if not (package / "package.json").is_file():
        _install(home, reason)
    return package


def _group_by_package(files: list[Path]) -> dict[Path, list[Path]]:
    found: dict[Path | None, list[Path]] = {}
    for file in files:
        found.setdefault(find_typescript_package(file), []).append(file)
    groups: dict[Path, list[Path]] = {}
    for package, group in found.items():
        reason = _why_unusable(package, group[0])
        usable = cached_typescript_package(reason) if reason else package
        groups.setdefault(usable, []).extend(group)
    return groups


# --- Measurement --------------------------------------------------------------

def _inline_sources(file: Path) -> list[dict[str, str]]:
    """One source per inline script of an HTML file, each at its own line of that file."""
    text = read_script_text(file)
    return [{"file": str(file), "text": in_place(text, block)} for block in script_blocks(text)]


def _cache_hint(package: Path) -> str:
    """What to try when the parser that failed is the cached one and not the project's own."""
    if cache_root() not in package.parents:
        return ""
    return (
        f"\nParsed with the cached typescript {TYPESCRIPT_VERSION}: the project has no typescript package of its own."
        "\nIf it uses newer syntax, install its dependencies (npm ci) and measure again."
    )


def _parse(node: str, package: Path, group: list[Path]) -> dict[str, list[dict]]:
    """Run measure-ts.mjs over one package's files; HTML files go in as their inline scripts."""
    files = [str(file) for file in group if language_of(file) != "html"]
    inline = [source for file in group if language_of(file) == "html" for source in _inline_sources(file)]
    command = [node, str(SCRIPT_DIR / "measure-ts.mjs"), str(package), *(["--inline"] if inline else []), *files]
    proc = subprocess.run(
        command, input=json.dumps(inline) if inline else None, capture_output=True, text=True, encoding="utf-8"
    )
    if proc.returncode != 0:
        raise MeasureError(f"measure-ts.mjs failed:\n{proc.stderr.strip()}{_cache_hint(package)}")
    return json.loads(proc.stdout)


def _has_code(file: Path) -> bool:
    """An HTML file with no inline JavaScript needs no parser at all."""
    return language_of(file) != "html" or bool(script_blocks(read_script_text(file)))


def parse_files(files: list[Path]) -> Parsed:
    """Measure TypeScript and JavaScript files and the inline scripts of HTML files."""
    files = [file for file in files if _has_code(file)]
    parsed = Parsed(functions=[], unparsed=[])
    if not files:
        return parsed
    node = shutil.which("node")
    if node is None:
        raise MeasureError("node is not on PATH. Install Node 20+ (https://nodejs.org) or run `nvm use` first.")
    for package, group in _group_by_package(files).items():
        found = _parse(node, package, group)
        parsed.functions.extend(FunctionMeasure(**{**row, "file": _display(Path(row["file"]))}) for row in found["functions"])
        parsed.unparsed.extend(UnparsedScript(**{**row, "file": _display(Path(row["file"]))}) for row in found["unparsed"])
    return parsed
