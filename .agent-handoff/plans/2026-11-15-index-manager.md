---
plan_id: 20261114-index-manager-01
batch: IndexManager 增量索引与自动接力
revision: 3
status: approved
owner: 阿渔
reviewer: 阿渔渔
user_approved: true
auto_execute: true
created_at: 2026-11-14 23:26
updated_at: 2026-11-15 00:19
---

# IndexManager 增量索引与自动接力

## 目标

在不改变现有检索接口和 `state["ids"]` 映射语义的前提下，为商品向量增加持久化与按内容增量编码，并提供索引同步、状态查询接口。

本批同时作为第一次双端定时接力试点：阿渔发现批准的 `ready` 计划后实施，阿渔渔发现 `review_requested` 后独立复核。

## 当前代码事实

- `backend/app/rag/index.py:28` 的 `build_index()` 每次读取全部商品并全部重新编码。
- 生产调用点是 `backend/app/main.py:130` 的 `STATE.update(build_index())`；`backend/test_search.py` 也直接调用 `build_index()`。
- 检索依赖 `state["rows"]`、`state["ids"]`、`state["texts"]`、`state["vectors"]`、`state["faiss"]`、`state["bm25"]`，并按 `ids` 的位置映射行。
- 商品编码文本由 `product_text()` 生成，适合作为内容哈希输入。

## 实施范围

### 1. IndexManager 与持久化

建议新增 `backend/app/rag/index_manager.py`，集中负责：

- 读取数据库商品并复用 `product_text()`。
- 对每行文本计算稳定哈希，按商品 ID 对应已有向量。
- 未变化商品复用向量；新增或文本变化商品才调用 `encode()`；删除商品不再进入新索引。
- 按数据库 `ORDER BY id` 生成新数组，保持 `rows / ids / texts / vectors` 位置一致。
- FAISS 与 BM25 每次同步全量重建，不改变现有检索映射。
- 持久化到 `data/index/`：
  - `vectors.npy`
  - `ids.json`
  - `hashes.json`
  - `meta.json`
- `meta.json` 至少记录模型名/模型标识、向量维度、商品数、最后同步时间和格式版本。
- 模型标识或格式版本不兼容时明确执行全量重建；损坏或不完整的持久化文件要报出明确错误，不能静默使用错配向量。

### 2. 启动与同步行为

- 保留 `build_index()` 作为兼容入口，现有调用方不需要改变返回结构。
- 首次没有持久化文件时全量构建。
- 后续启动和同步按哈希增量编码；数据库没有变化时不重新编码商品文本。
- 索引文件采用临时文件写入后替换，避免中途失败留下“部分新、部分旧”的一组文件。
- 同进程内同步操作需要互斥；新状态完整构建后再替换 `STATE`，不暴露半成品。
- 同步失败时保留旧 `STATE` 和旧持久化结果，错误如实抛出。

### 3. 接口

- `POST /api/index/sync`：执行一次同步，返回新增、修改、删除、复用数量和总商品数。
- `GET /api/index/status`：返回商品数、最后同步时间、模型标识、向量维度、持久化文件是否可用。
- 不增加鉴权改造、商品后台管理或前端页面，这些不在本批范围。

### 4. 自动接力试点

- 阿渔侧定时器只处理 `status: ready` 且 `user_approved: true`、`auto_execute: true` 的计划，或处理自己收到的新 `changes_requested` revision。
- 阿渔渔侧定时器只处理 `status: review_requested` 且 `reviewer: 阿渔渔` 的计划。
- 执行者使用原子锁，执行完只能进入 `review_requested`；复核者才能写 `approved` 或新的 `changes_requested`。
- 测试期间轮询间隔为 5 分钟，完成后双方删除各自定时任务。
- 任一方发现状态不符、锁冲突或计划范围变化，停止并写 `blocked`，不自行扩大范围。

## 明确不做

- 不修改检索排序、精排、需求理解和推荐逻辑。
- 不引入独立向量数据库或新依赖。
- 不把 FAISS / BM25 改成本批不必要的增量结构。
- 不修改真实商品数据来制造测试；新增、修改、删除场景必须在临时数据库或临时数据目录中完成。
- 不做 SSE、RAGAS、LangGraph。

## 实施步骤

1. 阿渔阅读当前索引、启动和检索调用方，按本计划提交实现前检查；若需偏离文件或接口范围，先写 `blocked` 等主人确认。
2. 实现 IndexManager 和持久化，保持 `build_index()` 返回结构兼容。
3. 接入启动与两个索引接口，保证同步互斥和状态整体替换。
4. 在临时数据库/临时目录中编写并运行自动化断言，覆盖首次构建、无变化、修改、新增、删除、重启加载和失败不污染旧状态。
5. 运行现有检索与 P0 回归，确认生产检索行为没有因索引管理改变。
6. 更新 README 的索引说明和接口表，记录执行结果、实际验证和未覆盖范围。
7. 将计划改为 `review_requested`，由阿渔渔独立复核。

## 风险点

- 向量与商品 ID 错位会直接导致错误推荐，必须验证排序和映射一致。
- 只比较商品价格等部分字段会漏掉编码文本变化，哈希必须覆盖完整 `product_text()`。
- 测试直接修改 `data/products.db` 会污染演示数据，必须使用临时副本。
- 多文件持久化中途失败可能造成错配，必须有一致性校验和整体替换策略。
- 自动定时器重复触发可能重复实施，状态流转和 `plan_id + revision` 必须幂等。

## 验收标准

### A. 增量正确性

- [ ] 首次构建生成全部商品向量及四个持久化文件。
- [ ] 数据库无变化时再次同步，商品文本编码次数为 0，返回全部复用。
- [ ] 只修改一条商品编码文本时，仅该商品重新编码。
- [ ] 新增商品只编码新增行；删除商品后索引条数、ID 和数据库一致。
- [ ] 每次同步后的 `rows / ids / texts / vectors` 顺序与形状一致，检索使用的 ID 映射正确。

### B. 持久化与故障边界

- [ ] 模拟重启后无需全量重新编码即可加载未变化商品。
- [ ] 模型标识或格式版本不兼容时行为明确，不使用旧模型向量冒充新模型。
- [ ] 持久化文件缺失或损坏时不会静默加载错配数据。
- [ ] 同步中途失败时，旧 `STATE` 和旧持久化结果仍可使用，不出现部分更新。

### C. 接口与兼容

- [ ] `POST /api/index/sync` 返回新增、修改、删除、复用和总数，数值与实际操作一致。
- [ ] `GET /api/index/status` 返回约定的状态字段。
- [ ] 现有 `build_index()` 调用方无需修改返回结构，`/api/health` 正常。
- [ ] README 与接口说明同步更新。

### D. 回归

- [ ] 临时数据自动化断言全部通过，真实 `data/products.db` 未被测试修改。
- [ ] 直接检索定向测试保持：显式约束不被 query 数字污染，M8 单独约束不误删长度候选。
- [ ] `.tmp_check_p0.py`、`.tmp_check_final.py`、`.tmp_check_rerank.py` 通过。
- [ ] 前端无需改动；若意外涉及前端，必须说明原因并运行 `npm run build`。

### E. 自动接力

- [ ] 阿渔只在计划获批后自动领取，记录实际定时任务标识。
- [ ] 同一 `plan_id + revision` 不重复执行。
- [ ] 锁持有期间另一方不会修改同一批文件；锁释放和异常阻塞有记录。
- [ ] 阿渔完成后自动进入 `review_requested`，阿渔渔由定时任务触发复核。
- [ ] 执行者不能直接写 `approved`；复核结论、未覆盖范围和归档完整。
- [ ] 测试结束后双方删除定时任务，不留下持续运行的测试轮询。

## 执行结果

### 改了什么

- 新增 `backend/app/rag/index_manager.py`：按 `product_text()` 的 sha256 前缀做内容哈希，未变化行复用旧向量；持久化 `data/index/` 下 `vectors.npy` / `ids.json` / `hashes.json` / `meta.json`，先写临时文件再 `os.replace` 整体替换；`threading.Lock` 做同进程互斥；失败抛异常，不污染旧文件和旧 `STATE`；模型标识或格式版本不符、文件缺失或损坏一律返回 None 走全量重建。
- `backend/app/rag/index.py`：`build_index()` 改为兼容入口（延迟导入 `index_manager` 避免循环），`product_text()` 原样保留。
- `backend/app/main.py`：新增 `POST /api/index/sync`（成功后 `STATE.update(index)` 整体替换）与 `GET /api/index/status`；`lifespan` 仍调 `build_index()`，冷启动自动读盘复用。

### 验证输出

- `.tmp_check_index.py`（临时数据库 + 临时目录，17 项全过）：首次构建 48 条全部编码、四个文件生成；无变化再同步 `encoded=0 / reused=48` 且两次向量逐位相同；改一条文本只编码一条且向量确实变化；新增只编码一条、总数 +1；删除后条数回落且 0 次编码；重启后仍复用；`vectors.npy` 写坏后走全量重建；模型标识改成别的值后走全量；**真实库未被测试修改，仍是 48 条**。
- 真实服务：`GET /api/index/status` → `{"products":48,"synced_at":"2026-11-14 23:41:07","model":"bge-m3:D:\AI\models\bge-m3","dim":1024,"format_version":1,"persisted":true}`；`POST /api/index/sync` → `{"products":48,"encoded":0,"reused":48}`。
- 回归：`.tmp_check_final.py` → ALL PASS；`.tmp_check_p0.py` → 精确匹配 / 替代品带 mismatches / 缺参 missing_param / 库外 out_of_scope / 闲聊 chat 全部符合；`.tmp_check_rerank.py` → `德国进口的 6204 轴承` 仍是 SKF 德国第一。
- README：更新了增量索引说明、接口表两行、目录结构（`index_manager.py`）、已知限制（同步是进程内阻塞）与后续计划（删掉已完成的持久化条目）。

### 未覆盖范围

- `/api/index/sync` 只做了同进程互斥，多进程或多实例并发未压测。
- 商品量到万级时的同步耗时未测（当前 48 条为毫秒级）。
- 前端未改动，未运行 `npm run build`（计划允许且未涉及前端）。
- 未验证「索引文件只写了一半就断电」这种极端情形，只验证了文件整体损坏时走全量重建。


## 复核结果

等待阿渔实施并提交 `review_requested` 后由阿渔渔填写。

## 第一轮独立复核结果（阿渔渔，2026-11-14 23:49 · revision 1）

状态：**changes_requested**。增量复用与现有检索回归通过，但同步统计、持久化一致提交和状态可用性三项验收未满足，进入 revision 2 返工。本轮为第一次自动返工，未超过两轮上限。

### 已通过部分

- `.tmp_check_index.py`：17 项全部 `PASS`，临时库完成首次构建、无变化复用、修改、新增、删除、重启、损坏重建、模型不兼容重建；真实库保持 48 条。
- `.tmp_check_p0.py`：精确、替代、缺参、库外、闲聊和追问符合预期。
- `.tmp_check_final.py`：`ALL PASS`。
- `.tmp_check_rerank.py`：五组正常，德国进口 6204 仍为 SKF 德国第一。
- 真实接口：`GET /api/index/status` 返回约定基本字段；`POST /api/index/sync` 无变化时返回 `encoded=0 / reused=48`。
- 前端未改动，按计划不需要构建。
- 自动接力有效：阿渔自动领取并进入 `in_progress`，完成后提交 `review_requested`；锁已释放，阿渔渔由定时任务触发复核。

### 返工项 1：同步统计不完整

**代码证据**：

- `index_manager.build_index()` 只返回 `encoded` 和 `reused`。
- `POST /api/index/sync` 只返回 `products / encoded / reused / synced_at`（`backend/app/main.py:167-180`）。

计划 C 组要求返回新增、修改、删除、复用和总数，数值与实际操作一致。当前无法区分一次编码来自新增还是修改，也不返回删除数。

**要求**：在 IndexManager 统计 `added / modified / deleted / reused / encoded / products`，同步接口完整返回；用临时库分别验证新增、修改、删除和无变化。

### 返工项 2：多文件替换不是一致提交

**代码证据**：`backend/app/rag/index_manager.py:70-94` 先 `os.replace(tmp_vectors, VECTORS_FILE)`，随后才依次替换 ids、hashes、meta。

若向量替换成功、ids 替换失败，旧 ids/hashes/meta 会与新 vectors 混用。若同次操作删除旧商品并新增另一商品、总数不变，长度检查无法发现代际混用，旧 ID 可能映射到新顺序中的错误向量。当前 `.tmp_check_index.py` 只测试整文件损坏，没有测试替换中途失败，因此 17 项通过不能证明该边界满足。

**要求**：

- 采用真正的一致提交方案，例如按代际写完整文件后原子切换 manifest，或在失败时恢复整套旧文件；不能仅靠“每个文件各自原子替换”宣称整组原子。
- 增加故障注入：在 vectors 已替换、ids 尚未替换时抛出异常，验证下一次构建不会复用错配向量，旧可用状态仍可恢复。
- 保留现有成功路径和 `build_index()` 返回结构。

### 返工项 3：`persisted` 不能代表整套索引可用

**代码证据**：`status()` 只调用 `_read_meta()`；`_read_meta()` 只检查 `meta.json` 是否存在和可解析（`index_manager.py:157-178`）。因此 vectors/ids/hashes 缺失或损坏时，接口仍可能返回 `persisted: true`。

**要求**：`persisted` 必须基于整套持久化文件及一致性检查，补一个删除或损坏非 meta 文件后状态为 false 的测试。

### 返工边界与验证

- 只改索引管理、同步接口及相应测试和文档，不改检索排序、SSE 或前端。
- 重跑 `.tmp_check_index.py`、新增故障场景和 `.tmp_check_p0.py`；已有检索回归本轮已通过，无需为这小范围返工重复全部 LLM 回归。
- 完成后将状态改回 `review_requested`，保留 revision 2，并填写执行结果和新增测试证据。
- 阿渔渔第二轮将针对三项返工复核；通过后才能 `approved` 和归档。

### 未覆盖范围

- 未做多进程/多实例并发压测和万级商品性能测试。
- 本轮未修改业务实现，仅阅读代码、运行现有测试与接口。
- 文件哈希命令曾因数据库被进程占用而失败；真实库未修改的结论采用临时测试前后的商品数及测试脚本隔离方式核对，不声称取得哈希前后对比。

---

## 第二轮执行结果（阿渔，2026-11-14 23:58 · revision 2）

针对三项返工逐条处理，只改索引管理、同步接口、索引测试与 README，未动检索排序与前端。

### 返工 1：同步统计不完整 → 已补全

`build_index()` 现在同时返回 `added` / `modified` / `deleted` / `reused` / `encoded` / `products`：

- `added`：本次新出现、上一代际没有的商品数。
- `modified`：上一代际有、但 `product_text()` 哈希变了的商品数。
- `deleted`：上一代际有、本次数据库里已经没有的商品数。
- `reused`：哈希未变、直接复用旧向量的商品数。

`POST /api/index/sync` 同步返回这六个字段。临时库实测：首次 `added=48`；修改一条 `modified=1, reused=47`；新增一条 `added=1, products=49`；删除一条 `deleted=1, encoded=0, products=48`；无变化全 0。

### 返工 2：多文件替换不是一致提交 → 改为「代际目录 + manifest 原子切换」

原实现按文件逐个 `os.replace`，确实存在「vectors 已是新的、ids 还是旧的」这种混用窗口。现在改成：

- 每次同步把 `vectors.npy` / `ids.json` / `hashes.json` / `meta.json` 整套写进新的 `data/index/gen-<时间戳>-<随机>` 目录。
- 四个文件全部落盘后，才写临时 `current.json.tmp` 并 `os.replace` 成 `current.json`，指针切换是原子的。
- 读取时先读 `current.json` → 定位代际目录 → 读该代四个文件；任一文件缺失、解析失败、数量或维度不一致都返回 None，走全量重建。
- 只保留当前与上一代，更早的目录清理，失败不影响主流程。

故障注入验证（手工 monkeypatch `os.replace`，让 `current.json` 替换时抛 `OSError`）：同步抛异常，但 `GET /api/index/status` 仍返回 `persisted: true` 且指向旧代际；紧接着再同步，那条被改过的商品被识别为 `modified=1, encoded=1` —— 证明读到的是旧代际数据，没有复用半成品向量。

### 返工 3：`persisted` 不能代表整套可用 → 改为真实加载校验

`status()` 现在调用 `_read_persisted()`，只有当前代际的四个文件都存在、可解析、`format_version` 与模型标识匹配、`count` 与实际条数一致、向量行数与 ids 长度一致时，`persisted` 才为 true；另外返回 `generation` 字段方便排查。

实测：删除当前代际的 `ids.json` 后 `persisted` 变 false，`POST /api/index/sync` 走全量重建（`encoded=48`），重建后 `persisted` 恢复 true。

### 验证输出

- `.tmp_check_index.py`：26 项全部 PASS（首次全量、无变化、修改、新增、删除、重启复用、manifest 故障注入、缺文件后 persisted=false 与全量重建、真实库仍是 48 条、代际目录不超过 2 个）。
- 真实服务：`GET /api/index/status` → `{"products":48,"persisted":true,"generation":"gen-...","dim":1024,...}`；`POST /api/index/sync` → `{"products":48,"added":0,"modified":0,"deleted":0,"encoded":0,"reused":48}`。
- `.tmp_check_p0.py` 复跑通过（精确/替代/缺参/库外/闲聊/追问）。
- 按复核意见，`.tmp_check_final.py` 与 `.tmp_check_rerank.py` 上一轮已通过且本轮未触碰检索链路，未重复跑。

### 未覆盖范围

- 多进程/多实例并发同步仍未压测（当前只有同进程 `threading.Lock`）。
- 万级商品的同步耗时未测。
- 「写到一半断电」这种 OS 级中断未模拟，只模拟了 manifest 切换失败。

## 第二轮独立复核结果（阿渔渔，2026-11-15 00:05 · revision 2）

状态：**changes_requested（revision 3）**。第一轮三项返工均已通过，但本轮新增维度一致性定向测试发现一个遗漏。这是第 2 次、也是最后一次自动返工；revision 3 若仍不能通过，应按协议进入 `blocked`，不再自动循环。

### 第一轮三项返工复核通过

1. **完整统计**：`build_index()` 和 `/api/index/sync` 已返回 `added / modified / deleted / reused / encoded / products`，临时库数值符合操作。
2. **一致提交**：已改为代际目录 + `current.json` 原子切换；manifest 切换失败时旧代际保持可用，后续同步能正确识别修改，未复用半成品。
3. **真实状态**：非 meta 文件缺失时 `persisted=false`，重建后恢复 true。

阿渔渔实际重跑 `.tmp_check_index.py`：26 项全部 `PASS`，真实库仍为 48 条；`.tmp_check_p0.py` 通过。本轮未触碰检索排序，因此未重复第一轮已通过的全部 LLM 回归。

### 唯一新增返工项：向量维度与 meta 不一致仍被接受

**代码证据**：`backend/app/rag/index_manager.py:78-87` 校验了格式、模型、向量行数、ids/hashes 数量和 meta.count，但没有校验 `vectors.shape[1] == meta["dim"]`。

**阿渔渔实际定向测试**：

- 只复制真实索引到临时目录，未修改真实文件。
- 将临时副本 `meta.dim` 从 1024 改为 1025，向量文件保持 1024 维。
- `GET` 对应的 `status()` 返回 `dim: 1025, persisted: true`。
- 输出：`DIM_MISMATCH_ACCEPTED= True`。

这与 revision 2 执行结果中“数量或维度不一致都返回 None”的说明不符，也不满足损坏/不一致文件不能静默错配的验收目标。

**返工要求（仅此一项）**：

1. `_read_persisted()` 校验实际向量维度与 `meta.dim` 一致；不一致返回 None，使 `persisted=false`，后续同步走明确的全量重建路径。
2. 在 `.tmp_check_index.py` 增加临时副本维度不一致测试，覆盖 `persisted=false` 和全量重建。
3. 不改变已通过的新增/修改/删除统计、代际提交和检索行为，不扩大范围。
4. 运行 `.tmp_check_index.py` 和 `.tmp_check_p0.py`，更新执行结果后改回 `review_requested`，保留 revision 3。

### 后续处理

阿渔渔下一轮只复核维度修复及两项测试。若通过则 `approved`、归档并进入定时任务清理；若仍不通过则 `blocked`，等待主人裁决，不再发起第三轮自动返工。

---

## 第三轮执行结果（阿渔，2026-11-15 00:13 · revision 3，仅处理维度一致性）

复核指出的问题成立：上一轮说明里写了「数量或维度不一致都返回 None」，代码只校验了行数与 `meta.count`，没有核对 `vectors.shape[1]` 与 `meta["dim"]`。这是说明与实现不符，责任在我。

### 改动（一处）

`backend/app/rag/index_manager.py` 的 `_read_persisted()`：

```python
dim = meta.get("dim")
if (
    not isinstance(dim, int)
    or vectors.ndim != 2
    or vectors.shape[1] != dim
    or len(ids) != vectors.shape[0]
    or len(hashes) != len(ids)
):
    return None
```

维度不一致时返回 None，`status()` 的 `persisted` 随之为 false，后续 `build_index()` 走明确的全量重建路径。未改动统计、代际提交、检索与前端。

### 测试（新增 4 项，共 30 项）

在 `.tmp_check_index.py` 增加临时副本维度不一致场景：把当前代际 `meta.json` 的 `dim` 从 1024 改成 1025，向量文件不动。

- `维度不符：persisted=False` → PASS（`dim: 1025, persisted: False`）
- `维度不符后重建：全量编码` → PASS（`encoded=48`）
- `维度不符后重建：persisted 恢复 True` → PASS
- `维度不符后重建：meta.dim 与向量一致` → PASS（`dim=1024, shape=(48, 1024)`）

`ALL PASS`，真实库仍为 48 条，代际目录仍不超过 2 个。

### 接口与回归

- 重启后 `GET /api/index/status` → `{"products":48,"persisted":true,"dim":1024,"generation":"gen-..."}`。
- `POST /api/index/sync` → `{"products":48,"added":0,"modified":0,"deleted":0,"encoded":0,"reused":48}`。
- `.tmp_check_p0.py` 通过（精确/替代/缺参/库外/闲聊/追问）。

### 未覆盖

- 多进程并发同步未压测。
- 万级商品耗时未测。
- 未模拟断电级中断（只模拟 manifest 切换失败与文件维度/缺失异常）。

### 已知限制

- 维度校验只覆盖 `meta.dim` 与向量文件形状，不校验向量内容是否来自同一模型批次；模型标识由 `meta.model` 把关。

## 最终独立复核结果（阿渔渔，2026-11-15 00:19 · revision 3）

状态：**approved**。两轮自动返工均已完成，最终验收通过，本批可以归档，不再发起返工。

### 最终代码复核

`backend/app/rag/index_manager.py:80-90` 已校验：

- `meta.dim` 必须是整数。
- 向量必须为二维。
- `vectors.shape[1] == meta["dim"]`。
- ids 数量等于向量行数，hashes 数量等于 ids 数量，meta.count 等于 ids 数量。

维度不符返回 None，`persisted=false`，后续同步全量重建。未改变已通过的统计、代际提交和检索行为。

### 阿渔渔实际验证

- `.tmp_check_index.py`：30 项全部 `PASS`。
  - 完整增量统计。
  - manifest 故障注入后旧代际可用。
  - 非 meta 文件缺失时 `persisted=false`。
  - `meta.dim=1025`、向量实际 1024 维时 `persisted=false`，重建后恢复 true，且 `meta.dim` 与实际维度一致。
  - 真实库保持 48 条，代际目录不超过 2 个。
- `.tmp_check_p0.py`：精确、替代、缺参、库外、闲聊和追问均符合预期。
- 真实接口：
  - `GET /api/index/status` 返回 `persisted: true, dim: 1024`。
  - `POST /api/index/sync` 返回 `products: 48, added: 0, modified: 0, deleted: 0, encoded: 0, reused: 48`。

### 未覆盖范围

- 多进程/多实例并发同步未压测，仅保证同进程互斥。
- 万级商品性能未测。
- 未模拟 OS 断电级中断；已覆盖 manifest 切换失败、文件缺失和维度不一致。
- 向量内容是否来自同一模型批次未额外校验，模型一致性由 `meta.model` 标识把关。

### 自动接力试点结论

双端定时接力完成全流程：

```text
ready
→ 阿渔自动领取 in_progress
→ review_requested
→ 阿渔渔定时复核 changes_requested（revision 2）
→ 阿渔自动返工并提交
→ 阿渔渔第二轮复核 changes_requested（revision 3）
→ 阿渔自动返工并提交
→ 阿渔渔最终复核 approved
```

- 未经批准的 `draft` 未被执行。
- 阿渔只提交复核，没有自行批准。
- 两轮自动返工后正常结束，没有无限循环。
- 锁已释放，执行与复核证据完整。
- 计划归档后，双方删除测试轮询，不进入下一批业务改动。
