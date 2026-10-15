---
name: clean-code-logging
description: Use when asked to fix, standardize, audit or reorder application logs, make Python backend logs JSON for GCP or AI agents, or make TypeScript browser console logs short and readable. Implements stable message prefixes, named trailing values ordered by how often they change, and safe backend/frontend logging adapters. Do not use just because an unrelated source edit contains a logger.
---

# Clean Code — Logging

Fix the logging code, not just the example output. With no path, inspect the
current repository. A path narrows the work. `audit` reports findings without
editing. Otherwise implement and verify the requested logging changes.

Read the project's `AGENTS.md`, `CLAUDE.md` and domain context first. Explicit
user choices win. Work through the existing logger and formatter; do not
replace the logging framework or add a log ingestion endpoint just to enforce
these rules. This skill does not authorize commit, push, deploy or account changes.

## Message contract

Use short, plain words and a fixed main message with no values in it:

```text
<fixed message>, <field>: <value>, <field>: <value>
http request, method: GET, path: /api/search, status: 200, duration_ms: 67.3
search executed, scope: customer, q_len: 8, hits: 12
upload failed, file_id: 42, error: 'File is missing'
```

All variable values go after the fixed message. Use named fields. Keep stable
`event` identifiers for backend queries. Pass values separately to the logger;
never scatter f-strings, template substitutions or concatenated values through
the first argument. Do not rename events or field names without updating their
callers, dashboards, queries and tests.

### Order by stability

Analyze the meaning of each field in its event. Put the fields that usually
stay the same for comparable operations first. Put the fields that change more
often last. A starting order is:

| Earlier → later | Examples |
|---|---|
| Operation and stable selectors | `method`, `path`, `scope`, `kind`, `model`, `prompt_version` |
| Variable inputs | `q_len`, input options; length only for sensitive searches |
| Target object | `invoice_id`, `row_id`, source and target IDs |
| Actor and per-call context | `actor_id`, client, session id when approved for logging |
| Outcome | `status`, `ok`, `access_denied`, changed fields |
| Counts and measurements | `hits`, `rows`, `attempts`, bytes, accuracy |
| Time | `duration_ms`, `elapsed_ms`, `took_ms` |
| Error details and stack | `error_type`, `error`, `exception`, `stack` |

This is a guide, not a universal ranking of names. `code` can be a stable
product or country code or a changing error code. A list of returned IDs is a
result, not a fixed target. Classify these per event. Within an equal stability group, use a
deterministic order. Alphabetical order is a tie-breaker, never the main rule.

Use one maintained ordering policy for shared BE/FE field names when both
exist. Include that asset in every required build/runtime stage. Unknown
library fields need a documented fallback; do not invent their semantics.

### Values and quotes

In the readable message, leave numbers, boolean/null and simple tokens unquoted:
`status: 200`, `method: GET`, `path: /api/search`, `file: report.pdf`.
Use single quotes for free text and empty strings: `error: 'File is missing'`,
`note: ''`. Double a literal apostrophe: `error: 'Can''t read file'`.
Do not wrap every string in double quotes just because the transport is JSON.

Actual JSON fields retain normal JSON double quotes, escaping and data types.
Use a real JSON encoder. Never create JSON by joining strings or removing
required escapes. Keep useful values for Error objects, falsey values, arrays,
bigint/custom types and circular data; normalize unsupported JSON values safely.

### Severity and logging cost

Choose severity by impact, not by the presence of an exception: DEBUG for
useful diagnostics, INFO for normal events, WARNING for a recoverable problem,
ERROR for a failed operation, CRITICAL for a failure that stops the service.
Keep the project's consistent HTTP summary policy: an INFO completion record
may include status 500 when a separate ERROR record describes the failure.
Expected validation responses and client cancellations are not automatically
ERROR records. Do not duplicate one exception stack at every layer.

Filter disabled levels before formatting/serialization. Check the level before
expensive log-only calculations; do not add guards around every cheap call.
Diagnostic formatter or output failures must not change the application result,
mask its original exception, leak raw data or recurse through the failed logger.
Restore request context even if writing the diagnostic record fails. Test this
behavior using simulated formatter/output failures. Preserve explicit project
requirements for business/audit events; they are not ordinary diagnostics.

### Full values and large records

Keep all data selected for logging after required redaction and safe type
normalization. Do not introduce truncation, character/depth/item limits,
sampling or omission to reduce volume. Safe cycle markers are necessary for
non-serializable cycles, not permission to cut valid non-cyclic data.

Inspect potentially large records: unbounded strings, collections, object
graphs, exception chains and repeated stacks. When a record can become very
large, warn the developer. Identify the event/call site, expanding fields and
known or estimated encoded size; state uncertainty and the destination limit.
Ask the developer to review the selected data or delivery design. Keep the
full selected values; do not silently change their contract or claim the sink
can ingest unlimited records. Complete independent work and report this open
point. For GCP size constraints, read [references/gcp.md](references/gcp.md).

### Data and errors

Do not expose passwords, credentials, auth/session tokens, raw search queries,
names, personal IDs or other protected data. Preserve existing
redaction and logging guards at every level, including exceptions. Prefer
safe IDs and lengths. Remove query values from request paths. Do not log the
raw trace header or whole request/body to gain context.

Redact before building both the readable message and structured output.
Cover nested values, exception messages and custom serialization results.
Validate external context fields. Render CR/LF, terminal escape sequences and
other control characters visibly in untrusted free text so they cannot spoof
records or alter display. Preserve genuine exception stack line breaks; encode
the outer backend JSON once. This is safe representation, not truncation.

Keep request ID and trace context consistent across app and library records.
Log an unhandled request error while that context is still active, then re-raise
and restore context. Preserve level filtering in startup, worker, reload and
CLI paths. A shared configuration must not silently re-enable disabled access
logging or duplicate records.

## Implement and verify

Inventory all in-scope logging paths before editing: call sites and aliases,
bound/context fields, helpers with `**kwargs`, stdlib/library records, server
bootstrap, warnings and exception paths. Distinguish diagnostic logs from CLI
reports, build tool output, persisted business/audit events and platform-owned
logs. State scope gaps; do not describe a partial conversion as complete.

Record the current format and each event's field meanings/order. Use `rg` to
find calls and framework configuration. Use the companion `clean-code` and
language skills for measurements and code shape; their instructions are in
`../clean-code/SKILL.md`, `../clean-code-python/SKILL.md` and
`../clean-code-typescript/SKILL.md` relative to this skill directory.

Implement the shared contract in the existing central adapters. Adjust calls
only when values are embedded in the main text, field names are unclear, or
an event needs a contextual ordering rule. Preserve structured fields and types.
Update project logging guidance and queries if their contract changes.

Verify behavior, not just string literals in source:

- Compare two HTTP records with the same method/path and different status/time.
- Compare searches with one scope and different query lengths/hit counts.
- Reverse input field order; the output order must stay the same.
- Check short tokens, free text, apostrophes and empty/falsey values.
- Exercise exceptions, JSON parsing/one physical line, and concurrent context cleanup.
- Exercise library/startup/reload/CLI level filtering and disabled access logs.
- Exercise browser levels, Error/stack and supported structured values.
- Check control characters, nested/exception redaction and external context.
- Simulate formatter/output failures without changing the application result.
- Check disabled levels skip expensive log-only work.
- Check full large values remain intact; report possible destination-size risks.
- Verify shared policy assets in the actual local and container build layouts.

Run the project's relevant tests, lint, typecheck/build and clean-code gates.
For GCP queries, prefer typed fields with resource/time restrictions over
parsing the human message. Message field order improves readability; it does
not guarantee faster queries. Optionally add a framework-provided route template
for grouping, separately from the safe actual path. Do not invent a route
from raw IDs or impose an OpenTelemetry SDK just for this format.

Review correctness, design and readability. Use an independent review when
requested and delegation is available. Recheck confirmed fixes. Report the
scope, examples, test results, remaining limits and review findings using the
project's communication style. Do not hard-code a particular reviewer/model.

## Backend — Python

Write application diagnostics as one JSON object per physical line. Route
stdlib/library and server logs through the same formatter as the app. Use
`message`, `severity`, UTC `timestamp`, stable `event`, `logger` and request
context; preserve useful typed fields. Keep exception stack data in the error
entry, not separate unstructured lines.

```python
logger.info("http.request", method="GET", path="/api/search", status=200, duration_ms=67.3)
logger.info("search.executed", scope="customer", q_len=8, hits=12)
logger.error("upload.failed", file_id=42, error="File is missing")
```

Read [references/python.md](references/python.md) for implementation examples,
stdlib/server integration and startup/error checks. For GCP, also read
[references/gcp.md](references/gcp.md).

## Frontend — TypeScript

Browser console logs are readable text, without a JSON envelope or timestamp
prefix. Keep the console level. Put all values at the end under the same
stability and quoting rules. Backend TypeScript/Node is still a server; do not
apply this browser transport choice to it.

```typescript
logger.info("api.ok", { url: "/api/search", status: 200, ms: 67.3 });
// api ok, url: /api/search, status: 200, ms: 67.3
logger.error("api.error", { url: "/api/search", status: 500, message: "File is missing" });
// api error, url: /api/search, status: 500, message: 'File is missing'
```

Read [references/typescript.md](references/typescript.md) for a console adapter,
ordering/quoting examples and behavior checks. Browser stacks may be multiline;
one physical JSON line is the backend transport requirement.
