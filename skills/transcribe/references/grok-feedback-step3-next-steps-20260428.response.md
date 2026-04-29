**1. 按最小可靠路径，下一步执行顺序建议：**

先补全 contract/schema（1-2 小时工作量），再接 live Step 3 decision flow，再补 audit/log/report 写入，最后 real sample replay E2E。

具体顺序：
- **Step A（今天就能做完）**：在 `references/agent-step3-adjudication-contract.md` 里把 `FinalizerResult.split_operations`、`correction_log`、`final_delivery_audit`、`report.json` 的 cue splitting 字段结构先写死（见第4点我给的最小 schema）。
- **Step B**：把 `apply_cue_splits()` 真正调用进 live Step 3 的 decision flow（建议加个 config flag `enable_cue_splitting: true`，fallback 仍是老的 `\n` 逻辑），只改 decision 点和 FinalizerResult 组装。
- **Step C**：在 finalizer 里把 helper 返回的 `correction_entries` / `cue_splits` / `split_statistics` 写入三个 JSON（先只写最小字段）。
- **Step D**：拿 3-5 个真实 replay sample（重点 cue 10/12）跑 end-to-end，验证输出 SRT/渲染是否正确。

理由：schema 先定死，后续写入和集成就不会反复改 contract；live flow 早接早发现 timing / monotonic 问题；audit 放最后不影响主路径交付。

**2. helper 层现在还缺的关键 contract（必须立刻补）：**

当前 `apply_cue_splits()` 已经很接近生产可用，但缺下面 4 个硬约束（建议直接加到 helper docstring + 单元测试断言里）：

- **Strict monotonic timing 校验**（必须）：输出 cue list 全局 start 时间必须严格非递减（`new_cues[i].start <= new_cues[i+1].start`），同一 cue 内 `start < end`。允许最大 gap=200ms、最大 overlap=0ms（overlap 直接抛或 risk_level=high 并 auto-snap 以 onset 为准）。超出即在 metadata 里标记 `timing_violation: true`。
- **New cue ids 重排策略**：固定采用 `original_cue_id + ".split.{n}"`（n 从 1 开始递增）。必须在 `cue_splits` metadata 里保留 `original_cue_id -> [new_cue_ids]` 映射，方便下游 audit 和 correction_log 回溯。
- **Split 后相邻 cue overlap/gap 容忍度**：明确定义 `max_allowed_gap_ms=200`, `max_allowed_overlap_ms=0`。如果前一个 cue 的 end > 下一个 cue 的 start，直接在 helper 里做 onset-first 微调（优先保持首字 onset），否则 risk_level=high 并记录 `adjustment_delta_ms`。
- **Intra-token split 显式禁用规则**：`token_anchored` 路径下**硬禁**（只能在 token 边界拆）；`partial_token_anchored` 路径只在 `length > 25 && confidence < 0.6` 时才允许，且必须在 `correction_entries` 里打 `intra_token_split: true` + `risk_level: high`。同时补一个 `length_calc_fn`（当前中文字符 `len(text.replace(" ", ""))`），写死在 contract 里。

这些 contract 补完后，helper 就真正“可上线”了。

**3. 真实样本验证重点盯的 failure mode（除了 cue 10/12 low-conf case）：**

优先级从高到低：

- **Timing cascade drift**：连续 3+ 个 cue 被 split 后，后续 cue 的 start/end 累计漂移 >300ms（最容易翻车，尤其长视频）。
- **Onset snap 在 noisy/quiet 段失效**：partial token 路径下，音频 onset 数据本身漂移或缺失，导致新 cue 提前/滞后明显（lip-sync 坏）。
- **Edge case 长度计算错误**：cue 包含 emoji、标点、全半角混合、或 sentence 中间无标点长句 → split 位置错或长度超 17 字仍未拆。
- **Post-split 极短 cue**：拆完出现 <5 字 cue（闪屏 + 渲染性能问题）。
- **Regression on 非长 cue**：短 cue（<12 字）被误触发 split，或 split 后整个 cue list 顺序乱掉。
- **Downstream live 渲染问题**：cue 数量突然暴增导致 agent 响应延迟或前端 rendering queue 溢出。
- **Fallback 场景**：helper 抛异常或无法拆时，是否正确回退到原始 cue（不能丢 cue）。

建议先用 2 个 long-cue replay + 1 个 noisy audio sample 跑，重点 diff 前后 SRT 的 timing 和 cue 数量。

**4. 三个 JSON 的最小必需字段（最小可审计版本，先这么落地，再扩展）：**

```json
// correction_log.json （每条 correction 一条 entry）
{
  "timestamp": "2026-04-28T08:xx:xx",
  "type": "cue_split",
  "original_cue_id": "cue_012",
  "split_type": "token_anchored | partial_token_anchored",
  "original_text": "...",
  "new_cues": [
    {"cue_id": "cue_012.split.1", "start_ms": 12340, "end_ms": 12890, "text": "...", "onset_delta_ms": 12}
  ],
  "risk_level": "low | medium | high",
  "reason": "length>17",
  "alignment_delta_ms": 45
}

// final_delivery_audit.json （放 cue_splitting 节点下）
{
  "cue_splitting": {
    "split_count": 7,
    "edited_cue_count": 4,
    "total_cues_before": 156,
    "total_cues_after": 163,
    "high_risk_count": 2,
    "avg_length_post_split": 11.8,
    "max_length": 17,
    "timing_issues_count": 0,
    "mean_alignment_delta_ms": 28
  }
}

// report.json （summary）
{
  "cue_splitting": {
    "split_count": 7,
    "split_ratio": "4.5%",
    "avg_cue_length": 11.8,
    "high_risk_splits": 2
  }
}
```

所有字段都从 `apply_cue_splits()` 返回的 metadata 直接映射，contract.md 里写清楚 key 含义和类型。

**5. 如果我来决定，下一次提交只做这一小段最值钱的工作：**

**最小高价值 next slice（预计 2-3 小时，可一次 PR 合入）**：

把 `apply_cue_splits()` **真正接进 live Step 3 decision flow**（加 config flag 控制），同时在 finalizer 里**只写入 correction_log.json 的最小 split records**（用上面 schema），然后立刻跑 3 个真实 replay sample（至少包含 cue 10/12），把 E2E 验证结果贴到 PR description。

不碰 final_delivery_audit 和 report（后面补），也不做全面统计扩展。

这样做能：
- 立刻把核心功能上线路径走通
- 拿到真实 timing / risk feedback
- 保持变更极小，review 容易
- 下一轮再补 audit 和 report 就水到渠成

需要我帮你把 contract.md 里那 4 个新 section 的草稿直接写出来，或者帮你 review integration 点的伪代码，随时说。
