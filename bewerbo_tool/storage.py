from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, Optional

from .models import RunRecord


class JsonStateStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self.path.exists():
            self._write({"runs": {}, "idempotency": {}})

    def _read(self) -> Dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: Dict) -> None:
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def save_run(self, run: RunRecord) -> None:
        with self._lock:
            data = self._read()
            data["runs"][run.run_id] = run.to_dict()
            if run.idempotency_key:
                data["idempotency"][run.idempotency_key] = run.run_id
            self._write(data)

    def save_run_if_idempotency_absent(self, run: RunRecord) -> RunRecord:
        with self._lock:
            data = self._read()
            if run.idempotency_key:
                existing_run_id = data["idempotency"].get(run.idempotency_key)
                if existing_run_id:
                    payload = data["runs"].get(existing_run_id)
                    if payload:
                        return RunRecord.from_dict(payload)

            data["runs"][run.run_id] = run.to_dict()
            if run.idempotency_key:
                data["idempotency"][run.idempotency_key] = run.run_id
            self._write(data)
            return run

    def get_run(self, run_id: str) -> Optional[RunRecord]:
        with self._lock:
            data = self._read()
            payload = data["runs"].get(run_id)
            return RunRecord.from_dict(payload) if payload else None

    def get_run_by_idempotency_key(self, key: str) -> Optional[RunRecord]:
        with self._lock:
            data = self._read()
            run_id = data["idempotency"].get(key)
            if not run_id:
                return None
            payload = data["runs"].get(run_id)
            return RunRecord.from_dict(payload) if payload else None

    def list_runs(self) -> Dict[str, RunRecord]:
        with self._lock:
            data = self._read()
            return {run_id: RunRecord.from_dict(payload) for run_id, payload in data["runs"].items()}
