from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from auxiliary_drafting import AuxiliaryDraftingError, request_auxiliary_manuscript_draft
from contracts import (
    MAX_SUBTITLE_LINE_UNITS,
    DraftLine,
    DraftQualitySignals,
    DraftStyleFlags,
    ProofreadEdit,
    ProofreadManuscript,
    RawSpanMapping,
    RunGlossary,
    SubtitleDraft,
    count_text_punctuation_violations,
    strip_subtitle_punctuation,
    subtitle_display_length,
)
from preflight import normalize_manuscript_text
from segmentation import recover_raw_payload_for_alignment

MAX_LINE_CHARS = MAX_SUBTITLE_LINE_UNITS
TARGET_READING_SECONDS = 2.0
MAX_READING_SECONDS = 6.0
_STRONG_BREAK_RE = re.compile(r"(?<=[。！？!?；;])")
_SOFT_BREAK_CHARS = "，、,:："
_PROTECTED_ACRONYM_RE = re.compile(r"\b[A-Z]{2,8}\b")
_PROTECTED_MODEL_RE = re.compile(r"\b[A-Z]+[0-9]+[A-Z0-9]*\b")
_PROTECTED_TITLE_PHRASE_RE = re.compile(r"\b[A-Z][A-Za-z0-9-]*(?:\s+[A-Z][A-Za-z0-9-]*){1,2}\b")
_PROTECTED_MIXED_TERM_FRAGMENT_CHARS = set("的得地了吗呢啊吧呀有和在是这那个来去你我他她它们将还也都个就提到说讲聊造过向")


@dataclass
class Step2ADraftingResult:
    proofread: ProofreadManuscript
    draft: SubtitleDraft
    drafting_mode: str
    draft_model_provider: str | None
    draft_model_name: str | None
    draft_fallback_used: bool
    draft_fallback_reason: str | None
    draft_fallback_code: str | None
    draft_attempt_count: int
    text_authority: str = "llm"
    manual_review_required: bool = False
    alert_reasons: list[str] = field(default_factory=list)


def _raw_text(raw_payload: dict) -> str:
    direct_text = str(raw_payload.get("text") or "").strip()
    if direct_text:
        return direct_text
    return "".join(str(segment.get("text") or "") for segment in raw_payload.get("segments") or [])


def _glossary_candidates(term: str, aliases: list[str]) -> list[str]:
    candidates = [term, term.lower(), re.sub(r"\s+", "", term)]
    candidates.extend(aliases)
    deduped: list[str] = []
    for candidate in candidates:
        clean = candidate.strip()
        if clean and clean not in deduped:
            deduped.append(clean)
    return deduped


def _apply_glossary_hints(text: str, glossary: RunGlossary) -> tuple[str, list[ProofreadEdit], list[dict]]:
    updated = text
    edits: list[ProofreadEdit] = []
    entity_decisions: list[dict] = []

    for entry in sorted(glossary.terms, key=lambda item: len(item.term), reverse=True):
        for candidate in _glossary_candidates(entry.term, entry.aliases):
            if candidate == entry.term:
                continue
            if candidate in updated:
                updated = updated.replace(candidate, entry.term)
                edits.append(
                    ProofreadEdit(
                        kind="entity",
                        source_text=candidate,
                        updated_text=entry.term,
                        reason="glossary canonicalization",
                    )
                )
                entity_decisions.append({"raw": candidate, "final": entry.term})

    return updated, edits, entity_decisions


def build_proofread_manuscript(*, raw_payload: dict, manuscript_text: str | None, mode: str, glossary: RunGlossary) -> ProofreadManuscript:
    # Debug/bootstrap helper retained for local fixtures and tests.
    # Mainline Step 2A should go through build_step2a_artifacts().
    recovery_edits: list[ProofreadEdit] = []
    recovery_decisions: list[dict] = []
    drafting_warnings = ["bootstrap proofreading only"]

    if mode == "manuscript-priority" and manuscript_text:
        source_text = manuscript_text
        normalized_source = normalize_manuscript_text(manuscript_text)
        proofread_confidence = 0.88
    else:
        source_text = _raw_text(raw_payload)
        normalized_source = source_text.strip()
        proofread_confidence = 0.72
        if manuscript_text:
            recovered_payload, recoveries = recover_raw_payload_for_alignment(
                raw_payload=raw_payload,
                manuscript_text=manuscript_text,
            )
            if recoveries:
                normalized_source = _raw_text(recovered_payload)
                proofread_confidence = 0.78
                recovery_edits = [
                    ProofreadEdit(
                        kind="entity",
                        source_text=item.raw_fragment,
                        updated_text=item.recovered_term,
                        reason="manuscript-backed recovery",
                    )
                    for item in recoveries
                ]
                recovery_decisions = [{"raw": item.raw_fragment, "final": item.recovered_term} for item in recoveries]

    proofread_text, material_edits, entity_decisions = _apply_glossary_hints(normalized_source, glossary)
    edit_summary = "bootstrap proofreading"
    return ProofreadManuscript(
        source_text=source_text,
        proofread_text=proofread_text,
        edit_summary=edit_summary,
        material_edits=[*recovery_edits, *material_edits],
        entity_decisions=[*recovery_decisions, *entity_decisions],
        proofread_confidence=proofread_confidence,
        draft_ready=True,
        drafting_warnings=drafting_warnings,
    )


def _max_prefix_index_within_limit(text: str, max_line_chars: int) -> int:
    units = 0
    last_valid = 0
    for index, char in enumerate(text, start=1):
        if char.isspace():
            last_valid = index
            continue
        units += 1
        if units > max_line_chars:
            return max(last_valid, 1)
        last_valid = index
    return max(last_valid, 1)



def _protected_text_candidates(glossary: RunGlossary) -> list[str]:
    candidates: list[str] = []
    for entry in glossary.terms:
        for candidate in [entry.term, *entry.aliases]:
            clean = str(candidate).strip()
            if clean and _is_protected_candidate(clean) and clean not in candidates:
                candidates.append(clean)
    return sorted(candidates, key=len, reverse=True)



def _looks_like_protected_mixed_term(text: str) -> bool:
    parts = text.split()
    if not 2 <= len(parts) <= 3:
        return False
    cjk_prefix = parts[0]
    latin_tail = parts[1:]
    if not 2 <= len(cjk_prefix) <= 4:
        return False
    if any(char in _PROTECTED_MIXED_TERM_FRAGMENT_CHARS for char in cjk_prefix):
        return False
    if subtitle_display_length(text) > 10:
        return False
    first_token = latin_tail[0]
    if not (first_token[:1].isupper() or first_token.isupper()):
        return False
    return all(re.sub(r"[^A-Za-z0-9]", "", token) for token in latin_tail)



def _is_protected_candidate(text: str) -> bool:
    return (
        bool(_PROTECTED_ACRONYM_RE.fullmatch(text))
        or bool(_PROTECTED_MODEL_RE.fullmatch(text))
        or bool(_PROTECTED_TITLE_PHRASE_RE.fullmatch(text))
        or _looks_like_protected_mixed_term(text)
    )



def _collect_protected_spans(text: str, glossary: RunGlossary) -> list[tuple[int, int]]:
    matches: list[tuple[int, int]] = []
    for candidate in _protected_text_candidates(glossary):
        for match in re.finditer(re.escape(candidate), text):
            matches.append((match.start(), match.end()))
    for pattern in (
        _PROTECTED_ACRONYM_RE,
        _PROTECTED_MODEL_RE,
        _PROTECTED_TITLE_PHRASE_RE,
    ):
        for match in pattern.finditer(text):
            matches.append((match.start(), match.end()))

    selected: list[tuple[int, int]] = []
    for start, end in sorted(matches, key=lambda span: (-(span[1] - span[0]), span[0])):
        if end - start < 2:
            continue
        if any(not (end <= kept_start or start >= kept_end) for kept_start, kept_end in selected):
            continue
        selected.append((start, end))
    return sorted(selected)



def _split_index_is_safe(index: int, protected_spans: list[tuple[int, int]]) -> bool:
    return not any(start < index < end for start, end in protected_spans)



def _adjust_split_index_for_protected_spans(index: int, protected_spans: list[tuple[int, int]]) -> int:
    for start, end in protected_spans:
        if start < index < end:
            return start if start > 0 else end
    return index



def _split_long_piece(piece: str, max_line_chars: int, glossary: RunGlossary) -> list[str]:
    lines: list[str] = []
    remaining = piece.strip()
    while subtitle_display_length(remaining) > max_line_chars:
        protected_spans = _collect_protected_spans(remaining, glossary)
        limit_index = _max_prefix_index_within_limit(remaining, max_line_chars)
        split_index = -1
        for idx in range(limit_index, 0, -1):
            if not _split_index_is_safe(idx, protected_spans):
                continue
            if remaining[idx - 1] in _SOFT_BREAK_CHARS and subtitle_display_length(remaining[:idx].strip()) <= max_line_chars:
                split_index = idx
                break
        if split_index == -1:
            split_index = _adjust_split_index_for_protected_spans(limit_index, protected_spans)
        line_text = remaining[:split_index].strip()
        if not line_text:
            split_index = len(remaining)
            line_text = remaining
        lines.append(line_text)
        remaining = remaining[split_index:].strip()
    if remaining:
        lines.append(remaining)
    return lines



def _split_text_into_lines(text: str, glossary: RunGlossary, max_line_chars: int = MAX_LINE_CHARS) -> list[str]:
    paragraph_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not paragraph_lines:
        return []

    lines: list[str] = []
    for paragraph in paragraph_lines:
        pieces = [piece.strip() for piece in _STRONG_BREAK_RE.split(paragraph) if piece.strip()]
        for piece in pieces:
            if subtitle_display_length(piece) <= max_line_chars:
                lines.append(piece)
                continue
            lines.extend(_split_long_piece(piece, max_line_chars, glossary))
    return lines


def _coarse_raw_span_mapping(*, raw_payload: dict, line_id: int, line_count: int) -> RawSpanMapping:
    segments = raw_payload.get("segments") or []
    if not segments:
        return RawSpanMapping(mapping_confidence=0.0)

    chosen_index = min(max(line_id - 1, 0), len(segments) - 1)
    chosen_segment = segments[chosen_index]
    words = chosen_segment.get("words") or []
    segment_id = chosen_segment.get("id")
    confidence = 0.7 if line_count == len(segments) else 0.55
    return RawSpanMapping(
        segment_ids=[segment_id] if segment_id is not None else [],
        word_start_id=words[0].get("id") if words else None,
        word_end_id=words[-1].get("id") if words else None,
        mapping_confidence=confidence,
    )


def _semantic_integrity_label(text: str) -> str:
    if subtitle_display_length(text) <= MAX_LINE_CHARS:
        return "high"
    if subtitle_display_length(text) <= MAX_LINE_CHARS + 6:
        return "medium"
    return "low"


def build_subtitle_draft(*, raw_payload: dict, manuscript_text: str | None, mode: str, glossary: RunGlossary, proofread: ProofreadManuscript) -> SubtitleDraft:
    # Debug/bootstrap helper retained for local fixtures and tests.
    # Mainline Step 2A should go through build_step2a_artifacts().
    del manuscript_text
    # Keep the bootstrap output contract stable so a future Hermes-managed LLM
    # can swap in without changing downstream alignment expectations.
    if mode == "manuscript-priority":
        draft_source = proofread.proofread_text
        draft_notes = ["proofread manuscript draft"]
    else:
        raw_text = proofread.proofread_text if proofread.proofread_text else _raw_text(raw_payload)
        draft_source = raw_text
        draft_notes = ["raw transcript structure"]

    split_lines = _split_text_into_lines(draft_source, glossary)
    cleaned_lines = [cleaned for cleaned in (strip_subtitle_punctuation(line) for line in split_lines) if cleaned]
    lines: list[DraftLine] = []
    for index, cleaned_text in enumerate(cleaned_lines, start=1):
        lines.append(
            DraftLine(
                line_id=index,
                text=cleaned_text,
                source_mode=mode,
                draft_notes=list(draft_notes),
                style_flags=DraftStyleFlags(punctuation_free=True, delivery_plain_text=True),
                quality_signals=DraftQualitySignals(
                    semantic_integrity=_semantic_integrity_label(cleaned_text),
                    glossary_safe=True,
                ),
                raw_span_mapping=_coarse_raw_span_mapping(
                    raw_payload=raw_payload,
                    line_id=index,
                    line_count=len(cleaned_lines),
                ),
            )
        )
    return SubtitleDraft(lines=lines)


def _build_llm_proofread_manuscript(
    *,
    raw_payload: dict,
    manuscript_text: str,
    mode: str,
    glossary: RunGlossary,
    payload: dict,
) -> ProofreadManuscript:
    proofread_text, material_edits, entity_decisions = _apply_glossary_hints(
        str(payload.get("proofread_text") or "").strip(),
        glossary,
    )
    source_text = manuscript_text if mode == "manuscript-priority" else _raw_text(raw_payload)
    edit_summary = "llm proofreading" if mode == "manuscript-priority" else "llm raw-priority drafting"
    return ProofreadManuscript(
        source_text=source_text,
        proofread_text=proofread_text,
        edit_summary=edit_summary,
        material_edits=material_edits,
        entity_decisions=entity_decisions,
        proofread_confidence=float(payload.get("proofread_confidence") or 0.9),
        draft_ready=True,
        drafting_warnings=[str(item).strip() for item in (payload.get("drafting_warnings") or []) if str(item).strip()],
    )


def _build_llm_subtitle_draft(
    *,
    raw_payload: dict,
    mode: str,
    payload: dict,
) -> SubtitleDraft:
    subtitle_lines = [str(item).strip() for item in (payload.get("subtitle_lines") or []) if str(item).strip()]
    draft_notes = [str(item).strip() for item in (payload.get("draft_notes") or []) if str(item).strip()] or ["llm semantic draft"]
    semantic_integrity = str(payload.get("semantic_integrity") or "medium").strip().lower()
    if semantic_integrity not in {"high", "medium", "low"}:
        semantic_integrity = "medium"
    glossary_safe = bool(payload.get("glossary_safe", True))

    lines: list[DraftLine] = []
    for index, raw_text in enumerate(subtitle_lines, start=1):
        text = raw_text.strip()
        punctuation_free = count_text_punctuation_violations(text) == 0
        lines.append(
            DraftLine(
                line_id=index,
                text=text,
                source_mode=mode,
                draft_notes=list(draft_notes),
                style_flags=DraftStyleFlags(punctuation_free=punctuation_free, delivery_plain_text=punctuation_free),
                quality_signals=DraftQualitySignals(
                    semantic_integrity=semantic_integrity,
                    glossary_safe=glossary_safe,
                ),
                raw_span_mapping=_coarse_raw_span_mapping(
                    raw_payload=raw_payload,
                    line_id=index,
                    line_count=len(subtitle_lines),
                ),
            )
        )
    return SubtitleDraft(lines=lines)


def _build_manual_review_step2a_result(*, raw_payload: dict, manuscript_text: str | None, mode: str, reason: str) -> Step2ADraftingResult:
    source_text = manuscript_text if mode == "manuscript-priority" and manuscript_text else _raw_text(raw_payload)
    proofread = ProofreadManuscript(
        source_text=source_text,
        proofread_text=source_text,
        edit_summary="manual review required",
        proofread_confidence=0.0,
        draft_ready=False,
        drafting_warnings=[reason],
    )
    return Step2ADraftingResult(
        proofread=proofread,
        draft=SubtitleDraft(lines=[]),
        drafting_mode="manual-review-required",
        draft_model_provider=None,
        draft_model_name=None,
        draft_fallback_used=False,
        draft_fallback_reason=reason,
        draft_fallback_code="auxiliary_request_failed",
        draft_attempt_count=0,
        text_authority="none",
        manual_review_required=True,
        alert_reasons=[reason],
    )



def build_step2a_artifacts(*, raw_payload: dict, manuscript_text: str | None, mode: str, glossary: RunGlossary) -> Step2ADraftingResult:
    try:
        payload = request_auxiliary_manuscript_draft(
            raw_payload=raw_payload,
            manuscript_text=manuscript_text,
            mode=mode,
            skill_dir=Path(__file__).resolve().parents[1],
        )
        proofread = _build_llm_proofread_manuscript(
            raw_payload=raw_payload,
            manuscript_text=manuscript_text or _raw_text(raw_payload),
            mode=mode,
            glossary=glossary,
            payload=payload,
        )
        draft = _build_llm_subtitle_draft(
            raw_payload=raw_payload,
            mode=mode,
            payload=payload,
        )
        if not draft.lines:
            raise RuntimeError("auxiliary draft returned no usable subtitle lines")
        alert_reasons = [item for item in proofread.drafting_warnings if item.startswith("contract alert:")]
        drafting_mode = "llm-primary-with-alerts" if alert_reasons else "llm-primary"
        return Step2ADraftingResult(
            proofread=proofread,
            draft=draft,
            drafting_mode=drafting_mode,
            draft_model_provider=str(payload.get("provider_alias") or None),
            draft_model_name=str(payload.get("model") or None),
            draft_fallback_used=False,
            draft_fallback_reason=None,
            draft_fallback_code=None,
            draft_attempt_count=int(payload.get("attempt_count") or 1),
            text_authority="llm",
            manual_review_required=False,
            alert_reasons=alert_reasons,
        )
    except Exception as exc:
        fallback_reason = str(exc).strip() or exc.__class__.__name__
        return _build_manual_review_step2a_result(
            raw_payload=raw_payload,
            manuscript_text=manuscript_text,
            mode=mode,
            reason=fallback_reason,
        )


def write_proofread_manuscript(artifact: ProofreadManuscript, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def write_subtitle_draft(artifact: SubtitleDraft, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
