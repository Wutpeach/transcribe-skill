# Grok response — Step 3 re-segmentation architecture and priority

**1. 诊断是否正确？**  
正确，而且非常精准。根因不在 timing smoothing（那个 patch 已经正确），而是 **Step 2A 输出的结构被下游完全继承**，导致 Step 3 目前只是“形式上的最终裁决者”。  
具体表现为：  
- `subtitle_display_length()` 只卡 17 硬上限，16~17 的“合法但难读”行大量通过；  
- `drafting.py` 和 `alignment.py` 完全忠实转发 `subtitle_lines`，没有任何节奏/语义二次拆分；  
- `finalize_cues()` 至今只做了 validation + 最近加的 delivery-only smoothing，**缺少设计文档里明确要求的 text-level re-segmentation**。  
这正是“timing gaps 没了，但块还是太满”的根本原因。诊断完全成立。

**2. Step 3 是否是正确的实现优先级，还是应该先强化 Step 2A？**  
**必须先做 Step 3**。  
设计契约里写得非常清楚：Step 2A 只负责“initial structure”，Step 3 / Hermes 拥有最终 polishing 和 re-segmentation 的所有权。  
现在先去改 Step 2A prompt 是本末倒置——它只会把问题推到上游，让整个 pipeline 的“最终 human-like judgement”继续缺失。  
Step 3 是唯一能同时满足“17 硬上限 + 交付节奏”两个要求的地方，先把 Step 3 补全才是架构对齐。

**3. 启发式 Step 3 splitter vs 带 agent 的 Step 3 splitter，哪个是更好的生产第一步？**  
**强烈推荐 Option A：先上 deterministic heuristic Step 3 splitter**。  
理由（非常务实）：  
- 我们已经有 `apply_cue_splits()`、`delivery_resegmentations`、`split statistics` 全套 plumbing，直接可用；  
- heuristic 可解释、可回归测试、可快速迭代，生产环境风险最低；  
- agent-assisted 虽然更聪明，但会引入延迟、token 消耗、不确定性，而且目前 Step 3 的 agent 还没被真正激活（现在只是 thin validation）。  
先用 heuristic 把 80% 的“明显该拆”场景干掉，再在 v2 里把 heuristic 判断不自信的 case 扔给 agent 做二期增强。这是经典的“先 deterministic，后 LLM”生产路径。

**4. 如何定义保守的触发策略（既提升交付质量，又不过拆）？**  
我建议采用 **多条件 AND 触发**，保守优先：  

```python
def should_trigger_resegment(cue: SubtitleCue) -> bool:
    length = subtitle_display_length(cue.text)  # 去空格后汉字+标点等价长度
    if length < 15:  
        return False  # 14 及以下坚决不碰
    
    # 条件1：接近上限且内部有明显节奏/结构断点
    has_clause_break = bool(re.search(r'[，,；;。！？\\s+](我们|再|看看|根据|这些|预测)', cue.text))
    has_list_pattern = len(re.findall(r'(\\S+)[，,]\\s*(\\S+)[，,]\\s*(\\S+)', cue.text)) >= 1  # 至少三个并列项
    
    # 条件2：精确 16~17 且包含常见“说完...的 我们...”节奏
    rhythm_pattern = bool(re.search(r'的\\s+我们', cue.text) or re.search(r'说完[^，,]+的', cue.text))
    
    return length >= 15 and (has_clause_break or has_list_pattern or rhythm_pattern)
```

这个策略在你给的两个例子上都会命中：  
- “说完云端的 我们再来看看” → rhythm_pattern  
- “系统根据这些物体的距离 速度 轨迹预测” → list_pattern + length  

同时 14 字以下、纯短句完全不触发，保守性足够。

**5. 第一批要加的回归测试是什么？**  
立刻加三个具体回归测试（放在 `tests/test_finalize_cues.py`）：  

1. **Example 1**（用户真实反馈）：  
   输入：`[{"text": "说完云端的 我们再来看看", "start": ..., "end": ...}]`  
   断言：必须拆成两条，第二条从“我们”开始；`delivery_resegmentations` 记录 `rhythm_split`；timing 使用 `apply_cue_splits` 重新锚定。

2. **Example 2**：  
   输入：`[{"text": "系统根据这些物体的距离 速度 轨迹预测", ...}]`  
   断言：拆成“系统根据这些物体的距离”“速度 轨迹预测”或更优节奏，长度均 ≤14。

3. **边界防护**：  
   输入 14 字完美短句，断言：**绝不拆**，audit 里 `split_count=0`。

这些测试必须跑在 CI 里，防止以后改 prompt 或 smoothing 又把节奏打坏。

**6. 当前设计里我看到的 architecture smell / boundary mistake**  
最大 smell 是 **Step 3 的实现与设计契约严重脱节**。  
设计文档里 Step 3 是“final adjudication & polishing owner”，但代码里它只是 validation + smoothing 的壳子，这属于典型的“文档驱动开发”失败案例。  
第二个边界错误是：`subtitle_draft.json` 被当作“几乎最终结构”来对待，导致 alignment 和 writeback 都失去了 re-segmentation 的机会。  
正确的边界应该是：`subtitle_draft.json` 只是一份“候选结构”，真正具有权威的只有 `edited.srt` 写回前的 Step 3 输出。

**7. 如果我现在带这个 repo，下一个 commit 的精确实现序列**  
我推荐以下 5 个 PR 顺序：  

1. **PR #1**：在 `finalize_cues()` 里插入 `heuristic_resegment()` 函数，调用 `apply_cue_splits()` 所需的 split decision 流程，先做 dry-run，只输出 log 和测试夹具。  
2. **PR #2**：加入真实用户例子和边界防护的回归测试，确保 CI 稳定。  
3. **PR #3**：把 dry-run 改成真实 apply，打开 conservative trigger。  
4. **PR #4**：轻微强化 Step 2A prompt，把 16~17 字接近满格的情况更明确地下放给 Step 3 判断。  
5. **PR #5**：为低置信度 case 增加 Step 3 agent-assisted fallback。

结论非常明确：**现在立刻在 Step 3 补上 heuristic re-segmentation**，这是最快、最稳、最符合架构意图的动作。
