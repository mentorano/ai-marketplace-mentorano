# Decisions, risk, and fitness functions

Use for significant decisions, architecture risk reviews, or verification.
Book basis: chapters 6 and 19-27. The compact records below are local
workflow suggestions; reuse the project's established formats instead.

## Preserve a decision's reasons

An ADR records one consequential decision and the context needed to revisit
it. Consequential can mean broad impact, expensive reversal, or significant
trade-offs. It does not mean every implementation choice needs a file.

Include the situation, constraints and priorities; feasible alternatives;
decision and rationale; positive and negative consequences; status; and
supporting evidence. Add a revisit condition when useful. Keep accepted
history: supersede an old decision with a linked replacement rather than
rewriting the reasons the old system was built that way.

Use “proposed” for an unresolved stakeholder decision. Do not infer consent
from a meeting, a quiet reviewer, or the presence of a document. An explicit
user decision or the project's established decision process can already
provide the necessary authority; do not invent an extra approval ceremony.

Clarify the difference between a principle that guides judgment and a
decision that constrains implementation. Capture scope and an exception's
reason so that a local trade-off does not silently become a universal rule.

## Risks are scenarios, not dislike of a style

A useful risk names a triggering condition, the affected workflow, the
mechanism of failure, and the consequence. Cite the dependency, test,
incident, or requirement that supports it. Missing evidence means uncertainty,
not automatically a defect and not automatically safety.

For example, a notification backlog can exceed the product's useful delivery
window during sustained overload. Merely saying “event-driven is risky”
does not identify the capacity gap, business consequence, or possible fix.

Prioritize by plausible impact and likelihood, with confidence and time
horizon stated. Ordinal risk matrices help triage; their products are not
measured failure probabilities. Avoid a precise-looking score with no basis.

For a material risk, choose a mitigation or explicit acceptance, name the
remaining risk, and identify the next evidence that would change the
assessment. A provider SLA or financial remedy does not eliminate an
outage's effect on the business workflow.

## Verify the characteristics that matter

A fitness function evaluates an architectural property against an objective
criterion. It may be a build check, a repeatable exercise, production
observation, or a manual review with explicit criteria. A passing unit test
can contribute evidence, but does not automatically validate a system-level
characteristic.

For each important check, specify:

| Field | Required meaning |
|---|---|
| Property and scope | Which chosen driver, dependency, or invariant it evaluates |
| Scenario | Workload, relevant state, and fault or change being exercised |
| Observation | Metric, invariant, or inspectable result and collection method |
| Criterion | Project threshold or rule; mark unresolved targets explicitly |
| Execution | Where and when it runs, and who owns follow-up |
| Response | Consequence of failure and any justified exception or limitation |

Examples of different evidence:

| Concern | Suitable check | What it does not establish |
|---|---|---|
| Module encapsulation | Forbidden-import and cycle checks using the intended dependency policy | Runtime isolation, schema ownership, or end-to-end reliability |
| Performance | Representative load with tail latency, throughput, and errors | Capacity at untested volumes or under different bottlenecks |
| Asynchronous reliability | Duplicate, restart, delayed-message, and replay scenarios around business effects | Arbitrary exactly-once semantics outside the checked protocol |
| Contract compatibility | Consumer/provider compatibility across the supported release window | Correct domain behavior or all production dependencies |
| Recoverability | Restore or failure exercise with verified state and elapsed time | A recovery objective never exercised in the tested conditions |

Preserve both component and end-to-end checks when a local improvement can
harm the whole workflow. Establish a baseline and a repeatable comparison
before claiming improvement. Report skipped, unavailable, and proposed
checks separately from executed checks. Do not run load or fault injection
against a live system merely because architecture validation was requested.

## Diagrams and teams

Use a diagram to answer a specific question: context, deployment, component
ownership, or runtime sequence. Keep the abstraction level clear. Label
arrows with their relationship and direction; show relevant data ownership,
sync/async communication, and failure boundaries. A boxes-and-lines diagram
without semantics cannot validate coupling. A diagram explains structure;
the ADR preserves the reason for choosing it.

Check who changes, releases, and operates each boundary. Cross-team changes,
unclear ownership, and unavailable expertise affect architectural feasibility.
Discuss needed collaboration or ownership explicitly; do not assume that
an agent can reorganize teams. Explain technical trade-offs through the
business outcome and cost, so affected people can evaluate them.

Revisit decisions when drivers, evidence, scale, ownership, or capabilities
change. Prefer a concrete trigger over constant reconsideration. The goal
is enough oversight to preserve intended properties while allowing useful
change, not a permanent review meeting or a maximal set of gates.
