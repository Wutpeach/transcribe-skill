from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from contracts import SubtitleCue, SubtitleDraft
from drafting import Step2ADraftingResult
from finalizer import FinalizerResult

_STAGE_ORDER = ("step2a", "step2b", "step3")

_STEP2A_OVER_LIMIT_RE = re.compile(r"^contract alert: subtitle_lines\[(\d+)\] exceeds (\d+) display units$")
_STEP2A_PUNCTUATION_RE = re.compile(r"^contract alert: subtitle_lines\[(\d+)\] contains punctuation$")
_STEP2A_DRAFT_PUNCTUATION_RE = re.compile(r"^subtitle_draft_line_(\d+)_not_punctuation_free\[text=(.*)\]$")
_STEP2A_STYLE_FLAG_RE = re.compile(r"^subtitle_draft_line_(\d+)_style_flag_punctuation_free_false\[text=(.*)\]$")
_STEP2B_ALIGNED_PUNCTUATION_RE = re.compile(r"^aligned_segment_line_(\d+)_not_punctuation_free\[text=(.*)\]$")
_STEP2B_SCRIPT_PASS_PUNCTUATION_RE = re.compile(r"^step_2b_script_pass_cue_(\d+)_not_punctuation_free\[text=(.*)\]$")
_STEP3_FINAL_PUNCTUATION_RE = re.compile(r"^step_3_final_delivery_cue_(\d+)_not_punctuation_free\[text=(.*)\]$")


def _first_text(values: list[str]) -> str | None:
    for value in values:
        clean = str(value or "").strip()
        if clean:
            return clean
    return None


def _line_text_map(subtitle_draft: SubtitleDraft) -> dict[int, str]:
    return {int(line.line_id): str(line.text) for line in subtitle_draft.lines}


def _cue_text_map(cues: list[SubtitleCue]) -> dict[int, str]:
    return {int(cue.index): str(cue.text) for cue in cues}


def _build_case(
    *,
    kind: str,
    stage: str,
    code: str,
    message: str,
    source: str,
    line_id: int | None = None,
    cue_index: int | None = None,
    text_preview: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "stage": stage,
        "code": code,
        "message": message,
        "line_id": line_id,
        "cue_index": cue_index,
        "text_preview": text_preview,
        "source": source,
        "metadata": metadata or {},
    }


def _parse_step2a_alert_reason(reason: str, *, line_texts: dict[int, str]) -> dict[str, Any]:
    if match := _STEP2A_OVER_LIMIT_RE.match(reason):
        line_id = int(match.group(1))
        return _build_case(
            kind="alert",
            stage="step2a",
            code="line_over_limit",
            message=reason,
            line_id=line_id,
            cue_index=None,
            text_preview=line_texts.get(line_id),
            source="step2a_alert_reasons",
            metadata={"limit": int(match.group(2))},
        )
    if match := _STEP2A_PUNCTUATION_RE.match(reason):
        line_id = int(match.group(1))
        return _build_case(
            kind="alert",
            stage="step2a",
            code="contains_punctuation",
            message=reason,
            line_id=line_id,
            cue_index=None,
            text_preview=line_texts.get(line_id),
            source="step2a_alert_reasons",
        )
    if match := _STEP2A_DRAFT_PUNCTUATION_RE.match(reason):
        line_id = int(match.group(1))
        preview = match.group(2).strip() or line_texts.get(line_id)
        return _build_case(
            kind="alert",
            stage="step2a",
            code="draft_not_punctuation_free",
            message=reason,
            line_id=line_id,
            cue_index=None,
            text_preview=preview,
            source="step2a_alert_reasons",
        )
    if match := _STEP2A_STYLE_FLAG_RE.match(reason):
        line_id = int(match.group(1))
        preview = match.group(2).strip() or line_texts.get(line_id)
        return _build_case(
            kind="alert",
            stage="step2a",
            code="draft_style_flag_punctuation_false",
            message=reason,
            line_id=line_id,
            cue_index=None,
            text_preview=preview,
            source="step2a_alert_reasons",
        )
    return _build_case(
        kind="alert",
        stage="step2a",
        code="generic_alert",
        message=reason,
        source="step2a_alert_reasons",
    )


def _parse_step2b_alert_reason(reason: str, *, cue_texts: dict[int, str]) -> dict[str, Any]:
    if match := _STEP2B_ALIGNED_PUNCTUATION_RE.match(reason):
        cue_index = int(match.group(1))
        preview = cue_texts.get(cue_index) or match.group(2).strip() or None
        return _build_case(
            kind="alert",
            stage="step2b",
            code="aligned_segment_not_punctuation_free",
            message=reason,
            cue_index=cue_index,
            text_preview=preview,
            source="step2b_alert_reasons",
        )
    if match := _STEP2B_SCRIPT_PASS_PUNCTUATION_RE.match(reason):
        cue_index = int(match.group(1))
        preview = cue_texts.get(cue_index) or match.group(2).strip() or None
        return _build_case(
            kind="alert",
            stage="step2b",
            code="script_pass_not_punctuation_free",
            message=reason,
            cue_index=cue_index,
            text_preview=preview,
            source="step2b_alert_reasons",
        )
    return _build_case(
        kind="alert",
        stage="step2b",
        code="generic_alert",
        message=reason,
        source="step2b_alert_reasons",
    )


def _parse_step3_alert_reason(reason: str, *, cue_texts: dict[int, str], source: str) -> dict[str, Any]:
    if match := _STEP3_FINAL_PUNCTUATION_RE.match(reason):
        cue_index = int(match.group(1))
        preview = cue_texts.get(cue_index) or match.group(2).strip() or None
        return _build_case(
            kind="alert",
            stage="step3",
            code="final_delivery_not_punctuation_free",
            message=reason,
            cue_index=cue_index,
            text_preview=preview,
            source=source,
        )
    if reason in {"aligned_segments_mismatch", "cue_index_sequence_invalid", "cue_timing_invalid", "cue_text_empty"}:
        return _build_case(
            kind="alert",
            stage="step3",
            code=reason,
            message=reason,
            source=source,
        )
    return _build_case(
        kind="alert",
        stage="step3",
        code="generic_alert",
        message=reason,
        source=source,
    )


def _aggregate_cases(cases: list[dict[str, Any]]) -> tuple[dict[str, dict[str, int]], dict[str, int], list[dict[str, Any]]]:
    stage_counts = {
        stage: {"alert_count": 0, "manual_review_count": 0}
        for stage in _STAGE_ORDER
    }
    code_counts: Counter[str] = Counter()
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)

    for case in cases:
        stage = str(case["stage"])
        kind = str(case["kind"])
        code = str(case["code"])
        if stage in stage_counts:
            key = "manual_review_count" if kind == "manual_review" else "alert_count"
            stage_counts[stage][key] += 1
        code_counts[code] += 1
        grouped[(kind, stage, code)].append(case)

    grouped_cases: list[dict[str, Any]] = []
    for kind, stage, code in sorted(grouped.keys(), key=lambda item: (_STAGE_ORDER.index(item[1]), item[0], item[2])):
        items = grouped[(kind, stage, code)]
        sample_messages: list[str] = []
        sample_text_previews: list[str] = []
        for item in items:
            message = str(item["message"])
            if message and message not in sample_messages:
                sample_messages.append(message)
            preview = item.get("text_preview")
            if isinstance(preview, str) and preview and preview not in sample_text_previews:
                sample_text_previews.append(preview)
        grouped_cases.append(
            {
                "kind": kind,
                "stage": stage,
                "code": code,
                "count": len(items),
                "sample_messages": sample_messages[:5],
                "sample_text_previews": sample_text_previews[:5],
            }
        )

    return stage_counts, dict(code_counts), grouped_cases


def build_alert_tracking(
    *,
    step2a_result: Step2ADraftingResult,
    subtitle_draft: SubtitleDraft,
    step2a_alert_reasons: list[str],
    step2b_alert_reasons: list[str],
    script_pass_cues: list[SubtitleCue],
    finalizer_result: FinalizerResult,
    step3_validation_alert_reasons: list[str],
    edited_cues: list[SubtitleCue],
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    line_texts = _line_text_map(subtitle_draft)
    step2b_cue_texts = _cue_text_map(script_pass_cues)
    step3_cue_texts = _cue_text_map(edited_cues)

    step2a_manual_review_message = None
    if step2a_result.manual_review_required:
        step2a_manual_review_message = _first_text([
            step2a_result.draft_fallback_reason or "",
            *step2a_result.alert_reasons,
            "manual review required",
        ])
        cases.append(
            _build_case(
                kind="manual_review",
                stage="step2a",
                code=step2a_result.draft_fallback_code or "manual_review_required",
                message=step2a_manual_review_message or "manual review required",
                source="step2a_manual_review",
                metadata={
                    "attempt_count": int(step2a_result.draft_attempt_count),
                    "drafting_mode": step2a_result.drafting_mode,
                    "text_authority": step2a_result.text_authority,
                },
            )
        )

    for reason in step2a_alert_reasons:
        if step2a_manual_review_message and reason == step2a_manual_review_message:
            continue
        cases.append(_parse_step2a_alert_reason(reason, line_texts=line_texts))

    for reason in step2b_alert_reasons:
        cases.append(_parse_step2b_alert_reason(reason, cue_texts=step2b_cue_texts))

    step3_manual_review_message = None
    skip_step3_echo = finalizer_result.finalizer_fallback_code == "step2a_manual_review_required"
    if finalizer_result.manual_review_required and not skip_step3_echo:
        step3_manual_review_message = _first_text([
            finalizer_result.finalizer_fallback_reason or "",
            *finalizer_result.alert_reasons,
            "manual review required",
        ])
        cases.append(
            _build_case(
                kind="manual_review",
                stage="step3",
                code=finalizer_result.finalizer_fallback_code or "manual_review_required",
                message=step3_manual_review_message or "manual review required",
                source="step3_manual_review",
                metadata={
                    "finalizer_mode": finalizer_result.finalizer_mode,
                    "text_authority": finalizer_result.text_authority,
                },
            )
        )

    if not skip_step3_echo:
        for reason in finalizer_result.alert_reasons:
            if step3_manual_review_message and reason == step3_manual_review_message:
                continue
            cases.append(_parse_step3_alert_reason(reason, cue_texts=step3_cue_texts, source="step3_alert_reasons"))

        for reason in finalizer_result.validation_fallback_reasons:
            cases.append(_parse_step3_alert_reason(reason, cue_texts=step3_cue_texts, source="step3_validation_fallback_reasons"))

        for reason in step3_validation_alert_reasons:
            cases.append(_parse_step3_alert_reason(reason, cue_texts=step3_cue_texts, source="step3_validation_alert_reasons"))

    stage_counts, code_counts, grouped_cases = _aggregate_cases(cases)
    alert_case_count = sum(1 for case in cases if case["kind"] == "alert")
    manual_review_case_count = sum(1 for case in cases if case["kind"] == "manual_review")
    return {
        "schema": "transcribe.alert_tracking.v1",
        "manual_review_required": step2a_result.manual_review_required or finalizer_result.manual_review_required,
        "alert_case_count": alert_case_count,
        "manual_review_case_count": manual_review_case_count,
        "stage_counts": stage_counts,
        "code_counts": code_counts,
        "grouped_cases": grouped_cases,
        "cases": cases,
    }


def write_alert_tracking(alert_tracking: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(alert_tracking, ensure_ascii=False, indent=2), encoding="utf-8")
