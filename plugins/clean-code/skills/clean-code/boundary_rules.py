"""The boundary rules and the Report they fill, for boundaries.py.

Imported only; nothing runs this file. boundaries.py keeps the command line
and the rendering; this module holds what is counted and why it is a rule.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from imports import Edge, External, Layout, Package, Place, Port, Source, SqlFile

ModuleGraph = Counter[tuple[str, str]]

# The rules. The names of the layers, core and domain modules are the Layout's.
COMPOSITION_ROOT = "main.py"
UPWARD_FROM = frozenset({"services", "models", "domain"})
PORT_LAYERS = frozenset({"services", "domain"})
HTTP_FRAMEWORKS = frozenset({"fastapi", "starlette"})
DOMAIN_FRAMEWORKS = frozenset({"fastapi", "sqlalchemy", "starlette"})


# --- Module graph -------------------------------------------------------------

@dataclass(frozen=True)
class Cycle:
    """Two modules that import each other; `closing` holds the edges in the rarer direction."""

    forward: tuple[str, str]
    forward_count: int
    backward_count: int
    closing: list[Edge]

    def row(self) -> dict[str, object]:
        return {
            "modules": list(self.forward),
            "forward": self.forward_count,
            "backward": self.backward_count,
            "closing": [edge.row() for edge in self.closing],
        }


def module_edges(edges: list[Edge]) -> ModuleGraph:
    """Imports between two different modules, counted per direction."""
    return Counter((e.src.module, e.dst.module) for e in edges if e.src.module != e.dst.module)


def cycle_graph(edges: list[Edge], package: Package) -> ModuleGraph:
    """The module graph without core and the package root; their outward edges are core_outward."""
    feature = [e for e in edges if package.is_feature(e.src.module) and package.is_feature(e.dst.module)]
    return module_edges(feature)


def _orient(a: str, b: str, graph: ModuleGraph) -> tuple[tuple[str, str], set[tuple[str, str]]]:
    """The direction with more imports is forward; the rarer one is cut. On a tie both are cut and the project picks."""
    if graph[(a, b)] == graph[(b, a)]:
        return (a, b), {(a, b), (b, a)}
    return ((a, b), {(b, a)}) if graph[(a, b)] > graph[(b, a)] else ((b, a), {(a, b)})


def mutual_pairs(edges: list[Edge], graph: ModuleGraph) -> list[Cycle]:
    pairs = sorted((a, b) for (a, b) in graph if a < b and graph[(b, a)])
    cycles = []
    for a, b in pairs:
        forward, cutting = _orient(a, b, graph)
        closing = [e for e in edges if (e.src.module, e.dst.module) in cutting]
        cycles.append(Cycle(forward, graph[forward], graph[(forward[1], forward[0])], closing))
    return cycles


def _reachable(start: str, adjacency: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    stack = [start]
    while stack:
        fresh = adjacency.get(stack.pop(), set()) - seen
        seen |= fresh
        stack.extend(fresh)
    return seen


def cyclic_modules(graph: ModuleGraph) -> list[str]:
    """Modules that can reach themselves through the module graph."""
    adjacency: dict[str, set[str]] = {}
    for a, b in graph:
        adjacency.setdefault(a, set()).add(b)
    return sorted(m for m in adjacency if m in _reachable(m, adjacency))


# --- Report -------------------------------------------------------------------

def _is_upward(edge: Edge) -> bool:
    return edge.src.layer in UPWARD_FROM and edge.dst.layer == "api"


def _is_core_outward(edge: Edge, package: Package) -> bool:
    if Path(edge.file).name == COMPOSITION_ROOT or edge.src.module not in package.layout.core:
        return False
    return package.is_feature(edge.dst.module)


def _in_domain(external: External, layout: Layout) -> bool:
    pure = external.place.module in layout.domain or external.place.layer in layout.domain
    return pure and external.framework in DOMAIN_FRAMEWORKS


def _in_services(external: External) -> bool:
    return external.place.layer == "services" and external.framework in HTTP_FRAMEWORKS


def _sql_files(sources: list[Source]) -> list[SqlFile]:
    api = [s for s in sources if s.place.layer == "api"]
    found = [SqlFile(s.file, s.sql_sites()) for s in api]
    return sorted((f for f in found if f.sites), key=lambda f: (-f.sites, f.file))


@dataclass
class Report:
    """The measures over `sources`; rows come from `kept`, module-level numbers from every source."""

    package: Package
    sources: list[Source]
    kept: list[Source]

    @property
    def layout(self) -> Layout:
        return self.package.layout

    @cached_property
    def edges(self) -> list[Edge]:
        return [edge for source in self.sources for edge in source.edges()]

    @cached_property
    def kept_edges(self) -> list[Edge]:
        return [edge for source in self.kept for edge in source.edges()]

    @cached_property
    def externals(self) -> list[External]:
        return [ext for source in self.kept for ext in source.externals()]

    @cached_property
    def graph(self) -> ModuleGraph:
        return cycle_graph(self.edges, self.package)

    @cached_property
    def modules(self) -> Counter[Place]:
        return Counter(source.place for source in self.sources)

    @cached_property
    def module_edges(self) -> ModuleGraph:
        return module_edges(self.edges)

    @cached_property
    def upward(self) -> list[Edge]:
        return [e for e in self.kept_edges if _is_upward(e)]

    @cached_property
    def cycles(self) -> list[Cycle]:
        return mutual_pairs(self.edges, self.graph)

    @cached_property
    def cyclic_modules(self) -> list[str]:
        return cyclic_modules(self.graph)

    @cached_property
    def core_outward(self) -> list[Edge]:
        return [e for e in self.kept_edges if _is_core_outward(e, self.package)]

    @cached_property
    def framework_in_domain(self) -> list[External]:
        return [e for e in self.externals if _in_domain(e, self.layout)]

    @cached_property
    def sql_in_api(self) -> list[SqlFile]:
        return _sql_files(self.kept)

    @cached_property
    def http_in_services(self) -> list[External]:
        return [e for e in self.externals if _in_services(e)]

    @cached_property
    def ports(self) -> list[Port]:
        return [port for source in self.kept if source.place.layer in PORT_LAYERS for port in source.ports()]

    @cached_property
    def summary(self) -> dict[str, int]:
        return {
            "files": len(self.sources),
            "row_files": len(self.kept),
            "modules": len({place.module for place in self.modules}),
            "upward": len(self.upward),
            "cycles": len(self.cycles),
            "cyclic_modules": len(self.cyclic_modules),
            "core_outward": len(self.core_outward),
            "framework_in_domain": len({e.file for e in self.framework_in_domain}),
            "sql_in_api": len(self.sql_in_api),
            "sql_sites": sum(f.sites for f in self.sql_in_api),
            "http_in_services": len({e.file for e in self.http_in_services}),
            "ports": len(self.ports),
        }


def _kept(sources: list[Source], changed: set[Path] | None) -> list[Source]:
    if changed is None:
        return sources
    return [s for s in sources if s.path.resolve() in changed]


def build_report(sources: list[Source], layout: Layout, changed: set[Path] | None = None) -> Report:
    """Measure every source; rows come from the changed files only when `changed` is given."""
    package = sources[0].package if sources else Package(Path("."), layout, frozenset())
    return Report(package, sources, _kept(sources, changed))
