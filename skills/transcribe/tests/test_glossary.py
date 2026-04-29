import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from glossary import AuxiliaryCorrection, build_run_glossary, write_run_glossary


def test_build_run_glossary_emits_empty_structure_without_manuscript(tmp_path):
    raw_payload = {"text": "纯中文测试。", "segments": []}

    glossary = build_run_glossary(raw_payload=raw_payload, manuscript_text=None)
    output_path = tmp_path / "run_glossary.json"
    write_run_glossary(glossary, output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "transcribe.run_glossary.v1"
    assert payload["terms"] == []


def test_build_run_glossary_extracts_mixed_script_terms_from_manuscript():
    raw_payload = {
        "text": "他造过的s7，也聊到hps，还提到岚图free和funasr api。",
        "segments": [],
    }
    manuscript_text = "他造过的 S7，也聊到 HPS，还提到岚图 Free 和 FunASR API。"

    glossary = build_run_glossary(raw_payload=raw_payload, manuscript_text=manuscript_text)
    terms = {entry.term: entry for entry in glossary.terms}

    assert "S7" in terms
    assert "HPS" in terms
    assert "岚图 Free" in terms
    assert "FunASR API" in terms
    assert "s7" in terms["S7"].aliases
    assert "hps" in terms["HPS"].aliases


def test_build_run_glossary_filters_sentence_fragments_and_keeps_term_like_entries_only():
    raw_payload = {
        "text": "东风有岚图free，这个ppt还分好几个阶段，日本jr福知山线，他造过的s7，也聊到hps。如果你a阶段发现的问题来不及提交ppt，这个问题得留到b阶段。",
        "segments": [],
    }
    manuscript_text = "东风有岚图 Free，这个 PPT 还分好几个阶段，日本 JR 福知山线，他造过的 S7，也聊到 HPS。如果你 A 阶段发现的问题来不及提交 PPT，这个问题得留到 B 阶段。"

    glossary = build_run_glossary(raw_payload=raw_payload, manuscript_text=manuscript_text)
    terms = {entry.term: entry for entry in glossary.terms}

    assert "岚图 Free" in terms
    assert "PPT" in terms
    assert "JR" in terms
    assert "S7" in terms
    assert "HPS" in terms

    assert "如果你 A" not in terms
    assert "这个问题得留到 B" not in terms
    assert "东风有岚图 Free" not in terms
    assert "阶段发现的问题来不及提交 PPT" not in terms

    assert terms["岚图 Free"].type == "mixed_term"
    assert terms["PPT"].type == "pure_acronym"
    assert terms["S7"].type == "model"


def test_build_run_glossary_merges_auxiliary_corrections_without_replacing_rule_terms(monkeypatch):
    raw_payload = {
        "text": "即使广汽自己有 ins、iny，也提到自动化和 hps。",
        "segments": [],
    }
    manuscript_text = "即使广汽自己有埃安 S、埃安 Y，也提到自働化和 HPS。"

    monkeypatch.setattr(
        "glossary.request_auxiliary_glossary_corrections",
        lambda **kwargs: [
            AuxiliaryCorrection(kind="entity", original="ins", corrected="埃安 S", confidence=0.95),
            AuxiliaryCorrection(kind="entity", original="iny", corrected="埃安 Y", confidence=0.93),
            AuxiliaryCorrection(kind="term", original="自动化", corrected="自働化", confidence=0.98),
        ],
    )

    glossary = build_run_glossary(raw_payload=raw_payload, manuscript_text=manuscript_text)
    terms = {entry.term: entry for entry in glossary.terms}

    assert "HPS" in terms
    assert "埃安 S" in terms
    assert "埃安 Y" in terms
    assert "自働化" in terms
    assert "ins" in terms["埃安 S"].aliases
    assert "iny" in terms["埃安 Y"].aliases
    assert "自动化" in terms["自働化"].aliases


def test_build_run_glossary_falls_back_to_rules_when_auxiliary_call_fails(monkeypatch):
    raw_payload = {"text": "他造过的s7，也聊到hps。", "segments": []}
    manuscript_text = "他造过的 S7，也聊到 HPS。"

    def boom(**kwargs):
        raise RuntimeError("aux down")

    monkeypatch.setattr("glossary.request_auxiliary_glossary_corrections", boom)

    glossary = build_run_glossary(raw_payload=raw_payload, manuscript_text=manuscript_text)
    terms = {entry.term: entry for entry in glossary.terms}

    assert "S7" in terms
    assert "HPS" in terms
