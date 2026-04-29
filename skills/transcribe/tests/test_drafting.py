import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from drafting import Step2ADraftingResult, build_proofread_manuscript, build_step2a_artifacts, build_subtitle_draft
from glossary import build_run_glossary
from contracts import DraftLine, ProofreadManuscript, RunGlossary, SubtitleDraft


RAW_PAYLOAD = {
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
}


def test_build_proofread_manuscript_prefers_manuscript_in_manuscript_priority_mode():
    manuscript_text = "今天我们来聊 FunASR。\n还看看埃安 S。"
    glossary = build_run_glossary(raw_payload=RAW_PAYLOAD, manuscript_text=manuscript_text)

    proofread = build_proofread_manuscript(
        raw_payload=RAW_PAYLOAD,
        manuscript_text=manuscript_text,
        mode="manuscript-priority",
        glossary=glossary,
    )

    assert proofread.source_text == manuscript_text
    assert "FunASR" in proofread.proofread_text
    assert "埃安 S" in proofread.proofread_text



def test_build_subtitle_draft_produces_semantic_lines_from_manuscript_priority_input():
    manuscript_text = "今天我们来聊 FunASR。\n还看看埃安 S。"
    glossary = build_run_glossary(raw_payload=RAW_PAYLOAD, manuscript_text=manuscript_text)
    proofread = build_proofread_manuscript(
        raw_payload=RAW_PAYLOAD,
        manuscript_text=manuscript_text,
        mode="manuscript-priority",
        glossary=glossary,
    )

    draft = build_subtitle_draft(
        raw_payload=RAW_PAYLOAD,
        manuscript_text=manuscript_text,
        mode="manuscript-priority",
        glossary=glossary,
        proofread=proofread,
    )

    assert len(draft.lines) == 2
    assert draft.lines[0].line_id == 1
    assert draft.lines[0].source_mode == "manuscript-priority"
    assert draft.lines[0].text == "今天我们来聊 FunASR"
    assert draft.lines[1].text == "还看看埃安 S"
    assert draft.lines[0].style_flags.punctuation_free is True
    assert draft.lines[0].style_flags.delivery_plain_text is True
    assert draft.lines[0].raw_span_mapping.segment_ids
    assert draft.lines[0].quality_signals.semantic_integrity in {"high", "medium", "low"}



def test_build_proofread_manuscript_keeps_raw_text_anchor_in_raw_priority_mode():
    glossary = build_run_glossary(raw_payload=RAW_PAYLOAD, manuscript_text=None)

    proofread = build_proofread_manuscript(
        raw_payload=RAW_PAYLOAD,
        manuscript_text=None,
        mode="raw-priority",
        glossary=glossary,
    )

    assert proofread.source_text == RAW_PAYLOAD["text"]
    assert proofread.proofread_text == RAW_PAYLOAD["text"]



def test_build_subtitle_draft_uses_raw_transcript_structure_in_raw_priority_mode():
    glossary = build_run_glossary(raw_payload=RAW_PAYLOAD, manuscript_text=None)
    proofread = build_proofread_manuscript(
        raw_payload=RAW_PAYLOAD,
        manuscript_text=None,
        mode="raw-priority",
        glossary=glossary,
    )

    draft = build_subtitle_draft(
        raw_payload=RAW_PAYLOAD,
        manuscript_text=None,
        mode="raw-priority",
        glossary=glossary,
        proofread=proofread,
    )

    assert draft.lines
    assert draft.lines[0].source_mode == "raw-priority"
    assert "raw transcript structure" in draft.lines[0].draft_notes
    assert "。" not in draft.lines[0].text
    assert draft.lines[0].style_flags.punctuation_free is True



def test_build_proofread_manuscript_applies_high_confidence_entity_hints_in_raw_priority_mode():
    raw_payload = {
        "text": "他讲到s7，也聊到hps。",
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 2.0,
                "text": "他讲到s7，也聊到hps。",
                "words": [
                    {"id": 1, "start": 0.0, "end": 1.0, "text": "他讲到s7", "punctuation": "，"},
                    {"id": 2, "start": 1.0, "end": 2.0, "text": "也聊到hps", "punctuation": "。"},
                ],
            }
        ],
    }
    manuscript_text = "他讲到 S7，也聊到 HPS。"
    glossary = build_run_glossary(raw_payload=raw_payload, manuscript_text=manuscript_text)

    proofread = build_proofread_manuscript(
        raw_payload=raw_payload,
        manuscript_text=manuscript_text,
        mode="raw-priority",
        glossary=glossary,
    )
    draft = build_subtitle_draft(
        raw_payload=raw_payload,
        manuscript_text=manuscript_text,
        mode="raw-priority",
        glossary=glossary,
        proofread=proofread,
    )

    assert "S7" in proofread.proofread_text
    assert "HPS" in proofread.proofread_text
    assert any("S7" in line.text for line in draft.lines)
    assert any("HPS" in line.text for line in draft.lines)



def test_build_proofread_manuscript_can_absorb_manuscript_backed_entity_recoveries():
    raw_payload = {
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
    }

    proofread = build_proofread_manuscript(
        raw_payload=raw_payload,
        manuscript_text="广汽埃安 S、埃安 Y现在卖得都挺好。",
        mode="raw-priority",
        glossary=RunGlossary(),
    )

    assert "埃安 S、埃安 Y" in proofread.proofread_text
    assert proofread.entity_decisions[0]["final"] == "埃安 S"



def test_build_subtitle_draft_normalizes_mixed_script_boundary_after_punctuation_strip():
    raw_payload = {
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
    }
    manuscript_text = "他造过的 S7，也讲到 HPS。"
    glossary = build_run_glossary(raw_payload=raw_payload, manuscript_text=manuscript_text)
    proofread = build_proofread_manuscript(
        raw_payload=raw_payload,
        manuscript_text=manuscript_text,
        mode="manuscript-priority",
        glossary=glossary,
    )

    draft = build_subtitle_draft(
        raw_payload=raw_payload,
        manuscript_text=manuscript_text,
        mode="manuscript-priority",
        glossary=glossary,
        proofread=proofread,
    )

    assert draft.lines[0].text == "他造过的 S7 也讲到 HPS"



def test_build_subtitle_draft_splits_long_manuscript_lines_to_17_units():
    manuscript_text = "我们中国人喜欢大空间都出了名了广汽和东风难道不知道吗"
    raw_payload = {
        "text": manuscript_text,
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 3.0,
                "text": manuscript_text,
                "words": [
                    {"id": 1, "start": 0.0, "end": 3.0, "text": manuscript_text, "punctuation": ""},
                ],
            }
        ],
    }
    glossary = build_run_glossary(raw_payload=raw_payload, manuscript_text=manuscript_text)
    proofread = build_proofread_manuscript(
        raw_payload=raw_payload,
        manuscript_text=manuscript_text,
        mode="manuscript-priority",
        glossary=glossary,
    )

    draft = build_subtitle_draft(
        raw_payload=raw_payload,
        manuscript_text=manuscript_text,
        mode="manuscript-priority",
        glossary=glossary,
        proofread=proofread,
    )

    assert len(draft.lines) >= 2
    assert all(len(line.text.replace(" ", "")) <= 17 for line in draft.lines)



def test_build_subtitle_draft_keeps_line_ids_contiguous_after_empty_cleaned_lines_are_dropped():
    raw_payload = {
        "text": "第一句。第二句。",
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 2.0,
                "text": "第一句。第二句。",
                "words": [
                    {"id": 1, "start": 0.0, "end": 1.0, "text": "第一句", "punctuation": "。"},
                    {"id": 2, "start": 1.0, "end": 2.0, "text": "第二句", "punctuation": "。"},
                ],
            }
        ],
    }
    proofread = ProofreadManuscript(
        source_text="第一句\n“”\n第二句",
        proofread_text="第一句\n“”\n第二句",
        edit_summary="fixture",
        draft_ready=True,
    )

    draft = build_subtitle_draft(
        raw_payload=raw_payload,
        manuscript_text="第一句\n“”\n第二句",
        mode="manuscript-priority",
        glossary=RunGlossary(),
        proofread=proofread,
    )

    assert [line.line_id for line in draft.lines] == [1, 2]
    assert [line.text for line in draft.lines] == ["第一句", "第二句"]



def test_build_subtitle_draft_keeps_glossary_acronym_intact_at_17_unit_boundary():
    manuscript_text = "如果你 A 阶段发现的问题来不及提交 PPT 恭喜你"
    raw_payload = {
        "text": manuscript_text,
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 3.0,
                "text": manuscript_text,
                "words": [
                    {"id": 1, "start": 0.0, "end": 3.0, "text": manuscript_text, "punctuation": ""},
                ],
            }
        ],
    }
    glossary = build_run_glossary(raw_payload=raw_payload, manuscript_text=manuscript_text)
    proofread = build_proofread_manuscript(
        raw_payload=raw_payload,
        manuscript_text=manuscript_text,
        mode="manuscript-priority",
        glossary=glossary,
    )

    draft = build_subtitle_draft(
        raw_payload=raw_payload,
        manuscript_text=manuscript_text,
        mode="manuscript-priority",
        glossary=glossary,
        proofread=proofread,
    )

    assert [line.text for line in draft.lines] == [
        "如果你 A 阶段发现的问题来不及提交",
        "PPT 恭喜你",
    ]



def test_build_subtitle_draft_keeps_glossary_latin_phrase_intact_at_17_unit_boundary():
    manuscript_text = "如果今天你第一次接触 Claude Code 恭喜你"
    raw_payload = {
        "text": manuscript_text,
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 3.0,
                "text": manuscript_text,
                "words": [
                    {"id": 1, "start": 0.0, "end": 3.0, "text": manuscript_text, "punctuation": ""},
                ],
            }
        ],
    }
    glossary = build_run_glossary(raw_payload=raw_payload, manuscript_text=manuscript_text)
    proofread = build_proofread_manuscript(
        raw_payload=raw_payload,
        manuscript_text=manuscript_text,
        mode="manuscript-priority",
        glossary=glossary,
    )

    draft = build_subtitle_draft(
        raw_payload=raw_payload,
        manuscript_text=manuscript_text,
        mode="manuscript-priority",
        glossary=glossary,
        proofread=proofread,
    )

    assert [line.text for line in draft.lines] == [
        "如果今天你第一次接触",
        "Claude Code 恭喜你",
    ]



def test_build_step2a_artifacts_prefers_auxiliary_llm_in_manuscript_priority_mode(monkeypatch):
    manuscript_text = "今天我们来聊 FunASR。\n还看看埃安 S。"
    glossary = build_run_glossary(raw_payload=RAW_PAYLOAD, manuscript_text=manuscript_text)

    def fake_request_auxiliary_manuscript_draft(**kwargs):
        return {
            "proofread_text": "今天我们来聊 FunASR\n还看看埃安 S",
            "subtitle_lines": ["今天我们来聊 FunASR", "还看看埃安 S"],
            "proofread_confidence": 0.97,
            "semantic_integrity": "high",
            "glossary_safe": True,
            "drafting_warnings": [],
            "draft_notes": ["llm semantic draft"],
            "provider_alias": "deepseek_direct_aux",
            "model": "deepseek-v4-flash",
        }

    monkeypatch.setattr("drafting.request_auxiliary_manuscript_draft", fake_request_auxiliary_manuscript_draft)

    result = build_step2a_artifacts(
        raw_payload=RAW_PAYLOAD,
        manuscript_text=manuscript_text,
        mode="manuscript-priority",
        glossary=glossary,
    )

    assert isinstance(result, Step2ADraftingResult)
    assert result.drafting_mode == "llm-primary"
    assert result.draft_model_provider == "deepseek_direct_aux"
    assert result.draft_model_name == "deepseek-v4-flash"
    assert result.draft_fallback_used is False
    assert result.draft_fallback_reason is None
    assert result.draft_fallback_code is None
    assert result.draft_attempt_count == 1
    assert result.proofread.proofread_confidence == 0.97
    assert result.proofread.proofread_text == "今天我们来聊 FunASR\n还看看埃安 S"
    assert [line.text for line in result.draft.lines] == ["今天我们来聊 FunASR", "还看看埃安 S"]
    assert result.draft.lines[0].draft_notes == ["llm semantic draft"]



def test_build_step2a_artifacts_prefers_auxiliary_llm_in_raw_priority_mode_when_manuscript_exists(monkeypatch):
    manuscript_text = "今天我们来聊 FunASR。\n还看看埃安 S。"
    glossary = build_run_glossary(raw_payload=RAW_PAYLOAD, manuscript_text=manuscript_text)

    def fake_request_auxiliary_manuscript_draft(**kwargs):
        return {
            "proofread_text": "今天我们来聊 FunASR 还看看埃安 S",
            "subtitle_lines": ["今天我们来聊 FunASR", "还看看埃安 S"],
            "proofread_confidence": 0.91,
            "semantic_integrity": "high",
            "glossary_safe": True,
            "drafting_warnings": ["raw-priority local entity recovery only"],
            "draft_notes": ["llm raw-priority draft"],
            "provider_alias": "deepseek_direct_aux",
            "model": "deepseek-v4-flash",
        }

    monkeypatch.setattr("drafting.request_auxiliary_manuscript_draft", fake_request_auxiliary_manuscript_draft)

    result = build_step2a_artifacts(
        raw_payload=RAW_PAYLOAD,
        manuscript_text=manuscript_text,
        mode="raw-priority",
        glossary=glossary,
    )

    assert result.drafting_mode == "llm-primary"
    assert result.draft_model_provider == "deepseek_direct_aux"
    assert result.draft_model_name == "deepseek-v4-flash"
    assert result.draft_fallback_used is False
    assert result.draft_fallback_reason is None
    assert result.draft_fallback_code is None
    assert result.draft_attempt_count == 1
    assert result.proofread.source_text == RAW_PAYLOAD["text"]
    assert result.proofread.proofread_text == "今天我们来聊 FunASR 还看看埃安 S"
    assert result.proofread.drafting_warnings == ["raw-priority local entity recovery only"]
    assert [line.source_mode for line in result.draft.lines] == ["raw-priority", "raw-priority"]
    assert result.draft.lines[0].draft_notes == ["llm raw-priority draft"]



def test_build_step2a_artifacts_marks_manual_review_instead_of_bootstrap_when_auxiliary_draft_fails(monkeypatch):
    manuscript_text = "今天我们来聊 FunASR。\n还看看埃安 S。"
    glossary = build_run_glossary(raw_payload=RAW_PAYLOAD, manuscript_text=manuscript_text)

    def fake_request_auxiliary_manuscript_draft(**kwargs):
        raise RuntimeError("auxiliary timeout")

    monkeypatch.setattr("drafting.request_auxiliary_manuscript_draft", fake_request_auxiliary_manuscript_draft)

    result = build_step2a_artifacts(
        raw_payload=RAW_PAYLOAD,
        manuscript_text=manuscript_text,
        mode="manuscript-priority",
        glossary=glossary,
    )

    assert result.drafting_mode == "manual-review-required"
    assert result.draft_model_provider is None
    assert result.draft_model_name is None
    assert result.draft_fallback_used is False
    assert result.draft_fallback_reason == "auxiliary timeout"
    assert result.draft_fallback_code == "auxiliary_request_failed"
    assert result.draft_attempt_count == 0
    assert result.manual_review_required is True
    assert result.draft.lines == []
    assert result.proofread.draft_ready is False
    assert result.proofread.edit_summary == "manual review required"
    assert result.alert_reasons == ["auxiliary timeout"]



def test_subtitle_draft_exposes_expected_line_fields():
    glossary = build_run_glossary(raw_payload=RAW_PAYLOAD, manuscript_text=None)
    proofread = build_proofread_manuscript(
        raw_payload=RAW_PAYLOAD,
        manuscript_text=None,
        mode="raw-priority",
        glossary=glossary,
    )

    draft = build_subtitle_draft(
        raw_payload=RAW_PAYLOAD,
        manuscript_text=None,
        mode="raw-priority",
        glossary=glossary,
        proofread=proofread,
    )

    line = draft.lines[0]
    assert hasattr(line, "line_id")
    assert hasattr(line, "text")
    assert hasattr(line, "source_mode")
    assert hasattr(line, "draft_notes")
    assert hasattr(line, "style_flags")
    assert hasattr(line, "quality_signals")
    assert hasattr(line, "raw_span_mapping")
