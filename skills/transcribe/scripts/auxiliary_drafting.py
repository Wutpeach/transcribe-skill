from __future__ import annotations

import json
import math
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib import request

from auxiliary_config import Step2AAuxiliaryConfig, load_prompt_text, load_step2a_auxiliary_config
from contracts import MAX_SUBTITLE_LINE_UNITS, count_text_punctuation_violations, subtitle_display_length


class AuxiliaryDraftingError(RuntimeError):
    def __init__(self, message: str, *, code: str = "auxiliary_contract_failed", attempt_count: int = 0):
        super().__init__(message)
        self.code = code
        self.attempt_count = attempt_count


_MAX_AUXILIARY_DRAFT_ATTEMPTS = 2
_SIMILARITY_PUNCT_RE = re.compile(r"[\s\.,，。！？!?:：;；、\-—_()（）\[\]{}\"'“”‘’/\\]+")
_TAIL_DRIFT_LOOKAHEAD_SEGMENTS = 4
_TAIL_DRIFT_ANCHOR_THRESHOLD = 0.6
_TAIL_DRIFT_LOW_SUPPORT_THRESHOLD = 0.4
_TAIL_DRIFT_MIN_RUN = 3
_TAIL_DRIFT_SCAN_START_RATIO = 0.6
_TAIL_DRIFT_SUBSTRING_FUZZ = 6


def _normalize_for_similarity(text: str) -> str:
    return _SIMILARITY_PUNCT_RE.sub("", text.lower())


def _raw_segment_texts(raw_payload: dict) -> list[str]:
    return [
        _normalize_for_similarity(str(segment.get("text") or ""))
        for segment in raw_payload.get("segments") or []
        if str(segment.get("text") or "").strip()
    ]


def _best_local_support_score(line: str, candidate: str) -> float:
    if not line or not candidate:
        return 0.0
    if line in candidate:
        return 1.0

    best_score = SequenceMatcher(None, line, candidate).ratio()
    min_window = max(1, len(line) - _TAIL_DRIFT_SUBSTRING_FUZZ)
    max_window = min(len(candidate), len(line) + _TAIL_DRIFT_SUBSTRING_FUZZ)
    for window_length in range(min_window, max_window + 1):
        last_start = len(candidate) - window_length
        for start in range(last_start + 1):
            score = SequenceMatcher(None, line, candidate[start : start + window_length]).ratio()
            if score > best_score:
                best_score = score
    return best_score


def _build_tail_support_profile(subtitle_lines: list[str], raw_payload: dict) -> list[dict[str, Any]]:
    raw_segments = _raw_segment_texts(raw_payload)
    if not raw_segments:
        return []

    profile: list[dict[str, Any]] = []
    current_segment_index = 0
    for line_id, line in enumerate(subtitle_lines, start=1):
        normalized_line = _normalize_for_similarity(line)
        best_score = 0.0
        best_segment_index = current_segment_index
        search_end = min(len(raw_segments), current_segment_index + _TAIL_DRIFT_LOOKAHEAD_SEGMENTS + 1)
        for segment_index in range(current_segment_index, search_end):
            candidate = raw_segments[segment_index]
            score = _best_local_support_score(normalized_line, candidate)
            if score > best_score:
                best_score = score
                best_segment_index = segment_index

        profile.append(
            {
                "line_id": line_id,
                "text": line,
                "score": best_score,
                "segment_index": best_segment_index,
            }
        )
        if best_score >= _TAIL_DRIFT_ANCHOR_THRESHOLD:
            current_segment_index = best_segment_index
    return profile


def _detect_tail_drift_feedback(*, subtitle_lines: list[str], raw_payload: dict, route_mode: str, manuscript_text: str | None) -> str | None:
    if route_mode != "raw-priority" or not manuscript_text:
        return None
    if len(subtitle_lines) < 8:
        return None

    profile = _build_tail_support_profile(subtitle_lines, raw_payload)
    if not profile:
        return None

    start_index = max(1, int(len(profile) * _TAIL_DRIFT_SCAN_START_RATIO)) - 1
    for run_start in range(start_index, len(profile)):
        if profile[run_start]["score"] >= _TAIL_DRIFT_LOW_SUPPORT_THRESHOLD:
            continue

        run_end = run_start
        while run_end < len(profile) and profile[run_end]["score"] < _TAIL_DRIFT_LOW_SUPPORT_THRESHOLD:
            run_end += 1
        run_length = run_end - run_start
        if run_length < _TAIL_DRIFT_MIN_RUN:
            continue

        previous_anchor = next(
            (profile[index] for index in range(run_start - 1, -1, -1) if profile[index]["score"] >= _TAIL_DRIFT_ANCHOR_THRESHOLD),
            None,
        )
        next_anchor = next(
            (profile[index] for index in range(run_end, len(profile)) if profile[index]["score"] >= _TAIL_DRIFT_ANCHOR_THRESHOLD),
            None,
        )
        if previous_anchor is None or next_anchor is None:
            continue
        if next_anchor["segment_index"] < previous_anchor["segment_index"]:
            continue

        drift_lines = profile[run_start:run_end]
        line_span = f"{drift_lines[0]['line_id']}-{drift_lines[-1]['line_id']}"
        sample_text = " / ".join(item["text"] for item in drift_lines[:3])
        return (
            "Tail drift detected in raw-priority output. "
            f"Supported raw anchor before drift: line {previous_anchor['line_id']} `{previous_anchor['text']}`. "
            f"Unsupported drift run: lines {line_span} `{sample_text}`. "
            f"Supported raw anchor after drift: line {next_anchor['line_id']} `{next_anchor['text']}`. "
            "Regenerate the whole JSON and remove manuscript-only tail material that is not supported by raw audio order."
        )

    return None


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
        raise AuxiliaryDraftingError("Auxiliary drafting response was empty")
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise AuxiliaryDraftingError("Auxiliary drafting response did not contain a JSON object")
        payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise AuxiliaryDraftingError("Auxiliary drafting response JSON must be an object")
    return payload


def _extract_message_json_payload(message: dict[str, Any], *, finish_reason: str | None = None) -> dict[str, Any]:
    parse_errors: list[str] = []
    saw_text = False
    for field_name in ("content", "reasoning_content"):
        text = _message_content_to_text(message.get(field_name))
        if not text.strip():
            continue
        saw_text = True
        try:
            return _extract_json_object(text)
        except AuxiliaryDraftingError as exc:
            parse_errors.append(f"{field_name}: {exc}")

    if finish_reason == "length":
        raise AuxiliaryDraftingError(
            "Auxiliary drafting response exhausted output budget before final JSON; finish_reason=length"
        )
    if parse_errors:
        raise AuxiliaryDraftingError("Auxiliary drafting response did not yield valid JSON: " + "; ".join(parse_errors))
    if not saw_text:
        raise AuxiliaryDraftingError("Auxiliary drafting response was empty")
    raise AuxiliaryDraftingError("Auxiliary drafting response did not contain a JSON object")


def _build_prompt(
    *,
    raw_payload: dict,
    manuscript_text: str | None,
    route_mode: str,
    config: Step2AAuxiliaryConfig,
    retry_feedback: str | None = None,
) -> str:
    sections: list[str] = []
    for task in ("manuscript_understanding", "deduplication"):
        if task in config.prompt_paths:
            sections.append(load_prompt_text(config, task).strip())
    guidance = "\n\n".join(section for section in sections if section)
    raw_text = str(raw_payload.get("text") or "").strip()
    manuscript_block = (manuscript_text or "").strip()
    route_specific_guidance = ""
    if route_mode == "raw-priority":
        route_specific_guidance = (
            "\nraw-priority 音频锚定保留规则：\n"
            "- 保留 raw_text 里能直接支撑事实的核心名词和重复强调 即使它看起来口语化或有重复\n"
            "- 如果 raw_text 与 manuscript_text 冲突 优先保留 raw_text 中更贴近音频事实的说法\n"
            "- 不要为了贴近 manuscript_text 而删除 raw_text 里的关键名词\n"
            "- 像 电池的电池 这种重复如果承载了明确事实或强调 默认保留 不要擅自改成电车等其他词\n"
            "- 只有当 raw_text 明显是噪声且上下文证据非常强时 才能吸收 manuscript_text 的替换说法\n"
        )
    retry_block = ""
    if retry_feedback:
        retry_block = (
            "\n上一次输出触发了 Step 2A drift guard 请整体重做：\n"
            f"- {retry_feedback}\n"
            "- 保持 raw 音频顺序 不要在两个 raw 锚点之间插入 manuscript 独有的尾段内容\n"
            "- 只保留有 raw 音频支撑的尾段句子\n"
        )
    return (
        f"{guidance}{route_specific_guidance}\n\n"
        "请只返回 JSON 对象，格式如下：\n"
        "{\n"
        '  "proofread_text": "...",\n'
        '  "subtitle_lines": ["..."],\n'
        '  "proofread_confidence": 0.0,\n'
        '  "semantic_integrity": "high|medium|low",\n'
        '  "glossary_safe": true,\n'
        '  "drafting_warnings": ["..."],\n'
        '  "draft_notes": ["llm semantic draft"]\n'
        "}\n\n"
        "约束：\n"
        "- subtitle_lines 每个元素代表一条字幕\n"
        "- subtitle_lines 必须是 plain text 且不含标点符号\n"
        "- 每条 subtitle line 的显示长度必须控制在 17 个汉字量级以内\n"
        "- 用少量高层判断完成分行 优先守住长度上限 再看自然语义停顿和口语节奏\n"
        "- 术语 人名 品牌 型号 固定搭配尽量整块保护\n"
        "- 语气词按节奏 态度和人物口吻的实际价值决定保留或精简\n"
        "- 保持事实顺序\n"
        "- 只做保守校对与语义切分\n"
        "- 如果没有把握 保持文稿原意并给出 drafting_warnings\n"
        f"{retry_block}\n"
        f"ROUTE_MODE:\n{route_mode}\n\n"
        f"MANUSCRIPT:\n{manuscript_block}\n\n"
        f"RAW:\n{raw_text}\n"
    )


def _normalize_string_list(value: Any, *, field_name: str, require_non_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise AuxiliaryDraftingError(f"Auxiliary drafting {field_name} must be a list")
    normalized: list[str] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, str):
            raise AuxiliaryDraftingError(f"Auxiliary drafting {field_name}[{index}] must be a string")
        clean = item.strip()
        if clean:
            normalized.append(clean)
    if require_non_empty and not normalized:
        raise AuxiliaryDraftingError(f"Auxiliary drafting {field_name} were empty after normalization")
    return normalized


def _analyze_subtitle_lines(value: Any) -> tuple[list[str], list[str]]:
    normalized_lines = _normalize_string_list(value, field_name="subtitle_lines", require_non_empty=True)
    contract_alerts: list[str] = []
    for index, line in enumerate(normalized_lines, start=1):
        if count_text_punctuation_violations(line):
            contract_alerts.append(f"subtitle_lines[{index}] contains punctuation")
        if subtitle_display_length(line) > MAX_SUBTITLE_LINE_UNITS:
            contract_alerts.append(
                f"subtitle_lines[{index}] exceeds {MAX_SUBTITLE_LINE_UNITS} display units"
            )
    return normalized_lines, contract_alerts


def _parse_draft_payload(response_payload: dict[str, Any], *, config: Step2AAuxiliaryConfig) -> dict[str, Any]:
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AuxiliaryDraftingError("Auxiliary drafting response missing choices")
    choice = choices[0] or {}
    message = choice.get("message") or {}
    finish_reason = str(choice.get("finish_reason") or "").strip() or None
    payload = _extract_message_json_payload(message, finish_reason=finish_reason)

    proofread_text = str(payload.get("proofread_text") or "").strip()
    if not proofread_text:
        raise AuxiliaryDraftingError("Auxiliary drafting payload missing proofread_text")

    subtitle_lines, contract_alerts = _analyze_subtitle_lines(payload.get("subtitle_lines"))

    semantic_integrity = str(payload.get("semantic_integrity") or "").strip().lower()
    if semantic_integrity not in {"high", "medium", "low"}:
        raise AuxiliaryDraftingError("Auxiliary drafting semantic_integrity must be one of high|medium|low")

    try:
        proofread_confidence = float(payload.get("proofread_confidence"))
    except (TypeError, ValueError) as exc:
        raise AuxiliaryDraftingError("Auxiliary drafting proofread_confidence is invalid") from exc
    if not math.isfinite(proofread_confidence) or proofread_confidence < 0.0 or proofread_confidence > 1.0:
        raise AuxiliaryDraftingError("Auxiliary drafting proofread_confidence must be within 0.0-1.0")

    glossary_safe = payload.get("glossary_safe")
    if not isinstance(glossary_safe, bool):
        raise AuxiliaryDraftingError("Auxiliary drafting glossary_safe must be a boolean")

    drafting_warnings = _normalize_string_list(payload.get("drafting_warnings", []), field_name="drafting_warnings")
    if contract_alerts:
        drafting_warnings.extend(f"contract alert: {item}" for item in contract_alerts)
    draft_notes = _normalize_string_list(payload.get("draft_notes", []), field_name="draft_notes") or ["llm semantic draft"]

    return {
        "proofread_text": proofread_text,
        "subtitle_lines": subtitle_lines,
        "proofread_confidence": proofread_confidence,
        "semantic_integrity": semantic_integrity,
        "glossary_safe": glossary_safe,
        "drafting_warnings": drafting_warnings,
        "draft_notes": draft_notes,
        "provider_alias": config.provider_alias,
        "model": config.model,
    }


def _error_code(exc: Exception) -> str:
    if isinstance(exc, AuxiliaryDraftingError):
        return exc.code
    return "auxiliary_request_failed"


def _build_request_body(*, config: Step2AAuxiliaryConfig, prompt: str) -> dict[str, Any]:
    return {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": "You are a careful subtitle drafting assistant. Return strict JSON only. Keep reasoning concise and put the final answer in message.content.",
            },
            {"role": "user", "content": prompt},
        ],
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
        "max_tokens": config.max_tokens,
        "response_format": {"type": "json_object"},
    }


def request_auxiliary_manuscript_draft(
    *,
    raw_payload: dict,
    manuscript_text: str | None,
    mode: str,
    skill_dir: Path | None = None,
    hermes_home: Path | None = None,
    urlopen=request.urlopen,
) -> dict[str, Any]:
    config = load_step2a_auxiliary_config(
        skill_dir=Path(skill_dir or Path(__file__).resolve().parents[1]),
        hermes_home=hermes_home,
    )
    if not config.enabled:
        raise AuxiliaryDraftingError("Auxiliary drafting is disabled", code="auxiliary_disabled")
    if not config.api_key:
        raise AuxiliaryDraftingError(
            f"Auxiliary API key `{config.api_key_env}` is not available",
            code="auxiliary_missing_api_key",
        )
    if config.api_mode != "chat_completions":
        raise AuxiliaryDraftingError(
            f"Unsupported auxiliary api_mode `{config.api_mode}`",
            code="auxiliary_unsupported_api_mode",
        )

    endpoint = config.base_url.rstrip("/") + "/chat/completions"
    last_error: Exception | None = None
    retry_feedback: str | None = None
    for attempt in range(1, _MAX_AUXILIARY_DRAFT_ATTEMPTS + 1):
        try:
            prompt = _build_prompt(
                raw_payload=raw_payload,
                manuscript_text=manuscript_text,
                route_mode=mode,
                config=config,
                retry_feedback=retry_feedback,
            )
            body = json.dumps(_build_request_body(config=config, prompt=prompt), ensure_ascii=False).encode("utf-8")
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
            payload = _parse_draft_payload(response_payload, config=config)
            drift_feedback = _detect_tail_drift_feedback(
                subtitle_lines=payload["subtitle_lines"],
                raw_payload=raw_payload,
                route_mode=mode,
                manuscript_text=manuscript_text,
            )
            if drift_feedback:
                raise AuxiliaryDraftingError(drift_feedback, code="auxiliary_tail_drift", attempt_count=attempt)
            payload["attempt_count"] = attempt
            return payload
        except Exception as exc:
            last_error = exc
            if isinstance(exc, AuxiliaryDraftingError) and exc.code == "auxiliary_tail_drift":
                retry_feedback = str(exc)
    error_code = _error_code(last_error) if last_error else "auxiliary_request_failed"
    raise AuxiliaryDraftingError(
        f"Auxiliary drafting failed after {_MAX_AUXILIARY_DRAFT_ATTEMPTS} attempts: {last_error}",
        code=error_code,
        attempt_count=_MAX_AUXILIARY_DRAFT_ATTEMPTS,
    ) from last_error
