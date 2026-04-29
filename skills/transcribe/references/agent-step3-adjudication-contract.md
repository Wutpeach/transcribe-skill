# Agent Step 3 Adjudication Contract

## Purpose

This document defines the active Step 3 workflow for the transcription pipeline.

Step 3 is owned by the live interactive agent session itself. It is not another configured backend-model call inside the pipeline.

## Control shape

- Step 1 = FunASR only
- Step 2 = configured auxiliary model plus pipeline guardrails
- Step 3 = live interactive agent adjudication

## Required Step 3 inputs

Read these artifacts first:

1. `agent_review_bundle.json`
2. `edited-script-pass.srt`
3. `report.json`
4. `alignment_audit.json`
5. `aligned_segments.json`
6. `proofread_manuscript.json`
7. `run_glossary.json`
8. `raw.json`

## Editable base

Use `edited-script-pass.srt` as the default editable base.

A migration task may explicitly replace this base. The active workflow keeps `edited-script-pass.srt` as the default.

When Step 3 re-segments a subtitle for delivery, the target output shape is **true cue-level splitting**. Do not treat an internal newline inside one unchanged cue timestamp as an acceptable substitute.

## Step 3 authority

The Step 3 agent may:
- perform final subtitle audit
- make conservative wording fixes
- fix mixed zh-en spacing
- improve subtitle segmentation when delivery quality clearly needs it
- preserve audio facts and protected term boundaries
- decide whether the run is ready for delivery or still needs review
- split one cue into multiple new cues when delivery timing and rhythm clearly support it
- assign onset-first timestamps for new cues using `aligned_segments.json` and `raw.json` word timing

The Step 3 agent may not:
- silently hand final text authority to another configured backend model path
- change timing facts without clear justification grounded in the run artifacts
- broaden the edit scope into free rewriting detached from the audio and manuscript evidence

## Required Step 3 outputs

The Step 3 agent must write:
- `edited.srt`
- `correction_log.json`
- `final_delivery_audit.json`
- updated `report.json`

## Required report state updates

Set `step3_status` to one of:
- `awaiting_agent_review`
- `adjudicated_ready`
- `adjudicated_needs_review`
- `blocked`

Expected meanings:
- `awaiting_agent_review` = Step 2 completed and is waiting for live agent adjudication
- `adjudicated_ready` = Step 3 completed and the output is ready for delivery
- `adjudicated_needs_review` = Step 3 completed and unresolved delivery risk remains
- `blocked` = Step 3 could not proceed because required conditions were missing

After Step 3 completion, `report.json` should be formally rewritten with at least:
- `step3_status`
- `step3_text_authority`
- `step3_alert_reasons`
- `manual_review_required`
- `final_delivery_status`
- `final_delivery_risk`
- `final_delivery_reasons`
- `finalizer_change_count`
- `finalizer_change_breakdown`
- `finalizer_applied_regions`
- `finalizer_mode`
- `finalizer_model_provider`
- `finalizer_model_name`
- `finalizer_fallback_used`
- `finalizer_fallback_reason`
- `finalizer_fallback_code`
- `segmentation_stats.edited_cue_count`
- top-level `edited_cue_count`
- top-level `split_count`
- top-level `cue_splitting`

## Audit expectations

`correction_log.json` and `final_delivery_audit.json` should remain machine-readable.

The final audit should preserve:
- what changed
- why it changed
- which cues or regions were affected
- why the run was marked ready or needs review

## Minimal cue-splitting contract

`FinalizerResult` should expose:
- `split_operations`: one record per original cue that was split into multiple new cues

`correction_log.json` should keep these minimum keys when cue splitting happens:
- `cue_splits`: array of split records
- `split_statistics`: aggregate counts derived from `cue_splits`
- each `cue_split` record should include:
  - `original_line_id`
  - `new_line_ids`
  - `split_type`
  - `split_confidence`
  - `start_alignment_delta_ms`
  - `risk_level`
  - `used_fallback`
  - `fallback_steps`
  - `split_point_token_index`

`final_delivery_audit.json` should keep a `cue_splitting` object with at least:
- `split_count`
- `high_risk_count`
- `max_length`
- `mean_alignment_delta_ms`

When Step 3 performs true cue-level splitting, `checks.resegment_count` should reflect the number of split operations, and `resegment_source` should name the Step 3 adjudication path.

## Workflow note

This contract belongs in workflow docs and skills. It should not be stored as long-term personal memory.