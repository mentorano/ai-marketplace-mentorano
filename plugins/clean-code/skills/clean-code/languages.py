"""File collection, the language of a file, and Python function measurement.

Imported by measure.py, boundaries.py and typescript.py; nothing runs this
file. TypeScript, JavaScript and inline HTML scripts are measured by
typescript.py.
"""
from __future__ import annotations

import ast
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKIP_DIRS = {
    "node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".git", "coverage", ".next",
    # Generated pages and their scripts: coverage.py, Sphinx, a static site build.
    "htmlcov", "_build", "_site",
}
LANGUAGE_BY_SUFFIX = {
    ".py": "py",
    ".ts": "ts",
    ".tsx": "ts",
    ".js": "js",
    ".mjs": "js",
    ".cjs": "js",
    ".jsx": "js",
    ".html": "html",
}
# The languages measure-ts.mjs parses; typescript.py runs it.
PARSER_LANGUAGES = frozenset({"ts", "js", "html"})
# A minified file is build output: one line holds every function, so its numbers say nothing.
MINIFIED_SUFFIXES = (".min.js", ".min.mjs", ".min.cjs")


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
    """The language a file is measured as, or None for a file that is not measured."""
    name = path.name.lower()
    if name.endswith(MINIFIED_SUFFIXES):
        return None
    return LANGUAGE_BY_SUFFIX.get(path.suffix.lower())


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


def read_script_text(path: Path) -> str:
    """Read a JavaScript or HTML file; one that is not UTF-8 is read one character per byte.

    Only the structure is measured, and an old page is often cp1251 or
    latin-1. Read as latin-1 no line and no brace moves, and a letter of a
    single-byte encoding stays a letter, so an identifier still parses; its
    name prints in the wrong letters. measure-ts.mjs reads a file the same way.
    """
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")
    except OSError as exc:
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

