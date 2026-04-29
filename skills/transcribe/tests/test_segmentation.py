import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from contracts import GlossaryEntry, RunGlossary
from segmentation import build_script_pass_result, build_script_pass_srt, cues_to_srt_text, recover_raw_payload_for_alignment


def test_segmentation_keeps_protected_mixed_script_phrase_together():
    raw_payload = {
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 4.0,
                "text": "东风有岚图 Free 这些量大管饱车型。",
                "words": [
                    {"id": 1, "start": 0.0, "end": 0.5, "text": "东风有", "punctuation": ""},
                    {"id": 2, "start": 0.5, "end": 1.0, "text": "岚图", "punctuation": ""},
                    {"id": 3, "start": 1.0, "end": 1.4, "text": " Free", "punctuation": ""},
                    {"id": 4, "start": 1.4, "end": 2.0, "text": "这些量大管饱车型", "punctuation": "。"},
                ],
            }
        ]
    }
    glossary = RunGlossary(terms=[GlossaryEntry(term="岚图 Free", aliases=["岚图free"])])

    cues = build_script_pass_srt(raw_payload=raw_payload, glossary=glossary)
    srt_text = cues_to_srt_text(cues)

    assert "岚图 Free" in srt_text
    assert "岚图\nFree" not in srt_text
    spoken = re.sub(r"\s+", "", raw_payload["segments"][0]["text"])
    dialogue = re.sub(r"\s+", "", "".join(cue.text.replace("\n", "") for cue in cues))
    assert dialogue == spoken


def test_segmentation_merges_micro_tail_cue_back_into_neighbor():
    raw_payload = {
        "segments": [
            {
                "id": 1,
                "start": 0.0,
                "end": 2.08,
                "text": "子豪说到这个的时候啊自己都绷不住了。",
                "words": [
                    {"id": 1, "start": 0.0, "end": 2.0, "text": "子豪说到这个的时候啊自己都绷不住", "punctuation": ""},
                    {"id": 2, "start": 2.0, "end": 2.08, "text": "了", "punctuation": "。"},
                ],
            }
        ]
    }

    cues = build_script_pass_srt(raw_payload=raw_payload, glossary=RunGlossary())

    assert len(cues) == 1
    assert cues[0].start == 0.0
    assert cues[0].end == 2.08
    assert cues[0].text == "子豪说到这个的时候啊自己都绷不住了。"


def test_manuscript_backed_entity_recovery_does_not_duplicate_preceding_phrase_for_ppt():
    raw_payload = {
        "segments": [
            {
                "id": 33,
                "start": 161.0,
                "end": 165.0,
                "text": "好啊，你写一份详细的ppt，仔细描述问题，",
                "words": [
                    {"id": 7, "start": 161.0, "end": 161.1, "text": "好", "punctuation": ""},
                    {"id": 8, "start": 161.1, "end": 161.3, "text": "啊", "punctuation": "，"},
                    {"id": 9, "start": 161.3, "end": 161.5, "text": "你", "punctuation": ""},
                    {"id": 10, "start": 161.5, "end": 161.7, "text": "写", "punctuation": ""},
                    {"id": 11, "start": 161.7, "end": 161.9, "text": "一份", "punctuation": ""},
                    {"id": 12, "start": 161.9, "end": 162.2, "text": "详细的", "punctuation": ""},
                    {"id": 13, "start": 162.2, "end": 162.5, "text": "ppt", "punctuation": "，"},
                    {"id": 14, "start": 162.5, "end": 163.0, "text": "仔细", "punctuation": ""},
                    {"id": 15, "start": 163.0, "end": 163.4, "text": "描述", "punctuation": ""},
                    {"id": 16, "start": 163.4, "end": 164.0, "text": "问题", "punctuation": "，"},
                ],
            }
        ]
    }

    recovered_payload, recoveries = recover_raw_payload_for_alignment(
        raw_payload=raw_payload,
        manuscript_text="好啊，你写一份详细的 PPT，仔细描述问题，",
    )

    assert [item.recovered_term for item in recoveries] == ["PPT"]
    assert recovered_payload["segments"][0]["text"] == "好啊，你写一份详细的PPT，仔细描述问题，"


def test_segmentation_recovers_manuscript_backed_key_entities_from_suspicious_asr_fragments():
    raw_payload = {
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
        ]
    }

    result = build_script_pass_result(
        raw_payload=raw_payload,
        glossary=RunGlossary(),
        manuscript_text="广汽埃安 S、埃安 Y现在卖得都挺好。",
    )
    dialogue = re.sub(r"\s+", "", "".join(cue.text for cue in result.cues))

    assert dialogue == "广汽埃安S、埃安Y现在卖得都挺好。"
    assert [item.recovered_term for item in result.entity_recoveries] == ["埃安 S", "埃安 Y"]
    assert [item.raw_fragment for item in result.entity_recoveries] == ["ins", "iny"]
