# Characteristics and boundaries

Use this reference to derive architectural requirements, choose component
boundaries, or explain why apparently independent parts remain coupled.
Book basis: chapters 2-8; see [sources](sources.md).

## Turn a goal into a testable driver

An architectural characteristic affects the system's structure and success,
not merely one local implementation choice. Business vocabulary needs
translation: a promotion can imply burst handling, an acquisition can imply
integration and changeability, and expensive downtime can imply recovery
and availability. Confirm the inference with available requirements.

Choose only the characteristics that distinguish the options in this
decision. Identify conflicts explicitly: tighter consistency can increase
coordination; isolation can add deployment and operational cost; stronger
security controls can affect usability and latency. Avoid a wish list in
which everything has the same priority.

Use a compact record when helpful:

| Driver and priority | Workflow and scenario | Observable target | Evidence or uncertainty |
|---|---|---|---|
| Responsiveness | Checkout during an expected traffic burst | End-to-end percentile and error rate under specified load; target supplied by requirements | Production traces, representative test, or unknown |
| Recoverability | Processing restarts after an interrupted write | Accepted data loss and restoration time | Recovery exercise, documented objective, or unknown |
| Changeability | A pricing rule changes | Affected components, contracts, tests, and deployments | Change history and dependency trace |

These are prompts for project values, not defaults. Record workload, data
volume, observation window, and environment when reporting measurements.
Scalability concerns capacity as load grows; elasticity concerns adapting
capacity as load changes. Neither means that adding a queue fixes overload.

## Identify cohesive responsibilities

Start from domain workflows, rules, actors, and ownership. Test candidate
boundaries against representative changes and the transactions they must
preserve. Iterate the component map when a workflow exposes a hidden
dependency. A component is not automatically a service.

Technical layers can separate responsibilities within a deployment. Domain
partitioning can localize business change. Combine them where useful;
folder names, one component per entity, and a list of CRUD operations do not
by themselves establish good cohesion. Do not split merely to make module
sizes equal, or distribute modules merely to enforce encapsulation.

For each important boundary, establish what it owns, its public contract,
what remains private, and how callers change when that contract changes.
Source visibility and architecture tests can protect these rules inside a
monolith as well as between services.

## Examine coupling by mechanism

| Mechanism | Evidence to inspect | Question that changes the decision |
|---|---|---|
| Source/build | Imports, shared libraries, generated clients, version policies | Does an implementation change force consumers to rebuild or coordinate? |
| Data | Reads/writes, schema ownership, joins, transaction scope, migrations | Can one owner change its data without breaking another workflow? |
| Runtime | Sync call chains, messages, external services, capacity limits | What waits, fails, or falls behind if this dependency is slow or absent? |
| Release | Deployment order, compatibility windows, rollback constraints | Can this unit deploy and roll back without a coordinated release? |
| Domain meaning | Rules and concepts shared by workflows | Is the coupling inherent in the problem, or introduced by implementation? |

Prefer lower implementation coupling across independently changing
responsibilities, while keeping closely related behavior cohesive. Coupling
is not a quantity to minimize blindly: splitting a transaction can exchange
simple local consistency for a distributed recovery protocol.

The book uses *architecture quantum* to reason about the scope of
architectural characteristics: a cohesive unit that can operate and deploy
independently with its necessary dependencies. Treat it as an analysis aid,
not a count derived from folders, processes, or service names. State which
dependency or property defines the boundary being discussed. Shared schemas,
runtime bottlenecks, and synchronous chains can widen that scope. A common
library and a common live database have different consequences; trace the
actual versioning and failure mechanisms rather than equating them.

## Data and transactions belong in the architecture

Identify the authoritative owner, allowed readers and writers, and the
business invariant for each relevant data set. Decide which updates must
commit together and which may converge later. Specify tolerated staleness
and recovery behavior from requirements, not a style label.

A shared database can simplify transactions and queries while coupling
migrations, load, access, and failures. Separate stores can improve ownership
and isolation while introducing propagation, duplicated data, reconciliation,
and cross-owner queries. Separate schemas, shared servers, and separate
database deployments are different boundaries. Describe the actual choice.

Before moving a transaction across services, explain failure after each
step, duplicate work, compensation where valid, and the point after which
an action cannot simply be undone. Do not promise atomicity across a local
database commit and message publication without a concrete protocol.
Compensation can also fail: identify the remaining partial state, safe retry
or repair behavior, and the owner responsible for reconciliation.

## Reuse and measurement limits

Similar code in different domain contexts can represent different policies.
Compare separate implementations, a versioned library, and a shared service
when reuse crosses ownership boundaries. A library introduces upgrade and
compatibility work; a service introduces a runtime dependency; duplication
introduces maintenance and divergence risk. Low volatility and a stable
abstraction favor reuse. One shared domain model is not automatically the
right abstraction for all contexts.

Metrics locate questions; they do not decide whether the design meets its
drivers. State scope, units, tool, and counting convention. Do not prescribe
an abstractness, component-size, or coupling target without a project reason.
Do not increase abstraction or split code solely to optimize a metric.
The sibling clean-code scripts measure selected source properties. They do
not measure data ownership, production behavior, or independent deployment.
