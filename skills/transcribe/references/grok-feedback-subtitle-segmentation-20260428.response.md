**1) diagnosis**

当前 Step 3 的输出（edited.srt）确实存在两个核心偏差，与 pipeline 的最终交付目标不符：

1. **分割方式错误**：Step 3 把“字幕过长”处理成了“单 cue 内插入换行符”（in-cue line break），而非真正的 cue-level re-segmentation。结果是 cue 索引、时间码均未增加，仅仅视觉上折行。这违背了“subtitle rhythm and readable cadence”的核心要求，也让后续播放器无法按自然节奏显示。

2. **长度策略偏差**：当前以 17 个中文字符作为硬上限，Step 2A/Step 3 均未把“理想长度约 12 个字符单位”作为优化目标。部分接近 17 的行在语义和节奏上仍有明显可切点，却被保留，导致最终字幕“视觉偏长、呼吸感差”。

这两个问题共同导致 edited.srt 的 cue 数量与 script_pass_cue_count 始终一致，无法体现 Step 3 的“final delivery judgment”价值，也使 correction_log.json 无法完整记录 one-to-many 的变换轨迹。

**2) recommended design**

**核心原则**  
- Step 3 必须拥有“cue 分裂权”：当一条 cue 长度 > 12 且存在自然语义/节奏切点时，**必须**拆成多条独立 cue，而非仅换行。  
- 分裂决策由 Step 3 完成，时间码重分配也由 Step 3 完成（Step 2A 只负责初稿）。  
- 所有操作必须可审计、可回溯。

**Step 3 如何创建新 cue 并重分配时间码（显式流程）**：

1. 读取 `edited-script-pass.srt` + `aligned_segments.json` + `alignment_audit.json`。
2. 对每条原 cue（记为 cue_i，起止时间 t_start ~ t_end，文本 text_i）：
   - 计算字符单位长度（中文=1，英文单词≈2，标点=0.5）。
   - 若长度 ≤ 12 或无合适切点 → 保留原 cue。
   - 若长度 > 12 且存在语义切点（逗号、句号、逻辑停顿）：
     - 在 aligned_segments 中找到 text_i 对应的 word/char-level 时间戳序列。
     - 在最佳切点位置（优先 10~14 字符区间内最自然的语义边界）取该位置的精确时间戳 t_split。
     - 创建两条新 cue：
       - 新 cue A：索引 = 当前最大索引+1，时间 = t_start → t_split，文本 = 前半段（保持原换行逻辑但不再需要换行）。
       - 新 cue B：索引 = 当前最大索引+2，时间 = t_split → t_end，文本 = 后半段。
     - 若 t_split 与原边界差距极小（<80ms），则使用 aligned_segments 中最近的 pause/breath 点作为 t_split（保证节奏自然）。
3. 保证全局时间码单调递增、无重叠、总时长不变。
4. 将分裂记录写入 `correction_log.json`：
   ```json
   {
     "type": "cue_split",
     "original_cue_index": 10,
     "original_time": "00:00:24,440 --> 00:00:27,500",
     "split_point": "他们会考虑好我们国内的",
     "new_cues": [
       {"index": 10, "time": "00:00:24,440 --> 00:00:25,800", "text": "他们会考虑好我们国内的"},
       {"index": 11, "time": "00:00:25,800 --> 00:00:27,500", "text": "法规道路情况等"}
     ]
   }
   ```
5. `final_delivery_audit.json` 增加字段 `cue_split_operations`（数组）和 `final_cue_count`。
6. `report.json` 更新 `edited_cue_count`（允许 > `script_pass_cue_count`），新增 `avg_cue_length_units`、`split_ratio` 等统计字段。

**3) minimal code-change path**

最小改动集合（优先级从高到低）：

1. **Step 3 agent（Grok 侧）**：
   - 修改输出逻辑：不再输出带 `\n` 的多行文本，而是直接生成多条独立 SRT 条目。
   - 新增函数 `split_cue_if_needed(cue, aligned_segments)`，返回 list of new cues。
   - 写入 `edited.srt` 时直接使用新 cue 列表。

2. **finalizer.py**：
   - 放宽 `edited_cue_count` 必须等于 `script_pass_cue_count` 的断言，改为 `>=` 并记录差值。
   - 在 `finalize_delivery()` 中支持读取 Step 3 输出的新 cue 列表，直接覆盖原 SRT。

3. **contracts / schemas**：
   - `correction_log.json` schema 增加 `"cue_split"` 类型。
   - `report.json` schema 增加 `edited_cue_count`、`split_ratio` 字段（向后兼容）。
   - `agent_review_bundle.json` 无需改动（已包含所有必要 artifact）。

4. **aligned_segments validation**：
   - 在 Step 3 内部新增 `cue_split_aware` 模式：允许一条原 segment 映射到多条 edited cue，但仍校验时间单调性。

上述改动仅需新增 ~150 行代码，主要集中在 Step 3 agent 和 finalizer 的审计部分。

**4) tests to add**

必须新增以下单元/集成测试：

1. **cue_split_test**：输入长度 18 的单 cue + aligned timestamps，验证输出 2 条 cue、索引连续、时间单调、总时长不变。
2. **timing_redistribution_test**：验证 t_split 来自 aligned_segments 精确位置，而非简单按字符比例切（避免“切在词中间”）。
3. **monotonicity_test**：全量 SRT 测试，确认所有 cue 的 end_time ≤ 下一条 start_time（误差 < 10ms）。
4. **correction_log_audit_test**：验证每一次 split 都在 correction_log 中有完整 one-to-many 记录。
5. **end_to_end_replay_test**：使用当前问题样本（cue 10、12），确认 edited.srt 中 cue 数量增加、长度落在 10~14 区间。
6. **regression_test**：短 cue（≤12）不分裂，保证向后兼容。

**5) prompt/policy changes for the 12-unit target**

**Step 2A prompt（subtitle_draft 阶段）升级**：
- 原“最大不超过 17” → 新增明确 policy：
  “理想单行长度为 10~14 个中文字符单位（目标中心 12），17 为绝对硬上限。只有当无法找到自然语义切点时才允许接近 17。优先在逗号、逻辑停顿处切分。”

**Step 3 review logic / system prompt 升级**（Grok 侧）：
- 新增一段 policy 指令：
  “你必须主动执行 cue-level splitting。当一条 cue 长度 ≥ 13 时，检查是否存在自然语义边界。若存在，则使用 aligned_segments 中的时间戳在最佳位置分裂成两条独立 cue（每条目标 10~14 字符）。仅当无法分裂（无对齐信息或时间窗 < 0.6s）时，才允许保留单 cue 并使用换行。最终输出必须是纯 cue 列表，不再包含任何 in-cue newline。”
- 增加显式检查列表：
  - 优先切点：逗号、句号、连接词（如“和”、“等”）、主谓/动宾边界。
  - 禁止行为：仅因长度接近 17 就换行而不分裂。

**全局 policy 文档更新**：
- 在 workflow summary 中明确：  
  “Step 3 拥有最终分割权，目标是让 90% 以上的 cue 长度落在 10~14 字符区间，平均长度接近 12。”

完成以上调整后，当前问题样本中的 cue 10 和 cue 12 将被正确拆分为 4 条独立 cue，节奏更自然，edited.srt 也将完全符合最终交付形态。