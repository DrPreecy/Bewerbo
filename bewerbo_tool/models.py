from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class WorkflowStep:
    id: str
    type: str
    params: Dict[str, Any] = field(default_factory=dict)
    retries: int = 0
    backoff_seconds: float = 0.0
    continue_on_error: bool = False
    compensation: Optional[str] = None


@dataclass
class WorkflowSpec:
    name: str
    version: str
    input_schema: Dict[str, Any]
    steps: List[WorkflowStep]


@dataclass
class StepResult:
    step_id: str
    status: StepStatus
    attempts: int
    started_at: str
    finished_at: str
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class AuditEvent:
    timestamp: str
    event_type: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RunRecord:
    run_id: str
    workflow_name: str
    workflow_version: str
    input_data: Dict[str, Any]
    context: Dict[str, Any]
    status: RunStatus
    current_step_index: int = 0
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    idempotency_key: Optional[str] = None
    requested_action: Optional[str] = None
    last_error: Optional[str] = None
    step_results: Dict[str, StepResult] = field(default_factory=dict)
    audit_log: List[AuditEvent] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_name": self.workflow_name,
            "workflow_version": self.workflow_version,
            "input_data": self.input_data,
            "context": self.context,
            "status": self.status.value,
            "current_step_index": self.current_step_index,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "idempotency_key": self.idempotency_key,
            "requested_action": self.requested_action,
            "last_error": self.last_error,
            "step_results": {
                k: {
                    "step_id": v.step_id,
                    "status": v.status.value,
                    "attempts": v.attempts,
                    "started_at": v.started_at,
                    "finished_at": v.finished_at,
                    "output": v.output,
                    "error": v.error,
                }
                for k, v in self.step_results.items()
            },
            "audit_log": [
                {
                    "timestamp": e.timestamp,
                    "event_type": e.event_type,
                    "message": e.message,
                    "details": e.details,
                }
                for e in self.audit_log
            ],
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "RunRecord":
        return RunRecord(
            run_id=data["run_id"],
            workflow_name=data["workflow_name"],
            workflow_version=data["workflow_version"],
            input_data=data.get("input_data", {}),
            context=data.get("context", {}),
            status=RunStatus(data.get("status", RunStatus.PENDING.value)),
            current_step_index=data.get("current_step_index", 0),
            created_at=data.get("created_at", utc_now_iso()),
            updated_at=data.get("updated_at", utc_now_iso()),
            idempotency_key=data.get("idempotency_key"),
            requested_action=data.get("requested_action"),
            last_error=data.get("last_error"),
            step_results={
                k: StepResult(
                    step_id=v["step_id"],
                    status=StepStatus(v["status"]),
                    attempts=v["attempts"],
                    started_at=v["started_at"],
                    finished_at=v["finished_at"],
                    output=v.get("output", {}),
                    error=v.get("error"),
                )
                for k, v in data.get("step_results", {}).items()
            },
            audit_log=[
                AuditEvent(
                    timestamp=e["timestamp"],
                    event_type=e["event_type"],
                    message=e["message"],
                    details=e.get("details", {}),
                )
                for e in data.get("audit_log", [])
            ],
        )
