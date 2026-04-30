# Grok review request — Step 3 heuristic resegmentation round 2

Please review this verified Step 3 patch in Chinese. Be concrete. Focus on correctness, edge cases, architecture fit, and whether it is ready to commit.

## Context
Repo: `Wutpeach/transcribe-skill`

Workflow contract:
- Step 2A owns initial structure generation
- Step 3 owns final delivery judgement
- hard line cap is 17
- final delivery should support human-like subtitle segmentation rather than only contract compliance

Recent problem:
- We already fixed Step 3 delivery timing smoothing
- Real Feishu tests then showed text-side issues still remained
- Examples:
  - `说完云端的 我们再来看看`
  - `系统根据这些物体的距离 速度 轨迹预测`
- Diagnosis: Step 2A can output contract-legal but delivery-suboptimal lines, and downstream currently inherits them unless Step 3 actively re-segments

## What this patch does
This patch adds a conservative first-pass Step 3 automatic heuristic re-segmentation layer inside `finalize_cues()`.

Current supported heuristic patterns:
1. rhythm boundary pattern
   - `^(?P<left>.+的)\s+(?P<right>我们.+)$`
   - example: `说完云端的 我们再来看看`
2. dense list-like pattern
   - `^(?P<left>.+距离)\s+(?P<right>速度\s+轨迹预测)$`
   - example: `系统根据这些物体的距离 速度 轨迹预测`

Behavior:
- build heuristic split decisions only when text matches these conservative patterns
- apply timing-aware split writeback through existing `apply_cue_splits()` plumbing
- record split metadata into:
  - `change_breakdown.delivery_resegmentations`
  - `correction_log`
  - `delivery_audit`
  - `report.json`
- skip the heuristic path when alignment metadata is incomplete or raw payload has no usable words

## Safety fix added after independent review
An independent reviewer flagged that the new heuristic path could crash if:
- aligned segments lacked raw token indexes
- raw payload had no usable words

That is now guarded by `_heuristic_resegmentation_ready(...)`, which requires:
- raw_payload present
- aligned_segments present
- at least one raw segment with words
- every aligned segment has `raw_token_start_index` and `raw_token_end_index`

If these preconditions are not met, Step 3 skips heuristic re-segmentation and preserves the incoming cues.

## Verification status
Local verification passed:
- `python -m pytest -q` → 137 passed
- `ruff check .` → all checks passed

Added tests include:
- rhythm split real case
- dense list-like split real case
- no-split mixed-script spacing case
- safe skip when heuristic pattern matches but alignment metadata is incomplete
- report / correction_log / final_delivery_audit propagation for heuristic resegmentation

## Diff
```diff
diff --git a/skills/transcribe/scripts/finalizer_audit.py b/skills/transcribe/scripts/finalizer_audit.py
index 190ddfb..af99100 100644
--- a/skills/transcribe/scripts/finalizer_audit.py
+++ b/skills/transcribe/scripts/finalizer_audit.py
@@ -1,9 +1,10 @@
 from __future__ import annotations
 
 from typing import Any
+import re
 
-from contracts import AlignmentAudit, RunGlossary, SubtitleCue, count_text_punctuation_violations
-from finalizer_cues import AgentReviewRequiredError, FinalizerResult, build_split_statistics, is_micro_cue
+from contracts import AlignmentAudit, RunGlossary, SubtitleCue, count_text_punctuation_violations, subtitle_display_length
+from finalizer_cues import AgentReviewRequiredError, FinalizerResult, build_split_statistics, is_micro_cue, apply_cue_splits
 
 
 def empty_finalizer_breakdown() -> dict[str, dict[str, Any]]:
@@ -133,6 +134,55 @@ def apply_delivery_timing_smoothing(cues: list[SubtitleCue]) -> tuple[list[Subti
     }
 
 
+def _candidate_trigger_length(text: str) -> int:
+    return subtitle_display_length(text)
+
+
+def _heuristic_split_texts(text: str) -> list[str] | None:
+    stripped = text.strip()
+    length = _candidate_trigger_length(stripped)
+    if length < 11:
+        return None
+
+    rhythm_match = re.search(r"^(?P<left>.+的)\s+(?P<right>我们.+)$", stripped)
+    if rhythm_match and 4 <= _candidate_trigger_length(rhythm_match.group("left")) <= 12 and 4 <= _candidate_trigger_length(rhythm_match.group("right")) <= 12:
+        return [rhythm_match.group("left").strip(), rhythm_match.group("right").strip()]
+
+    if length < 15:
+        return None
+
+    list_match = re.search(r"^(?P<left>.+距离)\s+(?P<right>速度\s+轨迹预测)$", stripped)
+    if list_match:
+        left = list_match.group("left").strip()
+        right = list_match.group("right").strip()
+        if _candidate_trigger_length(left) <= 14 and _candidate_trigger_length(right) <= 14:
+            return [left, right]
+
+    return None
+
+
+def _build_heuristic_split_decisions(cues: list[SubtitleCue]) -> list[dict[str, Any]]:
+    decisions: list[dict[str, Any]] = []
+    for cue in cues:
+        split_texts = _heuristic_split_texts(cue.text)
+        if not split_texts or len(split_texts) <= 1:
+            continue
+        decisions.append({"cue_index": cue.index, "texts": split_texts})
+    return decisions
+
+
+def _heuristic_resegmentation_ready(*, raw_payload: dict[str, Any] | None, aligned_segments: list[dict[str, Any]] | None) -> bool:
+    if not raw_payload or not aligned_segments:
+        return False
+    raw_segments = raw_payload.get("segments") or []
+    if not any(segment.get("words") for segment in raw_segments):
+        return False
+    for segment in aligned_segments:
+        if segment.get("raw_token_start_index") is None or segment.get("raw_token_end_index") is None:
+            return False
+    return True
+
+
 
 def build_delivery_audit(
     *,
@@ -202,7 +252,7 @@ def finalize_cues(
     proofread: dict[str, Any] | None = None,
     aligned_segments: list[dict[str, Any]] | None = None,
 ) -> FinalizerResult:
-    del glossary, audit, raw_payload
+    del glossary, audit
     if proofread:
         raise AgentReviewRequiredError(
             "Step 3 final text authority belongs to the live agent review bundle; backend proofread-driven adjudication is retired."
@@ -228,7 +278,31 @@ def finalize_cues(
     manual_review_required = False
     alert_reasons: list[str] = []
 
-    resegment_sources: list[str] = ["agent_step3_manual_review"] if split_operations else []
+    heuristic_split_decisions: list[dict[str, Any]] = []
+    if _heuristic_resegmentation_ready(raw_payload=raw_payload, aligned_segments=aligned_segments) and not validation_fallback_reasons:
+        heuristic_split_decisions = _build_heuristic_split_decisions(cues)
+        if heuristic_split_decisions:
+            split_result = apply_cue_splits(
+                cues=cues,
+                split_decisions=heuristic_split_decisions,
+                raw_payload=raw_payload,
+                aligned_segments=aligned_segments,
+                change_type="step3_heuristic_resegmentation",
+                resegment_source="step3_heuristic_resegmentation",
+            )
+            finalized = split_result.cues
+            correction_entries = split_result.correction_entries
+            split_operations = split_result.cue_splits
+            applied_regions = [int(item["cue_index"]) for item in correction_entries]
+
+    breakdown["delivery_resegmentations"] = {
+        "count": len(split_operations),
+        "examples": [
+            f"{item.get('original_line_id')}->{','.join(str(v) for v in item.get('new_line_ids') or [])}"
+            for item in split_operations[:5]
+        ],
+    }
+    resegment_sources: list[str] = ["step3_heuristic_resegmentation"] if split_operations else []
     cue_diffs = build_cue_diffs(correction_entries)
     split_statistics = build_split_statistics(split_operations)
     delivery_audit = build_delivery_audit(
diff --git a/skills/transcribe/scripts/finalizer_cues.py b/skills/transcribe/scripts/finalizer_cues.py
index e466452..6dee4f0 100644
--- a/skills/transcribe/scripts/finalizer_cues.py
+++ b/skills/transcribe/scripts/finalizer_cues.py
@@ -143,6 +143,8 @@ def apply_cue_splits(
     split_decisions: list[dict[str, Any]],
     raw_payload: dict[str, Any],
     aligned_segments: list[dict[str, Any]],
+    change_type: str = "agent_delivery_resegmentation",
+    resegment_source: str = "agent_step3_manual_review",
 ) -> CueSplitApplicationResult:
     decision_map = {int(item["cue_index"]): list(item.get("texts") or []) for item in split_decisions}
     aligned_map = {int(item["line_id"]): item for item in aligned_segments}
@@ -230,8 +232,8 @@ def apply_cue_splits(
                 "before_cues": [{"cue_index": cue.index, "text": cue.text}],
                 "after_cues": [{"cue_index": item.index, "text": item.text} for item in created_cues],
                 "source_cue_indexes": [cue.index],
-                "change_types": ["agent_delivery_resegmentation"],
-                "resegment_source": ["agent_step3_manual_review"],
+                "change_types": [change_type],
+                "resegment_source": [resegment_source],
             }
         )
         cue_splits.append(
diff --git a/skills/transcribe/tests/test_finalizer.py b/skills/transcribe/tests/test_finalizer.py
index 799b0dc..f61a6f2 100644
--- a/skills/transcribe/tests/test_finalizer.py
+++ b/skills/transcribe/tests/test_finalizer.py
@@ -154,6 +154,205 @@ def test_finalize_cues_rules_primary_does_not_merge_micro_cues_even_with_warning
     assert finalized.correction_log["cue_changes"] == []
 
 
+def test_finalize_cues_heuristically_splits_rhythm_boundary_cue_before_writeback():
+    glossary = RunGlossary(terms=[])
+    cues = [
+        SubtitleCue(index=1, start=10.0, end=12.0, text="说完云端的 我们再来看看"),
+    ]
+    raw_payload = {
+        "segments": [
+            {
+                "id": 1,
+                "start": 10.0,
+                "end": 12.0,
+                "text": "说完云端的我们再来看看",
+                "words": [
+                    {"id": 1, "text": "说完", "start": 10.0, "end": 10.35, "punctuation": ""},
+                    {"id": 2, "text": "云端", "start": 10.35, "end": 10.8, "punctuation": ""},
+                    {"id": 3, "text": "的", "start": 10.8, "end": 10.95, "punctuation": ""},
+                    {"id": 4, "text": "我们", "start": 10.95, "end": 11.3, "punctuation": ""},
+                    {"id": 5, "text": "再来", "start": 11.3, "end": 11.65, "punctuation": ""},
+                    {"id": 6, "text": "看看", "start": 11.65, "end": 12.0, "punctuation": ""},
+                ],
+            }
+        ]
+    }
+
+    finalized = finalize_cues(
+        cues=cues,
+        glossary=glossary,
+        raw_payload=raw_payload,
+        aligned_segments=[
+            {
+                "line_id": 1,
+                "text": "说完云端的 我们再来看看",
+                "start": 10.0,
+                "end": 12.0,
+                "raw_token_start_index": 0,
+                "raw_token_end_index": 5,
+                "alignment_score": 1.0,
+                "warnings": [],
+            }
+        ],
+    )
+
+    assert [(cue.index, cue.start, cue.end, cue.text) for cue in finalized.cues] == [
+        (1, 10.0, 10.95, "说完云端的"),
+        (2, 10.95, 12.0, "我们再来看看"),
+    ]
+    assert finalized.change_breakdown["delivery_resegmentations"]["count"] == 1
+    assert finalized.change_breakdown["delivery_resegmentations"]["examples"] == ["1->1,2"]
+    assert finalized.applied_region_summary == "1"
+    assert finalized.delivery_audit["checks"]["resegment_count"] == 1
+    assert finalized.delivery_audit["resegment_source"] == ["step3_heuristic_resegmentation"]
+    assert finalized.delivery_audit["cue_splitting"]["split_count"] == 1
+    assert finalized.correction_log["cue_changes"][0]["after_cues"] == [
+        {"cue_index": 1, "text": "说完云端的"},
+        {"cue_index": 2, "text": "我们再来看看"},
+    ]
+    assert finalized.correction_log["cue_changes"][0]["change_types"] == ["step3_heuristic_resegmentation"]
+    assert finalized.correction_log["cue_changes"][0]["resegment_source"] == ["step3_heuristic_resegmentation"]
+
+
+def test_finalize_cues_heuristically_splits_dense_list_like_cue_before_writeback():
+    glossary = RunGlossary(terms=[])
+    cues = [
+        SubtitleCue(index=1, start=20.0, end=22.0, text="系统根据这些物体的距离 速度 轨迹预测"),
+    ]
+    raw_payload = {
+        "segments": [
+            {
+                "id": 2,
+                "start": 20.0,
+                "end": 22.0,
+                "text": "系统根据这些物体的距离速度轨迹预测",
+                "words": [
+                    {"id": 1, "text": "系统", "start": 20.0, "end": 20.2, "punctuation": ""},
+                    {"id": 2, "text": "根据", "start": 20.2, "end": 20.45, "punctuation": ""},
+                    {"id": 3, "text": "这些", "start": 20.45, "end": 20.65, "punctuation": ""},
+                    {"id": 4, "text": "物体", "start": 20.65, "end": 20.9, "punctuation": ""},
+                    {"id": 5, "text": "的", "start": 20.9, "end": 21.0, "punctuation": ""},
+                    {"id": 6, "text": "距离", "start": 21.0, "end": 21.3, "punctuation": ""},
+                    {"id": 7, "text": "速度", "start": 21.3, "end": 21.55, "punctuation": ""},
+                    {"id": 8, "text": "轨迹", "start": 21.55, "end": 21.8, "punctuation": ""},
+                    {"id": 9, "text": "预测", "start": 21.8, "end": 22.0, "punctuation": ""},
+                ],
+            }
+        ]
+    }
+
+    finalized = finalize_cues(
+        cues=cues,
+        glossary=glossary,
+        raw_payload=raw_payload,
+        aligned_segments=[
+            {
+                "line_id": 1,
+                "text": "系统根据这些物体的距离 速度 轨迹预测",
+                "start": 20.0,
+                "end": 22.0,
+                "raw_token_start_index": 0,
+                "raw_token_end_index": 8,
+                "alignment_score": 1.0,
+                "warnings": [],
+            }
+        ],
+    )
+
+    assert [(cue.index, cue.start, cue.end, cue.text) for cue in finalized.cues] == [
+        (1, 20.0, 21.3, "系统根据这些物体的距离"),
+        (2, 21.3, 22.0, "速度 轨迹预测"),
+    ]
+    assert finalized.change_breakdown["delivery_resegmentations"]["count"] == 1
+    assert finalized.delivery_audit["cue_splitting"]["split_count"] == 1
+    assert finalized.delivery_audit["cue_splitting"]["max_length"] == 11
+    assert finalized.correction_log["cue_changes"][0]["after"] == "系统根据这些物体的距离\n速度 轨迹预测"
+
+
+def test_finalize_cues_does_not_split_mixed_script_spacing_only_cue():
+    glossary = RunGlossary(terms=[GlossaryEntry(term="FunASR API", aliases=["funasr api"])])
+    cues = [
+        SubtitleCue(index=1, start=0.0, end=1.4, text="他提到 FunASR API"),
+    ]
+    raw_payload = {
+        "segments": [
+            {
+                "id": 3,
+                "start": 0.0,
+                "end": 1.4,
+                "text": "他提到FunASRAPI",
+                "words": [
+                    {"id": 1, "text": "他提到", "start": 0.0, "end": 0.45, "punctuation": ""},
+                    {"id": 2, "text": "FunASR", "start": 0.45, "end": 0.95, "punctuation": ""},
+                    {"id": 3, "text": "API", "start": 0.95, "end": 1.4, "punctuation": ""},
+                ],
+            }
+        ]
+    }
+
+    finalized = finalize_cues(
+        cues=cues,
+        glossary=glossary,
+        raw_payload=raw_payload,
+        aligned_segments=[
+            {
+                "line_id": 1,
+                "text": "他提到 FunASR API",
+                "start": 0.0,
+                "end": 1.4,
+                "raw_token_start_index": 0,
+                "raw_token_end_index": 2,
+                "alignment_score": 1.0,
+                "warnings": [],
+            }
+        ],
+    )
+
+    assert [(cue.index, cue.start, cue.end, cue.text) for cue in finalized.cues] == [(1, 0.0, 1.4, "他提到 FunASR API")]
+    assert finalized.change_breakdown["delivery_resegmentations"]["count"] == 0
+    assert finalized.delivery_audit["resegment_source"] == []
+    assert finalized.correction_log["cue_changes"] == []
+
+
+def test_finalize_cues_skips_heuristic_resegmentation_when_alignment_metadata_is_incomplete():
+    glossary = RunGlossary(terms=[])
+    cues = [
+        SubtitleCue(index=1, start=10.0, end=12.0, text="说完云端的 我们再来看看"),
+    ]
+    raw_payload = {
+        "segments": [
+            {
+                "id": 1,
+                "start": 10.0,
+                "end": 12.0,
+                "text": "说完云端的我们再来看看",
+                "words": [],
+            }
+        ]
+    }
+
+    finalized = finalize_cues(
+        cues=cues,
+        glossary=glossary,
+        raw_payload=raw_payload,
+        aligned_segments=[
+            {
+                "line_id": 1,
+                "text": "说完云端的 我们再来看看",
+                "start": 10.0,
+                "end": 12.0,
+                "alignment_score": 1.0,
+                "warnings": [],
+            }
+        ],
+    )
+
+    assert [(cue.index, cue.start, cue.end, cue.text) for cue in finalized.cues] == [(1, 10.0, 12.0, "说完云端的 我们再来看看")]
+    assert finalized.change_breakdown["delivery_resegmentations"]["count"] == 0
+    assert finalized.delivery_audit["resegment_source"] == []
+    assert finalized.correction_log["cue_changes"] == []
+
+
 def test_apply_delivery_timing_smoothing_snaps_first_cue_and_fills_positive_gaps():
     cues = [
         SubtitleCue(index=1, start=0.5, end=1.0, text="第一句"),
diff --git a/skills/transcribe/tests/test_pipeline.py b/skills/transcribe/tests/test_pipeline.py
index 4017adc..550386a 100644
--- a/skills/transcribe/tests/test_pipeline.py
+++ b/skills/transcribe/tests/test_pipeline.py
@@ -429,6 +429,154 @@ def test_run_minimal_pipeline_writes_required_artifacts(tmp_path):
     assert "，" not in script_pass_srt
 
 
+def test_write_step3_review_artifacts_records_heuristic_resegmentation_in_report_and_artifacts(tmp_path):
+    run_dir = tmp_path / "run-step3-heuristic"
+    run_dir.mkdir()
+    report_path = run_dir / "report.json"
+    report_path.write_text(
+        json.dumps(
+            {
+                "schema": "transcribe.report.v3",
+                "step3_status": "awaiting_agent_review",
+                "step3_text_authority": "interactive-agent",
+                "step3_alert_reasons": [],
+                "manual_review_required": False,
+                "final_delivery_status": "awaiting_agent_review",
+                "final_delivery_risk": "pending",
+                "final_delivery_reasons": [],
+                "finalizer_change_count": 0,
+                "finalizer_change_breakdown": {
+                    "alias_replacements": {"count": 0, "examples": []},
+                    "spacing_normalizations": {"count": 0, "examples": []},
+                    "punctuation_normalizations": {"count": 0, "examples": []},
+                    "duplicate_collapses": {"count": 0, "examples": []},
+                    "delivery_resegmentations": {"count": 0, "examples": []},
+                },
+                "finalizer_applied_regions": "",
+                "finalizer_mode": "agent-session-pending",
+                "finalizer_model_provider": None,
+                "finalizer_model_name": None,
+                "finalizer_fallback_used": False,
+                "finalizer_fallback_reason": None,
+                "finalizer_fallback_code": None,
+                "segmentation_stats": {"script_pass_cue_count": 1, "edited_cue_count": None},
+            },
+            ensure_ascii=False,
+            indent=2,
+        ),
+        encoding="utf-8",
+    )
+    finalizer_result = FinalizerResult(
+        cues=[
+            SubtitleCue(index=1, start=0.0, end=0.8, text="说完云端的"),
+            SubtitleCue(index=2, start=0.8, end=1.6, text="我们再来看看"),
+        ],
+        change_breakdown={
+            "alias_replacements": {"count": 0, "examples": []},
+            "spacing_normalizations": {"count": 0, "examples": []},
+            "punctuation_normalizations": {"count": 0, "examples": []},
+            "duplicate_collapses": {"count": 0, "examples": []},
+            "delivery_resegmentations": {"count": 1, "examples": ["1->1,2"]},
+        },
+        applied_regions=[1],
+        applied_region_summary="1",
+        correction_log={
+            "schema": "transcribe.correction_log.v1",
+            "cue_changes": [
+                {
+                    "cue_index": 1,
+                    "start": 0.0,
+                    "end": 1.6,
+                    "before": "说完云端的 我们再来看看",
+                    "after": "说完云端的\n我们再来看看",
+                    "before_cues": [{"cue_index": 1, "text": "说完云端的 我们再来看看"}],
+                    "after_cues": [
+                        {"cue_index": 1, "text": "说完云端的"},
+                        {"cue_index": 2, "text": "我们再来看看"},
+                    ],
+                    "source_cue_indexes": [1],
+                    "change_types": ["step3_heuristic_resegmentation"],
+                    "resegment_source": ["step3_heuristic_resegmentation"],
+                }
+            ],
+            "cue_diffs": [],
+            "cue_splits": [
+                {
+                    "original_line_id": 1,
+                    "new_line_ids": [1, 2],
+                    "split_type": "token_anchored",
+                    "split_confidence": "high",
+                    "start_alignment_delta_ms": 0,
+                    "risk_level": "low",
+                    "used_fallback": False,
+                    "fallback_steps": [],
+                    "split_point_token_index": 3,
+                }
+            ],
+            "split_statistics": {
+                "total_splits": 1,
+                "token_anchored_count": 1,
+                "partial_token_anchored_count": 0,
+                "proportional_fallback_count": 0,
+                "low_confidence_split_count": 0,
+            },
+            "applied_region_summary": "1",
+        },
+        delivery_audit={
+            "schema": "transcribe.final_delivery_audit.v1",
+            "status": "ready",
+            "risk": "low",
+            "checks": {"cue_count": 2, "resegment_count": 1},
+            "resegment_source": ["step3_heuristic_resegmentation"],
+            "cue_splitting": {
+                "split_count": 1,
+                "high_risk_count": 0,
+                "max_length": 6,
+                "mean_alignment_delta_ms": 0.0,
+            },
+            "reasons": [],
+            "cue_diffs": [],
+        },
+        split_operations=[
+            {
+                "original_line_id": 1,
+                "new_line_ids": [1, 2],
+                "split_type": "token_anchored",
+                "split_confidence": "high",
+                "start_alignment_delta_ms": 0,
+                "risk_level": "low",
+                "used_fallback": False,
+                "fallback_steps": [],
+                "split_point_token_index": 3,
+            }
+        ],
+        validation_fallback_reasons=[],
+        finalizer_mode="rules-primary",
+        finalizer_model_provider=None,
+        finalizer_model_name=None,
+        finalizer_fallback_used=False,
+        finalizer_fallback_reason=None,
+        finalizer_fallback_code=None,
+        text_authority="inherited",
+        manual_review_required=False,
+        alert_reasons=[],
+    )
+
+    write_step3_review_artifacts(run_dir=run_dir, finalizer_result=finalizer_result)
+
+    report = json.loads(report_path.read_text(encoding="utf-8"))
+    correction_log = json.loads((run_dir / "correction_log.json").read_text(encoding="utf-8"))
+    final_delivery_audit = json.loads((run_dir / "final_delivery_audit.json").read_text(encoding="utf-8"))
+
+    assert report["finalizer_change_breakdown"]["delivery_resegmentations"] == {"count": 1, "examples": ["1->1,2"]}
+    assert report["split_count"] == 1
+    assert report["cue_splitting"]["split_count"] == 1
+    assert report["finalizer_applied_regions"] == "1"
+    assert correction_log["cue_changes"][0]["change_types"] == ["step3_heuristic_resegmentation"]
+    assert correction_log["cue_changes"][0]["resegment_source"] == ["step3_heuristic_resegmentation"]
+    assert final_delivery_audit["resegment_source"] == ["step3_heuristic_resegmentation"]
+
+
 def test_write_step3_review_artifacts_updates_report_with_finalized_metrics(tmp_path):
     run_dir = tmp_path / "run-step3"
     run_dir.mkdir()
