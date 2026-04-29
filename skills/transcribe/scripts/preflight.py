from __future__ import annotations

import json
import re
from pathlib import Path

from contracts import InputPreflight

_FILLER_TOKENS = {"嗯", "啊", "呃", "额", "诶", "欸", "唉"}
_TERMINAL_PUNCTUATION = {"。", "！", "？", "!", "?", ";", "；"}


def normalize_manuscript_text(text: str | None) -> str:
    if text is None:
        return ""

    normalized_lines: list[str] = []
    for raw_line in text.splitlines():
        compact = re.sub(r"\s+", " ", raw_line).strip()
        if compact:
            normalized_lines.append(compact)
    return "\n".join(normalized_lines)


def _count_fillers(raw_payload: dict) -> int:
    count = 0
    for segment in raw_payload.get("segments") or []:
        for word in segment.get("words") or []:
            token = str(word.get("text") or "").strip()
            if token in _FILLER_TOKENS:
                count += 1
    return count


def _count_terminal_punctuation(raw_payload: dict) -> int:
    count = 0
    for segment in raw_payload.get("segments") or []:
        text = str(segment.get("text") or "").strip()
        if text and text[-1] in _TERMINAL_PUNCTUATION:
            count += 1
    return count


def build_input_preflight(*, raw_payload: dict, manuscript_text: str | None, user_override: str | None) -> InputPreflight:
    # Keep these signals deliberately small and additive in the first pass.
    # Routing can extend this structure later without breaking the artifact shape.
    normalized_manuscript = normalize_manuscript_text(manuscript_text)
    warnings: list[str] = []
    if manuscript_text is not None and not normalized_manuscript:
        warnings.append("empty manuscript after normalization")

    segments = raw_payload.get("segments") or []
    word_count = sum(len(segment.get("words") or []) for segment in segments)

    return InputPreflight(
        audio_ok=bool(segments),
        manuscript_present=bool(normalized_manuscript),
        manuscript_length=len(manuscript_text or ""),
        normalized_manuscript_length=len(normalized_manuscript),
        speaker_complexity_signals={
            "segment_count": len(segments),
            "word_count": word_count,
        },
        style_volatility_signals={
            "filler_count": _count_fillers(raw_payload),
            "terminal_punctuation_count": _count_terminal_punctuation(raw_payload),
        },
        user_override=user_override,
        warnings=warnings,
    )


def write_input_preflight(preflight: InputPreflight, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(preflight.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
