from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import request

from auxiliary_config import AgentRuntimeConfig, Step2AAuxiliaryConfig, load_prompt_text, load_step2a_auxiliary_config


@dataclass
class AuxiliaryCorrection:
    kind: str
    original: str
    corrected: str
    confidence: float


class AuxiliaryGlossaryError(RuntimeError):
    pass


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    return ""


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise AuxiliaryGlossaryError("Auxiliary response was empty")
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise AuxiliaryGlossaryError("Auxiliary response did not contain a JSON object")
        payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise AuxiliaryGlossaryError("Auxiliary response JSON must be an object")
    return payload


def _validate_item(kind: str, item: Any) -> AuxiliaryCorrection:
    if not isinstance(item, dict):
        raise AuxiliaryGlossaryError(f"Invalid {kind} correction item")
    original = str(item.get("original") or "").strip()
    corrected = str(item.get("corrected") or "").strip()
    confidence_raw = item.get("confidence")
    if not original or not corrected:
        raise AuxiliaryGlossaryError(f"Missing original/corrected fields in {kind} correction")
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError) as exc:
        raise AuxiliaryGlossaryError(f"Invalid confidence in {kind} correction") from exc
    return AuxiliaryCorrection(kind=kind, original=original, corrected=corrected, confidence=confidence)


def _should_keep_correction(correction: AuxiliaryCorrection) -> bool:
    if correction.original == correction.corrected and correction.corrected.isascii() is False:
        return False
    return True


def _dedupe_corrections(corrections: list[AuxiliaryCorrection]) -> list[AuxiliaryCorrection]:
    deduped: list[AuxiliaryCorrection] = []
    seen: set[tuple[str, str, str]] = set()
    for correction in corrections:
        if not _should_keep_correction(correction):
            continue
        key = (correction.kind, correction.original, correction.corrected)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(correction)
    return deduped


def _parse_corrections(response_payload: dict[str, Any]) -> list[AuxiliaryCorrection]:
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AuxiliaryGlossaryError("Auxiliary response missing choices")
    message = (choices[0] or {}).get("message") or {}
    content_text = _message_content_to_text(message.get("content"))
    payload = _extract_json_object(content_text)

    corrections: list[AuxiliaryCorrection] = []
    for kind in ("entities", "terms"):
        items = payload.get(kind) or []
        if not isinstance(items, list):
            raise AuxiliaryGlossaryError(f"Auxiliary payload field `{kind}` must be a list")
        normalized_kind = "entity" if kind == "entities" else "term"
        for item in items:
            corrections.append(_validate_item(normalized_kind, item))
    return _dedupe_corrections(corrections)


def _build_prompt(*, raw_payload: dict, manuscript_text: str, config: Step2AAuxiliaryConfig) -> str:
    sections: list[str] = []
    for task in ("term_extraction", "entity_recovery"):
        if task in config.prompt_paths:
            sections.append(load_prompt_text(config, task).strip())
    guidance = "\n\n".join(section for section in sections if section)
    raw_text = str(raw_payload.get("text") or "").strip()
    return (
        f"{guidance}\n\n"
        "请只返回 JSON 对象，格式如下：\n"
        "{\n"
        '  "entities": [{"original": "...", "corrected": "...", "confidence": 0.0}],\n'
        '  "terms": [{"original": "...", "corrected": "...", "confidence": 0.0}]\n'
        "}\n\n"
        "约束：\n"
        "- 只返回高置信修正\n"
        "- 不要输出解释\n"
        "- 如果没有内容，返回空数组\n\n"
        f"MANUSCRIPT:\n{manuscript_text.strip()}\n\n"
        f"RAW:\n{raw_text}\n"
    )


def request_auxiliary_glossary_corrections(
    *,
    raw_payload: dict,
    manuscript_text: str | None,
    skill_dir: Path | None = None,
    hermes_home: Path | None = None,
    agent_runtime: AgentRuntimeConfig | None = None,
    urlopen=request.urlopen,
) -> list[AuxiliaryCorrection]:
    if not manuscript_text or not manuscript_text.strip():
        return []

    config = load_step2a_auxiliary_config(
        skill_dir=Path(skill_dir or Path(__file__).resolve().parents[1]),
        hermes_home=hermes_home,
        agent_runtime=agent_runtime,
    )
    if not config.enabled:
        return []
    if not config.api_key:
        raise AuxiliaryGlossaryError(f"Auxiliary API key `{config.api_key_env}` is not available")
    if config.api_mode != "chat_completions":
        raise AuxiliaryGlossaryError(f"Unsupported auxiliary api_mode `{config.api_mode}`")

    prompt = _build_prompt(raw_payload=raw_payload, manuscript_text=manuscript_text, config=config)
    body = json.dumps(
        {
            "model": config.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a careful subtitle preprocessing assistant. Return strict JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    endpoint = config.base_url.rstrip("/") + "/chat/completions"
    req = request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        },
        method="POST",
    )
    with urlopen(req, timeout=config.timeout) as response:
        response_payload = json.loads(response.read().decode("utf-8"))
    return _parse_corrections(response_payload)
