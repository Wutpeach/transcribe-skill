from __future__ import annotations

from typing import Any

from finalizer import FinalizerResult, empty_finalizer_breakdown


def manual_review_finalizer_result(*, reasons: list[str]) -> FinalizerResult:
    final_reasons = reasons or ["step_2a_manual_review_required"]
    return FinalizerResult(
        cues=[],
        change_breakdown=empty_finalizer_breakdown(),
        applied_regions=[],
        applied_region_summary="",
        correction_log={
            "schema": "transcribe.correction_log.v1",
            "cue_changes": [],
            "cue_diffs": [],
            "applied_region_summary": "",
        },
        delivery_audit={
            "schema": "transcribe.final_delivery_audit.v1",
            "status": "needs_review",
            "risk": "high",
            "checks": {
                "timing_monotonic": True,
                "empty_text_count": 0,
                "cue_count": 0,
                "punctuation_violation_count": 0,
                "micro_cue_count": 0,
                "resegment_count": 0,
            },
            "resegment_source": [],
            "reasons": final_reasons,
            "cue_diffs": [],
        },
        validation_fallback_reasons=[],
        finalizer_mode="manual-review-required",
        finalizer_model_provider=None,
        finalizer_model_name=None,
        finalizer_fallback_used=False,
        finalizer_fallback_reason=final_reasons[0],
        finalizer_fallback_code="step2a_manual_review_required",
        text_authority="none",
        manual_review_required=True,
        alert_reasons=final_reasons,
    )


def build_pending_step3_placeholder_result(*, script_pass_cues) -> FinalizerResult:
    return FinalizerResult(
        cues=script_pass_cues,
        change_breakdown=empty_finalizer_breakdown(),
        applied_regions=[],
        applied_region_summary="",
        correction_log={
            "schema": "transcribe.correction_log.v1",
            "cue_changes": [],
            "cue_diffs": [],
            "applied_region_summary": "",
        },
        delivery_audit={
            "schema": "transcribe.final_delivery_audit.v1",
            "status": "awaiting_agent_review",
            "risk": "pending",
            "checks": {},
            "reasons": [],
            "cue_diffs": [],
        },
        validation_fallback_reasons=[],
        finalizer_mode="agent-session-pending",
        finalizer_model_provider=None,
        finalizer_model_name=None,
        finalizer_fallback_used=False,
        finalizer_fallback_reason=None,
        finalizer_fallback_code=None,
        text_authority="interactive-agent",
        manual_review_required=False,
        alert_reasons=[],
    )


def bundle_priority_cases(alert_tracking: dict[str, Any], *, limit: int = 5) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for case in alert_tracking.get("cases") or []:
        cases.append(
            {
                "cue_index": case.get("cue_index") or case.get("line_id"),
                "reason": case.get("code") or case.get("message"),
                "text": case.get("text_preview") or "",
            }
        )
        if len(cases) >= limit:
            break
    return cases
