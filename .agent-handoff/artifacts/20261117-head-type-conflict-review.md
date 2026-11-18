# 头型冲突进 evaluate_row() 复核清单

- 状态：revision 1，待独立复核（业务状态判断属项目规则「必须复核」项）
- 实现：DSH 阿渔，2026-11-16 23:20 实施；2026-11-17 10:00 补边界实测
- 复核：渔渔（Kimi Code）
- 改动范围：3 个文件，+55 / -1（均未提交）
- 一键撤回：`git checkout -- backend/app/demand.py backend/app/main.py backend/eval/run_ragas.py`

## 1. 改动明细（行号以当前工作区为准）

### backend/app/demand.py（+27）

| 位置 | 改动 |
| --- | --- |
| `demand.py:104-124` | 新增 `HEAD_WORDS = {"外六角": ("外六角", "六角头"), "内六角": ("内六角", "沉头")}` 与 `extract_head(text) -> str \| None` |
| `demand.py:289` | `history_demand` 累初始画像时带上 `head` |
| `demand.py:302-303` | `history_demand` 逐句覆盖时，后说的头型覆盖先说的 |
| `demand.py:321` | `merge_demand` 中 `merged["head"] = current.get("head") or prev.get("head")` |
| `demand.py:457` | `parse_demand` 返回值新增 `"head": extract_head(text)` |

`extract_head` 的判定顺序：先判外六角，再判内六角；两个族都没出现返回 `None`，后续不做头型判定。

### backend/app/main.py（+24 / -1）

| 位置 | 改动 |
| --- | --- |
| `main.py:593-609` | 新增 `HEAD_LABELS = ("内六角圆柱头", "内六角沉头", "平头内六角", "外六角", "内六角")` 与 `product_head(name) -> (族, 具体写法)` |
| `main.py:613` | `_attr_conflicts` docstring 补「头型」 |
| `main.py:628-632` | `_attr_conflicts` 新增分支：用户点名头型且商品名读得出的族不同时，追加 `f"头型是{have_label}，不是{want_head}"` |

`evaluate_row()` 函数签名未动，头型经 `_attr_conflicts` 生效。

### backend/eval/run_ragas.py（+5）

| 位置 | 改动 |
| --- | --- |
| `run_ragas.py:29` | `from app.demand import extract_head` |
| `run_ragas.py:119-123` | `build_row` 里旧 raw 没有 `head` 字段时，按同一套规则现补，保证 replay 与线上判定口径一致 |

## 2. 设计取舍（请重点看第 4 节的风险）

1. **头型只进行状态，不进检索 query**。没有改 `_build_rewritten`，避免检索排序变化污染 replay 对比。代价见风险 4。
2. **按族比较，不按具体写法比较**。库里没有独立头型字段，头型只写在商品名里；用户说「内六角」时，圆柱头/沉头/平头都算内六角族。
3. **读不出头型就不判定**（fail-open）。`product_head` 匹配不到返回 `(None, None)`，不参与冲突判断，避免误伤没写头型的商品。

## 3. 已做的验证（都是实际运行）

### 3.1 冒烟

- `parse_demand("要 304 不锈钢的 M8×30 外六角螺栓，1000 个")` → `head = 外六角`
- `evaluate_row` 对 304 内六角圆柱头（行 91）→ `{'status': 'attr_conflict', 'text': '头型是内六角圆柱头，不是外六角，仅供参考'}`
- 同一需求对 304 外六角商品（行 001）→ 仍 `ok`
- `product_head("碳钢镀锌外六角螺栓 M8×30")` → `("外六角", "外六角")`

### 3.2 全量离线 replay（24 条）

命令（在 `backend` 下）：

```
& 'D:\AI\ComfyUI\venv\Scripts\python.exe' -m eval.run_ragas --replay ..\docs\ragas-raw-2026-11-16-graph.json
```

| 指标 | 基线 | 本次 | 变化 |
| --- | --- | --- | --- |
| row_status_accuracy | 0.9167 | 0.9583 | +0.0416 |
| Recall@3 | 0.8958 | 0.8958 | 不变 |
| MRR | 0.9115 | 0.9115 | 不变 |
| stage 准确率 | 0.9583 | 0.9583 | 不变 |
| match_kind 准确率 | 0.9375 | 0.9375 | 不变 |
| 硬约束违反 | 0 | 0 | 不变 |
| 严重可下单错误 | 0 | 0 | 不变 |

- `material-304-011` 由 `ok` 变 `attr_conflict`，符合预期。
- `multi-rows-021` 仍判错（`['ok','ok']` vs `ok`），属于 `_status_matches` 对 list 型 actual 直接 False 的既有问题，本次未碰。
- 报告：`docs/ragas-baseline-2026-11-16-replay.md` / `.json`（未跟踪，未改基线文档）。

### 3.3 商品库头型写法覆盖（只读查询 `data/products.db`）

商品名含「六角」或「沉头」的共 9 条：

- 8 条命中 `HEAD_LABELS`，`product_head` 返回正确族：内六角圆柱头 4 条、内六角沉头 1 条、平头内六角 1 条、外六角 2 条。
- 1 条未命中：`碳钢六角螺母 M10`（螺母没有头型概念，返回 `(None, None)`，不判定，正确）。

### 3.4 边界实测（用于暴露已知缺陷，见第 4 节）

| 输入 | `extract_head` 结果 | 评价 |
| --- | --- | --- |
| `要沉头螺丝 M4` | 内六角 | 合理 |
| `要十字槽沉头螺钉 M4` | 内六角 | **语义混维**，见风险 3 |
| `碳钢六角螺母 M10` | null | 正确 |
| `不要外六角，要内六角螺栓 M6` | 外六角 | **错误**，见风险 1 |
| `外六角内六角都行` | 外六角 | **错误**，见风险 2 |

## 4. 重点复核的风险（按严重度排序）

### 风险 1（已复现）：否定句误判

`extract_head` 只做关键词命中，且先判外六角。`"不要外六角，要内六角螺栓 M6"` 会被判成外六角，进而把内六角商品标成 `attr_conflict`。真实对话里否定句不罕见。

- 影响面：行状态误判（严重可下单错误仍为 0，但会误伤可下单商品）。
- 可选修法：命中前先看关键词前是否有「不要/别/不用/除了」等否定词；或改为「最后出现的头型词为准」。要不要本轮修，请复核方给意见。

### 风险 2：多选场景不支持

`外六角内六角都行` 只取第一个族。用户说「都行」时应视为不约束。

- 影响面：误判 `attr_conflict`。
- 建议：识别「都行/都接受/随便」时返回 `None`。

### 风险 3：沉头与内六角不是同一维度

`HEAD_WORDS["内六角"]` 把「沉头」也当作内六角关键词。沉头是头部形状，内六角是驱动方式，二者可以交叉（十字槽沉头、内六角沉头）。当前会把「十字槽沉头螺钉」判成内六角族。

- 现状影响：库内暂无十字槽商品，暂无实际误判；一旦扩充品类就会暴露。
- 建议：要么把「沉头」从内六角关键词里拿掉，要么拆成两个维度（驱动方式 + 头部形状）。

### 风险 4：用户说得更细时不生效

用户说「内六角沉头」时 `extract_head` 返回族「内六角」，`product_head` 读得出具体写法「内六角沉头」，但 `_attr_conflicts` 只比较族，所以内六角圆柱头也会判 `ok`。用户明确要沉头却没被约束。

- 影响面：偏「不够精确」，不会误标冲突。

### 风险 5：头型不进检索 query

用户要外六角、库里外六角只有 2 条时，Top-3 可能仍以材质/尺寸排序把内六角排前面，行状态会标 `attr_conflict` 但推荐列表观感差。

- 这是本轮刻意取舍（保 replay 干净）。是否下一轮把 `head` 加进 `_build_rewritten`，请复核方判断。

## 5. 未覆盖

- 在线采集重跑（要调真实模型，会改 `docs/ragas-raw-*.json` 口径）。
- 前端与 Excel 上传入口的实跑；前端 grep 确认不读 `demand.head`，与本次改动无耦合。
- 多轮真实会话（只做了 `history_demand` / `merge_demand` 的代码级确认，没有端到端会话用例）。
- RAGAS 在线四项指标未重算（replay 模式不跑 RAGAS）。

## 6. 复核建议步骤

1. 读 `demand.py:104-124`、`main.py:593-609`、`main.py:628-632` 三处核心改动。
2. 跑第 3.2 节的 replay 命令，核对 `row_status_accuracy` 是否为 0.9583、其余指标是否不变。
3. 用第 3.4 节的五个输入验证风险 1/2/3 是否如清单所述；如确认，决定本轮修还是记账下一轮。
4. 检查 `history_demand` 对旧会话数据是否安全（已确认：`history` 是消息列表，每次实时 `parse_demand`，不存在缺 `head` 键的问题；`merge_demand` 使用 `.get` 兜底）。
