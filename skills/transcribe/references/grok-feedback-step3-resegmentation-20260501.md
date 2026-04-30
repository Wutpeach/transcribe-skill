# Grok review request — Step 3 re-segmentation architecture and priority

You are reviewing the current architecture and debugging findings for a subtitle transcription pipeline. Please respond in Chinese. Be concrete and opinionated. Focus on root cause analysis, architecture judgement, and implementation priority.

## Project background
We are iterating on a transcription workflow repo: `Wutpeach/transcribe-skill`.

Current workflow boundary:
- Step 1 = FunASR only, outputs `raw.json`
- Step 2 = configured auxiliary model plus pipeline guardrails
- Step 2A = proofreading + one-line subtitle segmentation, outputs `subtitle_draft.json`
- Step 2B = alignment back onto raw timing, outputs `aligned_segments.json` and `edited-script-pass.srt`
- Step 2C = alignment audit + conservative downgrade
- Step 3 = live interactive agent final adjudication, should own polishing, re-segmentation, and final delivery writeback

Design intent we have already agreed on:
- Step 2A owns initial structure only
- Step 3 / Hermes owns final delivery judgement
- Hard line cap is 17 Han-character-equivalent units
- Final delivery should feel like human subtitle judgement, not just contract compliance
- Recently we implemented delivery-only timing smoothing in Step 3 writeback:
  - snap first cue start to 0.0
  - fill every positive inter-cue gap
  - keep overlaps unchanged
  - keep last cue end unchanged

## Recent status
We just implemented and shipped the timing smoothing change. Tests passed, Grok previously approved that patch, and the code is now on main.

However, a new Feishu real-run test exposed another class of issues:
- timing gaps are now gone
- but some subtitle blocks still feel under-segmented or too full

Examples from the user:
1. `说完云端的 我们再来看看`
   User feels this should be split into two subtitle blocks by delivery rhythm.
2. `系统根据这些物体的距离 速度 轨迹预测`
   User feels this is still too long / too full and should likely be split, even though it may pass the raw 17-unit cap depending on counting.

## What I found in the code
I traced the current repo behavior.

### Step 2A current behavior
In `skills/transcribe/scripts/auxiliary_drafting.py`, the auxiliary model returns `subtitle_lines` directly.
The system currently validates only:
- punctuation-free
- display length > 17

Relevant behavior:
- `subtitle_display_length()` removes whitespace and counts compact length
- exactly 17 passes
- anything under 18 passes even if it still feels too full or obviously splittable

### Step 2A to draft handoff
In `skills/transcribe/scripts/drafting.py`, LLM-returned `subtitle_lines` are accepted directly into `SubtitleDraft.lines`.
There is no second-pass structural refinement for near-limit or rhythmically awkward lines.

### Step 2B current behavior
`alignment.py` aligns each draft line onto raw timing.
It preserves line text structure from Step 2A.
It does not do semantic re-segmentation.

### Step 3 current behavior in repo
This is the key point.
The workflow/skill/design docs say Step 3 is the final adjudicator and should own polishing and re-segmentation.
But the actual repo implementation of `finalize_cues()` is still very thin.
Right now it mainly does validation / audit packaging.
The recent writeback addition performs timing smoothing only.
There is currently no default automatic Step 3 text-level re-segmentation pass for:
- lines that are <=17 but obviously splittable by rhythm
- lines exactly at 17 but visually too dense
- list-like or clause-like structures that should be split for delivery quality

### Important nuance
There are already plumbing pieces in the repo for split application and split auditing:
- `apply_cue_splits()`
- split statistics and report/audit fields
- `delivery_resegmentations` tracking

So part of the split infrastructure exists, but it does not appear to be wired into the normal Step 3 automatic flow.
This makes Step 3 functionally present as a design contract and manual review concept, but only partially present as automatic code behavior.

## My current diagnosis
My current diagnosis is:
1. The current bug is not in timing smoothing.
2. The main issue is that Step 2A can output lines that are contract-legal but delivery-suboptimal.
3. Downstream stages mostly inherit that structure.
4. Step 3 was conceptually defined as the final adjudicator, but its automatic text-level re-segmentation layer has not actually been implemented yet.

## My current proposal
I currently think the next implementation priority should be Step 3 delivery re-segmentation, not another narrow timing patch.

Proposed direction:
1. Keep Step 2A as initial structure generation.
2. Add an automatic Step 3 review pass that inspects final cues before writing `edited.srt`.
3. Trigger review on cases like:
   - display length near limit, especially 16-17 units
   - obvious internal clause boundary
   - list-like structures such as `距离 速度 轨迹`
   - rhythm boundaries such as `说完云端的 / 我们再来看看`
4. Generate split decisions conservatively.
5. Apply them with `apply_cue_splits()` so timing is re-anchored rather than naively cloned.
6. Record all such operations in correction log / delivery audit / report.
7. Add regression tests using real examples like the two lines above.

Possible architecture options I see:
- Option A: deterministic heuristic Step 3 splitter first, based on near-limit and lexical/rhythm boundaries
- Option B: agent-assisted Step 3 split decision layer, then deterministic timing application
- Option C: strengthen Step 2A prompts/contract first, and defer Step 3 auto re-segmentation

My current leaning:
- Step 3 should be the main fix surface because that matches the workflow contract
- Step 2A prompt/contract can be improved later as an upstream quality booster

## What I want from you
Please review this and answer these questions:
1. Is my diagnosis correct?
2. Is Step 3 the right implementation priority, or should we strengthen Step 2A first?
3. Between heuristic Step 3 splitting vs agent-assisted Step 3 splitting, which is the better first production move and why?
4. How would you define a conservative trigger policy so the system improves delivery quality without over-splitting?
5. What concrete regression tests would you add first?
6. Do you see any architecture smell or boundary mistake in the current design?
7. If you were guiding this repo for the next commit, what exact implementation sequence would you recommend?

Please give a practical engineering answer, not a generic discussion.
