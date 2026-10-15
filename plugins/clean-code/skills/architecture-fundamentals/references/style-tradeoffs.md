# Style and communication trade-offs

Read when a task chooses an architecture style or changes distribution,
communication, or data topology. Book basis: chapters 9-20 and 27.
These selection prompts are a synthesis, not the book's rating tables.

## Compare concrete candidates

First establish the driving characteristics and hard constraints. Keep the
candidate set small and relevant. Include retaining the current structure
with a targeted repair when viable. Do not treat microservices as a maturity
level, a monolith as technical debt, or a popular technology as a requirement.

| Candidate | Reason to consider it | Cost or condition to investigate |
|---|---|---|
| Layered architecture | Technical responsibility separation and straightforward workflows | Changes spanning layers, pass-through calls, coupled deployment and scaling |
| Modular monolith | Domain encapsulation with local calls and a single deployment | Enforced module contracts and data access; shared release, process, and capacity limits |
| Pipeline | A sequence of reusable transformations | Stage contracts, ordering, bottlenecks, backpressure, and failure recovery |
| Microkernel | A stable core with variable features or integrations | Plugin contracts, version compatibility, lifecycle, and isolation; plugins do not imply separate processes |
| Service-based architecture | Coarse domain services with selective deployment independence | Shared-data coupling, service contracts, and distributed operations; examine actual database ownership |
| Event-driven architecture | Bursts, asynchronous workflows, multiple reactions to events | Delayed completion, ordering, duplicates, replay, schema evolution, error ownership, and tracing |
| Space-based architecture | A demonstrated state or database bottleneck under extreme load | Partitioning, memory cost, replication lag, persistence and recovery; validate realistic volumes |
| Orchestration-driven SOA | Heterogeneous integration and centrally coordinated workflows | Shared service churn, orchestration bottlenecks, coordination cost, and operational concentration |
| Microservices | Independently evolving domains needing separate deployment or operational characteristics | Data ownership, network failures, consistency, observability, testing, and team capacity to operate them |

Use only relevant rows. Domain decomposition, technical layering, event
communication, and deployment structure describe different dimensions and
may coexist. An architecture pattern such as CQRS solves a narrower problem;
it is not a reason to select an entire system style. CQRS separates command
and query models; event sourcing stores changes as the authoritative
history. Neither implies the other. Introduce either only for a named need,
with its storage, consistency, evolution, and recovery costs.

## Distribution adds failure modes

For a critical remote interaction, establish timeout and deadline behavior,
retry policy, duplicate effects, partial failure, overload, observability,
and recovery responsibility. Consider real network latency, bandwidth,
security, changing topology, and operational ownership. A timeout does not
prove that a remote action did not happen.

Trace the business operation through the data path. Separate deployment is
not operational independence if the workflow still requires a coordinated
schema migration or synchronous availability of every downstream service.
A shared database is not automatically forbidden, but it changes the
independence and consistency claims the design can support.

Check whether the team can build, release, monitor, diagnose, and recover
each proposed unit. A design that requires unavailable operational capacity
is not viable merely because its topology matches a book diagram. Cloud
services may move responsibilities to a provider; they do not remove costs,
quotas, failure modes, or the need to check the actual service contract.

## Communication choices

**Synchronous calls** offer an immediate response and simpler local control
flow. They also couple latency and availability while the caller waits.
Budget the complete call chain and explain behavior when the dependency is
slow. More services can increase latency without increasing useful capacity.

**Asynchronous messaging** can buffer bursts and separate processing rates.
It requires explicit completion semantics, backlog capacity, maximum useful
message age, and recovery. Sustained ingress above processing capacity
still accumulates debt. A broker is itself a dependency.

Transport and workflow synchrony are different. A caller that sends through
a queue and waits for a reply still depends on downstream latency and
availability. An acknowledgment of acceptance does not prove completion of
the business operation; define the completion signal and recovery state.

Do not reduce messaging to “queues are decoupled, topics are coupled,” or
the reverse. Check the broker's subscription, persistence, acknowledgment,
ordering, retry, and retention configuration. Transport delivery guarantees
do not establish exactly-once business effects. For important effects,
inspect idempotency or deduplication and the database/publication protocol.
These are implementation checks, not properties inferred from a style name.

**Orchestration** puts workflow coordination in an explicit owner. It can
simplify sequencing and recovery while concentrating knowledge and runtime
dependencies. **Choreography** distributes reactions and can reduce central
coordination while obscuring end-to-end progress, failure handling, and
business rules. Compare the actual workflow; hybrid coordination is valid.

## Make the recommendation falsifiable

Explain the highest-priority driver each option serves, the consequence it
sacrifices, and the evidence behind that judgment. Do not add positive cells
or average the book's style ratings into a winner. A single hard constraint
can outweigh several secondary advantages.

For a migration, name the boundary to change first, compatibility during the
transition, data movement and reconciliation, and rollback or forward-repair
limits. Prefer an experiment or incremental boundary change when it can
resolve the important uncertainty. A wholesale rewrite needs its own
justification; a style comparison does not provide one automatically.
