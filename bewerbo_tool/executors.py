from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict

from .bewerbo_logic import (
    DecisionThresholds,
    analyze_rejection,
    build_master_profile,
    build_variants_for_job,
    classify_jobs,
    quality_checks,
    score_job,
)


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


class BuildProfileExecutor(StepExecutor):
    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        profile = build_master_profile(context)
        context["master_profile"] = profile
        return {"master_profile_created": True, "target_roles": profile.get("target_roles", [])}


class RejectionLearningExecutor(StepExecutor):
    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        analysis = analyze_rejection(context, context)
        context["rejection_analysis"] = analysis
        return analysis


class JobScoringExecutor(StepExecutor):
    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        jobs = context.get("job_market_data", [])
        profile = context.get("master_profile", {})
        scored = [score_job(job, profile) for job in jobs]
        scored.sort(key=lambda job: job.get("match_score", 0), reverse=True)
        context["scored_jobs"] = scored
        return {"jobs_scored": len(scored)}


class JobDecisionExecutor(StepExecutor):
    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        thresholds = DecisionThresholds(
            apply_min=float(step_params.get("apply_min", 0.72)),
            optional_min=float(step_params.get("optional_min", 0.52)),
        )
        classified = classify_jobs(context.get("scored_jobs", []), thresholds)
        context["classified_jobs"] = classified
        summary = {"apply": 0, "optional": 0, "skip": 0}
        for job in classified:
            summary[job["decision"]] += 1
        context["decision_summary"] = summary
        return summary


class GenerateDocumentsExecutor(StepExecutor):
    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        template_cv = Path(step_params["cv_template_path"]).read_text(encoding="utf-8")
        template_letter = Path(step_params["cover_letter_template_path"]).read_text(encoding="utf-8")
        templates = {"cv_master": template_cv, "cover_letter_master": template_letter}

        profile = context.get("master_profile", {})
        selected = [j for j in context.get("classified_jobs", []) if j.get("decision") in {"apply", "optional"}]
        applications = [build_variants_for_job(job, profile, templates) for job in selected]
        context["application_packages"] = applications
        return {"application_packages": len(applications)}


class QualityGateExecutor(StepExecutor):
    def execute(self, step_params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        report = quality_checks(context.get("application_packages", []))
        context["quality_report"] = report
        return {"all_passed": report.get("all_passed", False), "checks": len(report.get("checks", []))}


class ExecutorRegistry:
    def __init__(self, integration_client: IntegrationClient | None = None):
        ic = integration_client or MockIntegrationClient()
        self._executors = {
            "sanitize_input": SanitizeInputExecutor(),
            "transform": TransformExecutor(),
            "external_call": ExternalCallExecutor(ic),
            "emit_output": EmitOutputExecutor(),
            "fail_n_times": FailNTimesExecutor(),
            "build_profile": BuildProfileExecutor(),
            "rejection_learning": RejectionLearningExecutor(),
            "score_jobs": JobScoringExecutor(),
            "decide_jobs": JobDecisionExecutor(),
            "generate_documents": GenerateDocumentsExecutor(),
            "quality_gate": QualityGateExecutor(),
        }

    def get(self, step_type: str) -> StepExecutor:
        if step_type not in self._executors:
            raise KeyError(f"Unknown step executor type: {step_type}")
        return self._executors[step_type]
