# RAGAS 评估基线（2026-11-15）

## 一、运行信息

- 用例数：24
- 业务模型：deepseek-chat
- 评估模型：deepseek-chat
- embedding：bge-m3（本地 D:\AI\models\bge-m3）
- 并发：2
- 模式：replay（离线，零模型调用）
- 耗时：0.0 秒
- 平均单条耗时：4.75 秒

## 二、确定性指标

| 指标 | 数值 | 覆盖用例 |
| --- | --- | --- |
| stage 准确率 | 0.9583 | 24 |
| match_kind 准确率 | 0.9375 | 16 |
| Recall@3 | 0.8958 | 16 |
| MRR | 0.8802 | 16 |
| 行状态准确率 | 0.9167 | 24 |
| 硬约束违反率 | 0.0 | 15 |
| 严重可下单错误 | 0 | 17 |

口径说明：

- Recall@3 与 MRR 用同一分母——有期望商品且本轮确实有候选的用例；命中 0 分也计入，不剔除失败行。
- 多需求的候选来自各行 `items` 的并集；缺参行没有候选，该行不参与召回统计。
- `match_kind` 只表示硬约束（规格/内径/长度）的精确性，软属性不符不改变它。
- 行状态来自 `evaluate_row()`；多需求逐行比对，期望值写成数组。
- 严重错误 = 候选里存在 `alternative` 却把该行判成 `ok`，分母是有候选的用例数。

## 三、RAGAS 指标

未运行（--rules-only / --replay）

## 四、逐条明细

| case_id | stage | 期望 | 候选 | R@3 | MRR | 行状态 | 期望状态 | kind | Faith | AnsRel |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fastener-m8x30-001 | results | results | 91,99,95 | 1.0 | 1.0 | ok | ok | exact | - | - |
| fastener-m8x50-002 | results | results | 92 | 1.0 | 1.0 | ok | ok | exact | - | - |
| fastener-m10x40-003 | results | results | 94 | 1.0 | 1.0 | ok | ok | exact | - | - |
| bearing-6204-004 | results | results | 106,110,136,137,108 | 1.0 | 1.0 | ok | ok | exact | - | - |
| bearing-bore20-005 | results | results | 106,119,136,137,120 | 0.3333 | 0.3333 | below_moq | below_moq | exact | - | - |
| bearing-bore30-006 | results | results | 108,118,111 | 1.0 | 1.0 | ok | ok | exact | - | - |
| electrical-dz47-007 | results | results | 123,124,132,122,131 | 1.0 | 1.0 | ok | ok | exact | - | - |
| electrical-s350-008 | results | results | 133,128,132,134,122 | 1.0 | 1.0 | ok | ok | exact | - | - |
| origin-import-009 | results | results | 137,136,119,114,113 | 1.0 | 1.0 | ok | ok | exact | - | - |
| origin-germany-010 | results | results | 136,137,106,108,110 | 1.0 | 1.0 | ok | ok | exact | - | - |
| material-304-011 | results | results | 91,99,95 | 1.0 | 1.0 | ok | attr_conflict | exact | - | - |
| alternative-m12x80-012 | results | results | 96,94,92,103,93 | 1.0 | 1.0 | alternative_only | alternative_only | alternative | - | - |
| attr-conflict-013 | results | results | 114,117,113,107 | 0.0 | 0.25 | attr_conflict | attr_conflict | exact | - | - |
| missing-spec-014 | clarify | clarify | - | - | - | - | not_applicable | - | - | - |
| missing-length-015 | clarify | clarify | - | - | - | - | not_applicable | - | - | - |
| missing-bore-016 | clarify | clarify | - | - | - | - | not_applicable | - | - | - |
| out-of-scope-017 | out_of_scope | out_of_scope | - | - | - | - | not_applicable | - | - | - |
| multi-turn-018 | results | results | 91,95,99 | 1.0 | 1.0 | ok | ok | exact | - | - |
| multi-turn-019 | results | results | 91,99,95 | 1.0 | 1.0 | ok | ok | exact | - | - |
| multi-rows-020 | multi | multi | 95,102,99,103,94 | - | - | ['missing_param', 'missing_param'] | ['missing_param', 'missing_param'] | - | - | - |
| multi-rows-021 | multi | results | 99,91,95,95,99,91 | 1.0 | 0.5 | ['ok', 'ok'] | ok | - | - | - |
| chat-weather-022 | chat | chat | - | - | - | - | not_applicable | - | - | - |
| chat-knowledge-023 | chat | chat | - | - | - | - | not_applicable | - | - | - |
| chat-greeting-024 | chat | chat | - | - | - | - | not_applicable | - | - | - |

## 五、薄弱案例

### multi-rows-021（实际 multi / 期望 results）

- 输入：304 和 316 的 M8×30 螺丝，要 1000 个
- 候选：[99, 91, 95, 95, 99, 91]，Recall@3 1.0，MRR 0.5
- 行状态：实际 ['ok', 'ok'] / 期望 ok

```text
共 2 条需求，匹配到 2 条。明细在右侧。
```

### alternative-m12x80-012（实际 results / 期望 results）

- 输入：M12×80 的内六角螺丝，要 100 个
- 候选：[96, 94, 92, 103, 93]，Recall@3 1.0，MRR 1.0
- 行状态：实际 alternative_only / 期望 alternative_only
- 硬约束违反：碳钢热镀锌外六角螺栓 M12×60: 长度不符（要求 80mm，实际 60mm）；304 不锈钢内六角圆柱头螺丝 M10×40: spec 不含 M12（实际 M10×40mm）；304 不锈钢内六角圆柱头螺丝 M10×40: 长度不符（要求 80mm，实际 40mm）

```text
> 没有完全匹配的规格（长度要求 80mm，候选 60mm），以下是可替代的候选，下单前请确认是否可用。  ## 推荐  候选商品中没有 M12×80 的内六角螺丝，以下按接近程度排序，均不能直接按你的规格下单：  1. **304 不锈钢内六角圆柱头螺丝 M10×40（东明）** — 唯一同类型（内六角圆柱头），但规格 M10×40 与 M12×80 不符，直径和长度都偏小，不能替代 M12×80 使用。 2. **304 不锈钢内六角圆柱头螺丝 M8×50（东明）** — 同为内六角，规格更小，不适用。 3. **304 不锈钢内六角圆柱头螺丝 M6×20（东明）** — 同为内六角，规格最小，不适用。 4. **碳钢热镀锌外六角螺栓 M12×60（永固）** — 直径 M12 对得上，但为外六角头、长度 60mm，头型和长度均不符。 5. **碳钢六角螺母 M10（永固）** — 螺
```

### material-304-011（实际 results / 期望 results）

- 输入：要 304 不锈钢的 M8×30 外六角螺栓，1000 个
- 候选：[91, 99, 95]，Recall@3 1.0，MRR 1.0
- 行状态：实际 ok / 期望 attr_conflict

```text
## 推荐  **没有完全匹配的候选商品。** 三个候选均不满足「304 不锈钢 + 外六角」的组合要求，无法直接下单。  按接近程度排序：  1. **候选3 碳钢镀锌外六角螺栓 M8×30（永固）** — 这是你要的「外六角」头型，但**这不是你要的 304 不锈钢，而是碳钢镀锌**。规格 M8×30、8.8 级、MOQ 1000、交期 3 天，头型和尺寸对得上，价格最低。仅适用于对防锈要求不高、可接受镀锌件的室内/一般工况；不能替代 304 的耐腐蚀性能，户外或潮湿环境不建议用。  2. **候选1 304 不锈钢内六角圆柱头 M8×30（东明）** — 材质是你要的 304（A2-70），但**这不是你要的外六角，而是内六角圆柱头**。规格、MOQ 1000、交期 2 天均满足，防锈耐腐蚀。若安装工具和沉孔空间允许改用内六角，可作为替代方案，但头型与外观不符合原需求。  3. **
```

## 六、怎么读这些分数

- **Faithfulness 偏低，主要来自口径而不是编造**：推荐正文里有大量「注意事项」（含税、账期、备损、安装建议），这些内容不在候选商品属性里，RAGAS 会判成不被上下文支持。真实编造（价格/参数写错）需要看具体 case，不能只看均值。
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
