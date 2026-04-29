# Grok Feedback Brief — subtitle segmentation and Step 3 delivery

## Context

This note records issues found in the current real-sample replay output for the active transcription pipeline.

Reference run:
- output dir: `/Users/mabel/Downloads/Transcribe TEST/output-replay-agent-step3-20260428-220359`
- inspected file: `edited.srt`

## What is wrong in the current output

### 1. Step 3 used in-cue line breaks instead of true cue splitting

Observed in `edited.srt`:
- cue 10: `00:00:24,440 --> 00:00:27,500`
- cue 12: `00:00:31,400 --> 00:00:34,147`

Current behavior:
- one subtitle cue keeps the same single time range
- text is split into two display lines with an internal newline
- no new cue is created
- no new sub-timestamps are assigned

Why this is a problem:
- the desired delivery behavior is true subtitle re-segmentation when a line is too long
- long content should become multiple subtitle cues with new timing boundaries when the rhythm clearly supports it
- a two-line block inside one timestamp is not the target output shape for this workflow

Required direction:
- when Step 3 decides a subtitle should be split for delivery, it should be able to split one cue into multiple cues
- the split should create new cue indexes and new timing boundaries grounded in aligned timing evidence
- Step 3 should not treat internal newline insertion as the default substitute for cue-level re-segmentation

### 2. Seventeen characters is a hard ceiling, not the ideal target

User review finding:
- some lines at or near 17 display units are still visually too long
- they can be segmented more naturally

Required segmentation target:
- ideal line length is around 12 Chinese-character-equivalent units
- hard maximum remains 17 units
- lines close to 17 should still be reviewed for a better cut
- passing the 17-unit cap alone is insufficient for good subtitle rhythm

Interpretation for prompt and logic design:
- Step 2A and Step 3 should optimize for comfortable subtitle rhythm, not only hard-cap compliance
- 17 is the outer limit
- around 12 is the preferred center of gravity
- keep lines shorter when a natural semantic boundary exists

## Current workflow summary that Grok should work from

### Control shape
- Step 1 = FunASR only
- Step 2 = configured auxiliary model plus pipeline guardrails
- Step 3 = live interactive agent adjudication

### Active artifact flow
1. Step 1 writes `raw.json`
2. Step 2 preflight and routing write `input_preflight.json` and `mode_decision.json`
3. Step 2A writes:
   - `run_glossary.json`
   - `proofread_manuscript.json`
   - `subtitle_draft.json`
   - `aligned_segments.json`
   - `edited-script-pass.srt`
4. audit writes `alignment_audit.json`
5. pipeline handoff writes `agent_review_bundle.json`
6. Step 3 agent reads Step 2 artifacts and writes:
   - `edited.srt`
   - `correction_log.json`
   - `final_delivery_audit.json`
   - updated `report.json`

### Step 3 current contract
- Step 3 uses `edited-script-pass.srt` as the editable base
- Step 3 owns final delivery judgment
- Step 3 may fix mixed zh-en spacing, light wording issues, and segmentation
- Step 3 must stay grounded in `raw.json`, `aligned_segments.json`, `alignment_audit.json`, `proofread_manuscript.json`, `run_glossary.json`, and `report.json`
- Step 3 must not silently fall back to another backend model path

## What Grok should analyze and propose

Please give concrete modification suggestions for these points:

1. **Cue-level re-segmentation design**
   - How should Step 3 split one cue into multiple cues instead of inserting a newline inside one cue
   - What timing source should be used for new boundaries
   - How to keep the result auditable in `correction_log.json` and `final_delivery_audit.json`
   - How to update `report.json` and any contract fields cleanly

2. **Data model and contract changes**
   - Which parts of `finalizer.py`, contracts, or report schema need to change so `edited_cue_count` may differ from `script_pass_cue_count`
   - How to represent one-to-many cue transformations in `correction_log.json`
   - Whether `aligned_segments` validation should keep strict one-to-one assumptions or gain a cue-split-aware mode

3. **Segmentation policy upgrade**
   - How to encode the policy that ideal subtitle length is about 12 units while 17 is only the hard maximum
   - How Step 2A prompt and Step 3 review logic should reflect this
   - How to prefer natural semantic cuts over length-limit-only cuts

4. **Implementation path**
   - What is the cleanest minimal change set to move from in-cue line breaks to true cue splitting
   - Which layers should own the split decision and which layers should own timestamp redistribution
   - What tests should be added for cue splitting, cue count changes, and timing monotonicity

## Concrete example from the current run

Current wrong shape:
- cue 10 stayed one cue and became:
  - `他们会考虑好我们国内的`
  - `法规道路情况等`
- cue 12 stayed one cue and became:
  - `东本和广本基本就决定个`
  - `车内外颜色啥的`

Expected direction:
- these should be considered for conversion into separate subtitle cues with separate timestamps when supported by timing evidence
- the output format should privilege subtitle rhythm and readable cadence, not only compact visual wrapping
