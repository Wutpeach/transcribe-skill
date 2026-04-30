import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from auxiliary_config import AgentRuntimeConfig
from auxiliary_glossary import AuxiliaryGlossaryError, _build_prompt, request_auxiliary_glossary_corrections


class DummyResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def _runtime() -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        provider_name="openclaw",
        base_url="http://127.0.0.1:3000/v1",
        api_key="sk-openclaw",
        api_key_env="OPENCLAW_API_KEY",
        api_mode="chat_completions",
    )


def test_build_prompt_includes_anti_duplication_guidance(tmp_path):
    skill_dir = Path(__file__).resolve().parents[1]

    from auxiliary_config import load_step2a_auxiliary_config

    config = load_step2a_auxiliary_config(skill_dir=skill_dir, agent_runtime=_runtime())
    prompt = _build_prompt(
        raw_payload={"text": "好啊，你写一份详细的一份详细的 ppt", "segments": []},
        manuscript_text="好啊，你写一份详细的 PPT",
        config=config,
    )

    assert "连续重复" in prompt
    assert "冗余" in prompt


def test_request_auxiliary_glossary_corrections_parses_entities_and_terms(tmp_path):
    skill_dir = tmp_path / "transcribe"
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
tasks = ["term_extraction", "entity_recovery"]
""".strip(),
        encoding="utf-8",
    )
    (skill_dir / "prompts" / "understanding" / "term_extraction.md").write_text("term prompt", encoding="utf-8")
    (skill_dir / "prompts" / "understanding" / "entity_recovery.md").write_text("entity prompt", encoding="utf-8")

    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text(
        """
providers:
  newapi:
    name: newapi
    base_url: http://127.0.0.1:3000/v1
    key_env: NEWAPI_API_KEY
    api_mode: codex_responses
""".strip(),
        encoding="utf-8",
    )
    (hermes_home / ".env").write_text("NEWAPI_API_KEY=***", encoding="utf-8")

    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "entities": [
                                {"original": "ins", "corrected": "埃安 S", "confidence": 0.95}
                            ],
                            "terms": [
                                {"original": "自动化", "corrected": "自働化", "confidence": 0.98}
                            ],
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }

    corrections = request_auxiliary_glossary_corrections(
        raw_payload={"text": "即使广汽自己有 ins、iny，也提到自动化。", "segments": []},
        manuscript_text="即使广汽自己有埃安 S、埃安 Y，也提到自働化。",
        skill_dir=skill_dir,
        hermes_home=hermes_home,
        urlopen=lambda req, timeout=0: DummyResponse(json.dumps(payload).encode("utf-8")),
    )

    assert [(item.kind, item.original, item.corrected) for item in corrections] == [
        ("entity", "ins", "埃安 S"),
        ("term", "自动化", "自働化"),
    ]


def test_request_auxiliary_glossary_corrections_filters_identity_noise_but_keeps_case_normalization(tmp_path):
    skill_dir = tmp_path / "transcribe"
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
tasks = ["term_extraction", "entity_recovery"]
""".strip(),
        encoding="utf-8",
    )
    (skill_dir / "prompts" / "understanding" / "term_extraction.md").write_text("term prompt", encoding="utf-8")
    (skill_dir / "prompts" / "understanding" / "entity_recovery.md").write_text("entity prompt", encoding="utf-8")
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text(
        """
providers:
  newapi:
    name: newapi
    base_url: http://127.0.0.1:3000/v1
    key_env: NEWAPI_API_KEY
""".strip(),
        encoding="utf-8",
    )
    (hermes_home / ".env").write_text("NEWAPI_API_KEY=***", encoding="utf-8")

    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "entities": [],
                            "terms": [
                                {"original": "广汽", "corrected": "广汽", "confidence": 1.0},
                                {"original": "hps", "corrected": "HPS", "confidence": 0.95},
                            ],
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }

    corrections = request_auxiliary_glossary_corrections(
        raw_payload={"text": "广汽和 hps", "segments": []},
        manuscript_text="广汽和 HPS",
        skill_dir=skill_dir,
        hermes_home=hermes_home,
        urlopen=lambda req, timeout=0: DummyResponse(json.dumps(payload).encode("utf-8")),
    )

    assert [(item.original, item.corrected) for item in corrections] == [("hps", "HPS")]


def test_request_auxiliary_glossary_corrections_rejects_invalid_contract(tmp_path):
    skill_dir = tmp_path / "transcribe"
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
tasks = ["term_extraction", "entity_recovery"]
""".strip(),
        encoding="utf-8",
    )
    (skill_dir / "prompts" / "understanding" / "term_extraction.md").write_text("term prompt", encoding="utf-8")
    (skill_dir / "prompts" / "understanding" / "entity_recovery.md").write_text("entity prompt", encoding="utf-8")
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text(
        """
providers:
  newapi:
    name: newapi
    base_url: http://127.0.0.1:3000/v1
    key_env: NEWAPI_API_KEY
""".strip(),
        encoding="utf-8",
    )
    (hermes_home / ".env").write_text("NEWAPI_API_KEY=***", encoding="utf-8")

    payload = {"choices": [{"message": {"content": '{"entities": [{"original": "ins"}]}'}}]}

    try:
        request_auxiliary_glossary_corrections(
            raw_payload={"text": "ins", "segments": []},
            manuscript_text="埃安 S",
            skill_dir=skill_dir,
            hermes_home=hermes_home,
            urlopen=lambda req, timeout=0: DummyResponse(json.dumps(payload).encode("utf-8")),
        )
    except AuxiliaryGlossaryError as exc:
        assert "invalid" in str(exc).lower() or "missing" in str(exc).lower()
    else:
        raise AssertionError("Expected AuxiliaryGlossaryError for invalid contract")
