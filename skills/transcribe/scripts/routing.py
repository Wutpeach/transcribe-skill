from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from contracts import InputPreflight, ModeDecision
from preflight import normalize_manuscript_text

_PUNCT_SPACE_RE = re.compile(r"[\s\.,，。！？!?:：;；、\-—_()（）\[\]{}\"'“”‘’/\\]+")
_MANUSCRIPT_PRIORITY_GLOBAL = 0.90
_MANUSCRIPT_PRIORITY_LOCAL = 0.85
_RAW_PRIORITY_GLOBAL = 0.80
_WARNING_BAND_MANUSCRIPT_GLOBAL = 0.85
_WARNING_BAND_MANUSCRIPT_LOCAL = 0.80
_CONSERVATIVE_DEFAULT = "raw-priority"


def _normalize_for_similarity(text: str) -> str:
    lowered = text.lower()
    return _PUNCT_SPACE_RE.sub("", lowered)


def _raw_text(raw_payload: dict) -> str:
    direct_text = str(raw_payload.get("text") or "").strip()
    if direct_text:
        return direct_text
    return " ".join(str(segment.get("text") or "").strip() for segment in raw_payload.get("segments") or []).strip()


def score_manuscript_similarity(*, raw_payload: dict, manuscript_text: str | None) -> tuple[float, list[float]]:
    normalized_manuscript = normalize_manuscript_text(manuscript_text)
    if not normalized_manuscript:
        return 0.0, []

    raw_text_norm = _normalize_for_similarity(_raw_text(raw_payload))
    manuscript_norm = _normalize_for_similarity(normalized_manuscript)
    if not raw_text_norm or not manuscript_norm:
        return 0.0, []

    global_similarity = SequenceMatcher(None, raw_text_norm, manuscript_norm).ratio()

    raw_segments = [
        _normalize_for_similarity(str(segment.get("text") or ""))
        for segment in raw_payload.get("segments") or []
        if str(segment.get("text") or "").strip()
    ]
    manuscript_lines = [
        _normalize_for_similarity(line)
        for line in normalized_manuscript.splitlines()
        if line.strip()
    ]

    local_samples: list[float] = []
    if raw_segments and manuscript_lines:
        for line in manuscript_lines:
            if not line:
                continue
            local_samples.append(max(SequenceMatcher(None, line, segment).ratio() for segment in raw_segments))

    return global_similarity, local_samples


def _manuscript_completeness(raw_payload: dict, manuscript_text: str | None) -> float:
    manuscript_norm = _normalize_for_similarity(normalize_manuscript_text(manuscript_text))
    raw_norm = _normalize_for_similarity(_raw_text(raw_payload))
    if not manuscript_norm or not raw_norm:
        return 0.0
    return min(len(manuscript_norm) / len(raw_norm), 1.0)


def choose_mode(*, preflight: InputPreflight, raw_payload: dict, manuscript_text: str | None, user_override: str | None) -> ModeDecision:
    global_similarity, local_samples = score_manuscript_similarity(raw_payload=raw_payload, manuscript_text=manuscript_text)
    local_floor = min(local_samples) if local_samples else 0.0
    completeness = _manuscript_completeness(raw_payload, manuscript_text)
    signals = {
        **preflight.speaker_complexity_signals,
        **preflight.style_volatility_signals,
        "manuscript_present": preflight.manuscript_present,
    }
    reasons: list[str] = []

    if user_override and user_override != "auto":
        reasons.append("user override")
        return ModeDecision(
            mode=user_override,
            confidence=1.0,
            global_similarity=global_similarity,
            local_similarity_samples=local_samples,
            manuscript_completeness=completeness,
            signals=signals,
            reasons=reasons,
            user_override=user_override,
        )

    if not preflight.manuscript_present:
        reasons.append("manuscript missing or empty")
        return ModeDecision(
            mode="raw-priority",
            confidence=1.0,
            global_similarity=global_similarity,
            local_similarity_samples=local_samples,
            manuscript_completeness=completeness,
            signals=signals,
            reasons=reasons,
            user_override=user_override,
        )

    if global_similarity >= _MANUSCRIPT_PRIORITY_GLOBAL and local_floor >= _MANUSCRIPT_PRIORITY_LOCAL:
        reasons.append("high global and local manuscript similarity")
        confidence = round((global_similarity + local_floor) / 2, 3)
        return ModeDecision(
            mode="manuscript-priority",
            confidence=confidence,
            global_similarity=global_similarity,
            local_similarity_samples=local_samples,
            manuscript_completeness=completeness,
            signals=signals,
            reasons=reasons,
            user_override=user_override,
        )

    if global_similarity < _RAW_PRIORITY_GLOBAL:
        reasons.append("raw/manuscript similarity below raw-priority threshold")
        confidence = round(max(0.7, 1 - global_similarity), 3)
        return ModeDecision(
            mode="raw-priority",
            confidence=confidence,
            global_similarity=global_similarity,
            local_similarity_samples=local_samples,
            manuscript_completeness=completeness,
            signals=signals,
            reasons=reasons,
            user_override=user_override,
        )

    reasons.append("warning-band similarity; using conservative routing")
    average_local = sum(local_samples) / len(local_samples) if local_samples else global_similarity
    # Keep warning-band behavior explicit and stable for downstream drafting.
    mode = _CONSERVATIVE_DEFAULT
    if global_similarity >= _WARNING_BAND_MANUSCRIPT_GLOBAL and average_local >= _WARNING_BAND_MANUSCRIPT_LOCAL:
        mode = "manuscript-priority"
    confidence = round((global_similarity + average_local) / 2, 3)
    return ModeDecision(
        mode=mode,
        confidence=confidence,
        global_similarity=global_similarity,
        local_similarity_samples=local_samples,
        manuscript_completeness=completeness,
        signals=signals,
        reasons=reasons,
        user_override=user_override,
    )


def write_mode_decision(decision: ModeDecision, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
