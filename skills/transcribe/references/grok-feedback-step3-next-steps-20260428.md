我来同步一下当前这个字幕 Step 3 cue splitting 改造的最新成果，请你基于现状给出下一步建议，重点看执行顺序、风险点、contract 设计和 end-to-end 验证。

背景与目标：
- 工作流边界保持不变：Step 1 = FunASR；Step 2 = auxiliary + pipeline；Step 3 = live interactive agent
- 当前要解决的问题：Step 3 遇到过长字幕时，不能在同一个 cue 里插入换行符 `\n`，必须做真正的 cue-level splitting，生成多个新 cue 和新的时间戳
- 时间策略：新 cue 的 start 以首字 onset 对齐优先
- 长度策略：理想约 12 字，硬上限 17 字

你上一次给的核心建议：
- 主路径用 token-anchored
- 低置信度场景用 partial token-anchored + onset snap
- 审计里记录 split_type / start_alignment_delta_ms / risk_level
- correction_log / final_delivery_audit / report 都要补 split 相关统计

我已经完成的实现：
1. 在 `scripts/finalizer.py` 新增了 `apply_cue_splits()` helper
2. 这个 helper 已支持：
   - 把一个 cue 拆成多个新 cue
   - onset-first start 对齐
   - `token_anchored` 与 `partial_token_anchored` 两条落地路径
   - 返回 split metadata，包括：
     - `correction_entries`
     - `cue_splits`
     - `split_statistics`
3. `FinalizerResult` 已扩展，加入 `split_operations`
4. 已补两类测试：
   - 高置信场景：验证真 split + onset-first timing
   - 低置信场景：验证 partial token onset snap + 风险标记
5. 已更新文档：
   - `references/agent-step3-adjudication-contract.md`
   - `SKILL.md`
6. 当前测试状态：
   - `pytest tests/test_finalizer.py -q` -> 10 passed
   - `pytest -q` -> 104 passed

当前还没做完的部分：
1. 还没有把 `apply_cue_splits()` 真正接进 live Step 3 decision flow
2. 还没有把 split records 正式写进最终的 `correction_log.json`
3. 还没有把 split statistics / alignment issues 正式写进 `final_delivery_audit.json`
4. 还没有把 `edited_cue_count` / `split_count` 之类指标正式写进 `report.json`
5. 还没有拿真实 replay sample 做 end-to-end 验证，确认 cue 10 / 12 会从单 cue 内换行变成多个真正 cue

当前我想听你的下一步建议，请你直接回答这 5 件事：

1. 按最小可靠路径，下一阶段的执行顺序应该怎样排？
   - 例如：先接 live Step 3 -> 再写 audit/log -> 再做 real sample replay
   - 还是先把 schema/contract 全补完再接主流程

2. 现在这个 helper 层设计还缺什么关键 contract？
   - 比如 strict monotonic timing 校验
   - new cue ids 重排策略
   - split 后相邻 cue overlap/gap 容忍度
   - intra-token split 的显式禁用或受控开放条件

3. 对真实样本验证，你建议我重点盯哪些 failure mode？
   - cue 10 / 12 这种 low-confidence case 以外，还有哪些最容易翻车

4. correction_log.json / final_delivery_audit.json / report.json 各自最小必需字段，你会怎么定
   - 我想先做最小可审计版本，再逐步扩展

5. 如果你来决定，我下一次提交只做哪一小段最值钱的工作？
   - 请直接给一个最小但高价值的 next slice

请尽量给面向实现的建议，少讲原则，多讲顺序、边界、失败条件和最小可交付面。