# Bewerbo

Config-driven workflow automation tool with run state persistence, retries, idempotency, resume support, controls, and audit logging.

## Project layout

- `bewerbo_tool/` - engine, models, executors, service, CLI
- `workflows/v1/default_process.json` - versioned workflow definition
- `tests/` - unit/integration/regression-style tests

## Quick start

1. Create an input file:

```json
{
  "item_id": "123",
  "payload": "  sample payload  "
}
```

2. Start a run:

```bash
python -m bewerbo_tool.cli \
  --spec workflows/v1/default_process.json \
  --state state/runs.json \
  start \
  --input /absolute/path/to/input.json \
  --wait \
  --idempotency-key item-123
```

`start` runs asynchronously by default; use `--wait` (optionally with `--timeout`) to block until completion.

3. Check status:

```bash
python -m bewerbo_tool.cli \
  --spec workflows/v1/default_process.json \
  --state state/runs.json \
  status \
  --run-id <run-id>
```

4. Control run:

- Pause: `... pause --run-id <run-id>`
- Resume: `... resume --run-id <run-id>`
- Cancel: `... cancel --run-id <run-id>`
- Re-run failed step: `... rerun-failed --run-id <run-id>`

5. Metrics:

```bash
python -m bewerbo_tool.cli \
  --spec workflows/v1/default_process.json \
  --state state/runs.json \
  metrics
```

## Security and reliability notes

- Input validation is enforced from workflow `input_schema.required`.
- String sanitization removes low ASCII control characters from configured fields.
- Sensitive audit fields are recursively redacted for names containing `secret`, `token`, or `password`, and explicit keys like `api_key`, `private_key`, `access_key`, `client_secret`, and `authorization`.
- Max concurrent runs are bounded by the service semaphore.
- Failed runs retain step-level status and errors for deterministic resume/rerun behavior.
