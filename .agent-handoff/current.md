# 当前交接状态

> 最后更新：2026-11-17 16:05 · 渔渔（revision 3 独立复核，仍有正确性残留）
> 本文件只描述当前状态。历史过程见 `log/YYYY-MM-DD.md`。

## 项目背景

主人在 2026-11-16 确认：本项目是在尝试复刻主人当时在京东工业参与的 AI 选品，而不是凭空设计的通用导购 Demo。后续评审与优化应对照真实选品流程、参数约束、替代规则、采购校验和实际业务动作；不臆测或引入京东内部实现与敏感资料。

## 当前协作标准

自 2026-11-16 起，新批次除原计划格式外，还需遵守 `.agent-handoff/collab-automation.md` 第 8 节：声明 `allowed_paths / blocked_actions / inputs / expected_artifacts`，执行结果列实际修改文件，制品完成存在性、大小、SHA-256 和正文读回检查，失败 revision 独立留证。原子锁不代表权限边界，回执不代表任务成功。

## 当前阶段

LangGraph 渐进编排改造已完成，最终 **approved（revision 3）** 并归档。graph 已成为唯一主链路，旧线性实现、临时 engine 开关和过时说明均已清理。

## 最终交付

- 计划归档：`.agent-handoff/plans/2026-11-16-langgraph-migration.md`
- 图与 State：`backend/app/orchestration.py`
- 回调通过 RunnableConfig 传入，不进入 State；会话仍由现有 SQLite 负责，无 checkpointer。
- 检索、精排、需求解析、推荐提示词和商品数据未改。
- graph RAGAS 报告：`docs/ragas-baseline-2026-11-16-graph.md` / `.json`

## 最终验证

- 8/8 新旧结构一致，24 条 graph 规则通过。
- 切换后的 P0、多轮、假上游、索引和前端构建全部通过。
- 完整 RAGAS 与波动解释齐全。
- 最后一轮文本复核确认无默认 legacy 旧注释、无“零候选不适用”旧口径。

## 进行中：头型冲突进 evaluate_row()（revision 3 已复核，仍需定点修正）

- revision 3 共 3 个代码文件、+167/-1，未提交；渔渔 16:05 独立复核，未改实现。完整证据见 `.agent-handoff/log/2026-11-17.md` 16:05 记录。
- **已读代码确认**：当前明确表态会同时覆盖 `head/head_excluded`，未表态则二者继承，旧 prev 缺排除字段安全。子句内任一否定词会排除该子句所有头型；standalone 放宽未限定头型语境；replay 只在缺 `head` 时补两个字段。
- **已实际运行验证（通过）**：24 条 replay 保持 0.9583，其余指标和逐行关键字段不变；主自测的跨句另选、三种残留否定、双族放宽/双否定均通过。两族排除文案正确，`碳钢六角螺母 M10` 不判定；随便清空、排除族继承均正确。
- **已实际运行验证（问题）**：`外六角的价格不要太贵` 误排除外六角；历史外六角后 `数量不限` / `价格随便` 误清头型。原始无头型字段 raw 与线上一致，但 revision 2 旧 raw（有 `head`、缺 `head_excluded`）线上 `attr_conflict`、replay 错成 `ok`。同句「要外六角，改成内六角」仍取外六角；连续「内六角也不要」会覆盖较早排除。
- **建议**：暂不标最终 approved。revision 4 只修：否定与头型排除语义绑定、standalone 放宽限明确整句、`head/head_excluded` 分别判缺补值；同句改口按出现顺序。连续「也不要」的累积/覆盖口径另定并留回归。
- 风险 4/5、多需求旧 raw 和 list 状态匹配继续留下一轮；在线模型、前端及 Excel/图片端到端未跑。

## 下一步

1. 主责方按 16:05 记录做 revision 4 定点修正，再复测价格否定、非头型放宽、两代旧 raw 和 24 条 replay。
2. 风险 4/5 下一轮；是否补在线 RAGAS 由主人决定。
3. 其余方向仍待选：检索排序、Faithfulness 波动、面试材料整理。

## 阻塞

无。

## 接手入口

1. 项目根目录 `AGENTS.md`
2. 本文件
3. `.agent-handoff/plans/2026-11-16-langgraph-migration.md`
4. `docs/ragas-baseline-2026-11-16-graph.md`
5. `.agent-handoff/plans/2026-11-15-ragas-baseline.md`
