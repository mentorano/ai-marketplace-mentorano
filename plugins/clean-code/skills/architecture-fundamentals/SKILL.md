---
name: architecture-fundamentals
description: Use when designing or reviewing system architecture, choosing between a monolith and services, changing service or data ownership boundaries, evaluating architecture trade-offs or risks, or defining architecture characteristics, fitness functions, or architecture decision records. Covers system structure and runtime behavior. Ordinary local refactoring and source-level dependency review belong to clean-code.
---

# Architecture Fundamentals

Make architecture decisions from business drivers, constraints, and evidence.
The output is a justified decision or an evidence-backed review, not a score
for how closely a system resembles a favorite architecture style.

Adapted from Richards and Ford, *Fundamentals of Software Architecture*,
second edition (2025). The workflow is this plugin's synthesis. The book's
examples and style ratings are contextual guidance, not universal gates.
See [sources.md](references/sources.md) for provenance and caveats.

## Scope and evidence

Start with the user's decision and the existing system. Respect project
instructions, accepted decisions, vocabulary, and explicit constraints.
An architecture review does not itself authorize a rewrite, a migration,
new infrastructure, or a change in team ownership.

Inspect relevant requirements, code, deployment configuration, data access,
contracts, incidents, and measurements that are available. Distinguish
observations, stakeholder requirements, assumptions, and proposals. A source
tree alone cannot establish production latency, load, availability, cost,
or independent deployability. Mark missing evidence instead of inventing it.

Use only the depth needed for the decision. A local function edit does not
need a style comparison, ADR, or system audit. Use the sibling `clean-code`
skill for source changes and source-boundary checks; its numerical defaults
remain code-quality conventions, not proof of system fitness.

## Frame the decision

State the outcome, scope, present constraint, and why a decision is needed
now. Identify constraints that disqualify options, and preferences that
can be traded. Include team capability, delivery time, operations, and cost
when they affect feasibility. Do not infer these from repository size.

Translate business goals into a small prioritized set of architectural
characteristics: properties that materially influence the structure, such
as availability, responsiveness, changeability, or data consistency.
Separate top drivers from baseline obligations; a characteristic outside
the top drivers is not permission to ignore an applicable requirement.

For each driver, name its workflow or scope, the scenario that exercises it,
the observable outcome, and the target or unresolved target. Distinguish
normal load from bursts, service processing time from end-to-end latency,
and a test measurement from a production objective. Do not invent targets.
Read [characteristics and boundaries](references/characteristics-and-boundaries.md)
when deriving requirements, decomposing a system, or assessing coupling.

## Trace the actual boundaries

Follow a representative request or business workflow through components,
calls, messages, storage, and external dependencies. Distinguish a source
module, a deployment unit, a data owner, and a team; they need not coincide.
Use domain responsibilities and change patterns to assess cohesion.

Check source/build coupling, shared data and contracts, coordinated releases,
and runtime dependencies separately. Include synchronous calls, queues,
shared infrastructure, and failure propagation. Neither a clean import graph
nor separate containers proves independent operation. Async communication
changes coupling; it does not remove capacity limits or dependencies.

Before extracting common code across boundaries, compare the cost of
duplication with shared change, release coordination, and runtime failure.
Keep independently evolving domain models separate. Reuse stable mechanisms
when their ownership and compatibility policy justify the dependency.

## Compare and decide

Compare plausible options against the same prioritized drivers. Include the
current architecture or a smaller change when viable. A mandated platform
is a constraint: compare feasible designs within it rather than reopening
the user's choice. A hybrid can be valid when it has a clear purpose.

Read [style trade-offs](references/style-tradeoffs.md) when selecting a style
or changing distribution, communication, or data topology. Treat the style
name as a starting hypothesis, then evaluate the concrete design.

Explain the important benefit, cost, failure mode, and operational burden
of each candidate. Do not select by counting positive cells or copying star
ratings. Weight the consequences using the actual priorities. Separate a
known limitation from an untested assumption.

Recommend an option, explain what makes it preferable here, and state what
evidence or changed condition would reverse it. If an uncertainty can change
the choice, propose the smallest useful experiment or ask the specific
question. Continue work that does not depend on the missing answer.

## Verify and retain the rationale

Read [decisions and fitness](references/decisions-and-fitness.md) when
recording a significant decision, reviewing risk, or defining verification.
A fitness function is an objective evaluation of a chosen architectural
property. It can be automated or manual; it needs an observable criterion.

Tie verification to the drivers and the actual risk. Use existing project
checks where suitable. A dependency check verifies a structural rule;
load, failure, recovery, and compatibility checks answer different questions.
State what ran, what passed or failed, and what remains unmeasured. A
proposed check is not a passing result. Scope performance or failure tests
to an authorized environment.

For a consequential decision, preserve context, alternatives, rationale,
consequences, status, and a revisit trigger in the project's existing ADR
format, or provide that information in the response when no file is needed.
ADR means architecture decision record. Do not call a proposed decision
accepted unless existing authorization or project evidence supports that.

## Report proportional to the task

For a decision, explain the recommendation, drivers, comparison, accepted
costs, uncertainty, and verification. For a review, explain each supported
risk through a concrete scenario, evidence, consequence, and bounded remedy.
Keep observed defects separate from untested risks and optional improvements.

Give enough evidence for the reader to challenge the conclusion. Stop when
the requested decision or review is supported; do not generate every
reference's table or create a backlog for unrelated parts of the system.
