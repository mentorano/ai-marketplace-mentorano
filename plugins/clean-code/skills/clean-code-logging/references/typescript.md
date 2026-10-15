# TypeScript browser console logs

Use a central console wrapper. Emit one readable string at the selected level.
Do not stringify a whole record with `event`, `timestamp` and `data` around it.
Do not prepend a changing timestamp before the stable message. Keep any existing
remote telemetry separate; changing console format does not authorize new shipping.

## Adapter examples

Keep values in the trailing data argument at call sites:

```typescript
logger.info("api.ok", { url: "/api/search", status: 200, ms: 67.3 });
logger.info("search.executed", { scope: "customer", q_len: 8, hits: 12 });
logger.error("api.error", {
  url: "/api/search", status: 500, message: "Can't read file",
});
```

Readable outputs:

```text
api ok, url: /api/search, status: 200, ms: 67.3
search executed, scope: customer, q_len: 8, hits: 12
api error, url: /api/search, status: 500, message: 'Can''t read file'
```

`scope` changes less often than query length. `url` precedes status and time.
Build targets precede the current client build and attempts in reload logs.
Use the same project ordering policy as Python; do not maintain two drift-prone
maps. Package the shared file for the browser build and backend image.

An illustrative adapter, using the existing project's normalizer/order/value
formatter, is small:

```typescript
function emit(level: Level, event: string, data?: unknown) {
  const fields = fieldsOf(data);
  const text = /^[a-z][a-z0-9_.]*$/.test(event)
    ? event.replace(/[._]/g, " ") : event;
  const values = orderedLogFields(event, Object.keys(fields))
    .map((key) => `${key}: ${fieldText(fields[key])}`);
  console[level === "debug" ? "log" : level]([text, ...values].join(", "));
}
```

Reuse the project's debug destination rather than changing behavior just for
this example. Keep arbitrary plain event sentences intact.

A string-value formatter follows this contract:

```typescript
function stringField(value: string): string {
  // After redaction; genuine stack text uses a separate preserving path.
  value = value.replace(/[\u0000-\u001f\u007f]/g, (char) =>
    "\\x" + char.charCodeAt(0).toString(16).padStart(2, "0"));
  return /^[\p{L}\p{N}_./:@+%=-]+$/u.test(value)
    ? value : "'" + value.replace(/'/g, "''") + "'";
}
```

This is for the readable message only. Preserve finite numbers, booleans and
null as recognizable tokens. Handle `0`, `false` and empty strings by checking
`undefined`, not truthiness. Decide an explicit readable representation for
undefined, bigint and non-finite values. Error objects need their message and
stack; a generic JSON encoder often loses them. Keep error detail and stack last.

Nested objects/arrays use a complete safe representation in the value. Detect
actual cycles, not merely shared references: `{one: shared, two: shared}` is not
circular and both fields must retain their useful data. Do not mutate input
objects while serializing. Show control characters in untrusted free text as
visible escapes. Preserve genuine Error stack newlines through its separate path.
Apply redaction to nested and exception values before either rendering path.

## Verification

Spy on real console methods. Assert each call has one text argument and that
log/info/warn/error levels remain appropriate. Compare two outputs with the same
URL and different status/time; their URL prefix must match. Reverse field input
order and verify the same output. Check search scope before query length.

Exercise free text, apostrophes, empty string, zero/false/null, Error/stack,
array input, bigint, a cyclic object and shared non-cyclic objects. Confirm the
output is plain text rather than a JSON envelope. Run relevant Vitest tests,
ESLint/Prettier, TypeScript checking and the actual frontend build.

## Full output, levels and failures

Do not truncate strings, collections or stack data, and do not introduce
sampling or size/depth/item limits. Warn the developer about potentially large
console records and UI/performance effects. Identify the call site and expanding
fields; preserve full selected data while the developer reviews it.

Keep the project's level filtering before value conversion. When a disabled
level has expensive log-only work, use the wrapper's level check or lazy-data
mechanism. Do not introduce eager snapshots at call sites.

Choose levels by impact: debug diagnostics, info normal events, warn recoverable
issues, error failed operations. A validation response is not automatically an
error. Critical server shutdown severity belongs to server logging; do not invent
a browser `console.critical` method.

Test a throwing getter/custom serializer and failing console destination.
Diagnostic logging must not change the caller's result or mask an application
error. Use a safe non-recursive failure path; do not print the original raw data.
Also verify large values stay complete, controls cannot spoof messages, and
nested/exception redaction is preserved.

Source: [OWASP logging](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html).
