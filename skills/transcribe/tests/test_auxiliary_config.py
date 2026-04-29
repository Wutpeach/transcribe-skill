import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from auxiliary_config import load_prompt_text, load_step2a_auxiliary_config


def test_load_step2a_auxiliary_config_resolves_newapi_provider_and_model_defaults(tmp_path, monkeypatch):
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
tasks = ["term_extraction", "entity_recovery", "manuscript_understanding", "deduplication"]
""".strip(),
        encoding="utf-8",
    )
    for task in ["term_extraction", "entity_recovery", "manuscript_understanding", "deduplication"]:
        (skill_dir / "prompts" / "understanding" / f"{task}.md").write_text(f"# {task}\n", encoding="utf-8")

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
    monkeypatch.delenv("NEWAPI_API_KEY", raising=False)

    config = load_step2a_auxiliary_config(skill_dir=skill_dir, hermes_home=hermes_home)

    assert config.enabled is True
    assert config.provider_alias == "newapi"
    assert config.source_provider_name == "newapi"
    assert config.base_url == "http://127.0.0.1:3000/v1"
    assert config.api_key_env == "NEWAPI_API_KEY"
    assert config.api_key == "***"
    assert config.model == "deepseek-v4-flash"
    assert config.api_mode == "chat_completions"
    assert config.temperature == 0.2
    assert config.max_tokens == 32768
    assert config.timeout == 180
    assert set(config.prompt_paths) == {
        "term_extraction",
        "entity_recovery",
        "manuscript_understanding",
        "deduplication",
    }
    assert config.prompt_paths["term_extraction"].name == "term_extraction.md"


def test_load_prompt_text_reads_prompt_file_from_resolved_config(tmp_path):
    prompt_path = tmp_path / "term_extraction.md"
    prompt_path.write_text("You extract terms.", encoding="utf-8")

    class StubConfig:
        prompt_paths = {"term_extraction": prompt_path}

    assert load_prompt_text(StubConfig(), "term_extraction") == "You extract terms."
