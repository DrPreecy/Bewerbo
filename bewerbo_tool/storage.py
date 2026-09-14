from __future__ import annotations

import json
import os
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

from .models import RunRecord


class JsonStateStore:
    _locks_guard = threading.Lock()
    _path_locks: Dict[str, threading.RLock] = {}

    def __init__(self, path: str):
        """  init  ."""
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.path.with_suffix(f"{self.path.suffix}.lock")
        with self._locks_guard:
            self._lock = self._path_locks.setdefault(str(self.path.resolve()), threading.RLock())
        with self._transaction():
            if not self.path.exists():
                self._write({"runs": {}, "idempotency": {}})

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """ transaction."""
        with self._lock:
            with self._lock_path.open("a+", encoding="utf-8") as lock_file:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if fcntl is not None:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _read(self) -> Dict:
        """ read."""
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: Dict) -> None:
        """ write."""
        tmp_path = self.path.with_name(f"{self.path.name}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp_path, self.path)

    def save_run(self, run: RunRecord) -> None:
        """save run."""
        with self._transaction():
            data = self._read()
            data["runs"][run.run_id] = run.to_dict()
            if run.idempotency_key:
                data["idempotency"][run.idempotency_key] = run.run_id
            self._write(data)

    def save_run_preserving_requested_action(self, run: RunRecord) -> None:
        """save run preserving requested action."""
        with self._transaction():
            data = self._read()
            latest = data["runs"].get(run.run_id)
            if latest and latest.get("requested_action") and not run.requested_action:
                run.requested_action = latest["requested_action"]
            data["runs"][run.run_id] = run.to_dict()
            if run.idempotency_key:
                data["idempotency"][run.idempotency_key] = run.run_id
            self._write(data)

    def save_run_if_idempotency_absent(self, run: RunRecord) -> Tuple[RunRecord, bool]:
        """save run if idempotency absent."""
        with self._transaction():
            data = self._read()
            if run.idempotency_key:
                existing_run_id = data["idempotency"].get(run.idempotency_key)
                if existing_run_id:
                    payload = data["runs"].get(existing_run_id)
                    if payload:
                        return RunRecord.from_dict(payload), False

            data["runs"][run.run_id] = run.to_dict()
            if run.idempotency_key:
                data["idempotency"][run.idempotency_key] = run.run_id
            self._write(data)
            return run, True

    def get_run(self, run_id: str) -> Optional[RunRecord]:
        """get run."""
        with self._transaction():
            data = self._read()
            payload = data["runs"].get(run_id)
            return RunRecord.from_dict(payload) if payload else None

    def get_run_by_idempotency_key(self, key: str) -> Optional[RunRecord]:
        """get run by idempotency key."""
        with self._transaction():
            data = self._read()
            run_id = data["idempotency"].get(key)
            if not run_id:
                return None
            payload = data["runs"].get(run_id)
            return RunRecord.from_dict(payload) if payload else None

    def list_runs(self) -> Dict[str, RunRecord]:
        """list runs."""
        with self._transaction():
            data = self._read()
            return {run_id: RunRecord.from_dict(payload) for run_id, payload in data["runs"].items()}
