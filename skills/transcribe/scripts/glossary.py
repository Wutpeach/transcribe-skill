from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from auxiliary_config import AgentRuntimeConfig
from auxiliary_glossary import AuxiliaryCorrection, request_auxiliary_glossary_corrections
from contracts import GlossaryEntry, RunGlossary

_ACRONYM_RE = re.compile(r"\b[A-Z]{2,6}\b")
_MODEL_RE = re.compile(r"\b[A-Z]+[0-9]+[A-Z0-9]*\b")
_LATIN_PHRASE_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z][A-Za-z0-9-]*){1,2}\b")
_MIXED_TERM_RE = re.compile(r"[\u4e00-\u9fff]{1,6}\s+[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z0-9-]+){0,1}")
_FRAGMENT_PUNCT_RE = re.compile(r"[，。！？!?；;、]")
_FRAGMENT_CHARS = set("的得地了吗呢啊吧呀有和在是这那个来去你我他她它们将还也都个就提到说讲聊造过向")
_MIN_AUXILIARY_CONFIDENCE = 0.85
_LOGGER = logging.getLogger(__name__)


def _normalize_term(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _make_aliases(term: str) -> list[str]:
    aliases: list[str] = []
    lowered = term.lower()
    compact = re.sub(r"\s+", "", lowered)
    for candidate in [lowered, compact]:
        if candidate != term and candidate not in aliases:
            aliases.append(candidate)
    return aliases


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _has_latin_or_digit(text: str) -> bool:
    return bool(re.search(r"[A-Za-z0-9]", text))


def _looks_like_acronym(term: str) -> bool:
    return bool(_ACRONYM_RE.fullmatch(term))


def _looks_like_model(term: str) -> bool:
    return bool(_MODEL_RE.fullmatch(term))


def _looks_like_latin_phrase(term: str) -> bool:
    tokens = term.split()
    if not 2 <= len(tokens) <= 3:
        return False
    for token in tokens:
        if len(token) < 2:
            return False
        if not any(ch.isupper() for ch in token) and not any(ch.isdigit() for ch in token):
            return False
    return True


def _looks_like_mixed_term(term: str) -> bool:
    if not _has_cjk(term) or not _has_latin_or_digit(term):
        return False
    if _FRAGMENT_PUNCT_RE.search(term):
        return False

    parts = term.split()
    if not 2 <= len(parts) <= 3:
        return False

    cjk_prefix = parts[0]
    latin_tail = parts[1:]
    if not 2 <= len(cjk_prefix) <= 4:
        return False
    if any(char in _FRAGMENT_CHARS for char in cjk_prefix):
        return False

    first_token = latin_tail[0]
    latin_compact = re.sub(r"[^A-Za-z0-9]", "", first_token)
    if len(latin_compact) < 2:
        return False
    if not (first_token[:1].isupper() or first_token.isupper()):
        return False

    return all(len(re.sub(r"[^A-Za-z0-9]", "", token)) >= 2 for token in latin_tail)


def classify_term(term: str) -> str | None:
    candidate = term.strip()
    if not candidate or _FRAGMENT_PUNCT_RE.search(candidate):
        return None
    if _looks_like_model(candidate):
        return "model"
    if _looks_like_acronym(candidate):
        return "pure_acronym"
    if _looks_like_mixed_term(candidate):
        return "mixed_term"
    if _looks_like_latin_phrase(candidate):
        return "latin_term"
    return None


def _candidate_terms(manuscript_text: str) -> list[str]:
    candidates: list[str] = []

    def push(term: str) -> None:
        candidate = term.strip()
        if len(candidate) < 2:
            return
        if candidate not in candidates:
            candidates.append(candidate)

    for match in _MIXED_TERM_RE.findall(manuscript_text):
        parts = match.strip().split()
        if len(parts) < 2:
            continue
        cjk_prefix = parts[0]
        latin_tail = " ".join(parts[1:])
        for width in range(2, min(len(cjk_prefix), 4) + 1):
            push(f"{cjk_prefix[-width:]} {latin_tail}")

    for pattern in (_LATIN_PHRASE_RE, _MODEL_RE, _ACRONYM_RE):
        for match in pattern.findall(manuscript_text):
            push(match)

    return sorted(candidates, key=len, reverse=True)


def find_suspicious_glossary_terms(glossary: RunGlossary) -> list[str]:
    suspicious: list[str] = []
    for entry in glossary.terms:
        if classify_term(entry.term) is None:
            suspicious.append(entry.term)
    return suspicious


def _augment_aliases(existing: list[str], *candidates: str) -> list[str]:
    merged = list(existing)
    for candidate in candidates:
        cleaned = candidate.strip()
        compact = re.sub(r"\s+", "", cleaned)
        for item in [cleaned, cleaned.lower(), compact.lower()]:
            if item and item not in merged:
                merged.append(item)
    return merged


def _merge_auxiliary_corrections(*, terms: list[GlossaryEntry], corrections: list[AuxiliaryCorrection]) -> list[GlossaryEntry]:
    merged = list(terms)
    by_normalized = {_normalize_term(entry.term): entry for entry in merged}

    for correction in corrections:
        if correction.confidence < _MIN_AUXILIARY_CONFIDENCE:
            continue
        normalized = _normalize_term(correction.corrected)
        if not normalized:
            continue
        existing = by_normalized.get(normalized)
        if existing is not None:
            existing.aliases = _augment_aliases(existing.aliases, correction.original)
            continue
        term_type = classify_term(correction.corrected) or ("entity" if correction.kind == "entity" else "term")
        entry = GlossaryEntry(
            term=correction.corrected,
            aliases=_augment_aliases(_make_aliases(correction.corrected), correction.original),
            type=term_type,
            source="auxiliary",
        )
        merged.append(entry)
        by_normalized[normalized] = entry
    return merged


def build_run_glossary(
    *,
    raw_payload: dict,
    manuscript_text: str | None,
    agent_runtime: AgentRuntimeConfig | None = None,
) -> RunGlossary:
    if not manuscript_text or not manuscript_text.strip():
        return RunGlossary(terms=[], source="empty")

    raw_text_norm = _normalize_term(str(raw_payload.get("text") or ""))
    terms: list[GlossaryEntry] = []
    seen: set[str] = set()

    for candidate in _candidate_terms(manuscript_text):
        normalized = _normalize_term(candidate)
        if not normalized or normalized in seen:
            continue
        if raw_text_norm and normalized not in raw_text_norm:
            continue
        term_type = classify_term(candidate)
        if term_type is None:
            continue
        seen.add(normalized)
        terms.append(GlossaryEntry(term=candidate, aliases=_make_aliases(candidate), type=term_type, source="manuscript"))

    try:
        corrections = request_auxiliary_glossary_corrections(
            raw_payload=raw_payload,
            manuscript_text=manuscript_text,
            skill_dir=Path(__file__).resolve().parents[1],
            agent_runtime=agent_runtime,
        )
    except Exception as exc:
        _LOGGER.warning("Step 2A auxiliary glossary corrections unavailable: %s", exc)
        corrections = []

    if corrections:
        terms = _merge_auxiliary_corrections(terms=terms, corrections=corrections)

    return RunGlossary(terms=terms, source="manuscript")


def write_run_glossary(glossary: RunGlossary, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(glossary.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
