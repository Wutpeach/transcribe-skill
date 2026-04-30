from __future__ import annotations

from typing import Any
import re

from contracts import AlignmentAudit, RunGlossary, SubtitleCue, count_text_punctuation_violations, subtitle_display_length
from finalizer_cues import AgentReviewRequiredError, FinalizerResult, build_split_statistics, is_micro_cue, apply_cue_splits


def empty_finalizer_breakdown() -> dict[str, dict[str, Any]]:
    return {
        "alias_replacements": {"count": 0, "examples": []},
        "spacing_normalizations": {"count": 0, "examples": []},
        "punctuation_normalizations": {"count": 0, "examples": []},
        "duplicate_collapses": {"count": 0, "examples": []},
        "delivery_resegmentations": {"count": 0, "examples": []},
    }


def validate_cues(cues: list[SubtitleCue]) -> list[str]:
    reasons: list[str] = []
    expected_index = 1
    for cue in cues:
        if cue.index != expected_index:
            reasons.append("cue_index_sequence_invalid")
            break
        expected_index += 1
    if any(float(cue.start) >= float(cue.end) for cue in cues):
        reasons.append("cue_timing_invalid")
    if any(not cue.text.strip() for cue in cues):
        reasons.append("cue_text_empty")
    return reasons


def validate_aligned_segments(cues: list[SubtitleCue], aligned_segments: list[dict[str, Any]] | None) -> list[str]:
    if aligned_segments is None:
        return []
    if len(aligned_segments) != len(cues):
        return ["aligned_segments_mismatch"]

    for cue, segment in zip(cues, aligned_segments):
        if int(segment.get("line_id", -1)) != cue.index:
            return ["aligned_segments_mismatch"]
        segment_text = str(segment.get("text") or "").strip()
        if segment_text and segment_text != cue.text.strip():
            return ["aligned_segments_mismatch"]
    return []


def build_cue_diff_entry(
    *,
    target_cue_index: int,
    source_cue_indexes: list[int],
    before_cues: list[dict[str, Any]],
    after_cues: list[dict[str, Any]],
    change_types: list[str],
    resegment_source: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "target_cue_index": target_cue_index,
        "source_cue_indexes": source_cue_indexes,
        "before_cues": before_cues,
        "after_cues": after_cues,
        "change_types": change_types,
        "resegment_source": resegment_source or [],
    }


def build_cue_diffs(correction_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cue_diffs: list[dict[str, Any]] = []
    for entry in correction_entries:
        cue_diffs.append(
            build_cue_diff_entry(
                target_cue_index=int(entry.get("cue_index") or 0),
                source_cue_indexes=list(
                    entry.get("source_cue_indexes") or [int(entry.get("cue_index") or 0)]
                ),
                before_cues=list(
                    entry.get("before_cues")
                    or [{"cue_index": int(entry.get("cue_index") or 0), "text": entry.get("before") or ""}]
                ),
                after_cues=list(
                    entry.get("after_cues")
                    or [{"cue_index": int(entry.get("cue_index") or 0), "text": entry.get("after") or ""}]
                ),
                change_types=list(entry.get("change_types") or []),
                resegment_source=list(entry.get("resegment_source") or []),
            )
        )
    return cue_diffs


def range_summary(indexes: list[int]) -> str:
    if not indexes:
        return ""
    sorted_indexes = sorted(set(indexes))
    ranges: list[str] = []
    start = prev = sorted_indexes[0]
    for value in sorted_indexes[1:]:
        if value == prev + 1:
            prev = value
            continue
        ranges.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = value
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    return ",".join(ranges)



def apply_delivery_timing_smoothing(cues: list[SubtitleCue]) -> tuple[list[SubtitleCue], dict[str, Any]]:
    if not cues:
        return [], {"applied": False, "first_cue_snapped": False, "gaps_filled": 0}

    epsilon = 1e-4
    smoothed_cues = [SubtitleCue(index=cue.index, start=float(cue.start), end=float(cue.end), text=cue.text) for cue in cues]
    first_cue_snapped = False
    gaps_filled = 0

    if abs(smoothed_cues[0].start) > epsilon:
        smoothed_cues[0].start = 0.0
        first_cue_snapped = True

    for index in range(len(smoothed_cues) - 1):
        current_cue = smoothed_cues[index]
        next_cue = smoothed_cues[index + 1]
        if float(current_cue.end) < float(next_cue.start) - epsilon:
            current_cue.end = float(next_cue.start)
            gaps_filled += 1

    return smoothed_cues, {
        "applied": True,
        "first_cue_snapped": first_cue_snapped,
        "gaps_filled": gaps_filled,
    }


def _candidate_trigger_length(text: str) -> int:
    return subtitle_display_length(text)


def _heuristic_split_texts(text: str) -> list[str] | None:
    stripped = text.strip()
    length = _candidate_trigger_length(stripped)
    if length < 11:
        return None

    rhythm_match = re.search(r"^(?P<left>.+的)\s+(?P<right>我们.+)$", stripped)
    if rhythm_match and 4 <= _candidate_trigger_length(rhythm_match.group("left")) <= 12 and 4 <= _candidate_trigger_length(rhythm_match.group("right")) <= 12:
        return [rhythm_match.group("left").strip(), rhythm_match.group("right").strip()]

    if length < 15:
        return None

    list_match = re.search(r"^(?P<left>.+距离)\s+(?P<right>速度\s+轨迹预测)$", stripped)
    if list_match:
        left = list_match.group("left").strip()
        right = list_match.group("right").strip()
        if _candidate_trigger_length(left) <= 14 and _candidate_trigger_length(right) <= 14:
            return [left, right]

    return None


def _build_heuristic_split_decisions(cues: list[SubtitleCue]) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for cue in cues:
        split_texts = _heuristic_split_texts(cue.text)
        if not split_texts or len(split_texts) <= 1:
            continue
        decisions.append({"cue_index": cue.index, "texts": split_texts})
    return decisions


def _heuristic_resegmentation_ready(*, raw_payload: dict[str, Any] | None, aligned_segments: list[dict[str, Any]] | None) -> bool:
    if not raw_payload or not aligned_segments:
        return False
    raw_segments = raw_payload.get("segments") or []
    if not any(segment.get("words") for segment in raw_segments):
        return False
    for segment in aligned_segments:
        if segment.get("raw_token_start_index") is None or segment.get("raw_token_end_index") is None:
            return False
    return True



def build_delivery_audit(
    *,
    cues: list[SubtitleCue],
    validation_fallback_reasons: list[str],
    resegment_sources: list[str],
    cue_splits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    punctuation_violation_count = sum(count_text_punctuation_violations(cue.text) for cue in cues)
    split_operations = list(cue_splits or [])
    checks = {
        "timing_monotonic": all(float(cue.start) < float(cue.end) for cue in cues),
        "empty_text_count": sum(1 for cue in cues if not cue.text.strip()),
        "cue_count": len(cues),
        "punctuation_violation_count": punctuation_violation_count,
        "micro_cue_count": sum(1 for cue in cues if is_micro_cue(cue)),
        "resegment_count": len(split_operations) if split_operations else len(resegment_sources),
    }
    cue_splitting = {
        "split_count": len(split_operations),
        "high_risk_count": sum(1 for item in split_operations if item.get("risk_level") == "high"),
        "max_length": max((len("".join(cue.text.split())) for cue in cues), default=0),
        "mean_alignment_delta_ms": round(
            sum(int(item.get("start_alignment_delta_ms") or 0) for item in split_operations) / len(split_operations),
            2,
        )
        if split_operations
        else 0,
    }
    if validation_fallback_reasons:
        return {
            "schema": "transcribe.final_delivery_audit.v1",
            "status": "ready_with_fallback",
            "risk": "medium",
            "checks": checks,
            "resegment_source": resegment_sources,
            "cue_splitting": cue_splitting,
            "reasons": validation_fallback_reasons,
        }
    if punctuation_violation_count:
        return {
            "schema": "transcribe.final_delivery_audit.v1",
            "status": "needs_review",
            "risk": "high",
            "checks": checks,
            "resegment_source": resegment_sources,
            "cue_splitting": cue_splitting,
            "reasons": ["punctuation_violation"],
        }
    return {
        "schema": "transcribe.final_delivery_audit.v1",
        "status": "ready",
        "risk": "low",
        "checks": checks,
        "resegment_source": resegment_sources,
        "cue_splitting": cue_splitting,
        "reasons": [],
    }


def finalize_cues(
    *,
    cues: list[SubtitleCue],
    glossary: RunGlossary,
    audit: AlignmentAudit | None = None,
    raw_payload: dict[str, Any] | None = None,
    proofread: dict[str, Any] | None = None,
    aligned_segments: list[dict[str, Any]] | None = None,
) -> FinalizerResult:
    del glossary, audit
    if proofread:
        raise AgentReviewRequiredError(
            "Step 3 final text authority belongs to the live agent review bundle; backend proofread-driven adjudication is retired."
        )

    validation_fallback_reasons: list[str] = []
    validation_fallback_reasons.extend(validate_cues(cues))
    validation_fallback_reasons.extend(validate_aligned_segments(cues, aligned_segments))
    validation_fallback_reasons = list(dict.fromkeys(validation_fallback_reasons))

    finalized = cues
    breakdown = empty_finalizer_breakdown()
    applied_regions: list[int] = []
    correction_entries: list[dict[str, Any]] = []
    split_operations: list[dict[str, Any]] = []
    finalizer_mode = "rules-primary"
    finalizer_model_provider = None
    finalizer_model_name = None
    finalizer_fallback_used = False
    finalizer_fallback_reason = None
    finalizer_fallback_code = None
    text_authority = "inherited"
    manual_review_required = False
    alert_reasons: list[str] = []

    heuristic_split_decisions: list[dict[str, Any]] = []
    if _heuristic_resegmentation_ready(raw_payload=raw_payload, aligned_segments=aligned_segments) and not validation_fallback_reasons:
        heuristic_split_decisions = _build_heuristic_split_decisions(cues)
        if heuristic_split_decisions:
            split_result = apply_cue_splits(
                cues=cues,
                split_decisions=heuristic_split_decisions,
                raw_payload=raw_payload,
                aligned_segments=aligned_segments,
                change_type="step3_heuristic_resegmentation",
                resegment_source="step3_heuristic_resegmentation",
            )
            finalized = split_result.cues
            correction_entries = split_result.correction_entries
            split_operations = split_result.cue_splits
            applied_regions = [int(item["cue_index"]) for item in correction_entries]

    breakdown["delivery_resegmentations"] = {
        "count": len(split_operations),
        "examples": [
            f"{item.get('original_line_id')}->{','.join(str(v) for v in item.get('new_line_ids') or [])}"
            for item in split_operations[:5]
        ],
    }
    resegment_sources: list[str] = ["step3_heuristic_resegmentation"] if split_operations else []
    cue_diffs = build_cue_diffs(correction_entries)
    split_statistics = build_split_statistics(split_operations)
    delivery_audit = build_delivery_audit(
        cues=finalized,
        validation_fallback_reasons=validation_fallback_reasons,
        resegment_sources=resegment_sources,
        cue_splits=split_operations,
    )
    if manual_review_required:
        delivery_audit["status"] = "needs_review"
        delivery_audit["risk"] = "high"
        delivery_audit["reasons"] = list(dict.fromkeys([*delivery_audit.get("reasons", []), *alert_reasons]))
    delivery_audit["cue_diffs"] = cue_diffs
    correction_log = {
        "schema": "transcribe.correction_log.v1",
        "cue_changes": correction_entries,
        "cue_diffs": cue_diffs,
        "cue_splits": split_operations,
        "split_statistics": split_statistics,
        "applied_region_summary": range_summary(applied_regions),
    }
    return FinalizerResult(
        cues=finalized,
        change_breakdown=breakdown,
        applied_regions=sorted(set(applied_regions)),
        applied_region_summary=correction_log["applied_region_summary"],
        correction_log=correction_log,
        delivery_audit=delivery_audit,
        split_operations=split_operations,
        validation_fallback_reasons=validation_fallback_reasons,
        finalizer_mode=finalizer_mode,
        finalizer_model_provider=finalizer_model_provider,
        finalizer_model_name=finalizer_model_name,
        finalizer_fallback_used=finalizer_fallback_used,
        finalizer_fallback_reason=finalizer_fallback_reason,
        finalizer_fallback_code=finalizer_fallback_code,
        text_authority=text_authority,
        manual_review_required=manual_review_required,
        alert_reasons=list(alert_reasons),
    )
