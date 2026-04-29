# Implementation Plan

## Goal

Build the smallest active hybrid transcription pipeline that stays grounded in `raw.json` while supporting manuscript-priority and raw-priority delivery.

Current runnable shape:

`FunASR -> raw.json -> input_preflight.json -> mode_decision.json -> run_glossary.json -> proofread_manuscript.json -> subtitle_draft.json -> aligned_segments.json -> alignment_audit.json -> edited-script-pass.srt -> edited.srt -> report.json`

Real user workflow target:

`FunASR timing anchor -> manuscript proofreading -> one-line semantic subtitle drafting -> manuscript-line to raw-timing alignment -> audit-driven downgrade when needed -> final delivery`

## Phase 1 — active contract

1. Keep `transcribe` as the active execution skill.
2. Keep v3 design/reference material consolidated under `transcribe/references/`.
3. Treat archived legacy materials as read-only reference.

## Phase 2 — mandatory artifacts

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

Debug-only outputs:
- `semantic_segments.json`
- `final_delivery_audit.json`
- `correction_log.json`

## Phase 3 — stage behavior

### Step 1 — ASR / timing
- FunASR only
- preserve transcript text, segments, words, and timing unchanged
- `raw.json` stays the source of truth

### Step 0 — preflight
- emit `input_preflight.json`
- record manuscript presence, normalized length, style volatility, speaker-complexity proxies, and user override
- keep signals deterministic and small

### Step 2 — routing
- emit `mode_decision.json`
- choose between `manuscript-priority` and `raw-priority`
- keep warning-band cases observable
- allow explicit user override

### Step 2A — structure building
- emit `run_glossary.json`
- emit `proofread_manuscript.json`
- emit `subtitle_draft.json`
- emit `aligned_segments.json`
- emit `edited-script-pass.srt`
- keep glossary extraction narrow: acronyms, models, mixed-script entities, casing anchors
- allow narrow manuscript-backed entity recovery when suspicious ASR fragments match local manuscript anchors and entity count/order
- separate text drafting from timing alignment
- preserve raw timing authority while replacing only recovered entity text
- current runtime uses deterministic bootstrap drafting
- future Hermes-managed drafting should plug into the same `proofread_manuscript.json` and `subtitle_draft.json` contracts
- do zero broad text correction

### Step 5 — alignment audit and downgrade
- emit `alignment_audit.json`
- review mean alignment score, low-confidence regions, interpolated boundaries, and fallback regions
- downgrade weak manuscript-priority runs to `raw-priority`
- rebuild flagged regions from conservative raw timing spans before final delivery

### Step 3 / Hermes final
- use audited subtitle cues as the timing anchor
- apply conservative term/casing fixes
- handle mixed zh-en spacing
- allow light cleanup only
- produce `edited.srt`
- keep `report.json` compact and execution-facing

## Phase 4 — retired ideas

Do not revive these in the active mainline:
- global glossary stores
- glossary accumulation or promotion
- standalone auxiliary review stages
- intermediate text-polishing layers before Hermes final
- oversized report schemas tied to legacy control flow

## Phase 5 — verification

A valid run should prove all of these:
- `raw.json` remains unchanged after ASR
- `input_preflight.json` exists for every run
- `mode_decision.json` exists for every run
- both `manuscript-priority` and `raw-priority` paths have regression coverage
- `subtitle_draft.json` exists in both modes
- `aligned_segments.json` can rebuild `edited-script-pass.srt`
- `alignment_audit.json` can trigger downgrade and rebuild when alignment weakens
- `report.json` exposes route reasons, alignment quality, fallback counts, downgrade count, and entity recovery counts
- `edited.srt` stays readable and timing-grounded
