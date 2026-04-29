import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from contracts import (
    AgentReviewBundle,
    AlignedSegment,
    AlignedSegmentsSummary,
    AlignmentAudit,
    DraftLine,
    DraftQualitySignals,
    DraftStyleFlags,
    GlossaryEntry,
    InputPreflight,
    ModeDecision,
    PipelineOutputs,
    ProofreadEdit,
    ProofreadManuscript,
    RawSpanMapping,
    RunGlossary,
    SubtitleDraft,
    validate_subtitle_draft,
)


def test_input_preflight_to_dict_exposes_expected_fields():
    artifact = InputPreflight(
        audio_ok=True,
        manuscript_present=True,
        manuscript_length=12,
        normalized_manuscript_length=10,
        speaker_complexity_signals={"speaker_count_hint": 1},
        style_volatility_signals={"filler_density": 0.1},
        user_override="auto",
        warnings=["normalized whitespace"],
    )

    payload = artifact.to_dict()

    assert payload["audio_ok"] is True
    assert payload["manuscript_present"] is True
    assert payload["manuscript_length"] == 12
    assert payload["normalized_manuscript_length"] == 10
    assert payload["speaker_complexity_signals"] == {"speaker_count_hint": 1}
    assert payload["style_volatility_signals"] == {"filler_density": 0.1}
    assert payload["user_override"] == "auto"
    assert payload["warnings"] == ["normalized whitespace"]


def test_mode_decision_to_dict_exposes_expected_fields():
    artifact = ModeDecision(
        mode="manuscript-priority",
        confidence=0.91,
        global_similarity=0.94,
        local_similarity_samples=[0.9, 0.92],
        manuscript_completeness=0.98,
        signals={"single_speaker": True},
        reasons=["high similarity"],
        user_override=None,
    )

    payload = artifact.to_dict()

    assert payload["mode"] == "manuscript-priority"
    assert payload["confidence"] == 0.91
    assert payload["global_similarity"] == 0.94
    assert payload["local_similarity_samples"] == [0.9, 0.92]
    assert payload["manuscript_completeness"] == 0.98
    assert payload["signals"] == {"single_speaker": True}
    assert payload["reasons"] == ["high similarity"]
    assert payload["user_override"] is None


def test_proofread_manuscript_to_dict_exposes_expected_fields():
    artifact = ProofreadManuscript(
        source_text="原稿",
        proofread_text="修订稿",
        edit_summary="fixed typo",
        material_edits=[ProofreadEdit(kind="entity", source_text="ins", updated_text="埃安 S", reason="entity recovery")],
        entity_decisions=[{"raw": "ins", "final": "埃安 S"}],
        proofread_confidence=0.88,
        draft_ready=True,
        drafting_warnings=["bootstrap proofreading only"],
    )

    payload = artifact.to_dict()

    assert payload["schema"] == "transcribe.proofread_manuscript.v2"
    assert payload["source_text"] == "原稿"
    assert payload["proofread_text"] == "修订稿"
    assert payload["edit_summary"] == "fixed typo"
    assert payload["material_edits"][0]["kind"] == "entity"
    assert payload["material_edits"][0]["source_text"] == "ins"
    assert payload["material_edits"][0]["updated_text"] == "埃安 S"
    assert payload["material_edits"][0]["reason"] == "entity recovery"
    assert payload["entity_decisions"] == [{"raw": "ins", "final": "埃安 S"}]
    assert payload["proofread_confidence"] == 0.88
    assert payload["draft_ready"] is True
    assert payload["drafting_warnings"] == ["bootstrap proofreading only"]


def test_subtitle_draft_to_dict_exposes_expected_fields():
    artifact = SubtitleDraft(
        lines=[
            DraftLine(
                line_id=1,
                text="第一行",
                source_mode="manuscript-priority",
                draft_notes=["semantic split"],
                style_flags=DraftStyleFlags(punctuation_free=True, delivery_plain_text=True),
                quality_signals=DraftQualitySignals(semantic_integrity="high", glossary_safe=True),
                raw_span_mapping=RawSpanMapping(
                    segment_ids=[3, 4],
                    word_start_id=18,
                    word_end_id=29,
                    mapping_confidence=0.82,
                ),
            )
        ]
    )

    payload = artifact.to_dict()

    assert payload["schema"] == "transcribe.subtitle_draft.v2"
    assert payload["lines"][0]["line_id"] == 1
    assert payload["lines"][0]["text"] == "第一行"
    assert payload["lines"][0]["source_mode"] == "manuscript-priority"
    assert payload["lines"][0]["draft_notes"] == ["semantic split"]
    assert payload["lines"][0]["style_flags"] == {
        "punctuation_free": True,
        "delivery_plain_text": True,
    }
    assert payload["lines"][0]["quality_signals"] == {
        "semantic_integrity": "high",
        "glossary_safe": True,
    }
    assert payload["lines"][0]["raw_span_mapping"] == {
        "segment_ids": [3, 4],
        "word_start_id": 18,
        "word_end_id": 29,
        "mapping_confidence": 0.82,
    }


def test_validate_subtitle_draft_reports_punctuation_and_missing_style_flags():
    artifact = SubtitleDraft(
        lines=[
            DraftLine(
                line_id=1,
                text="第一行。",
                source_mode="manuscript-priority",
                draft_notes=["bootstrap draft"],
                style_flags=DraftStyleFlags(punctuation_free=False, delivery_plain_text=True),
            )
        ]
    )

    reasons = validate_subtitle_draft(artifact)

    assert reasons == [
        "subtitle_draft_line_1_not_punctuation_free[text=第一行。]",
        "subtitle_draft_line_1_style_flag_punctuation_free_false[text=第一行。]",
    ]


def test_aligned_segment_and_summary_to_dict_expose_expected_fields():
    segment = AlignedSegment(
        line_id=1,
        text="第一行",
        start=0.0,
        end=1.2,
        raw_token_start_index=0,
        raw_token_end_index=2,
        split_points=[{"token_index": 1, "ratio": 0.5}],
        alignment_score=0.93,
        protected_entities=["埃安 S"],
        warnings=["interpolated"],
    )
    summary = AlignedSegmentsSummary(
        line_count=1,
        mean_alignment_score=0.93,
        low_confidence_count=0,
        interpolated_boundary_count=1,
        fallback_region_count=0,
    )

    segment_payload = segment.to_dict()
    summary_payload = summary.to_dict()

    assert segment_payload["line_id"] == 1
    assert segment_payload["text"] == "第一行"
    assert segment_payload["raw_token_start_index"] == 0
    assert segment_payload["raw_token_end_index"] == 2
    assert segment_payload["split_points"] == [{"token_index": 1, "ratio": 0.5}]
    assert segment_payload["alignment_score"] == 0.93
    assert segment_payload["protected_entities"] == ["埃安 S"]
    assert segment_payload["warnings"] == ["interpolated"]

    assert summary_payload["line_count"] == 1
    assert summary_payload["mean_alignment_score"] == 0.93
    assert summary_payload["low_confidence_count"] == 0
    assert summary_payload["interpolated_boundary_count"] == 1
    assert summary_payload["fallback_region_count"] == 0


def test_alignment_audit_to_dict_exposes_expected_fields():
    artifact = AlignmentAudit(
        chosen_mode="manuscript-priority",
        post_alignment_mode="raw-priority",
        mean_alignment_score=0.74,
        downgraded_regions=[1, 2],
        rebuild_regions=[2],
        fallback_region_count=2,
        reasons=["mean score below threshold"],
    )

    payload = artifact.to_dict()

    assert payload["chosen_mode"] == "manuscript-priority"
    assert payload["post_alignment_mode"] == "raw-priority"
    assert payload["mean_alignment_score"] == 0.74
    assert payload["downgraded_regions"] == [1, 2]
    assert payload["rebuild_regions"] == [2]
    assert payload["fallback_region_count"] == 2
    assert payload["reasons"] == ["mean score below threshold"]



def test_pipeline_outputs_supports_hybrid_artifact_paths():
    artifact = PipelineOutputs(
        run_dir=Path("run"),
        raw_json_path=Path("run/raw.json"),
        run_glossary_path=Path("run/run_glossary.json"),
        script_pass_srt_path=Path("run/edited-script-pass.srt"),
        report_json_path=Path("run/report.json"),
        agent_review_bundle_path=Path("run/agent_review_bundle.json"),
        edited_srt_path=Path("run/edited.srt"),
        input_preflight_path=Path("run/input_preflight.json"),
        mode_decision_path=Path("run/mode_decision.json"),
        proofread_manuscript_path=Path("run/proofread_manuscript.json"),
        subtitle_draft_path=Path("run/subtitle_draft.json"),
        aligned_segments_path=Path("run/aligned_segments.json"),
        alignment_audit_path=Path("run/alignment_audit.json"),
        alert_tracking_path=Path("run/alert_tracking.json"),
    )

    assert artifact.agent_review_bundle_path == Path("run/agent_review_bundle.json")
    assert artifact.input_preflight_path == Path("run/input_preflight.json")
    assert artifact.mode_decision_path == Path("run/mode_decision.json")
    assert artifact.proofread_manuscript_path == Path("run/proofread_manuscript.json")
    assert artifact.subtitle_draft_path == Path("run/subtitle_draft.json")
    assert artifact.aligned_segments_path == Path("run/aligned_segments.json")
    assert artifact.alignment_audit_path == Path("run/alignment_audit.json")
    assert artifact.alert_tracking_path == Path("run/alert_tracking.json")


def test_pipeline_outputs_keep_final_delivery_paths_optional_until_agent_step3_completes():
    artifact = PipelineOutputs(
        run_dir=Path("run"),
        raw_json_path=Path("run/raw.json"),
        run_glossary_path=Path("run/run_glossary.json"),
        script_pass_srt_path=Path("run/edited-script-pass.srt"),
        report_json_path=Path("run/report.json"),
        agent_review_bundle_path=Path("run/agent_review_bundle.json"),
    )

    assert artifact.agent_review_bundle_path == Path("run/agent_review_bundle.json")
    assert artifact.edited_srt_path is None
    assert artifact.final_delivery_audit_path is None
    assert artifact.correction_log_path is None
    assert artifact.input_preflight_path is None
    assert artifact.mode_decision_path is None
    assert artifact.proofread_manuscript_path is None
    assert artifact.subtitle_draft_path is None
    assert artifact.aligned_segments_path is None
    assert artifact.alignment_audit_path is None
    assert artifact.alert_tracking_path is None


def test_agent_review_bundle_to_dict_exposes_expected_fields():
    artifact = AgentReviewBundle(
        run_dir="run",
        step3_execution_mode="agent-session",
        step3_owner="interactive-agent",
        input_paths={
            "script_pass_srt": "edited-script-pass.srt",
            "report_json": "report.json",
        },
        headline={
            "chosen_mode": "manuscript-priority",
            "step2a_alert_count": 2,
        },
        priority_cases=[
            {"cue_index": 44, "reason": "punctuation violation", "text": "假如有 A-B-C-D 几个生产流程"}
        ],
    )

    payload = artifact.to_dict()

    assert payload["schema"] == "transcribe.agent_review_bundle.v1"
    assert payload["run_dir"] == "run"
    assert payload["step3_execution_mode"] == "agent-session"
    assert payload["step3_owner"] == "interactive-agent"
    assert payload["input_paths"]["script_pass_srt"] == "edited-script-pass.srt"
    assert payload["headline"]["chosen_mode"] == "manuscript-priority"
    assert payload["priority_cases"][0]["cue_index"] == 44


def test_existing_glossary_contracts_still_work():
    glossary = RunGlossary(terms=[GlossaryEntry(term="FunASR")], source="manuscript")

    payload = glossary.to_dict()

    assert payload["schema"] == "transcribe.run_glossary.v1"
    assert payload["source"] == "manuscript"
    assert payload["terms"][0]["term"] == "FunASR"
