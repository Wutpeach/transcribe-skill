from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from contracts import AlignedSegmentsSummary
from finalizer import FinalizerResult, empty_finalizer_breakdown


def write_initial_report(
    *,
    output_path: Path,
    raw_payload: dict,
    chosen_mode: str,
    post_alignment_mode: str,
    route_decision_reasons: list[str],
    alignment_summary: AlignedSegmentsSummary,
    downgrade_count: int,
    glossary_term_count: int,
    script_pass_count: int,
    edited_count: int | None,
    glossary_applied: bool,
    short_cue_count: int,
    short_cue_examples: list[dict],
    suspicious_glossary_terms: list[str],
    entity_recovery_count: int,
    entity_recovery_examples: list[dict],
    drafting_mode: str,
    subtitle_punctuation_violation_count: int,
    semantic_cut_suspect_count: int,
    draft_model_provider: str | None,
    draft_model_name: str | None,
    draft_fallback_used: bool,
    draft_fallback_reason: str | None,
    draft_fallback_code: str | None,
    draft_attempt_count: int,
    step2a_text_authority: str,
    step2a_manual_review_required: bool,
    step2a_alert_reasons: list[str],
    step3_status: str,
    step3_text_authority: str,
    step3_alert_reasons: list[str],
    alert_tracking_summary: dict[str, object],
    step3_owner: str = "interactive-agent",
    step3_execution_mode: str = "agent-session",
) -> None:
    aligned_line_count = alignment_summary.line_count or 0
    alignment_success_rate = round(
        (aligned_line_count - alignment_summary.low_confidence_count) / aligned_line_count,
        3,
    ) if aligned_line_count else 0.0

    finalizer_breakdown = empty_finalizer_breakdown()
    finalizer_applied_regions = ""
    finalizer_change_count = 0
    finalizer_model_provider = None
    finalizer_model_name = None
    finalizer_fallback_used = False
    finalizer_fallback_reason = None
    finalizer_fallback_code = None

    if step3_status == "blocked":
        final_delivery_status = "blocked"
        final_delivery_risk = "high"
        final_delivery_reasons = list(dict.fromkeys(step3_alert_reasons or step2a_alert_reasons or ["step3_blocked"]))
        finalizer_mode = "blocked"
        manual_review_required = True
    else:
        final_delivery_status = "awaiting_agent_review"
        final_delivery_risk = "pending"
        final_delivery_reasons = []
        finalizer_mode = "agent-session-pending"
        manual_review_required = step2a_manual_review_required

    report = {
        "schema": "transcribe.report.v3",
        "backend": raw_payload.get("backend") or "funasr-api",
        "chosen_mode": chosen_mode,
        "post_alignment_mode": post_alignment_mode,
        "route_decision_reasons": route_decision_reasons,
        "drafting_mode": drafting_mode,
        "draft_model_provider": draft_model_provider,
        "draft_model_name": draft_model_name,
        "draft_fallback_used": draft_fallback_used,
        "draft_fallback_reason": draft_fallback_reason,
        "draft_fallback_code": draft_fallback_code,
        "draft_attempt_count": draft_attempt_count,
        "step2a_text_authority": step2a_text_authority,
        "step3_owner": step3_owner,
        "step3_execution_mode": step3_execution_mode,
        "step3_status": step3_status,
        "step3_text_authority": step3_text_authority,
        "script_text_override_used": False,
        "timing_text_override_used": False,
        "timing_only_fallback_used": post_alignment_mode != chosen_mode or downgrade_count > 0,
        "manual_review_required": manual_review_required,
        "step2a_alert_reasons": step2a_alert_reasons,
        "step3_alert_reasons": step3_alert_reasons,
        "alert_tracking_summary": alert_tracking_summary,
        "alignment_mean_score": alignment_summary.mean_alignment_score,
        "alignment_success_rate": alignment_success_rate,
        "low_confidence_alignment_count": alignment_summary.low_confidence_count,
        "interpolated_boundary_count": alignment_summary.interpolated_boundary_count,
        "fallback_region_count": alignment_summary.fallback_region_count,
        "downgrade_count": downgrade_count,
        "timing_metadata": {
            "segment_count": len(raw_payload.get("segments") or []),
            "word_count": sum(len(segment.get("words") or []) for segment in raw_payload.get("segments") or []),
        },
        "segmentation_stats": {
            "script_pass_cue_count": script_pass_count,
            "edited_cue_count": edited_count,
        },
        "edited_cue_count": edited_count,
        "split_count": 0,
        "cue_splitting": {
            "split_count": 0,
            "high_risk_count": 0,
            "max_length": 0,
            "mean_alignment_delta_ms": 0,
        },
        "glossary_applied": glossary_applied,
        "glossary_term_count": glossary_term_count,
        "short_cue_count": short_cue_count,
        "micro_cue_examples": short_cue_examples,
        "suspicious_glossary_terms": suspicious_glossary_terms,
        "entity_recovery_count": entity_recovery_count,
        "entity_recovery_examples": entity_recovery_examples,
        "subtitle_punctuation_violation_count": subtitle_punctuation_violation_count,
        "semantic_cut_suspect_count": semantic_cut_suspect_count,
        "finalizer_change_count": finalizer_change_count,
        "finalizer_change_breakdown": finalizer_breakdown,
        "final_delivery_risk": final_delivery_risk,
        "final_delivery_reasons": final_delivery_reasons,
        "finalizer_applied_regions": finalizer_applied_regions,
        "final_delivery_status": final_delivery_status,
        "finalizer_mode": finalizer_mode,
        "finalizer_model_provider": finalizer_model_provider,
        "finalizer_model_name": finalizer_model_name,
        "finalizer_fallback_used": finalizer_fallback_used,
        "finalizer_fallback_reason": finalizer_fallback_reason,
        "finalizer_fallback_code": finalizer_fallback_code,
    }
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def step3_status_from_finalizer_result(finalizer_result: FinalizerResult) -> str:
    if (
        finalizer_result.delivery_audit.get("status") == "ready"
        and finalizer_result.delivery_audit.get("risk") == "low"
        and not finalizer_result.manual_review_required
    ):
        return "adjudicated_ready"
    return "adjudicated_needs_review"


def step3_alert_reasons_from_finalizer_result(finalizer_result: FinalizerResult) -> list[str]:
    return list(
        dict.fromkeys(
            [
                *list(finalizer_result.validation_fallback_reasons),
                *list(finalizer_result.alert_reasons),
                *list(finalizer_result.delivery_audit.get("reasons") or []),
            ]
        )
    )


def report_finalizer_breakdown(finalizer_result: FinalizerResult) -> dict[str, dict[str, object]]:
    breakdown = empty_finalizer_breakdown()
    for key, value in (finalizer_result.change_breakdown or {}).items():
        if key in breakdown and isinstance(value, dict):
            breakdown[key] = {
                "count": int(value.get("count") or 0),
                "examples": list(value.get("examples") or []),
            }
    split_examples = [
        f"{item.get('original_line_id')}->{','.join(str(v) for v in item.get('new_line_ids') or [])}"
        for item in finalizer_result.split_operations
    ]
    breakdown["delivery_resegmentations"] = {
        "count": len(finalizer_result.split_operations),
        "examples": split_examples[:5],
    }
    return breakdown


def validate_step3_review_artifacts(finalizer_result: FinalizerResult) -> None:
    correction_schema = finalizer_result.correction_log.get("schema")
    if correction_schema != "transcribe.correction_log.v1":
        raise ValueError(f"invalid correction_log schema: {correction_schema!r}")
    delivery_schema = finalizer_result.delivery_audit.get("schema")
    if delivery_schema != "transcribe.final_delivery_audit.v1":
        raise ValueError(f"invalid final_delivery_audit schema: {delivery_schema!r}")


def validate_pending_step3_report(report: dict[str, Any]) -> None:
    schema = report.get("schema")
    if schema != "transcribe.report.v3":
        raise ValueError(f"invalid report schema: {schema!r}")
    status = report.get("step3_status")
    if status != "awaiting_agent_review":
        raise ValueError(
            f"step3 writeback requires report step3_status='awaiting_agent_review', got {status!r}"
        )


def update_report_for_step3_review(*, report_path: Path, finalizer_result: FinalizerResult) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    validate_pending_step3_report(report)
    validate_step3_review_artifacts(finalizer_result)

    report["step3_status"] = step3_status_from_finalizer_result(finalizer_result)
    report["step3_text_authority"] = finalizer_result.text_authority
    report["step3_alert_reasons"] = step3_alert_reasons_from_finalizer_result(finalizer_result)
    report["manual_review_required"] = finalizer_result.manual_review_required
    report["final_delivery_status"] = finalizer_result.delivery_audit.get("status")
    report["final_delivery_risk"] = finalizer_result.delivery_audit.get("risk")
    report["final_delivery_reasons"] = list(finalizer_result.delivery_audit.get("reasons") or [])
    report["finalizer_change_count"] = len(list(finalizer_result.correction_log.get("cue_changes") or []))
    report["finalizer_change_breakdown"] = report_finalizer_breakdown(finalizer_result)
    report["finalizer_applied_regions"] = finalizer_result.applied_region_summary
    report["finalizer_mode"] = finalizer_result.finalizer_mode
    report["finalizer_model_provider"] = finalizer_result.finalizer_model_provider
    report["finalizer_model_name"] = finalizer_result.finalizer_model_name
    report["finalizer_fallback_used"] = finalizer_result.finalizer_fallback_used
    report["finalizer_fallback_reason"] = finalizer_result.finalizer_fallback_reason
    report["finalizer_fallback_code"] = finalizer_result.finalizer_fallback_code
    segmentation_stats = dict(report.get("segmentation_stats") or {})
    segmentation_stats["edited_cue_count"] = len(finalizer_result.cues)
    report["segmentation_stats"] = segmentation_stats
    report["edited_cue_count"] = len(finalizer_result.cues)
    report["split_count"] = len(finalizer_result.split_operations)
    report["cue_splitting"] = dict(finalizer_result.delivery_audit.get("cue_splitting") or {})
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
