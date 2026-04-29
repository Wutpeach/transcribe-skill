# 人类验收标准对齐后的转录开发重设计方案

## 结论

后续开发主线需要从“把脚本 finalizer 做厚”切换成“把 Step 2A 做成真正有判断力的语义起草层”。

原因很简单：

- 人类可交付字幕的核心在 **语义单元完整 + 阅读节奏顺 + 无标点交付文本**
- 这三件事的主战场在 Step 2A
- Step 3 继续承担保守交付、统一规范、审计与兜底

当前脚本版 Step 2A 适合作为工程骨架，适合作为 fallback，适合作为回归基线。它适合承担稳定性职责。它不适合承担人类终稿质量职责。

## 当前设计需要做的整体改变

### 1. 重排开发优先级

旧优先级：
- 先把 Step 3 越做越强
- 再考虑 Step 2A drafting 升级

新优先级：
- 先把 Step 2A 的语义化起草正式升级成模型驱动
- 再把 Step 3 保持成保守 final adjudication
- 最后补强 alignment audit 和 replay 回归

### 2. 明确人类标准归属

把“人类标准”拆到正确阶段：

#### Step 2A 负责
- proofread manuscript against audio/raw clues
- 语义单元切分
- 一行一字幕
- 交付风格 plain text
- **去掉标点符号**
- glossary / entity boundary protection
- line-to-audio alignment input preparation

#### Step 3 负责
- conservative final delivery cleanup
- 术语统一
- mixed-script spacing
- 局部重复片段兜底
- 终稿审计
- 风险标记
- debug artifact 落盘

### 3. 把脚本切分降级成 bootstrap / fallback

当前 `scripts/drafting.py` 的 `_split_text_into_lines()` 应改成：

- bootstrap 起草器
- fallback 起草器
- regression baseline

它继续存在，价值很高：
- upstream / provider 出问题时可继续跑通
- 对齐与 audit 逻辑需要稳定输入源
- replay 回归需要 deterministic baseline

它的角色从“主起草器”收束为“安全网”。

## 新的阶段设计

## Step 1 — ASR / timing

保持不变。

输出：
- `raw.json`

规则：
- `raw.json` 继续做 source of truth
- 保留 segment / word / timing 原样可追溯

## Step 2 — preflight + routing

小改，不重写。

新增两类判定：
- manuscript 可用性是否足够支撑语义起草
- 当前 run 是否允许进入 model drafting

输出继续是：
- `input_preflight.json`
- `mode_decision.json`

建议新增字段：
- `drafting_mode`: `llm-primary | bootstrap-fallback`
- `delivery_style`: `plain-no-punctuation`

## Step 2A — model-driven semantic drafting

这是重设计中心。

### 目标

把当前 Step 2A 从“规则切句器”升级成“语义字幕起草器”。

### 核心输入

- `raw.json`
- `manuscript_text` 或 `proofread_manuscript.json`
- `run_glossary.json`
- `mode_decision.json`

### 核心输出

- `proofread_manuscript.json`
- `subtitle_draft.json`
- `semantic_segments.json`（建议从 debug-only 提升为重要观察产物）
- `aligned_segments.json`
- `edited-script-pass.srt`

### 2A 的模型职责

1. **proofread manuscript**
   - 参考 audio/raw/manuscript 做轻量校对
   - 重点是术语、实体、明显口误、错别字
   - 保持信息顺序稳定

2. **semantic subtitle drafting**
   - 按语义单元生成 one-line subtitle draft
   - 每行对应一个完整信息块
   - 文本面向交付
   - **无标点符号**
   - 保留口语风格中的重点信息
   - 清理明显 ASR 噪声与无意义重复

3. **draft self-check**
   - 检查一行是否过长
   - 检查语义是否截断
   - 检查 glossary terms 是否被破坏
   - 检查是否仍含标点符号

### 2A 的脚本职责

脚本层负责：
- prompt orchestration
- provider fallback
- schema validation
- punctuation-strip validation
- glossary boundary validation
- alignment handoff

其中 punctuation-free enforcement 建议做三道硬校验：
- Step 2A 模型输出后
- Step 2B 生成 `edited-script-pass.srt` 前
- Step 3 最终交付 gate 前

也就是说：
- **判断交给模型**
- **约束交给脚本**

## Step 2B（建议显式命名）— alignment

当前概念上已经存在，建议正式写成 Step 2B。

原因：
- 语义起草和对齐是两种完全不同的工作
- 把它们都叫 Step 2A 会压扁设计边界
- 保持 Step 1 / Step 2 / Step 3 的编号连续性，能减少日志、目录、监控和回归脚本返工

### Step 2B 负责
- 把 `subtitle_draft.json` 映射回 raw token spans
- 保护 glossary entities
- 做 split point / timing interpolation
- 生成 `aligned_segments.json`
- 生成 `edited-script-pass.srt`

### 设计收益
- 2A 更像“文本起草层”
- 4 更像“时间映射层”
- 出问题时能明确判断是 draft 问题还是 alignment 问题

## Step 5 — alignment audit and downgrade

保持，但要变成更强的 gate。

建议新增专门针对人类标准的结构指标：
- `semantic_cut_suspect_count`
- `punctuation_violation_count`
- `draft_overlength_count`
- `glossary_boundary_break_count`
- `micro_cue_count`

## Step 3 — conservative final adjudication

Step 3 保持保守，不再承担“重新思考整条字幕语义”的主职责。

### Step 3 继续负责
- alias -> canonical term
- mixed zh-en spacing
- duplicate collapse fallback
- final delivery audit
- correction log
- report aggregation

### Step 3 需要新增的硬约束
- `edited.srt` 最终文本继续满足 **无标点符号**
- 如果 Step 2A 漏出标点，Step 3 可以清理
- 这属于 delivery-style enforcement，不属于 semantic drafting

## 为什么这个设计更贴近人类验收

人类看字幕时，最在意的是：
- 这行是不是一个完整意思
- 读起来顺不顺
- 有没有像写稿腔或机器腔
- 有没有碎裂、机械、重复
- 有没有标点

这些问题里：
- “术语大小写”属于收尾问题
- “语义切分和阅读节奏”属于起草问题

所以真正的人类标准需要：
- **模型负责语义切分**
- **脚本负责约束与回退**

## 关键合同改动

## 1. `subtitle_draft.json` 合同升级

建议新增字段：

```json
{
  "lines": [
    {
      "line_id": 1,
      "text": "我们中国人喜欢大空间都出了名",
      "source_mode": "manuscript-priority",
      "draft_notes": ["llm semantic draft"],
      "style_flags": {
        "punctuation_free": true,
        "delivery_plain_text": true
      },
      "quality_signals": {
        "semantic_integrity": "high",
        "glossary_safe": true
      },
      "raw_span_mapping": {
        "segment_ids": [3, 4],
        "word_start_id": 18,
        "word_end_id": 29,
        "mapping_confidence": 0.82
      }
    }
  ]
}
```

这个 mapping 可以是粗粒度候选映射，不要求 Step 2A 直接完成最终 timing。它的价值是给 Step 2B 一个更稳定的对齐起点，减少 alignment 对纯文本猜测的依赖。

## 2. `proofread_manuscript.json` 合同升级

建议新增：
- `proofread_confidence`
- `draft_ready`
- `drafting_warnings`

## 3. `report.json` 的关注点调整

新增：
- `drafting_mode`
- `subtitle_punctuation_violation_count`
- `semantic_cut_suspect_count`
- `draft_model_provider`
- `draft_model_name`
- `draft_fallback_used`
- `draft_fallback_reason`
- `draft_fallback_code`
- `draft_attempt_count`

## 4. `semantic_segments.json` 地位提升

它应该成为核心观察产物，帮助回答：
- 模型为什么这么切
- 哪些地方被强约束修正了
- 哪些行进入 alignment 前就存在风险

## 开发策略改变

## Phase A — 先改合同，再改实现

先写清：
- punctuation-free subtitle contract
- model-driven Step 2A contract
- Step 4 alignment contract
- Step 5 gate metrics

## Phase B — 最小可用 2A 模型起草

先做最小版本，但同时覆盖两条路由：
- manuscript-priority 作为主路径
- raw-priority 作为简化版并行路径

用同一套 artifact contract，允许不同 prompt profile。

本阶段完成：
- 模型输出 `proofread_manuscript.json` + `subtitle_draft.json`
- 脚本做 schema / punctuation / glossary validation
- Step 2B 复用现有 alignment 骨架并开始适配新 draft contract

## Phase C — raw-priority 下的模型辅助起草

再扩到：
- raw-priority 也可用模型起草
- 前提是保持 raw authority
- manuscript 仅作为局部证据

## Phase D — 人类验收回路

引入真正的人类验收样本集，至少分三层：

1. 术语密集样本
2. 长句解释样本
3. 强口语跳跃样本

每轮观察：
- `subtitle_draft.json`
- `edited-script-pass.srt`
- `edited.srt`
- `report.json`
- `semantic_segments.json`

## 新的短期验收标准

在你认可的 1-5 条基础上，短期最终验收应改成两层：

### 工程验收
- artifact 齐全
- fallback 正常
- replay 稳定
- 测试全绿
- Step 3 v1 report/debug 完整

### 语义验收
针对一批真实样本人工抽查：
- 每条字幕是完整语义单元
- 最终字幕无标点符号
- 明显机械切分大幅下降
- 术语和实体保持稳定
- micro-cue 受控

## 推荐的下一步任务顺序

1. **写 Step 2A / Step 2B 合同与验证器**
2. **定义 punctuation-free subtitle contract 和三道硬校验**
3. **升级 `subtitle_draft.json`，加入 `raw_span_mapping` 候选映射字段**
4. **实现 manuscript-priority 为主、raw-priority 简化并行的最小模型起草路径**
5. **适配 Step 2B alignment，使其消费新的 draft contract**
6. **保留当前脚本 drafting 作为 bootstrap fallback**
7. **建立真实样本的人类验收集和 replay 回路**

## 决策结论

后续开发计划需要做的核心改变只有一个：

**把“人类标准”的责任中心从 Step 3 转移到 Step 2A model-driven drafting，同时让 Step 3 继续做保守 finalizer。**
