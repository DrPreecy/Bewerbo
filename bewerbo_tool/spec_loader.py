from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .models import WorkflowSpec, WorkflowStep


class SpecValidationError(ValueError):
    pass


def load_workflow_spec(spec_path: str) -> WorkflowSpec:
    payload = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    return parse_workflow_spec(payload)


def parse_workflow_spec(payload: Dict[str, Any]) -> WorkflowSpec:
    required_top = ["name", "version", "input_schema", "steps"]
    missing = [k for k in required_top if k not in payload]
    if missing:
        raise SpecValidationError(f"Missing workflow fields: {missing}")

    if not isinstance(payload["steps"], list) or not payload["steps"]:
        raise SpecValidationError("'steps' must be a non-empty list")

    steps = []
    step_ids = set()
    for raw_step in payload["steps"]:
        if "id" not in raw_step or "type" not in raw_step:
            raise SpecValidationError("Each step requires 'id' and 'type'")
        step_id = str(raw_step["id"])
        if step_id in step_ids:
            raise SpecValidationError(f"Duplicate step id: {step_id}")
        step_ids.add(step_id)
        try:
            retries = int(raw_step.get("retries", 0))
        except (TypeError, ValueError) as err:
            raise SpecValidationError(f"Invalid retries value for step '{step_id}'") from err
        if retries < 0:
            raise SpecValidationError(f"Invalid retries value for step '{step_id}': must be >= 0")
        try:
            backoff_seconds = float(raw_step.get("backoff_seconds", 0.0))
        except (TypeError, ValueError) as err:
            raise SpecValidationError(f"Invalid backoff_seconds value for step '{step_id}'") from err
        if backoff_seconds < 0:
            raise SpecValidationError(f"Invalid backoff_seconds value for step '{step_id}': must be >= 0")
        steps.append(
            WorkflowStep(
                id=step_id,
                type=str(raw_step["type"]),
                params=dict(raw_step.get("params", {})),
                retries=retries,
                backoff_seconds=backoff_seconds,
                continue_on_error=bool(raw_step.get("continue_on_error", False)),
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
    if not isinstance(input_data, dict):
        raise SpecValidationError("Input payload must be a JSON object")
    required = input_schema.get("required", [])
    missing = [field for field in required if field not in input_data]
    if missing:
        raise SpecValidationError(f"Missing required input fields: {missing}")
