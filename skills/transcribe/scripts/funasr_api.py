#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib import request


@dataclass
class FunASRApiConfig:
    api_key: str
    model: str = "fun-asr"
    base_http_api_url: str = "https://dashscope.aliyuncs.com/api/v1"
    language_hints: list[str] | None = None
    output_filename: str = "bailian_raw.json"


@dataclass
class FunASRRunResult:
    raw_json_path: Path
    upload_file_id: str
    uploaded_file_url: str
    task_id: str
    result_url: str


@dataclass
class FunASRTranscribeResult:
    raw_json_path: Path
    raw_srt_path: Path | None
    vendor_json_path: Path
    upload_file_id: str
    uploaded_file_url: str
    task_id: str
    result_url: str


class FunASRApiError(RuntimeError):
    pass


def _response_status_code(response: Any) -> int | None:
    if isinstance(response, dict):
        return response.get("status_code")
    return getattr(response, "status_code", None)


def _response_output(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        output = response.get("output")
        return output if isinstance(output, dict) else {}
    output = getattr(response, "output", None)
    return output if isinstance(output, dict) else {}


def _raise_for_response(response: Any, action: str) -> None:
    status_code = _response_status_code(response)
    if status_code in (HTTPStatus.OK, 200):
        return
    if isinstance(response, dict):
        message = response.get("message") or response.get("code") or repr(response)
    else:
        message = getattr(response, "message", None) or getattr(response, "code", None) or repr(response)
    raise FunASRApiError(f"{action} failed: {message}")


def _dashscope_imports():
    try:
        import dashscope
        from dashscope.audio.asr import Transcription
        from dashscope.files import Files
    except ImportError as exc:
        raise FunASRApiError("dashscope SDK not installed. Install with `pip install dashscope`.") from exc
    return dashscope, Files, Transcription


def _upload_local_file(local_audio_path: Path, config: FunASRApiConfig) -> dict[str, str]:
    dashscope, Files, _ = _dashscope_imports()
    dashscope.base_http_api_url = config.base_http_api_url
    upload_response = Files.upload(file_path=str(local_audio_path), purpose="inference", api_key=config.api_key)
    _raise_for_response(upload_response, "file upload")
    upload_output = _response_output(upload_response)
    uploaded_files = upload_output.get("uploaded_files") or []
    if not uploaded_files:
        raise FunASRApiError(f"file upload returned no uploaded_files: {upload_response!r}")
    file_id = uploaded_files[0].get("file_id")
    if not file_id:
        raise FunASRApiError(f"file upload returned no file_id: {upload_response!r}")
    info_response = Files.get(file_id=file_id, api_key=config.api_key)
    _raise_for_response(info_response, "file info lookup")
    info_output = _response_output(info_response)
    url = info_output.get("url")
    if not url:
        raise FunASRApiError(f"file info lookup returned no url: {info_response!r}")
    return {"file_id": file_id, "url": url}


def _submit_transcription_task(*, file_url: str, config: FunASRApiConfig) -> str:
    dashscope, _, Transcription = _dashscope_imports()
    dashscope.base_http_api_url = config.base_http_api_url
    kwargs: dict[str, Any] = {}
    if config.language_hints:
        kwargs["language_hints"] = config.language_hints
    task_response = Transcription.async_call(
        model=config.model,
        file_urls=[file_url],
        api_key=config.api_key,
        **kwargs,
    )
    _raise_for_response(task_response, "transcription task submission")
    task_output = _response_output(task_response)
    task_id = task_output.get("task_id")
    if not task_id:
        raise FunASRApiError(f"transcription task submission returned no task_id: {task_response!r}")
    return task_id


def _wait_for_task_result(*, task_id: str, config: FunASRApiConfig) -> dict[str, Any]:
    dashscope, _, Transcription = _dashscope_imports()
    dashscope.base_http_api_url = config.base_http_api_url
    wait_response = Transcription.wait(task=task_id, api_key=config.api_key)
    _raise_for_response(wait_response, "transcription task wait")
    return _response_output(wait_response)


def _download_json_payload(result_url: str) -> dict[str, Any]:
    with request.urlopen(result_url) as response:
        return json.loads(response.read().decode("utf-8"))


def _sentence_text(sentence: dict[str, Any]) -> str:
    text = str(sentence.get("text") or "").strip()
    if text:
        return text
    pieces: list[str] = []
    for word in sentence.get("words") or []:
        pieces.append(str(word.get("text") or ""))
        pieces.append(str(word.get("punctuation") or ""))
    return "".join(pieces).strip()


def normalize_bailian_payload(payload: dict[str, Any]) -> dict[str, Any]:
    transcripts = payload.get("transcripts") or []
    normalized_segments: list[dict[str, Any]] = []
    transcript_text_parts: list[str] = []

    for transcript in transcripts:
        transcript_text = str((transcript or {}).get("text") or "").strip()
        if transcript_text:
            transcript_text_parts.append(transcript_text)
        for sentence in (transcript or {}).get("sentences") or []:
            sentence_text = _sentence_text(sentence)
            if not sentence_text:
                continue
            words: list[dict[str, Any]] = []
            for idx, word in enumerate(sentence.get("words") or [], start=1):
                start_ms = float(word.get("begin_time") or 0.0)
                end_ms = float(word.get("end_time") or start_ms)
                words.append(
                    {
                        "id": idx,
                        "text": str(word.get("text") or ""),
                        "start": start_ms / 1000.0,
                        "end": end_ms / 1000.0,
                        "punctuation": str(word.get("punctuation") or ""),
                    }
                )
            start_ms = float(sentence.get("begin_time") or 0.0)
            end_ms = float(sentence.get("end_time") or start_ms)
            normalized_segments.append(
                {
                    "id": len(normalized_segments) + 1,
                    "start": start_ms / 1000.0,
                    "end": end_ms / 1000.0,
                    "text": sentence_text,
                    "words": words,
                    "source": "funasr-api.sentence",
                }
            )

    if not transcript_text_parts:
        transcript_text_parts = [segment["text"] for segment in normalized_segments if segment.get("text")]

    return {
        "schema": "transcribe.raw.v3",
        "text": " ".join(part for part in transcript_text_parts if part).strip(),
        "segments": normalized_segments,
        "backend": "funasr-api",
        "vendor": "bailian.fun-asr",
        "vendor_properties": payload.get("properties") or {},
        "vendor_file_url": payload.get("file_url"),
    }


def run_funasr_api(*, local_audio_path: Path, run_dir: Path, config: FunASRApiConfig) -> FunASRRunResult:
    local_audio_path = local_audio_path.expanduser().resolve()
    if not local_audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {local_audio_path}")
    run_dir.mkdir(parents=True, exist_ok=True)

    uploaded = _upload_local_file(local_audio_path, config)
    task_id = _submit_transcription_task(file_url=uploaded["url"], config=config)
    task_output = _wait_for_task_result(task_id=task_id, config=config)
    results = task_output.get("results") or []
    if not results:
        raise FunASRApiError(f"transcription task returned no results: {task_output!r}")
    first_result = results[0]
    if first_result.get("subtask_status") != "SUCCEEDED":
        message = first_result.get("message") or json.dumps(first_result, ensure_ascii=False)
        raise FunASRApiError(f"transcription subtask failed: {message}")
    result_url = first_result.get("transcription_url")
    if not result_url:
        raise FunASRApiError(f"transcription result missing transcription_url: {first_result!r}")
    payload = _download_json_payload(result_url)
    raw_json_path = run_dir / config.output_filename
    raw_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return FunASRRunResult(
        raw_json_path=raw_json_path,
        upload_file_id=uploaded["file_id"],
        uploaded_file_url=uploaded["url"],
        task_id=task_id,
        result_url=result_url,
    )


def run_funasr_api_for_transcribe(*, local_audio_path: Path, run_dir: Path, config: FunASRApiConfig) -> FunASRTranscribeResult:
    vendor_result = run_funasr_api(local_audio_path=local_audio_path, run_dir=run_dir, config=config)
    vendor_payload = json.loads(vendor_result.raw_json_path.read_text(encoding="utf-8"))
    normalized_payload = normalize_bailian_payload(vendor_payload)
    raw_json_path = run_dir / "raw.json"
    raw_json_path.write_text(json.dumps(normalized_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return FunASRTranscribeResult(
        raw_json_path=raw_json_path,
        raw_srt_path=None,
        vendor_json_path=vendor_result.raw_json_path,
        upload_file_id=vendor_result.upload_file_id,
        uploaded_file_url=vendor_result.uploaded_file_url,
        task_id=vendor_result.task_id,
        result_url=vendor_result.result_url,
    )
