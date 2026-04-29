from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from contracts import EntityRecovery, RunGlossary, SegmentationResult, SubtitleCue

_SOFT_LIMIT = 17
_MICRO_CUE_SECONDS = 0.6
_MICRO_CUE_CHARS = 3
_STRONG_BREAK_RE = re.compile(r"[。！？!?；;]$")
_TAIL_FRAGMENT_RE = re.compile(r"^[的了呢吗吧啊呀哈呃诶嗯哦哇欸…，。！？!?；;、]{1,4}$")
_MANUSCRIPT_ENTITY_RE = re.compile(r"[\u4e00-\u9fff]{2,5}\s+[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z0-9-]+){0,1}")
_SUSPICIOUS_FRAGMENT_RE = re.compile(r"[a-z][a-z0-9]{1,4}")
_ANCHOR_CHAR_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]+")
_CLAUSE_SPLIT_RE = re.compile(r"[。！？!?；;\n]+")


@dataclass
class _Unit:
    text: str
    start: float
    end: float


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _word_surface(word: dict) -> str:
    return f"{word.get('text') or ''}{word.get('punctuation') or ''}"


def _clean_fragment(text: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9]", "", text or "")
    return compact.lower()


def _looks_suspicious_fragment(word: dict) -> bool:
    text = str(word.get("text") or "")
    if re.search(r"[\u4e00-\u9fff]", text):
        return False
    compact = _clean_fragment(text)
    if not compact or not _SUSPICIOUS_FRAGMENT_RE.fullmatch(compact):
        return False
    return any(ch.isalpha() for ch in compact)


def _split_manuscript_clauses(manuscript_text: str) -> list[str]:
    clauses: list[str] = []
    for piece in _CLAUSE_SPLIT_RE.split(manuscript_text):
        clause = piece.strip()
        if clause:
            clauses.append(clause)
    return clauses


def _extract_recoverable_entities(clause: str) -> list[str]:
    entities: list[str] = []
    seen: set[str] = set()
    for match in _MANUSCRIPT_ENTITY_RE.finditer(clause):
        entity = match.group(0).strip()
        normalized = _normalize(entity)
        if normalized in seen:
            continue
        seen.add(normalized)
        entities.append(entity)
    return entities


def _anchor_text(text: str) -> str:
    return "".join(_ANCHOR_CHAR_RE.findall(text)).lower()


def _remove_entities_from_clause(clause: str, entities: list[str]) -> str:
    reduced = clause
    for entity in entities:
        reduced = reduced.replace(entity, " ", 1)
    return reduced


def _trim_overlapping_prefix(entity: str, prefix_text: str) -> str:
    prefix = _anchor_text(prefix_text)
    if not prefix:
        return entity

    parts = entity.split()
    if len(parts) < 2:
        return entity

    cjk_prefix = parts[0]
    latin_tail = " ".join(parts[1:])
    compact_prefix = _anchor_text(cjk_prefix)
    if compact_prefix.startswith(prefix):
        trimmed_prefix = cjk_prefix[len(prefix) :]
        candidate = f"{trimmed_prefix} {latin_tail}".strip()
        if candidate == latin_tail or _MANUSCRIPT_ENTITY_RE.fullmatch(candidate):
            return candidate
        return entity

    if prefix.endswith(compact_prefix):
        return latin_tail

    return entity


def _anchor_matches(raw_anchor: str, manuscript_anchor: str) -> bool:
    if not raw_anchor or not manuscript_anchor:
        return False
    if raw_anchor in manuscript_anchor or manuscript_anchor in raw_anchor:
        return True
    return SequenceMatcher(None, raw_anchor, manuscript_anchor).ratio() >= 0.72


def _recover_words_from_manuscript(
    *,
    words: list[dict],
    segment_id: int | str | None,
    manuscript_text: str | None,
) -> tuple[list[dict], list[EntityRecovery]]:
    if not manuscript_text or not manuscript_text.strip():
        return words, []

    suspicious_indexes = [idx for idx, word in enumerate(words) if _looks_suspicious_fragment(word)]
    if not suspicious_indexes:
        return words, []

    raw_anchor = _anchor_text("".join(_word_surface(word) for idx, word in enumerate(words) if idx not in suspicious_indexes))
    if not raw_anchor:
        return words, []

    best_entities: list[str] | None = None
    best_score = 0.0
    best_anchor_len = -1

    for clause in _split_manuscript_clauses(manuscript_text):
        entities = _extract_recoverable_entities(clause)
        if len(entities) != len(suspicious_indexes):
            continue
        manuscript_anchor = _anchor_text(_remove_entities_from_clause(clause, entities))
        if not _anchor_matches(raw_anchor, manuscript_anchor):
            continue
        score = SequenceMatcher(None, raw_anchor, manuscript_anchor).ratio()
        if score > best_score or (score == best_score and len(manuscript_anchor) > best_anchor_len):
            best_entities = entities
            best_score = score
            best_anchor_len = len(manuscript_anchor)

    if best_entities is None:
        return words, []

    leading_anchor_text = "".join(_word_surface(word) for word in words[: suspicious_indexes[0]])
    adjusted_entities = list(best_entities)
    adjusted_entities[0] = _trim_overlapping_prefix(adjusted_entities[0], leading_anchor_text)

    updated_words = [dict(word) for word in words]
    recoveries: list[EntityRecovery] = []
    for index, entity in zip(suspicious_indexes, adjusted_entities):
        original_text = str(updated_words[index].get("text") or "").strip()
        updated_words[index]["text"] = entity
        recoveries.append(
            EntityRecovery(
                segment_id=segment_id,
                word_id=updated_words[index].get("id"),
                raw_fragment=original_text,
                recovered_term=entity,
            )
        )
    return updated_words, recoveries


def recover_raw_payload_for_alignment(*, raw_payload: dict, manuscript_text: str | None) -> tuple[dict, list[EntityRecovery]]:
    updated_payload = dict(raw_payload)
    updated_segments: list[dict] = []
    entity_recoveries: list[EntityRecovery] = []

    for segment in raw_payload.get("segments") or []:
        updated_segment = dict(segment)
        words = segment.get("words") or []
        if words:
            recovered_words, segment_recoveries = _recover_words_from_manuscript(
                words=words,
                segment_id=segment.get("id"),
                manuscript_text=manuscript_text,
            )
            updated_segment["words"] = recovered_words
            updated_segment["text"] = "".join(_word_surface(word) for word in recovered_words).strip()
            entity_recoveries.extend(segment_recoveries)
        updated_segments.append(updated_segment)

    updated_payload["segments"] = updated_segments
    if updated_segments:
        updated_payload["text"] = "".join(str(segment.get("text") or "") for segment in updated_segments).strip()
    return updated_payload, entity_recoveries


def _merge_protected_units(words: list[dict], glossary: RunGlossary) -> list[_Unit]:
    surfaces = [_word_surface(word) for word in words]
    used = [False] * len(words)
    merged: list[_Unit] = []
    idx = 0

    protected_terms = sorted(glossary.terms, key=lambda item: len(item.term), reverse=True)
    while idx < len(words):
        if used[idx]:
            idx += 1
            continue

        match_unit: _Unit | None = None
        match_span = 1
        for entry in protected_terms:
            target = _normalize(entry.term)
            running = ""
            for end in range(idx, len(words)):
                running += _normalize(surfaces[end])
                if running == target:
                    text = "".join(surfaces[idx : end + 1])
                    match_unit = _Unit(text=text, start=float(words[idx]["start"]), end=float(words[end]["end"]))
                    match_span = end - idx + 1
                    break
                if not target.startswith(running):
                    break
            if match_unit is not None:
                break

        if match_unit is not None:
            for taken in range(idx, idx + match_span):
                used[taken] = True
            merged.append(match_unit)
            idx += match_span
            continue

        merged.append(_Unit(text=surfaces[idx], start=float(words[idx]["start"]), end=float(words[idx]["end"])))
        idx += 1

    return merged


def _compact_len(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def _is_micro_cue(cue: SubtitleCue) -> bool:
    duration = float(cue.end) - float(cue.start)
    compact_len = _compact_len(cue.text)
    if duration < _MICRO_CUE_SECONDS:
        return True
    if compact_len <= _MICRO_CUE_CHARS:
        return True
    return bool(_TAIL_FRAGMENT_RE.fullmatch(cue.text.strip()))


def collect_micro_cue_examples(cues: list[SubtitleCue], limit: int | None = 5) -> list[dict]:
    examples: list[dict] = []
    for cue in cues:
        if not _is_micro_cue(cue):
            continue
        examples.append(
            {
                "index": cue.index,
                "duration": round(float(cue.end) - float(cue.start), 3),
                "text": cue.text,
            }
        )
        if limit is not None and len(examples) >= limit:
            break
    return examples


def _merge_two_cues(left: SubtitleCue, right: SubtitleCue) -> SubtitleCue:
    return SubtitleCue(index=left.index, start=left.start, end=right.end, text=f"{left.text}{right.text}")


def _reindex_cues(cues: list[SubtitleCue]) -> list[SubtitleCue]:
    return [SubtitleCue(index=idx, start=cue.start, end=cue.end, text=cue.text) for idx, cue in enumerate(cues, start=1)]


def _merge_micro_cues(cues: list[SubtitleCue]) -> list[SubtitleCue]:
    merged = list(cues)
    if len(merged) <= 1:
        return _reindex_cues(merged)

    idx = 0
    while idx < len(merged):
        if len(merged) <= 1:
            break
        cue = merged[idx]
        if not _is_micro_cue(cue):
            idx += 1
            continue

        if idx > 0:
            merged[idx - 1] = _merge_two_cues(merged[idx - 1], cue)
            del merged[idx]
            idx = max(idx - 1, 0)
            continue

        merged[idx + 1] = SubtitleCue(
            index=merged[idx + 1].index,
            start=cue.start,
            end=merged[idx + 1].end,
            text=f"{cue.text}{merged[idx + 1].text}",
        )
        del merged[idx]

    return _reindex_cues(merged)


def build_script_pass_result(*, raw_payload: dict, glossary: RunGlossary, manuscript_text: str | None = None) -> SegmentationResult:
    cues: list[SubtitleCue] = []
    recovered_payload, entity_recoveries = recover_raw_payload_for_alignment(raw_payload=raw_payload, manuscript_text=manuscript_text)

    for segment in recovered_payload.get("segments") or []:
        segment_cues: list[SubtitleCue] = []
        words = segment.get("words") or []
        if not words:
            text = str(segment.get("text") or "").strip()
            if text:
                segment_cues.append(
                    SubtitleCue(
                        index=0,
                        start=float(segment.get("start") or 0.0),
                        end=float(segment.get("end") or 0.0),
                        text=text,
                    )
                )
            cues.extend(_merge_micro_cues(segment_cues))
            continue

        units = _merge_protected_units(words, glossary)
        current: list[_Unit] = []
        for unit in units:
            proposed = "".join(item.text for item in current + [unit])
            if current and _compact_len(proposed) > _SOFT_LIMIT:
                segment_cues.append(
                    SubtitleCue(
                        index=0,
                        start=current[0].start,
                        end=current[-1].end,
                        text="".join(item.text for item in current).strip(),
                    )
                )
                current = [unit]
                continue
            current.append(unit)
            if _STRONG_BREAK_RE.search(unit.text) and _compact_len("".join(item.text for item in current)) >= 8:
                segment_cues.append(
                    SubtitleCue(
                        index=0,
                        start=current[0].start,
                        end=current[-1].end,
                        text="".join(item.text for item in current).strip(),
                    )
                )
                current = []

        if current:
            segment_cues.append(
                SubtitleCue(
                    index=0,
                    start=current[0].start,
                    end=current[-1].end,
                    text="".join(item.text for item in current).strip(),
                )
            )

        cues.extend(_merge_micro_cues(segment_cues))

    return SegmentationResult(cues=_reindex_cues(cues), entity_recoveries=entity_recoveries)


def build_script_pass_srt(*, raw_payload: dict, glossary: RunGlossary, manuscript_text: str | None = None) -> list[SubtitleCue]:
    return build_script_pass_result(raw_payload=raw_payload, glossary=glossary, manuscript_text=manuscript_text).cues


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = max(int(round(float(seconds) * 1000)), 0)
    whole_seconds, milli = divmod(total_ms, 1000)
    minutes, sec = divmod(whole_seconds, 60)
    hours, minute = divmod(minutes, 60)
    return f"{hours:02d}:{minute:02d}:{sec:02d},{milli:03d}"


def cues_to_srt_text(cues: list[SubtitleCue]) -> str:
    blocks: list[str] = []
    for cue in cues:
        end = cue.end if cue.end > cue.start else cue.start + 0.12
        blocks.extend(
            [
                str(cue.index),
                f"{_format_srt_timestamp(cue.start)} --> {_format_srt_timestamp(end)}",
                cue.text,
                "",
            ]
        )
    return "\n".join(blocks)


def write_cues_to_srt(cues: list[SubtitleCue], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(cues_to_srt_text(cues), encoding="utf-8")
