from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"



def test_step2a_manuscript_prompt_uses_revised_whole_file_readability_style():
    prompt = (PROMPTS_DIR / "understanding" / "manuscript_understanding.md").read_text(encoding="utf-8")

    assert "整份字幕从头到尾读起来" in prompt
    assert "工作原则" in prompt
    assert "语义停顿" in prompt
    assert "口语节奏" in prompt
    assert "约 12 个汉字量级" in prompt
    assert "17 个汉字量级是硬上限" in prompt


def test_step2a_manuscript_prompt_hardens_punctuation_free_serial_token_handling():
    prompt = (PROMPTS_DIR / "understanding" / "manuscript_understanding.md").read_text(encoding="utf-8")

    assert "A-B-C-D" in prompt
    assert "A B C D" in prompt
    assert "连接符" in prompt


def test_step2a_manuscript_prompt_matches_json_contract_field_names():
    prompt = (PROMPTS_DIR / "understanding" / "manuscript_understanding.md").read_text(encoding="utf-8")

    assert "proofread_text" in prompt
    assert "subtitle_lines" in prompt
    assert "proofread_manuscript:" not in prompt
    assert "subtitle_draft:" not in prompt



def test_step2a_manuscript_prompt_mentions_fragment_avoidance_and_hanging_hps():
    prompt = (PROMPTS_DIR / "understanding" / "manuscript_understanding.md").read_text(encoding="utf-8")

    assert "单字尾巴" in prompt
    assert "悬空助词" in prompt
    assert "碎片感" in prompt
    assert "的 HPS" in prompt



def test_step2a_manuscript_prompt_includes_regression_examples_for_target_segmentation():
    prompt = (PROMPTS_DIR / "understanding" / "manuscript_understanding.md").read_text(encoding="utf-8")

    assert "现在的新能源车" in prompt
    assert "开发周期已经压到了三年以下" in prompt
    assert "因为本田的管理理念" in prompt
    assert "是脱胎于精益生产的 HPS" in prompt


def test_step2a_manuscript_prompt_includes_hard_cap_regression_calibration_examples():
    prompt = (PROMPTS_DIR / "understanding" / "manuscript_understanding.md").read_text(encoding="utf-8")

    assert "硬约束校准" in prompt
    assert "他们会考虑好我们国内的法规道路情况等" in prompt
    assert "详情咱们可以参考日本 JR 福知山线的脱轨事故" in prompt
    assert "东本和广本基本就决定个车内外颜色啥的" in prompt
    assert "警戒区" in prompt
    assert "禁止原样输出" in prompt



def test_step3_final_adjudication_prompt_mentions_short_cue_recut_trigger():
    prompt = (PROMPTS_DIR / "final_delivery" / "final_adjudication.md").read_text(encoding="utf-8")

    assert "像机器硬切" in prompt
    assert "铺垫与落点" in prompt
    assert "未超长" in prompt


def test_step3_final_adjudication_prompt_allows_true_cue_level_splitting():
    prompt = (PROMPTS_DIR / "final_delivery" / "final_adjudication.md").read_text(encoding="utf-8")

    assert "cue-level splitting" in prompt or "cue splitting" in prompt or "新 cue" in prompt
    assert "不要自行增删 cue 数量" not in prompt
