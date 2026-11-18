---
plan_id: 20261114-p0-correctness-01
batch: P0 正确性修复
revision: 2
status: approved
owner: 阿渔
reviewer: 阿渔渔
user_approved: true
created_at: 2026-11-14 23:07
updated_at: 2026-11-14 23:23
---

# P0 正确性修复：3.4 → 3.3 → 3.1

## 任务范围

1. **3.4 硬约束来源分离**：语义检索 query 与代码校验后的结构化参数分开，LLM 改写不得改变规格过滤。
2. **3.3 精确结果与替代品区分**：有精确命中时只保留精确结果；没有精确命中时明确标记替代品和差异，不静默当成普通推荐。
3. **3.1 统一行评估**：多需求、Excel 和图片上传使用同一套业务判断，缺关键参数不能标为“可下单”。
4. 前端跟随展示新状态，历史会话仍能读取。

## 不在本批次范围

- 3.2 库存与“可下单”完整口径。
- IndexManager、SSE、RAGAS、LangGraph。
- P1 唯一需求状态与 LLM 多需求拆分稳定性。
- 与本批无关的召回质量优化。

## 实施结果（阿渔填写）

### 3.4 硬约束来源分离

- `backend/app/rag/retriever.py`：`hybrid_search(query, state, top_k=10, constraints=None)`，显式约束优先；未传时保留文本解析的旧调用兼容行为。
- `backend/app/main.py`：`/api/search`、`_multi_reply` 两处、`_answer`、`_match_rows` 均传 `constraints=demand["params"]`。

### 3.3 精确结果与替代品区分

- 新增 `_mismatches(row, params)`，生成具体参数差异。
- 精确结果标 `match_kind="exact"`；无精确结果时保留候选并标 `match_kind="alternative"`，每条带 `mismatches`。
- `_answer` 在替代结果前增加明确提示，下单前需要确认是否可用。

### 3.1 统一行评估

- 新增 `evaluate_row(demand, items) -> {status, text}`。
- 判断顺序：`out_of_scope` → `missing_category` → `missing_param` → `no_match` → `alternative_only` → `attr_conflict` → `below_moq` → `ok`。
- `_multi_reply`、`_match_rows` 行数据增加 `status`。
- 上传结果落库补 `items[:1]` 与 `status`，避免刷新后商品属性丢失。
- 前端增加状态映射、替代品标签，表格根据 `status` 决定标签颜色。

### 改动文件

- `backend/app/rag/retriever.py`
- `backend/app/main.py`
- `frontend/src/App.tsx`
- `README.md`
- `docs/test-checklist.md`
- `docs/ui-excel.png`、`docs/ui-multi.png`、`docs/ui-chat-antd.png`

## 验收标准

> 勾选状态以“复核结果”为准。执行者自测通过不等于独立复核通过。

### A. 硬约束来源

- [ ] 主链路所有 `hybrid_search` 调用都显式传入当前行或当前需求的 `demand["params"]`。
- [ ] 检索使用显式约束时，不再从 LLM 改写后的语义 query 提取另一套硬过滤参数。
- [ ] 语义 query 中出现其它数字，不改变已传入的规格约束。

### B. 精确结果与替代品

- [ ] 有精确命中时只返回精确结果，并标为 `exact`。
- [ ] 无精确命中时，候选全部标为 `alternative`，且每条有具体 `mismatches`。
- [ ] 替代品回复明确提示“没有完全匹配”和“下单前请确认”，不能标为可下单。
- [ ] 只给 M8、未给长度时，长度不参与硬过滤，不误删不同长度的合理候选。
- [ ] 未指定某参数时，不因商品字段差异产生该参数的 mismatch。

### C. 统一行评估

- [ ] 多需求与上传链路都使用 `evaluate_row` 的结论，不各自维护冲突判断。
- [ ] 缺品类、缺关键参数、库外、无匹配、只有替代品、属性冲突、低于 MOQ 和可下单状态顺序明确。
- [ ] 缺关键参数即使有候选，也只能作为参考，状态不是 `ok`。
- [ ] 只有替代品时状态不是 `ok`，不能显示绿色可下单标签。
- [ ] 软属性冲突优先于 MOQ 是明确采用的业务顺序；回复能展示具体冲突原因。

### D. 前端与历史数据

- [ ] 前端使用结构化 `status` 和 `match_kind` 展示状态，不只依赖文案前缀。
- [ ] 老会话行数据没有 `items` 或 `status` 时不会报错，并能显示已有 `note`。
- [ ] 新上传结果落库后仍保留首个商品及状态，刷新前后显示所需字段一致。
- [ ] 前端生产构建通过。

### E. 回归与边界

- [ ] P0 精确、替代、缺参、库外、闲聊场景实际运行符合预期。
- [ ] 现有多轮最终回归通过。
- [ ] 多需求和 Excel 现有回归没有新增失败。
- [ ] 精排既有验证保持通过，德国进口 6204 的首位没有因本批改动回退。
- [ ] 已知 LLM 拆分和召回问题单独记录，不混入本批通过结论。

## 执行者验证记录（阿渔已报告）

| 验证 | 阿渔报告的结果 |
| --- | --- |
| `.tmp_check_p0.py` | 精确、替代、缺参、库外、闲聊符合预期 |
| `.tmp_check_final.py` | `ALL PASS` |
| `.tmp_check_multirows.py` | A–F 六组结构正常，缺参行文案正确 |
| `.tmp_check_excel.py` | 三表通过，库外行正确 |
| `.tmp_check_rerank.py` | 五组正常，德国进口 6204 为 SKF 德国第一 |
| 前端构建 | 通过，生成 `dist/assets/index-CnL2vhZJ.js` |

以上是执行者报告，复核方需重新核对代码并运行必要验证。

## 执行者记录的已知问题

- 「304 和 316 的 M8 螺丝 1000 个」可能被理解层拆成两行，属 P1 唯一需求状态与多需求拆分问题。
- 「螺丝 M10 数量 1000」的召回首位可能是螺母，属召回质量问题。

本批复核需判断是否由本批改动引入；不属于本批范围的问题不得借复核之名顺带修改。

## 复核结果（阿渔渔，2026-11-14 23:14）

状态：**changes_requested**。核心行为回归通过，但 C 组“所有入口统一使用 `evaluate_row`”尚有一项未满足，因此本批暂不批准进入 IndexManager。

### 验收结论

| 分组 | 结论 | 依据 |
| --- | --- | --- |
| A. 硬约束来源 | 通过 | 主链路五个调用点均传 `constraints=demand["params"]`；`retriever.py:159` 显式约束优先于文本解析 |
| B. 精确结果与替代品 | 通过 | 直接调用检索验证改写文本与约束分离、M8 单独约束、替代差异；接口验证 M12×80 与内径 17mm |
| C. 统一行评估 | **一项需修正** | `_match_rows` 已统一；`_multi_reply:262-284` 仍手写库外、缺品类、缺参三个 verdict |
| D. 前端与历史数据 | 代码与构建通过 | 老数据使用 `items?.[0]` 和可选 `status`；新落库保存 `items[:1]`、`status`；生产构建通过 |
| E. 回归与边界 | 通过，已知问题另记 | 既有脚本与定向测试通过；LLM 拆分和螺母召回问题仍存在，非本批新引入 |

### 需要阿渔修正的唯一事项

`backend/app/main.py:256-284` 的 `_multi_reply()` 没有真正全部复用 `evaluate_row()`：

- `out_of_scope` 分支手写 `status` 和 `text`。
- `missing_category` 分支手写 `status` 和 `text`。
- `missing_param` 分支手写 `status` 和 `text`。

当前行为测试虽然正确，但这仍保留两套判断来源，后续调整 `evaluate_row` 顺序或状态时可能再次分叉，不符合本批“统一行评估”的目标。

**返工要求**：

1. 三类分支的状态与基础判断统一由 `evaluate_row()` 给出。
2. 多需求缺参时仍可保留“以下为参考”的详细文案，但不能绕开统一状态判断；可通过统一函数的上下文参数或基于统一 `status` 的展示层补充文案实现。
3. 不改 `evaluate_row()` 已确认的业务优先级，不顺带处理 P1 或召回问题。
4. 修正后运行 `.tmp_check_p0.py` 和 `.tmp_check_multirows.py`，确认缺参、库外、缺品类及既有六组行为不变。
5. 更新执行结果，将计划改为 `review_requested`，`revision` 升为 2；阿渔渔只需做针对性复核。

### 阿渔渔实际运行的验证

- `.tmp_check_p0.py`：精确、替代、Excel 缺参、多需求缺参、库外、闲聊、追问均符合预期。
- `.tmp_check_final.py`：输出 `ALL PASS`。
- `.tmp_check_multirows.py`：A–F 均完成；缺参行状态正确。C 组仍复现 LLM 将两种材质拆成两行，按既有 P1 问题记录。
- `.tmp_check_excel.py`：standard、no_header、odd_names 均完成；库外、MOQ 与可下单判断符合预期。
- `.tmp_check_rerank.py`：五组均返回结果；德国进口 6204 首位仍为 SKF 德国。
- 前端 `npm run build`：通过；生成 `dist/assets/index-CnL2vhZJ.js`，仅有既有的大 chunk 警告。
- 直接检索定向测试：
  - query 为「螺丝 M10×40 长度 40mm」、显式约束为 `M8 + 30mm` 时，返回全部为 `M8×30mm / exact`。
  - 显式约束仅为 M8 时，保留 `M8×30mm`、`M8×50mm` 和仅标 M8 的候选，全部为 `exact`，无 `mismatches`。
  - 输出 `TARGETED PASS`。
- 第一次 P0 输出出现控制台 GBK 乱码，不是文件乱码；使用 `python -X utf8` 重跑后中文正常。一次 PowerShell 环境变量赋值因外层 shell 展开未生效，但后续 `-X utf8` 验证已成功，不影响测试结论。

### 未覆盖范围

- 未用真实图片调用视觉识别；图片与 Excel 在识别后共同进入 `_match_rows`，本次只核对了这条共用链路并实测 Excel。
- 未做浏览器中老会话的人工点击验收；老数据兼容性结论来自前端代码检查和生产构建。
- 未复核本批范围外的 LLM 拆分与召回质量，也未修改这些实现。

## 返工记录（阿渔，2026-11-14 23:30 · revision 2）

### 针对复核意见的唯一修正

`backend/app/main.py` 的 `_multi_reply()` 原先对 `out_of_scope`、`missing_category`、`missing_param` 三个分支各自手写 `{status, text}`，与 `evaluate_row()` 形成两套判断来源。已改为：

1. 三个分支删除，行内只做一件事——**有品类且非库外就检索**，缺参也检索（保持原来给参考候选的行为）。
2. 结论统一由 `evaluate_row(demand, items)` 给出，`status` 直接取它的返回值。
3. 新增 `_multi_row_text(demand, verdict, items)` 只做展示层换词：
   - `out_of_scope` → 「不在收录范围（只做紧固件 / 轴承 / 电气元件）」
   - `missing_category` → 「没看出是哪类，补充品类后我再找」
   - `missing_param` 且有候选 → 「参数不全（缺 X），以下为参考，暂不可下单」
   - 其余沿用 `verdict["text"]`
4. 未改动 `evaluate_row()` 的业务优先级，未处理 P1 与召回问题。

### 返工后验证（实际运行，`-X utf8`）

| 验证 | 结果 |
| --- | --- |
| `.tmp_check_p0.py` | 3.4 精确命中 `exact`；3.3 `M12×80` → `alternative` + `长度要求 80mm，候选 60mm`；`内径 17mm` → `alternative` + `内径要求 17mm，候选 12mm`；Excel 缺参行 `missing_param`；多需求缺参行 `missing_param` + 「参数不全（缺长度）…」；扳手 `out_of_scope`、天气 `chat`、追问 `clarify` |
| `.tmp_check_multirows.py` | A–F 六组全部完成，缺参行文案与状态一致；C 组仍复现 LLM 拆两行（P1，已另记） |
| 后端健康 | `{"ok":true,"products":48,"llm":true}` |

### 复核建议

只需针对 `_multi_reply` 这一处：确认三个分支已消失、`status` 全部来自 `evaluate_row`、缺参文案仍保留。其余 A/B/D/E 结论无需重跑。


## 第二轮复核结果（阿渔渔，2026-11-14 23:23 · revision 2）

状态：**approved**。唯一返工项已满足，本批全部验收结论通过，可以进入 IndexManager 计划阶段。

### 代码复核

- `backend/app/main.py:273-294`：`_multi_reply()` 只在有品类且非库外时检索，随后统一调用 `evaluate_row(demand, items)`；返回行的 `status` 直接取统一判断结果。
- `backend/app/main.py:256-270`：`_multi_row_text()` 仅根据统一 `status` 补充展示文案，不另做业务判断。
- 库外、缺品类、缺参三套手写 verdict 已移除。
- `evaluate_row()` 的业务优先级未改，未混入 P1 或召回优化。

### 阿渔渔实际重跑

- `.tmp_check_p0.py`：
  - M8×30 为 `exact`。
  - M12×80、内径 17mm 为 `alternative`，差异说明正确。
  - Excel 与多需求缺参均为 `missing_param`，多需求保留“以下为参考，暂不可下单”。
  - 扳手为 `out_of_scope`，天气为 `chat`，「我要买螺丝」为 `clarify`。
- `.tmp_check_multirows.py`：A–F 六组完成，缺参状态与详细文案保持；C 组仍有既有 LLM 拆分问题，按 P1 另记，不归入本批回退。

### 最终验收结论

A、B、C、D、E 五组全部通过。此前未覆盖的真实图片识别和浏览器老会话人工点击仍不属于本次新增验证，结论范围与第一轮一致。

### 流程结论

本计划完成 `ready/实施 → review_requested → changes_requested → 返工 revision 2 → review_requested → approved` 的完整闭环。执行者与复核者分离，返工范围和验证证据均已记录。
