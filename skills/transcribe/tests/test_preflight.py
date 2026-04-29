import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from preflight import build_input_preflight, normalize_manuscript_text, write_input_preflight


RAW_PAYLOAD = {
    "schema": "transcribe.raw.v3",
    "text": "嗯 今天我们来聊 FunASR。啊 然后看一下埃安 S。",
    "segments": [
        {
            "id": 1,
            "start": 0.0,
            "end": 1.0,
            "text": "嗯 今天我们来聊 FunASR。",
            "words": [
                {"id": 1, "start": 0.0, "end": 0.2, "text": "嗯", "punctuation": ""},
                {"id": 2, "start": 0.2, "end": 1.0, "text": "今天我们来聊 FunASR", "punctuation": "。"},
            ],
        },
        {
            "id": 2,
            "start": 1.0,
            "end": 2.0,
            "text": "啊 然后看一下埃安 S。",
            "words": [
                {"id": 3, "start": 1.0, "end": 1.2, "text": "啊", "punctuation": ""},
                {"id": 4, "start": 1.2, "end": 2.0, "text": "然后看一下埃安 S", "punctuation": "。"},
            ],
        },
    ],
}


def test_normalize_manuscript_text_collapses_whitespace_and_trims():
    assert normalize_manuscript_text("  第一行\n\n 第二行  ") == "第一行\n第二行"



def test_build_input_preflight_marks_present_manuscript_and_keeps_lengths():
    artifact = build_input_preflight(
        raw_payload=RAW_PAYLOAD,
        manuscript_text=" 第一行\n第二行 ",
        user_override="auto",
    )

    assert artifact.audio_ok is True
    assert artifact.manuscript_present is True
    assert artifact.manuscript_length == len(" 第一行\n第二行 ")
    assert artifact.normalized_manuscript_length == len("第一行\n第二行")
    assert artifact.user_override == "auto"



def test_build_input_preflight_warns_on_effectively_empty_manuscript():
    artifact = build_input_preflight(
        raw_payload=RAW_PAYLOAD,
        manuscript_text="  \n   ",
        user_override=None,
    )

    assert artifact.manuscript_present is False
    assert "empty manuscript after normalization" in artifact.warnings



def test_build_input_preflight_marks_absent_manuscript_when_none():
    artifact = build_input_preflight(
        raw_payload=RAW_PAYLOAD,
        manuscript_text=None,
        user_override=None,
    )

    assert artifact.manuscript_present is False
    assert artifact.manuscript_length == 0
    assert artifact.normalized_manuscript_length == 0



def test_build_input_preflight_collects_speaker_and_style_signals():
    artifact = build_input_preflight(
        raw_payload=RAW_PAYLOAD,
        manuscript_text="今天我们来聊 FunASR\n然后看一下埃安 S",
        user_override=None,
    )

    assert artifact.speaker_complexity_signals["segment_count"] == 2
    assert artifact.speaker_complexity_signals["word_count"] == 4
    assert artifact.style_volatility_signals["filler_count"] == 2
    assert artifact.style_volatility_signals["terminal_punctuation_count"] == 2



def test_write_input_preflight_serializes_json(tmp_path):
    artifact = build_input_preflight(
        raw_payload=RAW_PAYLOAD,
        manuscript_text="今天我们来聊 FunASR",
        user_override="raw-priority",
    )
    output_path = tmp_path / "input_preflight.json"

    write_input_preflight(artifact, output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["audio_ok"] is True
    assert payload["user_override"] == "raw-priority"
    assert payload["speaker_complexity_signals"]["segment_count"] == 2
