from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import BoundedSemaphore, Lock
from typing import Dict

from .engine import WorkflowEngine
from .models import RunRecord
from .spec_loader import WorkflowSpec


class WorkflowService:
    def __init__(self, engine: WorkflowEngine, max_concurrent_runs: int = 2):
        self.engine = engine
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent_runs)
        self._semaphore = BoundedSemaphore(value=max_concurrent_runs)
        self._futures: Dict[str, Future] = {}
        self._futures_lock = Lock()

    def start(self, spec: WorkflowSpec, input_data: Dict, idempotency_key: str | None = None) -> RunRecord:
        run = self.engine.create_run(spec, input_data, idempotency_key=idempotency_key)

        if run.status.value in {"running", "pending"}:
            self._submit(spec, run.run_id, resume=True)
        return run

    def _submit(self, spec: WorkflowSpec, run_id: str, resume: bool) -> None:
        with self._futures_lock:
            if run_id in self._futures and not self._futures[run_id].done():
                return

            def worker() -> RunRecord:
                with self._semaphore:
                    return self.engine.execute(spec, run_id, resume=resume)

            self._futures[run_id] = self._executor.submit(worker)

    def pause(self, run_id: str) -> RunRecord:
        return self.engine.request_action(run_id, "pause")

    def cancel(self, run_id: str) -> RunRecord:
        return self.engine.request_action(run_id, "cancel")

    def resume(self, spec: WorkflowSpec, run_id: str) -> RunRecord:
        self.engine.request_action(run_id, "resume")
        self._submit(spec, run_id, resume=True)
        run = self.engine.store.get_run(run_id)
        if not run:
            raise KeyError(f"Run not found: {run_id}")
        return run

    def rerun_failed_step(self, spec: WorkflowSpec, run_id: str) -> RunRecord:
        return self.engine.rerun_failed_step(spec, run_id)

    def wait(self, run_id: str, timeout: float | None = None) -> RunRecord:
        with self._futures_lock:
            future = self._futures.get(run_id)
        if future:
            return future.result(timeout=timeout)
        run = self.engine.store.get_run(run_id)
        if not run:
            raise KeyError(f"Run not found: {run_id}")
        return run
