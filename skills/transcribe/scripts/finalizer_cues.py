from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from contracts import SubtitleCue, strip_subtitle_punctuation

_CJK = r"\u4e00-\u9fff"
_MICRO_CUE_SECONDS = 0.6
_MICRO_CUE_CHARS = 3
_TAIL_FRAGMENT_RE = re.compile(r"^[的了呢吗吧啊呀哈呃诶嗯哦哇欸…，。！？!?；;、]{1,4}$")


@dataclass
class FinalizerResult:
    cues: list[SubtitleCue]
    change_breakdown: dict[str, dict[str, Any]] = field(default_factory=dict)
    applied_regions: list[int] = field(default_factory=list)
    applied_region_summary: str = ""
    correction_log: dict[str, Any] = field(default_factory=dict)
    delivery_audit: dict[str, Any] = field(default_factory=dict)
    split_operations: list[dict[str, Any]] = field(default_factory=list)
    validation_fallback_reasons: list[str] = field(default_factory=list)
    finalizer_mode: str = "rules-primary"
    finalizer_model_provider: str | None = None
    finalizer_model_name: str | None = None
    finalizer_fallback_used: bool = False
    finalizer_fallback_reason: str | None = None
    finalizer_fallback_code: str | None = None
    text_authority: str = "llm"
    manual_review_required: bool = False
    alert_reasons: list[str] = field(default_factory=list)


@dataclass
class CueSplitApplicationResult:
    cues: list[SubtitleCue]
    correction_entries: list[dict[str, Any]] = field(default_factory=list)
    cue_splits: list[dict[str, Any]] = field(default_factory=list)
    split_statistics: dict[str, int] = field(default_factory=dict)


class AgentReviewRequiredError(RuntimeError):
    pass


def normalize_mixed_spacing(text: str) -> str:
    text = re.sub(fr"(?<=[{_CJK}])(?=[A-Za-z0-9])", " ", text)
    text = re.sub(fr"(?<=[A-Za-z0-9])(?=[{_CJK}])", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def compact_len(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def is_micro_cue(cue: SubtitleCue) -> bool:
    duration = float(cue.end) - float(cue.start)
    cue_compact_len = compact_len(cue.text)
    if duration < _MICRO_CUE_SECONDS:
        return True
    if cue_compact_len <= _MICRO_CUE_CHARS:
        return True
    return bool(_TAIL_FRAGMENT_RE.fullmatch(cue.text.strip()))


def normalized_compact_text(text: str) -> str:
    return re.sub(r"\s+", "", strip_subtitle_punctuation(text)).strip()


def flatten_raw_words(raw_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for segment in raw_payload.get("segments") or [] if raw_payload else []:
        for word in segment.get("words") or []:
            text = str(word.get("text") or "")
            flattened.append(
                {
                    "token_index": len(flattened),
                    "segment_id": segment.get("id"),
                    "text": text,
                    "normalized_text": normalized_compact_text(text),
                    "start": float(word.get("start") or segment.get("start") or 0.0),
                    "end": float(word.get("end") or segment.get("end") or 0.0),
                    "punctuation": str(word.get("punctuation") or ""),
                }
            )
    return flattened


def longest_common_prefix_length(left: str, right: str) -> int:
    limit = min(len(left), len(right))
    idx = 0
    while idx < limit and left[idx] == right[idx]:
        idx += 1
    return idx


def candidate_suffix(tokens: list[dict[str, Any]], start_idx: int) -> str:
    return "".join(str(token.get("normalized_text") or "") for token in tokens[start_idx:])


def find_best_onset_token(tokens: list[dict[str, Any]], target_text: str) -> dict[str, Any] | None:
    target = normalized_compact_text(target_text)
    if not target:
        return None

    best: tuple[int, int, int] | None = None
    best_token: dict[str, Any] | None = None
    for idx, token in enumerate(tokens):
        token_norm = str(token.get("normalized_text") or "")
        if not token_norm:
            continue
        suffix = candidate_suffix(tokens, idx)
        prefix_len = longest_common_prefix_length(target, suffix)
        first_match = 1 if suffix and suffix[0] == target[0] else 0
        score = (first_match, prefix_len, -idx)
        if best is None or score > best:
            best = score
            best_token = token

    if best is None or best[1] == 0:
        return None
    return best_token


def build_split_statistics(cue_splits: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total_splits": len(cue_splits),
        "token_anchored_count": sum(1 for item in cue_splits if item.get("split_type") == "token_anchored"),
        "partial_token_anchored_count": sum(
            1 for item in cue_splits if item.get("split_type") == "partial_token_anchored"
        ),
        "proportional_fallback_count": sum(1 for item in cue_splits if item.get("split_type") == "proportional_fallback"),
        "low_confidence_split_count": sum(1 for item in cue_splits if item.get("split_confidence") == "low"),
    }


def apply_cue_splits(
    *,
    cues: list[SubtitleCue],
    split_decisions: list[dict[str, Any]],
    raw_payload: dict[str, Any],
    aligned_segments: list[dict[str, Any]],
    change_type: str = "agent_delivery_resegmentation",
    resegment_source: str = "agent_step3_manual_review",
) -> CueSplitApplicationResult:
    decision_map = {int(item["cue_index"]): list(item.get("texts") or []) for item in split_decisions}
    aligned_map = {int(item["line_id"]): item for item in aligned_segments}
    raw_tokens = flatten_raw_words(raw_payload)

    output_cues: list[SubtitleCue] = []
    correction_entries: list[dict[str, Any]] = []
    cue_splits: list[dict[str, Any]] = []
    next_index = 1

    for cue in cues:
        split_texts = decision_map.get(cue.index)
        if not split_texts or len(split_texts) <= 1:
            output_cues.append(SubtitleCue(index=next_index, start=cue.start, end=cue.end, text=cue.text))
            next_index += 1
            continue

        segment = aligned_map.get(cue.index)
        if segment is None:
            raise ValueError(f"missing aligned segment for cue {cue.index}")

        token_start = int(segment.get("raw_token_start_index"))
        token_end = int(segment.get("raw_token_end_index"))
        token_window = raw_tokens[token_start : token_end + 1]
        if not token_window:
            raise ValueError(f"empty raw token window for cue {cue.index}")

        alignment_score = float(segment.get("alignment_score") or 0.0)
        warnings = [str(item) for item in segment.get("warnings") or []]
        low_confidence = alignment_score < 0.75 or any("skipped leading" in item for item in warnings)

        starts = [float(cue.start)]
        split_point_token_indexes: list[int] = []
        fallback_steps: list[str] = []
        start_alignment_deltas_ms: list[int] = []

        for part_text in split_texts[1:]:
            onset_token = find_best_onset_token(token_window, part_text)
            if onset_token is None:
                total_units = sum(max(len(normalized_compact_text(text)), 1) for text in split_texts)
                completed_units = sum(max(len(normalized_compact_text(text)), 1) for text in split_texts[: len(starts)])
                ratio = completed_units / total_units if total_units else 0.5
                snapped_start = cue.start + ((cue.end - cue.start) * ratio)
                fallback_steps.append("proportional_fallback")
                split_point_token_indexes.append(token_window[-1]["token_index"])
                start_alignment_deltas_ms.append(0)
            else:
                snapped_start = float(onset_token["start"])
                split_point_token_indexes.append(int(onset_token["token_index"]))
                start_alignment_deltas_ms.append(int(round((snapped_start - float(onset_token["start"])) * 1000)))
                if low_confidence:
                    fallback_steps.append("partial_token_onset_snap")

            min_start = starts[-1] + 0.01
            max_start = float(cue.end) - 0.01
            snapped_start = min(max(snapped_start, min_start), max_start)
            starts.append(snapped_start)

        created_cues: list[SubtitleCue] = []
        created_indexes: list[int] = []
        for idx, part_text in enumerate(split_texts):
            part_start = starts[idx]
            part_end = starts[idx + 1] if idx + 1 < len(starts) else float(cue.end)
            if part_end <= part_start:
                part_end = part_start + 0.01
            created_cues.append(SubtitleCue(index=next_index, start=part_start, end=part_end, text=part_text))
            created_indexes.append(next_index)
            next_index += 1
        output_cues.extend(created_cues)

        split_type = "partial_token_anchored" if low_confidence else "token_anchored"
        if any(step == "proportional_fallback" for step in fallback_steps):
            split_type = "proportional_fallback"
        split_confidence = "low" if low_confidence else "high"
        risk_level = "high" if low_confidence else "low"
        used_fallback = bool(fallback_steps)

        correction_entries.append(
            {
                "cue_index": cue.index,
                "start": cue.start,
                "end": cue.end,
                "before": cue.text,
                "after": "\n".join(split_texts),
                "before_cues": [{"cue_index": cue.index, "text": cue.text}],
                "after_cues": [{"cue_index": item.index, "text": item.text} for item in created_cues],
                "source_cue_indexes": [cue.index],
                "change_types": [change_type],
                "resegment_source": [resegment_source],
            }
        )
        cue_splits.append(
            {
                "original_line_id": cue.index,
                "new_line_ids": created_indexes,
                "split_type": split_type,
                "split_confidence": split_confidence,
                "start_alignment_delta_ms": max(start_alignment_deltas_ms or [0]),
                "risk_level": risk_level,
                "used_fallback": used_fallback,
                "fallback_steps": fallback_steps,
                "split_point_token_index": split_point_token_indexes[0]
                if split_point_token_indexes
                else token_window[-1]["token_index"],
            }
        )

    return CueSplitApplicationResult(
        cues=output_cues,
        correction_entries=correction_entries,
        cue_splits=cue_splits,
        split_statistics=build_split_statistics(cue_splits),
    )
