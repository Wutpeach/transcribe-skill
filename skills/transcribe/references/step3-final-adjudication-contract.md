# Step 3 / Hermes Final Adjudication 设计合同（v1）

## 1. 目标

把 Step 3 建成当前转录主线里的**最终交付层**。

这一层接收已经完成对齐审计的字幕 cues，产出可以直接交付的 `edited.srt`，并把最终修改、交付风险、审计结论写进 `report.json`，在 debug 模式下补充 `correction_log.json` 与 `final_delivery_audit.json`。

一句话定义：**Step 2A 决定结构，Step 3 决定交付文本。**

## 2. 当前代码锚点

当前实现位于：

- `scripts/finalizer.py`
- `scripts/pipeline.py`
- `scripts/contracts.py`
- `tests/test_finalizer.py`
- `tests/test_pipeline.py`

当前 `scripts/finalizer.py` 只有两类动作：

1. `_replace_aliases()`
   - 依据 `run_glossary.json` 做 alias -> canonical term 替换
2. `_normalize_mixed_spacing()`
   - 处理中英混排空格

当前 `finalize_cues()` 的实际行为很轻，适合作为新 Step 3 的起点。

## 3. Stage 定位

### 3.1 Step 3 在主线中的位置

当前主线：

`raw.json -> input_preflight.json -> mode_decision.json -> run_glossary.json -> proofread_manuscript.json -> subtitle_draft.json -> aligned_segments.json -> alignment_audit.json -> edited-script-pass.srt -> Step 3 -> edited.srt + report.json`

### 3.2 Step 3 的 authority order

Step 3 内部继续沿用全流程 authority order：

`audio facts > raw timing/text evidence > protected term boundaries from run_glossary > manuscript local clues > Hermes judgment`

落地含义：

- 时间轴以审计后的 cues 为锚点
- 术语修正以 `run_glossary.json` 和局部 manuscript clues 为约束
- 最终行文、标点、混排、轻量重分段由 Step 3 决定

## 4. 输入合同

Step 3 的最小必需输入：

1. `edited-script-pass.srt`
   - 交付前脚本稿
   - 时间轴锚点来自 Step 2A + Step 5

2. `run_glossary.json`
   - 当次运行局部术语表
   - 提供 canonical term、aliases、type、source

3. `alignment_audit.json`
   - 提供 `chosen_mode`、`post_alignment_mode`、`rebuild_regions`、`reasons`
   - 供 Step 3 判断保守程度和交付风险

4. `raw.json`
   - 音频事实锚点
   - Step 3 需要保留可追溯性时可回查 segment / word 文本

Step 3 的推荐辅助输入：

5. `proofread_manuscript.json`
   - 提供 proofread 后的文本锚点和 material edits

6. `subtitle_draft.json`
   - 提供 Step 2A 的结构草稿

7. `aligned_segments.json`
   - 提供 line_id、raw token span、alignment score、warnings

## 5. 输出合同

### 5.1 必需输出

#### `edited.srt`

最终交付字幕。

要求：

- cue index 连续递增
- 时间码合法、单调、可被常见播放器加载
- 文本可读、术语稳定、中英混排自然
- 与 `edited-script-pass.srt` 保持高可追溯性

#### `report.json`

保持 compact、execution-facing。

当前已存在字段继续保留：

- `schema`
- `backend`
- `chosen_mode`
- `post_alignment_mode`
- `route_decision_reasons`
- `alignment_mean_score`
- `alignment_success_rate`
- `low_confidence_alignment_count`
- `interpolated_boundary_count`
- `fallback_region_count`
- `downgrade_count`
- `timing_metadata`
- `segmentation_stats`
- `glossary_applied`
- `glossary_term_count`
- `short_cue_count`
- `micro_cue_examples`
- `suspicious_glossary_terms`
- `entity_recovery_count`
- `entity_recovery_examples`
- `finalizer_change_count`
- `final_delivery_status`

建议新增字段：

- `finalizer_change_breakdown`
  - 建议结构：
    - `alias_replacements.count`
    - `alias_replacements.examples`
    - `spacing_normalizations.count`
    - `spacing_normalizations.examples`
    - `punctuation_normalizations.count`
    - `punctuation_normalizations.examples`
    - `duplicate_collapses.count`
    - `duplicate_collapses.examples`
    - `delivery_resegmentations.count`
    - `delivery_resegmentations.examples`
- `final_delivery_risk`
  - `low | medium | high`
- `final_delivery_reasons`
  - 交付判定原因数组
- `finalizer_applied_regions`
  - 被 Step 3 主动处理的 cue index 范围摘要，例如 `12-15,28`

### 5.2 Debug 输出

#### `correction_log.json`

按 cue 记录 Step 3 的文本修改。

建议结构：

```json
{
  "schema": "transcribe.correction_log.v1",
  "cue_changes": [
    {
      "cue_index": 12,
      "start": 31.2,
      "end": 33.8,
      "before": "好啊，写一份详细的一份详细的 PPT，仔细描述问题，",
      "after": "好啊，写一份详细的 PPT，仔细描述问题，",
      "change_types": ["duplicate_collapse"],
      "evidence": {
        "glossary_terms": ["PPT"],
        "alignment_warning": []
      }
    }
  ]
}
```

#### `final_delivery_audit.json`

记录 Step 3 对整份交付的审计结论。

建议结构：

```json
{
  "schema": "transcribe.final_delivery_audit.v1",
  "status": "ready",
  "risk": "low",
  "checks": {
    "timing_monotonic": true,
    "empty_text_count": 0,
    "micro_cue_count": 1,
    "overlong_line_count": 0,
    "glossary_conflict_count": 0,
    "unresolved_suspicious_fragment_count": 0
  },
  "reasons": []
}
```

## 6. Step 3 责任边界

### 6.1 Step 3 负责的内容

1. **术语交付归一**
   - alias -> canonical term
   - 大小写归一
   - mixed-script proper noun 保形

2. **中英混排与空白规范化**
   - 中文与拉丁字符、数字之间的可读空格
   - 多余空白压缩

3. **轻量标点与符号规范化**
   - 连续异常标点压缩
   - 中英文标点混用时的可读性整理
   - 括号、破折号、引号等表层一致性

4. **轻量文本纠偏**
   - 连续重复短语 collapse
   - 明显 delivery 噪声清理
   - cue 内局部表层修整

5. **必要时的轻量重分段**
   - 以交付质量为目标处理少量边界
   - 主要针对 micro-cue、尾巴 cue、过长单行、明显阅读断裂

6. **最终交付审计**
   - 评估 `edited.srt` 是否 ready
   - 产出风险等级和原因

### 6.2 由其他阶段负责的内容

- manuscript 校对锚点由 `build_proofread_manuscript()` 负责
- 单行字幕草稿由 `build_subtitle_draft()` 负责
- token-span 对齐由 `align_draft_to_raw_tokens()` 负责
- downgrade 与弱区域信号由 `build_alignment_audit()` 负责
- 大范围语义改写由未来 Hermes 深度交付 runtime 单独立项

## 7. Step 3 允许的修改类型

建议把 Step 3 改动分成三级，便于代码实现和 report 统计。

### A 级：确定性安全改动

直接进入 v1：

- glossary alias 替换
- 大小写归一
- 中英混排空格整理
- 重复空白压缩
- 标点表层整理

特点：

- 依赖规则即可完成
- 可回归、可统计、风险低

### B 级：保守文本修整

进入 v1，但需要审计记录：

- 连续重复片段 collapse
- 相邻高相似冗余片段 collapse
- 局部 delivery 噪声清理

约束：

- 保持原 cue 时间范围
- 保持 cue 顺序
- 保持核心语义
- 记录到 `correction_log.json`

### C 级：受控重分段

作为 v1.1 目标，当前合同先定边界：

- 连续 micro-cue 在证据充分时并入相邻 cue

约束：

- 仅处理连续 micro-cue
- 优先向相邻 cue 合并
- 保持总覆盖时间范围不变
- 保持 raw span 顺序
- `alignment_audit.json` 或 `aligned_segments.json` 里有明确 warning 证据
- 每次重分段都写入 `finalizer_change_breakdown.delivery_resegmentations`
- 每次重分段都在 `final_delivery_audit.json` 记录 `resegment_source`

## 8. Step 3 禁止越界的行为表达为工程规则

这里用工程规则直接定义边界：

1. Step 3 保持**局部修整优先**。
2. Step 3 保持**时间轴稳定优先**。
3. Step 3 保持**语义保守优先**。
4. Step 3 保持**与 Step 2A 产物高可追溯性**。
5. Step 3 对 manuscript 的使用保持**局部证据约束**。
6. Step 3 的每次主动文本变化都应当可计数、可抽样、可回放。

## 9. 建议的内部处理流水线

建议把 `finalize_cues()` 扩成一个可审计的小流水线：

1. `validate_finalizer_inputs()`
2. `apply_glossary_normalization()`
3. `apply_mixed_spacing_normalization()`
4. `apply_surface_punctuation_cleanup()`
5. `collapse_duplicate_fragments()`
6. `repair_delivery_boundaries_if_needed()`
7. `build_final_delivery_audit()`
8. `build_correction_log()`

建议接口形态：

```python
@dataclass
class FinalizerResult:
    cues: list[SubtitleCue]
    change_breakdown: dict[str, int]
    applied_regions: list[int]
    correction_log: dict
    delivery_audit: dict


def finalize_cues(
    *,
    cues: list[SubtitleCue],
    glossary: RunGlossary,
    audit: AlignmentAudit | None = None,
    raw_payload: dict | None = None,
    proofread: ProofreadManuscript | None = None,
    aligned_segments: list[dict] | None = None,
) -> FinalizerResult:
    ...
```

这会带来两个直接收益：

- `pipeline.py` 可以把 report 写得更清楚
- debug 文件可以由返回值直接落盘

`validate_finalizer_inputs()` 建议检查：

- cues 基本合法性：index 连续、`start < end`、文本非空
- 辅助输入 schema version
- `edited-script-pass.srt` cues 与 `aligned_segments.json` 的 line count / index 一致性
- cue 文本与辅助输入的 hash 或摘要一致性

当辅助输入缺失或校验失败时，Step 3 进入保守 fallback：

- 继续执行 A 级规则
- 跳过依赖辅助证据的 B / C 级动作
- 在 `final_delivery_audit.json` 和 `report.json` 里写入 fallback reason

## 10. Pipeline 集成要求

### 10.1 `scripts/finalizer.py`

建议保留文件名，直接扩展。

需要新增：

- `FinalizerResult` dataclass
- 细分 change breakdown
- duplicate cleanup 能力
- final delivery audit 能力
- correction log 输出数据结构
- 可选的轻量 resegmentation hook

### 10.2 `scripts/pipeline.py`

需要改动：

1. `finalize_cues()` 返回 `FinalizerResult`
2. `edited.srt` 从 `finalizer_result.cues` 落盘
3. `_write_report()` 接收：
   - `finalizer_change_breakdown`
   - `final_delivery_risk`
   - `final_delivery_reasons`
   - `finalizer_applied_regions`
4. debug 模式下落盘：
   - `correction_log.json`
   - `final_delivery_audit.json`

### 10.3 `scripts/contracts.py`

建议新增两个 dataclass：

- `FinalDeliveryAudit`
- `CueCorrectionLog` / `CueCorrectionChange`

当前阶段也可以先保持为 `dict`，让实现启动更快。

## 11. 测试合同

### 11.1 单测

新增或扩展：

- `tests/test_finalizer.py`
- `tests/test_pipeline.py`

建议覆盖：

1. **glossary 归一**
   - `s7 -> S7`
   - `funasr api -> FunASR API`

2. **mixed spacing**
   - `讲到hps和funasr api -> 讲到 HPS 和 FunASR API`

3. **重复片段 collapse**
   - `一份详细的一份详细的 PPT -> 一份详细的 PPT`
   - 保住 `埃安 S / 埃安 Y / 自働化`

4. **change breakdown**
   - `report.json` 正确统计 alias / spacing / duplicate cleanup

5. **correction log**
   - 只记录发生变化的 cues

6. **delivery audit**
   - micro-cue、空文本、非法时间范围能被识别

### 11.2 pipeline 回归

建议至少保留三类 case：

1. 纯 glossary + spacing case
2. manuscript-backed entity recovery case
3. 真实样本 replay case
   - 重点观察 `edited-script-pass.srt -> edited.srt` 的差异

## 12. v1 实现顺序

v1 范围：**A 级 + B 级**。

v1.1 范围：**C 级受控 micro-cue merge**。

### Task 3.1
扩展 `scripts/finalizer.py` 返回 `FinalizerResult`，保留现有 alias + spacing 行为，并加入输入校验。

### Task 3.2
给 `report.json` 加入：

- `finalizer_change_breakdown`
- `final_delivery_risk`
- `final_delivery_reasons`
- `finalizer_applied_regions`

### Task 3.3
加入 `collapse_duplicate_fragments()`，先覆盖 cue 内连续重复与高相似相邻短语。

### Task 3.4
加入 `correction_log.json` 与 `final_delivery_audit.json` 落盘。

### Task 3.5
加入受控 micro-cue merge hook，先处理连续 micro-cue 合并，并把 `resegment_source` 写入 `final_delivery_audit.json`。

## 13. 验收标准

满足以下条件时，Step 3 v1 可以视为成立：

1. `edited.srt` 在当前 sample 与回归样本上稳定生成。
2. `report.json` 能说明 Step 3 到底改了什么。
3. `PPT` 重复片段类问题能在 Step 3 留下一层清晰兜底。
4. `埃安 S / 埃安 Y / 自働化` 这类已修复实体保持稳定。
5. `pytest tests/ -q` 全绿。
6. 任何 Step 3 主动改动都能在 debug 输出里追溯。

## 14. 决策结论

下一阶段开发的主任务已经很清楚：**把 `scripts/finalizer.py` 从“术语替换器”升级成“最终交付层”。**
