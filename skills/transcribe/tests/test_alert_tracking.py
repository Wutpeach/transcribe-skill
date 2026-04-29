import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from alert_tracking import build_alert_tracking
from contracts import DraftLine, ProofreadManuscript, SubtitleCue, SubtitleDraft
from drafting import Step2ADraftingResult
from finalizer import FinalizerResult


def test_build_alert_tracking_classifies_step2a_contract_alert_and_collects_line_text():
    step2a_result = Step2ADraftingResult(
        proofread=ProofreadManuscript(
            source_text="原稿",
            proofread_text="原稿",
            edit_summary="llm proofreading",
            proofread_confidence=0.92,
            draft_ready=True,
            drafting_warnings=["contract alert: subtitle_lines[37] exceeds 17 display units"],
        ),
        draft=SubtitleDraft(
            lines=[
                DraftLine(
                    line_id=37,
                    text="这个例子确实已经超过十七字限制",
                    source_mode="manuscript-priority",
                )
            ]
        ),
        drafting_mode="llm-primary-with-alerts",
        draft_model_provider="deepseek_direct_aux",
        draft_model_name="deepseek-v4-flash",
        draft_fallback_used=False,
        draft_fallback_reason=None,
        draft_fallback_code=None,
        draft_attempt_count=1,
        text_authority="llm",
        manual_review_required=False,
        alert_reasons=["contract alert: subtitle_lines[37] exceeds 17 display units"],
    )

    tracking = build_alert_tracking(
        step2a_result=step2a_result,
        subtitle_draft=step2a_result.draft,
        step2a_alert_reasons=["contract alert: subtitle_lines[37] exceeds 17 display units"],
        step2b_alert_reasons=[],
        script_pass_cues=[],
        finalizer_result=FinalizerResult(cues=[]),
        step3_validation_alert_reasons=[],
        edited_cues=[],
    )

    assert tracking["schema"] == "transcribe.alert_tracking.v1"
    assert tracking["alert_case_count"] == 1
    assert tracking["manual_review_case_count"] == 0
    assert tracking["stage_counts"]["step2a"]["alert_count"] == 1
    assert tracking["code_counts"]["line_over_limit"] == 1
    assert tracking["cases"] == [
        {
            "kind": "alert",
            "stage": "step2a",
            "code": "line_over_limit",
            "message": "contract alert: subtitle_lines[37] exceeds 17 display units",
            "line_id": 37,
            "cue_index": None,
            "text_preview": "这个例子确实已经超过十七字限制",
            "source": "step2a_alert_reasons",
            "metadata": {"limit": 17},
        }
    ]


def test_build_alert_tracking_counts_step2a_manual_review_once_without_step3_echo():
    step2a_result = Step2ADraftingResult(
        proofread=ProofreadManuscript(
            source_text="原稿",
            proofread_text="原稿",
            edit_summary="manual review required",
            proofread_confidence=0.0,
            draft_ready=False,
            drafting_warnings=["auxiliary timeout"],
        ),
        draft=SubtitleDraft(lines=[]),
        drafting_mode="manual-review-required",
        draft_model_provider=None,
        draft_model_name=None,
        draft_fallback_used=False,
        draft_fallback_reason="auxiliary timeout",
        draft_fallback_code="auxiliary_request_failed",
        draft_attempt_count=2,
        text_authority="none",
        manual_review_required=True,
        alert_reasons=["auxiliary timeout"],
    )
    finalizer_result = FinalizerResult(
        cues=[],
        finalizer_mode="manual-review-required",
        finalizer_fallback_reason="auxiliary timeout",
        finalizer_fallback_code="step2a_manual_review_required",
        text_authority="none",
        manual_review_required=True,
        alert_reasons=["auxiliary timeout"],
    )

    tracking = build_alert_tracking(
        step2a_result=step2a_result,
        subtitle_draft=step2a_result.draft,
        step2a_alert_reasons=["auxiliary timeout"],
        step2b_alert_reasons=[],
        script_pass_cues=[],
        finalizer_result=finalizer_result,
        step3_validation_alert_reasons=[],
        edited_cues=[],
    )

    assert tracking["alert_case_count"] == 0
    assert tracking["manual_review_case_count"] == 1
    assert tracking["stage_counts"]["step2a"]["manual_review_count"] == 1
    assert tracking["stage_counts"]["step3"]["manual_review_count"] == 0
    assert tracking["code_counts"]["auxiliary_request_failed"] == 1
    assert tracking["cases"] == [
        {
            "kind": "manual_review",
            "stage": "step2a",
            "code": "auxiliary_request_failed",
            "message": "auxiliary timeout",
            "line_id": None,
            "cue_index": None,
            "text_preview": None,
            "source": "step2a_manual_review",
            "metadata": {
                "attempt_count": 2,
                "drafting_mode": "manual-review-required",
                "text_authority": "none",
            },
        }
    ]
