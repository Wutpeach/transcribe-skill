import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from auxiliary_drafting import AuxiliaryDraftingError, request_auxiliary_manuscript_draft


class DummyResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def _write_step2a_auxiliary_fixture(skill_dir: Path, hermes_home: Path) -> None:
    (skill_dir / "config").mkdir(parents=True)
    (skill_dir / "prompts" / "understanding").mkdir(parents=True)
    (skill_dir / "config" / "models.toml").write_text(
        """
[providers.hermes_newapi]
provider_alias = "newapi"
source = "hermes"

[models.step2a_understanding]
provider = "hermes_newapi"
model = "deepseek-v4-flash"
api_mode = "chat_completions"
temperature = 0.2
max_tokens = 32768
timeout = 180
""".strip(),
        encoding="utf-8",
    )
    (skill_dir / "config" / "transcribe.toml").write_text(
        """
[step2a.auxiliary_model]
enabled = true
model_ref = "step2a_understanding"
prompt_dir = "prompts/understanding"
tasks = ["manuscript_understanding", "deduplication"]
""".strip(),
        encoding="utf-8",
    )
    (skill_dir / "prompts" / "understanding" / "manuscript_understanding.md").write_text(
        "understanding prompt",
        encoding="utf-8",
    )
    (skill_dir / "prompts" / "understanding" / "deduplication.md").write_text(
        "deduplication prompt",
        encoding="utf-8",
    )
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text(
        """
providers:
  newapi:
    name: newapi
    base_url: http://127.0.0.1:3000/v1
    key_env: NEWAPI_API_KEY
    api_mode: chat_completions
""".strip(),
        encoding="utf-8",
    )
    (hermes_home / ".env").write_text("NEWAPI_API_KEY=***", encoding="utf-8")


def test_request_auxiliary_manuscript_draft_sends_deepseek_v4_thinking_json_request(tmp_path):
    skill_dir = tmp_path / "transcribe"
    hermes_home = tmp_path / ".hermes"
    _write_step2a_auxiliary_fixture(skill_dir, hermes_home)

    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout=0):
        captured["timeout"] = timeout
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "proofread_text": "今天我们来聊 FunASR",
                                "subtitle_lines": ["今天我们来聊 FunASR"],
                                "proofread_confidence": 0.97,
                                "semantic_integrity": "high",
                                "glossary_safe": True,
                                "drafting_warnings": [],
                                "draft_notes": ["llm semantic draft"],
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }
        return DummyResponse(json.dumps(payload).encode("utf-8"))

    request_auxiliary_manuscript_draft(
        raw_payload={"text": "今天我们来聊funasr。", "segments": []},
        manuscript_text="今天我们来聊 FunASR。",
        mode="manuscript-priority",
        skill_dir=skill_dir,
        hermes_home=hermes_home,
        urlopen=fake_urlopen,
    )

    body = captured["body"]

    assert captured["timeout"] == 180
    assert captured["url"] == "http://127.0.0.1:3000/v1/chat/completions"
    assert body["model"] == "deepseek-v4-flash"
    assert body["thinking"] == {"type": "enabled"}
    assert body["reasoning_effort"] == "high"
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_tokens"] == 32768
    assert "temperature" not in body


def test_request_auxiliary_manuscript_draft_adds_raw_priority_audio_anchor_guidance(tmp_path):
    skill_dir = tmp_path / "transcribe"
    hermes_home = tmp_path / ".hermes"
    _write_step2a_auxiliary_fixture(skill_dir, hermes_home)

    captured: dict[str, object] = {}

    def fake_urlopen(req, timeout=0):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "proofread_text": "用了欣旺达电池的电池我可不买",
                                "subtitle_lines": ["用了欣旺达电池的", "电池我可不买"],
                                "proofread_confidence": 0.97,
                                "semantic_integrity": "high",
                                "glossary_safe": True,
                                "drafting_warnings": [],
                                "draft_notes": ["llm semantic draft"],
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }
        return DummyResponse(json.dumps(payload).encode("utf-8"))

    request_auxiliary_manuscript_draft(
        raw_payload={"text": "用了欣旺达电池的电池我可不买", "segments": []},
        manuscript_text="用了欣旺达的电车我不买",
        mode="raw-priority",
        skill_dir=skill_dir,
        hermes_home=hermes_home,
        urlopen=fake_urlopen,
    )

    prompt = captured["body"]["messages"][1]["content"]
    assert "raw-priority 音频锚定保留规则" in prompt
    assert "保留 raw_text 里能直接支撑事实的核心名词和重复强调" in prompt
    assert "电池的电池" in prompt


def test_request_auxiliary_manuscript_draft_retries_with_tail_drift_feedback(tmp_path):
    skill_dir = tmp_path / "transcribe"
    hermes_home = tmp_path / ".hermes"
    _write_step2a_auxiliary_fixture(skill_dir, hermes_home)

    raw_payload = {
        "text": "但或许从这件事开始 人们对于欣旺达的评价可以变得不那么负面了吧 好了这就是今天的所有内容 如果大家喜欢我们的视频 我们下期再见啦",
        "segments": [
            {"text": "但或许从这件事开始 人们对于欣旺达的评价可以变得不那么负面了吧", "words": [{"text": "但或许从这件事开始", "punctuation": ""}]},
            {"text": "好了这就是今天的所有内容", "words": [{"text": "好了这就是今天的所有内容", "punctuation": ""}]},
            {"text": "如果大家喜欢我们的视频", "words": [{"text": "如果大家喜欢我们的视频", "punctuation": ""}]},
            {"text": "我们下期再见啦", "words": [{"text": "我们下期再见啦", "punctuation": ""}]},
        ],
    }
    manuscript_text = (
        "但或许从这件事开始，人们对欣旺达的评价可以变得不再那么负面了吧。\n"
        "但如果欣旺达想要摆脱之前的负面口碑，赢得更大的市场，靠低价来卷终归不是长久之道，未来技术才是唯一真理。\n"
        "好了，这就是今天的所有内容，如果大家喜欢我们的视频，我们下期再见啦。"
    )

    responses = [
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "proofread_text": "但或许从这件事开始 人们对欣旺达的评价可以变得不再那么负面了吧 但如果欣旺达想要摆脱之前的负面口碑 赢得更大的市场 靠低价来卷终归不是长久之道 未来技术才是唯一真理 好了这就是今天的所有内容 如果大家喜欢我们的视频 我们下期再见啦",
                                "subtitle_lines": [
                                    "但或许从这件事开始",
                                    "人们对欣旺达的评价",
                                    "可以变得不再那么负面了吧",
                                    "但如果欣旺达想要摆脱",
                                    "之前的负面口碑",
                                    "赢得更大的市场",
                                    "靠低价来卷终归不是长久之道",
                                    "未来技术才是唯一真理",
                                    "好了这就是今天的所有内容",
                                    "如果大家喜欢我们的视频",
                                    "我们下期再见啦",
                                ],
                                "proofread_confidence": 0.95,
                                "semantic_integrity": "high",
                                "glossary_safe": True,
                                "drafting_warnings": [],
                                "draft_notes": ["llm semantic draft"],
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "proofread_text": "但或许从这件事开始 人们对欣旺达的评价可以变得不再那么负面了吧 好了这就是今天的所有内容 如果大家喜欢我们的视频 我们下期再见啦",
                                "subtitle_lines": [
                                    "但或许从这件事开始",
                                    "人们对欣旺达的评价",
                                    "可以变得不再那么负面了吧",
                                    "好了这就是今天的所有内容",
                                    "如果大家喜欢我们的视频",
                                    "我们下期再见啦",
                                ],
                                "proofread_confidence": 0.97,
                                "semantic_integrity": "high",
                                "glossary_safe": True,
                                "drafting_warnings": [],
                                "draft_notes": ["llm semantic draft"],
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        },
    ]

    prompts: list[str] = []
    state = {"calls": 0}

    def fake_urlopen(req, timeout=0):
        prompts.append(json.loads(req.data.decode("utf-8"))["messages"][1]["content"])
        index = state["calls"]
        state["calls"] += 1
        return DummyResponse(json.dumps(responses[index]).encode("utf-8"))

    result = request_auxiliary_manuscript_draft(
        raw_payload=raw_payload,
        manuscript_text=manuscript_text,
        mode="raw-priority",
        skill_dir=skill_dir,
        hermes_home=hermes_home,
        urlopen=fake_urlopen,
    )

    assert state["calls"] == 2
    assert "Step 2A drift guard" in prompts[1]
    assert "Tail drift detected in raw-priority output" in prompts[1]
    assert result["subtitle_lines"] == [
        "但或许从这件事开始",
        "人们对欣旺达的评价",
        "可以变得不再那么负面了吧",
        "好了这就是今天的所有内容",
        "如果大家喜欢我们的视频",
        "我们下期再见啦",
    ]
    assert result["attempt_count"] == 2


def test_request_auxiliary_manuscript_draft_parses_json_from_reasoning_content_when_content_empty(tmp_path):
    skill_dir = tmp_path / "transcribe"
    hermes_home = tmp_path / ".hermes"
    _write_step2a_auxiliary_fixture(skill_dir, hermes_home)

    payload = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": "",
                    "reasoning_content": "先想一下\n{\"proofread_text\":\"今天我们来聊 FunASR\",\"subtitle_lines\":[\"今天我们来聊 FunASR\"],\"proofread_confidence\":0.97,\"semantic_integrity\":\"high\",\"glossary_safe\":true,\"drafting_warnings\":[],\"draft_notes\":[\"llm semantic draft\"]}",
                },
            }
        ]
    }

    result = request_auxiliary_manuscript_draft(
        raw_payload={"text": "今天我们来聊funasr。", "segments": []},
        manuscript_text="今天我们来聊 FunASR。",
        mode="manuscript-priority",
        skill_dir=skill_dir,
        hermes_home=hermes_home,
        urlopen=lambda req, timeout=0: DummyResponse(json.dumps(payload).encode("utf-8")),
    )

    assert result["subtitle_lines"] == ["今天我们来聊 FunASR"]


def test_request_auxiliary_manuscript_draft_reports_length_exhaustion_when_content_missing(tmp_path):
    skill_dir = tmp_path / "transcribe"
    hermes_home = tmp_path / ".hermes"
    _write_step2a_auxiliary_fixture(skill_dir, hermes_home)

    payload = {
        "choices": [
            {
                "finish_reason": "length",
                "message": {
                    "content": "",
                    "reasoning_content": "这里全是推理过程 还没有最终 JSON",
                },
            }
        ]
    }

    with pytest.raises(AuxiliaryDraftingError, match="finish_reason=length"):
        request_auxiliary_manuscript_draft(
            raw_payload={"text": "今天我们来聊funasr。", "segments": []},
            manuscript_text="今天我们来聊 FunASR。",
            mode="manuscript-priority",
            skill_dir=skill_dir,
            hermes_home=hermes_home,
            urlopen=lambda req, timeout=0: DummyResponse(json.dumps(payload).encode("utf-8")),
        )


def test_request_auxiliary_manuscript_draft_retries_once_after_invalid_contract(tmp_path):
    skill_dir = tmp_path / "transcribe"
    hermes_home = tmp_path / ".hermes"
    _write_step2a_auxiliary_fixture(skill_dir, hermes_home)

    responses = [
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "proofread_text": "今天我们来聊 FunASR",
                                "subtitle_lines": ["今天我们来聊 FunASR。"],
                                "proofread_confidence": 0.97,
                                "semantic_integrity": "high",
                                "glossary_safe": True,
                                "drafting_warnings": [],
                                "draft_notes": ["llm semantic draft"],
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "proofread_text": "今天我们来聊 FunASR",
                                "subtitle_lines": ["今天我们来聊 FunASR"],
                                "proofread_confidence": 0.97,
                                "semantic_integrity": "high",
                                "glossary_safe": True,
                                "drafting_warnings": [],
                                "draft_notes": ["llm semantic draft"],
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        },
    ]

    state = {"calls": 0}

    def fake_urlopen(req, timeout=0):
        index = state["calls"]
        state["calls"] += 1
        return DummyResponse(json.dumps(responses[index]).encode("utf-8"))

    result = request_auxiliary_manuscript_draft(
        raw_payload={"text": "今天我们来聊funasr。", "segments": []},
        manuscript_text="今天我们来聊 FunASR。",
        mode="manuscript-priority",
        skill_dir=skill_dir,
        hermes_home=hermes_home,
        urlopen=fake_urlopen,
    )

    assert state["calls"] == 1
    assert result["proofread_text"] == "今天我们来聊 FunASR"
    assert result["subtitle_lines"] == ["今天我们来聊 FunASR。"]
    assert result["attempt_count"] == 1
    assert result["drafting_warnings"] == ["contract alert: subtitle_lines[1] contains punctuation"]


def test_request_auxiliary_manuscript_draft_rejects_punctuated_subtitle_lines(tmp_path):
    skill_dir = tmp_path / "transcribe"
    hermes_home = tmp_path / ".hermes"
    _write_step2a_auxiliary_fixture(skill_dir, hermes_home)

    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "proofread_text": "今天我们来聊 FunASR",
                            "subtitle_lines": ["今天我们来聊 FunASR。"],
                            "proofread_confidence": 0.97,
                            "semantic_integrity": "high",
                            "glossary_safe": True,
                            "drafting_warnings": [],
                            "draft_notes": ["llm semantic draft"],
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }

    result = request_auxiliary_manuscript_draft(
        raw_payload={"text": "今天我们来聊funasr。", "segments": []},
        manuscript_text="今天我们来聊 FunASR。",
        mode="manuscript-priority",
        skill_dir=skill_dir,
        hermes_home=hermes_home,
        urlopen=lambda req, timeout=0: DummyResponse(json.dumps(payload).encode("utf-8")),
    )

    assert result["subtitle_lines"] == ["今天我们来聊 FunASR。"]
    assert result["drafting_warnings"] == ["contract alert: subtitle_lines[1] contains punctuation"]



def test_request_auxiliary_manuscript_draft_rejects_subtitle_lines_over_17_units(tmp_path):
    skill_dir = tmp_path / "transcribe"
    hermes_home = tmp_path / ".hermes"
    _write_step2a_auxiliary_fixture(skill_dir, hermes_home)

    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "proofread_text": "我们中国人喜欢大空间都出了名了",
                            "subtitle_lines": ["我们中国人喜欢大空间都出了名了对吧啊"],
                            "proofread_confidence": 0.97,
                            "semantic_integrity": "high",
                            "glossary_safe": True,
                            "drafting_warnings": [],
                            "draft_notes": ["llm semantic draft"],
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }

    result = request_auxiliary_manuscript_draft(
        raw_payload={"text": "我们中国人喜欢大空间都出了名的。", "segments": []},
        manuscript_text="我们中国人喜欢大空间都出了名了。",
        mode="manuscript-priority",
        skill_dir=skill_dir,
        hermes_home=hermes_home,
        urlopen=lambda req, timeout=0: DummyResponse(json.dumps(payload).encode("utf-8")),
    )

    assert result["subtitle_lines"] == ["我们中国人喜欢大空间都出了名了对吧啊"]
    assert result["drafting_warnings"] == ["contract alert: subtitle_lines[1] exceeds 17 display units"]



def test_request_auxiliary_manuscript_draft_rejects_out_of_range_confidence(tmp_path):
    skill_dir = tmp_path / "transcribe"
    hermes_home = tmp_path / ".hermes"
    _write_step2a_auxiliary_fixture(skill_dir, hermes_home)

    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "proofread_text": "今天我们来聊 FunASR",
                            "subtitle_lines": ["今天我们来聊 FunASR"],
                            "proofread_confidence": 1.5,
                            "semantic_integrity": "high",
                            "glossary_safe": True,
                            "drafting_warnings": [],
                            "draft_notes": ["llm semantic draft"],
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }

    with pytest.raises(AuxiliaryDraftingError, match="proofread_confidence"):
        request_auxiliary_manuscript_draft(
            raw_payload={"text": "今天我们来聊funasr。", "segments": []},
            manuscript_text="今天我们来聊 FunASR。",
            mode="manuscript-priority",
            skill_dir=skill_dir,
            hermes_home=hermes_home,
            urlopen=lambda req, timeout=0: DummyResponse(json.dumps(payload).encode("utf-8")),
        )
