# Python backend logs

Use the project's established logger. For structlog, keep the event fixed and
pass values as keyword arguments. For stdlib logging, use structured `extra`
fields when its existing adapter supports them. Avoid reserved `LogRecord`
names such as `message`, `name` or `filename` in stdlib `extra`.

```python
logger.info("invoice.created", filename="report.pdf", invoice_id=42)
logger.info("pdf.page.rendered", page=3, bytes=52000, ms=120)
logger.warning("summary.attempt_failed", model="m-v2",
               prompt_version="v3", code=429, attempt=2, error_type="RateLimitError")
```

The first message is `invoice created, filename: report.pdf, invoice_id: 42`.
The last message orders model/prompt first, outcome code next, attempt count
next, error detail last. A product or country `code` is instead stable context.
Use event-specific overrides when one field name has different roles.

## Shared ordering and readable values

The adapter needs the event and field names, not runtime values, to determine
order. In particular, do not decide ordering from the current status or timing:
a successful/failed event must keep the same selector prefix.

```python
import json
import re


def field_text(value):
    if isinstance(value, str):
        # After redaction; stack values use a separate preserving path.
        value = value.translate({i: f"\\x{i:02x}" for i in range(32)} | {127: "\\x7f"})
        if re.fullmatch(r"[\w./:@+%=-]+", value):
            return value
        return "'" + value.replace("'", "''") + "'"
    return json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)


def readable_message(event, fields, order):
    text = event.replace(".", " ").replace("_", " ")
    values = [f"{key}: {field_text(fields[key])}" for key in order(event, fields)]
    return ", ".join([text, *values])
```

These examples show the message contract, not a complete drop-in formatter.
Keep existing plain event sentences intact; only normalize identifier events.
Keep stack text last and preserve actual newlines inside the message when the
cloud error parser needs them. The outer JSON encoder escapes those newlines
once, so the transport still occupies one physical line.

Normalize unsupported values before encoding the whole record. `default=str`
alone does not handle circular containers or non-finite floats. Do not let a
formatting failure fall back to an unstructured logging error on stderr.

## App, stdlib and server output

Configure both structlog and stdlib, including library records. App-only
`JSONRenderer` does not convert Uvicorn/Gunicorn or third-party stdlib output.
Use the same formatter on every active diagnostic handler. Avoid wrapping an
already rendered JSON string in another JSON `message`.

When a library uses a template and positional args, retain its values at the
end. Prefer meaningful names when the template is known. Generic libraries
may require documented `arg_1`, `arg_2` fallback names. Do not guess an unknown
library's field meanings. A preformatted library message cannot be reliably
separated into a stable template and values; report that limit.

Uvicorn access records have known fields. A formatter can unpack them without
editing the dependency:

```python
client, method, target, version, status = record.args
fields = {
    "method": method,
    "path": str(target).partition("?")[0],
    "http_version": version,
    "client": client,
    "status": status,
}
```

Only use this mapping for the known access logger/template and five args.
Keep access logging disabled when the app already provides the safe request
record or the project prohibits raw server access logs. In stdlib, clearing
handlers is insufficient: `propagate=True` still reaches a parent handler.
Test the real configuration sequence: Uvicorn Config, app import/setup, then
HTTP protocol construction. Assert the effective `access_log` flag.

Gunicorn needs JSON configuration before its master starts workers. Uvicorn
reload needs the configured level/format before the supervisor starts; app
import happens too late for it. CLI helpers must read the same logging settings
as the app. Do not hard-code INFO in a separate startup config.

Preserve SQL/report output channels. Alembic `--sql` writes SQL to stdout;
write its JSON diagnostic logs to stderr so a SQL redirect stays executable.

## Request errors and tests

Bind request ID and validated trace data for the request. On unexpected errors,
log the exception while the context is bound, re-raise, then restore the prior
context. A later server ERROR otherwise loses the request ID/trace. Do not
convert application errors into successful responses or catch cancellations
as ordinary failures just for logging.

Verify actual handler output with an isolated process when global logger setup
would disturb the test runner. Parse every emitted line as one JSON object.
Check INFO/ERROR filtering for both app and libraries, exception stack retention,
no duplicate records, safe path without query values, and trace on the ERROR
entry as well as the HTTP 500 summary. Exercise concurrent requests and cleanup.

## Severity, cost and failure isolation

Use WARNING for a recoverable issue, ERROR for a failed operation and CRITICAL
when the service stops. Do not upgrade every HTTPException or cancellation to
ERROR. Preserve an intentional INFO HTTP summary plus the separate error record.

For stdlib logging, guard expensive log-only work before computing its args:

```python
if logger.isEnabledFor(logging.DEBUG):
    logger.debug("cache.snapshot", extra={"snapshot": build_safe_snapshot()})
```

For structlog, use its existing level API and early `filter_by_level` processor.
Do not use the stdlib method on an incompatible wrapper. Do not build an object
snapshot or stringify an exception before an early disabled-level check.

Redact nested fields and exception data before message/JSON rendering; check
custom `str()` results as well. Preserve stack newlines through a separate stack
path. Other untrusted strings show controls as visible escapes, without dropping
characters. Validate request IDs and other incoming context using project rules.

Keep all selected, redacted values. Avoid size/depth/item cutoffs. Test a large
string/list to verify complete output, then report any record likely to exceed
the actual destination limit. Give the developer its call site, growing fields
and measured/estimated UTF-8 record size. A size warning is not permission to
truncate or remove fields.

Simulate serializer and output-handler failures. The original application
response/exception must remain unchanged and request context must be restored.
Use a non-recursive, safe diagnostic fallback appropriate to the project; do not
fall back to printing the raw input. This contract applies to diagnostics, not
an explicit transactional audit requirement.

Sources: [Python logging optimization](https://docs.python.org/3/howto/logging.html#optimization),
[OWASP logging](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html),
[OpenTelemetry log model](https://opentelemetry.io/docs/specs/otel/logs/data-model/).
