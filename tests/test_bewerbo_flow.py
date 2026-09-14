import json
import tempfile
import unittest
from pathlib import Path

from bewerbo_tool.engine import WorkflowEngine
from bewerbo_tool.executors import ExecutorRegistry
from bewerbo_tool.spec_loader import load_workflow_spec
from bewerbo_tool.storage import JsonStateStore


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestBewerboFlow(unittest.TestCase):
    def test_bewerbo_process_end_to_end(self):
        """test bewerbo process end to end."""
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "state.json"
            store = JsonStateStore(str(state_path))
            engine = WorkflowEngine(store=store, registry=ExecutorRegistry())
            spec = load_workflow_spec(
                str(REPO_ROOT / "workflows" / "v1" / "bewerbo_application_process.json")
            )
            input_payload = json.loads(
                (REPO_ROOT / "assets" / "input" / "bewerbo_sample_input.json").read_text(encoding="utf-8")
            )

            run = engine.create_run(spec, input_payload, idempotency_key="bewerbo-e2e")
            result = engine.execute(spec, run.run_id)

            self.assertEqual(result.status.value, "completed")
            output = result.context["final_output"]
            self.assertIn("master_profile", output)
            self.assertIn("application_packages", output)
            self.assertEqual(output["decision_summary"]["apply"], 1)
            self.assertEqual(output["decision_summary"]["skip"], 2)
            self.assertGreaterEqual(len(output["application_packages"]), 1)

    def test_blocker_job_is_skipped(self):
        """test blocker job is skipped."""
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "state.json"
            store = JsonStateStore(str(state_path))
            engine = WorkflowEngine(store=store, registry=ExecutorRegistry())
            spec = load_workflow_spec(
                str(REPO_ROOT / "workflows" / "v1" / "bewerbo_application_process.json")
            )
            payload = json.loads(
                (REPO_ROOT / "assets" / "input" / "bewerbo_sample_input.json").read_text(encoding="utf-8")
            )
            run = engine.create_run(spec, payload)
            result = engine.execute(spec, run.run_id)
            classified = result.context["classified_jobs"]

            remote_ops = [j for j in classified if j["company"] == "RemoteOps"][0]
            self.assertEqual(remote_ops["decision"], "skip")
            self.assertIn("location_mismatch", remote_ops["blockers"])


if __name__ == "__main__":
    unittest.main()
