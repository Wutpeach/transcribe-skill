1. **我完全同意你的根因判断**，尤其是“飞书失败来自 repo 缺实现；TG 成功来自会话级 Step 3 收尾”这个解释**成立且无明显漏洞**。

   当前 repo 里 finalizer_audit.py、pipeline.py、pipeline_report.py 以及 write_step3_review_artifacts() 里确实**零实现**（你列的 1-4 点已确认），自动写回链路自然不可能产生 smoothing。TG 那次“看起来做到了”，最合理的解释就是 live interactive Step 3 会话里的人工/Agent 最终裁决直接把规则落到了交付文件里（而非 repo 自动能力）。平台差异（TG vs Feishu）只是表象，本质是 **“会话级最终收尾” vs “代码固化自动写回”** 的路径差异。  
   如果以后发现两个平台调用 finalizer 的入参或 timing metadata 有细微不同，再去补查；当前判断已足够 actionable，无需额外假设。

2. **最小实现路径合理，但位置我建议改成 write_step3_review_artifacts() 写 edited.srt 之前**（而不是 finalize_cues() 内部）。

   理由和顺序：
   - edited-script-pass.srt 必须**完全不变**（这是用户硬性要求），而 finalize_cues() 是当前整个 finalizer 的核心出口，很可能被 script-pass 写盘路径、audit、或其他 future 调用共享。一旦放进去就容易污染其他 artifact，regression 风险高。
   - write_step3_review_artifacts() 是**唯一只负责最终 delivery edited.srt** 的地方，在这里调用 smoothing helper 做一次 delivery-only transform 最干净：输入 finalizer_result.cues → apply_delivery_timing_smoothing() → 写 smoothed cues 到 edited.srt，其他 artifact（script-pass、intermediate）完全不动。
   - contract 最干净：finalize_cues() 继续返回“原始 final cues”（用于 script-pass 和 audit），smoothing 只作为 delivery polish 层，回归风险最低。
   - 实现顺序：先在 finalizer_audit.py 新增 `apply_delivery_timing_smoothing(cues: list[dict]) -> tuple[list[dict], dict]`（返回 smoothed_cues + metadata），再在 write_step3_review_artifacts() 里调用它（仅在写 edited.srt 前），最后更新 report/audit。

   这样改动面最小，review 时也最容易验证“只影响 edited.srt”。

3. **delivery-only smoothing contract 的最小必需字段集**（少而够用，优先 count + bool，避免冗余 details）：

   - **correction_log.json**（记录“做了什么”）：
     ```json
     {
       "delivery_timing_smoothing": {
         "applied": true,
         "smoothed_count": 3,          // 正 gap 数量
         "first_cue_snapped": true
       }
     }
     ```
     （只加这一条 entry，细节列表先不加，后面需要 debug 再扩展）

   - **final_delivery_audit.json**（给最终交付审计）：
     ```json
     {
       "timing_smoothed_count": 3
     }
     ```
     （直接顶层或放 delivery 节下，和现有 audit 字段平级）

   - **report.json**（summary 给 pipeline report）：
     ```json
     {
       "delivery_timing_smoothing": {
         "applied": true,
         "smoothed_count": 3
       }
     }
     ```
     或直接在 summary 里加 `"timing_smoothed_count": 3`（看现有 report 结构，优先复用同名字段）。

   这三个字段就够后续 pipeline_report.py 和 audit 可视化/统计用，不需要提前塞 gap list（除非你后面要 debug 具体哪几条 cue 被改）。

4. **我最担心以下 5 类 failure mode**（按优先级排序，必须先用单测钉死）：

   | 优先级 | Failure Mode | 必须钉死的边界/条件 | 单测 case |
   |--------|--------------|----------------------|-----------|
   | 1 | Overlap 共存 | prev.end > next.start 时**完全不动**（不填、不缩短） | 2 cues 有 overlap + 后面有 positive gap |
   | 2 | First cue snap + last cue 不延长 | first.start 任意（负/正）→ 0.0；last cue end 永远不动 | single cue；2 cues（只改 first，不改 last） |
   | 3 | 浮点边界 / zero-length | gap > 0.001（用 epsilon 判 positive）；round 到 3 位小数（SRT 精度） | gap=0.0005（不填）、gap=0.0015（填）、负 gap |
   | 4 | 连续多 gap + monotonic | 链式 extend（loop i=0 to n-2）；保证每条 cue end >= start，整体 start 非递减 | 4 cues 连续 3 个 positive gap |
   | 5 | 极端输入 | 空 list、1 cue、所有 cue 已对齐 | empty cues、single cue |

   **必须先用单测钉死**：first snap、positive gap fill、overlap preserve、last not extend、single cue、consecutive gaps、floating-point edge（0.000 vs 0.001）。  
   建议在 test_finalizer.py 新增 `test_delivery_timing_smoothing_*` 一组，用 pytest parametrize 把上面 7 个 case 一次覆盖。实现时用 `decimal.Decimal` 或 `round(t, 3)` 避免浮点坑。

5. **如果你让我决定，下一次提交只做下面这一小段最值钱的工作**（最小但立即可验证的高价值 slice）：

   **Slice 1（本次 PR 就够）**：
   1. 在 `skills/transcribe/scripts/finalizer_audit.py` 新增纯函数：
      ```python
      def apply_delivery_timing_smoothing(cues: list[dict]) -> tuple[list[dict], dict]:
          # 返回 (smoothed_cues, metadata)
      ```
      严格按 5 条用户规则实现（先 copy cues，避免原地改）。
   2. 在 `tests/test_finalizer.py` 补上面表格里 7 个单测（必须 100% pass）。
   3. 在 `write_step3_review_artifacts()` 里**只加 3 行**：
      ```python
      smoothed_cues, meta = apply_delivery_timing_smoothing(finalizer_result.cues)
      # ... 写 edited.srt 用 smoothed_cues
      # 把 meta 塞到 correction_log / audit / report
      ```
   4. 跑 `pytest tests/test_finalizer.py -k "delivery_timing"` + 一个真实 replay sample（生成 edited.srt 手动 diff 确认 first=0.0 + gaps 填平 + last 不变 + overlap 原样）。

   这段 PR 改动 < 150 行，review 极快，**立即解决飞书交付问题**，同时给后续 report/audit 留好钩子。做完这一段再看是否需要进一步加 details 到 correction_log。

   下一段（等这个 merge 后再做）：把 timing_smoothed_count 真正写入 pipeline_report.py 的 summary 和 final_delivery_audit.json。

这样走，风险最低、交付最快、验证最明确。需要我帮你先写 apply_delivery_timing_smoothing 的 skeleton 代码或单测模板，直接说一声。
