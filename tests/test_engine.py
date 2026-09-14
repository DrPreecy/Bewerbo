import json
from pathlib import Path

from bewerbo_tool.engine import WorkflowEngine
from bewerbo_tool.executors import ExecutorRegistry
from bewerbo_tool.models import RunStatus
from bewerbo_tool.spec_loader import load_workflow_spec
from bewerbo_tool.storage import JsonStateStore


def _engine_and_spec(tmp_path: Path):
    state = tmp_path / "state.json"
    store = JsonStateStore(str(state))
    engine = WorkflowEngine(store=store, registry=ExecutorRegistry())
    spec = load_workflow_spec("/home/runner/work/Bewerbo/Bewerbo/workflows/v1/default_process.json")
    return engine, spec


def test_end_to_end_workflow_completes(tmp_path: Path):
    engine, spec = _engine_and_spec(tmp_path)
    run = engine.create_run(spec, {"item_id": "1", "payload": " hello "}, idempotency_key="k1")
    completed = engine.execute(spec, run.run_id)

    assert completed.status == RunStatus.COMPLETED
    assert completed.context["integration_status"] == "ok"
    assert completed.context["final_output"]["item_id"] == "1"


def test_idempotency_returns_same_run(tmp_path: Path):
    engine, spec = _engine_and_spec(tmp_path)
    run1 = engine.create_run(spec, {"item_id": "1", "payload": "x"}, idempotency_key="same")
    run2 = engine.create_run(spec, {"item_id": "1", "payload": "x"}, idempotency_key="same")
    assert run1.run_id == run2.run_id


def test_retryable_step_succeeds_after_retries(tmp_path: Path):
    spec_path = tmp_path / "retry_spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "name": "retry",
                "version": "1",
                "input_schema": {"required": ["item_id", "payload"]},
                "steps": [
                    {
                        "id": "retrying",
                        "type": "fail_n_times",
                        "retries": 2,
                        "params": {"key": "k", "failures": 2},
                    },
                    {"id": "done", "type": "emit_output", "params": {"fields": ["item_id"]}},
                ],
            }
        ),
        encoding="utf-8",
    )

    store = JsonStateStore(str(tmp_path / "state.json"))
    engine = WorkflowEngine(store=store, registry=ExecutorRegistry())
    spec = load_workflow_spec(str(spec_path))

    run = engine.create_run(spec, {"item_id": "7", "payload": "x"})
    result = engine.execute(spec, run.run_id)

    assert result.status == RunStatus.COMPLETED
    assert result.step_results["retrying"].attempts == 3


def test_metrics_include_completed_runs(tmp_path: Path):
    engine, spec = _engine_and_spec(tmp_path)
    run = engine.create_run(spec, {"item_id": "1", "payload": "x"})
    engine.execute(spec, run.run_id)
    metrics = engine.metrics()
    assert metrics["total_runs"] == 1
    assert metrics["completed"] == 1
