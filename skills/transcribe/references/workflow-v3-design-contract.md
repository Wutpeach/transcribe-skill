# Workflow v3 Design Contract

Consolidated from the retired `transcribe-workflow-v3` skill directory.
`transcribe` remains the only active execution skill.

# Transcribe Workflow v3

Use this reference when redesigning, implementing, or reviewing the transcription pipeline.

## Core contract

The workflow has three explicit stages:

1. **Step 1 — ASR / timing**
   - Output: `raw.json`
   - `raw.json` is the source of truth.
   - Keep original text, segments, words, and timing for traceability.
   - This stage does not do text cleanup or segmentation.

2. **Step 0 / Step 2 — preflight + routing**
   - Outputs: `input_preflight.json`, `mode_decision.json`
   - Assess manuscript presence and quality before drafting.
   - Route between `manuscript-priority` and `raw-priority`.
   - Keep warning-band cases observable.
   - Allow explicit user override.

3. **Step 2A — run glossary prep + structure building**
   - Outputs: `run_glossary.json`, `proofread_manuscript.json`, `subtitle_draft.json`, `aligned_segments.json`, `edited-script-pass.srt`
   - Optional debug output: `semantic_segments.json`
   - If manuscript is present, extract a temporary per-run glossary with canonical terms, aliases, and casing guidance.
   - If manuscript is absent, still emit an empty or minimal `run_glossary.json` so the pipeline shape stays stable.
   - Responsibilities: proofread anchor selection, one-line subtitle drafting, protected-span preservation, line-to-audio alignment, and post-segmentation micro-cue merge guards.
   - Subtitle draft text should target delivery-style plain text without punctuation symbols.
   - Keep the glossary narrow: acronyms, models, mixed-script entities, and casing anchors.
   - This stage decides boundaries and structure.
   - This stage stays narrow enough that a redesign can replace its internals without changing the workflow contract.

4. **Step 5 — alignment audit and downgrade**
   - Output: `alignment_audit.json`
   - Review alignment quality before final delivery.
   - Downgrade weak manuscript-priority runs to `raw-priority` conservatively.
   - Rebuild flagged regions from raw timing spans before Hermes final.

5. **Step 3 — Hermes final adjudication**
   - Outputs: `edited.srt`, `report.json`
   - Optional gate/debug outputs: `final_delivery_audit.json`, `correction_log.json`
   - Responsibilities: term/casing cleanup, mixed zh-en spacing handling, conservative text fixes, final review, and delivery gate.
   - Hermes is the only explicit final authority in this stage.
   - Step 3 owns the delivered subtitle text and may absorb quality work that earlier versions tried to distribute across Step 2A.
   - Future Hermes-managed drafting should reuse the same `proofread_manuscript.json` and `subtitle_draft.json` contracts.
   - Current Step 3 mainline covers A/B-grade delivery edits: deterministic glossary normalization, spacing cleanup, surface punctuation cleanup, duplicate-fragment collapse, and small local delivery-noise cleanup.
   - A narrow v1.1 hook now exists for controlled consecutive micro-cue merge. It requires explicit `aligned_segments` warnings or alignment-audit region evidence, records `delivery_resegmentations`, and writes `resegment_source` into delivery audit artifacts.
   - Step 3 micro-cue resegmentation guardrails now include a protected-boundary veto. Before merging consecutive micro-cues, check glossary-backed protected terms, `aligned_segments[].protected_entities`, and proofread local line boundaries. Skip the merge when it would cross an entity boundary that the proofread keeps separate.
   - Step 3 audit should expose machine-readable cue diffs for every text or structure change. Keep `cue_diffs` aligned across `correction_log.json` and `final_delivery_audit.json`, with `target_cue_index`, `source_cue_indexes`, `before_cues`, `after_cues`, `change_types`, and `resegment_source`.
   - When Step 3 consumes auxiliary inputs like `aligned_segments.json` or proofread artifacts, validate schema/version and cue consistency first. On validation failure, fall back to A-grade rules and skip evidence-gated structural edits while recording the fallback reason in delivery audit/report artifacts.

## Authority order

Use this order whenever there is conflict:

`audio facts > raw timing/text evidence > protected term boundaries from run_glossary > manuscript local clues > Hermes judgment`

Implications:
- Audio stays primary.
- Manuscript is reference material.
- `run_glossary.json` provides local normalization guidance.
- Hermes owns the final delivery judgment.

## Artifact policy

### Keep by default
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

### Keep in debug mode
- `semantic_segments.json`
- `final_delivery_audit.json`
- `correction_log.json`

### Minimal `report.json`
Keep `report.json` compact:
- basic timing metadata
- segmentation stats
- whether `run_glossary.json` was applied
- short-cue count and sample micro-cues
- suspicious glossary terms
- manuscript-backed entity recovery count and examples
- finalizer change count
- final delivery status

Do not let `report.json` become a second workflow engine.

### Downgrade from first-class artifacts
Treat these as internal or debug-only unless there is a specific reason to expose them:
- `corrected_plaintext.md`
- `corrected_timing_payload.json`
- `multimodal-review.json`

## Design simplifications

### Old system status
The older transcribe system is retired from the active mainline.

Treat these legacy ideas and modules as archive-only unless a migration task explicitly revives them for reference:
- multi-layer glossary architecture
- glossary candidate accumulation
- glossary promotion flows
- standalone auxiliary review authority stages
- intermediate text-rewrite stages before Hermes final
- report schemas that mirror legacy multi-stage control flow

Do not spend active maintenance effort on the retired path.

### Glossary model
Use a single per-run glossary.

Remove or avoid:
- global glossary stores
- glossary candidate accumulation
- promotion logs
- promoted-term pipelines

The glossary is a local helper for the current run, not a long-term terminology platform.

### Review model
Do not model auxiliary review as a separate external authority stage.

If auxiliary models are used, they act as internal support for Hermes. The external workflow should still expose a single final adjudicator: Hermes.

## What to preserve from older versions
Keep these pieces if they already exist:
- FunASR API as the preferred ASR path
- `raw.json` as grounded source material
- timing-aware rebuild logic
- protected spans, validators, and fallback infrastructure
- the two-stage delivery shape: `edited-script-pass.srt -> edited.srt`

## What to rewrite first
When migrating from an older design, change these first:
1. Rewrite the skill / workflow contract so stage responsibilities are explicit.
2. Add manuscript-first drafting as the practical workflow anchor: proofread manuscript, semantically segment to one line per subtitle, then align lines back to raw timing.
3. Keep the long-term architecture hybrid rather than pure manuscript-first: route between manuscript-priority and raw-priority after assessing manuscript completeness, raw/manuscript similarity, and speaking-style signals.
4. Add explicit preflight, routing, alignment-audit, and mode-downgrade stages so weak manuscript runs can fall back gracefully.
5. Remove multi-layer glossary architecture.
6. Collapse intermediate text-rewrite stages into Hermes Step 3 unless manuscript adjudication and semantic line drafting are promoted into explicit pre-alignment stages.
7. Simplify report schema so it reflects the new authority model.

## Short checklist for future reviews
A healthy v3 run should satisfy all of these:
- `raw.json` is preserved unchanged.
- `run_glossary.json` exists only for the current run.
- Manuscript quality is assessed before mode selection.
- The pipeline can route between manuscript-priority and raw-priority behavior.
- Text drafting and timing alignment stay separate.
- Alignment audit can downgrade weak regions or whole runs before delivery.
- Step 3 / Hermes owns final polish and adjudication.
- Final delivery passes an explicit audit gate before release.

## Architecture drift warning

In review, watch for implementation drift from the user's intended control shape.

Target shape:
- Step 2A is model-led for proofreading, semantic segmentation, and local text decisions.
- Step 3 / Hermes is model-led for final subtitle judgment.
- Script layers keep authority over timing evidence, downgrade, rebuild, validation, protected boundaries, and auditability.

Prompt-shape guidance for subtitle segmentation:
- Prefer a short priority-ordered prompt over a long rule checklist.
- Keep one hard display constraint: each delivered subtitle line must stay within 17 Han-character-equivalent units.
- Express other segmentation guidance as high-level priorities rather than brittle micro-rules.
- Recommended priority order: line-length cap first, then natural semantic pause and spoken rhythm, then protected term / name / model integrity, then context-sensitive handling of filler and discourse particles.
- Do not instruct the model to mechanically delete all particles. Keep or trim them based on whether they carry rhythm, stance, or speaker voice.
- The goal is human-acceptable reading flow rather than rule-satisfaction by itself.

Drift signal:
- If the system behaves like "model drafts, scripts decide," the implementation has become more script-led than the user wants.
- That shape is acceptable as a temporary hardening phase.
- It is not the desired end state for this workflow.

## One-line reminder
The center of v3 is simple: **model-led subtitle judgment with script guardrails around timing, validation, and audit.**
