from __future__ import annotations

import time
import uuid
from typing import Dict, List

from .executors import ExecutorRegistry, RetryableStepError
from .models import AuditEvent, RunRecord, RunStatus, StepResult, StepStatus, utc_now_iso
from .spec_loader import WorkflowSpec, validate_input
from .storage import JsonStateStore


class WorkflowEngine:
    def __init__(self, store: JsonStateStore, registry: ExecutorRegistry):
        self.store = store
        self.registry = registry

    def create_run(
        self,
        spec: WorkflowSpec,
        input_data: Dict,
        idempotency_key: str | None = None,
    ) -> RunRecord:
        run, _ = self.create_run_with_flag(spec, input_data, idempotency_key=idempotency_key)
        return run

    def create_run_with_flag(
        self,
        spec: WorkflowSpec,
        input_data: Dict,
        idempotency_key: str | None = None,
    ) -> tuple[RunRecord, bool]:
        validate_input(spec.input_schema, input_data)

        run = RunRecord(
            run_id=str(uuid.uuid4()),
            workflow_name=spec.name,
            workflow_version=spec.version,
            input_data=input_data,
            context=dict(input_data),
            status=RunStatus.PENDING,
            idempotency_key=idempotency_key,
        )
        self._audit(run, "run_created", "Run created")
        return self.store.save_run_if_idempotency_absent(run)

    def request_action(self, run_id: str, action: str) -> RunRecord:
        run = self._require_run(run_id)
        run.requested_action = action
        run.updated_at = utc_now_iso()
        self._audit(run, "action_requested", "Control action requested", {"action": action})
        self.store.save_run(run)
        return run

    def execute(self, spec: WorkflowSpec, run_id: str, resume: bool = False) -> RunRecord:
        run = self._require_run(run_id)

        if run.status in {RunStatus.COMPLETED, RunStatus.CANCELLED}:
            return run

        if not resume:
            run.current_step_index = 0
            run.step_results = {}
            run.context = dict(run.input_data)

        run.status = RunStatus.RUNNING
        run.requested_action = None
        run.updated_at = utc_now_iso()
        self._audit(run, "run_started", "Run execution started", {"resume": resume})
        self.store.save_run(run)

        completed_step_ids: List[str] = [
            step_id for step_id, result in run.step_results.items() if result.status == StepStatus.COMPLETED
        ]

        for i in range(run.current_step_index, len(spec.steps)):
            run = self._require_run(run.run_id)
            if run.requested_action == "cancel":
                run.status = RunStatus.CANCELLED
                run.requested_action = None
                run.updated_at = utc_now_iso()
                self._audit(run, "run_cancelled", "Run cancelled")
                self.store.save_run(run)
                return run
            if run.requested_action == "pause":
                run.status = RunStatus.PAUSED
                run.requested_action = None
                run.current_step_index = i
                run.updated_at = utc_now_iso()
                self._audit(run, "run_paused", "Run paused", {"step_index": i})
                self.store.save_run(run)
                return run

            step = spec.steps[i]
            started = utc_now_iso()
            attempts = 0
            step_status = StepStatus.FAILED
            output = {}
            error_message = None

            while attempts <= max(step.retries, 0):
                attempts += 1
                try:
                    executor = self.registry.get(step.type)
                    output = executor.execute(step.params, run.context)
                    step_status = StepStatus.COMPLETED
                    error_message = None
                    break
                except RetryableStepError as err:
                    error_message = str(err)
                    if attempts > step.retries:
                        break
                    if step.backoff_seconds > 0:
                        time.sleep(step.backoff_seconds)
                except Exception as err:  # noqa: BLE001
                    error_message = str(err)
                    break

            result = StepResult(
                step_id=step.id,
                status=step_status,
                attempts=attempts,
                started_at=started,
                finished_at=utc_now_iso(),
                output=output,
                context_snapshot=dict(run.context),
                error=error_message,
            )
            run.step_results[step.id] = result
            run.current_step_index = i + 1
            run.updated_at = utc_now_iso()

            if step_status == StepStatus.COMPLETED:
                completed_step_ids.append(step.id)
                self._audit(run, "step_completed", "Step completed", {"step_id": step.id, "attempts": attempts})
                self._preserve_requested_action(run)
                self.store.save_run(run)
                continue

            run.last_error = error_message
            self._audit(run, "step_failed", "Step failed", {"step_id": step.id, "error": error_message})

            if step.continue_on_error:
                result.status = StepStatus.SKIPPED
                run.step_results[step.id] = result
                run.last_error = None
                self._audit(run, "step_skipped", "Continuing after failed step", {"step_id": step.id})
                self._preserve_requested_action(run)
                self.store.save_run(run)
                continue

            self._compensate(spec, run, completed_step_ids)
            run.status = RunStatus.FAILED
            self._preserve_requested_action(run)
            self.store.save_run(run)
            return run

        run.status = RunStatus.COMPLETED
        run.updated_at = utc_now_iso()
        self._audit(run, "run_completed", "Run completed")
        self._preserve_requested_action(run)
        self.store.save_run(run)
        return run

    def rerun_failed_step(self, spec: WorkflowSpec, run_id: str) -> RunRecord:
        run = self.prepare_rerun_failed_step(spec, run_id)
        return self.execute(spec, run.run_id, resume=True)

    def prepare_rerun_failed_step(self, spec: WorkflowSpec, run_id: str) -> RunRecord:
        run = self._require_run(run_id)
        if run.status != RunStatus.FAILED:
            raise ValueError("Run is not in failed status")

        failed_index = None
        for idx, step in enumerate(spec.steps):
            result = run.step_results.get(step.id)
            if result and result.status == StepStatus.FAILED:
                failed_index = idx
                break

        if failed_index is None:
            raise ValueError("No failed step found")

        for step in spec.steps[failed_index:]:
            run.step_results.pop(step.id, None)
        run.context = self._context_at_step_boundary(spec, run, failed_index)

        run.current_step_index = failed_index
        run.status = RunStatus.PENDING
        run.last_error = None
        run.updated_at = utc_now_iso()
        self._audit(run, "rerun_failed_step", "Re-running failed step", {"step_index": failed_index})
        self.store.save_run(run)
        return run

    def metrics(self) -> Dict[str, int]:
        runs = self.store.list_runs().values()
        totals = {
            "total_runs": 0,
            "running": 0,
            "paused": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
        }
        for run in runs:
            totals["total_runs"] += 1
            if run.status == RunStatus.RUNNING:
                totals["running"] += 1
            elif run.status == RunStatus.PAUSED:
                totals["paused"] += 1
            elif run.status == RunStatus.COMPLETED:
                totals["completed"] += 1
            elif run.status == RunStatus.FAILED:
                totals["failed"] += 1
            elif run.status == RunStatus.CANCELLED:
                totals["cancelled"] += 1
        return totals

    def _compensate(self, spec: WorkflowSpec, run: RunRecord, completed_step_ids: List[str]) -> None:
        for step in reversed(spec.steps):
            if step.id not in completed_step_ids or not step.compensation:
                continue
            try:
                executor = self.registry.get(step.compensation)
                result = executor.compensate(step.params, run.context)
                self._audit(run, "compensation_executed", "Compensation executed", {"step_id": step.id, "result": result})
            except Exception as err:  # noqa: BLE001
                self._audit(run, "compensation_failed", "Compensation failed", {"step_id": step.id, "error": str(err)})

    def _require_run(self, run_id: str) -> RunRecord:
        run = self.store.get_run(run_id)
        if not run:
            raise KeyError(f"Run not found: {run_id}")
        return run

    def _audit(self, run: RunRecord, event_type: str, message: str, details: Dict | None = None) -> None:
        safe_details = self._redact_sensitive(details or {})
        run.audit_log.append(
            AuditEvent(
                timestamp=utc_now_iso(),
                event_type=event_type,
                message=message,
                details=safe_details,
            )
        )

    def _redact_sensitive(self, details: Dict) -> Dict:
        return {key: self._redact_value(key, value) for key, value in details.items()}

    def _redact_value(self, key: str, value):
        lowered = key.lower()
        sensitive_tokens = (
            "secret",
            "token",
            "password",
            "api_key",
            "private_key",
            "access_key",
            "client_secret",
            "authorization",
        )
        if lowered in sensitive_tokens or any(token in lowered for token in ("secret", "token", "password")):
            return "***REDACTED***"
        if isinstance(value, dict):
            return {k: self._redact_value(k, v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._redact_value(key, item) for item in value]
        return value

    def _context_at_step_boundary(self, spec: WorkflowSpec, run: RunRecord, step_index: int) -> Dict:
        if step_index <= 0:
            return dict(run.input_data)
        previous_step_id = spec.steps[step_index - 1].id
        previous_result = run.step_results.get(previous_step_id)
        if previous_result and previous_result.status == StepStatus.COMPLETED:
            return dict(previous_result.context_snapshot or run.input_data)
        return dict(run.input_data)

    def _preserve_requested_action(self, run: RunRecord) -> None:
        if run.requested_action:
            return
        latest = self.store.get_run(run.run_id)
        if latest and latest.requested_action:
            run.requested_action = latest.requested_action
