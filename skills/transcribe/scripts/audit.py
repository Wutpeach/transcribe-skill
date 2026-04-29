from __future__ import annotations

import json
from pathlib import Path

from contracts import AlignedSegment, AlignmentAudit, ModeDecision

WHOLE_RUN_DOWNGRADE_THRESHOLD = 0.80
REGION_REBUILD_THRESHOLD = 0.75
FALLBACK_REGION_THRESHOLD = 3
LOW_CONFIDENCE_RATIO_THRESHOLD = 0.20


def build_alignment_audit(*, mode_decision: ModeDecision, aligned_segments: list[AlignedSegment]) -> AlignmentAudit:
    line_count = len(aligned_segments)
    mean_alignment_score = round(
        sum(segment.alignment_score for segment in aligned_segments) / line_count,
        3,
    ) if line_count else 0.0

    fallback_region_count = sum(1 for segment in aligned_segments if segment.warnings)
    low_confidence_regions = [segment.line_id for segment in aligned_segments if segment.alignment_score < REGION_REBUILD_THRESHOLD]
    low_confidence_ratio = (len(low_confidence_regions) / line_count) if line_count else 0.0

    reasons: list[str] = []
    whole_run_downgrade = False
    if mean_alignment_score < WHOLE_RUN_DOWNGRADE_THRESHOLD:
        whole_run_downgrade = True
        reasons.append("mean alignment score below downgrade threshold")
    if fallback_region_count >= FALLBACK_REGION_THRESHOLD:
        whole_run_downgrade = True
        reasons.append("fallback regions exceed downgrade threshold")
    if low_confidence_ratio > LOW_CONFIDENCE_RATIO_THRESHOLD:
        whole_run_downgrade = True
        reasons.append("low-confidence ratio exceeds downgrade threshold")

    rebuild_regions = list(low_confidence_regions)
    post_alignment_mode = mode_decision.mode
    downgraded_regions = list(low_confidence_regions)

    if whole_run_downgrade and mode_decision.mode == "manuscript-priority":
        post_alignment_mode = "raw-priority"
        if not rebuild_regions:
            rebuild_regions = [segment.line_id for segment in aligned_segments]
            downgraded_regions = list(rebuild_regions)

    return AlignmentAudit(
        chosen_mode=mode_decision.mode,
        post_alignment_mode=post_alignment_mode,
        mean_alignment_score=mean_alignment_score,
        downgraded_regions=downgraded_regions,
        rebuild_regions=rebuild_regions,
        fallback_region_count=fallback_region_count,
        reasons=reasons,
    )


def write_alignment_audit(audit: AlignmentAudit, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(audit.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
