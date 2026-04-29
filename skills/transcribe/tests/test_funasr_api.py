import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from funasr_api import FunASRApiConfig, run_funasr_api_for_transcribe, normalize_bailian_payload


def test_normalize_bailian_payload_produces_raw_v2_shape():
    payload = {
        "file_url": "https://example.com/audio.wav",
        "properties": {"original_duration_in_milliseconds": 3834},
        "transcripts": [
            {
                "text": "hello world，这里是阿里巴巴语音实验室。",
                "sentences": [
                    {
                        "begin_time": 600,
                        "end_time": 3520,
                        "text": "hello world，这里是阿里巴巴语音实验室。",
                        "words": [
                            {"begin_time": 600, "end_time": 1040, "text": "hello", "punctuation": ""},
                            {"begin_time": 1040, "end_time": 1280, "text": " world", "punctuation": "，"},
                            {"begin_time": 1360, "end_time": 1880, "text": "这里是", "punctuation": ""},
                            {"begin_time": 1880, "end_time": 2520, "text": "阿里巴巴", "punctuation": ""},
                            {"begin_time": 2520, "end_time": 2840, "text": "语音", "punctuation": ""},
                            {"begin_time": 2840, "end_time": 3520, "text": "实验室", "punctuation": "。"},
                        ],
                    }
                ],
            }
        ],
    }

    normalized = normalize_bailian_payload(payload)

    assert normalized["schema"] == "transcribe.raw.v3"
    assert normalized["backend"] == "funasr-api"
    assert normalized["vendor"] == "bailian.fun-asr"
    assert normalized["text"] == "hello world，这里是阿里巴巴语音实验室。"
    assert len(normalized["segments"]) == 1
    segment = normalized["segments"][0]
    assert segment["text"] == "hello world，这里是阿里巴巴语音实验室。"
    assert segment["start"] == 0.6
    assert segment["end"] == 3.52
    assert len(segment["words"]) == 6
    assert segment["words"][1]["punctuation"] == "，"


def test_run_funasr_api_for_transcribe_writes_vendor_and_raw_json():
    payload = {
        "transcripts": [
            {
                "text": "第一句。",
                "sentences": [
                    {
                        "begin_time": 0,
                        "end_time": 1200,
                        "text": "第一句。",
                        "words": [
                            {"begin_time": 0, "end_time": 600, "text": "第一", "punctuation": ""},
                            {"begin_time": 600, "end_time": 1200, "text": "句", "punctuation": "。"},
                        ],
                    }
                ],
            }
        ]
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        audio_path = tmp_path / "sample.wav"
        audio_path.write_bytes(b"RIFFfake")
        run_dir = tmp_path / "run"

        with patch("funasr_api._upload_local_file", return_value={"file_id": "file-123", "url": "https://uploaded.example/audio.wav"}), \
             patch("funasr_api._submit_transcription_task", return_value="task-123"), \
             patch("funasr_api._wait_for_task_result", return_value={"results": [{"subtask_status": "SUCCEEDED", "transcription_url": "https://result.example/output.json"}]}), \
             patch("funasr_api._download_json_payload", return_value=payload):
            result = run_funasr_api_for_transcribe(
                local_audio_path=audio_path,
                run_dir=run_dir,
                config=FunASRApiConfig(api_key="sk-test"),
            )

        assert result.vendor_json_path.exists()
        assert result.raw_json_path.exists()
        vendor_payload = json.loads(result.vendor_json_path.read_text(encoding="utf-8"))
        raw_payload = json.loads(result.raw_json_path.read_text(encoding="utf-8"))
        assert vendor_payload == payload
        assert raw_payload["text"] == "第一句。"
