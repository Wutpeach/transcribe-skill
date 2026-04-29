# Transcribe Hybrid Architecture Implementation Plan

> **For Hermes:** execute this plan in small TDD slices. Keep `raw.json` unchanged, keep timing traceable to raw token spans, and keep fallback behavior observable in artifacts and tests.

**Goal:** upgrade the current minimal FunASR-first pipeline into a hybrid subtitle pipeline with explicit routing, text drafting, line-to-audio alignment, audit-driven downgrade, and conservative final delivery.

**Architecture:** keep `raw.json` as the only primary timing anchor. Add a deterministic control layer around it: Step 0 preflight, Step 2 routing, Step 4 alignment, Step 5 audit. Add a text layer for proofreading and semantic line drafting that can start with a deterministic bootstrap and later accept Hermes-managed LLM drafting without changing the alignment contract.

**Tech Stack:** Python 3.11, pytest, dataclasses, existing `scripts/` pipeline, existing `tests/` suite, FunASR API.

---

## Scope for this implementation plan

This plan targets a shippable hybrid skeleton with real artifacts and real downgrade logic.

It includes:
- `input_preflight.json`
- `mode_decision.json`
- `proofread_manuscript.json`
- `subtitle_draft.json`
- `aligned_segments.json`
- `alignment_audit.json`
- expanded `report.json`
- deterministic routing
- deterministic draft bootstrap
- deterministic token-span alignment
- downgrade-aware pipeline integration

It defers:
- external forced alignment integration
- multi-speaker diarization
- heavy LLM rewriting inside the standalone Python runtime

For the first implementation, Step 3 should expose a stable drafting interface and support two sources:
- deterministic bootstrap drafting inside Python
- future Hermes-managed LLM drafting through a compatible artifact contract

---

## Current codebase anchor

Existing files to preserve and extend:
- `scripts/pipeline.py`
- `scripts/contracts.py`
- `scripts/glossary.py`
- `scripts/segmentation.py`
- `scripts/finalizer.py`
- `tests/test_pipeline.py`
- `tests/test_segmentation.py`
- `tests/test_glossary.py`

New modules proposed:
- `scripts/preflight.py`
- `scripts/routing.py`
- `scripts/drafting.py`
- `scripts/alignment.py`
- `scripts/audit.py`
- `tests/test_preflight.py`
- `tests/test_routing.py`
- `tests/test_drafting.py`
- `tests/test_alignment.py`
- `tests/test_audit.py`
- `tests/test_contracts.py`

---

## Task 1: Add hybrid contracts and output paths

**Objective:** define the dataclasses and pipeline outputs needed for hybrid artifacts before changing runtime behavior.

**Files:**
- Modify: `scripts/contracts.py`
- Create: `tests/test_contracts.py`

**Step 1: Write failing tests**

Create `tests/test_contracts.py` with tests for:
- `InputPreflight.to_dict()`
- `ModeDecision.to_dict()`
- `ProofreadManuscript.to_dict()`
- `SubtitleDraft.to_dict()`
- `AlignedSegment.to_dict()` and summary shape
- `AlignmentAudit.to_dict()`
- `PipelineOutputs` carrying new optional paths

Use concrete assertions for field names. Include one test that verifies future optional artifacts default to `None`.

**Step 2: Run tests to verify failure**

Run:
```bash
pytest tests/test_contracts.py -q
```
Expected: import or attribute failures because the new dataclasses do not exist yet.

**Step 3: Write minimal implementation**

In `scripts/contracts.py` add dataclasses for:
- `InputPreflight`
- `ModeDecision`
- `ProofreadEdit`
- `ProofreadManuscript`
- `DraftLine`
- `SubtitleDraft`
- `AlignedSegment`
- `AlignedSegmentsSummary`
- `AlignmentAudit`

Extend `PipelineOutputs` with:
- `input_preflight_path`
- `mode_decision_path`
- `proofread_manuscript_path`
- `subtitle_draft_path`
- `aligned_segments_path`
- `alignment_audit_path`

Every artifact class needs a `to_dict()` method with a stable schema field where useful.

**Step 4: Run tests to verify pass**

Run:
```bash
pytest tests/test_contracts.py -q
```
Expected: all tests pass.

**Step 5: Commit**

```bash
git add scripts/contracts.py tests/test_contracts.py
 git commit -m "feat: add hybrid transcription contracts"
```

---

## Task 2: Add Step 0 preflight

**Objective:** create a deterministic preflight module that validates inputs and emits routing signals before any mode choice.

**Files:**
- Create: `scripts/preflight.py`
- Create: `tests/test_preflight.py`
- Modify: `scripts/pipeline.py`

**Step 1: Write failing tests**

Create `tests/test_preflight.py` with tests for:
- manuscript present vs absent
- normalized manuscript length
- warnings for empty manuscript string
- capture of user override mode
- heuristic speaker/style signals from raw payload, using simple proxies such as segment count, short filler density, and punctuation volatility

Add one pipeline-level test in `tests/test_pipeline.py` that expects `input_preflight.json` to be written.

**Step 2: Run tests to verify failure**

Run:
```bash
pytest tests/test_preflight.py tests/test_pipeline.py::test_run_minimal_pipeline_writes_required_artifacts -q
```
Expected: module import failure or missing artifact assertions.

**Step 3: Write minimal implementation**

In `scripts/preflight.py` implement:
- `normalize_manuscript_text(text: str | None) -> str`
- `build_input_preflight(raw_payload: dict, manuscript_text: str | None, user_override: str | None) -> InputPreflight`
- `write_input_preflight(preflight: InputPreflight, output_path: Path) -> None`

Keep heuristics simple and deterministic:
- `audio_ok=True` when raw payload contains at least one segment
- `manuscript_present=True` when normalized manuscript has content
- `speaker_complexity_signals` and `style_volatility_signals` as counts/flags only

In `scripts/pipeline.py`:
- add optional `mode_override` to `PipelineConfig`
- emit `input_preflight.json`
- return its path in `PipelineOutputs`

**Step 4: Run tests to verify pass**

Run:
```bash
pytest tests/test_preflight.py tests/test_pipeline.py::test_run_minimal_pipeline_writes_required_artifacts -q
```
Expected: tests pass with the new artifact written.

**Step 5: Commit**

```bash
git add scripts/preflight.py scripts/pipeline.py tests/test_preflight.py tests/test_pipeline.py
 git commit -m "feat: add input preflight artifact"
```

---

## Task 3: Add Step 2 routing

**Objective:** choose `manuscript-priority` or `raw-priority` deterministically and record reasons.

**Files:**
- Create: `scripts/routing.py`
- Create: `tests/test_routing.py`
- Modify: `scripts/pipeline.py`

**Step 1: Write failing tests**

Create `tests/test_routing.py` with tests for:
- strong manuscript similarity chooses `manuscript-priority`
- weak or missing manuscript chooses `raw-priority`
- explicit user override wins
- warning-band inputs still produce a mode plus weak confidence
- reasons list is non-empty

Add one pipeline-level test that expects `mode_decision.json` to exist and contain the chosen mode.

**Step 2: Run tests to verify failure**

Run:
```bash
pytest tests/test_routing.py tests/test_pipeline.py::test_run_minimal_pipeline_writes_required_artifacts -q
```
Expected: missing routing module or missing `mode_decision.json`.

**Step 3: Write minimal implementation**

In `scripts/routing.py` implement:
- text normalization helpers shared with manuscript/raw comparison
- `score_manuscript_similarity(raw_payload: dict, manuscript_text: str | None) -> tuple[float, list[float]]`
- `choose_mode(preflight: InputPreflight, raw_payload: dict, manuscript_text: str | None, user_override: str | None) -> ModeDecision`
- `write_mode_decision(decision: ModeDecision, output_path: Path) -> None`

Keep similarity deterministic:
- compact character comparison on normalized text
- sampled local windows from the raw transcript
- configurable thresholds stored as module constants

In `scripts/pipeline.py`:
- call routing after preflight
- emit `mode_decision.json`
- return its path

**Step 4: Run tests to verify pass**

Run:
```bash
pytest tests/test_routing.py tests/test_pipeline.py::test_run_minimal_pipeline_writes_required_artifacts -q
```
Expected: routing tests and artifact test pass.

**Step 5: Commit**

```bash
git add scripts/routing.py scripts/pipeline.py tests/test_routing.py tests/test_pipeline.py
 git commit -m "feat: add hybrid routing decision"
```

---

## Task 4: Add Step 3 drafting interface and deterministic bootstrap

**Objective:** produce `proofread_manuscript.json` and `subtitle_draft.json` through one stable drafting interface that can later accept Hermes-managed LLM output.

**Files:**
- Create: `scripts/drafting.py`
- Create: `tests/test_drafting.py`
- Modify: `scripts/pipeline.py`
- Modify: `scripts/segmentation.py`

**Step 1: Write failing tests**

Create `tests/test_drafting.py` with tests for:
- manuscript-priority path returns proofread text and one-line draft lines from manuscript input
- raw-priority path keeps raw transcript as anchor and drafts lines from raw text
- high-confidence manuscript entity hints can improve raw-priority draft text locally
- draft lines keep explicit fields such as `line_id`, `text`, `source_mode`, `draft_notes`

Add a pipeline-level test that expects:
- `proofread_manuscript.json`
- `subtitle_draft.json`

**Step 2: Run tests to verify failure**

Run:
```bash
pytest tests/test_drafting.py tests/test_pipeline.py::test_run_minimal_pipeline_writes_required_artifacts -q
```
Expected: missing drafting module or missing artifacts.

**Step 3: Write minimal implementation**

In `scripts/drafting.py` implement:
- `build_proofread_manuscript(raw_payload: dict, manuscript_text: str | None, mode: str, glossary: RunGlossary) -> ProofreadManuscript`
- `build_subtitle_draft(raw_payload: dict, manuscript_text: str | None, mode: str, glossary: RunGlossary, proofread: ProofreadManuscript) -> SubtitleDraft`
- artifact writers for both JSON outputs

For the first bootstrap implementation:
- manuscript-priority: use normalized manuscript text, preserve meaning, log edits conservatively, and split draft lines with explicit rules
- raw-priority: derive draft lines from raw transcript or current segmentation grouping, with local entity upgrades only when confidence is high

Bootstrap drafting constants for the first pass:
- `MAX_LINE_CHARS = 22`
- `TARGET_READING_SECONDS = 2.0`
- `MAX_READING_SECONDS = 6.0`
- punctuation break priority: `。！？!?；;` > `，、,:` > soft length break
- never split protected glossary entities or approved recovered entities

In `scripts/segmentation.py` expose a small helper for conservative raw grouping if needed, rather than duplicating grouping logic inside `drafting.py`.

In `scripts/pipeline.py` integrate the drafting stage and return paths.

**Step 4: Run tests to verify pass**

Run:
```bash
pytest tests/test_drafting.py tests/test_pipeline.py::test_run_minimal_pipeline_writes_required_artifacts -q
```
Expected: draft artifacts exist and tests pass.

**Step 5: Commit**

```bash
git add scripts/drafting.py scripts/segmentation.py scripts/pipeline.py tests/test_drafting.py tests/test_pipeline.py
 git commit -m "feat: add subtitle drafting artifacts"
```

---

## Task 5: Add Step 4 line-to-audio alignment

**Objective:** align draft lines back to continuous raw token spans and emit `aligned_segments.json` plus `edited-script-pass.srt`.

**Files:**
- Create: `scripts/alignment.py`
- Create: `tests/test_alignment.py`
- Modify: `scripts/pipeline.py`
- Modify: `scripts/contracts.py`

**Step 1: Write failing tests**

Create `tests/test_alignment.py` with tests for:
- exact line-to-token-span alignment with manuscript-priority input
- raw-priority alignment from raw-derived draft lines
- protected glossary entity remains intact across alignment
- weighted interpolation splits one raw token into two line boundaries when needed
- low-confidence region records a warning instead of silent success
- overlong candidate span is rejected in favor of the next sequential match
- cross-token boundary cases keep monotonic timing and non-overlapping line spans

Add one pipeline-level test that expects:
- `aligned_segments.json`
- `edited-script-pass.srt` derived from aligned segments rather than direct old segmentation output

**Step 2: Run tests to verify failure**

Run:
```bash
pytest tests/test_alignment.py tests/test_pipeline.py::test_run_minimal_pipeline_reports_manuscript_backed_entity_recoveries -q
```
Expected: missing alignment module or old pipeline behavior.

**Step 3: Write minimal implementation**

In `scripts/alignment.py` implement:
- normalization helpers for draft lines and raw token surfaces
- `align_draft_to_raw_tokens(draft: SubtitleDraft, raw_payload: dict, glossary: RunGlossary) -> list[AlignedSegment]`
- constrained sequential DP or greedy-first path with scored span search
- weighted token-internal interpolation for intra-token boundary cuts
- `build_aligned_segments(...) -> dict-like artifact` or dedicated dataclass
- `aligned_segments_to_cues(...) -> list[SubtitleCue]`
- artifact writer

Guidelines for the first implementation:
- keep spans continuous
- preserve monotonic, non-overlapping timing
- penalize overlong spans and timing jumps
- preserve recovered entities and glossary entities
- prefer deterministic transparency over clever heuristics

Minimal viable alignment rules for the first pass:
- start with greedy sequential matching over normalized draft lines and raw token windows
- search windows in reading order only
- allow DP fallback only when greedy confidence drops below `0.85`
- trigger intra-token interpolation only when one raw token clearly covers text that must belong to two adjacent drafted lines
- use weighted interpolation for zh/en/number mixtures and protect entity boundaries before interpolation

In `scripts/pipeline.py` replace direct `build_script_pass_result(...).cues` generation with:
- current entity recovery/glossary preparation
- drafting output
- alignment output
- `edited-script-pass.srt` from aligned segments

Keep the current entity recovery logic alive inside the alignment input preparation path until it can be absorbed cleanly.

**Step 4: Run tests to verify pass**

Run:
```bash
pytest tests/test_alignment.py tests/test_pipeline.py::test_run_minimal_pipeline_reports_manuscript_backed_entity_recoveries -q
```
Expected: alignment tests pass and the pipeline produces aligned output.

**Step 5: Commit**

```bash
git add scripts/alignment.py scripts/pipeline.py tests/test_alignment.py tests/test_pipeline.py
 git commit -m "feat: add line-to-audio alignment"
```

---

## Task 6: Add Step 5 audit and downgrade logic

**Objective:** review alignment quality and downgrade weak regions or the full run when manuscript-priority underperforms.

**Files:**
- Create: `scripts/audit.py`
- Create: `tests/test_audit.py`
- Modify: `scripts/pipeline.py`
- Modify: `scripts/finalizer.py`

**Step 1: Write failing tests**

Create `tests/test_audit.py` with tests for:
- strong alignment keeps chosen mode unchanged
- weak mean alignment score triggers downgrade to raw-priority
- high fallback region count triggers rebuild decisions
- audit artifact records reasons and rebuild regions

Add a pipeline-level test that expects `alignment_audit.json` and `post-alignment mode` fields in `report.json`.

**Step 2: Run tests to verify failure**

Run:
```bash
pytest tests/test_audit.py tests/test_pipeline.py::test_run_minimal_pipeline_writes_required_artifacts -q
```
Expected: missing audit module or missing report fields.

**Step 3: Write minimal implementation**

In `scripts/audit.py` implement:
- `build_alignment_audit(mode_decision: ModeDecision, aligned_segments: list[AlignedSegment]) -> AlignmentAudit`
- concrete first-pass downgrade thresholds:
  - downgrade whole-run mode when `mean_alignment_score < 0.80`
  - downgrade flagged regions when per-region `alignment_score < 0.75`
  - force rebuild path when `fallback_region_count >= 3` or more than `20%` of lines are low-confidence
- region rebuild selection for low-confidence spans
- writer for `alignment_audit.json`

In `scripts/pipeline.py`:
- call the audit after alignment
- if downgrade is required, rebuild flagged regions with conservative raw grouping rules before final delivery
- rerun cue assembly after rebuild so the finalizer receives the post-audit subtitle pass
- emit `alignment_audit.json`

In `scripts/finalizer.py` keep final text cleanup conservative and audit-aware. Finalizer should respect already-audited timing and avoid reshaping lines heavily.

**Step 4: Run tests to verify pass**

Run:
```bash
pytest tests/test_audit.py tests/test_pipeline.py::test_run_minimal_pipeline_writes_required_artifacts -q
```
Expected: audit tests and updated pipeline tests pass.

**Step 5: Commit**

```bash
git add scripts/audit.py scripts/pipeline.py scripts/finalizer.py tests/test_audit.py tests/test_pipeline.py
 git commit -m "feat: add alignment audit and downgrade flow"
```

---

## Task 7: Expand report.json and regression coverage

**Objective:** make the final report reflect the hybrid runtime clearly and guard the whole pipeline with end-to-end tests.

**Files:**
- Modify: `scripts/pipeline.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_segmentation.py`
- Modify: `tests/test_glossary.py`

**Step 1: Write failing tests**

Add or update pipeline tests for:
- chosen mode and post-alignment mode
- route decision reasons
- alignment success rate
- low-confidence alignment count
- interpolated boundary count
- fallback region count
- downgrade count
- backward-compatible entity recovery reporting

Add one end-to-end regression test for:
- clean manuscript-priority sample
- dirty manuscript that routes to raw-priority

**Step 2: Run tests to verify failure**

Run:
```bash
pytest tests/test_pipeline.py -q
```
Expected: missing fields or failing new assertions.

**Step 3: Write minimal implementation**

Update `_write_report()` in `scripts/pipeline.py` to include all required hybrid fields.

Keep the report compact. Prefer counts, scores, and small examples. Keep large traces in dedicated artifact files.

**Step 4: Run tests to verify pass**

Run:
```bash
pytest tests/test_pipeline.py -q
```
Expected: all pipeline tests pass.

**Step 5: Commit**

```bash
git add scripts/pipeline.py tests/test_pipeline.py tests/test_segmentation.py tests/test_glossary.py
 git commit -m "feat: expand hybrid report coverage"
```

---

## Task 8: Run the full suite and update skill docs

**Objective:** verify the new runtime and document the executable hybrid path.

**Files:**
- Modify: `references/implementation-plan.md`
- Modify: `references/minimal-execution-contract.md`
- Modify: `references/workflow-v3-design-contract.md`
- Modify: `SKILL.md` in `custom/transcribe`

**Step 1: Run the full suite**

Run:
```bash
pytest tests/ -q
```
Expected: all tests pass.

**Step 2: Update docs**

Reflect the new runtime shape:
- Step 0 preflight
- Step 2 routing
- Step 3 text refinement and drafting
- Step 4 alignment
- Step 5 audit and downgrade
- Step 6 conservative final

Document current implementation scope clearly:
- deterministic draft bootstrap is present
- Hermes-managed LLM drafting can plug into the same `subtitle_draft.json` contract later
- forced alignment remains optional heavy fallback

**Step 3: Verify docs and references**

Check that all file names, artifacts, and stage numbers match the implemented runtime.

**Step 4: Commit**

```bash
git add references/implementation-plan.md references/minimal-execution-contract.md references/workflow-v3-design-contract.md /Users/mabel/.hermes/skills/custom/transcribe/SKILL.md
 git commit -m "docs: update hybrid transcription execution docs"
```

---

## Verification matrix

Before marking implementation complete, confirm all of these:
- `raw.json` remains unchanged after ASR
- `input_preflight.json` exists for every run
- `mode_decision.json` exists for every run
- manuscript-priority and raw-priority both have passing end-to-end tests
- `subtitle_draft.json` is produced in both modes
- `aligned_segments.json` can rebuild `edited-script-pass.srt`
- `alignment_audit.json` can trigger downgrade when quality drops
- `report.json` summarizes chosen mode, post-alignment mode, alignment quality, fallback counts, and entity recovery counts
- `edited.srt` remains readable and timing-grounded

## Recommended implementation order in one line

Build the bridge in this order: contracts -> preflight -> routing -> drafting -> alignment -> audit -> report -> docs.
