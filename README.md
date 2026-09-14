# Bewerbo

Config-driven workflow automation tool with run state persistence, retries, idempotency, resume support, controls, and audit logging.

## Project layout

- `/home/runner/work/Bewerbo/Bewerbo/bewerbo_tool` - engine, models, executors, service, CLI
- `/home/runner/work/Bewerbo/Bewerbo/workflows/v1/default_process.json` - versioned workflow definition
- `/home/runner/work/Bewerbo/Bewerbo/tests` - unit/integration/regression-style tests

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
  --spec /home/runner/work/Bewerbo/Bewerbo/workflows/v1/default_process.json \
  --state /home/runner/work/Bewerbo/Bewerbo/state/runs.json \
  start \
  --input /absolute/path/to/input.json \
  --idempotency-key item-123
```

3. Check status:

```bash
python -m bewerbo_tool.cli \
  --spec /home/runner/work/Bewerbo/Bewerbo/workflows/v1/default_process.json \
  --state /home/runner/work/Bewerbo/Bewerbo/state/runs.json \
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
  --spec /home/runner/work/Bewerbo/Bewerbo/workflows/v1/default_process.json \
  --state /home/runner/work/Bewerbo/Bewerbo/state/runs.json \
  metrics
```

## Security and reliability notes

- Input validation is enforced from workflow `input_schema.required`.
- String sanitization removes low ASCII control characters from configured fields.
- Sensitive keys in audit details (`secret`, `token`, `password`, `key`) are redacted.
- Max concurrent runs are bounded by the service semaphore.
- Failed runs retain step-level status and errors for deterministic resume/rerun behavior.
