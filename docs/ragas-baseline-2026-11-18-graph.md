# RAGAS 评估基线（2026-11-18）

## 一、运行信息

- 用例数：24
- 业务模型：deepseek-chat
- 评估模型：deepseek-chat
- embedding：bge-m3（本地 D:\AI\models\bge-m3）
- 并发：2
- 模式：在线采集 + 规则 + RAGAS
- 耗时：375.2 秒
- 平均单条耗时：4.5 秒

## 二、确定性指标

| 指标 | 数值 | 覆盖用例 |
| --- | --- | --- |
| stage 准确率 | 0.9583 | 24 |
| match_kind 准确率 | 0.9375 | 16 |
| Recall@3 | 0.8958 | 16 |
| MRR | 0.9115 | 16 |
| 行状态准确率 | 0.9583 | 24 |
| 硬约束违反率 | 0.0 | 15 |
| 严重可下单错误 | 0 | 17 |

口径说明：

- Recall@3 与 MRR 用同一分母——有期望商品、且本轮适用于召回统计的用例。完整需求即使零候选也计 0 分（那是最该暴露的失败），只有缺参参考行与不适用行才排除。
- 多需求的候选来自各行 `items` 的并集；缺参行没有候选，该行不参与召回统计。
- `match_kind` 只表示硬约束（规格/内径/长度）的精确性，软属性不符不改变它。
- 行状态来自 `evaluate_row()`；多需求逐行比对，期望值写成数组。
- 严重错误 = 候选里存在 `alternative` 却把该行判成 `ok`，分母是有候选的用例数。

## 三、RAGAS 指标

适用 15 条（非 results 分支 9 条不计入）。

| 指标（实际类名） | 均值 |
| --- | --- |
| ContextPrecisionWithReference | 0.8467 |
| ContextRecall | 0.7667 |
| Faithfulness | 0.672 |
| AnswerRelevancy | 0.6771 |

失败指标调用 0 次（单指标失败记为 null，不计入均值）。

## 四、逐条明细

| case_id | stage | 期望 | 候选 | R@3 | MRR | 行状态 | 期望状态 | kind | Faith | AnsRel |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fastener-m8x30-001 | results | results | 91,99,95 | 1.0 | 1.0 | ok | ok | exact | 1.0 | 0.6602 |
| fastener-m8x50-002 | results | results | 92 | 1.0 | 1.0 | ok | ok | exact | 0.375 | 0.6349 |
| fastener-m10x40-003 | results | results | 94 | 1.0 | 1.0 | ok | ok | exact | 0.1429 | 0.6313 |
| bearing-6204-004 | results | results | 106,110,136,137,108 | 1.0 | 1.0 | ok | ok | exact | 0.3958 | 0.6561 |
| bearing-bore20-005 | results | results | 106,119,136,137,120 | 0.3333 | 0.3333 | below_moq | below_moq | exact | 0.9722 | 0.688 |
| bearing-bore30-006 | results | results | 108,118,111 | 1.0 | 1.0 | ok | ok | exact | 0.9524 | 0.677 |
| electrical-dz47-007 | results | results | 123,124,132,122,131 | 1.0 | 1.0 | ok | ok | exact | 1.0 | 0.6422 |
| electrical-s350-008 | results | results | 133,128,132,134,122 | 1.0 | 1.0 | ok | ok | exact | 0.8235 | 0.6964 |
| origin-import-009 | results | results | 137,136,119,114,113 | 1.0 | 1.0 | ok | ok | exact | 0.9706 | 0.6978 |
| origin-germany-010 | results | results | 136,137,106,108,110 | 1.0 | 1.0 | ok | ok | exact | 0.7391 | 0.7141 |
| material-304-011 | results | results | 91,99,95 | 1.0 | 1.0 | attr_conflict | attr_conflict | exact | 0.58 | 0.8411 |
| alternative-m12x80-012 | results | results | 96,94,92,103,93 | 1.0 | 1.0 | alternative_only | alternative_only | alternative | 0.4839 | 0.8677 |
| attr-conflict-013 | results | results | 114,117,113,107 | 0.0 | 0.25 | attr_conflict | attr_conflict | exact | 0.5577 | 0.7595 |
| missing-spec-014 | clarify | clarify | - | - | - | - | not_applicable | - | - | - |
| missing-length-015 | clarify | clarify | - | - | - | - | not_applicable | - | - | - |
| missing-bore-016 | clarify | clarify | - | - | - | - | not_applicable | - | - | - |
| out-of-scope-017 | out_of_scope | out_of_scope | - | - | - | - | not_applicable | - | - | - |
| multi-turn-018 | results | results | 91,95,99 | 1.0 | 1.0 | ok | ok | exact | 0.3056 | 0.6261 |
| multi-turn-019 | results | results | 91,99,95 | 1.0 | 1.0 | ok | ok | exact | 0.7818 | 0.3648 |
| multi-rows-020 | multi | multi | 95,102,99,103,94 | - | - | ['missing_param', 'missing_param'] | ['missing_param', 'missing_param'] | - | - | - |
| multi-rows-021 | multi | results | 91,99,95,91,99,95 | 1.0 | 1.0 | ['ok', 'ok'] | ok | - | - | - |
| chat-weather-022 | chat | chat | - | - | - | - | not_applicable | - | - | - |
| chat-knowledge-023 | chat | chat | - | - | - | - | not_applicable | - | - | - |
| chat-greeting-024 | chat | chat | - | - | - | - | not_applicable | - | - | - |

## 五、薄弱案例

### multi-rows-021（实际 multi / 期望 results）

- 输入：304 和 316 的 M8×30 螺丝，要 1000 个
- 候选：[91, 99, 95, 91, 99, 95]，Recall@3 1.0，MRR 1.0
- 行状态：实际 ['ok', 'ok'] / 期望 ok

```text
共 2 条需求，匹配到 2 条。明细在右侧。
```

### alternative-m12x80-012（实际 results / 期望 results）

- 输入：M12×80 的内六角螺丝，要 100 个
- 候选：[96, 94, 92, 103, 93]，Recall@3 1.0，MRR 1.0
- 行状态：实际 alternative_only / 期望 alternative_only
- 硬约束违反：碳钢热镀锌外六角螺栓 M12×60: 长度不符（要求 80mm，实际 60mm）；304 不锈钢内六角圆柱头螺丝 M10×40: spec 不含 M12（实际 M10×40mm）；304 不锈钢内六角圆柱头螺丝 M10×40: 长度不符（要求 80mm，实际 40mm）
- RAGAS：Faith 0.4839 / CtxRecall 0.75 / AnsRel 0.8677

```text
> 没有完全匹配的规格（长度要求 80mm，候选 60mm），以下是可替代的候选，下单前请确认是否可用。  ## 推荐  候选商品中没有 M12×80 的内六角螺丝，无法直接下单。按接近程度排序：  1. **候选2：304 不锈钢内六角圆柱头螺丝 M10×40** — 唯一同为“内六角圆柱头螺丝”的候选，但规格 M10×40 与需求 M12×80 不符（直径小 2mm、长度短 40mm），不能替代 M12×80 使用。 2. **候选3：304 不锈钢内六角圆柱头螺丝 M8×50** — 同为内六角，规格 M8×50 差距更大，不匹配。 3. **候选5：304 不锈钢内六角圆柱头螺丝 M6×20** — 同为内六角，规格 M6×20 差距最大，不匹配。  ## 逐项核对  - **候选1**：不是内六角，而是外六角螺栓；规格 M12×60，长度比 80mm 短 20mm。头部形式和长度
```

### fastener-m10x40-003（实际 results / 期望 results）

- 输入：304 不锈钢 M10×40 内六角螺丝，500 个
- 候选：[94]，Recall@3 1.0，MRR 1.0
- 行状态：实际 ok / 期望 ok
- RAGAS：Faith 0.1429 / CtxRecall 1.0 / AnsRel 0.6313

```text
**推荐** 1. 304 不锈钢内六角圆柱头螺丝 M10×40（东明）：唯一候选，材质、头型、规格均匹配，MOQ 500 与需求数量 500 正好一致。  **核对事实** - 匹配：材质 304 不锈钢、内六角头、M10×40mm，均符合要求。 - 价格：¥0.78/个，500 个合计 ¥390。 - MOQ 与数量：MOQ 500，需求 500，刚好达到起订量，无超量。 - 交期：2 天。 - 用户明确要求的属性：无产地、品牌、工艺、行业要求，候选无冲突项。  ---  【通用提示】以上价格、MOQ、交期为候选信息，下单前请与供应商核对；税率、账期、运费以实际结算为准；如需备损，建议按用量加订 3%~5% 并确认是否可拆零。
```

### multi-turn-018（实际 results / 期望 results）

- 输入：30mm 的，要 1000 个
- 候选：[91, 95, 99]，Recall@3 1.0，MRR 1.0
- 行状态：实际 ok / 期望 ok
- RAGAS：Faith 0.3056 / CtxRecall 1.0 / AnsRel 0.6261

```text
## 推荐（按匹配度排序）  1. **304 不锈钢内六角圆柱头螺丝 M8×30（东明）** — 规格 M8×30mm 完全匹配，数量 1000 正好等于 MOQ 1000，可下单；304 不锈钢防锈，交期 2 天最短。用户未指定材质/头型，此款为通用圆柱头内六角，适配面最广。 2. **碳钢镀锌外六角螺栓 M8×30（永固）** — 规格 M8×30mm 匹配，数量 1000 等于 MOQ 1000；单价 ¥0.22 最低，8.8 级通用型，交期 3 天。头型为外六角，与候选 1 不同，用户未限定头型，可用。 3. **304 不锈钢内六角沉头螺丝 M8×30（东明）** — 规格 M8×30mm 匹配，数量 1000 等于 MOQ 1000；单价 ¥0.40 最高，交期 2 天。沉头 90°，仅适合需要平整表面的连接场景，通用性弱于前两款。  ## 事实核对  - 三款规格均为 M8
```

### origin-import-009（实际 results / 期望 results）

- 输入：进口的 6204 轴承，要 50 个
- 候选：[137, 136, 119, 114, 113]，Recall@3 1.0，MRR 1.0
- 行状态：实际 ok / 期望 ok
- RAGAS：Faith 0.9706 / CtxRecall 0.0 / AnsRel 0.6978

```text
## 推荐（按匹配度排序）  **1. 深沟球轴承 6204-2RS（进口·日本，NSK）— 最匹配** - 型号 6204-2RS，内径 20mm、外径 47mm，符合 6204 规格；产地标注进口·日本，满足“进口”要求。 - 价格 ¥26.0/个，数量 50 个合计约 ¥1300；MOQ 10，50 个满足起订量。 - 交期 10 天。  **2. 深沟球轴承 6204-2RS（进口·德国，SKF）— 匹配，价格与交期更高** - 型号 6204-2RS，规格同为内径 20mm、外径 47mm；产地进口·德国，满足“进口”要求。 - 价格 ¥38.0/个，比候选 1 高 ¥12.0/个，50 个合计约 ¥1900；MOQ 10，50 个满足。 - 交期 15 天，比候选 1 长 5 天。  ## 不满足需求的候选（不可按“进口 6204”下单）  **3. 不锈钢轴承 S6204-2
```

### attr-conflict-013（实际 results / 期望 results）

- 输入：进口的 6204 轴承，内径 25mm 的，要 50 个
- 候选：[114, 117, 113, 107]，Recall@3 0.0，MRR 0.25
- 行状态：实际 attr_conflict / 期望 attr_conflict
- RAGAS：Faith 0.5577 / CtxRecall 0.0 / AnsRel 0.7595

```text
## 推荐（按匹配度排序）  1. **深沟球轴承 6205-2RS（内径 25mm）** — 最接近需求：深沟球轴承与 6204 同系列结构，内径 25mm 满足，双面密封适合常规工况。但型号是 6205-2RS 而非 6204，外径 52mm（6204 为 47mm），尺寸不同，不能直接替代 6204 安装位。 2. **调心球轴承 1205（内径 25mm）** — 内径满足，但结构为调心球轴承，非 6204 深沟球，外径 52mm，载荷与安装尺寸均不同。 3. **带座轴承 UCP205（内径 25mm）** — 内径满足，但为带座外球面轴承单元，非 6204，安装方式完全不同。 4. **推力球轴承 51105（内径 25mm）** — 内径满足，但只能承受轴向载荷，非 6204 深沟球，用途不同。  ## 事实核对  - **进口属性**：四个候选产地均为**国产**，无进口商
```

### multi-turn-019（实际 results / 期望 results）

- 输入：要 2000 个
- 候选：[91, 99, 95]，Recall@3 1.0，MRR 1.0
- 行状态：实际 ok / 期望 ok
- RAGAS：Faith 0.7818 / CtxRecall 0.25 / AnsRel 0.3648

```text
**推荐（按匹配度排序）**  1. **304 不锈钢内六角圆柱头螺丝 M8×30（东明）** — 完全匹配：304 不锈钢、内六角、M8×30mm 全部满足；圆柱头内六角为常规内六角螺丝形态。¥0.35/个，MOQ 1000，数量 2000 满足起订量（为 MOQ 的 2 倍），交期 2 天。 2. **304 不锈钢内六角沉头螺丝 M8×30（东明）** — 材质、规格、内六角均满足，但头部为 90° 沉头，与常规圆柱头内六角不同；仅适合需要沉头平整表面的连接。¥0.4/个，比候选 1 贵 ¥0.05/个；MOQ 1000，数量 2000 满足；交期 2 天。  **不满足要求的候选**  3. **碳钢镀锌外六角螺栓 M8×30（永固）** — 这不是你要的 304 不锈钢内六角螺丝，而是碳钢镀锌外六角螺栓：材质为碳钢（非 304 不锈钢）、头部为外六角（非内六角），两项均不满足，
```

## 六、怎么读这些分数

- **Faithfulness 0.672，比 2026-11-16 基线的 0.4067 高 0.265**：2026-11-18 起通用建议（备损、账期、物流、下单前核对）移出正文，改由系统统一追加 `【通用提示】` 尾注，评测前把尾注剥离。剩余低分主要来自引用用户需求的句子（如「MOQ 100 > 需求 50」「你未提产地要求」），RAGAS 的 faithfulness 只对照候选上下文、不看 user_input。
- **ContextRecall 偏低，部分来自 reference 写法**：结构化短文本（分号拼接的属性行）会让 LLM 判定偏保守。看这条要看候选顺序，不是看分数。
- **确定性指标优先于语义分**：stage、硬约束、match_kind、行状态不受评估模型影响；只有 replay 模式下这些指标才完全离线可复现。

## 七、未覆盖范围

- 未评估多轮长对话（超过 4 轮的上下文继承）。
- 未评估上传（Excel / 图片）路径的质量。
- 未做并发压力与限流测试。
- 未对 RAGAS 分数设合格阈值，首轮只建立分布。
- 在线采集阶段仍会调业务模型（理解/改写/推荐），同一句话两次运行的回复措辞可能不同；只有 `--replay` 的规则指标是离线复现。
- 已知问题用例（`multi-rows-021` 材质并列被拆成两行）按原样保留，没有为了让分数好看而删除。

## 八、复现

```powershell
cd backend
# 全量：在线采集 + 规则 + RAGAS，同时写 raw JSON
& 'D:\AI\ComfyUI\venv\Scripts\python.exe' -m eval.run_ragas

# 只采集原始结果，不跑 RAGAS
& 'D:\AI\ComfyUI\venv\Scripts\python.exe' -m eval.run_ragas --collect-only

# 离线重算规则指标（零模型调用）
& 'D:\AI\ComfyUI\venv\Scripts\python.exe' -m eval.run_ragas --replay docs\ragas-raw-2026-11-15.json
```
