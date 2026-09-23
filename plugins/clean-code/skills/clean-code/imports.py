"""The import graph of a Python package: where each file sits and what it imports.

Imported by boundaries.py, which is the only entry point; nothing runs this file.
"""
from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass, field
from functools import cached_property
from pathlib import Path

from languages import MeasureError, _display, language_of, parse_python, read_text

ROOT_LAYER = "root"
PORT_BASES = frozenset({"Protocol", "ABC"})
SQL_SITE = re.compile(r"select\(|\.execute\(|\.where\(|func\.")


@dataclass(frozen=True)
class Layout:
    """The names a project gives its layers, its framework modules and its pure modules."""

    layers: frozenset[str] = frozenset({"api", "services", "models", "schemas", "domain", "parsers"})
    core: frozenset[str] = frozenset({"core", "shared"})
    domain: frozenset[str] = frozenset({"domain", "shared", "parsers"})


@dataclass(frozen=True)
class Place:
    module: str
    layer: str

    def __str__(self) -> str:
        return f"{self.module}.{self.layer}"


@dataclass(frozen=True)
class Package:
    """The top-level package the files belong to, with the project's layout.

    `modules` is read from the disk once, so a Report stays valid after the tree is gone.
    """

    root: Path
    layout: Layout
    modules: frozenset[str]

    @staticmethod
    def at(root: Path, layout: Layout) -> Package:
        return Package(root, layout, frozenset(child.name for child in root.iterdir() if child.is_dir()))

    @property
    def name(self) -> str:
        return self.root.name

    def owns(self, target: str) -> bool:
        return target.split(".", 1)[0] == self.name

    def is_feature(self, module: str) -> bool:
        return module != self.name and module not in self.layout.core

    def place_of(self, segments: tuple[str, ...]) -> Place:
        """The place of a path or an import target, read from its first two segments under the root."""
        if not segments or segments[0] not in self.modules:
            return Place(self.name, ROOT_LAYER)
        if segments[0] in self.layout.layers:
            return Place(self.name, segments[0])
        layer = segments[1] if len(segments) > 1 and segments[1] in self.layout.layers else ROOT_LAYER
        return Place(segments[0], layer)


@dataclass(frozen=True)
class Edge:
    """One import statement from a file to a module of the same package."""

    file: str
    line: int
    target: str
    src: Place
    dst: Place

    def row(self) -> dict[str, object]:
        return {"file": self.file, "line": self.line, "target": self.target}


@dataclass(frozen=True)
class External:
    """One import statement of a package outside the project."""

    file: str
    line: int
    framework: str
    place: Place

    def row(self) -> dict[str, object]:
        return {"file": self.file, "line": self.line, "framework": self.framework}


@dataclass(frozen=True)
class Port:
    file: str
    line: int
    name: str

    def row(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SqlFile:
    file: str
    sites: int

    def row(self) -> dict[str, object]:
        return asdict(self)


# --- Parsing ------------------------------------------------------------------

def package_root(path: Path) -> Path:
    """The top-level package: the top of the chain of directories with an __init__.py above the file.

    Resolved first, because a relative path stops climbing at `.` and its parent is `.` again.
    """
    package = path.resolve().parent
    while (package.parent / "__init__.py").is_file():
        package = package.parent
    return package


@dataclass
class Source:
    """One parsed file: where it sits, what it imports, what it defines."""

    path: Path
    package: Package
    tree: ast.Module
    text: str
    file: str = field(init=False)
    dirs: tuple[str, ...] = field(init=False)
    place: Place = field(init=False)

    def __post_init__(self) -> None:
        self.file = _display(self.path)
        self.dirs = self.path.resolve().parent.relative_to(self.package.root).parts
        self.place = self.package.place_of(self.dirs)

    @cached_property
    def imports(self) -> list[tuple[int, str]]:
        """(line, dotted target) for every import statement, relative imports resolved."""
        nodes = [n for n in ast.walk(self.tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        return [(node.lineno, target) for node in nodes for target in self._targets(node)]

    def _targets(self, node: ast.Import | ast.ImportFrom) -> list[str]:
        if isinstance(node, ast.Import):
            return [alias.name for alias in node.names]
        module = self._absolute(node)
        return sorted({self._deepest(module, alias.name) for alias in node.names})

    def _absolute(self, node: ast.ImportFrom) -> str:
        if node.level == 0:
            return node.module or ""
        base = [self.package.name, *self.dirs[: len(self.dirs) - node.level + 1]]
        return ".".join(base + ([node.module] if node.module else []))

    def _deepest(self, module: str, name: str) -> str:
        """`from app.orders import api` binds a layer: the target is the deeper path when that changes the place."""
        deeper = f"{module}.{name}"
        if self.package.place_of(_segments(deeper)) == self.package.place_of(_segments(module)):
            return module
        return deeper

    def edges(self) -> list[Edge]:
        return [self._edge(line, target) for line, target in self.imports if self.package.owns(target)]

    def _edge(self, line: int, target: str) -> Edge:
        dst = self.package.place_of(_segments(target))
        return Edge(file=self.file, line=line, target=target, src=self.place, dst=dst)

    def externals(self) -> list[External]:
        return [
            External(file=self.file, line=line, framework=target.split(".", 1)[0], place=self.place)
            for line, target in self.imports
            if not self.package.owns(target)
        ]

    def ports(self) -> list[Port]:
        classes = [n for n in ast.walk(self.tree) if isinstance(n, ast.ClassDef)]
        return [Port(self.file, c.lineno, c.name) for c in classes if any(_base_name(b) in PORT_BASES for b in c.bases)]

    def sql_sites(self) -> int:
        lines = self.text.split("\n")
        statements = [n for n in ast.walk(self.tree) if isinstance(n, ast.stmt)]
        return sum(1 for node in statements if SQL_SITE.search(_statement_text(node, lines)))


def _segments(target: str) -> tuple[str, ...]:
    """The dotted path below the package name."""
    return tuple(target.split(".")[1:])


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Subscript):
        node = node.value
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def _statement_text(node: ast.stmt, lines: list[str]) -> str:
    """The statement's own lines: all of them for a simple statement, the header only for a compound one."""
    body = getattr(node, "body", None)
    end = body[0].lineno - 1 if body else node.end_lineno
    return "\n".join(lines[node.lineno - 1 : end])


def parse_source(path: Path, package: Package) -> Source:
    text = read_text(path)
    return Source(path=path, package=package, tree=parse_python(path, text), text=text)


def _package_for(path: Path, layout: Layout, known: dict[Path, Package]) -> Package:
    root = package_root(path)
    if known and root not in known:
        first = next(iter(known))
        raise MeasureError(
            f"{path}: belongs to package {root.name!r}, but this run measures {first.name!r} ({first}).\n"
            "One package per run; the module graph has no meaning across two."
        )
    return known.setdefault(root, Package.at(root, layout))


def parse_sources(files: list[Path], layout: Layout) -> list[Source]:
    foreign = [path for path in files if language_of(path) != "py"]
    if foreign:
        raise MeasureError(
            f"{foreign[0]}: boundaries.py measures Python only in this version.\n"
            "For a TypeScript tree run dependency-cruiser (npx depcruise --validate src) instead."
        )
    known: dict[Path, Package] = {}
    return [parse_source(path, _package_for(path, layout, known)) for path in files]
