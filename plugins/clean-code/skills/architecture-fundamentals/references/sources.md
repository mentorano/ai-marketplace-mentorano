# Sources and adaptation notes

Primary source: Mark Richards and Neal Ford, *Fundamentals of Software
Architecture: A Modern Engineering Approach*, second edition, O'Reilly,
March 2025, ISBN 978-1-098-17551-1. [Publisher listing](https://www.oreilly.com/library/view/fundamentals-of-software/9781098175504/).

Reviewed all 27 chapters in a PDF copy.
The PDF is reflowed; the anchors below are one-based physical PDF pages,
not printed edition pages. The chapter title is the portable locator.
Selected figures and disputed examples were inspected visually; this was
not a visual inspection of every page. No book text or images are bundled.

## Provenance map

| Skill concept | Book chapters and PDF anchors |
|---|---|
| Context, architectural significance, trade-offs | 1 Introduction, 20-28; 2 Architectural Thinking, 40-45 and 62-68 |
| Cohesion, coupling and limits of structural measures | 3 Modularity, 76-107 |
| Prioritized characteristics and business translation | 4 Architectural Characteristics Defined, 109-132; 5 Identifying Architectural Characteristics, 134-158 |
| Objective criteria and fitness functions | 6 Measuring and Governing Architectural Characteristics, 159-183 |
| Scope, data dependencies, bounded contexts, runtime coupling | 7 The Scope of Architectural Characteristics, 185-198 |
| Logical components versus deployment, iterative decomposition | 8 Component-Based Thinking, 204-236 |
| Partitioning, distributed costs, failure and team topology | 9 Foundations, 244-283 |
| Layered and modular-monolith selection | 10 Layered Architecture Style, 284-302; 11 The Modular Monolith Architecture Style, 305-326 |
| Pipeline and microkernel selection | 12 Pipeline Architecture Style, 333-355; 13 Microkernel Architecture Style, 356-380 |
| Coarse services and shared-data consequences | 14 Service-Based Architecture Style, 384-409 |
| Events, acceptance versus completion, recovery and data topology | 15 Event-Driven Architecture Style, 422-470 and 487-509 |
| Memory, replication, persistence and recovery trade-offs | 16 Space-Based Architecture Style, 515-570 |
| Shared service churn and coordination | 17 Orchestration-Driven Service-Oriented Architecture, 571-597 |
| Domain independence, transactions, ownership and operations | 18 Microservices Architecture Style, 598-646 |
| Contextual style selection | 19 Choosing the Appropriate Architecture Style, 650-669 |
| Reuse, coordination, read/write separation and brokers | 20 Architectural Patterns, 670-690 |
| Decision significance, ADRs, status and oversight | 21 Architectural Decisions, 698-722 |
| Impact, likelihood, mitigation and residual risk | 22 Analyzing Architecture Risk, 726-744 and 754 |
| Diagrams with appropriate scope and audience | 23 Diagramming Architecture, 755-768 |
| Team feedback, proportional oversight, evidence and communication | 24 Making Teams Effective, 769-800; 25 Negotiation and Leadership Skills, 806-836 |
| Infrastructure, data, engineering, team and business constraints | 26 Architectural Intersections, 837-867 |
| Weighted trade-offs, reuse volatility, rationale and spectrum of choices | 27 The Laws of Software Architecture, Revisited, 868-886 |

The prioritized-driver record, evidence labels, response shape, revisit
triggers, and detailed failure-check prompts are this plugin's synthesis.
They are not prescribed templates from the authors. The existing clean-code
numerical gates are not newly validated by this book.

## Corrections and qualifications retained in the skill

| Source passage | Validation and treatment |
|---|---|
| Abstractness example, ch. 3 PDF 92 | The formula counts abstract and concrete artifacts, but the example divides by lines of code. This is an internal unit mismatch, confirmed visually. Do not implement that example. [JDepend's documented metric](https://github.com/clarkware/jdepend/blob/master/docs/JDepend.html) uses abstract classes/interfaces relative to all classes. |
| Static coupling wording, ch. 8 PDF 230 | Equates static coupling with synchronous communication, in tension with ch. 7 PDF 191-194. The skill explicitly distinguishes source/build wiring from runtime blocking and timing. |
| Bandwidth units, ch. 9 PDF 272 | The passage uses inconsistent unit notation: GBps for the larger payload, then Kbps for the smaller one. 200 bytes multiplied by 2,000 requests per second gives 400 KB/s, or 3.2 Mbit/s before overhead, using decimal units. The value 400 is consistent with KB/s; qualify this as a unit-notation error rather than a demonstrated arithmetic error. |
| Messaging guarantees, ch. 15 PDF 461-465 | Require product-specific evidence and a business-effect protocol. Publisher confirms and consumer acknowledgments do not prove exactly-once effects; retries can duplicate work. [RabbitMQ's reliability documentation](https://www.rabbitmq.com/docs/reliability) explicitly discusses duplicates and idempotent consumers. This is a checked example, not a claim about every broker. |
| Cache size and topology heuristics, ch. 16 PDF 531-534; service counts elsewhere | Treat as illustrative assumptions, not portable limits or selection gates. Measure workload, memory, consistency and recovery in the actual design. |
| CQRS, ch. 20 PDF 683-684 | The physically separate-store example is one implementation. [Fowler's CQRS description](https://martinfowler.com/bliki/CQRS.html) allows command and query models to share a database. The skill does not require separate stores or event sourcing. |
| SLA and availability risk, ch. 22 PDF 749 | The case removes a risk after finding SLAs. Our qualification: a contractual objective alone does not demonstrate runtime behavior or remove failure consequences. Keep dependency risk and evidence explicit. |
| C4 terminology, ch. 23 PDF 763 | The book calls the fourth level Class. [The creator's C4 model](https://c4model.com/) names it Code and permits more than class diagrams. The skill avoids encoding the book's terminology as a standard. |
| Availability arithmetic, ch. 25 PDF 809 | For a 365-day continuous observation year, 99.999% allows 315.36 seconds, about 5 minutes 15 seconds. The table gives 5 minutes 35 seconds. An averaged daily budget is not a per-outage guarantee. No numeric availability default is imported. |
| Queue/topic comparison, ch. 27 PDF 878-879 | Table 27-2 places poor extensibility under advantages and good extensibility under disadvantages, apparently reversed. Monitoring, permissions and scaling depend on the implementation. The skill asks for actual broker semantics rather than reusing this ranking. |

These are findings about this supplied edition, not claims of publisher-
confirmed errata. They do not amount to a fact-check of every anecdote,
technology assertion, or numerical example in the book. In particular,
vendor protocol lists, serialization anecdotes, dated AI predictions,
legal case-study assumptions, and categorical style/cloud claims are not
adopted as fundamentals and were not independently certified.

## Supporting primary sources

Michael Nygard's [Documenting Architecture Decisions](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
supports concise records with context, status, decision, and consequences,
and preserving superseded decisions. The skill extends that approach with
task-proportional comparison and explicit revisit conditions.

External pages above were checked on 2026-10-07. Consult the actual product's
current documentation when a future task depends on product capabilities.
