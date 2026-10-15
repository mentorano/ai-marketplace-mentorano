# GCP structured logging

Cloud Run collects container stdout/stderr. A JSON object per physical line
lets Cloud Logging recognize structured fields without adding a logging SDK.
Browser console output is not automatically sent to GCP.

Useful fields are not a universally mandatory payload. Add special fields
only when their values are available and meaningful:

| Field | Meaning |
|---|---|
| `severity` | GCP level such as DEBUG, INFO, WARNING, ERROR or CRITICAL |
| `message` | Readable fixed message with ordered trailing values |
| `timestamp` | UTC RFC 3339 timestamp |
| `httpRequest` | Method, safe request URL/path, status and latency such as `0.0673s` |
| `logging.googleapis.com/trace` | `projects/<project>/traces/<trace_id>` |
| `logging.googleapis.com/spanId` | Span ID as 16 hex digits |
| `logging.googleapis.com/trace_sampled` | Boolean sampling value when known |
| `event`, `logger`, `request_id` | Application fields for exact filtering and context |

Do not treat the entire Cloud Logging LogEntry schema as fields that the
application must emit. Resource/revision metadata normally comes from the
platform. Verify current behavior for the target runtime/collector before
claiming a field is automatically promoted.

Read `X-Cloud-Trace-Context` only for validated trace/span/sample parts. Use
configured project identity. Convert a decimal span ID to 16-digit hex, validate
its range, and do not emit incomplete resource names or the raw header.

Preserve stack traces in the error entry. Where Error Reporting reads `message`,
include the actual stack there at the tail. Do not double-escape stack newlines
inside the message; encode the outer JSON once. Keep `exception` as a structured
field if useful and supported by the adapter. Verify the target Error Reporting
format rather than assuming any JSON error string creates an error group.

Typed fields let Logs Explorer filter without regexp:

```text
resource.type="cloud_run_revision"
jsonPayload.event="http.request"
jsonPayload.path="/api/search"
jsonPayload.status=500
```

HTTP completion summaries may remain INFO even when `status` is 500. To find
those, filter `jsonPayload.status=500`; ERROR filters select exception records.
Keep metadata out of the human message unless needed; any included request IDs
or timestamps are variable values and belong at its end.

## Size risks and query policy

Cloud Logging currently limits an ordinary LogEntry to approximately 256 KB;
this is a platform constraint, not a truncation policy. Recheck current limits
and the target collector's behavior. Preserve all selected/redacted values.
When an event may exceed the limit, report its call site, expanding fields and
encoded UTF-8 size estimate to the developer. Do not truncate, split, sample or
remove data automatically; ask the developer to review its data/delivery design.
Do not promise successful ingestion of an oversized record.

Prefer equality/numeric filters on typed fields and restrict resource/time.
Ordering values in `message` supports reading and stable text prefixes, but
does not itself guarantee query performance. Optionally record the framework's
route template as separate `route` data, such as `/invoices/{invoice_id}`.
Keep the safe actual path separately; never label a raw path `http.route`.

Authoritative references (check again when the target runtime or fields change):

- [Cloud Run logging](https://docs.cloud.google.com/run/docs/logging)
- [Structured logging and special fields](https://docs.cloud.google.com/logging/docs/structured-logging)
- [Error Reporting formats](https://docs.cloud.google.com/error-reporting/docs/formatting-error-messages)
- [Claude Code skills](https://code.claude.com/docs/en/skills)
- [Claude Code plugin layout](https://code.claude.com/docs/en/plugins-reference)

- [Cloud Logging quotas and limits](https://cloud.google.com/logging/quotas)
- [Logging query optimization](https://docs.cloud.google.com/logging/docs/view/logging-query-language)
- [OpenTelemetry HTTP route convention](https://opentelemetry.io/docs/specs/semconv/http/http-metrics/)
