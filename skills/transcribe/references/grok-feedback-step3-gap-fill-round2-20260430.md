我来同步一下当前 transcribe 仓库里一个新的 Step 3 delivery gap smoothing 问题，请你基于现状给出建议，重点看根因判断、最小实现路径、contract 设计、验证策略，以及 TG/Feishu 行为差异的解释是否合理。

背景与现状：
- 工作流边界保持不变：Step 1 = FunASR；Step 2 = auxiliary + pipeline；Step 3 = live interactive agent
- 用户的明确交付规则：
  1) 最终交付 `edited.srt` 的第一条 cue start 要强制对齐到 `0.0`
  2) 每个正 inter-cue gap 都要被填平：前一条 cue 的 end 延到下一条 cue 的 start
  3) overlap 保持原样
  4) 最后一条 cue 不延长
  5) 不改 cue text / cue order / cue indexes
- 用户反馈：在飞书调用我做音频转录时，拿到的字幕文件没有消除这些间隙；但在 Telegram 里让我转录时，效果是符合这个规则的。

我刚刚核查了当前 repo 代码，确认到这些事实：
1. `skills/transcribe/scripts/finalizer_audit.py` 当前没有任何 delivery gap smoothing 实现
   - 没有 `apply_delivery_timing_smoothing`
   - `build_delivery_audit()` 只有常规检查
   - `finalize_cues()` 当前基本是原样返回 `cues`
2. `skills/transcribe/scripts/pipeline_report.py` 当前也没有：
   - `timing_smoothed_count`
   - `delivery_timing_smoothing`
3. `skills/transcribe/scripts/pipeline.py` 的 `write_step3_review_artifacts()` 当前只是把 `finalizer_result.cues` 直接写成 `edited.srt`
   - 中间没有做任何 gap fill
4. `tests/test_finalizer.py` 当前也没有覆盖：
   - first cue snap to 0
   - fill every positive gap
   - do not extend last cue
5. 当前 repo 的未提交改动主要集中在 Step 2A runtime 注入、aux fallback metadata 修复，以及相关测试；和 gap smoothing 直接相关的文件当前没有落盘中的修改

所以我现在的根因判断是：
- 飞书那次之所以没做到，是因为当前仓库自动写回链路里根本还没有把这条 delivery-only smoothing 规则实现进去
- Telegram 那次之所以“看起来做到了”，很可能是因为当时是 live interactive Step 3 会话内人工/会话级最终裁决，把这个规则临时落实到了交付文件里，而不是 repo 自动写回链路本身具备了这能力
- 我认为这两个平台的差异，更像是“会话级人工 Step 3 收尾”和“代码固化的自动写回链路”之间的差异，而不是 TG / Feishu 平台本身的差异

我准备的最小实现方案：
1. 在 `skills/transcribe/scripts/finalizer_audit.py` 增加一个 delivery-only timing smoothing helper
   - 输入 final delivery cues
   - 输出 smoothed cues + smoothing records/metadata
2. 规则严格按用户要求：
   - first cue start -> 0.0
   - every positive gap gets filled by extending previous cue end
   - overlap unchanged
   - last cue not extended
   - text/order/index unchanged
3. 保持 `edited-script-pass.srt` 不变，只在 Step 3 最终交付 `edited.srt` 上应用
4. 把变更写入：
   - `correction_log.json` 记录 `delivery_timing_smoothing`
   - `final_delivery_audit.json` 记录 `timing_smoothed_count`
   - `report.json` 记录同名 summary 字段
5. 补测试：
   - first cue snap to zero
   - fill positive inter-cue gap
   - single cue / last cue behavior
   - overlap preserved
6. 跑完整 pytest 和一个真实 replay sample 验证

我想直接听你对这 5 件事的建议，请你逐条回答：

1. 你是否同意我的根因判断？
   - 尤其是“飞书失败来自 repo 缺实现；TG 成功来自会话级 Step 3 收尾”这个解释是否成立
   - 如果你觉得这个判断有漏洞，请直接指出

2. 这个最小实现路径是否合理？
   - 你会把 smoothing 放在 `finalize_cues()` 内部
   - 还是放在 `write_step3_review_artifacts()` 写盘前
   - 哪个位置 contract 更干净，回归风险更低

3. 对这个 delivery-only smoothing contract，你会强制哪些最小字段？
   - `correction_log.json`
   - `final_delivery_audit.json`
   - `report.json`
   请给最小必需字段集，少而够用

4. 你最担心哪些 failure mode？
   - 比如 zero-length cue、浮点边界、monotonic timing、连续多 gap、和 overlap 共存等
   - 哪些必须先用单测钉死

5. 如果你来决定，下一次提交只做哪一小段最值钱的工作？
   - 请给一个最小但高价值 next slice

请尽量给面向实现的建议，少讲原则，多讲顺序、边界、失败条件和最小可交付面。