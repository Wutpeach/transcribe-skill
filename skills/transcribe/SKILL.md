---
name: transcribe
description: "Minimal active transcription workflow: FunASR to raw.json, Step 2 / 2A segmentation with per-run run_glossary.json, and Step 3 / Hermes final delivery."
version: 1.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [transcription, subtitles, funasr, srt, workflow]
---

# transcribe

Use this skill for the active transcription mainline.

## Goal

Produce a deliverable SRT that is:
- grounded in audio facts
- terminology-correct
- smoothly segmented
- kept on the smallest stable pipeline

## Active mainline

### Step 1 — FunASR / timing
Outputs:
- `raw.json`

Rules:
- `raw.json` is the source of truth.
- Preserve transcript text, segments, words, and timing unchanged.
- Do not clean text here.
- Do not segment here.

### Step 2 — preflight + routing
Outputs:
- `input_preflight.json`
- `mode_decision.json`

Rules:
- Assess manuscript presence and quality before drafting.
- Keep the first-pass signals deterministic and small.
- Route between `manuscript-priority` and `raw-priority`.
- Allow explicit user override.
- Keep warning-band cases observable so later audit can downgrade conservatively.

### Step 2A — run glossary prep + structure building
Outputs:
- `run_glossary.json`
- `proofread_manuscript.json` (`transcribe.proofread_manuscript.v2`)
- `subtitle_draft.json` (`transcribe.subtitle_draft.v2`)
- `aligned_segments.json` (`transcribe.aligned_segments.v2`)
- `edited-script-pass.srt`

Design direction:
- Step 2A owns structural drafting.
- Step 2B owns alignment.
- Step 2A's center is manuscript proofreading, one-line subtitle segmentation, glossary-boundary protection, and delivery-style plain-text drafting.
- Step 2A draft text should be punctuation-free.
- Step 2A should treat 17 Han-character-equivalent units as a hard per-line display cap.
- It may prepare narrow local normalization guidance in `run_glossary.json`.
- It should stay structurally focused and small enough to be redesigned or replaced cleanly.
- Current Phase A contract adds `proofread_confidence`, `draft_ready`, `drafting_warnings`, `style_flags`, `quality_signals`, and coarse `raw_span_mapping` so the legacy deterministic path and the live LLM path share the same artifact shape.

### Step 5 — alignment audit and downgrade
Outputs:
- `alignment_audit.json`

Rules:
- Review aligned line quality before final delivery.
- Downgrade weak manuscript-priority runs to `raw-priority` conservatively.
- Mark weak regions with audit signals such as `rebuild_regions` for observability and downstream caution.
- Keep downgrade and weak-region reasons observable.

Optional debug output:
- `semantic_segments.json`

Rules:
- Build a temporary per-run glossary.
- If manuscript exists, extract canonical terms, aliases, and casing guidance.
- Keep the glossary narrow: acronyms, models, mixed-script entities, and casing anchors.
- If manuscript does not exist, still emit an empty or minimal `run_glossary.json` so the pipeline shape stays stable.
- Separate text drafting from timing alignment.
- `proofread_manuscript.json` is the textual draft anchor.
- `subtitle_draft.json` is one subtitle line per semantic unit.
- Subtitle text should be delivery-oriented plain text without punctuation symbols.
- Enforce punctuation-free delivery text at three gates: right after Step 2A draft generation, before Step 2B writes `edited-script-pass.srt`, and before Step 3 writes `edited.srt`.
- `aligned_segments.json` maps each draft line back onto raw timing with token spans, split points, confidence, and warnings.
- `aligned_segments.json` should carry explicit Step 2B identity such as schema `transcribe.aligned_segments.v2` and `source_stage=step-2b-alignment`.
- `edited-script-pass.srt` comes from aligned segments rather than direct raw segmentation.
- Allow protected-span preservation, glossary-boundary protection, manuscript-backed entity recovery for key entities, and post-segmentation micro-cue merge guards.
- Trigger manuscript-backed entity recovery only when suspicious ASR fragments align with local manuscript anchors and entity count/order.
- Restrict recovery to brands, models, and mixed-script proper nouns.
- In `raw-priority`, allow narrow manuscript-backed entity recovery to enter proofread and draft text when the recovery is locally anchored and high-confidence.
- Preserve raw timing authority while replacing only the recovered entity text.
- Do zero broad text correction.
- Do not repair ordinary wording or prose here.

### Step 3 — Hermes / agent adjudication
Outputs:
- `edited.srt`
- `report.json`

Optional gate/debug outputs:
- `final_delivery_audit.json`
- `correction_log.json`

Rules:
- Step 3 is owned by the live interactive agent session itself.
- Use `raw.json` as the fact anchor.
- Read Step 2 artifacts such as `edited-script-pass.srt`, `proofread_manuscript.json`, `aligned_segments.json`, `alignment_audit.json`, `run_glossary.json`, and `report.json`.
- Use `edited-script-pass.srt` as the default editable base unless a migration task explicitly changes that contract.
- Apply conservative term and casing fixes.
- Handle mixed zh-en spacing.
- Do light error correction.
- Re-segment only when needed for delivery quality.
- Hermes is the sole final adjudicator.
- Step 3 must not silently fall back to another configured backend model path.

## Authority order

Use this order whenever there is conflict:

`audio facts > raw timing/text evidence > protected term boundaries from run_glossary > manuscript local clues > Hermes judgment`

## Default artifacts
Keep by default:
- `raw.json`
- `input_preflight.json`
- `mode_decision.json`
- `run_glossary.json`
- `proofread_manuscript.json`
- `subtitle_draft.json`
- `aligned_segments.json`
- `alignment_audit.json`
- `edited-script-pass.srt`
- `edited.srt`
- `report.json`
- `alert_tracking.json`

Debug only:
- `semantic_segments.json`
- `final_delivery_audit.json`
- `correction_log.json`

## Retired from active maintenance
Treat these as archive-only unless a migration task explicitly needs them for reference:
- global glossary stores
- glossary candidate accumulation
- promotion logs
- promoted-term pipelines
- standalone auxiliary review stages
- intermediate text-polishing stages before Hermes final
- oversized report schemas that encode old workflow control

## Current implementation shape

- The active skill directory includes a minimal runnable pipeline:
- `scripts/pipeline.py` orchestrates the run
- `scripts/funasr_api.py` handles Bailian FunASR calls
- `scripts/preflight.py` builds deterministic manuscript-quality signals into `input_preflight.json`
- `scripts/routing.py` selects `manuscript-priority` or `raw-priority` and writes `mode_decision.json`
- `scripts/glossary.py` builds per-run `run_glossary.json`
- `scripts/drafting.py` builds `proofread_manuscript.json` and `subtitle_draft.json`
- `scripts/alignment.py` aligns subtitle draft lines back onto raw timing and writes `aligned_segments.json`
- `scripts/audit.py` reviews alignment quality, emits `alignment_audit.json`, and marks downgrade/rebuild regions
- `scripts/segmentation.py` now also exposes reusable manuscript-backed entity recovery helpers and SRT writers used by the rebuilt script pass
- `scripts/finalizer.py` is the compatibility export surface for Step 3 helpers.
- `scripts/finalizer_bundle.py` builds and writes `agent_review_bundle.json`.
- `scripts/finalizer_cues.py` owns token-anchored cue splitting, timing snaps, and Step 3 result dataclasses.
- `scripts/finalizer_audit.py` owns finalizer validation, cue diff/audit shaping, and `finalize_cues()`.
- `scripts/finalizer_writeback.py` writes machine-readable Step 3 artifacts.
- `scripts/pipeline_report.py` owns initial `report.json` generation plus validated Step 3 state transitions during writeback.
- `scripts/pipeline_step2_handoff.py` owns Step 2-to-Step 3 handoff placeholder/fallback helpers.
- `scripts/alert_tracking.py` classifies stage alerts, aggregates manual-review causes, and writes `alert_tracking.json`.
- `scripts/contracts.py` defines the normalized contracts, including `transcribe.raw.v3`
- `scripts/auxiliary_drafting.py` performs the live Step 2A auxiliary drafting path.
- Auxiliary drafting now uses a structured response boundary before artifacts enter the pipeline.
- Validate `subtitle_lines` as a non-empty list of strings.
- Treat punctuation-bearing lines and over-17-unit lines as soft contract alerts: keep the model text, attach alert strings in `drafting_warnings`, and preserve model authority.
- Require `semantic_integrity` to be exactly `high`, `medium`, or `low`.
- Require `proofread_confidence` to stay within `0.0-1.0`.
- Require `glossary_safe` to be boolean.
- Require `drafting_warnings` and `draft_notes` to be string lists.
- Retry the auxiliary drafting request on transport or parse failures only. Soft contract alerts stay on the successful path and do not trigger script takeover.
- Auxiliary drafting no longer requires manuscript text as a hard prerequisite. Empty manuscript context is allowed when the route still wants the model path.
- Record `draft_fallback_reason` in `Step2ADraftingResult` and `report.json` so manual-review causes stay observable.
- Record `draft_fallback_code` and `draft_attempt_count` alongside the free-text reason so retry behavior and failure category stay queryable.
- Current `draft_fallback_code` values are centered on request-path failures such as `auxiliary_disabled`, `auxiliary_missing_api_key`, `auxiliary_unsupported_api_mode`, and `auxiliary_request_failed`.
- `draft_attempt_count` is the number of auxiliary attempts on the chosen path. Clean LLM success reports the successful attempt number, and `manual-review-required` after request failure reports the terminal attempt count.
- `scripts/auxiliary_config.py` resolves the Step 2A auxiliary-model scaffold from `config/models.toml`, `config/transcribe.toml`, Hermes provider config, and prompt files under `prompts/understanding/`
- `scripts/auxiliary_glossary.py` performs the first live Step 2A auxiliary call path for entity and term correction, then `scripts/glossary.py` merges the validated corrections conservatively into `run_glossary.json`
- The auxiliary model scaffold can be pointed at a dedicated direct provider for Step 2A only. In practice, `config/models.toml` can reference a Hermes provider alias such as `deepseek_direct_aux`, with the concrete `base_url`, `key_env`, and `api_mode=chat_completions` defined in `~/.hermes/config.yaml`, so the transcription auxiliary path can bypass a flaky proxy without changing the user's main Hermes routing.

Current Step 3 status:
- The active mainline is now fully agent-led Step 3 rather than backend-model-led Step 3.
- `scripts/pipeline.py` stops after Step 2 packaging and writes the Step 3 handoff artifacts.
- `scripts/pipeline.py` now also exposes `write_step3_review_artifacts()` as the official Step 3 completion writeback path for `edited.srt`, `correction_log.json`, `final_delivery_audit.json`, and the finalized `report.json` fields.
- `write_step3_review_artifacts()` now validates the pending `report.json` state and Step 3 artifact schemas before promoting `step3_status` into an adjudicated state.
- Step 3 reads Step 2 artifacts, uses `edited-script-pass.srt` as the editable base, and performs the final subtitle adjudication in the live interactive session.
- `agent_review_bundle.json` is the required handoff artifact between Step 2 and Step 3.
- `report.json` treats ordinary Step 3 handoff as a normal pending state with `step3_owner="interactive-agent"`, `step3_execution_mode="agent-session"`, and `step3_status="awaiting_agent_review"`.
- If Step 2 cannot produce a valid draft handoff, `report.json` should mark `step3_status="blocked"` and keep final delivery files absent.
- Final delivery files stay late-bound until the live agent completes Step 3: `edited.srt`, `correction_log.json`, and `final_delivery_audit.json` should remain absent on the pipeline mainline.
- `scripts/finalizer.py` remains a helper surface for packaging, token-anchored cue splitting, and writeback-side validation.
- It now exposes token-anchored cue splitting so the live Step 3 agent can turn one cue into multiple new timed cues with onset-first timing derived from `aligned_segments.json` and `raw.json` word timing.
- `finalize_cues()` rejects proofread-driven backend adjudication. Live Step 3 text changes must flow through the agent review bundle and `write_step3_review_artifacts()`.
- The retired Step 3 backend path is fully removed: `scripts/auxiliary_finalization.py` is gone, `load_step3_auxiliary_config()` is gone, and unit tests should treat any proofread-driven finalization attempt as architecture drift.
- `correction_log.json` and `final_delivery_audit.json` should remain machine-readable so agent edits stay auditable.


Current Step 2A authority guard:
- Step 2A should treat auxiliary output as the text authority when the call succeeds.
- If the auxiliary response violates soft contract expectations such as punctuation-free lines or the 17-unit cap, keep the model text, attach contract alerts, and expose them in observability fields. Do not silently rewrite those lines in the script layer.
- If the auxiliary request itself fails, return a `manual-review-required` result rather than reviving a broad bootstrap text takeover path.
- A Step 2A `manual-review-required` result should still produce an auditable pipeline run: write the proofread artifact, an empty subtitle draft / aligned-segment / SRT tail, `report.json`, and `final_delivery_audit.json`, then stop before Step 2B / Step 3 text processing.
- `Step2ADraftingResult` should carry `text_authority`, `manual_review_required`, and `alert_reasons` so downstream stages can preserve the authority decision.

Current Step 2B authority guard:
- Alignment owns timing and span mapping.
- Mainline Step 2B should not rebuild subtitle text from raw spans.
- Legacy raw-span rebuild helpers are retired from the active code path.
- Validation at Step 2B should produce alerts and audit signals, while leaving text decisions to the model-owned stages.
- Keep a same-token collapse guard after alignment and before script-pass cue serialization. When consecutive low-confidence micro-duration lines collapse onto the exact same raw token window, merge that run into the nearest overlapping aligned cue or into one segment of its own. Preserve the existing subtitle texts in order, add an explicit warning such as `timing collapse merged 289-295`, and avoid resurrecting any raw-text rebuild path.

## Step 2A auxiliary drafting maintenance order

The active pipeline has already crossed the rollout phase. Keep Step 2A aligned with these maintenance rules:
1. Keep the artifact contract stable: `proofread_manuscript.json` and `subtitle_draft.json` should stay shape-compatible across prompt or provider changes.
2. Keep the live success path model-led: successful auxiliary calls should resolve to `llm-primary` or `llm-primary-with-alerts`.
3. Keep the failure path review-led: request or parse failure should resolve to `manual-review-required`, with no bootstrap text takeover revived.
4. Keep `report.json` observability locked: `drafting_mode`, `draft_model_provider`, `draft_model_name`, `draft_fallback_used`, `draft_fallback_reason`, `draft_fallback_code`, `draft_attempt_count`, `step2a_text_authority`, and `manual_review_required` should remain stable.
- Keep the raw-priority path narrow: preserve raw transcript authority in `proofread.source_text`, allow only locally anchored entity recovery, and avoid broad script cleanup.
- In `raw-priority`, add explicit audio-anchor retention guidance inside the Step 2A prompt. Preserve core nouns, repeated emphasis, and other salient audio facts even when the manuscript offers a smoother paraphrase. A real regression on `用了欣旺达电池` showed that prompt-level manuscript pressure can delete a key noun and turn `用了欣旺达电池的电车我可不买` into `用了欣旺达的电车我不买`. The durable first fix is a narrow raw-priority prompt block that tells the model to keep audio-anchored key terms and avoid manuscript-driven deletion of those anchors.
- In `raw-priority`, keep a tail drift guard after JSON parsing. Compare each drafted subtitle line against nearby raw tail material with substring-aware local support, scan only the final 40% of the draft, and trigger a retry only when a 3-plus-line low-support run is bracketed by supported raw anchors. This protects CTA tails from manuscript-only continuation while keeping ordinary line splitting untouched. If the retry still drifts, fail closed to manual review rather than letting unsupported tail text enter Step 2B.
6. Keep the authority gate in CI: the end-to-end authority/manual-review regression tests should stay mandatory before any merge.

Verification command:
```bash
python3 scripts/pipeline.py --help
```

Test runner note:
```bash
PYTHONPATH=scripts pytest tests/test_prompts.py -q
```
Use `PYTHONPATH=scripts` for direct unit runs in this skill repo when tests rely on top-level imports like `glossary` from `tests/conftest.py`.

Run shape:
```bash
python3 scripts/pipeline.py /path/to/audio.wav \
  --output-dir /path/to/run \
  --manuscript-path /path/to/manuscript.txt
```

Optional explicit override:
```bash
python3 scripts/pipeline.py /path/to/audio.wav \
  --output-dir /path/to/run \
  --funasr-api-key YOUR_KEY \
  --manuscript-path /path/to/manuscript.txt
```

Preferred Step 1 credential/config layout for this skill:
- Keep shared FunASR settings inside the skill directory so other agents such as OpenClaw can discover them easily.
- Put portable defaults in `config/funasr.toml`, such as `base_http_api_url`, `model`, `language_hints`, and `key_env`.
- Put machine-local secrets in `config/funasr.local.toml` or `.env.local` inside the skill directory.
- When packaging the skill for sharing, include `config/funasr.local.example.toml` and keep the real local secret file out of the shared bundle.
- Preferred discovery order for Step 1 is: explicit CLI key, then skill-local secret config, then skill-local env file, then broader Hermes environment.

Replay from existing `raw.json`:
```bash
python3 scripts/pipeline.py \
  --output-dir /path/to/replay-run \
  --replay-from-raw /path/to/existing/raw.json \
  --manuscript-path /path/to/manuscript.txt
```

## Real-run findings

From real-sample replay on a production-like case:
- If Step 1 cannot run because the API key or upstream ASR service is unavailable, replay the current Step 2 / Step 3 stack from an existing `raw.json` to validate structure and delivery behavior.
- Review `run_glossary.json` on every real sample. If it contains sentence fragments or long contextual phrases, tighten the candidate filters.
- Review `edited-script-pass.srt` for short cues. Very short cues such as isolated tail characters or sub-0.5s subtitle units belong in Step 2 micro-cue merge guards.
- Use `report.json` to watch `short_cue_count`, `micro_cue_examples`, `suspicious_glossary_terms`, and `finalizer_change_count` during regression work.
- When someone asks whether the pipeline is already usable on a real audio, inspect a real run directory first rather than answering from test status. The most useful artifacts are `edited.srt` for visible delivery quality and `final_delivery_audit.json` for pass/fail plus concrete findings. In this project, production-like replay outputs have been kept under `~/Downloads/Transcribe TEST/`, and that directory can serve as the first regression gallery before diving into code.
- A real FunASR + manuscript run can still start as `manuscript-priority` and downgrade to `raw-priority` at audit time even when mean alignment score looks serviceable. Inspect `alignment_success_rate`, `fallback_region_count`, and `downgrade_count` together rather than trusting the mean score alone.
- Watch for manuscript-backed entity recovery overreach. A recovered term can duplicate nearby wording, as in `一份详细的一份详细的 PPT`, so inspect the recovered raw-word substitution itself before blaming drafting. In the real sample, the structural draft and aligned segment stayed clean while manuscript-backed recovery expanded raw `ppt` into `一份详细的 PPT`, which duplicated the immediately preceding words during raw-span rebuild. A conservative fix is to trim recovered entities when the leading context already contains the same CJK prefix and keep only the entity tail such as `PPT`.
- Watch for manuscript-backed entity recovery underreach. Mixed-script or model-like entities such as `埃安 S` / `埃安 Y` can survive as ASR noise like `ins` / `iny` unless local anchor matching is stronger.
- Watch for manuscript orthography loss on culturally marked terms such as `自働化`. If the manuscript carries the authoritative form, the pipeline needs a preservation path that survives raw-first fallback pressure.
- Step 2A auxiliary glossary calls can time out on real-sample replay. The run still completes on deterministic fallback, so review `run_glossary.json` and the delivered SRT for unresolved entities such as `ins` / `iny` and manuscript orthography regressions when the auxiliary path drops out.
- A dedicated direct DeepSeek provider for Step 2A can restore the live auxiliary path cleanly. On a real-sample replay, direct `deepseek-v4-flash` produced corrections such as `ins -> 埃安 S`, `iny -> 埃安 Y`, and `自动化 -> 自働化`, and those corrections landed in `run_glossary.json` and `edited.srt` while the repeated-fragment defect `一份详细的一份详细的 PPT` remained as a separate Step 3 quality problem.
- A replay from an existing `raw.json` can expose contract conflicts even when Step 1 is blocked by a missing ASR key. In the current mainline, Step 2A can stay clean and punctuation-free while Step 2B rebuilds low-confidence regions from raw token spans and reintroduces punctuation from `word.punctuation`. If `rebuild_segments_from_raw()` joins raw tokens with punctuation and the pipeline still enforces a punctuation-free gate on rebuilt `aligned_segments` or `edited-script-pass.srt`, a real sample can fail in Step 2B despite a successful LLM draft. Treat this as a design-boundary signal: Step 2B rebuild validation should focus on timing/span consistency, and the final punctuation-free delivery gate belongs at Step 3 unless the rebuild path explicitly strips punctuation.
- DeepSeek `deepseek-v4-flash` in official thinking mode can consume the whole completion budget in `reasoning_content` and leave `message.content` empty when `max_tokens` is too small for Step 2A's long JSON output. The durable fix on this project path is: call the official endpoint with explicit `thinking={type: enabled}`, `reasoning_effort=high`, and `response_format={type: json_object}`; raise Step 2A output budget to at least `32768`; and let the parser inspect both `message.content` and `reasoning_content`, with a clear `finish_reason=length` error when no final JSON arrives.
- On the production replay sample, both a long segmentation prompt and a short priority-ordered prompt succeeded after the official DeepSeek V4 request shape and parser fix landed. The short prompt produced slightly cleaner boundaries on this case, with fewer start-particle artifacts and fewer micro-cue fragments, while the long prompt still produced a few more structure-splitting issues. Prefer the short priority-ordered prompt as the default Step 2A direction unless a specific regression shows the need for extra guidance.
- A third soft prompt variant that explicitly asked for mixed-script entity integrity and short rhythm-beat preservation restored useful beats such as `还没完` / `恭喜你` and preserved blocks like `A阶段和B阶段` and `日本JR福知山线的脱轨事故`, but it also over-fragmented the sample, increased short lines, and still collapsed mixed-script spacing in output lines like `埃安S` / `岚图Free`. Treat this as a useful probe rather than the new default. The current best default remains the short priority-ordered prompt, and the next prompt iteration should target mixed-script spacing more directly without adding more beat-splitting pressure.
- On the same replay sample, the checked-in short prompt later regressed on the 17-unit gate and failed contract validation, while a spacing-focused short variant succeeded twice and preserved mixed-script shapes such as `埃安 S`, `岚图 Free`, `A 阶段`, and `JR 福知山线`. That variant also pushed the draft toward over-splitting, including a second run with many very short lines. Treat this as a directionally correct probe: mixed-script spacing needs an explicit local reminder.
- A follow-up spacing-lite short variant that softened the reminder to local mixed-script spacing stability still failed twice on the same replay, once with `subtitle_lines[52]` containing punctuation and once with `subtitle_lines[37]` exceeding the 17-unit cap. Treat this as evidence that a milder wording alone does not recover stability. The next prompt iteration should harden contract obedience around punctuation-free output and the 17-unit cap before trying another spacing-only refinement.
- A later Grok-written readability-first prompt with explicit sample calibration improved local structure on repeated direct probes around the target sections. It often produced cleaner HPS segmentation such as `因为本田的管理理念` / `是脱胎于精益生产的 HPS`, and it usually kept the `现在的新能源车` block readable. But it was still contract-unstable on the same replay: repeated probes showed stray punctuation on lines like `假如有A-B-C-D几个生产流程`, occasional 18-unit lines, and one full `build_step2a_artifacts()` replay falling back to bootstrap because the auxiliary response failed validation. Treat this prompt as directionally useful for readability, but not yet pipeline-stable until punctuation-free obedience and the 17-unit cap are re-hardened.
- A later hardening pass found a second contract drift inside the same Step 2A prompt: the body still ended with legacy free-form labels `proofread_manuscript:` / `subtitle_draft:` even though the wrapper requires JSON keys `proofread_text` / `subtitle_lines`. That drift can surface as `Auxiliary drafting payload missing proofread_text`. Keep the prompt body aligned with the JSON contract whenever Step 2A wording is edited.
- On the production replay sample, adding explicit no-punctuation serial-token guidance for cases like `A-B-C-D -> A B C D`, restoring the JSON field names, and adding hard-cap calibration examples improved the failure shape: punctuation alerts dropped out, and 2 of 3 replay runs completed with `0` Step 2A over-limit lines. The remaining unstable cases still cluster around the same long explanatory lines such as `他们会考虑好我们国内的法规道路情况等` and `东本和广本基本就决定个车内外颜色啥的`, so the next prompt iteration should target those long-clause cuts directly rather than reopening mixed-script spacing work.
- When the user wants to replay from existing FunASR output without re-running ASR, use `scripts/pipeline.py --replay-from-raw /path/to/raw.json --output-dir /path/to/replay-run`. This rebuilds `input_preflight.json`, `mode_decision.json`, `run_glossary.json`, `proofread_manuscript.json`, `subtitle_draft.json`, `aligned_segments.json`, `alignment_audit.json`, `edited-script-pass.srt`, `report.json`, and `agent_review_bundle.json` without rerunning ASR. Keep the copied `raw.json` inside the new run directory so the replay remains auditable.
- On a replay with the new 17-unit segmentation rules, verify all three stages separately: `subtitle_draft.json`, `edited-script-pass.srt`, and `edited.srt`. A real sample showed `subtitle_draft.json` at 0 lines over 17, `edited-script-pass.srt` reintroducing overlong lines in rebuild regions, and `edited.srt` still retaining one over-17 line after Step 3. This means Step 2A hard-cap enforcement can be correct while Step 2B rebuild still stretches lines past the display limit.
- If one or two over-17 lines remain after replay, inspect `alignment_audit.json` first. In the current workflow, the most likely source is `rebuild_regions`, where Step 2B replaces clean draft boundaries with raw-span text. Compare the affected cue in `subtitle_draft.json`, `aligned_segments.json`, and `edited.srt` to confirm whether rebuild, rather than Step 2A or Step 3, introduced the regression.
- When a rebuilt raw span exceeds the 17-unit cap while the original aligned text is already within 17 and still highly similar to the raw rebuild, keep the aligned text instead of the rebuilt raw text. This preserves the Step 2A boundary on low-confidence rebuild regions where raw-only fallback merely reintroduces filler like `啊` / `这个` and stretches the line past the display cap.
- If Step 3 reports `aligned_segments_mismatch`, inspect `subtitle_draft.json` and `aligned_segments.json` for skipped `line_id` values before blaming the finalizer. In the bootstrap path, a punctuation-only draft line can be stripped to empty and dropped. `line_id` must then be recomputed from the filtered non-empty lines so `aligned_segments[].line_id` stays consecutive and matches the cue indexes passed into Step 3.
- If adjacent subtitle lines show end/start duplication, split the diagnosis into two paths before changing code. First compare `subtitle_draft.json`, `aligned_segments.json`, `edited-script-pass.srt`, and `edited.srt` for the same cue pair. If the duplication appears only after Step 2B on a low-confidence cue, inspect `alignment_audit.json` and the raw token slice for that cue. The usual cause is raw-span rebuild reintroducing a prefix already consumed by the previous line, as in `精益生产` followed by rebuilt `生产的这个 HPS`.
- If the duplicated boundary already exists in `subtitle_draft.json`, inspect Step 2A segmentation rather than rebuild. The durable fix is protected-span-aware segmentation before line splitting. The current bootstrap path now keeps glossary-backed and pattern-backed protected spans intact at the 17-unit boundary for cases like `提交 PPT` and `Claude Code`, and Step 2B now applies an overlap-trim guard after raw-span rebuild on rebuilt low-confidence cues.
- If a one-character cue such as `程` survives into `edited.srt`, trace it across `subtitle_draft.json`, `edited-script-pass.srt`, and `edited.srt` before changing Step 3. If the fragment already exists in `subtitle_draft.json`, the root cause is Step 2A bootstrap splitting rather than alignment or finalization. In the current bootstrap path, `_split_long_piece()` can cut at the 17-unit boundary inside a lexical unit, producing tails like `生产流` / `程`. The durable fix is a Step 2A split guard for word-tail fragments and single-character residue, rather than trying to clean it up only at the end.
- If a boundary like `精益生产` / `的这个 HPS` appears in `edited.srt`, compare the same cue pair in `subtitle_draft.json` and `edited-script-pass.srt`. A common pattern is: Step 2A draft creates a stiff but acceptable split such as `精益生产` / `的 HPS`, then Step 2B rebuild on a low-confidence region reintroduces spoken filler from raw timing, yielding `的这个 HPS`. Treat this as a rebuild-policy problem. When the draft boundary is already semantically cleaner and the raw rebuild only adds filler like `这个` or `啊`, prefer the aligned draft text.
- If a micro-cue survives to `edited.srt` even though the adjacent cue boundary is suspicious, inspect `aligned_segments.json` and `alignment_audit.json` for where the warning signal is attached. The current Step 3 controlled micro-cue merge keys off the micro-cue's own warning or rebuild signal. A case like `生产流` / `程` can evade merge when the left cue carries `skipped leading raw characters` and the right micro-cue carries no warning. The next hardening step is to let Step 3 consider neighboring boundary evidence, not only per-cue flags.
- Use the user's hand-cut segmentation as a calibration reference, with priority on overall subtitle readability rather than line-by-line imitation. Evaluate Step 2A prompt variants by reading the whole subtitle file for smooth flow, moderate segmentation density, stable rhythm, and absence of awkward tails or broken terms. Keep `34-39` and `53-55` as useful probe groups for long explanatory cadence and HPS structure, while allowing alternate cuts when the full-file reading experience is clearly smoother.
- Bailian FunASR via `dashscope` SDK should use `https://dashscope.aliyuncs.com/api/v1` as `base_http_api_url`. The OpenAI-compatible endpoint `https://dashscope.aliyuncs.com/compatible-mode/v1` can return HTTP 400 during `Files.upload`, so use the API-v1 endpoint for live FunASR runs.
- A live full-flow run can still fail with `No API-key provided` even when the endpoint is correct. In that case, treat the problem as current-session credential visibility first. Check the live Hermes environment and `launchctl getenv` on macOS for `DASHSCOPE_API_KEY`, `BAILIAN_API_KEY`, `FUNASR_API_KEY`, and `ALIYUN_BAILIAN_API_KEY`. If they are empty in the active run, Step 1 is blocked.
- When Step 1 is blocked, keep the active path FunASR-first: restore credential visibility or replay from an existing FunASR `raw.json`. Do not generate a new local `faster-whisper` `raw.json` as part of the active workflow.
- A valid live FunASR key can unblock Step 1 cleanly while leaving the current mainline still review-blocked downstream. On the production sample, a real full-flow run with a working key completed ASR and alignment, then ended with `finalizer_mode=manual-review-required` because Step 2A emitted six over-17 lines (`12, 28, 29, 39, 66, 77`) and one punctuation-bearing line (`44: 假如有 A-B-C-D 几个生产流程`). Those exact contract violations propagated unchanged through `edited-script-pass.srt` and `edited.srt`, and Step 3 failed after two auxiliary attempts on `finalized_lines[44] must be punctuation_free`. Treat this pattern as current prompt instability rather than ASR failure.
- Alert strings shaped like `subtitle_lines[37] exceeds 17 display units` refer to subtitle line id `37`, not to a count of 37 offending lines. When reviewing over-limit cases, inspect the specific cue ids listed in `alert_tracking.json`, `edited-script-pass.srt`, and `edited.srt`.
- For an agent-owned Step 3 replay, a practical adjudication pass is: scan `edited-script-pass.srt` for over-17 lines, punctuation-bearing cues, mixed zh-en tokens, and tail timing collapses; normalize local mixed-script spacing such as `埃安 S`, `岚图 Free`, `A 阶段`, and `PPT`; then write `edited.srt`, `correction_log.json`, `final_delivery_audit.json`, and update `report.json`. Keep delivery checks and alignment risk separate: a run can reach `0` punctuation violations and `0` over-limit lines while still staying `adjudicated_needs_review` because `post_alignment_mode=raw-priority`, high `fallback_region_count`, or multiple downgraded regions still make the overall delivery risk high.
- If you are auditing an older replay artifact whose `raw.json` did not come from FunASR, watch the ending especially closely for manuscript drift plus collapsed timing. A real sample showed the closing CTA lines all inheriting the same final raw token span, which produced six overlapping 0.24s cues at the end of `edited-script-pass.srt`. When that happens, compare the tail of `edited-script-pass.srt`, `aligned_segments.json`, and localized audio evidence. If the audio has already moved into the closing CTA while the script pass still carries earlier manuscript wording, treat it as a manuscript-drift region and rebuild the tail cues from audio evidence rather than trusting the carried manuscript sequence.
- A Step 3 pass that fixes long lines by inserting `\n` inside one existing cue is still the wrong delivery shape for this workflow. The target behavior is true cue-level re-segmentation: create new subtitle cues with new timing boundaries when rhythm and timing evidence support the split. Treat internal line wrapping inside one unchanged timestamp as a bug to report, not a valid substitute for cue splitting.
- Subtitle length policy should target comfortable rhythm rather than bare compliance. Around 12 Chinese-character-equivalent units per cue is the preferred center, and 17 units is the hard maximum. A line that passes the 17-unit cap can still need splitting when a natural semantic boundary would produce a shorter, smoother subtitle.

## Practical review checklist

When a previously working Bailian / DashScope key seems to have disappeared:
- Check the live agent process environment first. A key can exist in a past shell session and still be absent from the current Hermes run.
- Check common variable names: `DASHSCOPE_API_KEY`, `BAILIAN_API_KEY`, `FUNASR_API_KEY`, and `ALIYUN_BAILIAN_API_KEY`.
- Inspect shell startup files and nearby project `.env` files, then check platform-specific environment stores if relevant.
- On macOS, `launchctl getenv KEY` can help confirm whether the key is present in the user launch environment.
- If all checks are empty, treat the key as unavailable for the current run and either restore it explicitly or replay Step 2 / Step 3 from an existing `raw.json`.

## Practical review checklist

On a real sample, check these first:
1. `run_glossary.json` contains mostly real terms like product names, acronyms, and mixed-script entities.
2. `edited-script-pass.srt` has no obvious burst of tiny trailing cues.
3. `edited.srt` improves casing and zh-en spacing without broad rewriting.
4. `report.json` is rich enough to expose short-cue counts, suspicious glossary terms, and finalizer change counts.

## Current design pressure

The user's real workflow is manuscript-first subtitle production:
1. proofread the manuscript against audio
2. semantically segment it into one subtitle line per unit
3. align those lines back onto audio timing

The intended control shape is two-model-led rather than script-led:
- the Step 2A auxiliary model and Step 3 Hermes are the primary decision-makers for proofreading, semantic segmentation, rewriting, and final subtitle judgment
- scripts should support the model path with alignment, serialization, validation, report generation, and alerts
- scripts should not hold broad text-rewrite authority over model output
- if a script layer frequently overrides model structure or wording, treat that as architecture drift away from the target workflow

When redesigning or reviewing the pipeline, treat manuscript matching and model-led subtitle judgment as the core path.

Implementation warning from live review:
- the pipeline can drift into script-led behavior even while auxiliary drafting exists
- that drift usually shows up when deterministic finalizer rules and fallback paths gain stronger control than the model outputs
- if you see the system described as "model drafts, scripts decide," treat that as a design-smell against the user's target architecture unless the task is explicitly a temporary hardening phase
- when reviewing the current Step 3 chain, check prompt and doc drift before deeper refactors. A live prompt that still says cue count must stay unchanged conflicts directly with the cue-splitting contract and is release-blocking.
- if `references/minimal-execution-contract.md` still describes deterministic bootstrap drafting as the current runtime, treat it as obsolete contract drift. Prefer deleting it over maintaining a second stale workflow summary.
- if the skill docs promise replay from an existing `raw.json`, prioritize adding a narrow replay entrypoint on the existing `scripts/pipeline.py` CLI before larger architectural cleanup. The smallest useful shape is a `--replay-from-raw` style path that rebuilds Step 0 through Step 2 handoff artifacts and `agent_review_bundle.json` without rerunning ASR.
- when reprioritizing maintenance work, use this order: Step 3 prompt and workflow-doc truth first, replay usability second, Step 3 auxiliary-finalization removal third, god-file splitting after that.

Review checklist for architecture drift:
- check whether `drafting_mode` is frequently `llm-primary` / `llm-primary-with-alerts` or frequently collapsing into `manual-review-required`
- check whether Step 3 is a real model adjudicator or still a deterministic placeholder
- check whether final text decisions are being made by model outputs or by post-hoc script normalization/resegmentation
- preserve script authority for timing evidence and safety rails, while shifting text-quality authority back toward the model path

When real samples expose quality problems, inspect Step 2 first:
- over-wide glossary extraction
- missing short-cue merge guard
- boundary protection that preserves bad fragments
- lack of manuscript-line to token-span alignment for user-provided one-line subtitle drafts

Keep the script layer as guardrails. Push subtitle-quality judgment toward the model path.

## Active workflow boundary

The user wants this control shape kept explicit in workflow docs and skills:
- Step 1 = FunASR only
- Step 2 = configured auxiliary model plus pipeline guardrails
- Step 3 = the live interactive agent session itself, such as Hermes or OpenClaw, reading Step 2 artifacts and performing the final audit, judgment, and subtitle edits

Operational interpretation:
- Step 3 should read Step 2 outputs such as `edited-script-pass.srt`, `proofread_manuscript.json`, `aligned_segments.json`, `alignment_audit.json`, `run_glossary.json`, and `report.json`
- Step 3 should use `edited-script-pass.srt` as the editable base unless a migration task explicitly changes that contract
- Step 3 rules belong in `SKILL.md` / workflow docs rather than long-term memory
- Treat any active `step3.auxiliary_model` backend path as legacy or transitional architecture when reviewing the system
- Prefer a handoff artifact such as `agent_review_bundle.json` and a report state like `awaiting_agent_review` over silently running another configured model inside the pipeline
- Avoid silent fallback from Step 3 to another backend model path; if the live system still has that path, treat it as architecture drift and call it out explicitly

## One-line reminder
Step 2 owns structure. Step 3 / Hermes owns delivery judgment.
