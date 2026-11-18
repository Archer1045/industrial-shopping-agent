# 当前交接状态

> 最后更新：2026-11-18 22:42 · 阿渔（revision 4 实施，待独立复核）
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

## 进行中：头型冲突进 evaluate_row()（revision 4 已实施，待独立复核）

- revision 4 只动 `backend/app/demand.py` 与 `backend/eval/run_ragas.py`，未改 `main.py`（revision 1 的 `_attr_conflicts`/`product_head` 保持）。完整证据见 `log/2026-11-18.md`。
- **改动 1（否定与头型绑定）**：`_negated_heads()` 替代「子句含否定词就排除整句头型」——否定词后跳过填充词（我/给/要/用…）紧跟的头型算排除；否定词前跳过连词（和/与/都/也…）与头型词收集并列族。中间夹「价格」「数量」这类非连词时不算，`外六角的价格不要太贵` 不再误排除。
- **改动 2（放宽限定）**：`_clause_relaxed()` 要求放宽词与头型词同子句；`_bare_relax()` 要求整句去掉宽词后没有其他实词。`数量不限`/`价格随便` 不再清空头型，只认 `随便`/`都行`/`外六角内六角都行`。
- **改动 3（按出现顺序取最近表态）**：`extract_head()` 改用 `_heads_by_position()` 取最后出现的族，`要外六角，改成内六角` → 内六角。
- **改动 4（修饰语不算点名）**：`_is_head_modifier()` 把头型词后接「的 + 价格/数量/交期/贵/便宜」的当修饰语跳过。
- **改动 5（连续否定累积）**：`_head_from_users()` 从最近往前扫，否定族累积（`insert(0)` 保持时间序），遇点名/放宽清空；`parse_demand` 新增 `head_relaxed`；`merge_demand` 纯否定时把 `prev.head_excluded` 与当前并集，放宽才清空。
- **改动 6（replay 分别补值）**：`run_ragas.py` 的 `head` 与 `head_excluded` 改成分别判缺，revision 2 旧 raw 也能补全。
- **已实际运行验证**：`%TEMP%` 语义脚本 23/23 通过（价格否定、修饰语、并列双否定、数量/价格放宽、同句改口、历史累积、merge 三种分支、原有回归）；24 条 replay `row_status_accuracy=0.9583`，stage/match_kind/recall/mrr/hard/severe 全部不变。
- 仍留下一轮：风险 4/5、多需求旧 raw、`_status_matches` 对 list 直接 False（`multi-rows-021`）；未跑在线模型与前端。

## 下一步

1. 渔渔独立复核 revision 4（重点：否定邻接规则、放宽限定、累积口径、两代旧 raw）。
2. 风险 4/5 下一轮；是否补在线 RAGAS 由主人决定。
3. 其余方向仍待选：检索排序、Fine-tuning、面试材料整理。

## 阻塞

无。

## 接手入口

1. 项目根目录 `AGENTS.md`
2. 本文件
3. `.agent-handoff/plans/2026-11-16-langgraph-migration.md`
4. `docs/ragas-baseline-2026-11-16-graph.md`
5. `.agent-handoff/plans/2026-11-15-ragas-baseline.md`
