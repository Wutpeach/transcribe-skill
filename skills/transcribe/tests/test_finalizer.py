import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from contracts import AgentReviewBundle, GlossaryEntry, RunGlossary, SubtitleCue
from finalizer import AgentReviewRequiredError, FinalizerResult, apply_cue_splits, build_agent_review_bundle, finalize_cues, write_agent_review_bundle
from finalizer_audit import apply_delivery_timing_smoothing


def test_build_agent_review_bundle_collects_step2_handoff_inputs():
    bundle = build_agent_review_bundle(
        run_dir=Path("/tmp/run"),
        report={
            "chosen_mode": "manuscript-priority",
            "post_alignment_mode": "raw-priority",
            "alignment_success_rate": 0.8,
            "fallback_region_count": 3,
            "downgrade_count": 1,
            "step2a_alert_reasons": ["a", "b"],
            "step3_alert_reasons": ["c"],
        },
        priority_cases=[{"cue_index": 44, "reason": "punctuation violation", "text": "假如有 A-B-C-D 几个生产流程"}],
    )

    assert isinstance(bundle, AgentReviewBundle)
    assert bundle.step3_execution_mode == "agent-session"
    assert bundle.step3_owner == "interactive-agent"
    assert bundle.input_paths["script_pass_srt"] == "edited-script-pass.srt"
    assert bundle.headline["chosen_mode"] == "manuscript-priority"
    assert bundle.headline["step2a_alert_count"] == 2
    assert bundle.headline["step2b_or_step3_signal_count"] == 1
    assert bundle.priority_cases[0]["cue_index"] == 44


def test_write_agent_review_bundle_writes_json_payload(tmp_path):
    bundle = AgentReviewBundle(
        run_dir=str(tmp_path),
        step3_execution_mode="agent-session",
        step3_owner="interactive-agent",
        input_paths={"script_pass_srt": "edited-script-pass.srt"},
        headline={"chosen_mode": "manuscript-priority"},
        priority_cases=[],
    )
    output_path = tmp_path / "agent_review_bundle.json"

    write_agent_review_bundle(bundle, output_path)

    payload = output_path.read_text(encoding="utf-8")
    assert '"schema": "transcribe.agent_review_bundle.v1"' in payload
    assert '"step3_execution_mode": "agent-session"' in payload


def test_finalize_cues_rules_primary_preserves_incoming_text_without_proofread_context():
    glossary = RunGlossary(
        terms=[
            GlossaryEntry(term="S7", aliases=["s7"]),
            GlossaryEntry(term="HPS", aliases=["hps"]),
            GlossaryEntry(term="FunASR API", aliases=["funasr api"]),
        ]
    )
    cues = [
        SubtitleCue(index=1, start=0.0, end=1.0, text="他造过的s7"),
        SubtitleCue(index=2, start=1.0, end=2.0, text="也讲到hps和funasr api"),
    ]

    finalized = finalize_cues(cues=cues, glossary=glossary)

    assert isinstance(finalized, FinalizerResult)
    assert [cue.text for cue in finalized.cues] == ["他造过的s7", "也讲到hps和funasr api"]
    assert finalized.finalizer_mode == "rules-primary"
    assert finalized.text_authority == "inherited"
    assert finalized.delivery_audit["status"] == "ready"
    assert finalized.delivery_audit["risk"] == "low"
    assert finalized.validation_fallback_reasons == []
    assert finalized.applied_region_summary == ""
    assert finalized.correction_log["cue_changes"] == []
    assert finalized.correction_log["cue_diffs"] == []
    assert all(bucket["count"] == 0 for bucket in finalized.change_breakdown.values())


def test_finalize_cues_records_validation_fallback_without_rewriting_text():
    glossary = RunGlossary(terms=[GlossaryEntry(term="PPT", aliases=["ppt"])])
    cues = [
        SubtitleCue(index=1, start=0.0, end=1.0, text="写个ppt"),
    ]

    finalized = finalize_cues(
        cues=cues,
        glossary=glossary,
        aligned_segments=[{"line_id": 3, "text": "别的行"}],
    )

    assert finalized.cues[0].text == "写个ppt"
    assert finalized.finalizer_mode == "rules-primary"
    assert finalized.text_authority == "inherited"
    assert finalized.delivery_audit["status"] == "ready_with_fallback"
    assert finalized.delivery_audit["risk"] == "medium"
    assert finalized.validation_fallback_reasons == ["aligned_segments_mismatch"]
    assert finalized.delivery_audit["reasons"] == ["aligned_segments_mismatch"]
    assert finalized.applied_region_summary == ""
    assert finalized.correction_log["cue_changes"] == []
    assert finalized.correction_log["cue_diffs"] == []
    assert all(bucket["count"] == 0 for bucket in finalized.change_breakdown.values())


def test_finalize_cues_rules_primary_keeps_punctuation_and_duplicate_text_but_marks_review():
    glossary = RunGlossary(terms=[GlossaryEntry(term="PPT", aliases=["ppt"])])
    cues = [
        SubtitleCue(index=1, start=0.0, end=2.0, text="好啊，写一份详细的一份详细的ppt，仔细描述问题。"),
    ]

    finalized = finalize_cues(cues=cues, glossary=glossary)

    assert finalized.cues[0].text == "好啊，写一份详细的一份详细的ppt，仔细描述问题。"
    assert finalized.finalizer_mode == "rules-primary"
    assert finalized.text_authority == "inherited"
    assert finalized.delivery_audit["status"] == "needs_review"
    assert finalized.delivery_audit["risk"] == "high"
    assert finalized.delivery_audit["reasons"] == ["punctuation_violation"]
    assert finalized.change_breakdown["alias_replacements"]["count"] == 0
    assert finalized.change_breakdown["spacing_normalizations"]["count"] == 0
    assert finalized.change_breakdown["punctuation_normalizations"]["count"] == 0
    assert finalized.change_breakdown["duplicate_collapses"]["count"] == 0
    assert finalized.change_breakdown["delivery_resegmentations"]["count"] == 0


def test_finalize_cues_rules_primary_does_not_merge_micro_cues_even_with_warning_evidence():
    glossary = RunGlossary(terms=[])
    cues = [
        SubtitleCue(index=1, start=0.0, end=1.0, text="我们先看整体"),
        SubtitleCue(index=2, start=1.0, end=1.2, text="啊"),
        SubtitleCue(index=3, start=1.2, end=1.4, text="嗯"),
        SubtitleCue(index=4, start=1.4, end=2.4, text="再看细节"),
    ]

    finalized = finalize_cues(
        cues=cues,
        glossary=glossary,
        aligned_segments=[
            {"line_id": 1, "text": "我们先看整体", "warnings": []},
            {"line_id": 2, "text": "啊", "warnings": ["tail micro cue"]},
            {"line_id": 3, "text": "嗯", "warnings": ["tail micro cue"]},
            {"line_id": 4, "text": "再看细节", "warnings": []},
        ],
    )

    assert [cue.text for cue in finalized.cues] == ["我们先看整体", "啊", "嗯", "再看细节"]
    assert [(cue.start, cue.end) for cue in finalized.cues] == [(0.0, 1.0), (1.0, 1.2), (1.2, 1.4), (1.4, 2.4)]
    assert finalized.finalizer_mode == "rules-primary"
    assert finalized.text_authority == "inherited"
    assert finalized.change_breakdown["delivery_resegmentations"]["count"] == 0
    assert finalized.delivery_audit["resegment_source"] == []
    assert finalized.correction_log["cue_changes"] == []


def test_finalize_cues_heuristically_splits_rhythm_boundary_cue_before_writeback():
    glossary = RunGlossary(terms=[])
    cues = [
        SubtitleCue(index=1, start=10.0, end=12.0, text="说完云端的 我们再来看看"),
    ]
    raw_payload = {
        "segments": [
            {
                "id": 1,
                "start": 10.0,
                "end": 12.0,
                "text": "说完云端的我们再来看看",
                "words": [
                    {"id": 1, "text": "说完", "start": 10.0, "end": 10.35, "punctuation": ""},
                    {"id": 2, "text": "云端", "start": 10.35, "end": 10.8, "punctuation": ""},
                    {"id": 3, "text": "的", "start": 10.8, "end": 10.95, "punctuation": ""},
                    {"id": 4, "text": "我们", "start": 10.95, "end": 11.3, "punctuation": ""},
                    {"id": 5, "text": "再来", "start": 11.3, "end": 11.65, "punctuation": ""},
                    {"id": 6, "text": "看看", "start": 11.65, "end": 12.0, "punctuation": ""},
                ],
            }
        ]
    }

    finalized = finalize_cues(
        cues=cues,
        glossary=glossary,
        raw_payload=raw_payload,
        aligned_segments=[
            {
                "line_id": 1,
                "text": "说完云端的 我们再来看看",
                "start": 10.0,
                "end": 12.0,
                "raw_token_start_index": 0,
                "raw_token_end_index": 5,
                "alignment_score": 1.0,
                "warnings": [],
            }
        ],
    )

    assert [(cue.index, cue.start, cue.end, cue.text) for cue in finalized.cues] == [
        (1, 10.0, 10.95, "说完云端的"),
        (2, 10.95, 12.0, "我们再来看看"),
    ]
    assert finalized.change_breakdown["delivery_resegmentations"]["count"] == 1
    assert finalized.change_breakdown["delivery_resegmentations"]["examples"] == ["1->1,2"]
    assert finalized.applied_region_summary == "1"
    assert finalized.delivery_audit["checks"]["resegment_count"] == 1
    assert finalized.delivery_audit["resegment_source"] == ["step3_heuristic_resegmentation"]
    assert finalized.delivery_audit["cue_splitting"]["split_count"] == 1
    assert finalized.correction_log["cue_changes"][0]["after_cues"] == [
        {"cue_index": 1, "text": "说完云端的"},
        {"cue_index": 2, "text": "我们再来看看"},
    ]
    assert finalized.correction_log["cue_changes"][0]["change_types"] == ["step3_heuristic_resegmentation"]
    assert finalized.correction_log["cue_changes"][0]["resegment_source"] == ["step3_heuristic_resegmentation"]


def test_finalize_cues_heuristically_splits_dense_list_like_cue_before_writeback():
    glossary = RunGlossary(terms=[])
    cues = [
        SubtitleCue(index=1, start=20.0, end=22.0, text="系统根据这些物体的距离 速度 轨迹预测"),
    ]
    raw_payload = {
        "segments": [
            {
                "id": 2,
                "start": 20.0,
                "end": 22.0,
                "text": "系统根据这些物体的距离速度轨迹预测",
                "words": [
                    {"id": 1, "text": "系统", "start": 20.0, "end": 20.2, "punctuation": ""},
                    {"id": 2, "text": "根据", "start": 20.2, "end": 20.45, "punctuation": ""},
                    {"id": 3, "text": "这些", "start": 20.45, "end": 20.65, "punctuation": ""},
                    {"id": 4, "text": "物体", "start": 20.65, "end": 20.9, "punctuation": ""},
                    {"id": 5, "text": "的", "start": 20.9, "end": 21.0, "punctuation": ""},
                    {"id": 6, "text": "距离", "start": 21.0, "end": 21.3, "punctuation": ""},
                    {"id": 7, "text": "速度", "start": 21.3, "end": 21.55, "punctuation": ""},
                    {"id": 8, "text": "轨迹", "start": 21.55, "end": 21.8, "punctuation": ""},
                    {"id": 9, "text": "预测", "start": 21.8, "end": 22.0, "punctuation": ""},
                ],
            }
        ]
    }

    finalized = finalize_cues(
        cues=cues,
        glossary=glossary,
        raw_payload=raw_payload,
        aligned_segments=[
            {
                "line_id": 1,
                "text": "系统根据这些物体的距离 速度 轨迹预测",
                "start": 20.0,
                "end": 22.0,
                "raw_token_start_index": 0,
                "raw_token_end_index": 8,
                "alignment_score": 1.0,
                "warnings": [],
            }
        ],
    )

    assert [(cue.index, cue.start, cue.end, cue.text) for cue in finalized.cues] == [
        (1, 20.0, 21.3, "系统根据这些物体的距离"),
        (2, 21.3, 22.0, "速度 轨迹预测"),
    ]
    assert finalized.change_breakdown["delivery_resegmentations"]["count"] == 1
    assert finalized.delivery_audit["cue_splitting"]["split_count"] == 1
    assert finalized.delivery_audit["cue_splitting"]["max_length"] == 11
    assert finalized.correction_log["cue_changes"][0]["after"] == "系统根据这些物体的距离\n速度 轨迹预测"


def test_finalize_cues_does_not_split_mixed_script_spacing_only_cue():
    glossary = RunGlossary(terms=[GlossaryEntry(term="FunASR API", aliases=["funasr api"])])
    cues = [
        SubtitleCue(index=1, start=0.0, end=1.4, text="他提到 FunASR API"),
    ]
    raw_payload = {
        "segments": [
            {
                "id": 3,
                "start": 0.0,
                "end": 1.4,
                "text": "他提到FunASRAPI",
                "words": [
                    {"id": 1, "text": "他提到", "start": 0.0, "end": 0.45, "punctuation": ""},
                    {"id": 2, "text": "FunASR", "start": 0.45, "end": 0.95, "punctuation": ""},
                    {"id": 3, "text": "API", "start": 0.95, "end": 1.4, "punctuation": ""},
                ],
            }
        ]
    }

    finalized = finalize_cues(
        cues=cues,
        glossary=glossary,
        raw_payload=raw_payload,
        aligned_segments=[
            {
                "line_id": 1,
                "text": "他提到 FunASR API",
                "start": 0.0,
                "end": 1.4,
                "raw_token_start_index": 0,
                "raw_token_end_index": 2,
                "alignment_score": 1.0,
                "warnings": [],
            }
        ],
    )

    assert [(cue.index, cue.start, cue.end, cue.text) for cue in finalized.cues] == [(1, 0.0, 1.4, "他提到 FunASR API")]
    assert finalized.change_breakdown["delivery_resegmentations"]["count"] == 0
    assert finalized.delivery_audit["resegment_source"] == []
    assert finalized.correction_log["cue_changes"] == []


def test_finalize_cues_skips_heuristic_resegmentation_when_alignment_metadata_is_incomplete():
    glossary = RunGlossary(terms=[])
    cues = [
        SubtitleCue(index=1, start=10.0, end=12.0, text="说完云端的 我们再来看看"),
    ]
    raw_payload = {
        "segments": [
            {
                "id": 1,
                "start": 10.0,
                "end": 12.0,
                "text": "说完云端的我们再来看看",
                "words": [],
            }
        ]
    }

    finalized = finalize_cues(
        cues=cues,
        glossary=glossary,
        raw_payload=raw_payload,
        aligned_segments=[
            {
                "line_id": 1,
                "text": "说完云端的 我们再来看看",
                "start": 10.0,
                "end": 12.0,
                "alignment_score": 1.0,
                "warnings": [],
            }
        ],
    )

    assert [(cue.index, cue.start, cue.end, cue.text) for cue in finalized.cues] == [(1, 10.0, 12.0, "说完云端的 我们再来看看")]
    assert finalized.change_breakdown["delivery_resegmentations"]["count"] == 0
    assert finalized.delivery_audit["resegment_source"] == []
    assert finalized.correction_log["cue_changes"] == []


def test_apply_delivery_timing_smoothing_snaps_first_cue_and_fills_positive_gaps():
    cues = [
        SubtitleCue(index=1, start=0.5, end=1.0, text="第一句"),
        SubtitleCue(index=2, start=1.4, end=2.0, text="第二句"),
        SubtitleCue(index=3, start=2.5, end=3.0, text="第三句"),
    ]

    smoothed_cues, metadata = apply_delivery_timing_smoothing(cues)

    assert [(cue.index, cue.start, cue.end, cue.text) for cue in smoothed_cues] == [
        (1, 0.0, 1.4, "第一句"),
        (2, 1.4, 2.5, "第二句"),
        (3, 2.5, 3.0, "第三句"),
    ]
    assert metadata == {
        "applied": True,
        "first_cue_snapped": True,
        "gaps_filled": 2,
    }
    assert [(cue.start, cue.end) for cue in cues] == [(0.5, 1.0), (1.4, 2.0), (2.5, 3.0)]



def test_apply_delivery_timing_smoothing_preserves_overlap_and_last_cue_end():
    cues = [
        SubtitleCue(index=1, start=0.0, end=1.2, text="第一句"),
        SubtitleCue(index=2, start=1.0, end=1.8, text="第二句"),
        SubtitleCue(index=3, start=2.0, end=2.6, text="第三句"),
    ]

    smoothed_cues, metadata = apply_delivery_timing_smoothing(cues)

    assert [(cue.index, cue.start, cue.end, cue.text) for cue in smoothed_cues] == [
        (1, 0.0, 1.2, "第一句"),
        (2, 1.0, 2.0, "第二句"),
        (3, 2.0, 2.6, "第三句"),
    ]
    assert metadata == {
        "applied": True,
        "first_cue_snapped": False,
        "gaps_filled": 1,
    }



def test_apply_delivery_timing_smoothing_handles_single_cue_without_extending_end():
    cues = [SubtitleCue(index=1, start=0.3, end=1.1, text="单句")]

    smoothed_cues, metadata = apply_delivery_timing_smoothing(cues)

    assert [(cue.index, cue.start, cue.end, cue.text) for cue in smoothed_cues] == [(1, 0.0, 1.1, "单句")]
    assert metadata == {
        "applied": True,
        "first_cue_snapped": True,
        "gaps_filled": 0,
    }



def test_finalize_cues_requires_live_agent_adjudication_when_proofread_context_is_provided():
    glossary = RunGlossary(terms=[GlossaryEntry(term="HPS", aliases=["hps"])])
    cues = [
        SubtitleCue(index=1, start=0.0, end=1.0, text="我们整体看一下"),
        SubtitleCue(index=2, start=1.0, end=2.0, text="再讲hps"),
    ]

    try:
        finalize_cues(
            cues=cues,
            glossary=glossary,
            raw_payload={"text": "我们先看整体，再讲 HPS。", "segments": []},
            proofread={"proofread_text": "我们先看整体\n再讲 HPS"},
            aligned_segments=[
                {"line_id": 1, "text": "我们整体看一下", "warnings": []},
                {"line_id": 2, "text": "再讲hps", "warnings": []},
            ],
        )
    except AgentReviewRequiredError as exc:
        assert "live agent" in str(exc)
    else:
        raise AssertionError("finalize_cues should reject proofread-driven backend adjudication")


def test_apply_cue_splits_creates_true_new_cues_with_onset_first_timing():
    cues = [
        SubtitleCue(index=1, start=24.44, end=27.5, text="他们会考虑好我们国内的法规道路情况等"),
    ]
    raw_payload = {
        "segments": [
            {
                "id": 5,
                "start": 24.44,
                "end": 27.64,
                "text": "他们会考虑好我们国内的法规道路情况等等",
                "words": [
                    {"id": 1, "text": "他们会", "start": 24.44, "end": 24.88, "punctuation": ""},
                    {"id": 2, "text": "考虑", "start": 24.88, "end": 25.24, "punctuation": ""},
                    {"id": 3, "text": "好", "start": 25.24, "end": 25.52, "punctuation": ""},
                    {"id": 4, "text": "我们", "start": 25.52, "end": 25.76, "punctuation": ""},
                    {"id": 5, "text": "国内", "start": 25.76, "end": 26.08, "punctuation": ""},
                    {"id": 6, "text": "的", "start": 26.08, "end": 26.20, "punctuation": ""},
                    {"id": 7, "text": "法规", "start": 26.20, "end": 26.68, "punctuation": "、"},
                    {"id": 8, "text": "道路", "start": 26.80, "end": 27.08, "punctuation": ""},
                    {"id": 9, "text": "情况", "start": 27.08, "end": 27.36, "punctuation": ""},
                    {"id": 10, "text": "等等", "start": 27.36, "end": 27.64, "punctuation": "，"},
                ],
            }
        ]
    }
    aligned_segments = [
        {
            "line_id": 1,
            "text": "他们会考虑好我们国内的法规道路情况等",
            "start": 24.44,
            "end": 27.5,
            "raw_token_start_index": 0,
            "raw_token_end_index": 9,
            "alignment_score": 1.0,
            "warnings": [],
        }
    ]

    result = apply_cue_splits(
        cues=cues,
        split_decisions=[{"cue_index": 1, "texts": ["他们会考虑好我们国内的", "法规道路情况等"]}],
        raw_payload=raw_payload,
        aligned_segments=aligned_segments,
    )

    assert [(cue.index, cue.start, cue.end, cue.text) for cue in result.cues] == [
        (1, 24.44, 26.2, "他们会考虑好我们国内的"),
        (2, 26.2, 27.5, "法规道路情况等"),
    ]
    assert result.correction_entries[0]["source_cue_indexes"] == [1]
    assert result.correction_entries[0]["after_cues"] == [
        {"cue_index": 1, "text": "他们会考虑好我们国内的"},
        {"cue_index": 2, "text": "法规道路情况等"},
    ]
    assert result.cue_splits == [
        {
            "original_line_id": 1,
            "new_line_ids": [1, 2],
            "split_type": "token_anchored",
            "split_confidence": "high",
            "start_alignment_delta_ms": 0,
            "risk_level": "low",
            "used_fallback": False,
            "fallback_steps": [],
            "split_point_token_index": 6,
        }
    ]
    assert result.split_statistics == {
        "total_splits": 1,
        "token_anchored_count": 1,
        "partial_token_anchored_count": 0,
        "proportional_fallback_count": 0,
        "low_confidence_split_count": 0,
    }


def test_apply_cue_splits_uses_partial_token_onset_snap_for_low_confidence_alignment():
    cues = [
        SubtitleCue(index=1, start=31.4, end=34.14666666666667, text="东本和广本基本就决定个车内外颜色啥的"),
    ]
    raw_payload = {
        "segments": [
            {
                "id": 6,
                "start": 31.4,
                "end": 34.44,
                "text": "东本和广本啊基本就决定个这个车内外的颜色",
                "words": [
                    {"id": 1, "text": "东", "start": 31.4, "end": 31.6, "punctuation": ""},
                    {"id": 2, "text": "本", "start": 31.6, "end": 31.72, "punctuation": ""},
                    {"id": 3, "text": "和", "start": 31.72, "end": 31.88, "punctuation": ""},
                    {"id": 4, "text": "广", "start": 31.88, "end": 32.04, "punctuation": ""},
                    {"id": 5, "text": "本", "start": 32.04, "end": 32.2, "punctuation": ""},
                    {"id": 6, "text": "啊", "start": 32.2, "end": 32.32, "punctuation": "，"},
                    {"id": 7, "text": "基本", "start": 32.36, "end": 32.68, "punctuation": ""},
                    {"id": 8, "text": "就", "start": 32.68, "end": 32.96, "punctuation": ""},
                    {"id": 9, "text": "决定", "start": 32.96, "end": 33.24, "punctuation": ""},
                    {"id": 10, "text": "个", "start": 33.24, "end": 33.4, "punctuation": ""},
                    {"id": 11, "text": "这个", "start": 33.4, "end": 33.56, "punctuation": ""},
                    {"id": 12, "text": "车", "start": 33.56, "end": 33.72, "punctuation": ""},
                    {"id": 13, "text": "内外", "start": 33.72, "end": 34.0, "punctuation": ""},
                    {"id": 14, "text": "的颜色", "start": 34.0, "end": 34.44, "punctuation": ""},
                ],
            }
        ]
    }
    aligned_segments = [
        {
            "line_id": 1,
            "text": "东本和广本基本就决定个车内外颜色啥的",
            "start": 31.4,
            "end": 34.14666666666667,
            "raw_token_start_index": 0,
            "raw_token_end_index": 13,
            "alignment_score": 0.683,
            "warnings": ["low alignment confidence", "skipped leading raw characters"],
        }
    ]

    result = apply_cue_splits(
        cues=cues,
        split_decisions=[{"cue_index": 1, "texts": ["东本和广本基本就决定个", "车内外颜色啥的"]}],
        raw_payload=raw_payload,
        aligned_segments=aligned_segments,
    )

    assert [(cue.index, cue.start, cue.end, cue.text) for cue in result.cues] == [
        (1, 31.4, 33.56, "东本和广本基本就决定个"),
        (2, 33.56, 34.14666666666667, "车内外颜色啥的"),
    ]
    assert result.cue_splits == [
        {
            "original_line_id": 1,
            "new_line_ids": [1, 2],
            "split_type": "partial_token_anchored",
            "split_confidence": "low",
            "start_alignment_delta_ms": 0,
            "risk_level": "high",
            "used_fallback": True,
            "fallback_steps": ["partial_token_onset_snap"],
            "split_point_token_index": 11,
        }
    ]
    assert result.split_statistics == {
        "total_splits": 1,
        "token_anchored_count": 0,
        "partial_token_anchored_count": 1,
        "proportional_fallback_count": 0,
        "low_confidence_split_count": 1,
    }
