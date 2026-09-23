# Clean Architecture review

Four phases, restated for an agent from Robert C. Martin's `architect` role
in `unclebob/swarm-forge` (`swarmforge/roles/architect.prompt` on the
`six-pack` and `four-pack` branches; `main` carries no architect role). The
phases follow Clean Architecture ch. 22 (the Dependency Rule, Interface
Adapters) and ch. 23 (Presenters and Humble Objects). Run them in this
order whenever a change touches a module boundary, adds an import between
layers, or adds a module.

## Vocabulary

- **High-level module**: far from IO. Rules, decisions, domain types.
- **Low-level module**: near IO. HTTP handlers, database access, file
  system, network, UI rendering, framework glue.
- **Adapter**: a low-level module that translates between the outside world
  and a high-level module.
- **Boundary**: the line an import crosses between the two.

## Phase 1 — UI / core separation

First question: can the core behaviour be tested without the UI or IO? If
not, the separation is missing; start there.

Take each value the UI or the route handler shows, and each decision it
makes. Look for the domain function that owns it. The adapter asks that
function and translates the answer into HTML, JSON, bytes, or copy. It does
not redo the rule. Formatting is the adapter's job (dates, currency, labels, a greyed
button); the decision behind the formatting is not.

Smells: a handler that computes a total, a component that decides whether a
user may edit, a template that evaluates a business rule. Fix: move the
rule into the high-level module, call it from the adapter.

**A correct import direction does not excuse duplicated logic.** When the
adapter computes an answer that a domain function already gives, the
adapter is wrong. The mirror case is wrong too: a domain function that only
the tests call, while the adapter keeps its own copy of the rule. Make the
adapter call the function, or remove the function.

## Phase 2 — Dependency rule

Source code dependencies point inward. A high-level module never imports a
volatile low-level one. A low-level module calls inward through a narrow
interface the high-level module owns. A dependency on a stable platform
facility, such as the standard library, is not the smell.

Smells: a domain module importing the ORM, the HTTP framework, a client
library; a service that takes the framework's request object (an
`HttpRequest`, a `fastapi.Request`) instead of a plain request model it
owns; a business rule that reads an environment variable; an import cycle
across a boundary. Fix: define the
interface in the high-level module (a protocol, an abstract class, a
function type), implement it in the adapter, inject it.

Check with the import graph, not with the folder names. A file in
`services/` that imports `fastapi` is an adapter regardless of the folder.

## Phase 3 — Information hiding

A module exposes concepts, not its representation. No persistence shape,
framework type, or transport format crosses a boundary; what crosses is a
simple, isolated data structure in the form the inner circle wants.

Smells: an ORM row or entity handed across a boundary in either direction;
a Pydantic request model passed into a domain function; a component that
knows the JSON field names of the backend; a `dict[str, Any]` or
`Record<string, unknown>` at a boundary whose keys the receiver has to
know. Clean Code ch. 8 is explicit about the last one: do not pass a map
across a boundary, and do not return one from or accept one into a public
API; keep it inside the class that uses it. Fix: a typed value at the
boundary (a dataclass, a domain model, a discriminated union), translated
in the adapter; the ORM and the transport mapping stay in the outer layer.

## Phase 4 — Local quality at the boundary

The usual code-level review, aimed at the code on each side of the
boundary: naming, branching, repeated code, failure handling and corner
cases. The adapter is thin; the
translation is explicit. Duplication across a boundary is judged
differently from duplication inside a module: only true duplication counts,
where every change to one instance forces the same change to the other. Two
similar views, queries or schemas that serve different use cases and will
change for different reasons stay apart. An error crosses the boundary in the form the
inner module defines: the adapter turns an external failure into a domain
error on the way in and a domain error into a transport error on the way
out. A domain module never names a transport or framework error type.

## Automated checks

When the project has a dependency checker, forbidden-import rule, or
import-cycle check, run it. Its allowed-dependency list records the design
the team wants; the imports in the code today may be mistakes. When the
correct fix is a new inward call, edit the list to allow it. When an edit
to the list would allow an outward call or a cycle, the edit is the
mistake. When the project has no such check, add a lightweight one when
practical; where the language can enforce visibility itself, prefer that to
a tool that runs after the build.
