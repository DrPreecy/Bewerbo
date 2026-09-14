import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from bewerbo_tool.engine import WorkflowEngine
from bewerbo_tool.executors import ExecutorRegistry
from bewerbo_tool.models import RunStatus
from bewerbo_tool.spec_loader import load_workflow_spec
from bewerbo_tool.storage import JsonStateStore


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestEngine(unittest.TestCase):
    def _engine_and_spec(self, base: Path):
        state = base / "state.json"
        store = JsonStateStore(str(state))
        engine = WorkflowEngine(store=store, registry=ExecutorRegistry())
        spec = load_workflow_spec(str(REPO_ROOT / "workflows" / "v1" / "default_process.json"))
        return engine, spec

    def test_end_to_end_workflow_completes(self):
        with tempfile.TemporaryDirectory() as td:
            engine, spec = self._engine_and_spec(Path(td))
            run = engine.create_run(spec, {"item_id": "1", "payload": " hello "}, idempotency_key="k1")
            completed = engine.execute(spec, run.run_id)

            self.assertEqual(completed.status, RunStatus.COMPLETED)
            self.assertEqual(completed.context["integration_status"], "ok")
            self.assertEqual(completed.context["final_output"]["item_id"], "1")

    def test_idempotency_returns_same_run(self):
        with tempfile.TemporaryDirectory() as td:
            engine, spec = self._engine_and_spec(Path(td))
            run1 = engine.create_run(spec, {"item_id": "1", "payload": "x"}, idempotency_key="same")
            run2 = engine.create_run(spec, {"item_id": "1", "payload": "x"}, idempotency_key="same")
            self.assertEqual(run1.run_id, run2.run_id)

    def test_retryable_step_succeeds_after_retries(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            spec_path = base / "retry_spec.json"
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

            store = JsonStateStore(str(base / "state.json"))
            engine = WorkflowEngine(store=store, registry=ExecutorRegistry())
            spec = load_workflow_spec(str(spec_path))

            run = engine.create_run(spec, {"item_id": "7", "payload": "x"})
            result = engine.execute(spec, run.run_id)

            self.assertEqual(result.status, RunStatus.COMPLETED)
            self.assertEqual(result.step_results["retrying"].attempts, 3)

    def test_metrics_include_completed_runs(self):
        with tempfile.TemporaryDirectory() as td:
            engine, spec = self._engine_and_spec(Path(td))
            run = engine.create_run(spec, {"item_id": "1", "payload": "x"})
            engine.execute(spec, run.run_id)
            metrics = engine.metrics()
            self.assertEqual(metrics["total_runs"], 1)
            self.assertEqual(metrics["completed"], 1)

    def test_pause_request_pauses_before_next_step(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            spec_path = base / "pause_spec.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "name": "pause",
                        "version": "1",
                        "input_schema": {"required": ["item_id", "payload"]},
                        "steps": [
                            {"id": "first", "type": "transform", "params": {"mappings": {"a": "payload"}}},
                            {
                                "id": "retrying",
                                "type": "fail_n_times",
                                "retries": 2,
                                "backoff_seconds": 0.05,
                                "params": {"key": "pause", "failures": 2},
                            },
                            {"id": "last", "type": "emit_output", "params": {"fields": ["item_id"]}},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            store = JsonStateStore(str(base / "state.json"))
            engine = WorkflowEngine(store=store, registry=ExecutorRegistry())
            spec = load_workflow_spec(str(spec_path))
            run = engine.create_run(spec, {"item_id": "8", "payload": "x"})

            thread = threading.Thread(target=lambda: engine.execute(spec, run.run_id))
            thread.start()
            time.sleep(0.03)
            engine.request_action(run.run_id, "pause")
            thread.join(timeout=2)

            paused = store.get_run(run.run_id)
            self.assertIsNotNone(paused)
            self.assertEqual(paused.status, RunStatus.PAUSED)

    def test_cancel_request_cancels_before_next_step(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            spec_path = base / "cancel_spec.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "name": "cancel",
                        "version": "1",
                        "input_schema": {"required": ["item_id", "payload"]},
                        "steps": [
                            {"id": "first", "type": "transform", "params": {"mappings": {"a": "payload"}}},
                            {
                                "id": "retrying",
                                "type": "fail_n_times",
                                "retries": 2,
                                "backoff_seconds": 0.05,
                                "params": {"key": "cancel", "failures": 2},
                            },
                            {"id": "last", "type": "emit_output", "params": {"fields": ["item_id"]}},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            store = JsonStateStore(str(base / "state.json"))
            engine = WorkflowEngine(store=store, registry=ExecutorRegistry())
            spec = load_workflow_spec(str(spec_path))
            run = engine.create_run(spec, {"item_id": "9", "payload": "x"})

            thread = threading.Thread(target=lambda: engine.execute(spec, run.run_id))
            thread.start()
            time.sleep(0.03)
            engine.request_action(run.run_id, "cancel")
            thread.join(timeout=2)

            cancelled = store.get_run(run.run_id)
            self.assertIsNotNone(cancelled)
            self.assertEqual(cancelled.status, RunStatus.CANCELLED)

    def test_rerun_failed_step_recovers(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            spec_path = base / "rerun_spec.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "name": "rerun",
                        "version": "1",
                        "input_schema": {"required": ["item_id", "payload"]},
                        "steps": [
                            {
                                "id": "flaky",
                                "type": "fail_n_times",
                                "retries": 1,
                                "params": {"key": "rerun", "failures": 2},
                            },
                            {"id": "done", "type": "emit_output", "params": {"fields": ["item_id"]}},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            store = JsonStateStore(str(base / "state.json"))
            engine = WorkflowEngine(store=store, registry=ExecutorRegistry())
            spec = load_workflow_spec(str(spec_path))
            run = engine.create_run(spec, {"item_id": "10", "payload": "x"})

            first = engine.execute(spec, run.run_id)
            self.assertEqual(first.status, RunStatus.FAILED)

            recovered = engine.rerun_failed_step(spec, run.run_id)
            self.assertEqual(recovered.status, RunStatus.COMPLETED)


if __name__ == "__main__":
    unittest.main()
