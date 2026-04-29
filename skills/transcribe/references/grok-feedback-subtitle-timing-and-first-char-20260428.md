# Grok Feedback Brief — cue splitting, timestamp redistribution, and first-character alignment

## Purpose

This note summarizes:
- the current pipeline state
- the current real-run bug
- Hermes's proposed Step 3 cue-splitting plan
- the user's additional timing preference

Please review the plan critically and suggest a better approach if one exists.

## Current workflow shape

- Step 1 = FunASR only
- Step 2 = configured auxiliary model plus pipeline guardrails
- Step 3 = live interactive agent adjudication

Active artifact flow:
1. Step 1 writes `raw.json`
2. Step 2 writes `input_preflight.json`, `mode_decision.json`
3. Step 2A / alignment write:
   - `run_glossary.json`
   - `proofread_manuscript.json`
   - `subtitle_draft.json`
   - `aligned_segments.json`
   - `alignment_audit.json`
   - `edited-script-pass.srt`
4. pipeline handoff writes `agent_review_bundle.json`
5. Step 3 writes:
   - `edited.srt`
   - `correction_log.json`
   - `final_delivery_audit.json`
   - updated `report.json`

## Current real-run bug

Reference run:
- replay output dir: `/Users/mabel/Downloads/Transcribe TEST/output-replay-agent-step3-20260428-220359`

Current wrong behavior in `edited.srt`:
- Step 3 handled long subtitles by inserting `\n` inside one existing cue
- it did not create new subtitle cues
- it did not generate new timestamps for the split parts

Observed examples:
- cue 10 remained `00:00:24,440 --> 00:00:27,500`
  - `他们会考虑好我们国内的`
  - `法规道路情况等`
- cue 12 remained `00:00:31,400 --> 00:00:34,147`
  - `东本和广本基本就决定个`
  - `车内外颜色啥的`

This is the wrong delivery shape for this workflow. The target is true cue-level re-segmentation.

## Subtitle length policy

User policy:
- comfortable target is around 12 Chinese-character-equivalent units per subtitle line
- 17 units is the hard maximum
- a line near 17 can still be too long and should still be split if a natural semantic cut exists

## New user timing preference

This is the key new requirement:
- when a subtitle is split into multiple new cues, prioritize aligning the **first character of each subtitle line**
- rationale: the first character is where the speaker visibly starts that subtitle unit
- if the first character is late or misaligned, the whole subtitle line feels wrong even if the end time is roughly acceptable

Operational interpretation:
- start-time alignment has higher priority than end-time neatness
- new cue start boundaries should prefer word/character onsets that match the first displayed character of the new subtitle line
- a slightly rough end boundary is more tolerable than a visibly late subtitle start

## Current evidence from the run

### 1. FunASR raw output does have word-level timestamps

Verified from `raw.json`:
- top-level keys include `segments`
- each segment includes `words`
- each word has `text`, `start`, `end`, and `punctuation`

Example from the real file:
- `{'id': 1, 'text': '你说', 'start': 0.16, 'end': 0.76, 'punctuation': ''}`
- `{'id': 2, 'text': '我们', 'start': 0.76, 'end': 1.04, 'punctuation': ''}`

### 2. aligned_segments.json already exposes raw token spans

For cue 10:
- `line_id = 10`
- `start = 24.44`
- `end = 27.5`
- `raw_token_start_index = 65`
- `raw_token_end_index = 74`
- `alignment_score = 1.0`

For cue 12:
- `line_id = 12`
- `start = 31.4`
- `end = 34.14666666666667`
- `raw_token_start_index = 88`
- `raw_token_end_index = 101`
- `alignment_score = 0.683`
- warnings include:
  - `low alignment confidence`
  - `skipped leading raw characters`

### 3. raw tokens for cue 10 can support a token-anchored split

Cue 10 raw token slice:
- 65 `他们会` `24.44-24.88`
- 66 `考虑` `24.88-25.24`
- 67 `好` `25.24-25.52`
- 68 `我们` `25.52-25.76`
- 69 `国内` `25.76-26.08`
- 70 `的` `26.08-26.20`
- 71 `法规` `26.20-26.68`
- 72 `道路` `26.80-27.08`
- 73 `情况` `27.08-27.36`
- 74 `等等` `27.36-27.64`

This means a split such as:
- `他们会考虑好我们国内的`
- `法规道路情况等`

could anchor the second new cue start near token 71 start `26.20`.

### 4. cue 12 is a lower-confidence case

Cue 12 raw token slice includes spoken-noise-like pieces:
- `啊`
- `这个`
- `的颜色`

So cue 12 should probably be treated as a lower-confidence split case with explicit audit marking.

## Hermes current proposed plan

### Split decision policy

- Step 3 decides whether to split based on:
  - semantic boundary quality
  - preferred length around 12 units
  - hard maximum 17 units
- newline insertion inside one unchanged cue should be treated as a bug, not as valid completion

### Timestamp redistribution policy

Hermes currently proposes three levels:

#### A. token-anchored split
Use when aligned token mapping is good.

Method:
- map the chosen text split to raw token boundaries through `aligned_segments.json`
- assign each new cue start from the first token start of that new cue
- assign each new cue end from the last token end of that new cue
- clamp the first cue start to the original cue start
- clamp the last cue end to the original cue end

#### B. proportional fallback
Use when token alignment is incomplete or weak.

Method:
- keep the original cue start and end fixed
- distribute total duration across the new sub-cues by text-length ratio or token-count ratio
- still prefer the new cue **start** to snap to the nearest plausible token onset when possible

#### C. audit-flagged low-confidence split
Use when the cue is weakly aligned and includes wording noise or skipped leading characters.

Method:
- allow the split
- write strong audit markers to `correction_log.json` and `final_delivery_audit.json`
- keep these cases queryable as higher-risk edits

## Hermes current prioritization rule

Hermes's current view is:
- prioritize the **start time of each new subtitle cue**
- prefer first-character onset alignment over perfect end-boundary neatness
- a slightly imperfect end is acceptable
- a visibly late first character is much more damaging to subtitle feel

## Questions for Grok

Please answer in Chinese and be concrete.

### 1. Is this prioritization correct?
- Do you agree that the first-character onset of each new cue should have higher priority than end-boundary neatness?
- If yes, how should this be encoded in Step 3 logic and audit policy?
- If no, what should the actual priority order be?

### 2. What is the best way to split timestamps after cue splitting?
- Should Step 3 rely primarily on FunASR `words[].start/end`?
- Should it trust `aligned_segments.json` token spans first and then fall back to `raw.json`?
- Should it ever use proportional redistribution when token spans exist but are low-confidence?
- How should it handle cases like cue 12 with `low alignment confidence` and `skipped leading raw characters`?

### 3. How fine-grained should the alignment target be?
- word-level only
- character-level approximation inside a multi-character token
- hybrid approach

Important note:
FunASR words can be multi-character chunks such as `他们会` or `国内`, not always one Chinese character per timestamp entry.
Please suggest the cleanest practical policy for splitting inside or around those chunks.

### 4. What contract and schema changes do you recommend?
Please focus on:
- `finalizer.py`
- `aligned_segments` validation assumptions
- `correction_log.json`
- `final_delivery_audit.json`
- `report.json`

### 5. What would be the minimal clean implementation path?
Please distinguish:
- what should be done now as the smallest reliable fix
- what can wait for a later refinement pass

### 6. Are there better rules than Hermes's current A/B/C plan?
Please critique this plan directly and propose a better one if needed.

## Goal

We want a Step 3 cue-splitting design that:
- produces true new subtitle cues
- aligns new cue starts as naturally as possible to speech onset
- stays grounded in existing FunASR and aligned-segment evidence
- remains auditable
- avoids over-complicated architecture for the first implementation pass
