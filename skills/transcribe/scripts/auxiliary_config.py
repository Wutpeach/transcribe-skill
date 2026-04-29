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
    content = path.read_text(encoding="utf-8")
    if tomllib is not None:
        return tomllib.loads(content)
    return _fallback_toml_loads(content)


def _read_yaml(path: Path) -> dict:
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


def _load_step_auxiliary_config(*, skill_dir: Path, stage_name: str, hermes_home: Path | None = None) -> Step2AAuxiliaryConfig:
    skill_dir = Path(skill_dir).expanduser().resolve()
    hermes_home = Path(hermes_home or Path("~/.hermes").expanduser()).expanduser().resolve()

    models_cfg = _read_toml(_require_file(skill_dir / "config" / "models.toml", "models config"))
    transcribe_cfg = _read_toml(_require_file(skill_dir / "config" / "transcribe.toml", "transcribe config"))
    hermes_cfg = _read_yaml(_require_file(hermes_home / "config.yaml", "Hermes config"))
    hermes_env = _read_dotenv(hermes_home / ".env")

    stage_cfg = (((transcribe_cfg.get(stage_name) or {}).get("auxiliary_model")) or {})
    model_ref = str(stage_cfg.get("model_ref") or "").strip()
    if not model_ref:
        raise AuxiliaryConfigError(f"config/transcribe.toml is missing {stage_name}.auxiliary_model.model_ref")

    models = models_cfg.get("models") or {}
    model_cfg = models.get(model_ref) or {}
    if not model_cfg:
        raise AuxiliaryConfigError(f"Unknown model_ref `{model_ref}` in config/transcribe.toml")

    providers = models_cfg.get("providers") or {}
    provider_ref = str(model_cfg.get("provider") or "").strip()
    provider_cfg = providers.get(provider_ref) or {}
    if not provider_cfg:
        raise AuxiliaryConfigError(f"Unknown provider `{provider_ref}` in config/models.toml")

    if str(provider_cfg.get("source") or "").strip() != "hermes":
        raise AuxiliaryConfigError(f"Unsupported provider source for `{provider_ref}`")

    source_provider_alias = str(provider_cfg.get("provider_alias") or "").strip()
    if not source_provider_alias:
        raise AuxiliaryConfigError(f"Provider `{provider_ref}` is missing provider_alias")

    hermes_provider = ((hermes_cfg.get("providers") or {}).get(source_provider_alias)) or {}
    if not hermes_provider:
        raise AuxiliaryConfigError(f"Hermes provider `{source_provider_alias}` not found in {hermes_home / 'config.yaml'}")

    api_key_env = str(hermes_provider.get("key_env") or "").strip()
    api_key = os.environ.get(api_key_env, "") if api_key_env else ""
    if not api_key and api_key_env:
        api_key = hermes_env.get(api_key_env, "")

    default_prompt_dir = "prompts/understanding" if stage_name == "step2a" else f"prompts/{stage_name}"
    prompt_dir = skill_dir / str(stage_cfg.get("prompt_dir") or default_prompt_dir)
    tasks = [str(item).strip() for item in (stage_cfg.get("tasks") or []) if str(item).strip()]
    prompt_paths = {task: _require_file(prompt_dir / f"{task}.md", f"prompt for task `{task}`") for task in tasks}

    return Step2AAuxiliaryConfig(
        enabled=bool(stage_cfg.get("enabled", False)),
        provider_alias=source_provider_alias,
        source_provider_name=str(hermes_provider.get("name") or source_provider_alias),
        model=str(model_cfg.get("model") or "").strip(),
        api_mode=str(model_cfg.get("api_mode") or hermes_provider.get("api_mode") or "").strip(),
        base_url=str(hermes_provider.get("base_url") or "").strip(),
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
