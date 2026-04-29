# Transcribe Hybrid Architecture Draft

## Goal

Build a subtitle pipeline that delivers:
- audio-grounded timing
- manuscript-aware text quality
- semantic subtitle lines with good reading flow
- stable fallback behavior across clean and messy inputs

## Core idea

The long-term mainline is a hybrid system with two operating modes:
- **manuscript-priority** for read-script, near-verbatim, high-quality manuscript inputs
- **raw-priority** for weak-manuscript, improvised, or mismatch-heavy inputs

Both modes share one timing anchor:
- `raw.json` from FunASR remains the only primary source for observed audio timing

Both modes share one delivery contract:
- final output remains `edited.srt`
- all timing-bearing subtitle lines must trace back to raw token spans or approved fallback aligners

## Design principles

1. Keep audio facts primary.
2. Use LLMs for text decisions: proofreading, entity adjudication, semantic line drafting.
3. Use deterministic modules for timing decisions: token-span alignment, interpolation, validation, fallback.
4. Keep manuscript matching as a first-class path.
5. Keep raw-priority as a stable safety path.
6. Make routing explicit through a decision gate.
7. Log mode choice, confidence, and fallback reasons in the report.

## Operating modes

### Mode A — manuscript-priority
Use when:
- manuscript exists
- manuscript is complete enough for subtitle drafting
- manuscript and raw ASR have high local and global match confidence
- content is read-script, lecture, product demo, narration, TTS, or controlled delivery

Behavior:
1. proofread manuscript against raw/audio clues
2. produce polished subtitle draft lines, one semantic unit per line
3. align drafted lines back to raw token spans
4. interpolate inside tokens only when required
5. run conservative final checks

### Mode B — raw-priority
Use when:
- manuscript is absent, partial, outline-like, or clearly post-written
- manuscript and raw ASR differ materially
- content is interview, conversation, livestream, vlog, or improvised speech

Behavior:
1. preserve raw transcript as the main text anchor
2. use manuscript only for local entity correction and terminology hints when confidence is high
3. derive subtitle structure from raw tokens plus lightweight semantic grouping
4. run conservative final checks

## Decision gate

Create a routing stage after `raw.json` is available.

### Inputs to routing
- manuscript presence
- manuscript completeness score
- raw/manuscript global similarity score
- local alignment confidence on sampled windows
- speaking style signals: single-speaker vs multi-speaker, improvised cues, filler density, timing volatility
- optional user override: `mode=manuscript-priority|raw-priority|auto`

### Routing outcome
Return:
- chosen mode
- confidence score
- reasons list
- fallback recommendation if confidence is weak

### Suggested thresholds
- manuscript-priority candidate: global similarity >= 0.90 and sampled local confidence >= 0.85
- hybrid warning band: global similarity 0.80-0.90 or unstable local windows
- raw-priority: global similarity < 0.80, incomplete manuscript, or strong improvised-speech signals

Thresholds should stay configurable and data-driven.

## Stage layout

### Step 0 — input validation and preprocessing
Outputs:
- `input_preflight.json`
- optional normalized manuscript working text

Responsibilities:
- validate audio, manuscript, and run options
- normalize manuscript text for comparison and drafting
- inspect raw prerequisites after ASR is available
- extract early signals for routing such as manuscript completeness, speaker complexity, filler density, and style volatility
- capture user override settings

### Step 1 — ASR timing anchor
Output:
- `raw.json`

Responsibilities:
- call FunASR
- preserve transcript text, segments, words, and timing unchanged
- attach backend metadata and confidence fields when available

### Step 2 — routing and manuscript assessment
Outputs:
- `mode_decision.json`
- optional `manuscript_assessment.json`

Responsibilities:
- compare normalized manuscript and raw transcript
- score completeness, similarity, and local match quality
- choose manuscript-priority or raw-priority
- store decision reasons and confidence

### Step 3 — text refinement and subtitle drafting
Outputs:
- `proofread_manuscript.json`
- optional `proofread_diff.json`
- `subtitle_draft.json`
- optional `subtitle_draft.txt`

Responsibilities:
- keep LLM work inside strict text boundaries
- produce subtitle-ready semantic lines with reading constraints
- preserve factual meaning, speaking intent, and entity integrity
- log material edits and drafting notes

Mode behavior:
- manuscript-priority:
  1. proofread manuscript against raw/audio clues
  2. reconcile entities, acronyms, models, and mixed-script terms
  3. draft one-line-per-subtitle semantic lines from the proofread manuscript
- raw-priority:
  1. keep raw transcript as the main text anchor
  2. apply only high-confidence local manuscript hints such as entity correction
  3. draft subtitle lines from raw transcript structure with light semantic grouping

Rules:
- preserve order
- preserve factual meaning
- keep broad stylistic rewriting outside the mainline
- keep subtitle constraints explicit: max chars, max reading seconds, punctuation policy, entity protection

### Step 4 — line-to-audio alignment
Outputs:
- `aligned_segments.json`
- `edited-script-pass.srt`

Responsibilities:
- align each drafted subtitle line to a continuous raw token span
- keep glossary entities unbroken
- apply token-internal interpolation when a line boundary falls inside a raw token
- score each aligned line and the whole pass
- emit warnings and fallback reasons

Recommended algorithm:
1. normalize draft lines and raw tokens
2. protect glossary entities and approved recovered entities
3. run sequential constrained DP or Viterbi alignment from lines to token spans
4. penalize overly long spans, skipped spans, and unstable timing jumps
5. interpolate character boundaries inside tokens with weighted interpolation
6. downgrade low-confidence regions to safer raw grouping rules

### Step 5 — alignment audit and mode downgrade
Outputs:
- `alignment_audit.json`

Responsibilities:
- review aggregate and local alignment quality
- decide whether the run stays in the chosen mode
- downgrade weak regions or the whole run to raw-priority behavior when needed
- record downgrade reasons, fallback counts, and keep-vs-rebuild decisions

### Step 6 — conservative final delivery
Outputs:
- `edited.srt`
- `report.json`
- optional `final_delivery_audit.json`

Responsibilities:
- apply light zh-en spacing and casing cleanup
- enforce delivery constraints
- preserve aligned timing unless a tiny corrective adjustment is justified
- summarize mode choice, alignment quality, downgrade decisions, fallback counts, entity recovery counts, and final status

## Contracts

### `input_preflight.json`
Fields:
- `audio_ok`
- `manuscript_present`
- `manuscript_length`
- `normalized_manuscript_length`
- `speaker_complexity_signals`
- `style_volatility_signals`
- `user_override`
- `warnings`

### `mode_decision.json`
Fields:
- `mode`
- `confidence`
- `global_similarity`
- `local_similarity_samples`
- `manuscript_completeness`
- `signals`
- `reasons`
- `user_override`

### `proofread_manuscript.json`
Fields:
- `source_text`
- `proofread_text`
- `edit_summary`
- `material_edits`
- `entity_decisions`

### `subtitle_draft.json`
Fields:
- `lines`: array of
  - `line_id`
  - `text`
  - `source_mode`
  - `draft_notes`

### `aligned_segments.json`
Fields:
- `segments`: array of
  - `line_id`
  - `text`
  - `start`
  - `end`
  - `raw_token_start_index`
  - `raw_token_end_index`
  - `split_points`
  - `alignment_score`
  - `protected_entities`
  - `warnings`
- `summary`
  - `line_count`
  - `mean_alignment_score`
  - `low_confidence_count`
  - `interpolated_boundary_count`
  - `fallback_region_count`

### `alignment_audit.json`
Fields:
- `chosen_mode`
- `post_alignment_mode`
- `mean_alignment_score`
- `downgraded_regions`
- `rebuild_regions`
- `fallback_region_count`
- `reasons`

### `report.json`
Should include at minimum:
- chosen mode and confidence
- post-alignment mode
- route decision reasons
- glossary term count
- entity recovery count and examples
- alignment success rate
- low-confidence alignment count
- interpolated boundary count
- fallback region count
- downgrade count
- finalizer change count
- final delivery status

## Fallback strategy

### Local fallback
If one region aligns poorly:
- keep the draft text when confidence remains acceptable
- snap timing to a safer raw token grouping
- mark warning fields in `aligned_segments.json`

### Segment fallback
If a draft segment fails alignment:
- rebuild that region from raw tokens using conservative segmentation
- keep manuscript text as a reference note rather than delivered text when mismatch is high

### Mode fallback
If manuscript-priority routing confidence drops during alignment:
- downgrade the run or the affected region to raw-priority behavior
- keep the decision and reason in `report.json`

### Heavy fallback
Introduce forced alignment only when:
- manuscript-priority is requested or strongly indicated
- alignment quality stays low after DP and interpolation
- raw/manuscript mismatch appears local rather than global
- user enables high-precision mode or project policy requires it

## LLM boundaries

### LLM owns
- proofreading
- entity adjudication when evidence is sufficient
- semantic line drafting
- optional explanations for material edits

### Deterministic modules own
- routing scores
- token-span alignment
- interpolation
- confidence scoring
- fallback selection
- final timing integrity checks

## Suggested implementation order

### Phase 1
Add input preflight and routing artifacts without changing final delivery behavior.
- implement `input_preflight.json`
- implement `mode_decision.json`
- keep current raw-based segmentation path as the stable baseline

### Phase 2
Add text refinement and drafting.
- implement `proofread_manuscript.json`
- implement `subtitle_draft.json`
- keep alignment experimental behind a flag

### Phase 3
Implement robust line-to-audio alignment and audit.
- add `aligned_segments.json`
- produce `edited-script-pass.srt` from aligned segments
- add interpolation and confidence scoring
- implement `alignment_audit.json`

### Phase 4
Turn on automatic mode selection and downgrade flow.
- default to `auto`
- retain manual override
- enable post-alignment downgrade to raw-priority behavior

### Phase 5
Add optional heavy fallback.
- integrate a forced aligner for high-precision or failure-recovery paths only

## Validation plan

A healthy run should satisfy:
- `raw.json` remains unchanged
- chosen mode matches input quality and user intent
- drafted lines read naturally
- aligned lines map cleanly to raw timing
- entity-heavy lines stay intact
- fallback activates gracefully on weak regions
- final subtitle stays faithful to audio and readable on screen

## Recommended near-term target

The next core capability is Step 4 line-to-audio alignment.
That module is the bridge between high-quality drafted subtitle text and stable audio timing.
