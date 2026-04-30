from __future__ import annotations

import argparse
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from auxiliary_config import AgentRuntimeConfig
from alert_tracking import build_alert_tracking, write_alert_tracking
from alignment import align_draft_to_raw_tokens, aligned_segments_to_cues, write_aligned_segments
from audit import build_alignment_audit, write_alignment_audit
from contracts import (
    AlignedSegmentsSummary,
    PipelineOutputs,
    SubtitleCue,
    count_text_punctuation_violations,
    validate_aligned_segments_texts,
    validate_cues_punctuation_free,
    validate_subtitle_draft,
)
from drafting import build_step2a_artifacts, write_proofread_manuscript, write_subtitle_draft
from finalizer import (
    FinalizerResult,
    build_agent_review_bundle,
    finalize_cues,  # noqa: F401 - imported for pipeline-level patching in tests and live Step 3 wiring surface
    write_agent_review_bundle,
    write_correction_log,
    write_final_delivery_audit,
)
from finalizer_audit import apply_delivery_timing_smoothing
from funasr_api import FunASRApiConfig, FunASRTranscribeResult, run_funasr_api_for_transcribe
from funasr_config import resolve_funasr_config
from glossary import build_run_glossary, find_suspicious_glossary_terms, write_run_glossary
from pipeline_report import (
    update_report_for_step3_review,
    validate_pending_step3_report,
    validate_step3_review_artifacts,
    write_initial_report,
)
from pipeline_step2_handoff import (
    build_pending_step3_placeholder_result,
    bundle_priority_cases,
    manual_review_finalizer_result,
)
from preflight import build_input_preflight, write_input_preflight
from routing import choose_mode, write_mode_decision
from segmentation import collect_micro_cue_examples, recover_raw_payload_for_alignment, write_cues_to_srt


@dataclass
class PipelineConfig:
    funasr_api_key: str
    funasr_model: str = "fun-asr"
    funasr_base_http_api_url: str = "https://dashscope.aliyuncs.com/api/v1"
    funasr_language_hints: list[str] | None = None
    mode_override: str | None = None


def _resolve_agent_runtime_from_env() -> AgentRuntimeConfig | None:
    base_url = os.environ.get("CURRENT_LIVE_AGENT_BASE_URL", "").strip()
    api_key = os.environ.get("CURRENT_LIVE_AGENT_API_KEY", "").strip()
    if not (base_url and api_key):
        return None
    return AgentRuntimeConfig(
        provider_name=os.environ.get("CURRENT_LIVE_AGENT_PROVIDER_NAME", "").strip() or "current-live-agent",
        base_url=base_url,
        api_key_env="CURRENT_LIVE_AGENT_API_KEY",
        api_key=api_key,
        api_mode=os.environ.get("CURRENT_LIVE_AGENT_API_MODE", "").strip() or "chat_completions",
    )


def _load_text(path: Path | None) -> str | None:
    if path is None:
        return None
    return path.read_text(encoding="utf-8")


def resolve_pipeline_config_from_args(
    args: argparse.Namespace,
    *,
    skill_dir: Path | None = None,
    hermes_home: Path | None = None,
) -> PipelineConfig:
    skill_dir = Path(skill_dir or Path(__file__).resolve().parents[1]).expanduser().resolve()
    resolved = resolve_funasr_config(
        skill_dir=skill_dir,
        cli_api_key=args.funasr_api_key,
        cli_model=args.funasr_model,
        cli_base_http_api_url=args.funasr_base_http_api_url,
        cli_language_hints=args.funasr_language_hints,
        hermes_home=hermes_home,
    )
    return PipelineConfig(
        funasr_api_key=resolved.api_key,
        funasr_model=resolved.model,
        funasr_base_http_api_url=resolved.base_http_api_url,
        funasr_language_hints=resolved.language_hints,
        mode_override=args.mode,
    )


def write_step3_review_artifacts(*, run_dir: Path, finalizer_result: FinalizerResult) -> None:
    report_path = run_dir / "report.json"
    if not report_path.exists():
        raise FileNotFoundError(f"missing report.json in {run_dir}")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    validate_pending_step3_report(report)
    validate_step3_review_artifacts(finalizer_result)

    edited_srt_path = run_dir / "edited.srt"
    correction_log_path = run_dir / "correction_log.json"
    final_delivery_audit_path = run_dir / "final_delivery_audit.json"

    smoothed_cues, smoothing_metadata = apply_delivery_timing_smoothing(finalizer_result.cues)
    correction_log = dict(finalizer_result.correction_log)
    correction_log["delivery_timing_smoothing"] = dict(smoothing_metadata)
    delivery_audit = dict(finalizer_result.delivery_audit)
    delivery_audit["timing_smoothed_count"] = int(smoothing_metadata.get("gaps_filled") or 0)
    delivery_audit["first_cue_start_snapped"] = bool(smoothing_metadata.get("first_cue_snapped"))
    smoothed_result = FinalizerResult(
        cues=smoothed_cues,
        change_breakdown=finalizer_result.change_breakdown,
        applied_regions=finalizer_result.applied_regions,
        applied_region_summary=finalizer_result.applied_region_summary,
        correction_log=correction_log,
        delivery_audit=delivery_audit,
        split_operations=finalizer_result.split_operations,
        validation_fallback_reasons=finalizer_result.validation_fallback_reasons,
        finalizer_mode=finalizer_result.finalizer_mode,
        finalizer_model_provider=finalizer_result.finalizer_model_provider,
        finalizer_model_name=finalizer_result.finalizer_model_name,
        finalizer_fallback_used=finalizer_result.finalizer_fallback_used,
        finalizer_fallback_reason=finalizer_result.finalizer_fallback_reason,
        finalizer_fallback_code=finalizer_result.finalizer_fallback_code,
        text_authority=finalizer_result.text_authority,
        manual_review_required=finalizer_result.manual_review_required,
        alert_reasons=finalizer_result.alert_reasons,
    )

    write_cues_to_srt(smoothed_result.cues, edited_srt_path)
    write_correction_log(smoothed_result.correction_log, correction_log_path)
    write_final_delivery_audit(smoothed_result.delivery_audit, final_delivery_audit_path)
    update_report_for_step3_review(report_path=report_path, finalizer_result=smoothed_result)


def _run_pipeline_from_raw_payload(
    *,
    raw_payload: dict,
    raw_json_path: Path,
    vendor_json_path: Path | None,
    run_dir: Path,
    manuscript_text: str | None,
    mode_override: str | None,
    agent_runtime: AgentRuntimeConfig | None = None,
) -> PipelineOutputs:
    input_preflight = build_input_preflight(
        raw_payload=raw_payload,
        manuscript_text=manuscript_text,
        user_override=mode_override,
    )
    input_preflight_path = run_dir / "input_preflight.json"
    write_input_preflight(input_preflight, input_preflight_path)

    mode_decision = choose_mode(
        preflight=input_preflight,
        raw_payload=raw_payload,
        manuscript_text=manuscript_text,
        user_override=mode_override,
    )
    mode_decision_path = run_dir / "mode_decision.json"
    write_mode_decision(mode_decision, mode_decision_path)

    glossary = build_run_glossary(
        raw_payload=raw_payload,
        manuscript_text=manuscript_text,
        agent_runtime=agent_runtime,
    )
    run_glossary_path = run_dir / "run_glossary.json"
    write_run_glossary(glossary, run_glossary_path)

    step2a_result = build_step2a_artifacts(
        raw_payload=raw_payload,
        manuscript_text=manuscript_text,
        mode=mode_decision.mode,
        glossary=glossary,
        agent_runtime=agent_runtime,
    )
    proofread_manuscript = step2a_result.proofread
    proofread_manuscript_path = run_dir / "proofread_manuscript.json"
    write_proofread_manuscript(proofread_manuscript, proofread_manuscript_path)

    subtitle_draft = step2a_result.draft
    step2a_alert_reasons = list(dict.fromkeys([*step2a_result.alert_reasons, *validate_subtitle_draft(subtitle_draft)]))
    subtitle_draft_path = run_dir / "subtitle_draft.json"
    write_subtitle_draft(subtitle_draft, subtitle_draft_path)
    if step2a_result.manual_review_required or not subtitle_draft.lines:
        aligned_summary = AlignedSegmentsSummary(
            line_count=0,
            mean_alignment_score=0.0,
            low_confidence_count=0,
            interpolated_boundary_count=0,
            fallback_region_count=0,
        )
        aligned_segments_path = run_dir / "aligned_segments.json"
        write_aligned_segments(segments=[], summary=aligned_summary, output_path=aligned_segments_path)

        alignment_audit = build_alignment_audit(mode_decision=mode_decision, aligned_segments=[])
        alignment_audit_path = run_dir / "alignment_audit.json"
        write_alignment_audit(alignment_audit, alignment_audit_path)

        script_pass_cues: list[SubtitleCue] = []
        script_pass_srt_path = run_dir / "edited-script-pass.srt"
        write_cues_to_srt(script_pass_cues, script_pass_srt_path)

        finalizer_result = manual_review_finalizer_result(reasons=step2a_alert_reasons)
        step3_alert_reasons = list(finalizer_result.alert_reasons)

        report_json_path = run_dir / "report.json"
        alert_tracking = build_alert_tracking(
            step2a_result=step2a_result,
            subtitle_draft=subtitle_draft,
            step2a_alert_reasons=step2a_alert_reasons,
            step2b_alert_reasons=[],
            script_pass_cues=script_pass_cues,
            finalizer_result=finalizer_result,
            step3_validation_alert_reasons=[],
            edited_cues=finalizer_result.cues,
        )
        alert_tracking_path = run_dir / "alert_tracking.json"
        write_alert_tracking(alert_tracking, alert_tracking_path)
        write_initial_report(
            output_path=report_json_path,
            raw_payload=raw_payload,
            chosen_mode=mode_decision.mode,
            post_alignment_mode=alignment_audit.post_alignment_mode,
            route_decision_reasons=mode_decision.reasons,
            alignment_summary=aligned_summary,
            downgrade_count=len(alignment_audit.downgraded_regions),
            glossary_term_count=len(glossary.terms),
            script_pass_count=0,
            edited_count=None,
            glossary_applied=bool(glossary.terms),
            short_cue_count=0,
            short_cue_examples=[],
            suspicious_glossary_terms=find_suspicious_glossary_terms(glossary),
            entity_recovery_count=0,
            entity_recovery_examples=[],
            drafting_mode=step2a_result.drafting_mode,
            subtitle_punctuation_violation_count=0,
            semantic_cut_suspect_count=0,
            draft_model_provider=step2a_result.draft_model_provider,
            draft_model_name=step2a_result.draft_model_name,
            draft_fallback_used=step2a_result.draft_fallback_used,
            draft_fallback_reason=step2a_result.draft_fallback_reason,
            draft_fallback_code=step2a_result.draft_fallback_code,
            draft_attempt_count=step2a_result.draft_attempt_count,
            step2a_text_authority=step2a_result.text_authority,
            step2a_manual_review_required=step2a_result.manual_review_required,
            step2a_alert_reasons=step2a_alert_reasons,
            step3_status="blocked",
            step3_text_authority="none",
            step3_alert_reasons=step3_alert_reasons,
            alert_tracking_summary={
                "alert_case_count": alert_tracking["alert_case_count"],
                "manual_review_case_count": alert_tracking["manual_review_case_count"],
                "stage_counts": alert_tracking["stage_counts"],
                "code_counts": alert_tracking["code_counts"],
            },
        )
        report_payload = json.loads(report_json_path.read_text(encoding="utf-8"))
        agent_review_bundle = build_agent_review_bundle(
            run_dir=run_dir,
            report=report_payload,
            priority_cases=bundle_priority_cases(alert_tracking),
        )
        agent_review_bundle_path = run_dir / "agent_review_bundle.json"
        write_agent_review_bundle(agent_review_bundle, agent_review_bundle_path)
        return PipelineOutputs(
            run_dir=run_dir,
            raw_json_path=raw_json_path,
            run_glossary_path=run_glossary_path,
            script_pass_srt_path=script_pass_srt_path,
            report_json_path=report_json_path,
            agent_review_bundle_path=agent_review_bundle_path,
            edited_srt_path=None,
            vendor_json_path=vendor_json_path,
            input_preflight_path=input_preflight_path,
            mode_decision_path=mode_decision_path,
            proofread_manuscript_path=proofread_manuscript_path,
            subtitle_draft_path=subtitle_draft_path,
            aligned_segments_path=aligned_segments_path,
            alignment_audit_path=alignment_audit_path,
            final_delivery_audit_path=None,
            correction_log_path=None,
            alert_tracking_path=alert_tracking_path,
        )

    recovered_payload, entity_recoveries = recover_raw_payload_for_alignment(
        raw_payload=raw_payload,
        manuscript_text=manuscript_text,
    )
    aligned_segments, aligned_summary = align_draft_to_raw_tokens(
        draft=subtitle_draft,
        raw_payload=recovered_payload,
        glossary=glossary,
    )
    aligned_segments_path = run_dir / "aligned_segments.json"
    write_aligned_segments(segments=aligned_segments, summary=aligned_summary, output_path=aligned_segments_path)

    alignment_audit = build_alignment_audit(
        mode_decision=mode_decision,
        aligned_segments=aligned_segments,
    )
    alignment_audit_path = run_dir / "alignment_audit.json"
    write_alignment_audit(alignment_audit, alignment_audit_path)

    post_audit_segments = aligned_segments
    step2b_alert_reasons = validate_aligned_segments_texts(post_audit_segments)
    script_pass_cues = aligned_segments_to_cues(post_audit_segments)
    step2b_alert_reasons.extend(validate_cues_punctuation_free(script_pass_cues, stage="step_2b_script_pass"))
    script_pass_srt_path = run_dir / "edited-script-pass.srt"
    write_cues_to_srt(script_pass_cues, script_pass_srt_path)

    step3_alert_reasons = list(dict.fromkeys(step2b_alert_reasons))
    placeholder_finalizer_result = build_pending_step3_placeholder_result(script_pass_cues=script_pass_cues)

    report_json_path = run_dir / "report.json"
    alert_tracking = build_alert_tracking(
        step2a_result=step2a_result,
        subtitle_draft=subtitle_draft,
        step2a_alert_reasons=step2a_alert_reasons,
        step2b_alert_reasons=step2b_alert_reasons,
        script_pass_cues=script_pass_cues,
        finalizer_result=placeholder_finalizer_result,
        step3_validation_alert_reasons=[],
        edited_cues=script_pass_cues,
    )
    alert_tracking_path = run_dir / "alert_tracking.json"
    write_alert_tracking(alert_tracking, alert_tracking_path)
    all_short_cue_examples = collect_micro_cue_examples(script_pass_cues, limit=None)
    short_cue_examples = all_short_cue_examples[:5]
    suspicious_glossary_terms = find_suspicious_glossary_terms(glossary)
    entity_recovery_examples = [item.to_dict() for item in entity_recoveries[:5]]
    subtitle_punctuation_violation_count = sum(count_text_punctuation_violations(cue.text) for cue in script_pass_cues)
    semantic_cut_suspect_count = sum(
        1 for line in subtitle_draft.lines if line.quality_signals.semantic_integrity == "low"
    )
    write_initial_report(
        output_path=report_json_path,
        raw_payload=raw_payload,
        chosen_mode=mode_decision.mode,
        post_alignment_mode=alignment_audit.post_alignment_mode,
        route_decision_reasons=mode_decision.reasons,
        alignment_summary=aligned_summary,
        downgrade_count=len(alignment_audit.downgraded_regions),
        glossary_term_count=len(glossary.terms),
        script_pass_count=len(script_pass_cues),
        edited_count=None,
        glossary_applied=bool(glossary.terms),
        short_cue_count=len(all_short_cue_examples),
        short_cue_examples=short_cue_examples,
        suspicious_glossary_terms=suspicious_glossary_terms,
        entity_recovery_count=len(entity_recoveries),
        entity_recovery_examples=entity_recovery_examples,
        drafting_mode=step2a_result.drafting_mode,
        subtitle_punctuation_violation_count=subtitle_punctuation_violation_count,
        semantic_cut_suspect_count=semantic_cut_suspect_count,
        draft_model_provider=step2a_result.draft_model_provider,
        draft_model_name=step2a_result.draft_model_name,
        draft_fallback_used=step2a_result.draft_fallback_used,
        draft_fallback_reason=step2a_result.draft_fallback_reason,
        draft_fallback_code=step2a_result.draft_fallback_code,
        draft_attempt_count=step2a_result.draft_attempt_count,
        step2a_text_authority=step2a_result.text_authority,
        step2a_manual_review_required=step2a_result.manual_review_required,
        step2a_alert_reasons=step2a_alert_reasons,
        step3_status="awaiting_agent_review",
        step3_text_authority="interactive-agent",
        step3_alert_reasons=step3_alert_reasons,
        alert_tracking_summary={
            "alert_case_count": alert_tracking["alert_case_count"],
            "manual_review_case_count": alert_tracking["manual_review_case_count"],
            "stage_counts": alert_tracking["stage_counts"],
            "code_counts": alert_tracking["code_counts"],
        },
    )

    report_payload = json.loads(report_json_path.read_text(encoding="utf-8"))
    agent_review_bundle = build_agent_review_bundle(
        run_dir=run_dir,
        report=report_payload,
        priority_cases=bundle_priority_cases(alert_tracking),
    )
    agent_review_bundle_path = run_dir / "agent_review_bundle.json"
    write_agent_review_bundle(agent_review_bundle, agent_review_bundle_path)

    return PipelineOutputs(
        run_dir=run_dir,
        raw_json_path=raw_json_path,
        run_glossary_path=run_glossary_path,
        script_pass_srt_path=script_pass_srt_path,
        report_json_path=report_json_path,
        agent_review_bundle_path=agent_review_bundle_path,
        edited_srt_path=None,
        vendor_json_path=vendor_json_path,
        input_preflight_path=input_preflight_path,
        mode_decision_path=mode_decision_path,
        proofread_manuscript_path=proofread_manuscript_path,
        subtitle_draft_path=subtitle_draft_path,
        aligned_segments_path=aligned_segments_path,
        alignment_audit_path=alignment_audit_path,
        final_delivery_audit_path=None,
        correction_log_path=None,
        alert_tracking_path=alert_tracking_path,
    )


def run_minimal_pipeline(*, audio_path: Path, run_dir: Path, manuscript_text: str | None, config: PipelineConfig) -> PipelineOutputs:
    run_dir.mkdir(parents=True, exist_ok=True)
    agent_runtime = _resolve_agent_runtime_from_env()

    funasr_result: FunASRTranscribeResult = run_funasr_api_for_transcribe(
        local_audio_path=audio_path,
        run_dir=run_dir,
        config=FunASRApiConfig(
            api_key=config.funasr_api_key,
            model=config.funasr_model,
            base_http_api_url=config.funasr_base_http_api_url,
            language_hints=config.funasr_language_hints,
        ),
    )

    raw_payload = json.loads(funasr_result.raw_json_path.read_text(encoding="utf-8"))
    return _run_pipeline_from_raw_payload(
        raw_payload=raw_payload,
        raw_json_path=funasr_result.raw_json_path,
        vendor_json_path=funasr_result.vendor_json_path,
        run_dir=run_dir,
        manuscript_text=manuscript_text,
        mode_override=config.mode_override,
        agent_runtime=agent_runtime,
    )


def run_replay_from_raw(
    *,
    raw_json_path: Path,
    run_dir: Path,
    manuscript_text: str | None,
    mode_override: str | None = None,
    agent_runtime: AgentRuntimeConfig | None = None,
) -> PipelineOutputs:
    run_dir.mkdir(parents=True, exist_ok=True)
    source_raw_json_path = raw_json_path.expanduser().resolve()
    replay_raw_json_path = run_dir / "raw.json"
    if source_raw_json_path != replay_raw_json_path:
        shutil.copy2(source_raw_json_path, replay_raw_json_path)
    raw_payload = json.loads(replay_raw_json_path.read_text(encoding="utf-8"))
    return _run_pipeline_from_raw_payload(
        raw_payload=raw_payload,
        raw_json_path=replay_raw_json_path,
        vendor_json_path=None,
        run_dir=run_dir,
        manuscript_text=manuscript_text,
        mode_override=mode_override,
        agent_runtime=agent_runtime,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the minimal FunASR-first transcription pipeline.")
    parser.add_argument("audio", nargs="?", help="Local audio/video file path")
    parser.add_argument("--output-dir", required=True, help="Run output directory")
    parser.add_argument("--manuscript-path", default=None, help="Optional manuscript text file")
    parser.add_argument("--replay-from-raw", default=None, help="Replay Step 0-2 handoff from an existing raw.json")
    parser.add_argument("--funasr-api-key", default=None, help="Bailian FunASR API key")
    parser.add_argument("--funasr-model", default=None)
    parser.add_argument("--funasr-base-http-api-url", default=None)
    parser.add_argument("--funasr-language-hint", action="append", dest="funasr_language_hints", default=None)
    parser.add_argument("--mode", choices=["auto", "manuscript-priority", "raw-priority"], default=None)
    return parser


def main(argv: list[str] | None = None, *, skill_dir: Path | None = None, hermes_home: Path | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    manuscript_text = _load_text(Path(args.manuscript_path).expanduser().resolve()) if args.manuscript_path else None
    run_dir = Path(args.output_dir).expanduser().resolve()
    if args.replay_from_raw:
        if args.audio:
            parser.error("audio positional argument is not used with --replay-from-raw")
        outputs = run_replay_from_raw(
            raw_json_path=Path(args.replay_from_raw).expanduser().resolve(),
            run_dir=run_dir,
            manuscript_text=manuscript_text,
            mode_override=args.mode,
        )
    else:
        if not args.audio:
            parser.error("audio is required unless --replay-from-raw is set")
        config = resolve_pipeline_config_from_args(args, skill_dir=skill_dir, hermes_home=hermes_home)
        if not config.funasr_api_key:
            parser.error("FunASR API key is required. Provide --funasr-api-key or configure a skill-local credential source.")
        outputs = run_minimal_pipeline(
            audio_path=Path(args.audio).expanduser().resolve(),
            run_dir=run_dir,
            manuscript_text=manuscript_text,
            config=config,
        )
    print(
        json.dumps(
            {
                "run_dir": str(outputs.run_dir),
                "raw_json_path": str(outputs.raw_json_path),
                "input_preflight_path": str(outputs.input_preflight_path),
                "mode_decision_path": str(outputs.mode_decision_path),
                "proofread_manuscript_path": str(outputs.proofread_manuscript_path),
                "subtitle_draft_path": str(outputs.subtitle_draft_path),
                "aligned_segments_path": str(outputs.aligned_segments_path),
                "alignment_audit_path": str(outputs.alignment_audit_path),
                "run_glossary_path": str(outputs.run_glossary_path),
                "script_pass_srt_path": str(outputs.script_pass_srt_path),
                "agent_review_bundle_path": str(outputs.agent_review_bundle_path),
                "edited_srt_path": str(outputs.edited_srt_path) if outputs.edited_srt_path else None,
                "report_json_path": str(outputs.report_json_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
