**1) 是否同意首字符对齐优先级？**  
是的，我完全同意首字符（first-character onset）对齐应高于尾边界整洁度。这是正确的优先级。  
理由：字幕是**视觉+听觉同步**的媒介，用户眼睛先看到第一个字出现的时间点，如果首字符晚于说话人实际发声起点（即使只有0.2–0.3秒），就会产生明显的“滞后感”，远比尾部略长或略短更破坏观感。用户本次明确提出的“first character is where the speaker visibly starts that subtitle unit”正是行业最佳实践（Netflix、YouTube中文字幕也优先保证首字弹出时机）。  

**编码方式（Step 3逻辑+审计策略）**：  
- 每一次拆分后，新Cue的`start`必须强制等于`max(原始Cue start, 该行第一个显示字符对应的token onset)`。  
- `end`允许有±0.3秒的松弛（下一Cue的start会自然覆盖）。  
- 审计策略：在`correction_log.json`和`final_delivery_audit.json`中新增字段`start_alignment_delta`（毫秒）和`start_late_flag`（>150ms视为黄色警告，>300ms视为红色高风险），而`end_deviation`仅做信息记录，不触发高优先级告警。这样审计时可以快速过滤“首字滞后”的坏案例。

**2) 最佳时间戳再分配策略**  
**核心原则**：**始终以token-anchored为主**，绝不轻易退化为纯比例分配。  

**推荐具体流程**：  
1. 从`aligned_segments.json`读取当前Cue的`raw_token_start_index`和`raw_token_end_index`，直接拿到原始FunASR `words[]`切片（已验证包含完整`start`/`end`）。  
2. 根据语义+长度策略（目标12字符，硬上限17）在**文本层面**确定拆分点（例如“他们会考虑好我们国内的 | 法规道路情况等”）。  
3. 将拆分点映射到**最近的token边界**（优先不切token内部）。  
   - 新Cue1：`start = max(原始Cue start, Part1第一个token.start)`，`end = Part1最后一个token.end`  
   - 新Cue2：`start = Part2第一个token.start`（这就是首字符对齐的关键），`end = min(原始Cue end, Part2最后一个token.end)`  
4. **仅在以下情况**才做字符级近似插值（intra-token split）：  
   - 必须在多字符token内部拆分（如“他们会”要拆在“他们|会”），且该token时长>0.4秒。  
   - 插值公式：`split_time = token.start + (char_offset / token_char_count) * token_duration`（简单线性即可，中文发音速度相对均匀）。  
5. **绝不**在有有效token span的情况下使用纯比例分配（B方案）。比例分配只作为**最终保底**，且必须在audit中标记`used_proportional_fallback: true`。

这样既利用了FunASR已有的word级精度，又严格满足“首字符对齐”要求。

**3) 低置信度对齐案例的处理（如Cue 12）**  
Cue 12这类（low alignment confidence + skipped leading raw characters + 包含“啊/这个/的颜色”等口语噪声）**不应阻止拆分**，但必须做强审计+保守处理：  

- **仍执行token-anchored**，但只使用**高置信token**（可增加alignment_score > 0.75的过滤）。  
- 若无法找到可靠拆分token，则**退化为“半比例+首字符优先”**：  
  - 先尝试在现有token列表中找最接近语义拆分点的token onset作为新Cue start。  
  - 剩余时长才做比例分配。  
- **审计强化**：  
  - `correction_log.json`新增数组`risky_splits[]`，每条记录包含：`original_line_id`、`split_reason`、`alignment_score`、`skipped_chars`、`used_fallback`。  
  - `final_delivery_audit.json`增加`low_confidence_split_count`和`risk_flag: "manual_review_recommended"`。  
  - `report.json`里新增`subtitle_quality_metrics.low_conf_cues`统计，便于后续pipeline监控。  

这样既不牺牲长度政策，又把风险完全暴露给人工/后续审核。

**4) 最小化干净实现路径**  
**现在立刻要做的最小可靠修复（1–2天可完成）**：  
- 在Step 3（live interactive agent adjudication）或`finalizer.py`的subtitle后处理逻辑中，**彻底移除“插入\n”的行为**，改为真正的Cue拆分（生成多条SRT记录）。  
- 实现**单一的token-anchored主路径**（上述2中的1-3步），只加一个简单的intra-token线性插值作为兜底。  
- 强制所有新Cue的start按“首字符onset”规则计算。  
- 立即在`edited.srt`输出新Cue，并在`correction_log.json`记录每一次拆分的`original_cue_id`、`new_cue_ids`、`split_point_token_index`。  

**可推迟到下一次迭代**：  
- 字符级精细插值优化、语义边界自动打分模型、比例分配的智能权重等。  
- 先把当前bug（Cue 10/12仍保持旧时间戳）彻底堵死，再谈优雅。

**5) 推荐的schema/contract变更**  
- **`aligned_segments.json`**：增加校验规则（pipeline guardrail）：`raw_token_start_index`和`raw_token_end_index`必须指向有效的`raw.json` words[]，否则Step 3拒绝处理并抛`alignment_broken`错误。  
- **`correction_log.json`**：新增字段（数组）：  
  ```json
  "cue_splits": [{
    "original_line_id": 10,
    "new_line_ids": [10, 11],
    "split_type": "token_anchored",  // or "proportional_fallback"
    "start_alignment_delta_ms": 80,
    "risk_level": "low"  // or "medium/high"
  }]
  ```  
- **`final_delivery_audit.json`**：新增`split_statistics`对象（total_splits、token_anchored_ratio、low_conf_splits等）和`start_alignment_issues[]`列表。  
- **`report.json`**：新增`subtitle_metrics` section，包含`avg_chars_per_line`、`max_chars_per_line`、`first_char_alignment_compliance_rate`（百分比）。  
- **`edited.srt`**：无schema变更，但必须保证每行Cue都是独立记录（不再出现带\n的长Cue）。  
- **`finalizer.py`**：增加显式contract：`split_cue(original_cue, split_points) -> list[new_cues]`，并在Step 3 handoff前校验所有新Cue的start/end严格递增、无重叠。

**6) 对Hermes A/B/C方案的批判及更好替代**  
Hermes的A/B/C三级方案**方向正确，但过于碎片化**，容易导致代码分支爆炸和维护困难。  

**主要问题**：  
- 把“低置信”单独做C类，会让Step 3决策逻辑散落在多个if-else里。  
- B类“proportional fallback”在有token数据时仍被允许使用，违背了“首字符优先”的核心要求。  

**我建议的更好方案（取代A/B/C）**：  
**统一“Confidence-Guided Token-Anchored Pipeline”**（单路径+置信度开关）：  
1. 尝试**Full Token-Anchored**（当前alignment_score ≥ 0.75 且无skipped leading chars）。  
2. 若失败，自动降级为**Partial Token-Anchored + Onset Snap**（仍优先使用可用token的start做新Cue首字符对齐，剩余时长才比例分配）。  
3. 所有路径都记录`split_confidence`和`fallback_steps`到log/audit。  

优点：代码只有一条主路径+一个fallback分支，审计数据更结构化，也完全满足“首字符对齐”优先级。Hermes方案可以直接演进成这个统一方案，无需推倒重来。

这个设计能立即解决当前real-run bug，同时为后续迭代留下清晰、可审计、可扩展的空间。如果需要，我可以立刻给出`split_cue()`函数的伪代码框架。