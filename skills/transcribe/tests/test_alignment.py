import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from alignment import _apply_same_token_collapse_guard, align_draft_to_raw_tokens, aligned_segments_to_cues, write_aligned_segments
from contracts import AlignedSegment, DraftLine, RunGlossary, SubtitleDraft
from segmentation import recover_raw_payload_for_alignment


RAW_PAYLOAD = {
    "text": "今天我们来聊FunASR。还看看埃安S。",
    "segments": [
        {
            "id": 1,
            "start": 0.0,
            "end": 1.0,
            "text": "今天我们来聊FunASR。",
            "words": [
                {"id": 1, "start": 0.0, "end": 0.5, "text": "今天我们来聊", "punctuation": ""},
                {"id": 2, "start": 0.5, "end": 1.0, "text": "FunASR", "punctuation": "。"},
            ],
        },
        {
            "id": 2,
            "start": 1.0,
            "end": 2.0,
            "text": "还看看埃安S。",
            "words": [
                {"id": 3, "start": 1.0, "end": 1.5, "text": "还看看", "punctuation": ""},
                {"id": 4, "start": 1.5, "end": 2.0, "text": "埃安S", "punctuation": "。"},
            ],
        },
    ],
}


def test_alignment_maps_manuscript_priority_lines_to_exact_token_spans():
    draft = SubtitleDraft(
        lines=[
            DraftLine(line_id=1, text="今天我们来聊 FunASR。", source_mode="manuscript-priority"),
            DraftLine(line_id=2, text="还看看埃安 S。", source_mode="manuscript-priority"),
        ]
    )

    segments, summary = align_draft_to_raw_tokens(
        draft=draft,
        raw_payload=RAW_PAYLOAD,
        glossary=RunGlossary(),
    )

    assert segments[0].raw_token_start_index == 0
    assert segments[0].raw_token_end_index == 1
    assert segments[1].raw_token_start_index == 2
    assert segments[1].raw_token_end_index == 3
    assert summary.line_count == 2



def test_alignment_maps_raw_priority_lines_from_raw_structure():
    draft = SubtitleDraft(lines=[DraftLine(line_id=1, text="今天我们来聊FunASR。", source_mode="raw-priority")])

    segments, summary = align_draft_to_raw_tokens(
        draft=draft,
        raw_payload=RAW_PAYLOAD,
        glossary=RunGlossary(),
    )

    assert len(segments) == 1
    assert segments[0].text == "今天我们来聊FunASR。"
    assert summary.mean_alignment_score > 0.9



def test_alignment_keeps_protected_glossary_entity_intact_across_tokens():
    raw_payload = {
        "text": "岚图 Free很能打。",
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 1.5,
                "text": "岚图 Free很能打。",
                "words": [
                    {"id": 1, "start": 0.0, "end": 0.4, "text": "岚图", "punctuation": ""},
                    {"id": 2, "start": 0.4, "end": 0.9, "text": " Free", "punctuation": ""},
                    {"id": 3, "start": 0.9, "end": 1.5, "text": "很能打", "punctuation": "。"},
                ],
            }
        ],
    }
    draft = SubtitleDraft(lines=[DraftLine(line_id=1, text="岚图 Free", source_mode="manuscript-priority")])
    glossary = RunGlossary()

    segments, _summary = align_draft_to_raw_tokens(
        draft=draft,
        raw_payload=raw_payload,
        glossary=glossary,
    )

    assert segments[0].raw_token_start_index == 0
    assert segments[0].raw_token_end_index == 1



def test_alignment_interpolates_when_two_lines_split_one_raw_token():
    raw_payload = {
        "text": "今天我们来聊FunASR",
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 1.0,
                "text": "今天我们来聊FunASR",
                "words": [
                    {"id": 1, "start": 0.0, "end": 1.0, "text": "今天我们来聊FunASR", "punctuation": ""},
                ],
            }
        ],
    }
    draft = SubtitleDraft(
        lines=[
            DraftLine(line_id=1, text="今天我们来聊", source_mode="manuscript-priority"),
            DraftLine(line_id=2, text="FunASR", source_mode="manuscript-priority"),
        ]
    )

    segments, _summary = align_draft_to_raw_tokens(
        draft=draft,
        raw_payload=raw_payload,
        glossary=RunGlossary(),
    )

    assert segments[0].raw_token_start_index == 0
    assert segments[0].raw_token_end_index == 0
    assert segments[1].raw_token_start_index == 0
    assert segments[1].raw_token_end_index == 0
    assert segments[0].split_points
    assert segments[0].end <= segments[1].start



def test_alignment_marks_low_confidence_regions_with_warning():
    draft = SubtitleDraft(lines=[DraftLine(line_id=1, text="完全不一样的句子", source_mode="manuscript-priority")])

    segments, summary = align_draft_to_raw_tokens(
        draft=draft,
        raw_payload=RAW_PAYLOAD,
        glossary=RunGlossary(),
    )

    assert segments[0].warnings
    assert segments[0].alignment_score < 0.85
    assert summary.low_confidence_count == 1



def test_same_token_collapse_guard_merges_low_confidence_tail_run_into_previous_anchor():
    guarded = _apply_same_token_collapse_guard(
        [
            AlignedSegment(
                line_id=1,
                text="好了这就是今天的所有内容",
                start=525.10,
                end=526.68,
                raw_token_start_index=1779,
                raw_token_end_index=1784,
                split_points=[],
                alignment_score=0.0,
                protected_entities=[],
                warnings=["low alignment confidence"],
            ),
            AlignedSegment(
                line_id=2,
                text="如果大家喜欢我们的视频",
                start=526.52,
                end=526.68,
                raw_token_start_index=1784,
                raw_token_end_index=1784,
                split_points=[],
                alignment_score=0.0,
                protected_entities=[],
                warnings=["low alignment confidence"],
            ),
            AlignedSegment(
                line_id=3,
                text="欢迎点赞转发一键三连",
                start=526.52,
                end=526.68,
                raw_token_start_index=1784,
                raw_token_end_index=1784,
                split_points=[],
                alignment_score=0.0,
                protected_entities=[],
                warnings=["low alignment confidence"],
            ),
            AlignedSegment(
                line_id=4,
                text="我们下期再见啦",
                start=526.52,
                end=526.68,
                raw_token_start_index=1784,
                raw_token_end_index=1784,
                split_points=[],
                alignment_score=0.07,
                protected_entities=[],
                warnings=["low alignment confidence"],
            ),
        ]
    )

    assert len(guarded) == 1
    assert guarded[0].line_id == 1
    assert guarded[0].text == "好了这就是今天的所有内容如果大家喜欢我们的视频欢迎点赞转发一键三连我们下期再见啦"
    assert guarded[0].start == 525.10
    assert guarded[0].end == 526.68
    assert "timing collapse merged 2-4" in guarded[0].warnings



def test_write_aligned_segments_serializes_json_and_cues(tmp_path):
    draft = SubtitleDraft(lines=[DraftLine(line_id=1, text="今天我们来聊 FunASR。", source_mode="manuscript-priority")])
    segments, summary = align_draft_to_raw_tokens(draft=draft, raw_payload=RAW_PAYLOAD, glossary=RunGlossary())
    output_path = tmp_path / "aligned_segments.json"

    write_aligned_segments(segments=segments, summary=summary, output_path=output_path)
    cues = aligned_segments_to_cues(segments)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["schema"] == "transcribe.aligned_segments.v2"
    assert payload["source_stage"] == "step-2b-alignment"
    assert payload["summary"]["line_count"] == 1
    assert payload["segments"][0]["text"] == "今天我们来聊 FunASR。"
    assert cues[0].text == "今天我们来聊 FunASR。"



def test_alignment_uses_recovered_entities_before_matching():
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
    recovered_payload, _recoveries = recover_raw_payload_for_alignment(
        raw_payload=raw_payload,
        manuscript_text="广汽埃安 S、埃安 Y现在卖得都挺好。",
    )
    draft = SubtitleDraft(lines=[DraftLine(line_id=1, text="广汽埃安 S、埃安 Y现在卖得都挺好。", source_mode="manuscript-priority")])

    segments, summary = align_draft_to_raw_tokens(
        draft=draft,
        raw_payload=recovered_payload,
        glossary=RunGlossary(),
    )

    assert segments[0].alignment_score > 0.9
    assert summary.low_confidence_count == 0
