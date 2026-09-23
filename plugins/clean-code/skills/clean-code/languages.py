"""File collection and per-language function measurement.

Imported by measure.py and boundaries.py, the two entry points; nothing runs
this file.
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKIP_DIRS = {"node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".git", "coverage", ".next"}


class MeasureError(Exception):
    """A run that could not measure. The message says how to fix it."""


@dataclass
class FunctionMeasure:
    file: str
    name: str
    line: int
    lines: int
    cc: int
    params: int
    depth: int


def language_of(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "py"
    if suffix in (".ts", ".tsx"):
        return "ts"
    return None


def _display(path: Path) -> str:
    try:
        rel = os.path.relpath(path)
    except ValueError:
        return str(path)
    if rel.split(os.sep, 1)[0] == os.pardir:
        return str(path)
    return rel


def read_text(path: Path) -> str:
    """Read a source file, turning an unreadable file into a broken run."""
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        raise MeasureError(f"{path}: cannot read: {exc}") from exc


# --- Collection ---------------------------------------------------------------

def _git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MeasureError(f"git {' '.join(args)} failed in {cwd}:\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _walk(root: Path):
    if root.is_file():
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            yield Path(dirpath) / name


def changed_files(roots: list[Path], base: str) -> list[Path]:
    anchor = roots[0] if roots[0].is_dir() else roots[0].parent
    repo = Path(_git(["rev-parse", "--show-toplevel"], cwd=anchor))
    try:
        merge_base = _git(["merge-base", base, "HEAD"], cwd=repo)
    except MeasureError as exc:
        raise MeasureError(
            f"base {base!r} does not resolve in {repo}.\nPass --base <ref> that exists here, e.g. --base main"
        ) from exc
    modified = _git(["diff", "--name-only", merge_base], cwd=repo).splitlines()
    untracked = _git(["ls-files", "--others", "--exclude-standard"], cwd=repo).splitlines()
    candidates = [repo / rel for rel in modified + untracked]
    return [p for p in candidates if p.is_file() and any(_is_under(p, r) for r in roots)]


def collect_files(roots: list[Path], changed: bool, base: str) -> list[Path]:
    for root in roots:
        if not root.exists():
            raise MeasureError(f"{root}: no such path")
    candidates = changed_files(roots, base) if changed else [p for root in roots for p in _walk(root)]
    seen: set[Path] = set()
    out: list[Path] = []
    for path in candidates:
        if language_of(path) is None or path.resolve() in seen:
            continue
        seen.add(path.resolve())
        out.append(path)
    return out


# --- Python -------------------------------------------------------------------

_PY_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_PY_BLOCKS: tuple[type, ...] = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.Match,
) + tuple(getattr(ast, name) for name in ("TryStar",) if hasattr(ast, name))


def _own_nodes(fn: ast.AST):
    """Yield every node inside fn without entering nested defs or classes."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        if isinstance(node, _PY_DEFS):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _py_complexity(fn: ast.AST) -> int:
    cc = 1
    for node in _own_nodes(fn):
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.match_case)):
            cc += 1
        elif isinstance(node, ast.comprehension):
            cc += 1 + len(node.ifs)
        elif isinstance(node, ast.BoolOp):
            cc += len(node.values) - 1
    return cc


def _py_depth(fn: ast.AST) -> int:
    def rec(node: ast.AST, depth: int) -> int:
        best = depth
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _PY_DEFS):
                continue
            next_depth = depth
            if isinstance(child, _PY_BLOCKS):
                is_elif = isinstance(node, ast.If) and isinstance(child, ast.If) and node.orelse == [child]
                next_depth = depth if is_elif else depth + 1
            best = max(best, rec(child, next_depth))
        return best

    return rec(fn, 0)


def _py_params(args: ast.arguments, in_class: bool) -> int:
    positional = list(args.posonlyargs) + list(args.args)
    if in_class and positional and positional[0].arg in ("self", "cls"):
        positional = positional[1:]
    count = len(positional) + len(args.kwonlyargs)
    if args.vararg:
        count += 1
    if args.kwarg:
        count += 1
    return count


class _PyVisitor(ast.NodeVisitor):
    def __init__(self, file: str):
        self.file = file
        self.functions: list[FunctionMeasure] = []
        self._scope: list[tuple[str, bool]] = []  # (name, is_class)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope.append((node.name, True))
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        in_class = bool(self._scope) and self._scope[-1][1]
        qualified = ".".join([name for name, _ in self._scope] + [node.name])
        self.functions.append(
            FunctionMeasure(
                file=self.file,
                name=qualified,
                line=node.lineno,
                lines=node.end_lineno - node.lineno + 1,
                cc=_py_complexity(node),
                params=_py_params(node.args, in_class),
                depth=_py_depth(node),
            )
        )
        self._scope.append((node.name, False))
        self.generic_visit(node)
        self._scope.pop()


def parse_python(path: Path, text: str) -> ast.Module:
    """Parse a source file, turning a syntax error into a broken run."""
    try:
        return ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        raise MeasureError(f"{path}: cannot parse: {exc}") from exc


def measure_python_file(path: Path) -> list[FunctionMeasure]:
    tree = parse_python(path, read_text(path))
    visitor = _PyVisitor(_display(path))
    visitor.visit(tree)
    return visitor.functions


# --- TypeScript ---------------------------------------------------------------

def find_typescript_package(file: Path) -> Path | None:
    for parent in file.resolve().parents:
        candidate = parent / "node_modules" / "typescript"
        if (candidate / "package.json").is_file():
            return candidate
    return None


def _require_compiler_api(package: Path) -> None:
    # TypeScript 7 is the native compiler and ships no JavaScript API: its
    # package.json has no `main`, and measure-ts.mjs would die on a bare
    # "Cannot find module" that names neither the version nor the fix.
    manifest = json.loads((package / "package.json").read_text(encoding="utf-8"))
    main = manifest.get("main")
    if main and (package / main).is_file():
        return
    raise MeasureError(
        f"typescript {manifest.get('version', '?')} at {package} has no JavaScript compiler API,\n"
        "which measure-ts.mjs needs to parse the files. TypeScript 7 dropped it.\n"
        "Point the script at a 5.x package: install one next to the sources with\n"
        "  npm install --no-save typescript@5"
    )


def _group_by_package(files: list[Path]) -> dict[Path, list[Path]]:
    groups: dict[Path, list[Path]] = {}
    for file in files:
        package = find_typescript_package(file)
        if package is None:
            raise MeasureError(
                f"typescript package not found above {file}.\n"
                "Install the project's dependencies once per working copy:\n"
                "  cd <frontend dir> && npm ci\n"
                "or add the compiler alone:\n"
                "  npm install --save-dev typescript@5"
            )
        groups.setdefault(package, []).append(file)
    return groups


def measure_ts_files(files: list[Path]) -> list[FunctionMeasure]:
    if not files:
        return []
    groups = _group_by_package(files)
    for package in groups:
        _require_compiler_api(package)
    node = shutil.which("node")
    if node is None:
        raise MeasureError("node is not on PATH. Install Node 20+ (https://nodejs.org) or run `nvm use` first.")
    out: list[FunctionMeasure] = []
    for package, group in groups.items():
        command = [node, str(SCRIPT_DIR / "measure-ts.mjs"), str(package), *[str(f) for f in group]]
        proc = subprocess.run(command, capture_output=True, text=True)
        if proc.returncode != 0:
            raise MeasureError(f"measure-ts.mjs failed:\n{proc.stderr.strip()}")
        for row in json.loads(proc.stdout):
            row["file"] = _display(Path(row["file"]))
            out.append(FunctionMeasure(**row))
    return out
