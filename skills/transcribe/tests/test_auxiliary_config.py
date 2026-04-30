import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from auxiliary_config import AgentRuntimeConfig, load_prompt_text, load_step2a_auxiliary_config


TASKS = ["term_extraction", "entity_recovery", "manuscript_understanding", "deduplication"]


def _write_shared_skill_fixture(skill_dir: Path) -> None:
    (skill_dir / "config").mkdir(parents=True)
    (skill_dir / "prompts" / "understanding").mkdir(parents=True)
    (skill_dir / "config" / "models.toml").write_text(
        """
[providers.auxiliary_openai_compatible]
source = "openai_compatible"
provider_name = "openai-compatible"
base_url_env = "AUXILIARY_BASE_URL"
api_key_env = "AUXILIARY_API_KEY"
api_mode = "chat_completions"
fallback_provider = "current_live_agent"

[providers.current_live_agent]
source = "agent"
provider_name = "current-live-agent"

[models.step2a_understanding]
provider = "auxiliary_openai_compatible"
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
    for task in TASKS:
        (skill_dir / "prompts" / "understanding" / f"{task}.md").write_text(f"# {task}\n", encoding="utf-8")


def test_load_step2a_auxiliary_config_prefers_skill_local_openai_compatible_env(tmp_path, monkeypatch):
    skill_dir = tmp_path / "transcribe"
    _write_shared_skill_fixture(skill_dir)
    (skill_dir / ".env.local").write_text(
        "AUXILIARY_BASE_URL=https://api.deepseek.com/v1\nAUXILIARY_API_KEY=sk-local\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("AUXILIARY_BASE_URL", raising=False)
    monkeypatch.delenv("AUXILIARY_API_KEY", raising=False)

    config = load_step2a_auxiliary_config(skill_dir=skill_dir)

    assert config.enabled is True
    assert config.provider_alias == "auxiliary_openai_compatible"
    assert config.source_provider_name == "openai-compatible"
    assert config.base_url == "https://api.deepseek.com/v1"
    assert config.api_key_env == "AUXILIARY_API_KEY"
    assert config.api_key == "sk-local"
    assert config.model == "deepseek-v4-flash"
    assert config.api_mode == "chat_completions"
    assert config.temperature == 0.2
    assert config.max_tokens == 32768
    assert config.timeout == 180
    assert set(config.prompt_paths) == set(TASKS)


def test_load_step2a_auxiliary_config_prefers_auxiliary_local_toml_over_env(tmp_path, monkeypatch):
    skill_dir = tmp_path / "transcribe"
    _write_shared_skill_fixture(skill_dir)
    (skill_dir / ".env.local").write_text(
        "AUXILIARY_BASE_URL=https://api.example.com/v1\nAUXILIARY_API_KEY=sk-env\n",
        encoding="utf-8",
    )
    (skill_dir / "config" / "auxiliary.local.toml").write_text(
        """
[auxiliary]
base_url = "https://api.deepseek.com/v1"
api_key = "sk-toml"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.delenv("AUXILIARY_BASE_URL", raising=False)
    monkeypatch.delenv("AUXILIARY_API_KEY", raising=False)

    config = load_step2a_auxiliary_config(skill_dir=skill_dir)

    assert config.provider_alias == "auxiliary_openai_compatible"
    assert config.base_url == "https://api.deepseek.com/v1"
    assert config.api_key == "sk-toml"
    assert config.model == "deepseek-v4-flash"


def test_load_step2a_auxiliary_config_falls_back_to_injected_current_live_agent_runtime_when_generic_env_is_missing(tmp_path, monkeypatch):
    skill_dir = tmp_path / "transcribe"
    _write_shared_skill_fixture(skill_dir)

    monkeypatch.delenv("AUXILIARY_BASE_URL", raising=False)
    monkeypatch.delenv("AUXILIARY_API_KEY", raising=False)
    monkeypatch.delenv("CURRENT_LIVE_AGENT_BASE_URL", raising=False)
    monkeypatch.delenv("CURRENT_LIVE_AGENT_API_KEY", raising=False)

    config = load_step2a_auxiliary_config(
        skill_dir=skill_dir,
        agent_runtime=AgentRuntimeConfig(
            provider_name="openclaw",
            base_url="http://127.0.0.1:3000/v1",
            api_key="sk-openclaw",
            api_key_env="OPENCLAW_API_KEY",
            api_mode="responses",
        ),
    )

    assert config.provider_alias == "current_live_agent"
    assert config.source_provider_name == "current-live-agent"
    assert config.base_url == "http://127.0.0.1:3000/v1"
    assert config.api_key_env == "OPENCLAW_API_KEY"
    assert config.api_key == "sk-openclaw"
    assert config.model == "deepseek-v4-flash"
    assert config.api_mode == "chat_completions"


def test_load_step2a_auxiliary_config_falls_back_to_current_live_agent_env_when_runtime_is_not_injected(tmp_path, monkeypatch):
    skill_dir = tmp_path / "transcribe"
    _write_shared_skill_fixture(skill_dir)

    monkeypatch.delenv("AUXILIARY_BASE_URL", raising=False)
    monkeypatch.delenv("AUXILIARY_API_KEY", raising=False)
    monkeypatch.setenv("CURRENT_LIVE_AGENT_BASE_URL", "http://127.0.0.1:9000/v1")
    monkeypatch.setenv("CURRENT_LIVE_AGENT_API_KEY", "sk-live-agent")
    monkeypatch.setenv("CURRENT_LIVE_AGENT_API_MODE", "responses")
    monkeypatch.setenv("CURRENT_LIVE_AGENT_PROVIDER_NAME", "codex-cli")

    config = load_step2a_auxiliary_config(skill_dir=skill_dir)

    assert config.provider_alias == "current_live_agent"
    assert config.source_provider_name == "current-live-agent"
    assert config.base_url == "http://127.0.0.1:9000/v1"
    assert config.api_key_env == "CURRENT_LIVE_AGENT_API_KEY"
    assert config.api_key == "sk-live-agent"
    assert config.model == "deepseek-v4-flash"
    assert config.api_mode == "chat_completions"


def test_load_prompt_text_reads_prompt_file_from_resolved_config(tmp_path):
    prompt_path = tmp_path / "term_extraction.md"
    prompt_path.write_text("You extract terms.", encoding="utf-8")

    class StubConfig:
        prompt_paths = {"term_extraction": prompt_path}

    assert load_prompt_text(StubConfig(), "term_extraction") == "You extract terms."
