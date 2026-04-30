---
name: transcribe
description: "Minimal active transcription workflow: FunASR to raw.json, Step 2 / 2A segmentation with per-run run_glossary.json, and Step 3 live-agent final delivery."
version: 1.2.0
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

## Active workflow

### Step 1 — FunASR / timing
Outputs:
- `raw.json`

Rules:
- `raw.json` is the source of truth.
- Preserve transcript text, segments, words, and timing unchanged.
- Keep Step 1 timing-only.

### Step 2 — preflight + routing
Outputs:
- `input_preflight.json`
- `mode_decision.json`

Rules:
- Assess manuscript presence and quality before drafting.
- Keep the first-pass signals deterministic and compact.
- Route between `manuscript-priority` and `raw-priority`.
- Keep warning-band cases observable so later audit can downgrade conservatively.

### Step 2A — glossary prep + structural drafting
Outputs:
- `run_glossary.json`
- `proofread_manuscript.json` (`transcribe.proofread_manuscript.v2`)
- `subtitle_draft.json` (`transcribe.subtitle_draft.v2`)

Rules:
- Step 2A owns proofreading and one-line subtitle segmentation.
- Draft text should stay punctuation-free.
- `17` Han-character-equivalent units is the hard per-line cap.
- `run_glossary.json` is per-run only.
- Keep glossary scope narrow: acronyms, models, mixed-script entities, casing anchors.
- Auxiliary success keeps model text as text authority.
- Auxiliary request or parse failure resolves to `manual-review-required`.
- In `raw-priority`, preserve raw transcript authority and allow only narrow locally anchored entity recovery.

### Step 2B — alignment + script pass
Outputs:
- `aligned_segments.json` (`transcribe.aligned_segments.v2`)
- `edited-script-pass.srt`

Rules:
- Alignment owns timing and span mapping.
- `aligned_segments.json` maps draft lines back onto raw timing with token spans, split points, confidence, and warnings.
- `edited-script-pass.srt` comes from aligned segments rather than direct raw segmentation.
- Keep glossary-boundary protection, protected-span preservation, and same-token collapse guards.
- Keep text authority with the model-owned stages. Use Step 2B for timing, validation, and conservative guardrails.

### Step 2C — alignment audit + downgrade
Outputs:
- `alignment_audit.json`

Optional debug output:
- `semantic_segments.json`

Rules:
- Review aligned line quality before final delivery.
- Downgrade weak `manuscript-priority` runs to `raw-priority` conservatively.
- Mark weak regions and downgrade reasons explicitly.

### Step 3 — Final Adjudication / live agent adjudication
Pipeline handoff outputs:
- `agent_review_bundle.json`
- `report.json`

Final delivery outputs:
- `edited.srt`
- `correction_log.json`
- `final_delivery_audit.json`

Rules:
- Step 3 is owned by the current live interactive agent session.
- Use `raw.json` as the fact anchor.
- Read Step 2 artifacts such as `edited-script-pass.srt`, `proofread_manuscript.json`, `aligned_segments.json`, `alignment_audit.json`, `run_glossary.json`, and `report.json`.
- Use `edited-script-pass.srt` as the default editable base.
- Apply conservative term and casing fixes, mixed zh-en spacing cleanup, light error correction, and cue-level re-segmentation when delivery quality needs it.
- The current Step 3 live agent is the sole final adjudicator.
- Final delivery files are late-bound and should be written by `write_step3_review_artifacts()`.

## Authority order

Use this order whenever there is conflict:

`audio facts > raw timing/text evidence > protected term boundaries from run_glossary > manuscript local clues > Step 3 judgment`

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
- `agent_review_bundle.json`
- `edited.srt`
- `report.json`
- `alert_tracking.json`

Debug only:
- `semantic_segments.json`
- `final_delivery_audit.json`
- `correction_log.json`

## Repository map

Core runtime files:
- `scripts/pipeline.py` — run orchestration and replay entrypoint
- `scripts/funasr_api.py` — Bailian FunASR calls
- `scripts/preflight.py` — manuscript-quality signals
- `scripts/routing.py` — route selection
- `scripts/glossary.py` — per-run glossary build
- `scripts/auxiliary_glossary.py` — live term/entity correction support
- `scripts/drafting.py` — proofread + subtitle draft artifacts
- `scripts/auxiliary_drafting.py` — Step 2A live drafting path
- `scripts/alignment.py` — draft-to-timing alignment
- `scripts/audit.py` — alignment review and downgrade signals
- `scripts/pipeline_report.py` — `report.json` generation and Step 3 state transitions
- `scripts/finalizer.py` plus `finalizer_*` modules — Step 3 helper surface and writeback validation

## Commands

Verification:
```bash
python3 scripts/pipeline.py --help
```

Main run:
```bash
python3 scripts/pipeline.py /path/to/audio.wav \
  --output-dir /path/to/run \
  --manuscript-path /path/to/manuscript.txt
```

Replay from existing `raw.json`:
```bash
python3 scripts/pipeline.py \
  --output-dir /path/to/replay-run \
  --replay-from-raw /path/to/existing/raw.json \
  --manuscript-path /path/to/manuscript.txt
```

Prompt-focused test run:
```bash
PYTHONPATH=scripts pytest tests/test_prompts.py -q
```

## Configuration

Preferred Step 1 credential/config layout:
- Put portable defaults in `config/funasr.toml`.
- Put machine-local secrets in `config/funasr.local.toml` or `.env.local`.
- Include `config/funasr.local.example.toml` when sharing the skill.
- Preferred discovery order is: explicit CLI key, skill-local secret config, skill-local env file, broader host environment.

Step 2A provider notes:
- Public setup should collect an OpenAI-compatible auxiliary `base_url` and `api_key`.
- Step 2A local secrets can live in `.env.local` or `config/auxiliary.local.toml`.
- `scripts/auxiliary_config.py` resolves the Step 2A auxiliary model from `config/models.toml`, `config/transcribe.toml`, skill-local env/config, and the current live agent runtime.
- If the Step 2A auxiliary config is incomplete, provider fallback should resolve against the current live agent session rather than a hardcoded host-specific provider alias.
- Host runtimes can inject that fallback directly or expose it through `CURRENT_LIVE_AGENT_BASE_URL`, `CURRENT_LIVE_AGENT_API_KEY`, `CURRENT_LIVE_AGENT_API_MODE`, and `CURRENT_LIVE_AGENT_PROVIDER_NAME`.
- If the Step 2A auxiliary request itself fails, the current live agent should take over Step 2 drafting work, produce Step 2 artifacts, and still hand the run to Step 3 for the normal final adjudication pass.
- Agent takeover should report `draft_model_provider = "local-helper"` because the fallback artifact comes from local helper logic rather than a second live model call.

## Review checklist

On a real sample, check these first:
1. `run_glossary.json` contains mostly real terms such as product names, acronyms, and mixed-script entities.
2. `edited-script-pass.srt` has no obvious burst of tiny trailing cues.
3. `edited.srt` improves casing and zh-en spacing while preserving audio facts.
4. `report.json` exposes draft mode, alerts, downgrade signals, and final delivery state clearly.

## Workflow boundary

Keep this control shape explicit:
- Step 1 = FunASR only
- Step 2 = configured auxiliary model plus pipeline guardrails
- Step 3 = the current live interactive agent session itself

Step 2 owns structure. Step 3 owns delivery judgment.

## Reference documents

Read these selectively when the task calls for deeper context:
- debugging replay regressions or reviewing real-sample failures → `references/real-run-findings.md`
- changing workflow contracts or authority boundaries → `references/workflow-v3-design-contract.md`
- reviewing implementation sequencing or migration scope → `references/implementation-plan.md`
- performing Step 3 adjudication design or writeback changes → `references/agent-step3-adjudication-contract.md`
- checking final Step 3 output expectations → `references/step3-final-adjudication-contract.md`
