import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from auxiliary_config import AgentRuntimeConfig
from contracts import (
    AlignedSegment,
    AlignedSegmentsSummary,
    AlignmentAudit,
    DraftLine,
    PipelineOutputs,
    ProofreadManuscript,
    SubtitleCue,
    SubtitleDraft,
    validate_subtitle_draft,
)
from funasr_api import FunASRTranscribeResult
from finalizer import FinalizerResult
from pipeline import (
    PipelineConfig,
    build_parser,
    main,
    resolve_pipeline_config_from_args,
    run_minimal_pipeline,
    run_replay_from_raw,
    write_step3_review_artifacts,
)
from drafting import Step2ADraftingResult


class DummyFunASRResult(FunASRTranscribeResult):
    pass


def _step2a_fixture_result(*, text_lines: list[str], source_mode: str, provider: str = "deepseek_direct_aux") -> Step2ADraftingResult:
    joined = "\n".join(text_lines)
    return Step2ADraftingResult(
        proofread=ProofreadManuscript(
            source_text=joined,
            proofread_text=joined,
            edit_summary="fixture proofreading",
            proofread_confidence=0.95,
            draft_ready=True,
            drafting_warnings=[],
        ),
        draft=SubtitleDraft(
            lines=[DraftLine(line_id=index, text=text, source_mode=source_mode) for index, text in enumerate(text_lines, start=1)]
        ),
        drafting_mode="llm-primary",
        draft_model_provider=provider,
        draft_model_name="deepseek-v4-flash",
        draft_fallback_used=False,
        draft_fallback_reason=None,
        draft_fallback_code=None,
        draft_attempt_count=1,
        text_authority="llm",
        manual_review_required=False,
        alert_reasons=[],
    )


def _agent_runtime_fixture() -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        provider_name="openclaw",
        base_url="http://127.0.0.1:3000/v1",
        api_key_env="CURRENT_LIVE_AGENT_API_KEY",
        api_key="sk-openclaw",
        api_mode="chat_completions",
    )


def test_build_parser_accepts_replay_from_raw_without_audio_or_api_key():
    args = build_parser().parse_args([
        "--output-dir",
        "/tmp/run",
        "--replay-from-raw",
        "/tmp/raw.json",
    ])

    assert args.audio is None
    assert args.replay_from_raw == "/tmp/raw.json"
    assert args.funasr_api_key is None


def test_resolve_pipeline_config_from_args_reads_skill_local_funasr_toml(tmp_path):
    skill_dir = tmp_path / "skill"
    config_dir = skill_dir / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "funasr.toml").write_text(
        """
[funasr]
model = "fun-asr-plus"
base_http_api_url = "https://dashscope.example/api/v1"
language_hints = ["zh", "en"]
key_env = "TRANSCRIBE_FUNASR_KEY"
""".strip(),
        encoding="utf-8",
    )
    (config_dir / "funasr.local.toml").write_text(
        """
[funasr]
api_key = "sk-skill-local"
""".strip(),
        encoding="utf-8",
    )

    args = build_parser().parse_args([
        str(tmp_path / "sample.wav"),
        "--output-dir",
        str(tmp_path / "run"),
    ])

    config = resolve_pipeline_config_from_args(args, skill_dir=skill_dir)

    assert config.funasr_api_key == "sk-skill-local"
    assert config.funasr_model == "fun-asr-plus"
    assert config.funasr_base_http_api_url == "https://dashscope.example/api/v1"
    assert config.funasr_language_hints == ["zh", "en"]


def test_resolve_pipeline_config_from_args_prefers_cli_key_over_skill_local_files(tmp_path):
    skill_dir = tmp_path / "skill"
    config_dir = skill_dir / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "funasr.toml").write_text(
        """
[funasr]
key_env = "TRANSCRIBE_FUNASR_KEY"
""".strip(),
        encoding="utf-8",
    )
    (config_dir / "funasr.local.toml").write_text(
        """
[funasr]
api_key = "sk-skill-local"
""".strip(),
        encoding="utf-8",
    )
    (skill_dir / ".env.local").write_text("TRANSCRIBE_FUNASR_KEY=sk-env-local\n", encoding="utf-8")

    args = build_parser().parse_args([
        str(tmp_path / "sample.wav"),
        "--output-dir",
        str(tmp_path / "run"),
        "--funasr-api-key",
        "sk-cli",
    ])

    config = resolve_pipeline_config_from_args(args, skill_dir=skill_dir)

    assert config.funasr_api_key == "sk-cli"


def test_main_accepts_skill_local_funasr_key_when_cli_flag_is_missing(tmp_path):
    skill_dir = tmp_path / "skill"
    config_dir = skill_dir / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "funasr.toml").write_text(
        """
[funasr]
key_env = "TRANSCRIBE_FUNASR_KEY"
""".strip(),
        encoding="utf-8",
    )
    (skill_dir / ".env.local").write_text("TRANSCRIBE_FUNASR_KEY=sk-env-local\n", encoding="utf-8")

    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"RIFFfake")
    run_dir = tmp_path / "run"
    captured = {}

    def fake_run_minimal_pipeline(*, audio_path, run_dir, manuscript_text, config):
        captured["config"] = config
        return PipelineOutputs(
            run_dir=run_dir,
            raw_json_path=run_dir / "raw.json",
            run_glossary_path=run_dir / "run_glossary.json",
            script_pass_srt_path=run_dir / "edited-script-pass.srt",
            report_json_path=run_dir / "report.json",
            agent_review_bundle_path=run_dir / "agent_review_bundle.json",
        )

    with patch("pipeline.run_minimal_pipeline", side_effect=fake_run_minimal_pipeline):
        exit_code = main([
            str(audio_path),
            "--output-dir",
            str(run_dir),
        ], skill_dir=skill_dir)

    assert exit_code == 0
    assert captured["config"].funasr_api_key == "sk-env-local"


def test_run_replay_from_raw_rebuilds_step2_handoff_artifacts_from_existing_raw_json(tmp_path):
    raw_source_path = tmp_path / "existing-raw.json"
    raw_source_path.write_text(
        json.dumps(
            {
                "schema": "transcribe.raw.v3",
                "text": "他造过的s7 也讲到hps",
                "segments": [
                    {
                        "id": 1,
                        "start": 0.0,
                        "end": 2.0,
                        "text": "他造过的s7 也讲到hps",
                        "words": [
                            {"id": 1, "start": 0.0, "end": 0.8, "text": "他造过的s7", "punctuation": ""},
                            {"id": 2, "start": 0.8, "end": 2.0, "text": "也讲到hps", "punctuation": ""},
                        ],
                    }
                ],
                "backend": "funasr-api",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    step2a_result = _step2a_fixture_result(
        text_lines=["他造过的 S7", "也讲到 HPS"],
        source_mode="manuscript-priority",
    )

    with patch("pipeline.build_step2a_artifacts", return_value=step2a_result):
        outputs = run_replay_from_raw(
            raw_json_path=raw_source_path,
            run_dir=tmp_path / "replay-run",
            manuscript_text="他造过的 S7 也讲到 HPS",
            mode_override="manuscript-priority",
        )

    assert outputs.raw_json_path.exists()
    assert outputs.raw_json_path.parent == outputs.run_dir
    assert outputs.raw_json_path.read_text(encoding="utf-8") == raw_source_path.read_text(encoding="utf-8")
    assert outputs.vendor_json_path is None
    assert outputs.input_preflight_path.exists()
    assert outputs.mode_decision_path.exists()
    assert outputs.proofread_manuscript_path.exists()
    assert outputs.subtitle_draft_path.exists()
    assert outputs.aligned_segments_path.exists()
    assert outputs.alignment_audit_path.exists()
    assert outputs.run_glossary_path.exists()
    assert outputs.script_pass_srt_path.exists()
    assert outputs.agent_review_bundle_path.exists()
    assert outputs.report_json_path.exists()

    report = json.loads(outputs.report_json_path.read_text(encoding="utf-8"))
    assert report["step3_status"] in {"awaiting_agent_review", "blocked"}


def test_run_replay_from_raw_uses_injected_agent_runtime_for_current_live_agent_fallback(tmp_path):
    raw_source_path = tmp_path / "existing-raw.json"
    raw_source_path.write_text(
        json.dumps(
            {
                "schema": "transcribe.raw.v3",
                "text": "他造过的s7 也讲到hps",
                "segments": [
                    {
                        "id": 1,
                        "start": 0.0,
                        "end": 2.0,
                        "text": "他造过的s7 也讲到hps",
                        "words": [
                            {"id": 1, "start": 0.0, "end": 0.8, "text": "他造过的s7", "punctuation": ""},
                            {"id": 2, "start": 0.8, "end": 2.0, "text": "也讲到hps", "punctuation": ""},
                        ],
                    }
                ],
                "backend": "funasr-api",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    outputs = run_replay_from_raw(
        raw_json_path=raw_source_path,
        run_dir=tmp_path / "replay-run-runtime",
        manuscript_text="他造过的 S7 也讲到 HPS",
        mode_override="manuscript-priority",
        agent_runtime=_agent_runtime_fixture(),
    )

    report = json.loads(outputs.report_json_path.read_text(encoding="utf-8"))
    assert report["drafting_mode"] in {"llm-primary", "llm-primary-with-alerts", "agent-fallback"}
    assert report["step3_status"] == "awaiting_agent_review"


def test_run_minimal_pipeline_writes_required_artifacts(tmp_path):
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"RIFFfake")
    raw_payload = {
        "schema": "transcribe.raw.v3",
        "text": "他造过的s7，也讲到hps。",
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 2.0,
                "text": "他造过的s7，也讲到hps。",
                "words": [
                    {"id": 1, "start": 0.0, "end": 0.7, "text": "他造过的s7", "punctuation": "，"},
                    {"id": 2, "start": 0.7, "end": 2.0, "text": "也讲到hps", "punctuation": "。"},
                ],
            }
        ],
        "backend": "funasr-api",
        "vendor": "bailian.fun-asr",
    }

    def fake_run_funasr_api_for_transcribe(*, local_audio_path, run_dir, config):
        vendor_json_path = run_dir / "bailian_raw.json"
        raw_json_path = run_dir / "raw.json"
        vendor_json_path.write_text(json.dumps({"vendor": True}, ensure_ascii=False), encoding="utf-8")
        raw_json_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return DummyFunASRResult(
            raw_json_path=raw_json_path,
            vendor_json_path=vendor_json_path,
            raw_srt_path=None,
            upload_file_id="file-123",
            uploaded_file_url="https://uploaded.example/audio.wav",
            task_id="task-123",
            result_url="https://result.example/output.json",
        )

    step2a_result = _step2a_fixture_result(
        text_lines=["他造过的 S7", "也讲到 HPS"],
        source_mode="manuscript-priority",
    )

    with patch("pipeline.run_funasr_api_for_transcribe", side_effect=fake_run_funasr_api_for_transcribe), patch(
        "pipeline.build_step2a_artifacts",
        return_value=step2a_result,
    ):
        outputs = run_minimal_pipeline(
            audio_path=audio_path,
            run_dir=tmp_path / "run",
            manuscript_text="他造过的 S7，也讲到 HPS。",
            config=PipelineConfig(funasr_api_key="sk-test"),
        )

    assert outputs.raw_json_path.exists()
    assert outputs.input_preflight_path.exists()
    assert outputs.mode_decision_path.exists()
    assert outputs.proofread_manuscript_path.exists()
    assert outputs.subtitle_draft_path.exists()
    assert outputs.aligned_segments_path.exists()
    assert outputs.alignment_audit_path.exists()
    assert outputs.run_glossary_path.exists()
    assert outputs.script_pass_srt_path.exists()
    assert outputs.agent_review_bundle_path.exists()
    assert outputs.edited_srt_path is None
    assert outputs.final_delivery_audit_path is None
    assert outputs.correction_log_path is None
    assert outputs.report_json_path.exists()
    assert outputs.alert_tracking_path.exists()

    mode_decision = json.loads(outputs.mode_decision_path.read_text(encoding="utf-8"))
    assert mode_decision["mode"] in {"manuscript-priority", "raw-priority"}

    report = json.loads(outputs.report_json_path.read_text(encoding="utf-8"))
    agent_review_bundle = json.loads(outputs.agent_review_bundle_path.read_text(encoding="utf-8"))
    alert_tracking = json.loads(outputs.alert_tracking_path.read_text(encoding="utf-8"))
    subtitle_draft = json.loads(outputs.subtitle_draft_path.read_text(encoding="utf-8"))
    aligned_segments = json.loads(outputs.aligned_segments_path.read_text(encoding="utf-8"))
    script_pass_srt = outputs.script_pass_srt_path.read_text(encoding="utf-8")
    assert report["backend"] == "funasr-api"
    assert report["chosen_mode"] == "manuscript-priority"
    assert report["post_alignment_mode"] == "manuscript-priority"
    assert report["route_decision_reasons"]
    assert report["alignment_mean_score"] >= 0.8
    assert 0.0 <= report["alignment_success_rate"] <= 1.0
    assert report["low_confidence_alignment_count"] == 0
    assert report["interpolated_boundary_count"] >= 0
    assert report["fallback_region_count"] == 0
    assert report["downgrade_count"] == 0
    assert report["step3_owner"] == "interactive-agent"
    assert report["step3_execution_mode"] == "agent-session"
    assert report["final_delivery_status"] in {"awaiting_agent_review", "blocked"}
    assert report["script_text_override_used"] is False
    assert report["glossary_term_count"] == 2
    assert report["short_cue_count"] == 0
    assert report["micro_cue_examples"] == []
    assert report["suspicious_glossary_terms"] == []
    assert report["entity_recovery_count"] == 0
    assert report["entity_recovery_examples"] == []
    assert report["finalizer_change_count"] == 0
    assert report["drafting_mode"] in {"llm-primary", "llm-primary-with-alerts", "manual-review-required"}
    assert report["subtitle_punctuation_violation_count"] == 0
    assert report["semantic_cut_suspect_count"] == 0
    assert report["alert_tracking_summary"]["alert_case_count"] >= 0
    assert report["alert_tracking_summary"]["manual_review_case_count"] >= 0
    assert agent_review_bundle["schema"] == "transcribe.agent_review_bundle.v1"
    assert agent_review_bundle["step3_execution_mode"] == "agent-session"
    assert agent_review_bundle["input_paths"]["script_pass_srt"] == "edited-script-pass.srt"
    assert alert_tracking["schema"] == "transcribe.alert_tracking.v1"
    if report["drafting_mode"] == "manual-review-required":
        assert report["step3_status"] == "blocked"
        assert report["step3_text_authority"] == "none"
        assert report["manual_review_required"] is True
        assert report["draft_model_provider"] is None
        assert report["draft_model_name"] is None
        assert report["draft_fallback_used"] is False
        assert report["draft_fallback_reason"]
        assert report["draft_fallback_code"]
    else:
        assert report["step3_status"] == "awaiting_agent_review"
        assert report["step3_text_authority"] == "interactive-agent"
        assert report["draft_model_provider"]
        assert report["draft_model_name"]
        assert report["draft_fallback_used"] is False
        assert report["draft_fallback_reason"] is None
        assert report["draft_fallback_code"] is None
        assert report["draft_attempt_count"] >= 1
    assert subtitle_draft["schema"] == "transcribe.subtitle_draft.v2"
    assert "S7" in " ".join(line["text"] for line in subtitle_draft["lines"])
    assert "HPS" in " ".join(line["text"] for line in subtitle_draft["lines"])
    assert aligned_segments["schema"] == "transcribe.aligned_segments.v2"
    assert "。" not in script_pass_srt
    assert "，" not in script_pass_srt


def test_write_step3_review_artifacts_updates_report_with_finalized_metrics(tmp_path):
    run_dir = tmp_path / "run-step3"
    run_dir.mkdir()
    report_path = run_dir / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema": "transcribe.report.v3",
                "step3_status": "awaiting_agent_review",
                "step3_text_authority": "interactive-agent",
                "step3_alert_reasons": [],
                "manual_review_required": False,
                "final_delivery_status": "awaiting_agent_review",
                "final_delivery_risk": "pending",
                "final_delivery_reasons": [],
                "finalizer_change_count": 0,
                "finalizer_change_breakdown": {
                    "alias_replacements": {"count": 0, "examples": []},
                    "spacing_normalizations": {"count": 0, "examples": []},
                    "punctuation_normalizations": {"count": 0, "examples": []},
                    "duplicate_collapses": {"count": 0, "examples": []},
                    "delivery_resegmentations": {"count": 0, "examples": []},
                },
                "finalizer_applied_regions": "",
                "finalizer_mode": "agent-session-pending",
                "finalizer_model_provider": None,
                "finalizer_model_name": None,
                "finalizer_fallback_used": False,
                "finalizer_fallback_reason": None,
                "finalizer_fallback_code": None,
                "segmentation_stats": {"script_pass_cue_count": 2, "edited_cue_count": None},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    finalizer_result = FinalizerResult(
        cues=[
            SubtitleCue(index=1, start=0.0, end=0.8, text="前半句"),
            SubtitleCue(index=2, start=0.8, end=1.6, text="后半句"),
            SubtitleCue(index=3, start=1.6, end=2.4, text="结尾"),
        ],
        change_breakdown={
            "alias_replacements": {"count": 1, "examples": ["S7"]},
            "spacing_normalizations": {"count": 0, "examples": []},
            "punctuation_normalizations": {"count": 0, "examples": []},
            "duplicate_collapses": {"count": 0, "examples": []},
            "delivery_resegmentations": {"count": 0, "examples": []},
        },
        applied_regions=[1],
        applied_region_summary="1",
        correction_log={
            "schema": "transcribe.correction_log.v1",
            "cue_changes": [{"cue_index": 1}, {"cue_index": 2}],
            "cue_diffs": [],
            "cue_splits": [
                {
                    "original_line_id": 1,
                    "new_line_ids": [1, 2],
                    "split_type": "token_anchored",
                    "split_confidence": "high",
                    "start_alignment_delta_ms": 0,
                    "risk_level": "low",
                    "used_fallback": False,
                    "fallback_steps": [],
                    "split_point_token_index": 4,
                }
            ],
            "split_statistics": {
                "total_splits": 1,
                "token_anchored_count": 1,
                "partial_token_anchored_count": 0,
                "proportional_fallback_count": 0,
                "low_confidence_split_count": 0,
            },
            "applied_region_summary": "1",
        },
        delivery_audit={
            "schema": "transcribe.final_delivery_audit.v1",
            "status": "ready",
            "risk": "low",
            "checks": {"cue_count": 3, "resegment_count": 1},
            "resegment_source": ["agent_step3_manual_review"],
            "cue_splitting": {
                "split_count": 1,
                "high_risk_count": 0,
                "max_length": 4,
                "mean_alignment_delta_ms": 0.0,
            },
            "reasons": [],
            "cue_diffs": [],
        },
        split_operations=[
            {
                "original_line_id": 1,
                "new_line_ids": [1, 2],
                "split_type": "token_anchored",
                "split_confidence": "high",
                "start_alignment_delta_ms": 0,
                "risk_level": "low",
                "used_fallback": False,
                "fallback_steps": [],
                "split_point_token_index": 4,
            }
        ],
        validation_fallback_reasons=[],
        finalizer_mode="llm-primary",
        finalizer_model_provider="deepseek_direct_aux",
        finalizer_model_name="deepseek-v4-flash",
        finalizer_fallback_used=False,
        finalizer_fallback_reason=None,
        finalizer_fallback_code=None,
        text_authority="llm",
        manual_review_required=False,
        alert_reasons=[],
    )

    write_step3_review_artifacts(run_dir=run_dir, finalizer_result=finalizer_result)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    edited_srt = (run_dir / "edited.srt").read_text(encoding="utf-8")
    correction_log = json.loads((run_dir / "correction_log.json").read_text(encoding="utf-8"))
    final_delivery_audit = json.loads((run_dir / "final_delivery_audit.json").read_text(encoding="utf-8"))
    assert (run_dir / "edited.srt").exists()
    assert (run_dir / "correction_log.json").exists()
    assert (run_dir / "final_delivery_audit.json").exists()
    assert "00:00:00,000 --> 00:00:00,800" in edited_srt
    assert "00:00:00,800 --> 00:00:01,600" in edited_srt
    assert correction_log["delivery_timing_smoothing"] == {
        "applied": True,
        "first_cue_snapped": False,
        "gaps_filled": 0,
    }
    assert final_delivery_audit["timing_smoothed_count"] == 0
    assert final_delivery_audit["first_cue_start_snapped"] is False
    assert report["step3_status"] == "adjudicated_ready"
    assert report["step3_text_authority"] == "llm"
    assert report["manual_review_required"] is False
    assert report["final_delivery_status"] == "ready"
    assert report["final_delivery_risk"] == "low"
    assert report["finalizer_change_count"] == 2
    assert report["finalizer_applied_regions"] == "1"
    assert report["finalizer_mode"] == "llm-primary"
    assert report["finalizer_model_provider"] == "deepseek_direct_aux"
    assert report["finalizer_model_name"] == "deepseek-v4-flash"
    assert report["segmentation_stats"]["edited_cue_count"] == 3
    assert report["cue_splitting"]["split_count"] == 1
    assert report["cue_splitting"]["high_risk_count"] == 0
    assert report["split_count"] == 1
    assert report["edited_cue_count"] == 3
    assert report["delivery_timing_smoothing"] == {
        "count": 0,
        "first_cue_snapped": False,
    }
    assert report["timing_smoothed_count"] == 0


def test_write_step3_review_artifacts_applies_delivery_timing_smoothing_before_writing_srt(tmp_path):
    run_dir = tmp_path / "run-step3-smoothed"
    run_dir.mkdir()
    report_path = run_dir / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema": "transcribe.report.v3",
                "step3_status": "awaiting_agent_review",
                "step3_text_authority": "interactive-agent",
                "step3_alert_reasons": [],
                "manual_review_required": False,
                "final_delivery_status": "awaiting_agent_review",
                "final_delivery_risk": "pending",
                "final_delivery_reasons": [],
                "finalizer_change_count": 0,
                "finalizer_change_breakdown": {
                    "alias_replacements": {"count": 0, "examples": []},
                    "spacing_normalizations": {"count": 0, "examples": []},
                    "punctuation_normalizations": {"count": 0, "examples": []},
                    "duplicate_collapses": {"count": 0, "examples": []},
                    "delivery_resegmentations": {"count": 0, "examples": []},
                },
                "finalizer_applied_regions": "",
                "finalizer_mode": "agent-session-pending",
                "finalizer_model_provider": None,
                "finalizer_model_name": None,
                "finalizer_fallback_used": False,
                "finalizer_fallback_reason": None,
                "finalizer_fallback_code": None,
                "segmentation_stats": {"script_pass_cue_count": 2, "edited_cue_count": None},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    finalizer_result = FinalizerResult(
        cues=[
            SubtitleCue(index=1, start=0.4, end=0.9, text="前句"),
            SubtitleCue(index=2, start=1.1, end=1.8, text="后句"),
        ],
        change_breakdown={
            "alias_replacements": {"count": 0, "examples": []},
            "spacing_normalizations": {"count": 0, "examples": []},
            "punctuation_normalizations": {"count": 0, "examples": []},
            "duplicate_collapses": {"count": 0, "examples": []},
            "delivery_resegmentations": {"count": 0, "examples": []},
        },
        applied_regions=[],
        applied_region_summary="",
        correction_log={
            "schema": "transcribe.correction_log.v1",
            "cue_changes": [],
            "cue_diffs": [],
            "cue_splits": [],
            "split_statistics": {
                "total_splits": 0,
                "token_anchored_count": 0,
                "partial_token_anchored_count": 0,
                "proportional_fallback_count": 0,
                "low_confidence_split_count": 0,
            },
            "applied_region_summary": "",
        },
        delivery_audit={
            "schema": "transcribe.final_delivery_audit.v1",
            "status": "ready",
            "risk": "low",
            "checks": {"cue_count": 2, "resegment_count": 0},
            "resegment_source": [],
            "cue_splitting": {
                "split_count": 0,
                "high_risk_count": 0,
                "max_length": 2,
                "mean_alignment_delta_ms": 0,
            },
            "reasons": [],
            "cue_diffs": [],
        },
        split_operations=[],
        validation_fallback_reasons=[],
        finalizer_mode="rules-primary",
        finalizer_model_provider=None,
        finalizer_model_name=None,
        finalizer_fallback_used=False,
        finalizer_fallback_reason=None,
        finalizer_fallback_code=None,
        text_authority="inherited",
        manual_review_required=False,
        alert_reasons=[],
    )

    write_step3_review_artifacts(run_dir=run_dir, finalizer_result=finalizer_result)

    edited_srt = (run_dir / "edited.srt").read_text(encoding="utf-8")
    correction_log = json.loads((run_dir / "correction_log.json").read_text(encoding="utf-8"))
    final_delivery_audit = json.loads((run_dir / "final_delivery_audit.json").read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert "00:00:00,000 --> 00:00:01,100" in edited_srt
    assert "00:00:01,100 --> 00:00:01,800" in edited_srt
    assert correction_log["delivery_timing_smoothing"] == {
        "applied": True,
        "first_cue_snapped": True,
        "gaps_filled": 1,
    }
    assert final_delivery_audit["timing_smoothed_count"] == 1
    assert final_delivery_audit["first_cue_start_snapped"] is True
    assert report["delivery_timing_smoothing"] == {
        "count": 1,
        "first_cue_snapped": True,
    }
    assert report["timing_smoothed_count"] == 1



def test_write_step3_review_artifacts_marks_report_needs_review_when_delivery_risk_remains(tmp_path):
    run_dir = tmp_path / "run-step3-needs-review"
    run_dir.mkdir()
    report_path = run_dir / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema": "transcribe.report.v3",
                "step3_status": "awaiting_agent_review",
                "step3_text_authority": "interactive-agent",
                "step3_alert_reasons": [],
                "manual_review_required": False,
                "final_delivery_status": "awaiting_agent_review",
                "final_delivery_risk": "pending",
                "final_delivery_reasons": [],
                "finalizer_change_count": 0,
                "finalizer_change_breakdown": {
                    "alias_replacements": {"count": 0, "examples": []},
                    "spacing_normalizations": {"count": 0, "examples": []},
                    "punctuation_normalizations": {"count": 0, "examples": []},
                    "duplicate_collapses": {"count": 0, "examples": []},
                    "delivery_resegmentations": {"count": 0, "examples": []},
                },
                "finalizer_applied_regions": "",
                "finalizer_mode": "agent-session-pending",
                "finalizer_model_provider": None,
                "finalizer_model_name": None,
                "finalizer_fallback_used": False,
                "finalizer_fallback_reason": None,
                "finalizer_fallback_code": None,
                "segmentation_stats": {"script_pass_cue_count": 1, "edited_cue_count": None},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    finalizer_result = FinalizerResult(
        cues=[SubtitleCue(index=1, start=0.0, end=1.0, text="原句")],
        change_breakdown={
            "alias_replacements": {"count": 0, "examples": []},
            "spacing_normalizations": {"count": 0, "examples": []},
            "punctuation_normalizations": {"count": 0, "examples": []},
            "duplicate_collapses": {"count": 0, "examples": []},
            "delivery_resegmentations": {"count": 0, "examples": []},
        },
        applied_regions=[],
        applied_region_summary="",
        correction_log={
            "schema": "transcribe.correction_log.v1",
            "cue_changes": [],
            "cue_diffs": [],
            "cue_splits": [],
            "split_statistics": {
                "total_splits": 0,
                "token_anchored_count": 0,
                "partial_token_anchored_count": 0,
                "proportional_fallback_count": 0,
                "low_confidence_split_count": 0,
            },
            "applied_region_summary": "",
        },
        delivery_audit={
            "schema": "transcribe.final_delivery_audit.v1",
            "status": "needs_review",
            "risk": "high",
            "checks": {"cue_count": 1, "resegment_count": 0},
            "resegment_source": [],
            "cue_splitting": {
                "split_count": 0,
                "high_risk_count": 0,
                "max_length": 2,
                "mean_alignment_delta_ms": 0,
            },
            "reasons": ["punctuation_violation"],
            "cue_diffs": [],
        },
        split_operations=[],
        validation_fallback_reasons=["aligned_segments_mismatch"],
        finalizer_mode="manual-review-required",
        finalizer_model_provider=None,
        finalizer_model_name=None,
        finalizer_fallback_used=False,
        finalizer_fallback_reason="aux timeout",
        finalizer_fallback_code="auxiliary_request_failed",
        text_authority="llm",
        manual_review_required=True,
        alert_reasons=["aux timeout"],
    )

    write_step3_review_artifacts(run_dir=run_dir, finalizer_result=finalizer_result)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["step3_status"] == "adjudicated_needs_review"
    assert report["manual_review_required"] is True
    assert report["final_delivery_status"] == "needs_review"
    assert report["final_delivery_risk"] == "high"
    assert report["step3_alert_reasons"] == ["aligned_segments_mismatch", "aux timeout", "punctuation_violation"]
    assert report["finalizer_fallback_reason"] == "aux timeout"
    assert report["finalizer_fallback_code"] == "auxiliary_request_failed"


def test_write_step3_review_artifacts_rejects_non_pending_report_state(tmp_path):
    run_dir = tmp_path / "run-step3-invalid-state"
    run_dir.mkdir()
    report_path = run_dir / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema": "transcribe.report.v3",
                "step3_status": "blocked",
                "step3_text_authority": "none",
                "step3_alert_reasons": ["step3_blocked"],
                "manual_review_required": True,
                "final_delivery_status": "blocked",
                "final_delivery_risk": "high",
                "final_delivery_reasons": ["step3_blocked"],
                "finalizer_change_count": 0,
                "finalizer_change_breakdown": {
                    "alias_replacements": {"count": 0, "examples": []},
                    "spacing_normalizations": {"count": 0, "examples": []},
                    "punctuation_normalizations": {"count": 0, "examples": []},
                    "duplicate_collapses": {"count": 0, "examples": []},
                    "delivery_resegmentations": {"count": 0, "examples": []},
                },
                "finalizer_applied_regions": "",
                "finalizer_mode": "blocked",
                "finalizer_model_provider": None,
                "finalizer_model_name": None,
                "finalizer_fallback_used": False,
                "finalizer_fallback_reason": None,
                "finalizer_fallback_code": None,
                "segmentation_stats": {"script_pass_cue_count": 1, "edited_cue_count": None},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    finalizer_result = FinalizerResult(
        cues=[SubtitleCue(index=1, start=0.0, end=1.0, text="原句")],
        change_breakdown={
            "alias_replacements": {"count": 0, "examples": []},
            "spacing_normalizations": {"count": 0, "examples": []},
            "punctuation_normalizations": {"count": 0, "examples": []},
            "duplicate_collapses": {"count": 0, "examples": []},
            "delivery_resegmentations": {"count": 0, "examples": []},
        },
        applied_regions=[],
        applied_region_summary="",
        correction_log={
            "schema": "transcribe.correction_log.v1",
            "cue_changes": [],
            "cue_diffs": [],
            "cue_splits": [],
            "split_statistics": {
                "total_splits": 0,
                "token_anchored_count": 0,
                "partial_token_anchored_count": 0,
                "proportional_fallback_count": 0,
                "low_confidence_split_count": 0,
            },
            "applied_region_summary": "",
        },
        delivery_audit={
            "schema": "transcribe.final_delivery_audit.v1",
            "status": "ready",
            "risk": "low",
            "checks": {"cue_count": 1, "resegment_count": 0},
            "resegment_source": [],
            "cue_splitting": {
                "split_count": 0,
                "high_risk_count": 0,
                "max_length": 2,
                "mean_alignment_delta_ms": 0,
            },
            "reasons": [],
            "cue_diffs": [],
        },
        split_operations=[],
        validation_fallback_reasons=[],
        finalizer_mode="rules-primary",
        finalizer_model_provider=None,
        finalizer_model_name=None,
        finalizer_fallback_used=False,
        finalizer_fallback_reason=None,
        finalizer_fallback_code=None,
        text_authority="inherited",
        manual_review_required=False,
        alert_reasons=[],
    )

    with pytest.raises(ValueError, match="awaiting_agent_review"):
        write_step3_review_artifacts(run_dir=run_dir, finalizer_result=finalizer_result)


def test_write_step3_review_artifacts_rejects_invalid_step3_artifact_schema(tmp_path):
    run_dir = tmp_path / "run-step3-invalid-artifact"
    run_dir.mkdir()
    report_path = run_dir / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema": "transcribe.report.v3",
                "step3_status": "awaiting_agent_review",
                "step3_text_authority": "interactive-agent",
                "step3_alert_reasons": [],
                "manual_review_required": False,
                "final_delivery_status": "awaiting_agent_review",
                "final_delivery_risk": "pending",
                "final_delivery_reasons": [],
                "finalizer_change_count": 0,
                "finalizer_change_breakdown": {
                    "alias_replacements": {"count": 0, "examples": []},
                    "spacing_normalizations": {"count": 0, "examples": []},
                    "punctuation_normalizations": {"count": 0, "examples": []},
                    "duplicate_collapses": {"count": 0, "examples": []},
                    "delivery_resegmentations": {"count": 0, "examples": []},
                },
                "finalizer_applied_regions": "",
                "finalizer_mode": "agent-session-pending",
                "finalizer_model_provider": None,
                "finalizer_model_name": None,
                "finalizer_fallback_used": False,
                "finalizer_fallback_reason": None,
                "finalizer_fallback_code": None,
                "segmentation_stats": {"script_pass_cue_count": 1, "edited_cue_count": None},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    finalizer_result = FinalizerResult(
        cues=[SubtitleCue(index=1, start=0.0, end=1.0, text="原句")],
        change_breakdown={
            "alias_replacements": {"count": 0, "examples": []},
            "spacing_normalizations": {"count": 0, "examples": []},
            "punctuation_normalizations": {"count": 0, "examples": []},
            "duplicate_collapses": {"count": 0, "examples": []},
            "delivery_resegmentations": {"count": 0, "examples": []},
        },
        applied_regions=[],
        applied_region_summary="",
        correction_log={
            "schema": "transcribe.correction_log.v1",
            "cue_changes": [],
            "cue_diffs": [],
            "cue_splits": [],
            "split_statistics": {
                "total_splits": 0,
                "token_anchored_count": 0,
                "partial_token_anchored_count": 0,
                "proportional_fallback_count": 0,
                "low_confidence_split_count": 0,
            },
            "applied_region_summary": "",
        },
        delivery_audit={
            "schema": "broken.audit.schema",
            "status": "ready",
            "risk": "low",
            "checks": {"cue_count": 1, "resegment_count": 0},
            "resegment_source": [],
            "cue_splitting": {
                "split_count": 0,
                "high_risk_count": 0,
                "max_length": 2,
                "mean_alignment_delta_ms": 0,
            },
            "reasons": [],
            "cue_diffs": [],
        },
        split_operations=[],
        validation_fallback_reasons=[],
        finalizer_mode="rules-primary",
        finalizer_model_provider=None,
        finalizer_model_name=None,
        finalizer_fallback_used=False,
        finalizer_fallback_reason=None,
        finalizer_fallback_code=None,
        text_authority="inherited",
        manual_review_required=False,
        alert_reasons=[],
    )

    with pytest.raises(ValueError, match="final_delivery_audit"):
        write_step3_review_artifacts(run_dir=run_dir, finalizer_result=finalizer_result)


def test_run_minimal_pipeline_uses_llm_step2a_metadata_when_auxiliary_draft_succeeds(tmp_path):
    audio_path = tmp_path / "sample-llm.wav"
    audio_path.write_bytes(b"RIFFfake")
    raw_payload = {
        "schema": "transcribe.raw.v3",
        "text": "今天我们来聊funasr。还看看埃安s。",
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 1.0,
                "text": "今天我们来聊funasr。",
                "words": [
                    {"id": 1, "start": 0.0, "end": 1.0, "text": "今天我们来聊funasr", "punctuation": "。"},
                ],
            },
            {
                "id": 2,
                "start": 1.0,
                "end": 2.0,
                "text": "还看看埃安s。",
                "words": [
                    {"id": 2, "start": 1.0, "end": 2.0, "text": "还看看埃安s", "punctuation": "。"},
                ],
            },
        ],
        "backend": "funasr-api",
        "vendor": "bailian.fun-asr",
    }

    def fake_run_funasr_api_for_transcribe(*, local_audio_path, run_dir, config):
        vendor_json_path = run_dir / "bailian_raw.json"
        raw_json_path = run_dir / "raw.json"
        vendor_json_path.write_text(json.dumps({"vendor": True}, ensure_ascii=False), encoding="utf-8")
        raw_json_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return DummyFunASRResult(
            raw_json_path=raw_json_path,
            vendor_json_path=vendor_json_path,
            raw_srt_path=None,
            upload_file_id="file-123",
            uploaded_file_url="https://uploaded.example/audio.wav",
            task_id="task-123",
            result_url="https://result.example/output.json",
        )

    step2a_result = Step2ADraftingResult(
        proofread=ProofreadManuscript(
            source_text="今天我们来聊 FunASR。\n还看看埃安 S。",
            proofread_text="今天我们来聊 FunASR\n还看看埃安 S",
            edit_summary="llm proofreading",
            proofread_confidence=0.97,
            draft_ready=True,
            drafting_warnings=[],
        ),
        draft=SubtitleDraft(
            lines=[
                DraftLine(line_id=1, text="今天我们来聊 FunASR", source_mode="manuscript-priority", draft_notes=["llm semantic draft"]),
                DraftLine(line_id=2, text="还看看埃安 S", source_mode="manuscript-priority", draft_notes=["llm semantic draft"]),
            ]
        ),
        drafting_mode="llm-primary",
        draft_model_provider="deepseek_direct_aux",
        draft_model_name="deepseek-v4-flash",
        draft_fallback_used=False,
        draft_fallback_reason=None,
        draft_fallback_code=None,
        draft_attempt_count=1,
    )
    assert validate_subtitle_draft(step2a_result.draft) == []

    with patch("pipeline.run_funasr_api_for_transcribe", side_effect=fake_run_funasr_api_for_transcribe), patch(
        "pipeline.build_step2a_artifacts",
        return_value=step2a_result,
    ):
        outputs = run_minimal_pipeline(
            audio_path=audio_path,
            run_dir=tmp_path / "run-llm",
            manuscript_text="今天我们来聊 FunASR。\n还看看埃安 S。",
            config=PipelineConfig(funasr_api_key="sk-test"),
        )

    report = json.loads(outputs.report_json_path.read_text(encoding="utf-8"))
    assert report["drafting_mode"] == "llm-primary"
    assert report["draft_model_provider"] == "deepseek_direct_aux"
    assert report["draft_model_name"] == "deepseek-v4-flash"
    assert report["draft_fallback_used"] is False
    assert report["draft_fallback_reason"] is None
    assert report["draft_fallback_code"] is None
    assert report["draft_attempt_count"] == 1



def test_run_minimal_pipeline_reports_total_short_cue_count_even_when_examples_are_capped(tmp_path):
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"RIFFfake")
    raw_payload = {
        "schema": "transcribe.raw.v3",
        "text": "啊。啊。啊。啊。啊。啊。",
        "segments": [
            {
                "id": idx,
                "start": float(idx),
                "end": float(idx) + 0.2,
                "text": "啊。",
                "words": [
                    {"id": 1, "start": float(idx), "end": float(idx) + 0.2, "text": "啊", "punctuation": "。"},
                ],
            }
            for idx in range(6)
        ],
        "backend": "funasr-api",
        "vendor": "bailian.fun-asr",
    }

    def fake_run_funasr_api_for_transcribe(*, local_audio_path, run_dir, config):
        vendor_json_path = run_dir / "bailian_raw.json"
        raw_json_path = run_dir / "raw.json"
        vendor_json_path.write_text(json.dumps({"vendor": True}, ensure_ascii=False), encoding="utf-8")
        raw_json_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return DummyFunASRResult(
            raw_json_path=raw_json_path,
            vendor_json_path=vendor_json_path,
            raw_srt_path=None,
            upload_file_id="file-123",
            uploaded_file_url="https://uploaded.example/audio.wav",
            task_id="task-123",
            result_url="https://result.example/output.json",
        )

    step2a_result = Step2ADraftingResult(
        proofread=ProofreadManuscript(
            source_text="啊\n啊\n啊\n啊\n啊\n啊",
            proofread_text="啊\n啊\n啊\n啊\n啊\n啊",
            edit_summary="fixture proofreading",
            proofread_confidence=1.0,
            draft_ready=True,
            drafting_warnings=[],
        ),
        draft=SubtitleDraft(lines=[DraftLine(line_id=idx, text="啊", source_mode="raw-priority") for idx in range(1, 7)]),
        drafting_mode="manual-review-required",
        draft_model_provider=None,
        draft_model_name=None,
        draft_fallback_used=False,
        draft_fallback_reason="fixture",
        draft_fallback_code="fixture",
        draft_attempt_count=0,
        text_authority="llm",
        manual_review_required=False,
        alert_reasons=[],
    )
    aligned_segments = [
        AlignedSegment(
            line_id=idx,
            text="啊",
            start=float(idx - 1),
            end=float(idx - 1) + 0.2,
            raw_token_start_index=idx - 1,
            raw_token_end_index=idx - 1,
            alignment_score=1.0,
        )
        for idx in range(1, 7)
    ]
    aligned_summary = AlignedSegmentsSummary(
        line_count=6,
        mean_alignment_score=1.0,
        low_confidence_count=0,
        interpolated_boundary_count=0,
        fallback_region_count=0,
    )
    alignment_audit = AlignmentAudit(
        chosen_mode="raw-priority",
        post_alignment_mode="raw-priority",
        mean_alignment_score=1.0,
        downgraded_regions=[],
        rebuild_regions=[],
        fallback_region_count=0,
        reasons=[],
    )
    finalizer_result = FinalizerResult(
        cues=[SubtitleCue(index=idx, start=float(idx - 1), end=float(idx - 1) + 0.2, text="啊") for idx in range(1, 7)],
        change_breakdown={
            "alias_replacements": {"count": 0, "examples": []},
            "spacing_normalizations": {"count": 0, "examples": []},
            "punctuation_normalizations": {"count": 0, "examples": []},
            "duplicate_collapses": {"count": 0, "examples": []},
            "delivery_resegmentations": {"count": 0, "examples": []},
        },
        applied_regions=[],
        applied_region_summary="",
        correction_log={"schema": "transcribe.correction_log.v1", "cue_changes": [], "cue_diffs": [], "applied_region_summary": ""},
        delivery_audit={"schema": "transcribe.final_delivery_audit.v1", "status": "ready", "risk": "low", "checks": {}, "reasons": [], "cue_diffs": []},
        validation_fallback_reasons=[],
        finalizer_mode="manual-review-required",
        finalizer_model_provider=None,
        finalizer_model_name=None,
        finalizer_fallback_used=False,
        finalizer_fallback_reason="fixture",
        finalizer_fallback_code="fixture",
        text_authority="llm",
        manual_review_required=False,
        alert_reasons=[],
    )

    with patch("pipeline.run_funasr_api_for_transcribe", side_effect=fake_run_funasr_api_for_transcribe), patch(
        "pipeline.build_step2a_artifacts",
        return_value=step2a_result,
    ), patch(
        "pipeline.align_draft_to_raw_tokens",
        return_value=(aligned_segments, aligned_summary),
    ), patch(
        "pipeline.build_alignment_audit",
        return_value=alignment_audit,
    ), patch(
        "pipeline.finalize_cues",
        return_value=finalizer_result,
    ):
        outputs = run_minimal_pipeline(
            audio_path=audio_path,
            run_dir=tmp_path / "run-micro",
            manuscript_text=None,
            config=PipelineConfig(funasr_api_key="sk-test"),
        )

    report = json.loads(outputs.report_json_path.read_text(encoding="utf-8"))
    assert report["short_cue_count"] == 6
    assert len(report["micro_cue_examples"]) == 5


def test_run_minimal_pipeline_reports_manuscript_backed_entity_recoveries(tmp_path):
    audio_path = tmp_path / "sample-entity.wav"
    audio_path.write_bytes(b"RIFFfake")
    raw_payload = {
        "schema": "transcribe.raw.v3",
        "text": "广汽ins、iny现在卖得都挺好。",
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 3.0,
                "text": "广汽ins、iny现在卖得都挺好。",
                "words": [
                    {"id": 1, "start": 0.0, "end": 0.5, "text": "广汽", "punctuation": ""},
                    {"id": 2, "start": 0.5, "end": 1.0, "text": "ins", "punctuation": "、"},
                    {"id": 3, "start": 1.0, "end": 1.5, "text": "iny", "punctuation": ""},
                    {"id": 4, "start": 1.5, "end": 3.0, "text": "现在卖得都挺好", "punctuation": "。"},
                ],
            }
        ],
        "backend": "funasr-api",
        "vendor": "bailian.fun-asr",
    }

    def fake_run_funasr_api_for_transcribe(*, local_audio_path, run_dir, config):
        vendor_json_path = run_dir / "bailian_raw.json"
        raw_json_path = run_dir / "raw.json"
        vendor_json_path.write_text(json.dumps({"vendor": True}, ensure_ascii=False), encoding="utf-8")
        raw_json_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return DummyFunASRResult(
            raw_json_path=raw_json_path,
            vendor_json_path=vendor_json_path,
            raw_srt_path=None,
            upload_file_id="file-123",
            uploaded_file_url="https://uploaded.example/audio.wav",
            task_id="task-123",
            result_url="https://result.example/output.json",
        )

    step2a_result = _step2a_fixture_result(
        text_lines=["广汽埃安 S", "埃安 Y现在卖得都挺好"],
        source_mode="manuscript-priority",
    )

    with patch("pipeline.run_funasr_api_for_transcribe", side_effect=fake_run_funasr_api_for_transcribe), patch(
        "pipeline.build_step2a_artifacts",
        return_value=step2a_result,
    ):
        outputs = run_minimal_pipeline(
            audio_path=audio_path,
            run_dir=tmp_path / "run-entity",
            manuscript_text="广汽埃安 S、埃安 Y现在卖得都挺好。",
            config=PipelineConfig(funasr_api_key="sk-test"),
        )

    script_pass_srt = outputs.script_pass_srt_path.read_text(encoding="utf-8")
    report = json.loads(outputs.report_json_path.read_text(encoding="utf-8"))
    compact_srt = script_pass_srt.replace(" ", "")
    assert "广汽埃安S" in compact_srt
    assert "埃安Y" in compact_srt
    assert "现在卖得都挺好" in compact_srt
    assert report["entity_recovery_count"] == 2
    assert report["route_decision_reasons"]
    assert report["downgrade_count"] >= 0
    assert [item["recovered_term"] for item in report["entity_recovery_examples"]] == ["埃安 S", "埃安 Y"]
    assert [item["raw_fragment"] for item in report["entity_recovery_examples"]] == ["ins", "iny"]



def test_run_minimal_pipeline_preserves_step2_micro_cues_in_script_pass_and_marks_agent_handoff(tmp_path):
    audio_path = tmp_path / "sample-step3-micro.wav"
    audio_path.write_bytes(b"RIFFfake")
    raw_payload = {
        "schema": "transcribe.raw.v3",
        "text": "我们先看整体啊嗯再看细节。",
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 2.4,
                "text": "我们先看整体啊嗯再看细节。",
                "words": [
                    {"id": 1, "start": 0.0, "end": 2.4, "text": "我们先看整体啊嗯再看细节", "punctuation": "。"},
                ],
            }
        ],
        "backend": "funasr-api",
        "vendor": "bailian.fun-asr",
    }

    def fake_run_funasr_api_for_transcribe(*, local_audio_path, run_dir, config):
        vendor_json_path = run_dir / "bailian_raw.json"
        raw_json_path = run_dir / "raw.json"
        vendor_json_path.write_text(json.dumps({"vendor": True}, ensure_ascii=False), encoding="utf-8")
        raw_json_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return DummyFunASRResult(
            raw_json_path=raw_json_path,
            vendor_json_path=vendor_json_path,
            raw_srt_path=None,
            upload_file_id="file-123",
            uploaded_file_url="https://uploaded.example/audio.wav",
            task_id="task-123",
            result_url="https://result.example/output.json",
        )

    step2a_result = Step2ADraftingResult(
        proofread=ProofreadManuscript(
            source_text="我们先看整体\n啊\n嗯\n再看细节",
            proofread_text="我们先看整体\n啊\n嗯\n再看细节",
            edit_summary="llm proofreading",
            proofread_confidence=0.88,
            draft_ready=True,
            drafting_warnings=[],
        ),
        draft=SubtitleDraft(
            lines=[
                DraftLine(line_id=1, text="我们先看整体", source_mode="manuscript-priority"),
                DraftLine(line_id=2, text="啊", source_mode="manuscript-priority"),
                DraftLine(line_id=3, text="嗯", source_mode="manuscript-priority"),
                DraftLine(line_id=4, text="再看细节", source_mode="manuscript-priority"),
            ]
        ),
        drafting_mode="llm-primary",
        draft_model_provider="deepseek_direct_aux",
        draft_model_name="deepseek-v4-flash",
        draft_fallback_used=False,
        draft_fallback_reason=None,
        draft_fallback_code=None,
        draft_attempt_count=1,
        text_authority="llm",
        manual_review_required=False,
        alert_reasons=[],
    )
    aligned_segments = [
        AlignedSegment(
            line_id=1,
            text="我们先看整体",
            start=0.0,
            end=1.0,
            raw_token_start_index=0,
            raw_token_end_index=0,
            alignment_score=0.95,
        ),
        AlignedSegment(
            line_id=2,
            text="啊",
            start=1.0,
            end=1.2,
            raw_token_start_index=1,
            raw_token_end_index=1,
            alignment_score=0.95,
            warnings=["tail micro cue"],
        ),
        AlignedSegment(
            line_id=3,
            text="嗯",
            start=1.2,
            end=1.4,
            raw_token_start_index=2,
            raw_token_end_index=2,
            alignment_score=0.95,
            warnings=["tail micro cue"],
        ),
        AlignedSegment(
            line_id=4,
            text="再看细节",
            start=1.4,
            end=2.4,
            raw_token_start_index=3,
            raw_token_end_index=3,
            alignment_score=0.95,
        ),
    ]
    aligned_summary = AlignedSegmentsSummary(
        line_count=4,
        mean_alignment_score=0.95,
        low_confidence_count=0,
        interpolated_boundary_count=0,
        fallback_region_count=2,
    )
    alignment_audit = AlignmentAudit(
        chosen_mode="manuscript-priority",
        post_alignment_mode="manuscript-priority",
        mean_alignment_score=0.95,
        downgraded_regions=[],
        rebuild_regions=[],
        fallback_region_count=2,
        reasons=[],
    )

    finalizer_result = FinalizerResult(
        cues=[
            SubtitleCue(index=1, start=0.0, end=1.0, text="我们先看整体"),
            SubtitleCue(index=2, start=1.0, end=1.2, text="啊"),
            SubtitleCue(index=3, start=1.2, end=1.4, text="嗯"),
            SubtitleCue(index=4, start=1.4, end=2.4, text="再看细节"),
        ],
        change_breakdown={
            "alias_replacements": {"count": 0, "examples": []},
            "spacing_normalizations": {"count": 0, "examples": []},
            "punctuation_normalizations": {"count": 0, "examples": []},
            "duplicate_collapses": {"count": 0, "examples": []},
            "delivery_resegmentations": {"count": 0, "examples": []},
        },
        applied_regions=[],
        applied_region_summary="",
        correction_log={"schema": "transcribe.correction_log.v1", "cue_changes": [], "cue_diffs": [], "applied_region_summary": ""},
        delivery_audit={
            "schema": "transcribe.final_delivery_audit.v1",
            "status": "ready",
            "risk": "low",
            "checks": {"timing_monotonic": True, "empty_text_count": 0, "cue_count": 4, "punctuation_violation_count": 0, "micro_cue_count": 2, "resegment_count": 0},
            "resegment_source": [],
            "reasons": [],
            "cue_diffs": [],
        },
        validation_fallback_reasons=[],
        finalizer_mode="llm-primary",
        finalizer_model_provider="deepseek_direct_aux",
        finalizer_model_name="deepseek-v4-flash",
        finalizer_fallback_used=False,
        finalizer_fallback_reason=None,
        finalizer_fallback_code=None,
        text_authority="llm",
        manual_review_required=False,
        alert_reasons=[],
    )

    with patch("pipeline.run_funasr_api_for_transcribe", side_effect=fake_run_funasr_api_for_transcribe), patch(
        "pipeline.build_step2a_artifacts",
        return_value=step2a_result,
    ), patch(
        "pipeline.align_draft_to_raw_tokens",
        return_value=(aligned_segments, aligned_summary),
    ), patch(
        "pipeline.build_alignment_audit",
        return_value=alignment_audit,
    ), patch(
        "pipeline.finalize_cues",
        return_value=finalizer_result,
    ):
        outputs = run_minimal_pipeline(
            audio_path=audio_path,
            run_dir=tmp_path / "run-step3-micro",
            manuscript_text="我们先看整体\n啊\n嗯\n再看细节",
            config=PipelineConfig(funasr_api_key="sk-test"),
        )

    report = json.loads(outputs.report_json_path.read_text(encoding="utf-8"))
    script_pass_srt = outputs.script_pass_srt_path.read_text(encoding="utf-8")

    assert report["finalizer_change_breakdown"]["delivery_resegmentations"]["count"] == 0
    assert report["finalizer_change_breakdown"]["delivery_resegmentations"]["examples"] == []
    assert report["finalizer_applied_regions"] == ""
    assert report["step3_status"] == "awaiting_agent_review"
    assert report["step3_text_authority"] == "interactive-agent"
    assert outputs.final_delivery_audit_path is None
    assert outputs.edited_srt_path is None
    assert "我们先看整体" in script_pass_srt
    assert "\n啊\n" in script_pass_srt
    assert "\n嗯\n" in script_pass_srt



def test_run_minimal_pipeline_reports_agent_handoff_metadata_from_step2_outputs(tmp_path):
    audio_path = tmp_path / "sample-report.wav"
    audio_path.write_bytes(b"RIFFfake")
    raw_payload = {
        "schema": "transcribe.raw.v3",
        "text": "他造过的s7，也讲到hps。",
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 2.0,
                "text": "他造过的s7，也讲到hps。",
                "words": [
                    {"id": 1, "start": 0.0, "end": 0.7, "text": "他造过的s7", "punctuation": "，"},
                    {"id": 2, "start": 0.7, "end": 2.0, "text": "也讲到hps", "punctuation": "。"},
                ],
            }
        ],
        "backend": "funasr-api",
        "vendor": "bailian.fun-asr",
    }

    def fake_run_funasr_api_for_transcribe(*, local_audio_path, run_dir, config):
        vendor_json_path = run_dir / "bailian_raw.json"
        raw_json_path = run_dir / "raw.json"
        vendor_json_path.write_text(json.dumps({"vendor": True}, ensure_ascii=False), encoding="utf-8")
        raw_json_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return DummyFunASRResult(
            raw_json_path=raw_json_path,
            vendor_json_path=vendor_json_path,
            raw_srt_path=None,
            upload_file_id="file-123",
            uploaded_file_url="https://uploaded.example/audio.wav",
            task_id="task-123",
            result_url="https://result.example/output.json",
        )

    finalizer_result = FinalizerResult(
        cues=[
            SubtitleCue(index=1, start=0.0, end=2.0, text="他造过的 S7 也讲到 HPS"),
        ],
        change_breakdown={
            "alias_replacements": {"count": 1, "examples": ["s7 -> S7"]},
            "spacing_normalizations": {"count": 1, "examples": ["hps -> HPS"]},
            "punctuation_normalizations": {"count": 1, "examples": ["他造过的 S7，也讲到 HPS。 -> 他造过的 S7 也讲到 HPS"]},
            "duplicate_collapses": {"count": 0, "examples": []},
            "delivery_resegmentations": {"count": 0, "examples": []},
        },
        applied_regions=[1, 2, 3],
        applied_region_summary="1-3",
        correction_log={"schema": "transcribe.correction_log.v1", "cue_changes": [], "applied_region_summary": "1-3"},
        delivery_audit={
            "schema": "transcribe.final_delivery_audit.v1",
            "status": "ready_with_fallback",
            "risk": "medium",
            "checks": {"timing_monotonic": True, "empty_text_count": 0, "cue_count": 1, "punctuation_violation_count": 0},
            "reasons": ["aligned_segments_mismatch"],
        },
        validation_fallback_reasons=["aligned_segments_mismatch"],
        finalizer_mode="llm-primary",
        finalizer_model_provider="deepseek_direct_aux",
        finalizer_model_name="deepseek-v4-flash",
        finalizer_fallback_used=False,
        finalizer_fallback_reason=None,
        finalizer_fallback_code=None,
    )

    step2a_result = _step2a_fixture_result(
        text_lines=["他造过的 S7", "也讲到 HPS"],
        source_mode="manuscript-priority",
    )

    with patch("pipeline.run_funasr_api_for_transcribe", side_effect=fake_run_funasr_api_for_transcribe), patch(
        "pipeline.build_step2a_artifacts",
        return_value=step2a_result,
    ), patch(
        "pipeline.finalize_cues",
        return_value=finalizer_result,
    ):
        outputs = run_minimal_pipeline(
            audio_path=audio_path,
            run_dir=tmp_path / "run-report",
            manuscript_text="他造过的 S7，也讲到 HPS。",
            config=PipelineConfig(funasr_api_key="sk-test"),
        )

    report = json.loads(outputs.report_json_path.read_text(encoding="utf-8"))
    assert outputs.correction_log_path is None
    assert outputs.final_delivery_audit_path is None
    assert outputs.edited_srt_path is None
    assert report["finalizer_change_breakdown"]["alias_replacements"]["count"] == 0
    assert report["finalizer_change_breakdown"]["spacing_normalizations"]["examples"] == []
    assert report["final_delivery_risk"] == "pending"
    assert report["final_delivery_reasons"] == []
    assert report["finalizer_applied_regions"] == ""
    assert report["final_delivery_status"] == "awaiting_agent_review"
    assert report["finalizer_mode"] == "agent-session-pending"
    assert report["finalizer_model_provider"] is None
    assert report["finalizer_model_name"] is None
    assert report["finalizer_fallback_used"] is False
    assert report["finalizer_fallback_reason"] is None
    assert report["finalizer_fallback_code"] is None
    assert report["step3_status"] == "awaiting_agent_review"
    assert report["step3_text_authority"] == "interactive-agent"


def test_run_minimal_pipeline_routes_dirty_manuscript_to_raw_priority(tmp_path):
    audio_path = tmp_path / "sample-dirty.wav"
    audio_path.write_bytes(b"RIFFfake")
    raw_payload = {
        "schema": "transcribe.raw.v3",
        "text": "今天临时闲聊一点别的内容，顺手讲两个完全无关的话题。",
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 1.2,
                "text": "今天临时闲聊一点别的内容。",
                "words": [
                    {"id": 1, "start": 0.0, "end": 0.6, "text": "今天临时闲聊一点别的内容", "punctuation": "。"},
                ],
            },
            {
                "id": 2,
                "start": 1.2,
                "end": 2.6,
                "text": "顺手讲两个完全无关的话题。",
                "words": [
                    {"id": 2, "start": 1.2, "end": 2.6, "text": "顺手讲两个完全无关的话题", "punctuation": "。"},
                ],
            },
        ],
        "backend": "funasr-api",
        "vendor": "bailian.fun-asr",
    }

    def fake_run_funasr_api_for_transcribe(*, local_audio_path, run_dir, config):
        vendor_json_path = run_dir / "bailian_raw.json"
        raw_json_path = run_dir / "raw.json"
        vendor_json_path.write_text(json.dumps({"vendor": True}, ensure_ascii=False), encoding="utf-8")
        raw_json_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return DummyFunASRResult(
            raw_json_path=raw_json_path,
            vendor_json_path=vendor_json_path,
            raw_srt_path=None,
            upload_file_id="file-123",
            uploaded_file_url="https://uploaded.example/audio.wav",
            task_id="task-123",
            result_url="https://result.example/output.json",
        )

    step2a_result = _step2a_fixture_result(
        text_lines=["今天临时闲聊一点别的内容", "顺手讲两个完全无关的话题"],
        source_mode="raw-priority",
    )

    with patch("pipeline.run_funasr_api_for_transcribe", side_effect=fake_run_funasr_api_for_transcribe), patch(
        "pipeline.build_step2a_artifacts",
        return_value=step2a_result,
    ):
        outputs = run_minimal_pipeline(
            audio_path=audio_path,
            run_dir=tmp_path / "run-dirty",
            manuscript_text="这是后补提纲，和真实音频内容差异很大。",
            config=PipelineConfig(funasr_api_key="sk-test"),
        )

    report = json.loads(outputs.report_json_path.read_text(encoding="utf-8"))
    assert report["chosen_mode"] == "raw-priority"
    assert report["post_alignment_mode"] == "raw-priority"
    assert report["route_decision_reasons"]



def test_run_minimal_pipeline_does_not_call_raw_text_rebuild_in_mainline(tmp_path):
    audio_path = tmp_path / "sample-no-rebuild.wav"
    audio_path.write_bytes(b"RIFFfake")
    raw_payload = {
        "schema": "transcribe.raw.v3",
        "text": "先看整体 再看 HPS",
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 2.0,
                "text": "先看整体 再看 HPS",
                "words": [
                    {"id": 1, "start": 0.0, "end": 1.0, "text": "先看整体", "punctuation": ""},
                    {"id": 2, "start": 1.0, "end": 2.0, "text": "再看 HPS", "punctuation": ""},
                ],
            }
        ],
        "backend": "funasr-api",
        "vendor": "bailian.fun-asr",
    }

    def fake_run_funasr_api_for_transcribe(*, local_audio_path, run_dir, config):
        vendor_json_path = run_dir / "bailian_raw.json"
        raw_json_path = run_dir / "raw.json"
        vendor_json_path.write_text(json.dumps({"vendor": True}, ensure_ascii=False), encoding="utf-8")
        raw_json_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return DummyFunASRResult(
            raw_json_path=raw_json_path,
            vendor_json_path=vendor_json_path,
            raw_srt_path=None,
            upload_file_id="file-123",
            uploaded_file_url="https://uploaded.example/audio.wav",
            task_id="task-123",
            result_url="https://result.example/output.json",
        )

    step2a_result = Step2ADraftingResult(
        proofread=ProofreadManuscript(
            source_text="先看整体\n再看 HPS",
            proofread_text="先看整体\n再看 HPS",
            edit_summary="llm proofreading",
            proofread_confidence=0.95,
            draft_ready=True,
            drafting_warnings=[],
        ),
        draft=SubtitleDraft(
            lines=[
                DraftLine(line_id=1, text="先看整体", source_mode="manuscript-priority"),
                DraftLine(line_id=2, text="再看 HPS", source_mode="manuscript-priority"),
            ]
        ),
        drafting_mode="llm-primary",
        draft_model_provider="deepseek_direct_aux",
        draft_model_name="deepseek-v4-flash",
        draft_fallback_used=False,
        draft_fallback_reason=None,
        draft_fallback_code=None,
        draft_attempt_count=1,
    )
    aligned_segments = [
        AlignedSegment(
            line_id=1,
            text="先看整体",
            start=0.0,
            end=1.0,
            raw_token_start_index=0,
            raw_token_end_index=0,
            alignment_score=0.92,
        ),
        AlignedSegment(
            line_id=2,
            text="再看 HPS",
            start=1.0,
            end=2.0,
            raw_token_start_index=1,
            raw_token_end_index=1,
            alignment_score=0.7,
            warnings=["low alignment confidence"],
        ),
    ]
    aligned_summary = AlignedSegmentsSummary(
        line_count=2,
        mean_alignment_score=0.81,
        low_confidence_count=1,
        interpolated_boundary_count=0,
        fallback_region_count=1,
    )
    alignment_audit = AlignmentAudit(
        chosen_mode="manuscript-priority",
        post_alignment_mode="raw-priority",
        mean_alignment_score=0.81,
        downgraded_regions=[2],
        rebuild_regions=[2],
        fallback_region_count=1,
        reasons=["low-confidence ratio exceeds downgrade threshold"],
    )
    finalizer_result = FinalizerResult(
        cues=[
            SubtitleCue(index=1, start=0.0, end=1.0, text="先看整体"),
            SubtitleCue(index=2, start=1.0, end=2.0, text="再看 HPS"),
        ],
        change_breakdown={
            "alias_replacements": {"count": 0, "examples": []},
            "spacing_normalizations": {"count": 0, "examples": []},
            "punctuation_normalizations": {"count": 0, "examples": []},
            "duplicate_collapses": {"count": 0, "examples": []},
            "delivery_resegmentations": {"count": 0, "examples": []},
        },
        applied_regions=[],
        applied_region_summary="",
        correction_log={"schema": "transcribe.correction_log.v1", "cue_changes": [], "cue_diffs": [], "applied_region_summary": ""},
        delivery_audit={"schema": "transcribe.final_delivery_audit.v1", "status": "ready", "risk": "low", "checks": {}, "reasons": [], "cue_diffs": []},
        validation_fallback_reasons=[],
        finalizer_mode="llm-primary",
        finalizer_model_provider="deepseek_direct_aux",
        finalizer_model_name="deepseek-v4-flash",
        finalizer_fallback_used=False,
        finalizer_fallback_reason=None,
        finalizer_fallback_code=None,
    )

    with patch("pipeline.run_funasr_api_for_transcribe", side_effect=fake_run_funasr_api_for_transcribe), patch(
        "pipeline.build_step2a_artifacts",
        return_value=step2a_result,
    ), patch(
        "pipeline.align_draft_to_raw_tokens",
        return_value=(aligned_segments, aligned_summary),
    ), patch(
        "pipeline.build_alignment_audit",
        return_value=alignment_audit,
    ), patch(
        "pipeline.finalize_cues",
        return_value=finalizer_result,
    ):
        outputs = run_minimal_pipeline(
            audio_path=audio_path,
            run_dir=tmp_path / "run-no-rebuild",
            manuscript_text="先看整体\n再看 HPS",
            config=PipelineConfig(funasr_api_key="sk-test"),
        )

    report = json.loads(outputs.report_json_path.read_text(encoding="utf-8"))
    assert report["script_text_override_used"] is False
    assert report["timing_only_fallback_used"] is True
    assert report["step2a_text_authority"] == "llm"
    assert report["step3_text_authority"] == "interactive-agent"
    assert report["manual_review_required"] is False
    assert report["step3_status"] == "awaiting_agent_review"



def test_run_minimal_pipeline_locks_authority_flags_on_llm_primary_happy_path(tmp_path):
    audio_path = tmp_path / "sample-authority-happy.wav"
    audio_path.write_bytes(b"RIFFfake")
    raw_payload = {
        "schema": "transcribe.raw.v3",
        "text": "今天我们来聊 FunASR 也看看埃安 S",
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 2.0,
                "text": "今天我们来聊 FunASR 也看看埃安 S",
                "words": [
                    {"id": 1, "start": 0.0, "end": 1.0, "text": "今天我们来聊 FunASR", "punctuation": ""},
                    {"id": 2, "start": 1.0, "end": 2.0, "text": "也看看埃安 S", "punctuation": ""},
                ],
            }
        ],
        "backend": "funasr-api",
        "vendor": "bailian.fun-asr",
    }

    def fake_run_funasr_api_for_transcribe(*, local_audio_path, run_dir, config):
        vendor_json_path = run_dir / "bailian_raw.json"
        raw_json_path = run_dir / "raw.json"
        vendor_json_path.write_text(json.dumps({"vendor": True}, ensure_ascii=False), encoding="utf-8")
        raw_json_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return DummyFunASRResult(
            raw_json_path=raw_json_path,
            vendor_json_path=vendor_json_path,
            raw_srt_path=None,
            upload_file_id="file-123",
            uploaded_file_url="https://uploaded.example/audio.wav",
            task_id="task-123",
            result_url="https://result.example/output.json",
        )

    step2a_result = Step2ADraftingResult(
        proofread=ProofreadManuscript(
            source_text="今天我们来聊 FunASR\n也看看埃安 S",
            proofread_text="今天我们来聊 FunASR\n也看看埃安 S",
            edit_summary="llm proofreading",
            proofread_confidence=0.96,
            draft_ready=True,
            drafting_warnings=[],
        ),
        draft=SubtitleDraft(
            lines=[
                DraftLine(line_id=1, text="今天我们来聊 FunASR", source_mode="manuscript-priority"),
                DraftLine(line_id=2, text="也看看埃安 S", source_mode="manuscript-priority"),
            ]
        ),
        drafting_mode="llm-primary",
        draft_model_provider="deepseek_direct_aux",
        draft_model_name="deepseek-v4-flash",
        draft_fallback_used=False,
        draft_fallback_reason=None,
        draft_fallback_code=None,
        draft_attempt_count=1,
        text_authority="llm",
        manual_review_required=False,
        alert_reasons=[],
    )
    aligned_segments = [
        AlignedSegment(
            line_id=1,
            text="今天我们来聊 FunASR",
            start=0.0,
            end=1.0,
            raw_token_start_index=0,
            raw_token_end_index=0,
            alignment_score=0.96,
        ),
        AlignedSegment(
            line_id=2,
            text="也看看埃安 S",
            start=1.0,
            end=2.0,
            raw_token_start_index=1,
            raw_token_end_index=1,
            alignment_score=0.94,
        ),
    ]
    aligned_summary = AlignedSegmentsSummary(
        line_count=2,
        mean_alignment_score=0.95,
        low_confidence_count=0,
        interpolated_boundary_count=0,
        fallback_region_count=0,
    )
    alignment_audit = AlignmentAudit(
        chosen_mode="manuscript-priority",
        post_alignment_mode="manuscript-priority",
        mean_alignment_score=0.95,
        downgraded_regions=[],
        rebuild_regions=[],
        fallback_region_count=0,
        reasons=[],
    )
    finalizer_result = FinalizerResult(
        cues=[
            SubtitleCue(index=1, start=0.0, end=1.0, text="今天我们来聊 FunASR"),
            SubtitleCue(index=2, start=1.0, end=2.0, text="也看看埃安 S"),
        ],
        change_breakdown={
            "alias_replacements": {"count": 0, "examples": []},
            "spacing_normalizations": {"count": 0, "examples": []},
            "punctuation_normalizations": {"count": 0, "examples": []},
            "duplicate_collapses": {"count": 0, "examples": []},
            "delivery_resegmentations": {"count": 0, "examples": []},
        },
        applied_regions=[],
        applied_region_summary="",
        correction_log={"schema": "transcribe.correction_log.v1", "cue_changes": [], "cue_diffs": [], "applied_region_summary": ""},
        delivery_audit={"schema": "transcribe.final_delivery_audit.v1", "status": "ready", "risk": "low", "checks": {}, "reasons": [], "cue_diffs": []},
        validation_fallback_reasons=[],
        finalizer_mode="llm-primary",
        finalizer_model_provider="deepseek_direct_aux",
        finalizer_model_name="deepseek-v4-flash",
        finalizer_fallback_used=False,
        finalizer_fallback_reason=None,
        finalizer_fallback_code=None,
        text_authority="llm",
        manual_review_required=False,
        alert_reasons=[],
    )

    with patch("pipeline.run_funasr_api_for_transcribe", side_effect=fake_run_funasr_api_for_transcribe), patch(
        "pipeline.build_step2a_artifacts",
        return_value=step2a_result,
    ), patch(
        "pipeline.align_draft_to_raw_tokens",
        return_value=(aligned_segments, aligned_summary),
    ), patch(
        "pipeline.build_alignment_audit",
        return_value=alignment_audit,
    ), patch(
        "pipeline.finalize_cues",
        return_value=finalizer_result,
    ):
        outputs = run_minimal_pipeline(
            audio_path=audio_path,
            run_dir=tmp_path / "run-authority-happy",
            manuscript_text="今天我们来聊 FunASR\n也看看埃安 S",
            config=PipelineConfig(funasr_api_key="sk-test"),
        )

    report = json.loads(outputs.report_json_path.read_text(encoding="utf-8"))
    assert report["step2a_text_authority"] == "llm"
    assert report["step3_text_authority"] == "interactive-agent"
    assert report["manual_review_required"] is False
    assert report["step2a_alert_reasons"] == []
    assert report["step3_alert_reasons"] == []
    assert report["step3_status"] == "awaiting_agent_review"


def test_run_minimal_pipeline_keeps_llm_authority_when_step2a_only_has_soft_alerts(tmp_path):
    audio_path = tmp_path / "sample-authority-soft-alert.wav"
    audio_path.write_bytes(b"RIFFfake")
    raw_payload = {
        "schema": "transcribe.raw.v3",
        "text": "现在看A阶段 和 B阶段",
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 1.8,
                "text": "现在看A阶段 和 B阶段",
                "words": [
                    {"id": 1, "start": 0.0, "end": 0.9, "text": "现在看A阶段", "punctuation": ""},
                    {"id": 2, "start": 0.9, "end": 1.8, "text": "和 B阶段", "punctuation": ""},
                ],
            }
        ],
        "backend": "funasr-api",
        "vendor": "bailian.fun-asr",
    }

    def fake_run_funasr_api_for_transcribe(*, local_audio_path, run_dir, config):
        vendor_json_path = run_dir / "bailian_raw.json"
        raw_json_path = run_dir / "raw.json"
        vendor_json_path.write_text(json.dumps({"vendor": True}, ensure_ascii=False), encoding="utf-8")
        raw_json_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return DummyFunASRResult(
            raw_json_path=raw_json_path,
            vendor_json_path=vendor_json_path,
            raw_srt_path=None,
            upload_file_id="file-123",
            uploaded_file_url="https://uploaded.example/audio.wav",
            task_id="task-123",
            result_url="https://result.example/output.json",
        )

    step2a_result = Step2ADraftingResult(
        proofread=ProofreadManuscript(
            source_text="现在看 A 阶段\n和 B 阶段",
            proofread_text="现在看 A 阶段\n和 B 阶段",
            edit_summary="llm proofreading",
            proofread_confidence=0.9,
            draft_ready=True,
            drafting_warnings=["contract alert: subtitle_lines[1] exceeds 17 display units"],
        ),
        draft=SubtitleDraft(
            lines=[
                DraftLine(line_id=1, text="现在看 A 阶段", source_mode="raw-priority"),
                DraftLine(line_id=2, text="和 B 阶段", source_mode="raw-priority"),
            ]
        ),
        drafting_mode="llm-primary-with-alerts",
        draft_model_provider="deepseek_direct_aux",
        draft_model_name="deepseek-v4-flash",
        draft_fallback_used=False,
        draft_fallback_reason=None,
        draft_fallback_code=None,
        draft_attempt_count=1,
        text_authority="llm",
        manual_review_required=False,
        alert_reasons=["contract alert: subtitle_lines[1] exceeds 17 display units"],
    )
    aligned_segments = [
        AlignedSegment(
            line_id=1,
            text="现在看 A 阶段",
            start=0.0,
            end=0.9,
            raw_token_start_index=0,
            raw_token_end_index=0,
            alignment_score=0.92,
        ),
        AlignedSegment(
            line_id=2,
            text="和 B 阶段",
            start=0.9,
            end=1.8,
            raw_token_start_index=1,
            raw_token_end_index=1,
            alignment_score=0.92,
        ),
    ]
    aligned_summary = AlignedSegmentsSummary(
        line_count=2,
        mean_alignment_score=0.92,
        low_confidence_count=0,
        interpolated_boundary_count=0,
        fallback_region_count=0,
    )
    alignment_audit = AlignmentAudit(
        chosen_mode="raw-priority",
        post_alignment_mode="raw-priority",
        mean_alignment_score=0.92,
        downgraded_regions=[],
        rebuild_regions=[],
        fallback_region_count=0,
        reasons=[],
    )
    finalizer_result = FinalizerResult(
        cues=[
            SubtitleCue(index=1, start=0.0, end=0.9, text="现在看 A 阶段"),
            SubtitleCue(index=2, start=0.9, end=1.8, text="和 B 阶段"),
        ],
        change_breakdown={
            "alias_replacements": {"count": 0, "examples": []},
            "spacing_normalizations": {"count": 0, "examples": []},
            "punctuation_normalizations": {"count": 0, "examples": []},
            "duplicate_collapses": {"count": 0, "examples": []},
            "delivery_resegmentations": {"count": 0, "examples": []},
        },
        applied_regions=[],
        applied_region_summary="",
        correction_log={"schema": "transcribe.correction_log.v1", "cue_changes": [], "cue_diffs": [], "applied_region_summary": ""},
        delivery_audit={"schema": "transcribe.final_delivery_audit.v1", "status": "ready", "risk": "low", "checks": {}, "reasons": [], "cue_diffs": []},
        validation_fallback_reasons=[],
        finalizer_mode="llm-primary",
        finalizer_model_provider="deepseek_direct_aux",
        finalizer_model_name="deepseek-v4-flash",
        finalizer_fallback_used=False,
        finalizer_fallback_reason=None,
        finalizer_fallback_code=None,
        text_authority="llm",
        manual_review_required=False,
        alert_reasons=[],
    )

    with patch("pipeline.run_funasr_api_for_transcribe", side_effect=fake_run_funasr_api_for_transcribe), patch(
        "pipeline.build_step2a_artifacts",
        return_value=step2a_result,
    ), patch(
        "pipeline.align_draft_to_raw_tokens",
        return_value=(aligned_segments, aligned_summary),
    ), patch(
        "pipeline.build_alignment_audit",
        return_value=alignment_audit,
    ), patch(
        "pipeline.finalize_cues",
        return_value=finalizer_result,
    ):
        outputs = run_minimal_pipeline(
            audio_path=audio_path,
            run_dir=tmp_path / "run-authority-soft-alert",
            manuscript_text="现在看 A 阶段\n和 B 阶段",
            config=PipelineConfig(funasr_api_key="sk-test"),
        )

    report = json.loads(outputs.report_json_path.read_text(encoding="utf-8"))
    alert_tracking = json.loads(outputs.alert_tracking_path.read_text(encoding="utf-8"))
    assert report["drafting_mode"] == "llm-primary-with-alerts"
    assert report["step2a_text_authority"] == "llm"
    assert report["step3_text_authority"] == "interactive-agent"
    assert report["manual_review_required"] is False
    assert report["step2a_alert_reasons"] == ["contract alert: subtitle_lines[1] exceeds 17 display units"]
    assert report["step3_status"] == "awaiting_agent_review"
    assert report["alert_tracking_summary"]["alert_case_count"] == 1
    assert report["alert_tracking_summary"]["manual_review_case_count"] == 0
    assert report["alert_tracking_summary"]["code_counts"]["line_over_limit"] == 1
    assert alert_tracking["cases"][0]["stage"] == "step2a"
    assert alert_tracking["cases"][0]["code"] == "line_over_limit"


def test_run_minimal_pipeline_continues_to_agent_review_when_step2a_auxiliary_request_fails(tmp_path):
    audio_path = tmp_path / "sample-authority-step2a-fail.wav"
    audio_path.write_bytes(b"RIFFfake")
    raw_payload = {
        "schema": "transcribe.raw.v3",
        "text": "现在讲一下 HPS",
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 1.5,
                "text": "现在讲一下 HPS",
                "words": [
                    {"id": 1, "start": 0.0, "end": 1.5, "text": "现在讲一下 HPS", "punctuation": ""},
                ],
            }
        ],
        "backend": "funasr-api",
        "vendor": "bailian.fun-asr",
    }

    def fake_run_funasr_api_for_transcribe(*, local_audio_path, run_dir, config):
        vendor_json_path = run_dir / "bailian_raw.json"
        raw_json_path = run_dir / "raw.json"
        vendor_json_path.write_text(json.dumps({"vendor": True}, ensure_ascii=False), encoding="utf-8")
        raw_json_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return DummyFunASRResult(
            raw_json_path=raw_json_path,
            vendor_json_path=vendor_json_path,
            raw_srt_path=None,
            upload_file_id="file-123",
            uploaded_file_url="https://uploaded.example/audio.wav",
            task_id="task-123",
            result_url="https://result.example/output.json",
        )

    step2a_result = Step2ADraftingResult(
        proofread=ProofreadManuscript(
            source_text="现在讲一下 HPS",
            proofread_text="现在讲一下 HPS",
            edit_summary="agent managed fallback",
            proofread_confidence=0.72,
            draft_ready=True,
            drafting_warnings=["auxiliary timeout", "bootstrap proofreading only"],
        ),
        draft=SubtitleDraft(lines=[DraftLine(line_id=1, text="现在讲一下 HPS", source_mode="manuscript-priority")]),
        drafting_mode="agent-fallback",
        draft_model_provider="local-helper",
        draft_model_name=None,
        draft_fallback_used=True,
        draft_fallback_reason="auxiliary timeout",
        draft_fallback_code="auxiliary_request_failed",
        draft_attempt_count=0,
        text_authority="interactive-agent",
        manual_review_required=False,
        alert_reasons=["auxiliary timeout"],
    )
    aligned_segments = [
        AlignedSegment(
            line_id=1,
            text="现在讲一下 HPS",
            start=0.0,
            end=1.5,
            raw_token_start_index=0,
            raw_token_end_index=0,
            alignment_score=0.92,
        )
    ]
    aligned_summary = AlignedSegmentsSummary(
        line_count=1,
        mean_alignment_score=0.92,
        low_confidence_count=0,
        interpolated_boundary_count=0,
        fallback_region_count=0,
    )
    alignment_audit = AlignmentAudit(
        chosen_mode="manuscript-priority",
        post_alignment_mode="manuscript-priority",
        mean_alignment_score=0.92,
        downgraded_regions=[],
        rebuild_regions=[],
        fallback_region_count=0,
        reasons=[],
    )

    with patch("pipeline.run_funasr_api_for_transcribe", side_effect=fake_run_funasr_api_for_transcribe), patch(
        "pipeline.build_step2a_artifacts",
        return_value=step2a_result,
    ), patch(
        "pipeline.align_draft_to_raw_tokens",
        return_value=(aligned_segments, aligned_summary),
    ), patch(
        "pipeline.build_alignment_audit",
        return_value=alignment_audit,
    ), patch(
        "pipeline.finalize_cues",
        side_effect=AssertionError("pipeline should stop at agent handoff before step 3 final adjudication"),
    ):
        outputs = run_minimal_pipeline(
            audio_path=audio_path,
            run_dir=tmp_path / "run-authority-step2a-fail",
            manuscript_text="现在讲一下 HPS",
            config=PipelineConfig(funasr_api_key="sk-test"),
        )

    report = json.loads(outputs.report_json_path.read_text(encoding="utf-8"))
    alert_tracking = json.loads(outputs.alert_tracking_path.read_text(encoding="utf-8"))
    proofread = json.loads(outputs.proofread_manuscript_path.read_text(encoding="utf-8"))
    subtitle_draft = json.loads(outputs.subtitle_draft_path.read_text(encoding="utf-8"))
    agent_review_bundle = json.loads(outputs.agent_review_bundle_path.read_text(encoding="utf-8"))
    assert proofread["proofread_text"] == "现在讲一下 HPS"
    assert outputs.edited_srt_path is None
    assert outputs.final_delivery_audit_path is None
    assert outputs.correction_log_path is None
    assert report["drafting_mode"] == "agent-fallback"
    assert report["step2a_text_authority"] == "interactive-agent"
    assert report["step3_text_authority"] == "interactive-agent"
    assert report["manual_review_required"] is False
    assert report["draft_model_provider"] == "local-helper"
    assert report["draft_model_name"] is None
    assert report["draft_fallback_used"] is True
    assert report["draft_fallback_reason"] == "auxiliary timeout"
    assert report["draft_fallback_code"] == "auxiliary_request_failed"
    assert report["step3_status"] == "awaiting_agent_review"
    assert report["final_delivery_status"] == "awaiting_agent_review"
    assert report["step2a_alert_reasons"] == ["auxiliary timeout"]
    assert subtitle_draft["lines"]
    assert agent_review_bundle["step3_execution_mode"] == "agent-session"
    assert alert_tracking["manual_review_case_count"] == 0


def test_run_minimal_pipeline_stops_at_agent_handoff_after_step2_success(tmp_path):
    audio_path = tmp_path / "sample-authority-step3-fail.wav"
    audio_path.write_bytes(b"RIFFfake")
    raw_payload = {
        "schema": "transcribe.raw.v3",
        "text": "先看整体 再看 HPS",
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 2.0,
                "text": "先看整体 再看 HPS",
                "words": [
                    {"id": 1, "start": 0.0, "end": 1.0, "text": "先看整体", "punctuation": ""},
                    {"id": 2, "start": 1.0, "end": 2.0, "text": "再看 HPS", "punctuation": ""},
                ],
            }
        ],
        "backend": "funasr-api",
        "vendor": "bailian.fun-asr",
    }

    def fake_run_funasr_api_for_transcribe(*, local_audio_path, run_dir, config):
        vendor_json_path = run_dir / "bailian_raw.json"
        raw_json_path = run_dir / "raw.json"
        vendor_json_path.write_text(json.dumps({"vendor": True}, ensure_ascii=False), encoding="utf-8")
        raw_json_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return DummyFunASRResult(
            raw_json_path=raw_json_path,
            vendor_json_path=vendor_json_path,
            raw_srt_path=None,
            upload_file_id="file-123",
            uploaded_file_url="https://uploaded.example/audio.wav",
            task_id="task-123",
            result_url="https://result.example/output.json",
        )

    step2a_result = Step2ADraftingResult(
        proofread=ProofreadManuscript(
            source_text="先看整体\n再看 HPS",
            proofread_text="先看整体\n再看 HPS",
            edit_summary="llm proofreading",
            proofread_confidence=0.95,
            draft_ready=True,
            drafting_warnings=[],
        ),
        draft=SubtitleDraft(
            lines=[
                DraftLine(line_id=1, text="先看整体", source_mode="manuscript-priority"),
                DraftLine(line_id=2, text="再看 HPS", source_mode="manuscript-priority"),
            ]
        ),
        drafting_mode="llm-primary",
        draft_model_provider="deepseek_direct_aux",
        draft_model_name="deepseek-v4-flash",
        draft_fallback_used=False,
        draft_fallback_reason=None,
        draft_fallback_code=None,
        draft_attempt_count=1,
        text_authority="llm",
        manual_review_required=False,
        alert_reasons=[],
    )
    aligned_segments = [
        AlignedSegment(
            line_id=1,
            text="先看整体",
            start=0.0,
            end=1.0,
            raw_token_start_index=0,
            raw_token_end_index=0,
            alignment_score=0.92,
        ),
        AlignedSegment(
            line_id=2,
            text="再看 HPS",
            start=1.0,
            end=2.0,
            raw_token_start_index=1,
            raw_token_end_index=1,
            alignment_score=0.92,
        ),
    ]
    aligned_summary = AlignedSegmentsSummary(
        line_count=2,
        mean_alignment_score=0.92,
        low_confidence_count=0,
        interpolated_boundary_count=0,
        fallback_region_count=0,
    )
    alignment_audit = AlignmentAudit(
        chosen_mode="manuscript-priority",
        post_alignment_mode="manuscript-priority",
        mean_alignment_score=0.92,
        downgraded_regions=[],
        rebuild_regions=[],
        fallback_region_count=0,
        reasons=[],
    )
    finalizer_result = FinalizerResult(
        cues=[
            SubtitleCue(index=1, start=0.0, end=1.0, text="先看整体"),
            SubtitleCue(index=2, start=1.0, end=2.0, text="再看 HPS"),
        ],
        change_breakdown={
            "alias_replacements": {"count": 0, "examples": []},
            "spacing_normalizations": {"count": 0, "examples": []},
            "punctuation_normalizations": {"count": 0, "examples": []},
            "duplicate_collapses": {"count": 0, "examples": []},
            "delivery_resegmentations": {"count": 0, "examples": []},
        },
        applied_regions=[],
        applied_region_summary="",
        correction_log={"schema": "transcribe.correction_log.v1", "cue_changes": [], "cue_diffs": [], "applied_region_summary": ""},
        delivery_audit={"schema": "transcribe.final_delivery_audit.v1", "status": "needs_review", "risk": "high", "checks": {}, "reasons": ["auxiliary timeout"], "cue_diffs": []},
        validation_fallback_reasons=[],
        finalizer_mode="manual-review-required",
        finalizer_model_provider=None,
        finalizer_model_name=None,
        finalizer_fallback_used=False,
        finalizer_fallback_reason="auxiliary timeout",
        finalizer_fallback_code="auxiliary_request_failed",
        text_authority="llm",
        manual_review_required=True,
        alert_reasons=["auxiliary timeout"],
    )

    with patch("pipeline.run_funasr_api_for_transcribe", side_effect=fake_run_funasr_api_for_transcribe), patch(
        "pipeline.build_step2a_artifacts",
        return_value=step2a_result,
    ), patch(
        "pipeline.align_draft_to_raw_tokens",
        return_value=(aligned_segments, aligned_summary),
    ), patch(
        "pipeline.build_alignment_audit",
        return_value=alignment_audit,
    ), patch(
        "pipeline.finalize_cues",
        return_value=finalizer_result,
    ):
        outputs = run_minimal_pipeline(
            audio_path=audio_path,
            run_dir=tmp_path / "run-authority-step3-fail",
            manuscript_text="先看整体\n再看 HPS",
            config=PipelineConfig(funasr_api_key="sk-test"),
        )

    report = json.loads(outputs.report_json_path.read_text(encoding="utf-8"))
    script_pass_srt = outputs.script_pass_srt_path.read_text(encoding="utf-8")
    assert "先看整体" in script_pass_srt
    assert "再看 HPS" in script_pass_srt
    assert report["step2a_text_authority"] == "llm"
    assert report["step3_text_authority"] == "interactive-agent"
    assert report["manual_review_required"] is False
    assert report["finalizer_mode"] == "agent-session-pending"
    assert report["step3_status"] == "awaiting_agent_review"
    assert report["step3_alert_reasons"] == []
    assert outputs.edited_srt_path is None
    assert outputs.final_delivery_audit_path is None
