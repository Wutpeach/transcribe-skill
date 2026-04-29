from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

try:
    import tomllib  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    tomllib = None


DEFAULT_AUXILIARY_BASE_URL_ENV = "AUXILIARY_BASE_URL"
DEFAULT_AUXILIARY_API_KEY_ENV = "AUXILIARY_API_KEY"
DEFAULT_AUXILIARY_API_MODE = "chat_completions"


@dataclass
class Step2AAuxiliaryConfig:
    enabled: bool
    provider_alias: str
    source_provider_name: str
    model: str
    api_mode: str
    base_url: str
    api_key_env: str
    api_key: str
    temperature: float
    max_tokens: int
    timeout: int
    prompt_dir: Path
    prompt_paths: dict[str, Path]


class AuxiliaryConfigError(RuntimeError):
    pass


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


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _require_file(path: Path, description: str) -> Path:
    if not path.exists():
        raise AuxiliaryConfigError(f"Missing {description}: {path}")
    return path


def _non_empty(value: object) -> str:
    return str(value or "").strip()


def _resolve_env(name: str, *sources: dict[str, str]) -> str:
    key = _non_empty(name)
    if not key:
        return ""
    for source in sources:
        value = _non_empty(source.get(key))
        if value:
            return value
    return ""


def _resolve_provider(
    *,
    provider_ref: str,
    providers: dict,
    model_cfg: dict,
    skill_dir: Path,
    hermes_home: Path,
    local_env: dict[str, str],
    env_map: dict[str, str],
    local_aux_cfg: dict,
    seen: set[str],
) -> tuple[str, str, str, str]:
    if provider_ref in seen:
        raise AuxiliaryConfigError(f"Provider fallback loop detected for `{provider_ref}`")
    seen.add(provider_ref)

    provider_cfg = providers.get(provider_ref) or {}
    if not provider_cfg:
        raise AuxiliaryConfigError(f"Unknown provider `{provider_ref}` in config/models.toml")

    source = _non_empty(provider_cfg.get("source"))
    if source in {"openai_compatible", "env"}:
        base_url_env = _non_empty(provider_cfg.get("base_url_env")) or DEFAULT_AUXILIARY_BASE_URL_ENV
        api_key_env = _non_empty(provider_cfg.get("api_key_env")) or DEFAULT_AUXILIARY_API_KEY_ENV
        provider_name = _non_empty(provider_cfg.get("provider_name")) or provider_ref
        api_mode = _non_empty(model_cfg.get("api_mode") or provider_cfg.get("api_mode")) or DEFAULT_AUXILIARY_API_MODE

        base_url = _non_empty(local_aux_cfg.get("base_url")) or _resolve_env(base_url_env, local_env, env_map)
        api_key = _non_empty(local_aux_cfg.get("api_key")) or _resolve_env(api_key_env, local_env, env_map)

        if base_url and api_key:
            return provider_ref, provider_name, api_mode, base_url, api_key_env, api_key

        fallback_provider = _non_empty(provider_cfg.get("fallback_provider"))
        if fallback_provider:
            return _resolve_provider(
                provider_ref=fallback_provider,
                providers=providers,
                model_cfg=model_cfg,
                skill_dir=skill_dir,
                hermes_home=hermes_home,
                local_env=local_env,
                env_map=env_map,
                local_aux_cfg=local_aux_cfg,
                seen=seen,
            )

        missing = []
        if not base_url:
            missing.append(base_url_env)
        if not api_key:
            missing.append(api_key_env)
        joined = ", ".join(missing) if missing else provider_ref
        raise AuxiliaryConfigError(f"Missing auxiliary configuration: {joined}")

    if source == "hermes":
        source_provider_alias = _non_empty(provider_cfg.get("provider_alias"))
        if not source_provider_alias:
            raise AuxiliaryConfigError(f"Provider `{provider_ref}` is missing provider_alias")

        hermes_cfg = _read_yaml(_require_file(hermes_home / "config.yaml", "Hermes config"))
        hermes_env = _read_dotenv(hermes_home / ".env")
        hermes_provider = ((hermes_cfg.get("providers") or {}).get(source_provider_alias)) or {}
        if not hermes_provider:
            raise AuxiliaryConfigError(f"Hermes provider `{source_provider_alias}` not found in {hermes_home / 'config.yaml'}")

        api_key_env = _non_empty(hermes_provider.get("key_env"))
        api_key = _resolve_env(api_key_env, local_env, env_map, hermes_env) if api_key_env else ""
        api_mode = _non_empty(model_cfg.get("api_mode") or hermes_provider.get("api_mode")) or DEFAULT_AUXILIARY_API_MODE
        base_url = _non_empty(hermes_provider.get("base_url"))
        provider_name = _non_empty(hermes_provider.get("name")) or source_provider_alias
        return source_provider_alias, provider_name, api_mode, base_url, api_key_env, api_key

    raise AuxiliaryConfigError(f"Unsupported provider source for `{provider_ref}`")


def _load_step_auxiliary_config(*, skill_dir: Path, stage_name: str, hermes_home: Path | None = None) -> Step2AAuxiliaryConfig:
    skill_dir = Path(skill_dir).expanduser().resolve()
    hermes_home = Path(hermes_home or Path("~/.hermes").expanduser()).expanduser().resolve()
    env_map = dict(os.environ)
    local_env = _read_dotenv(skill_dir / ".env.local")
    local_aux_cfg = ((_read_toml(skill_dir / "config" / "auxiliary.local.toml")).get("auxiliary") or {})

    models_cfg = _read_toml(_require_file(skill_dir / "config" / "models.toml", "models config"))
    transcribe_cfg = _read_toml(_require_file(skill_dir / "config" / "transcribe.toml", "transcribe config"))

    stage_cfg = (((transcribe_cfg.get(stage_name) or {}).get("auxiliary_model")) or {})
    model_ref = _non_empty(stage_cfg.get("model_ref"))
    if not model_ref:
        raise AuxiliaryConfigError(f"config/transcribe.toml is missing {stage_name}.auxiliary_model.model_ref")

    models = models_cfg.get("models") or {}
    model_cfg = models.get(model_ref) or {}
    if not model_cfg:
        raise AuxiliaryConfigError(f"Unknown model_ref `{model_ref}` in config/transcribe.toml")

    providers = models_cfg.get("providers") or {}
    provider_ref = _non_empty(model_cfg.get("provider"))
    provider_alias, provider_name, api_mode, base_url, api_key_env, api_key = _resolve_provider(
        provider_ref=provider_ref,
        providers=providers,
        model_cfg=model_cfg,
        skill_dir=skill_dir,
        hermes_home=hermes_home,
        local_env=local_env,
        env_map=env_map,
        local_aux_cfg=local_aux_cfg,
        seen=set(),
    )

    default_prompt_dir = "prompts/understanding" if stage_name == "step2a" else f"prompts/{stage_name}"
    prompt_dir = skill_dir / str(stage_cfg.get("prompt_dir") or default_prompt_dir)
    tasks = [str(item).strip() for item in (stage_cfg.get("tasks") or []) if str(item).strip()]
    prompt_paths = {task: _require_file(prompt_dir / f"{task}.md", f"prompt for task `{task}`") for task in tasks}

    return Step2AAuxiliaryConfig(
        enabled=bool(stage_cfg.get("enabled", False)),
        provider_alias=provider_alias,
        source_provider_name=provider_name,
        model=_non_empty(model_cfg.get("model")),
        api_mode=api_mode,
        base_url=base_url,
        api_key_env=api_key_env,
        api_key=api_key,
        temperature=float(model_cfg.get("temperature", 0.0)),
        max_tokens=int(model_cfg.get("max_tokens", 0)),
        timeout=int(model_cfg.get("timeout", 60)),
        prompt_dir=prompt_dir,
        prompt_paths=prompt_paths,
    )


def load_step2a_auxiliary_config(*, skill_dir: Path, hermes_home: Path | None = None) -> Step2AAuxiliaryConfig:
    return _load_step_auxiliary_config(skill_dir=skill_dir, stage_name="step2a", hermes_home=hermes_home)


def load_prompt_text(config: Step2AAuxiliaryConfig, task: str) -> str:
    prompt_path = config.prompt_paths[task]
    return prompt_path.read_text(encoding="utf-8")
