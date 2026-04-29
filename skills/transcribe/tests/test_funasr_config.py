import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from funasr_config import resolve_funasr_config



def test_resolve_funasr_config_accepts_funasr_api_key_from_skill_local_env(tmp_path):
    skill_dir = tmp_path / "skill"
    config_dir = skill_dir / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "funasr.toml").write_text(
        """
[funasr]
model = "fun-asr-plus"
base_http_api_url = "https://dashscope.example/api/v1"
key_env = "DASHSCOPE_API_KEY"
""".strip(),
        encoding="utf-8",
    )
    (skill_dir / ".env.local").write_text("FUNASR_API_KEY=sk-funasr-local\n", encoding="utf-8")

    config = resolve_funasr_config(
        skill_dir=skill_dir,
        cli_api_key=None,
        cli_model=None,
        cli_base_http_api_url=None,
        cli_language_hints=None,
        env={},
    )

    assert config.api_key == "sk-funasr-local"
    assert config.model == "fun-asr-plus"
    assert config.base_http_api_url == "https://dashscope.example/api/v1"
    assert config.key_env == "DASHSCOPE_API_KEY"



def test_resolve_funasr_config_keeps_hermes_env_as_fallback(tmp_path):
    skill_dir = tmp_path / "skill"
    config_dir = skill_dir / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "funasr.toml").write_text(
        """
[funasr]
key_env = "DASHSCOPE_API_KEY"
""".strip(),
        encoding="utf-8",
    )

    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    (hermes_home / ".env").write_text("DASHSCOPE_API_KEY=sk-hermes-fallback\n", encoding="utf-8")

    config = resolve_funasr_config(
        skill_dir=skill_dir,
        cli_api_key=None,
        cli_model=None,
        cli_base_http_api_url=None,
        cli_language_hints=None,
        hermes_home=hermes_home,
        env={},
    )

    assert config.api_key == "sk-hermes-fallback"
