from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Dict


class RetryableStepError(RuntimeError):
    pass


class IntegrationClient(ABC):
    @abstractmethod
    def call(self, target: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class MockIntegrationClient(IntegrationClient):
    def call(self, target: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "target": target,
            "status": "ok",
            "echo": payload,
        }


class StepExecutor(ABC):
    @abstractmethod
    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def compensate(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        return {"compensated": False}


class SanitizeInputExecutor(StepExecutor):
    _dangerous_chars = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")

    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        fields = step_params.get("fields", [])
        for field in fields:
            value = context.get(field)
            if isinstance(value, str):
                context[field] = self._dangerous_chars.sub("", value).strip()
        return {"sanitized_fields": fields}


class TransformExecutor(StepExecutor):
    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        mappings = step_params.get("mappings", {})
        for target, source in mappings.items():
            context[target] = context.get(source)
        return {"mapped": list(mappings.keys())}


class ExternalCallExecutor(StepExecutor):
    def __init__(self, integration_client: IntegrationClient):
        self.integration_client = integration_client

    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        target = step_params.get("target", "mock://integration")
        payload_fields = step_params.get("payload_fields", [])
        payload = {f: context.get(f) for f in payload_fields}
        response = self.integration_client.call(target, payload)
        context["integration_status"] = response.get("status")
        context["integration_response"] = response
        return {"integration_status": response.get("status")}


class EmitOutputExecutor(StepExecutor):
    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        fields = step_params.get("fields", [])
        output = {f: context.get(f) for f in fields}
        context["final_output"] = output
        return output


class FailNTimesExecutor(StepExecutor):
    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        key = f"_attempt_{step_params.get('key', 'default')}"
        required_failures = int(step_params.get("failures", 1))
        current = int(context.get(key, 0))
        if current < required_failures:
            context[key] = current + 1
            raise RetryableStepError("Transient failure; retry allowed")
        return {"recovered_after": current}


class ExecutorRegistry:
    def __init__(self, integration_client: IntegrationClient | None = None):
        ic = integration_client or MockIntegrationClient()
        self._executors = {
            "sanitize_input": SanitizeInputExecutor(),
            "transform": TransformExecutor(),
            "external_call": ExternalCallExecutor(ic),
            "emit_output": EmitOutputExecutor(),
            "fail_n_times": FailNTimesExecutor(),
        }

    def get(self, step_type: str) -> StepExecutor:
        if step_type not in self._executors:
            raise KeyError(f"Unknown step executor type: {step_type}")
        return self._executors[step_type]
