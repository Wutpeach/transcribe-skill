import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from preflight import build_input_preflight
from routing import choose_mode, score_manuscript_similarity, write_mode_decision


RAW_PAYLOAD_STRONG = {
    "text": "今天我们来聊 FunASR，还会看看埃安 S。",
    "segments": [
        {"id": 1, "text": "今天我们来聊 FunASR。", "words": [{"id": 1}, {"id": 2}]},
        {"id": 2, "text": "还会看看埃安 S。", "words": [{"id": 3}, {"id": 4}]},
    ],
}

RAW_PAYLOAD_WEAK = {
    "text": "今天临时闲聊一点别的内容，顺手讲两个完全无关的话题。",
    "segments": [
        {"id": 1, "text": "今天临时闲聊一点别的内容。", "words": [{"id": 1}, {"id": 2}]},
        {"id": 2, "text": "顺手讲两个完全无关的话题。", "words": [{"id": 3}, {"id": 4}]},
    ],
}


def test_score_manuscript_similarity_returns_high_scores_for_close_texts():
    global_similarity, samples = score_manuscript_similarity(
        raw_payload=RAW_PAYLOAD_STRONG,
        manuscript_text="今天我们来聊 FunASR\n还会看看埃安 S",
    )

    assert global_similarity >= 0.9
    assert samples
    assert min(samples) >= 0.85



def test_choose_mode_prefers_manuscript_priority_for_high_similarity_input():
    preflight = build_input_preflight(
        raw_payload=RAW_PAYLOAD_STRONG,
        manuscript_text="今天我们来聊 FunASR\n还会看看埃安 S",
        user_override=None,
    )

    decision = choose_mode(
        preflight=preflight,
        raw_payload=RAW_PAYLOAD_STRONG,
        manuscript_text="今天我们来聊 FunASR\n还会看看埃安 S",
        user_override=None,
    )

    assert decision.mode == "manuscript-priority"
    assert decision.confidence >= 0.85
    assert decision.reasons



def test_choose_mode_prefers_raw_priority_for_missing_manuscript():
    preflight = build_input_preflight(
        raw_payload=RAW_PAYLOAD_STRONG,
        manuscript_text=None,
        user_override=None,
    )

    decision = choose_mode(
        preflight=preflight,
        raw_payload=RAW_PAYLOAD_STRONG,
        manuscript_text=None,
        user_override=None,
    )

    assert decision.mode == "raw-priority"
    assert "manuscript missing or empty" in decision.reasons



def test_choose_mode_prefers_raw_priority_for_weak_similarity_input():
    manuscript_text = "这是后补提纲，和真实音频内容差异很大。"
    preflight = build_input_preflight(
        raw_payload=RAW_PAYLOAD_WEAK,
        manuscript_text=manuscript_text,
        user_override=None,
    )

    decision = choose_mode(
        preflight=preflight,
        raw_payload=RAW_PAYLOAD_WEAK,
        manuscript_text=manuscript_text,
        user_override=None,
    )

    assert decision.mode == "raw-priority"
    assert decision.global_similarity < 0.8
    assert decision.reasons



def test_choose_mode_honors_explicit_override():
    preflight = build_input_preflight(
        raw_payload=RAW_PAYLOAD_WEAK,
        manuscript_text="很差的文稿",
        user_override="manuscript-priority",
    )

    decision = choose_mode(
        preflight=preflight,
        raw_payload=RAW_PAYLOAD_WEAK,
        manuscript_text="很差的文稿",
        user_override="manuscript-priority",
    )

    assert decision.mode == "manuscript-priority"
    assert decision.user_override == "manuscript-priority"
    assert "user override" in decision.reasons



def test_choose_mode_keeps_warning_band_observable():
    raw_payload = {
        "text": "今天我们会聊 FunASR，也会顺带提到一个车型。",
        "segments": [
            {"id": 1, "text": "今天我们会聊 FunASR。", "words": [{"id": 1}, {"id": 2}]},
            {"id": 2, "text": "也会顺带提到一个车型。", "words": [{"id": 3}, {"id": 4}]},
        ],
    }
    manuscript_text = "今天我们会聊 FunASR\n也会提到一个车型"
    preflight = build_input_preflight(
        raw_payload=raw_payload,
        manuscript_text=manuscript_text,
        user_override=None,
    )

    decision = choose_mode(
        preflight=preflight,
        raw_payload=raw_payload,
        manuscript_text=manuscript_text,
        user_override=None,
    )

    assert decision.mode in {"manuscript-priority", "raw-priority"}
    assert 0.0 <= decision.confidence <= 1.0
    assert decision.reasons



def test_choose_mode_defaults_warning_band_to_raw_priority_below_manuscript_local_threshold():
    raw_payload = {
        "text": "今天我们会聊 FunASR，也会顺带提到一个车型。",
        "segments": [
            {"id": 1, "text": "今天我们会聊 FunASR。", "words": [{"id": 1}, {"id": 2}]},
            {"id": 2, "text": "也会顺带提到一个车型。", "words": [{"id": 3}, {"id": 4}]},
        ],
    }
    manuscript_text = "今天我们会聊 FunASR\n还会提到一个案例"
    preflight = build_input_preflight(
        raw_payload=raw_payload,
        manuscript_text=manuscript_text,
        user_override=None,
    )

    decision = choose_mode(
        preflight=preflight,
        raw_payload=raw_payload,
        manuscript_text=manuscript_text,
        user_override=None,
    )

    assert 0.80 <= decision.global_similarity < 0.90
    assert decision.mode == "raw-priority"
    assert "warning-band similarity; using conservative routing" in decision.reasons



def test_write_mode_decision_serializes_json(tmp_path):
    preflight = build_input_preflight(
        raw_payload=RAW_PAYLOAD_STRONG,
        manuscript_text="今天我们来聊 FunASR\n还会看看埃安 S",
        user_override=None,
    )
    decision = choose_mode(
        preflight=preflight,
        raw_payload=RAW_PAYLOAD_STRONG,
        manuscript_text="今天我们来聊 FunASR\n还会看看埃安 S",
        user_override=None,
    )
    output_path = tmp_path / "mode_decision.json"

    write_mode_decision(decision, output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "manuscript-priority"
    assert payload["reasons"]
