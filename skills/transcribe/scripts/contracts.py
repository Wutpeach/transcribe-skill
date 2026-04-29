from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_SUBTITLE_PUNCTUATION_RE = re.compile(r"[，。！？、；：,.!?;:()（）\[\]{}<>《》【】“”‘’\"'`~…—-]")


@dataclass
class GlossaryEntry:
    term: str
    aliases: list[str] = field(default_factory=list)
    type: str = "term"
    source: str = "manuscript"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunGlossary:
    terms: list[GlossaryEntry] = field(default_factory=list)
    source: str = "run"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "transcribe.run_glossary.v1",
            "source": self.source,
            "terms": [term.to_dict() for term in self.terms],
        }


@dataclass
class SubtitleCue:
    index: int
    start: float
    end: float
    text: str


@dataclass
class EntityRecovery:
    segment_id: int | str | None
    word_id: int | str | None
    raw_fragment: str
    recovered_term: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SegmentationResult:
    cues: list[SubtitleCue] = field(default_factory=list)
    entity_recoveries: list[EntityRecovery] = field(default_factory=list)


@dataclass
class InputPreflight:
    audio_ok: bool
    manuscript_present: bool
    manuscript_length: int
    normalized_manuscript_length: int
    speaker_complexity_signals: dict[str, Any] = field(default_factory=dict)
    style_volatility_signals: dict[str, Any] = field(default_factory=dict)
    user_override: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModeDecision:
    mode: str
    confidence: float
    global_similarity: float
    local_similarity_samples: list[float] = field(default_factory=list)
    manuscript_completeness: float = 0.0
    signals: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    user_override: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProofreadEdit:
    kind: str
    source_text: str
    updated_text: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProofreadManuscript:
    source_text: str
    proofread_text: str
    edit_summary: str = ""
    material_edits: list[ProofreadEdit] = field(default_factory=list)
    entity_decisions: list[dict[str, Any]] = field(default_factory=list)
    proofread_confidence: float = 0.0
    draft_ready: bool = True
    drafting_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "transcribe.proofread_manuscript.v2",
            "source_text": self.source_text,
            "proofread_text": self.proofread_text,
            "edit_summary": self.edit_summary,
            "material_edits": [item.to_dict() for item in self.material_edits],
            "entity_decisions": self.entity_decisions,
            "proofread_confidence": self.proofread_confidence,
            "draft_ready": self.draft_ready,
            "drafting_warnings": self.drafting_warnings,
        }


@dataclass
class DraftStyleFlags:
    punctuation_free: bool = True
    delivery_plain_text: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DraftQualitySignals:
    semantic_integrity: str = "medium"
    glossary_safe: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RawSpanMapping:
    segment_ids: list[int | str] = field(default_factory=list)
    word_start_id: int | str | None = None
    word_end_id: int | str | None = None
    mapping_confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DraftLine:
    line_id: int
    text: str
    source_mode: str
    draft_notes: list[str] = field(default_factory=list)
    style_flags: DraftStyleFlags = field(default_factory=DraftStyleFlags)
    quality_signals: DraftQualitySignals = field(default_factory=DraftQualitySignals)
    raw_span_mapping: RawSpanMapping = field(default_factory=RawSpanMapping)

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "text": self.text,
            "source_mode": self.source_mode,
            "draft_notes": list(self.draft_notes),
            "style_flags": self.style_flags.to_dict(),
            "quality_signals": self.quality_signals.to_dict(),
            "raw_span_mapping": self.raw_span_mapping.to_dict(),
        }


@dataclass
class SubtitleDraft:
    lines: list[DraftLine] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "transcribe.subtitle_draft.v2",
            "lines": [line.to_dict() for line in self.lines],
        }


@dataclass
class AlignedSegment:
    line_id: int
    text: str
    start: float
    end: float
    raw_token_start_index: int
    raw_token_end_index: int
    split_points: list[dict[str, Any]] = field(default_factory=list)
    alignment_score: float = 0.0
    protected_entities: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AlignedSegmentsSummary:
    line_count: int
    mean_alignment_score: float
    low_confidence_count: int
    interpolated_boundary_count: int
    fallback_region_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AlignmentAudit:
    chosen_mode: str
    post_alignment_mode: str
    mean_alignment_score: float
    downgraded_regions: list[int] = field(default_factory=list)
    rebuild_regions: list[int] = field(default_factory=list)
    fallback_region_count: int = 0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentReviewBundle:
    run_dir: str
    step3_execution_mode: str
    step3_owner: str
    input_paths: dict[str, str]
    headline: dict[str, Any]
    priority_cases: list[dict[str, Any]] = field(default_factory=list)
    schema: str = "transcribe.agent_review_bundle.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "run_dir": self.run_dir,
            "step3_execution_mode": self.step3_execution_mode,
            "step3_owner": self.step3_owner,
            "input_paths": dict(self.input_paths),
            "headline": dict(self.headline),
            "priority_cases": list(self.priority_cases),
        }


@dataclass
class PipelineOutputs:
    run_dir: Path
    raw_json_path: Path
    run_glossary_path: Path
    script_pass_srt_path: Path
    report_json_path: Path
    agent_review_bundle_path: Path
    edited_srt_path: Path | None = None
    vendor_json_path: Path | None = None
    semantic_segments_path: Path | None = None
    final_delivery_audit_path: Path | None = None
    correction_log_path: Path | None = None
    input_preflight_path: Path | None = None
    mode_decision_path: Path | None = None
    proofread_manuscript_path: Path | None = None
    subtitle_draft_path: Path | None = None
    aligned_segments_path: Path | None = None
    alignment_audit_path: Path | None = None
    alert_tracking_path: Path | None = None


def _preview_text(text: str, limit: int = 24) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= limit:
        return clean
    return f"{clean[:limit]}…"


MAX_SUBTITLE_LINE_UNITS = 17



def subtitle_display_length(text: str) -> int:
    return len(re.sub(r"\s+", "", text).strip())



def strip_subtitle_punctuation(text: str) -> str:
    stripped = _SUBTITLE_PUNCTUATION_RE.sub("", text)
    stripped = re.sub(r"(?<=[\u4e00-\u9fff])(?=[A-Za-z0-9])", " ", stripped)
    stripped = re.sub(r"(?<=[A-Za-z0-9])(?=[\u4e00-\u9fff])", " ", stripped)
    stripped = re.sub(r"\s+", " ", stripped)
    return stripped.strip()


def count_text_punctuation_violations(text: str) -> int:
    return len(_SUBTITLE_PUNCTUATION_RE.findall(text))


def validate_subtitle_draft(artifact: SubtitleDraft) -> list[str]:
    reasons: list[str] = []
    for line in artifact.lines:
        preview = _preview_text(line.text)
        if count_text_punctuation_violations(line.text):
            reasons.append(f"subtitle_draft_line_{line.line_id}_not_punctuation_free[text={preview}]")
        if not line.style_flags.punctuation_free:
            reasons.append(f"subtitle_draft_line_{line.line_id}_style_flag_punctuation_free_false[text={preview}]")
    return reasons


def validate_aligned_segments_texts(segments: list[AlignedSegment]) -> list[str]:
    reasons: list[str] = []
    for segment in segments:
        if count_text_punctuation_violations(segment.text):
            reasons.append(
                f"aligned_segment_line_{segment.line_id}_not_punctuation_free[text={_preview_text(segment.text)}]"
            )
    return reasons


def validate_cues_punctuation_free(cues: list[SubtitleCue], *, stage: str) -> list[str]:
    reasons: list[str] = []
    for cue in cues:
        if count_text_punctuation_violations(cue.text):
            reasons.append(f"{stage}_cue_{cue.index}_not_punctuation_free[text={_preview_text(cue.text)}]")
    return reasons
