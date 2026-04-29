import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import audit
from audit import build_alignment_audit, write_alignment_audit
from contracts import AlignedSegment, ModeDecision


def _segment(*, line_id: int, score: float, warnings: list[str] | None = None) -> AlignedSegment:
    return AlignedSegment(
        line_id=line_id,
        text=f"line-{line_id}",
        start=float(line_id - 1),
        end=float(line_id),
        raw_token_start_index=line_id - 1,
        raw_token_end_index=line_id - 1,
        alignment_score=score,
        warnings=warnings or [],
    )


def _decision(mode: str = "manuscript-priority") -> ModeDecision:
    return ModeDecision(
        mode=mode,
        confidence=0.91,
        global_similarity=0.93,
        local_similarity_samples=[0.92, 0.94],
        manuscript_completeness=0.96,
        reasons=["test fixture"],
    )


def test_build_alignment_audit_keeps_mode_when_alignment_is_strong():
    audit_result = build_alignment_audit(
        mode_decision=_decision(),
        aligned_segments=[_segment(line_id=1, score=0.95), _segment(line_id=2, score=0.92)],
    )

    assert audit_result.chosen_mode == "manuscript-priority"
    assert audit_result.post_alignment_mode == "manuscript-priority"
    assert audit_result.downgraded_regions == []
    assert audit_result.rebuild_regions == []
    assert audit_result.reasons == []


def test_build_alignment_audit_downgrades_full_run_when_mean_score_is_weak():
    audit_result = build_alignment_audit(
        mode_decision=_decision(),
        aligned_segments=[_segment(line_id=1, score=0.74), _segment(line_id=2, score=0.78)],
    )

    assert audit_result.post_alignment_mode == "raw-priority"
    assert any("mean alignment score" in reason for reason in audit_result.reasons)


def test_build_alignment_audit_marks_low_confidence_regions_for_review_signals():
    audit_result = build_alignment_audit(
        mode_decision=_decision(),
        aligned_segments=[
            _segment(line_id=1, score=0.94),
            _segment(line_id=2, score=0.72, warnings=["low alignment confidence"]),
            _segment(line_id=3, score=0.73, warnings=["low alignment confidence"]),
            _segment(line_id=4, score=0.71, warnings=["low alignment confidence"]),
        ],
    )

    assert audit_result.rebuild_regions == [2, 3, 4]
    assert audit_result.downgraded_regions == [2, 3, 4]
    assert audit_result.fallback_region_count == 3
    assert any("fallback regions" in reason for reason in audit_result.reasons)


def test_audit_module_has_no_legacy_raw_text_rebuild_helper():
    assert not hasattr(audit, "rebuild_segments_from_raw")


def test_write_alignment_audit_serializes_reasons_and_regions(tmp_path):
    audit_result = build_alignment_audit(
        mode_decision=_decision(),
        aligned_segments=[_segment(line_id=1, score=0.72, warnings=["low alignment confidence"])],
    )
    output_path = tmp_path / "alignment_audit.json"

    write_alignment_audit(audit_result, output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["post_alignment_mode"] == "raw-priority"
    assert payload["rebuild_regions"] == [1]
    assert payload["reasons"]
