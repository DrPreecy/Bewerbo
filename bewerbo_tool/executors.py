from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict

from .bewerbo_logic import DecisionThresholds, analyze_rejection, build_master_profile, build_variants_for_job, classify_jobs, quality_checks, score_job


class RetryableStepError(RuntimeError):
    pass


class IntegrationClient(ABC):
    @abstractmethod
    def call(self, target: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """call."""
        raise NotImplementedError


class MockIntegrationClient(IntegrationClient):
    def call(self, target: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """call."""
        return {"target": target, "status": "ok", "echo": payload}


class StepExecutor(ABC):
    @abstractmethod
    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """execute."""
        raise NotImplementedError

    def compensate(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """compensate."""
        return {"compensated": False}


class SanitizeInputExecutor(StepExecutor):
    _dangerous_chars = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")

    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """execute."""
        fields = step_params.get("fields", [])
        for field in fields:
            if isinstance(context.get(field), str):
                context[field] = self._dangerous_chars.sub("", context[field]).strip()
        return {"sanitized_fields": fields}


class TransformExecutor(StepExecutor):
    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """execute."""
        mappings = step_params.get("mappings", {})
        for target, source in mappings.items():
            context[target] = context.get(source)
        return {"mapped": list(mappings.keys())}


class ExternalCallExecutor(StepExecutor):
    def __init__(self, integration_client: IntegrationClient):
        """  init  ."""
        self.integration_client = integration_client

    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """execute."""
        payload = {field: context.get(field) for field in step_params.get("payload_fields", [])}
        response = self.integration_client.call(step_params.get("target", "mock://integration"), payload)
        context["integration_status"], context["integration_response"] = response.get("status"), response
        return {"integration_status": response.get("status")}


class EmitOutputExecutor(StepExecutor):
    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """execute."""
        output = {field: context.get(field) for field in step_params.get("fields", [])}
        context["final_output"] = output
        return output


class FailNTimesExecutor(StepExecutor):
    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """execute."""
        key = f"_attempt_{step_params.get('key', 'default')}"
        current, required = int(context.get(key, 0)), int(step_params.get("failures", 1))
        if current < required:
            context[key] = current + 1
            raise RetryableStepError("Transient failure; retry allowed")
        return {"recovered_after": current}


class BuildProfileExecutor(StepExecutor):
    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """execute."""
        profile = build_master_profile(context)
        context["master_profile"] = profile
        return {"master_profile_created": True, "target_roles": profile.get("target_roles", [])}


class RejectionLearningExecutor(StepExecutor):
    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """execute."""
        analysis = analyze_rejection(context, context)
        context["rejection_analysis"] = analysis
        return analysis


class JobScoringExecutor(StepExecutor):
    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """execute."""
        scored = [score_job(job, context.get("master_profile", {})) for job in context.get("job_market_data", [])]
        scored.sort(key=lambda job: job.get("match_score", 0), reverse=True)
        context["scored_jobs"] = scored
        return {"jobs_scored": len(scored)}


class JobDecisionExecutor(StepExecutor):
    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """execute."""
        thresholds = DecisionThresholds(float(step_params.get("apply_min", 0.72)), float(step_params.get("optional_min", 0.52)))
        classified = classify_jobs(context.get("scored_jobs", []), thresholds)
        context["classified_jobs"] = classified
        summary = {"apply": 0, "optional": 0, "skip": 0}
        for job in classified:
            summary[job["decision"]] += 1
        context["decision_summary"] = summary
        return summary


class GenerateDocumentsExecutor(StepExecutor):
    def _resolve_template_path(self, value: str) -> Path:
        """ resolve template path."""
        path = Path(value)
        if path.is_absolute():
            return path
        for root in (Path.cwd(), *Path.cwd().parents):
            candidate = root / path
            if candidate.is_file():
                return candidate
        raise FileNotFoundError(f"Template path could not be resolved: {value}")

    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """execute."""
        templates = {
            "cv_master": self._resolve_template_path(step_params["cv_template_path"]).read_text(encoding="utf-8"),
            "cover_letter_master": self._resolve_template_path(step_params["cover_letter_template_path"]).read_text(encoding="utf-8"),
        }
        selected = [job for job in context.get("classified_jobs", []) if job.get("decision") in {"apply", "optional"}]
        applications = [build_variants_for_job(job, context.get("master_profile", {}), templates) for job in selected]
        context["application_packages"] = applications
        return {"application_packages": len(applications)}


class QualityGateExecutor(StepExecutor):
    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """execute."""
        report = quality_checks(context.get("application_packages", []))
        context["quality_report"] = report
        return {"all_passed": report.get("all_passed", False), "checks": len(report.get("checks", []))}


class ExecutorRegistry:
    def __init__(self, integration_client: IntegrationClient | None = None):
        """  init  ."""
        client = integration_client or MockIntegrationClient()
        self._executors = {
            "sanitize_input": SanitizeInputExecutor(), "transform": TransformExecutor(),
            "external_call": ExternalCallExecutor(client), "emit_output": EmitOutputExecutor(),
            "fail_n_times": FailNTimesExecutor(), "build_profile": BuildProfileExecutor(),
            "rejection_learning": RejectionLearningExecutor(), "score_jobs": JobScoringExecutor(),
            "decide_jobs": JobDecisionExecutor(), "generate_documents": GenerateDocumentsExecutor(),
            "quality_gate": QualityGateExecutor(),
        }

    def get(self, step_type: str) -> StepExecutor:
        """get."""
        if step_type not in self._executors:
            raise KeyError(f"Unknown step executor type: {step_type}")
        return self._executors[step_type]
