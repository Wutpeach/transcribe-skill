from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from contracts import AlignedSegment, AlignedSegmentsSummary, RunGlossary, SubtitleCue, SubtitleDraft, strip_subtitle_punctuation

_LOW_CONFIDENCE_THRESHOLD = 0.85
_MAX_SKIP_CHARS = 3
_MAX_EXTRA_CHARS = 6
_COLLAPSE_DURATION_SECONDS = 0.35
_COMPARABLE_CHAR_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]")


@dataclass
class _ComparableChar:
    value: str
    start: float
    end: float
    token_index: int
    char_offset: int
    token_char_count: int


def _word_surface(word: dict) -> str:
    return f"{word.get('text') or ''}{word.get('punctuation') or ''}"


def _flatten_raw_tokens(raw_payload: dict) -> list[dict]:
    tokens: list[dict] = []
    token_index = 0
    for segment in raw_payload.get("segments") or []:
        for word in segment.get("words") or []:
            tokens.append(
                {
                    "token_index": token_index,
                    "surface": _word_surface(word),
                    "start": float(word.get("start") or 0.0),
                    "end": float(word.get("end") or 0.0),
                }
            )
            token_index += 1
    return tokens


def _token_to_comparable_chars(token: dict) -> list[_ComparableChar]:
    comparable_chars = [char.lower() for char in token["surface"] if _COMPARABLE_CHAR_RE.fullmatch(char)]
    if not comparable_chars:
        return []

    duration = max(token["end"] - token["start"], 0.001)
    char_duration = duration / len(comparable_chars)
    units: list[_ComparableChar] = []
    for offset, char in enumerate(comparable_chars):
        start = token["start"] + char_duration * offset
        end = token["start"] + char_duration * (offset + 1)
        units.append(
            _ComparableChar(
                value=char,
                start=start,
                end=end,
                token_index=token["token_index"],
                char_offset=offset,
                token_char_count=len(comparable_chars),
            )
        )
    return units


def _expand_raw_chars(raw_payload: dict) -> list[_ComparableChar]:
    units: list[_ComparableChar] = []
    for token in _flatten_raw_tokens(raw_payload):
        units.extend(_token_to_comparable_chars(token))
    return units


def _draft_chars(text: str) -> list[str]:
    return [char.lower() for char in text if _COMPARABLE_CHAR_RE.fullmatch(char)]


def _find_best_span(line_chars: list[str], raw_chars: list[_ComparableChar], current_index: int) -> tuple[int, int, float]:
    if not raw_chars:
        return 0, 0, 0.0

    target = "".join(line_chars)
    if not target:
        start = min(current_index, len(raw_chars) - 1)
        return start, start, 1.0

    best_start = min(current_index, len(raw_chars) - 1)
    best_end = best_start
    best_score = -1.0

    search_start_limit = min(len(raw_chars) - 1, current_index + _MAX_SKIP_CHARS)
    for start in range(current_index, search_start_limit + 1):
        min_end = min(len(raw_chars) - 1, start + max(len(line_chars) - 1, 0))
        max_end = min(len(raw_chars) - 1, start + len(line_chars) + _MAX_EXTRA_CHARS)
        for end in range(min_end, max_end + 1):
            candidate = "".join(unit.value for unit in raw_chars[start : end + 1])
            score = SequenceMatcher(None, target, candidate).ratio()
            score -= abs(len(candidate) - len(target)) * 0.03
            score -= (start - current_index) * 0.05
            if score > best_score:
                best_start = start
                best_end = end
                best_score = score

    return best_start, best_end, max(best_score, 0.0)


def _split_points_for_span(start_unit: _ComparableChar, end_unit: _ComparableChar) -> list[dict]:
    split_points: list[dict] = []
    if start_unit.char_offset > 0:
        split_points.append(
            {
                "token_index": start_unit.token_index,
                "ratio": round(start_unit.char_offset / start_unit.token_char_count, 3),
                "side": "start",
            }
        )
    if end_unit.char_offset < end_unit.token_char_count - 1:
        split_points.append(
            {
                "token_index": end_unit.token_index,
                "ratio": round((end_unit.char_offset + 1) / end_unit.token_char_count, 3),
                "side": "end",
            }
        )
    return split_points


def _merge_segment_texts(texts: list[str]) -> str:
    return strip_subtitle_punctuation("".join(texts))


def _is_same_token_collapse_candidate(segment: AlignedSegment) -> bool:
    duration = float(segment.end) - float(segment.start)
    return (
        segment.alignment_score < _LOW_CONFIDENCE_THRESHOLD
        and duration <= _COLLAPSE_DURATION_SECONDS
        and segment.raw_token_start_index == segment.raw_token_end_index
    )


def _copy_segment(segment: AlignedSegment) -> AlignedSegment:
    return AlignedSegment(
        line_id=segment.line_id,
        text=segment.text,
        start=segment.start,
        end=segment.end,
        raw_token_start_index=segment.raw_token_start_index,
        raw_token_end_index=segment.raw_token_end_index,
        split_points=list(segment.split_points),
        alignment_score=segment.alignment_score,
        protected_entities=list(segment.protected_entities),
        warnings=list(segment.warnings),
    )


def _reindex_segments(segments: list[AlignedSegment]) -> list[AlignedSegment]:
    return [
        AlignedSegment(
            line_id=index,
            text=segment.text,
            start=segment.start,
            end=segment.end,
            raw_token_start_index=segment.raw_token_start_index,
            raw_token_end_index=segment.raw_token_end_index,
            split_points=list(segment.split_points),
            alignment_score=segment.alignment_score,
            protected_entities=list(segment.protected_entities),
            warnings=list(segment.warnings),
        )
        for index, segment in enumerate(segments, start=1)
    ]


def _apply_same_token_collapse_guard(segments: list[AlignedSegment]) -> list[AlignedSegment]:
    guarded: list[AlignedSegment] = []
    index = 0
    while index < len(segments):
        segment = segments[index]
        if not _is_same_token_collapse_candidate(segment):
            guarded.append(_copy_segment(segment))
            index += 1
            continue

        run_end = index + 1
        while run_end < len(segments):
            candidate = segments[run_end]
            if not _is_same_token_collapse_candidate(candidate):
                break
            if candidate.raw_token_start_index != segment.raw_token_start_index:
                break
            if candidate.raw_token_end_index != segment.raw_token_end_index:
                break
            run_end += 1

        run = segments[index:run_end]
        if len(run) == 1:
            guarded.append(_copy_segment(segment))
            index = run_end
            continue

        collapse_warning = f"timing collapse merged {run[0].line_id}-{run[-1].line_id}"
        if guarded and guarded[-1].raw_token_end_index >= run[0].raw_token_start_index:
            previous = guarded[-1]
            previous.text = _merge_segment_texts([previous.text, *[item.text for item in run]])
            previous.end = max(previous.end, run[-1].end)
            previous.raw_token_end_index = max(previous.raw_token_end_index, run[-1].raw_token_end_index)
            previous.alignment_score = min(previous.alignment_score, *(item.alignment_score for item in run))
            previous.warnings = list(dict.fromkeys([*previous.warnings, *(warning for item in run for warning in item.warnings), collapse_warning]))
        else:
            merged = _copy_segment(run[0])
            merged.text = _merge_segment_texts([item.text for item in run])
            merged.end = run[-1].end
            merged.raw_token_end_index = run[-1].raw_token_end_index
            merged.alignment_score = min(item.alignment_score for item in run)
            merged.warnings = list(dict.fromkeys([*(warning for item in run for warning in item.warnings), collapse_warning]))
            guarded.append(merged)
        index = run_end

    return _reindex_segments(guarded)


def align_draft_to_raw_tokens(*, draft: SubtitleDraft, raw_payload: dict, glossary: RunGlossary) -> tuple[list[AlignedSegment], AlignedSegmentsSummary]:
    del glossary  # Alignment keeps the interface ready for protected-entity-aware refinement.

    raw_chars = _expand_raw_chars(raw_payload)
    segments: list[AlignedSegment] = []
    current_index = 0

    for line in draft.lines:
        line_chars = _draft_chars(line.text)
        if not raw_chars:
            segments.append(
                AlignedSegment(
                    line_id=line.line_id,
                    text=line.text,
                    start=0.0,
                    end=0.0,
                    raw_token_start_index=0,
                    raw_token_end_index=0,
                    split_points=[],
                    alignment_score=0.0,
                    protected_entities=[],
                    warnings=["no raw timing characters available"],
                )
            )
            continue

        safe_current = min(current_index, len(raw_chars) - 1)
        start_index, end_index, score = _find_best_span(line_chars, raw_chars, safe_current)
        start_unit = raw_chars[start_index]
        end_unit = raw_chars[end_index]
        warnings: list[str] = []
        if score < _LOW_CONFIDENCE_THRESHOLD:
            warnings.append("low alignment confidence")
        if start_index > safe_current:
            warnings.append("skipped leading raw characters")

        segments.append(
            AlignedSegment(
                line_id=line.line_id,
                text=line.text,
                start=start_unit.start,
                end=end_unit.end,
                raw_token_start_index=start_unit.token_index,
                raw_token_end_index=end_unit.token_index,
                split_points=_split_points_for_span(start_unit, end_unit),
                alignment_score=round(score, 3),
                protected_entities=[],
                warnings=warnings,
            )
        )
        current_index = min(end_index + 1, len(raw_chars) - 1)

    segments = _apply_same_token_collapse_guard(segments)
    line_count = len(segments)
    mean_alignment_score = round(sum(segment.alignment_score for segment in segments) / line_count, 3) if line_count else 0.0
    low_confidence_count = sum(1 for segment in segments if segment.alignment_score < _LOW_CONFIDENCE_THRESHOLD)
    interpolated_boundary_count = sum(len(segment.split_points) for segment in segments)
    fallback_region_count = sum(1 for segment in segments if segment.warnings)
    summary = AlignedSegmentsSummary(
        line_count=line_count,
        mean_alignment_score=mean_alignment_score,
        low_confidence_count=low_confidence_count,
        interpolated_boundary_count=interpolated_boundary_count,
        fallback_region_count=fallback_region_count,
    )
    return segments, summary


def aligned_segments_to_cues(segments: list[AlignedSegment]) -> list[SubtitleCue]:
    return [
        SubtitleCue(index=index, start=segment.start, end=segment.end, text=segment.text)
        for index, segment in enumerate(segments, start=1)
    ]


def write_aligned_segments(*, segments: list[AlignedSegment], summary: AlignedSegmentsSummary, output_path: Path) -> None:
    payload = {
        "schema": "transcribe.aligned_segments.v2",
        "source_stage": "step-2b-alignment",
        "segments": [segment.to_dict() for segment in segments],
        "summary": summary.to_dict(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
