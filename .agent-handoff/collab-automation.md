# 协作自动化：双端定时接力协议

> 起草：阿渔；修订定稿：2026-11-14 23:26 · 渔渔  
> 当前用途：IndexManager 自动接力试点。  
> 当前计划：`.agent-handoff/plan.md`

## 1. 分工与边界

| 角色 | 负责 | 不得直接做 |
| --- | --- | --- |
| 渔渔（本地 Kimi Code） | 出计划、独立复核、批准或提出返工 | 不因定时器触发而直接实施业务改动 |
| 阿渔（DSH） | 领取已批准计划、实施、基础验证、提交复核 | 不自主决定新批次，不把自己标为 `approved` |

自动接力只减少传话，不取消主人的范围确认。新计划必须同时满足：

```yaml
status: ready
user_approved: true
auto_execute: true
```

阿渔才能首次领取。`draft`、`ready` 但未获批、未允许自动执行的计划都不能动业务代码。

## 2. 计划文件与状态机

当前活动计划固定为 `.agent-handoff/plan.md`，文首必须有：

```yaml
---
plan_id: 20261114-index-manager-01
batch: IndexManager 增量索引与自动接力
revision: 1
status: draft
owner: 阿渔
reviewer: 渔渔
user_approved: false
auto_execute: false
created_at: YYYY-MM-DD HH:mm
updated_at: YYYY-MM-DD HH:mm
---
```

状态流转：

```text
draft
→ ready                    主人批准范围并允许自动执行
→ in_progress              阿渔原子领取
→ review_requested         阿渔实施和自测完成
→ approved                 渔渔复核通过
→ 归档

review_requested
→ changes_requested        渔渔提出具体返工项
→ in_progress              阿渔领取同一 plan_id 的新 revision
→ review_requested
→ approved / 第二轮返工 / blocked
```

规则：

- `plan_id + revision` 标识一次执行，重复触发不得重复实施。
- 执行者只能推进到 `review_requested`。
- 复核者写 `approved` 或 `changes_requested`，并附证据和未覆盖范围。
- 返工时 `revision` 增加；同一计划最多自动往返两轮，仍不通过则 `blocked`。
- 完成后归档到 `.agent-handoff/plans/YYYY-MM-DD-批次.md`。
- `current.md` 始终指向当前活动计划或最终归档。

## 2.1 执行结果与证据

> 2026-11-16 追加。起因：某次执行结果写的是「18 项 ALL PASS」，实际那是改动前跑的旧输出，复核者重跑得到 6 项失败。

「声明」「回执」「制品」是三件不同的东西，不能混着写：

| | 是什么 | 允许的写法 |
| --- | --- | --- |
| 声明 | 「我认为改到位了」 | 可以写判断，但要标明是判断 |
| 回执 | `status: review_requested` | 只能是事实，不能带结论 |
| 制品 | 命令原文 + 实际输出 + 运行时间 | 必须来自真实运行，不许转述 |

规则：

1. **执行结果必须附证据文件**。路径固定为 `.agent-handoff/artifacts/<plan_id>-r<revision>.log`，内容至少包括：
   - 每条验证命令的原文（可直接复制运行）
   - 该命令的实际输出，失败的也照贴，不许只留通过的部分
   - 每条命令的执行时间，取自 `Get-Date` 的实际输出，不手写
2. **`plan.md` 的「执行结果」只放结论与指向**：改了什么、结论是什么、证据见哪个文件。输出全文不进 `plan.md`。
3. **没有证据不许写「通过」**。没跑过、没留输出，或输出来自改动前的运行，一律写「未验证」；不许把「改完应该就对了」写成 PASS。
4. **复核者先看证据再看结论**。证据文件缺失、或结论与证据矛盾时，直接 `changes_requested`，不需要再逐行读代码。

## 3. 原子锁

锁文件：`.agent-handoff/lock.json`。

内容至少包括：

```json
{
  "owner": "阿渔",
  "plan_id": "20261114-index-manager-01",
  "revision": 1,
  "started_at": "YYYY-MM-DDTHH:mm:ss",
  "expires_at": "YYYY-MM-DDTHH:mm:ss"
}
```

规则：

1. 通过“文件不存在时才允许创建”的原子方式抢锁；成功创建的一方才获得执行权。
2. 抢锁后先将计划改为 `in_progress`，再实施。
3. 有未过期锁时不抢、不覆盖，等待下一次轮询。
4. 过期锁不能直接删除后复工；先核对持有者是否仍在运行。无法确认时标记 `blocked` 并交主人处理。
5. 正常完成、提交复核或进入 `blocked` 后释放自己持有的锁。
6. 复核者只修改计划、交接和评审文档，不持业务实施锁，也不修改执行中的业务文件。

## 4. 双端定时任务

试点期间双方每 5 分钟检查一次 `.agent-handoff/plan.md`，测试结束后都删除任务。

### 阿渔（DSH）执行轮询

每次触发：

1. 读取计划和锁；没有新工作立即结束。
2. 可领取的情况：
   - `ready + user_approved: true + auto_execute: true` 的新 `plan_id`。
   - `changes_requested` 中交给阿渔的新 `revision`。
3. 原子抢锁，改 `in_progress`，严格按范围实施和验证。
4. 成功则写执行结果、附证据文件（见 2.1）并改 `review_requested`；无法按计划完成则写 `blocked`。
5. 释放锁，在 `current.md` 和当日日志记录定时任务标识与结果。

### 渔渔（本地 Kimi Code）复核轮询

每次触发：

1. 读取计划；不是 `review_requested` 或复核人不是渔渔时立即结束。
2. 已复核过的 `plan_id + revision` 不重复复核。
3. 读取最新代码，按验收标准独立验证。
4. 写 `approved` 或 `changes_requested`，更新 `current.md` 和日志。
5. 通过后归档；返工时增加 `revision`，交阿渔领取。

### 定时能力限制

本地 Kimi Code 的定时任务只在当前会话存活且空闲时触发，不是长期系统守护进程。本次试点需保持对应会话开启；长期方案再使用 Windows 任务计划程序或常驻调度器。

## 5. 自动执行禁区

即使计划已批准，定时任务也不能自行扩大为以下操作：

- 删除或迁移真实数据。
- 升级依赖、引入计划外依赖。
- 重启计划外服务。
- `git commit`、`git push` 或其它远端操作。
- 修改计划列出的文件范围。
- 读取或传输敏感配置。

遇到上述需要时进入 `blocked`，由主人决定。

## 6. 试点通过标准

- 未经批准的计划不会被执行。
- 阿渔能自动领取批准的 IndexManager 计划，且只领取一次。
- 锁能阻止并发实施，异常时有明确状态。
- 阿渔完成后渔渔能自动开始复核。
- 执行与复核状态不能越权，返工能按 revision 回流。
- 验收标准、实际执行、复核结论和未覆盖范围完整。
- 每份执行结果都有对应证据文件，且结论与证据一致；缺证据或结论与证据矛盾时复核直接打回。
- 测试结束后双方定时任务删除，计划归档。

## 7. 长期方向

本次先验证文件状态机与双端触发。若长期需要无人值守，再实现 Windows 常驻调度器，根据状态分别调用两端已有的非交互入口；在那之前，不把当前会话定时器描述成可靠的跨会话服务。

## 8. 执行范围、交接清单与制品验证（2026-11-16 补充）

> 依据：`D:\study\lesson\实现Hermes中的多Agent协作、主Agent调度\课程总结.md`。  
> 本节约束后续所有批次，与第 3、4 节配合使用，不引入 ACP、checkpoint 或断点续跑。

### 8.1 原子锁不是权限边界

`lock.json` 只负责互斥，防止同一任务重复实施，不能限制执行者修改哪些文件。

新计划 frontmatter 必须增加：

```yaml
allowed_paths:
  - backend/app/orchestration.py
  - backend/eval/**
blocked_actions:
  - delete_data
  - install_dependency
  - restart_service
  - git_commit
  - git_push
inputs:
  - backend/eval/dataset.jsonl
  - docs/REPORT-TEMPLATE.md
expected_artifacts:
  - docs/example-report.md
  - docs/example-report.json
```

规则：

1. `allowed_paths` 和 `blocked_actions` 管执行范围，原子锁管并发，两者不得互相替代。
2. 执行结果必须列出实际修改文件；复核时检查是否超出 `allowed_paths`。
3. 越界修改不能因测试通过而批准，应直接进入 `changes_requested` 或 `blocked`。
4. 只有文档约定而没有系统级隔离时，不得宣称已经实现沙箱。

### 8.2 交接必须包含任务、材料、模板和预期制品

接手者不能只依赖当前会话或另一方的聊天记忆。每份计划需要明确：

- 任务文字：目标、范围、验收标准。
- `inputs`：数据、原始采集、参考实现等输入文件。
- 模板或格式约束：报告模板、输出 schema、命名规则。
- `expected_artifacts`：最终应生成的文件。

材料文件不存在或不符合要求时，不得凭模型常识编造内容继续实施，应写 `blocked` 并说明缺什么。

### 8.3 回执不等于完成，命令成功不等于制品合格

提交 `review_requested` 前，执行者必须完成制品检查，而不只是看到进程结束或命令返回 0。

对 `expected_artifacts` 中的每个文件，至少验证：

- 文件存在，且为普通文件，不接受符号链接冒充。
- 文件大小大于 0。
- 记录 SHA-256。
- 实际读回正文或解析结构化内容，确认非空、格式正确、关键字段存在且无乱码。
- 内容与计划验收标准一致，不以模型在消息里声称“已生成”作为证据。

制品清单建议保存为 `.agent-handoff/artifacts/<plan_id>-r<revision>-manifest.json`，至少包含：

```json
{
  "plan_id": "example-01",
  "revision": 1,
  "status": "completed",
  "error": null,
  "artifacts": [
    {
      "path": "docs/example-report.md",
      "bytes": 12345,
      "sha256": "实际哈希",
      "readback_ok": true
    }
  ]
}
```

`manifest.status` 描述本次执行是否完成；`review_requested` 仍然只是请求复核，只有复核者才能写 `approved`。

### 8.4 失败留证与重跑边界

- 每次失败运行的日志、原始结果、修改清单和半成品必须保留，不覆盖上一次失败的 revision 证据。
- 返工必须使用新 revision，并说明修复了哪个失败点。
- 已存在合格制品时，先读回检查，再决定是否需要重跑；不得因为定时器重复触发就重复生成。
- 保留输入文件，修复条件后可以重新执行；不做无限重试，不超过既定两轮返工上限。

### 8.5 后续验收补充

以后每个批次除原有验收外，还必须回答：

1. 实际修改文件是否全部在 `allowed_paths` 内？
2. `inputs`、模板和 `expected_artifacts` 是否明确且存在？
3. 制品是否通过存在性、大小、SHA-256 和正文读回检查？
4. 失败 revision 的日志与制品是否保留？
5. 是否只凭回执、返回码或模型声明就误判完成？

以上任一项不能回答，都不得写 `approved`。
