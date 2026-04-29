from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

try:
    import tomllib  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    tomllib = None


DEFAULT_FUNASR_MODEL = "fun-asr"
DEFAULT_FUNASR_BASE_HTTP_API_URL = "https://dashscope.aliyuncs.com/api/v1"
DEFAULT_FUNASR_KEY_ENV = "DASHSCOPE_API_KEY"
COMMON_FUNASR_KEY_ENVS = (
    "DASHSCOPE_API_KEY",
    "BAILIAN_API_KEY",
    "FUNASR_API_KEY",
    "ALIYUN_BAILIAN_API_KEY",
)


@dataclass
class ResolvedFunASRConfig:
    api_key: str
    model: str
    base_http_api_url: str
    language_hints: list[str] | None
    key_env: str


def _parse_toml_scalar(raw: str):
    text = raw.strip()
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    if text.startswith("[") and text.endswith("]"):
        return ast.literal_eval(text)
    if text.startswith('"') and text.endswith('"'):
        return ast.literal_eval(text)
    if text.startswith("'") and text.endswith("'"):
        return ast.literal_eval(text)
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _fallback_toml_loads(content: str) -> dict:
    root: dict = {}
    current = root
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = root
            for part in line[1:-1].split("."):
                current = current.setdefault(part, {})
            continue
        key, value = line.split("=", 1)
        current[key.strip()] = _parse_toml_scalar(value)
    return root


def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    content = path.read_text(encoding="utf-8")
    if tomllib is not None:
        return tomllib.loads(content)
    return _fallback_toml_loads(content)


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def _as_string_list(value: object) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else None
    if isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value if str(item).strip()]
        return items or None
    return None


def _non_empty_string(value: object, default: str) -> str:
    text = str(value or "").strip()
    return text or default


def resolve_funasr_config(
    *,
    skill_dir: Path,
    cli_api_key: str | None,
    cli_model: str | None,
    cli_base_http_api_url: str | None,
    cli_language_hints: list[str] | None,
    hermes_home: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> ResolvedFunASRConfig:
    skill_dir = Path(skill_dir).expanduser().resolve()
    hermes_home = Path(hermes_home or Path("~/.hermes").expanduser()).expanduser().resolve()
    env_map = dict(os.environ if env is None else env)

    shared_cfg = ((_read_toml(skill_dir / "config" / "funasr.toml")).get("funasr") or {})
    local_cfg = ((_read_toml(skill_dir / "config" / "funasr.local.toml")).get("funasr") or {})
    local_env = _read_dotenv(skill_dir / ".env.local")
    hermes_env = _read_dotenv(hermes_home / ".env")

    key_env = _non_empty_string(local_cfg.get("key_env") or shared_cfg.get("key_env"), DEFAULT_FUNASR_KEY_ENV)

    api_key_candidates: list[str] = []
    if cli_api_key:
        api_key_candidates.append(cli_api_key)
    local_api_key = str(local_cfg.get("api_key") or "").strip()
    if local_api_key:
        api_key_candidates.append(local_api_key)

    env_names = [key_env, *COMMON_FUNASR_KEY_ENVS]
    seen_env_names: set[str] = set()
    for env_name in env_names:
        name = str(env_name or "").strip()
        if not name or name in seen_env_names:
            continue
        seen_env_names.add(name)
        for source in (local_env, env_map, hermes_env):
            value = str(source.get(name) or "").strip()
            if value:
                api_key_candidates.append(value)

    api_key = next((candidate for candidate in api_key_candidates if candidate), "")

    model = _non_empty_string(cli_model or local_cfg.get("model") or shared_cfg.get("model"), DEFAULT_FUNASR_MODEL)
    base_http_api_url = _non_empty_string(
        cli_base_http_api_url or local_cfg.get("base_http_api_url") or shared_cfg.get("base_http_api_url"),
        DEFAULT_FUNASR_BASE_HTTP_API_URL,
    )
    language_hints = _as_string_list(
        cli_language_hints if cli_language_hints is not None else local_cfg.get("language_hints", shared_cfg.get("language_hints"))
    )

    return ResolvedFunASRConfig(
        api_key=api_key,
        model=model,
        base_http_api_url=base_http_api_url,
        language_hints=language_hints,
        key_env=key_env,
    )
