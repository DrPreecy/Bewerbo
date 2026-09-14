from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


DEFAULT_ROLE_HINTS = {
    "python": ["Data & AI", "Software Engineering", "Automation"],
    "sql": ["Data & AI", "Business Intelligence", "Controlling"],
    "communication": ["Consulting", "Project Management", "HR"],
    "finance": ["Banking", "Corporate Finance", "Risk"],
    "analysis": ["Data & AI", "Risk", "Strategy"],
}


@dataclass
class DecisionThresholds:
    apply_min: float = 0.72
    optional_min: float = 0.52


def normalize_skill(skill: str) -> str:
    return skill.strip().lower().replace("-", " ")


def build_master_profile(input_data: Dict[str, Any]) -> Dict[str, Any]:
    basics = input_data.get("candidate_basics", {})
    interview = input_data.get("interview_answers", {})
    skills = [normalize_skill(s) for s in interview.get("skills", [])]
    preferences = {
        "location": interview.get("location", "Germany"),
        "salary_expectation": interview.get("salary_expectation", "market"),
        "culture": interview.get("culture", "balanced"),
        "study_focus": interview.get("study_focus", "duales Studium"),
        "no_gos": interview.get("no_gos", []),
    }

    hidden_fits = sorted(
        {
            role
            for skill in skills
            for role in DEFAULT_ROLE_HINTS.get(skill, [])
        }
    )

    return {
        "name": basics.get("name", "Candidate"),
        "email": basics.get("email", ""),
        "skills": skills,
        "strengths": interview.get("strengths", []),
        "preferences": preferences,
        "hidden_fit_roles": hidden_fits,
        "target_roles": sorted(set(interview.get("target_roles", []) + hidden_fits)),
    }


def analyze_rejection(input_data: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    rejection = input_data.get("rejection_feedback", "")
    text = str(rejection).lower()
    risks = []
    if "absage" in text or "nicht" in text:
        risks.append("profile_positioning_unclear")
    if "bank" in text or "dz" in text:
        risks.append("banking_fit_gap")
    if not risks:
        risks.append("insufficient_signal")

    mitigation = {
        "profile_positioning_unclear": "Sharpen role narrative and achievement metrics.",
        "banking_fit_gap": "Add finance-relevant projects and conservative document variant.",
        "insufficient_signal": "Strengthen interview answers and evidence-based skills.",
    }
    context["ko_risks"] = risks
    return {
        "ko_risks": risks,
        "mitigation": [mitigation[r] for r in risks],
    }


def score_job(job: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    skills = set(profile.get("skills", []))
    wanted = {normalize_skill(s) for s in job.get("required_skills", [])}
    preferred = {normalize_skill(s) for s in job.get("preferred_skills", [])}

    hard_filters = job.get("hard_filters", {})
    location_ok = hard_filters.get("location", "") in ("", profile.get("preferences", {}).get("location", "Germany"))
    language_ok = hard_filters.get("language", "") in ("", "German", "English", "DE/EN")

    match_required = (len(skills & wanted) / len(wanted)) if wanted else 0.6
    match_preferred = (len(skills & preferred) / len(preferred)) if preferred else 0.5
    role_bonus = 0.15 if job.get("role_family") in profile.get("target_roles", []) else 0.0
    growth_bonus = 0.1 if job.get("learning_potential", "medium") == "high" else 0.04

    score = (0.55 * match_required) + (0.2 * match_preferred) + role_bonus + growth_bonus
    score = max(0.0, min(1.0, score))

    blockers = []
    if not location_ok:
        blockers.append("location_mismatch")
    if not language_ok:
        blockers.append("language_mismatch")

    risk = "high" if blockers else ("medium" if score < 0.6 else "low")
    return {
        **job,
        "match_score": round(score, 3),
        "risk": risk,
        "blockers": blockers,
        "reasoning": {
            "required_skill_match": round(match_required, 3),
            "preferred_skill_match": round(match_preferred, 3),
            "role_bonus": role_bonus,
            "growth_bonus": growth_bonus,
        },
    }


def classify_jobs(scored_jobs: List[Dict[str, Any]], thresholds: DecisionThresholds) -> List[Dict[str, Any]]:
    classified = []
    for job in scored_jobs:
        score = float(job.get("match_score", 0.0))
        blockers = job.get("blockers", [])
        if blockers:
            decision = "skip"
            reason = f"Hard blockers: {', '.join(blockers)}"
        elif score >= thresholds.apply_min:
            decision = "apply"
            reason = "Strong role and skill fit."
        elif score >= thresholds.optional_min:
            decision = "optional"
            reason = "Potential fit worth manual review."
        else:
            decision = "skip"
            reason = "Low fit vs current profile."
        classified.append({**job, "decision": decision, "decision_reason": reason})
    return classified


def render_template(template: str, data: Dict[str, Any]) -> str:
    out = template
    for key, value in data.items():
        out = out.replace(f"{{{{{key}}}}}", str(value))
    return out


def build_variants_for_job(job: Dict[str, Any], profile: Dict[str, Any], templates: Dict[str, str]) -> Dict[str, Any]:
    base = {
        "name": profile.get("name", "Candidate"),
        "role": job.get("title", "Duales Studium"),
        "company": job.get("company", "Unternehmen"),
        "skills": ", ".join(profile.get("skills", [])[:6]),
        "strengths": ", ".join(profile.get("strengths", [])[:4]),
    }
    cv_master = render_template(templates["cv_master"], base)
    letter_master = render_template(templates["cover_letter_master"], base)

    qualities = [
        ("v1_top", "high", "Highly tailored and evidence-focused."),
        ("v2_strong", "high", "Tailored with strong motivation signal."),
        ("v3_balanced", "medium", "Balanced fit narrative."),
        ("v4_generic", "medium", "Generic but role-relevant variant."),
        ("v5_fallback", "low", "Fallback quality for broad campaigns."),
    ]

    variants = []
    for name, quality, note in qualities:
        variants.append(
            {
                "variant": name,
                "quality_level": quality,
                "notes": note,
                "cv": cv_master,
                "cover_letter": letter_master,
            }
        )

    return {
        "job_id": job.get("id"),
        "company": job.get("company"),
        "title": job.get("title"),
        "variants": variants,
    }


def quality_checks(application_set: List[Dict[str, Any]]) -> Dict[str, Any]:
    checks = []
    for app in application_set:
        for variant in app.get("variants", []):
            cv = variant.get("cv", "")
            letter = variant.get("cover_letter", "")
            score = 0
            if len(cv) > 120:
                score += 1
            if len(letter) > 180:
                score += 1
            if "{{" not in cv and "{{" not in letter:
                score += 1
            checks.append(
                {
                    "job_id": app.get("job_id"),
                    "variant": variant.get("variant"),
                    "ats_ready": score >= 2,
                    "individuality": "high" if variant.get("quality_level") in ("high",) else "medium",
                    "clarity": "good" if score >= 2 else "needs_work",
                }
            )
    return {
        "checks": checks,
        "all_passed": all(c["ats_ready"] for c in checks) if checks else True,
    }
