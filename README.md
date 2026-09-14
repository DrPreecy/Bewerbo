# Bewerbo

Ready-to-run Bewerbungsystem for dual-study application workflows:
- Profil-Interview → Master-Profil
- Job-Research/Scoring/Decision
- CV + Anschreiben Varianten (v1..v5)
- Quality checks + output package

## Project layout

- `bewerbo_tool/` - engine, domain logic, executors, service, CLI
- `workflows/v1/bewerbo_application_process.json` - Bewerbo main process
- `assets/input/bewerbo_sample_input.json` - starter input payload
- `assets/templates/` - master CV and cover-letter templates
- `tests/` - unit/integration/regression-style tests

## Quick start

1. Create an input file:

```json
{
  "item_id": "123",
  "payload": "  sample payload  "
}
```

2. Start the Bewerbo process:

```bash
python -m bewerbo_tool.cli \
  --spec /home/runner/work/Bewerbo/Bewerbo/workflows/v1/bewerbo_application_process.json \
  --state state/runs.json \
  start \
  --input /home/runner/work/Bewerbo/Bewerbo/assets/input/bewerbo_sample_input.json \
  --wait \
  --idempotency-key candidate-max-001
```

`start` runs asynchronously by default; use `--wait` (optionally with `--timeout`) to block until completion.

3. Check status:

```bash
python -m bewerbo_tool.cli \
  --spec /home/runner/work/Bewerbo/Bewerbo/workflows/v1/bewerbo_application_process.json \
  --state state/runs.json \
  status \
  --run-id <run-id>
```

4. Control run:

- Pause: `... pause --run-id <run-id>`
- Resume: `... resume --run-id <run-id>`
- Cancel: `... cancel --run-id <run-id>`
- Re-run failed step: `... rerun-failed --run-id <run-id> --wait`

5. Metrics:

```bash
python -m bewerbo_tool.cli \
  --spec /home/runner/work/Bewerbo/Bewerbo/workflows/v1/bewerbo_application_process.json \
  --state state/runs.json \
  metrics
```

## Output structure

`final_output` includes:
- `master_profile`
- `rejection_analysis` (KO risks + mitigation)
- `scored_jobs`
- `classified_jobs` (`apply`/`optional`/`skip`)
- `decision_summary`
- `application_packages` (5 quality variants per selected job)
- `quality_report`

## Security and reliability notes

- Input validation is enforced from workflow `input_schema.required`.
- String sanitization removes low ASCII control characters from configured fields.
- Sensitive audit fields are recursively redacted for names containing `secret`, `token`, or `password`, and explicit keys like `api_key`, `private_key`, `access_key`, `client_secret`, and `authorization`.
- Max concurrent runs are bounded by the service semaphore.
- Failed runs retain step-level status and errors for deterministic resume/rerun behavior.
