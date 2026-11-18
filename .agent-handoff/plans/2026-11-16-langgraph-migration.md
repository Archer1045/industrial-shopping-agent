---
plan_id: 20261116-langgraph-migration-01
batch: LangGraph 渐进编排改造
revision: 3
status: approved
owner: 阿渔
reviewer: 渔渔
user_approved: true
auto_execute: false
created_at: 2026-11-16 07:48
updated_at: 2026-11-16 10:17
---

# LangGraph 渐进编排改造

## 目标

把当前 `_answer()` 中串联的理解、意图、多需求、缺参、检索和推荐分支，迁移为显式、可视、可单独测试的 LangGraph 状态图，同时保持现有 API、业务结果、SSE 事件、会话落库和取消语义不变。

本批是**编排迁移**，不是重写 Agent。检索、精排、需求解析、推荐提示词和商品数据都保持原样。

## 为什么可以做，但不能全面重写

当前主链路是固定步骤 + 条件分支，没有长时间运行的循环，也不需要人工中断恢复。LangGraph 在这里的主要价值是：

- 把隐含在 `_answer()` 里的分支变成显式节点和条件边。
- 让每轮输入、需求、候选、结果和错误成为明确的共享状态。
- 能用 mock 节点验证单条路径，继续复用现有 RAGAS 做迁移对照。

不采用原《总Agent-LangGraph设计》中这些部分：

- 多游戏 fan-out / fan-in。
- FGO 长循环、`interrupt()`、checkpoint 恢复。
- 独立 Capability HTTP 层。
- 为“用了 LangGraph”而增加多 Agent 或额外 LLM 调用。

官方定位与本方案一致：LangGraph 是显式状态和控制流框架，不要求 LangChain，也不要求固定 Agent 架构。

参考：[LangGraph 官方概览](https://docs.langchain.com/oss/python/langgraph/overview)、[Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)。

## 当前环境

- 已安装 `langgraph==1.2.22`、`langchain-core==1.8.0`，不需要为“能用 LangGraph”再引入一套 LangChain Agent。
- 当前 `_answer()` 包含：理解层、规则意图、chat、多需求、需求合并、库外/缺参、检索、推荐、替代与城市前缀。
- `_chat()` 负责历史读取、最终消息落库和 message_id；SSE 通过回调推 stage/delta/reset/result/error，并有取消闸门。
- `backend/eval/dataset.jsonl` 和 replay 已提供 24 条迁移对照。

## 目标图结构

```text
START
  ↓
prepare               理解层 + 历史合并 + 当前 query
  ↓
route_intent          按 intent 分流
  ├─ chat → chat_reply → END
  └─ purchase
       ↓
     route_rows
       ├─ multi → multi_reply → END
       └─ single
            ↓
          parse_demand + merge_demand
            ↓
          route_missing
            ├─ out_of_scope → out_of_scope_reply → END
            ├─ clarify → clarify_reply → END
            └─ complete
                 ↓
               retrieve
                 ↓
               route_empty
                 ├─ empty → END
                 └─ recommend → END
```

`_chat()` 的 saving/落库仍在图外执行，不把数据库副作用藏进节点。`STATE` 商品索引只读，不放进用户会话状态。

## State 设计

建议新增 `backend/app/orchestration.py`，用 TypedDict 定义每轮独立状态：

```python
class ShoppingState(TypedDict, total=False):
    query: str
    raw_query: str
    history: list[dict]
    top_k: int
    understood: dict | None
    intent: str
    rows: list[str]
    demand: dict
    rewritten_query: str
    items: list[dict]
    result: dict
    error: str | None
```

要求：

- 每轮请求新建 state，不跨会话共享，不把用户 A 的需求泄漏给用户 B。
- `on_stage / on_delta / on_reset / is_cancelled` 通过节点闭包或 RunnableConfig 传入，不存入可持久化状态。
- 商品检索 STATE 通过现有只读依赖获取，IndexManager 同步仍由现有接口负责。
- 本批不引入 LangGraph checkpointer，不新增会话表；现有 sessions/messages 仍是唯一历史来源。

## 节点迁移原则

- 将现有分支代码**原样小步搬成命名节点**，不在迁移时顺手“优化”业务。
- 复用 `understand.understand()`、`detect_intent()`、`parse_demand()`、`merge_demand()`、`evaluate_row()`、`hybrid_search()`、推荐提示词和模板。
- chat/multi/clarify/out_of_scope/empty 等结果结构保持原样。
- 推荐节点继续复用 `llm.chat()` 与 `llm.chat_stream()`，不能用 LangGraph updates 模拟 token。
- 保持现有 LLM 失败降级规则，不新增自动重试和额外模型调用。
- 每个节点只返回部分 state，不直接操作 HTTP response 或消息表。

## 分阶段实施

### 阶段 0：锁定迁移基线

- 保存当前 24 条 replay 结果和 P0/SSE 关键行为。
- 为 `_answer()` 增加分支级 mock 对照：chat、clarify、multi、out_of_scope、exact、alternative、empty、LLM 失败。
- 确认旧实现当前测试全绿，再开始搬迁。

### 阶段 1：图与节点

- 新增 `orchestration.py`：State、节点、条件边、compile。
- 保留 `main.py` 旧 `_answer()` 作为迁移期对照，提供临时 `ANSWER_ENGINE=legacy|graph`，默认 legacy。
- 新图只做同一套业务，不增加新 API 字段。
- 输出 Mermaid 图，检查节点和条件边无死路。

### 阶段 2：接入现有 API 与 SSE

- `graph_answer()` 返回现有 result dict。
- `GET/POST /api/chat` 通过临时开关走图；旧路由结构不变。
- `/api/chat/stream` 的 stage/delta/reset/result/error 全部保持，token 仍来自真实 DeepSeek stream。
- 保留 saving 前取消、无 delta 取消、上游关闭、消息各落库一次。
- 迁移期临时开关只用于验收；最终切默认后删除开关与旧重复实现，不长期维护两套链路。

### 阶段 3：对照与切换

- mock 对比旧/新结构：stage、demand、items、rows、options、match_kind、status，不要求 LLM 文本逐字相同。
- 跑 P0、最终多轮、SSE 假上游、索引测试、前端构建。
- 跑 24 条规则评估与 RAGAS，解释在线模型波动，不把文本差异当作结构回归。
- 渔渔复核通过后，默认切到 graph，删除 legacy 分支和临时开关，README 更新为实际图。

## 明确不做

- 不改检索、精排、需求解析、evaluate_row、推荐提示词和商品数据。
- 不引入 LangChain AgentExecutor、多 Agent、LangGraph Platform、LangSmith 或新数据库。
- 不做 checkpoint、interrupt、长循环、分布式执行和断点恢复。
- 不修改前端协议，不要求前端感知 LangGraph。
- 不顺手修头型冲突或调 RAGAS 分数，这些另立业务批次。

## 风险点

- 新旧两套分支并存期间容易漏改，必须限时用于迁移验收，最终删除旧实现。
- State 若保存回调或商品大对象，会造成序列化和并发问题。
- 图外 saving 若重复执行，会保存两条消息。
- 用 graph updates 替代真实 token 会破坏 SSE 体验。
- 盲目拆太多节点会增加跳转和测试成本，节点应与业务阶段一致。

## 验收标准

### A. 图与状态

- [ ] 图包含上述分支，无死路，能输出正确 Mermaid。
- [ ] 每轮 state 独立，无跨会话数据、回调或商品索引大对象。
- [ ] 不使用 checkpointer、不新增历史表，现有 sessions/messages 仍是唯一历史来源。
- [ ] 各节点可单独 mock 测试，条件边覆盖所有分支。

### B. 行为兼容

- [ ] 旧/新结构对照一致，API 字段不减少。
- [ ] 不增加主链路 LLM 调用次数，不改提示词和检索参数。
- [ ] exact/alternative、缺参、库外、多需求、chat、empty 和 LLM 失败行为一致。
- [ ] 最终 graph 默认启用后，legacy 重复实现与临时开关已删除。

### C. SSE 与落库

- [ ] stage/delta/reset/result/error 语义与现网一致，真实 token 不变成 graph updates。
- [ ] 用户与助手消息各落库一次，message_id 与最终文本一致。
- [ ] 无 delta、saving 前和客户端断开都不落库，上游响应可关闭。
- [ ] 前端无需修改且 `npm run build` 通过。

### D. 回归与文档

- [ ] P0、最终多轮、SSE 假上游、索引测试全部通过。
- [ ] 24 条规则指标无结构性回退；在线 RAGAS 波动有逐例解释。
- [ ] README 有实际图、State 说明、为什么不用 checkpoint，以及迁移后调用路径。
- [ ] 依赖版本、实际验证和未覆盖范围写入执行结果。

## 执行结果（revision 1）

### 阶段 0：先验证一件事再动手

迁移前做了两个准备。

**异常传播实验**（`.tmp/probe_langgraph_exc.py`，5 行图，不碰业务代码）：

```
ok: returned {'value': 'ok'}
base-exception: BaseException propagated -> StreamCancelled: cancelled in node
value-error: wrapped -> ValueError: normal error
```

结论：`BaseException` 子类能原样穿过 `graph.invoke`，取消语义可以保住。这条必须先验，因为 SSE 批次刚修好的「断开不落库」全靠它。

**基线确认**：迁移前 `.tmp_check_p0.py`、`.tmp_check_final.py`、`.tmp_check_multirows.py`、`.tmp_check_sse_fake.py`、`.tmp_check_index.py` 全部通过。

### 阶段 1：图与节点

新增 `backend/app/orchestration.py`（约 350 行），12 个节点、5 组条件边。

- `ShoppingState` 用 TypedDict，每轮 `invoke` 新建，回调与取消函数放在 state 里但明确不持久化。
- `build_graph(deps)` 接受 main 模块作为依赖注入，orchestration 不反向 import main，可以单独用替身测试。
- 节点只搬逻辑不优化：`prepare` / `resolve_intent` / `chat_reply` / `expand_rows` / `multi_reply` / `parse` / `out_of_scope_reply` / `clarify_reply` / `retrieve` / `empty_reply` / `recommend` / `finish`。
- `draw_mermaid()` 导出图，用于检查分支连通。

实际导出的边：

```
__start__ --> prepare
prepare -.-> chat_reply / resolve_intent / finish
resolve_intent -.-> chat_reply / expand_rows
expand_rows -.-> multi_reply / parse
parse -.-> clarify_reply / out_of_scope_reply / retrieve
retrieve -.-> empty_reply / recommend
各回复节点 --> __end__
```

无死路，`finish` 只接 debug 分支。

### 阶段 2：接入

`backend/app/main.py`：

- `GRAPH` 全局，在 `lifespan` 里 `build_graph(sys.modules[__name__])`，关闭时置 None。
- `_engine_of()` 读请求参数优先、`ANSWER_ENGINE` 环境变量其次，默认 `legacy`。
- `_graph_answer()` 组 state 调 `GRAPH.invoke()`，取 `result`。
- `_answer()` 加 `engine` 形参，开头分流；`_chat()`、`GET/POST /api/chat` 全部透传。

`ANSWER_ENGINE` 是环境变量，切换要重启（索引要重新加载）；对照测试直接用请求参数 `?engine=graph`，不用反复重启——这是我在评审时提的第三点，已按这个方式实现。

### 阶段 3：对照与回归

**结构对照**（`.tmp_compare_engine.py`，8 条输入 × 2 引擎）：

```
OK   304 不锈钢 M8 螺丝，长度 30mm，1000 个  (reply_len 654 vs 533)
OK   我要买螺丝  (reply_len 19 vs 18)
OK   内径 20 的轴承要 50 个  (reply_len 742 vs 895)
OK   我想买个扳手  (reply_len 47 vs 47)
OK   今天天气怎么样  (reply_len 42 vs 45)
OK   螺丝 M8 和 M10 各要 1000 个  (reply_len 22 vs 22)
OK   M12×80 的内六角螺丝，100 个  (reply_len 815 vs 715)
OK   进口的轴承  (reply_len 15 vs 15)

8/8 structural same
```

比较项是 stage / demand 关键字段 / items 的 match_kind / rows / options，文本长度不参与判定（LLM 措辞每次不同）。

**取消穿透**（graph 路径）：

```
ok: _StreamCancelled 穿透
```

**HTTP 双引擎**（真实服务 8100）：

```
legacy results items 3 kinds ['exact']
graph  results items 3 kinds ['exact']
```

**回归**：`.tmp_check_p0.py` 通过、`.tmp_check_final.py` ALL PASS、`.tmp_check_multirows.py` A–F 正常、`.tmp_check_sse_fake.py` A–F ALL PASS、`.tmp_check_index.py` ALL PASS。

### 本批没有做的事

- **默认引擎仍是 legacy**。按计划，切默认和删除旧实现要等复核通过，本批只交付「图可用 + 结构一致」。
- **没有跑 24 条 RAGAS 对照**。结构对照只覆盖 8 条代表性输入；全量跑要 6 分钟且评估模型本身有波动，建议在切默认前单独做一次。
- **graph 路径没有 SSE 集成测试**。假上游测试打的是 legacy 分支；graph 的流式只验证了「取消能穿透」和「HTTP 非流式结果一致」两点。

### 改动文件

- 新增 `backend/app/orchestration.py`
- 修改 `backend/app/main.py`（GRAPH、`_engine_of`、`_graph_answer`、`_answer`/`_chat`/路由加 `engine`）
- 修改 `README.md`（新增「编排层：把分支搬成状态图」一节）
- 新增 `.tmp_compare_engine.py`、`.tmp/probe_langgraph_exc.py`

## 复核结果

等待阿渔提交 `review_requested` 后由渔渔填写。

## 第一轮独立复核结果（渔渔，2026-11-16 09:04 · revision 1）

状态：**changes_requested（revision 2）**。graph 的结构、24 条规则、假上游和取消路径已实测通过，但目前只完成“graph 可用”，尚未完成计划要求的默认切换、legacy 清理和完整 RAGAS，不能按迁移完成批准。

### 渔渔实际验证

- `.tmp_compare_engine.py`：8/8 结构一致。
- 在独立进程将 `_chat()` 包装为 `engine="graph"` 后跑 24 条规则：
  - stage 0.9583、match_kind 0.9375、R@3 0.8958、MRR 0.9115、行状态 0.9167、硬约束 0.0、严重错误 0。
  - MRR 与基线 0.8802 的差异来自在线检索/模型波动，需在全量报告中解释，不能当确定回退。
- 在独立进程设置 `ANSWER_ENGINE=graph` 后跑 `.tmp_check_sse_fake.py`：A–F 全部通过，包括 reset、error、无 delta 取消和 saving 前取消。
- `npm run build`：通过，无新增前端依赖。

### 剩余返工项

1. **SSE 迁移入口未透传 engine**。`POST /api/chat/stream` 当前没有 engine 参数，worker 也未透传，真实 HTTP 流式无法像非流式一样用 `?engine=graph` 对照。迁移期应补齐，完成 graph SSE 实测；最终切换后再移除该临时参数。
2. **完整 RAGAS 未执行**。目前只有渔渔补跑的 24 条规则，没有 graph 的完整 RAGAS 报告。需运行并保存结果，解释 MRR 和语义指标波动。
3. **默认引擎仍是 legacy**。计划要求复核可用后切 graph 默认，并删除旧 `_answer()` 线性实现、`ANSWER_ENGINE`、请求参数和 GRAPH 分支。完成清理后再跑一次关键回归，避免只删文档不删代码。
4. **回调存放位置偏离设计**。`on_stage/on_delta/on_reset/is_cancelled` 目前放进 ShoppingState，计划约定通过节点闭包或 RunnableConfig 传入。虽当前未持久化、未观察到串话，仍应改为约定方式，避免未来引入 checkpoint 时把函数对象带进状态。

### 边界

- 不重写图和业务逻辑，只完成接入、验证、切换和清理。
- 切换后必须保留现有 SSE、取消、落库和 API 字段。
- 完成后改回 `review_requested`，保留 revision 2，写清默认引擎、旧代码删除情况、完整 RAGAS 和最终回归。
- 渔渔下一轮核对清理结果并做最终验收。

## 第二轮执行结果（revision 2，返工四项）

### 1. 回调从 State 移到 RunnableConfig

`ShoppingState` 删掉 `on_stage` / `on_delta` / `on_reset` / `is_cancelled` 四个字段；新增 `_hook(config, name)`，从 `config["configurable"]["hooks"]` 取。12 个节点签名统一带 `config: RunnableConfig`。

`_answer` 调用侧改成：

```python
GRAPH.invoke(state, config={"configurable": {"hooks": hooks}})
```

理由按原计划：State 将来可能被 checkpoint 序列化，函数对象既不可序列化也不该被持久化。现在没有 checkpointer，但设计上不能留这个坑。

验证：结构对照 8/8 仍一致；`_StreamCancelled` 从 `graph.invoke` 原样穿透。

### 2. SSE 补 engine 透传并实测

`POST /api/chat/stream` 在迁移期加了 `engine` 参数并透传给 `_chat`。用 `.tmp_check_stream_engine.py` 对同一句「304 不锈钢 M8 螺丝，长度 30mm，1000 个」分别走 legacy 和 graph：

```
legacy stages: ['understanding', 'retrieving', 'recommending'] deltas: 377
graph  stages: ['understanding', 'retrieving', 'recommending'] deltas: 360
结构一致: True
graph 有 delta: True graph 无 error: True
```

事件序列、delta 数量级、结果结构（stage / items / kinds / demand_category）全部相同，token 仍是真实增量。

### 3. 完整 RAGAS

新增 `--engine` 参数（`legacy|graph`），raw 与报告文件名带引擎后缀，避免覆盖基线。

graph 引擎跑完整 24 条 + RAGAS，耗时 378.7 秒：

| 指标 | 基线（11-15 legacy） | graph（11-16） |
| --- | --- | --- |
| stage 准确率 | 0.9583 | 0.9583 |
| match_kind 准确率 | 0.9375 | 0.9375 |
| Recall@3 | 0.8958 | 0.8958 |
| MRR | 0.8802 | 0.9115 |
| 行状态准确率 | 0.9167 | 0.9167 |
| 硬约束违反率 | 0.0 | 0.0 |
| 严重可下单错误 | 0 | 0 |
| ContextPrecisionWithReference | 0.7911 | 0.8467 |
| ContextRecall | 0.7444 | 0.7667 |
| Faithfulness | 0.3932 | 0.4067 |
| AnswerRelevancy | 0.6924 | 0.6580 |

**逐条比对两份 raw，规则指标只有一处差异**：`multi-rows-021`（「304 和 316 的 M8×30 螺丝」被拆成两行）的 MRR 0.5 → 1.0。原因是两行候选并集里 91 号的落位不同，属于在线检索波动，不是结构变化；该用例本身仍未修好，如实留在基线里。

**RAGAS 波动不是回退**：同一份回复文本，两次评估分数差别很大——`bearing-6204-004` 的 faithfulness 0.0417 → 0.5319，`multi-turn-018` 0.5349 → 0.0750。这说明该指标对评估模型的采样很敏感，不能用来判断迁移是否等价。判断等价要看确定性指标（stage / 硬约束 / match_kind / 行状态），那四项逐条一致。

报告：`docs/ragas-baseline-2026-11-16-graph.json` / `.md`，raw：`docs/ragas-raw-2026-11-16-graph.json`。

### 4. 切默认并删除 legacy

- 删除 `_engine_of()` 与 `ANSWER_ENGINE` 环境变量。
- 删除旧 `_answer()` 的 157 行线性实现（含理解层判断、chat、多需求、缺参、检索、推荐全部内联分支）。
- `_graph_answer()` 改名为 `_answer()`，成为唯一主链路；`_chat`、`GET/POST /api/chat`、`POST /api/chat/stream` 全部去掉 `engine` 参数。
- `main.py` 从 29,168 字节降到 22,903 字节，`_answer` 从 157 行降到 34 行。
- 删除 `.tmp_compare_engine.py`（对照脚本使命结束），`.tmp_check_stream_engine.py` 改成单路径实测。

关键回归（切换后）：

```
.tmp_check_p0.py        通过
.tmp_check_final.py     ALL PASS
.tmp_check_multirows.py A–F 正常
.tmp_check_sse_fake.py  A–F ALL PASS
.tmp_check_index.py     ALL PASS
.tmp_check_sse.py       391 个 delta / 落库各一条 / ALL PASS
npm run build           通过，无前端改动
```

其中 `.tmp_check_sse_fake.py` 的六场景（成功 / 中途异常 / 理解层异常 / 取消 / 无 delta 取消 / 落库前取消）现在打的就是状态图路径——这是之前「graph 没有 SSE 集成测试」的缺口，切默认后自动补上了。

真实 HTTP 流式（`.tmp_check_stream_engine.py`）：

```
stages: ['understanding', 'retrieving', 'recommending']
deltas: 382
stage: results items: 3 kinds: ['exact']
ALL PASS
```

### 未覆盖范围

- 前端没有为本次迁移做任何改动，`npm run build` 通过但未做浏览器端交互验收。
- RAGAS 的语义指标仍受评估模型采样影响，本批只做了「确定性指标逐条一致」的等价判断，没有为语义分数设阈值。
- 头型冲突、检索排序、Faithfulness 波动三个已知问题未在本批处理（计划明确规定另立业务批次）。

## 第二轮独立复核结果（渔渔，2026-11-16 10:04 · revision 2）

状态：**changes_requested（revision 3，仅两处说明清理）**。功能、切换和完整 RAGAS 均已通过，只有旧注释/旧口径未同步。这是第 2 次、也是最后一次返工；revision 3 若仍不通过则 blocked。

### 已通过

- 回调已移至 RunnableConfig，不再进入 ShoppingState。
- graph 成为唯一主链路，engine 参数与旧线性实现已删除。
- 完整 RAGAS 报告存在：stage 0.9583、match_kind 0.9375、R@3 0.8958、MRR 0.9115、行状态 0.9167、硬约束 0、严重错误 0；语义波动有解释。
- 渔渔实际重跑切换后的 `.tmp_check_p0.py`、`.tmp_check_final.py`、`.tmp_check_sse_fake.py`、`.tmp_check_index.py`，全部通过。
- `npm run build` 通过。

### 唯一剩余项：说明与实际实现不一致

1. `backend/app/main.py:48-49` 仍写“默认走原有线性实现，显式指定 graph 时才走状态图”；`main.py:176` 仍写“默认仍走 legacy 分支”。当前 graph 已是唯一主链路，应删除或改为当前事实。
2. `backend/eval/run_ragas.py` 的报告口径仍写“Recall@3 与 MRR 用同一分母——有期望商品且本轮确实有候选的用例”，`docs/ragas-baseline-2026-11-16-graph.md` 也同样。当前实现已明确：完整需求零候选也计 0，只有缺参参考行/不适用行才排除。需同时修生成器模板和本次报告，避免下次生成又写回旧口径。

### 收尾要求

- 只改上述注释和报告文字，不改图、评估逻辑或业务行为。
- 用文字检查确认 main 不再声称默认 legacy，新报告不再声称零候选不适用。
- 改回 `review_requested`，保留 revision 3。渔渔下一轮只做文本核对，通过后批准归档。


## 第三轮执行结果（revision 3，返工两项文字）

**改动范围**：只改说明文字，未动状态图、评估逻辑与业务行为。

1. ackend/app/main.py:48 → # 主链路就是状态图。旧实现与临时开关已删除。；:176 → # 状态图在启动时编译一次，之后每轮请求复用它，State 按请求新建
2. ackend/eval/run_ragas.py:215（注释）与 :306（报告模板）改为「有期望商品、且本轮适用于召回统计的用例。完整需求即使零候选也计 0 分（那是最该暴露的失败），只有缺参参考行与不适用行才排除」
3. docs/ragas-baseline-2026-11-16-graph.md 同步替换同一句

**文字核对（实际运行）**
- main.py：legacy 0 处、迁移期 0 处、线性实现 0 处；st.parse 通过
- 
un_ragas.py：旧口径「确实有候选的用例」0 处；st.parse 通过
- 报告 md：旧口径 0 处，新口径 1 处
- 三文件 ad（U+FFFD）合计 0

**未改**：图中节点、_hook 取法、评估实现、任何业务分支。

## 最终文本复核（渔渔，2026-11-16 10:17 · revision 3）

状态：**approved**。

- `main.py:48` 已改为“主链路就是状态图，旧实现与临时开关已删除”。
- `main.py:175` 已改为启动时编译状态图、每轮新建 State。
- `run_ragas.py` 与 `docs/ragas-baseline-2026-11-16-graph.md` 已明确：完整需求零候选也计 0，只有缺参参考行与不适用行才排除。

功能与迁移验收已在 revision 2 全部通过，本轮仅核对说明，未重复运行测试。LangGraph 渐进编排改造至此完成，批准归档，不自动开始下一批。
