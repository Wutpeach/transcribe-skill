from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from contracts import AgentReviewBundle


def build_agent_review_bundle(
    *,
    run_dir: Path,
    report: dict[str, Any],
    priority_cases: list[dict[str, Any]] | None = None,
) -> AgentReviewBundle:
    return AgentReviewBundle(
        run_dir=str(run_dir),
        step3_execution_mode="agent-session",
        step3_owner="interactive-agent",
        input_paths={
            "raw_json": "raw.json",
            "proofread_manuscript": "proofread_manuscript.json",
            "subtitle_draft": "subtitle_draft.json",
            "aligned_segments": "aligned_segments.json",
            "alignment_audit": "alignment_audit.json",
            "run_glossary": "run_glossary.json",
            "script_pass_srt": "edited-script-pass.srt",
            "report_json": "report.json",
        },
        headline={
            "chosen_mode": report.get("chosen_mode"),
            "post_alignment_mode": report.get("post_alignment_mode"),
            "alignment_success_rate": report.get("alignment_success_rate"),
            "fallback_region_count": report.get("fallback_region_count"),
            "downgrade_count": report.get("downgrade_count"),
            "step2a_alert_count": len(report.get("step2a_alert_reasons") or []),
            "step2b_or_step3_signal_count": len(report.get("step3_alert_reasons") or []),
        },
        priority_cases=list(priority_cases or []),
    )


def write_agent_review_bundle(bundle: AgentReviewBundle, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
