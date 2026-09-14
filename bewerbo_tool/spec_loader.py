from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict

from .models import WorkflowSpec, WorkflowStep


class SpecValidationError(ValueError):
    pass


def load_workflow_spec(spec_path: str) -> WorkflowSpec:
    """load workflow spec."""
    payload = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    return parse_workflow_spec(payload)


def parse_workflow_spec(payload: Dict[str, Any]) -> WorkflowSpec:
    """parse workflow spec."""
    required_top = ["name", "version", "input_schema", "steps"]
    missing = [k for k in required_top if k not in payload]
    if missing:
        raise SpecValidationError(f"Missing workflow fields: {missing}")

    if not isinstance(payload["steps"], list) or not payload["steps"]:
        raise SpecValidationError("'steps' must be a non-empty list")

    steps = []
    step_ids = set()
    for raw_step in payload["steps"]:
        if not isinstance(raw_step, dict) or "id" not in raw_step or "type" not in raw_step:
            raise SpecValidationError("Each step requires 'id' and 'type'")
        step_id = str(raw_step["id"])
        if step_id in step_ids:
            raise SpecValidationError(f"Duplicate step id: {step_id}")
        step_ids.add(step_id)

        retries = raw_step.get("retries", 0)
        if isinstance(retries, bool) or not isinstance(retries, int):
            raise SpecValidationError(f"Invalid retries value for step '{step_id}'")
        if retries < 0:
            raise SpecValidationError(f"Invalid retries value for step '{step_id}': must be >= 0")

        backoff_seconds = raw_step.get("backoff_seconds", 0.0)
        if (
            isinstance(backoff_seconds, bool)
            or not isinstance(backoff_seconds, (int, float))
            or not math.isfinite(backoff_seconds)
        ):
            raise SpecValidationError(f"Invalid backoff_seconds value for step '{step_id}'")
        if backoff_seconds < 0:
            raise SpecValidationError(f"Invalid backoff_seconds value for step '{step_id}': must be >= 0")

        continue_on_error = raw_step.get("continue_on_error", False)
        if not isinstance(continue_on_error, bool):
            raise SpecValidationError(f"Invalid continue_on_error value for step '{step_id}'")

        steps.append(
            WorkflowStep(
                id=step_id,
                type=str(raw_step["type"]),
                params=dict(raw_step.get("params", {})),
                retries=retries,
                backoff_seconds=float(backoff_seconds),
                continue_on_error=continue_on_error,
                compensation=raw_step.get("compensation"),
            )
        )

    return WorkflowSpec(
        name=str(payload["name"]),
        version=str(payload["version"]),
        input_schema=dict(payload["input_schema"]),
        steps=steps,
    )


def validate_input(input_schema: Dict[str, Any], input_data: Dict[str, Any]) -> None:
    """validate input."""
    if not isinstance(input_data, dict):
        raise SpecValidationError("Input payload must be a JSON object")
    required = input_schema.get("required", [])
    missing = [field for field in required if field not in input_data]
    if missing:
        raise SpecValidationError(f"Missing required input fields: {missing}")
