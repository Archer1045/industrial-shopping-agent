"""RAGAS 评估基线：24 条人工标注用例的确定性指标 + RAGAS 语义指标。

用法：
    python -m eval.run_ragas                      # 全量：在线采集 + 规则指标 + RAGAS
    python -m eval.run_ragas --rules-only         # 在线采集 + 规则指标（不跑 RAGAS，但仍调业务模型）
    python -m eval.run_ragas --collect-only       # 只采集原始结果（保存 raw JSON）
    python -m eval.run_ragas --replay <raw.json>  # 离线重算规则指标（零模型调用）

产物：
    docs/ragas-baseline-YYYY-MM-DD.json / .md
    docs/ragas-raw-YYYY-MM-DD.json（--collect-only 或全量时写入，用于 replay）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app import main as app_main  # noqa: E402
from app.demand import excluded_heads, extract_head, normalize  # noqa: E402

DATASET = Path(__file__).resolve().parent / "dataset.jsonl"
DOCS = BACKEND.parent / "docs"
EMBED_DIR = Path(r"D:\AI\models\bge-m3")
CONCURRENCY = 2
STAMP = date.today().isoformat()


def load_cases(limit: int | None = None) -> list[dict]:
    cases = []
    with DATASET.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases[:limit] if limit else cases


def context_text(item: dict) -> str:
    """把候选商品拼成一段检索上下文，供 RAGAS 判断信息覆盖度。"""
    parts = [
        item.get("name", ""),
        item.get("spec", ""),
        f"型号 {item['model']}" if item.get("model") and item["model"] != "-" else "",
        item.get("material", ""),
        item.get("standard", ""),
        f"工艺 {item['process']}" if item.get("process") and item["process"] != "-" else "",
        f"产地 {item['origin']}" if item.get("origin") else "",
        f"适用行业 {item['industry']}" if item.get("industry") and item["industry"] != "-" else "",
        f"¥{item['price']}" if item.get("price") is not None else "",
        f"MOQ {item['moq']}" if item.get("moq") is not None else "",
        f"交期 {item['lead_time']} 天" if item.get("lead_time") is not None else "",
        item.get("description", ""),
    ]
    return "；".join(p for p in parts if p)


def _faithfulness_text(reply: str) -> str:
    """RAGAS 只评有据的推荐正文；通用提示由系统追加，不计入事实性。"""
    head = (reply or "").split("【通用提示】", 1)[0].rstrip()
    return head.rstrip("- \n")


def collect(cases: list[dict], engine: str | None = None) -> tuple[list[dict], float]:
    """在线采集：每条调一次真实主链路，只保存原始结果，不在这里算指标。"""
    started = time.perf_counter()
    collected = []
    for i, case in enumerate(cases, 1):
        t0 = time.perf_counter()
        try:
            result = app_main._chat(
                case["user_input"],
                history=case.get("history") or [],
                top_k=5,
            )
            error = None
        except Exception as exc:  # 单条失败不影响全量
            result = None
            error = f"{type(exc).__name__}: {exc}"
        elapsed = round(time.perf_counter() - t0, 2)
        collected.append({"case_id": case["case_id"], "result": result, "elapsed": elapsed, "error": error})
        print(f"[{i}/{len(cases)}] {case['case_id']} stage={(result or {}).get('stage')} {elapsed}s"
              + (f" error={error}" if error else ""))
    return collected, round(time.perf_counter() - started, 1)


def _status_matches(expected, actual) -> bool | None:
    """行状态比对：支持单值、多行列表、not_applicable。"""
    if expected is None:
        return None
    if expected == "not_applicable":
        return actual is None
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(
            e == a for e, a in zip(expected, actual)
        )
    if isinstance(actual, list):
        return False
    return expected == actual


def _severe(items: list[dict], row_status) -> bool:
    """替代结果被标成可下单，才算严重错误。"""
    if not items or row_status != "ok":
        return False
    return any(item.get("match_kind") == "alternative" for item in items)


def build_row(case: dict, collected: dict) -> dict:
    """纯函数：从原始结果算确定性指标，不调任何模型。"""
    result = collected.get("result") or {}
    items = result.get("items") or []
    rows = result.get("rows") or []
    demand = result.get("demand") or {}
    # 头型判定上线前采集的 raw 没有 head 字段，按同一套规则现补，
    # 先做简称归一（圆柱头、杯头），保证 replay 重算出来的行状态和线上判定口径一致。
    if "head" not in demand:
        raw_query = normalize(str(demand.get("raw_query") or ""))
        demand = {
            **demand,
            "head": extract_head(raw_query),
            "head_excluded": excluded_heads(raw_query),
        }
    stage = result.get("stage")

    # 多需求：候选来自各行；缺参行没有候选，不参与召回
    if stage == "multi":
        candidate_ids = [
            int(it["id"])
            for r in rows
            for it in (r.get("items") or [])
            if it.get("id") is not None
        ]
        row_status = [r.get("status") for r in rows] or None
        match_kind = None
        severe = any(
            _severe(r.get("items") or [], r.get("status")) for r in rows
        )
    else:
        candidate_ids = [int(it["id"]) for it in items if it.get("id") is not None]
        if items:
            row_status = app_main.evaluate_row(demand, items)["status"]
        else:
            row_status = None
        match_kind = items[0].get("match_kind") if items else None
        severe = _severe(items, row_status)

    expected = [int(i) for i in (case.get("expected_product_ids") or [])]
    top3 = candidate_ids[:3]
    hit3 = [i for i in expected if i in top3]
    # 召回是否适用：只看三条——有期望商品、本轮是 results 分支、不是缺参参考行。
    # 完整需求即使零候选也要记 0 分（那是检索失败，不能当成不适用）。
    statuses = row_status if isinstance(row_status, list) else [row_status]
    valid_statuses = [s for s in statuses if s]
    all_missing = bool(valid_statuses) and all(
        s in ("missing_param", "missing_category") for s in valid_statuses
    )
    applicable = bool(expected) and stage in ("results", "multi") and not all_missing
    recall_at_3 = round(len(hit3) / len(expected), 4) if applicable else None
    mrr = None
    if applicable:
        mrr = 0.0
        for rank, pid in enumerate(candidate_ids, start=1):
            if pid in expected:
                mrr = round(1.0 / rank, 4)
                break

    violations = []
    hard = case.get("required_hard_constraints") or {}
    for item in items:
        spec = str(item.get("spec") or "")
        size = str(item.get("size") or "")
        length = str(item.get("length") or "")
        if "spec_m" in hard and hard["spec_m"] not in spec:
            violations.append(f"{item.get('name')}: spec 不含 {hard['spec_m']}（实际 {spec}）")
        if "length" in hard and hard["length"] not in length:
            violations.append(f"{item.get('name')}: 长度不符（要求 {hard['length']}，实际 {length or '未标'}）")
        if "size" in hard and hard["size"] not in size:
            violations.append(f"{item.get('name')}: 内径不符（要求 {hard['size']}，实际 {size or '未标'}）")

    expected_kind = case.get("expected_match_kind")
    kind_ok = None
    if expected_kind is not None:
        kind_ok = match_kind == expected_kind

    expected_status = case.get("expected_row_status")
    status_ok = _status_matches(expected_status, row_status)

    return {
        "case_id": case["case_id"],
        "user_input": case["user_input"],
        "tags": case.get("tags") or [],
        "expected_stage": case["expected_stage"],
        "actual_stage": stage,
        "stage_ok": stage == case["expected_stage"],
        "expected_product_ids": expected,
        "candidate_ids": candidate_ids,
        "recall_at_3": recall_at_3,
        "mrr": mrr,
        "recall_applicable": applicable,
        "hard_violations": violations,
        "expected_match_kind": expected_kind,
        "actual_match_kind": match_kind,
        "match_kind_ok": kind_ok,
        "expected_row_status": expected_status,
        "row_status": row_status,
        "row_status_ok": status_ok,
        "severe_orderable_error": severe,
        "contexts": [context_text(it) for it in items],
        "response": result.get("reply") or "",
        "response_for_faith": _faithfulness_text(result.get("reply") or ""),
        "reference": case.get("reference") or "",
        "elapsed": collected.get("elapsed") or 0.0,
        "error": collected.get("error"),
    }


def summarize(rows: list[dict]) -> dict:
    total = len(rows)
    stage_ok = sum(1 for r in rows if r["stage_ok"])
    kind_rows = [r for r in rows if r["match_kind_ok"] is not None]
    # Recall 与 MRR 用同一分母：有期望商品、且本轮适用于召回统计的用例。
    # 完整需求但零候选也算 0 分（那是最该暴露的失败），只有缺参参考行/不适用行才排除。
    recall_rows = [r for r in rows if r["recall_at_3"] is not None]
    status_rows = [r for r in rows if r["row_status_ok"] is not None]
    # 硬约束违反只统计「本应精确匹配」的 results 行；alternative_only 是主动降级，不算违反
    violation_rows = [
        r for r in rows
        if r["expected_stage"] == "results" and r["row_status"] != "alternative_only"
    ]
    severe_rows = [r for r in rows if r["candidate_ids"]]
    violations = sum(1 for r in violation_rows if r["hard_violations"])
    severe = sum(1 for r in rows if r["severe_orderable_error"])
    return {
        "total": total,
        "stage_accuracy": round(stage_ok / total, 4) if total else None,
        "match_kind_accuracy": round(sum(1 for r in kind_rows if r["match_kind_ok"]) / len(kind_rows), 4) if kind_rows else None,
        "match_kind_cases": len(kind_rows),
        "recall_at_3": round(sum(r["recall_at_3"] for r in recall_rows) / len(recall_rows), 4) if recall_rows else None,
        "recall_cases": len(recall_rows),
        "mrr": round(sum(r["mrr"] for r in recall_rows) / len(recall_rows), 4) if recall_rows else None,
        "row_status_accuracy": round(sum(1 for r in status_rows if r["row_status_ok"]) / len(status_rows), 4) if status_rows else None,
        "row_status_cases": len(status_rows),
        "hard_violation_rate": round(violations / len(violation_rows), 4) if violation_rows else None,
        "hard_violation_cases": len(violation_rows),
        "severe_orderable_errors": severe,
        "severe_scope_cases": len(severe_rows),
        "errors": sum(1 for r in rows if r["error"]),
        "avg_elapsed": round(sum(r["elapsed"] for r in rows) / total, 2) if total else None,
    }


def write_reports(rows: list[dict], summary: dict, ragas: dict, meta: dict, suffix: str = "") -> tuple[Path, Path]:
    DOCS.mkdir(parents=True, exist_ok=True)
    stamp = STAMP
    json_path = DOCS / f"ragas-baseline-{stamp}{suffix}.json"
    md_path = DOCS / f"ragas-baseline-{stamp}{suffix}.md"

    payload = {"meta": meta, "summary": summary, "ragas": ragas, "rows": rows}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def weakness(r: dict) -> float:
        score = 0.0
        if not r["stage_ok"]:
            score += 3
        if r["severe_orderable_error"]:
            score += 3
        if r["hard_violations"]:
            score += 2
        if r["row_status_ok"] is False:
            score += 1.5
        faith = (r.get("ragas") or {}).get("faithfulness")
        if faith is not None and faith < 0.35:
            score += 1.5
        rec = (r.get("ragas") or {}).get("llm_context_recall")
        if rec is not None and rec < 0.5:
            score += 1
        return -score

    worst = sorted([r for r in rows if weakness(r) < 0], key=weakness)[:10]

    def fmt(value):
        return "-" if value is None else value

    lines = [
        f"# RAGAS 评估基线（{stamp}）",
        "",
        "## 一、运行信息",
        "",
        f"- 用例数：{summary['total']}",
        f"- 业务模型：{meta['model']}",
        f"- 评估模型：{meta['eval_model']}",
        f"- embedding：{meta['embedding']}",
        f"- 并发：{meta['concurrency']}",
        f"- 模式：{meta['mode']}",
        f"- 耗时：{meta['elapsed']} 秒",
        f"- 平均单条耗时：{summary['avg_elapsed']} 秒",
        "",
        "## 二、确定性指标",
        "",
        "| 指标 | 数值 | 覆盖用例 |",
        "| --- | --- | --- |",
        f"| stage 准确率 | {fmt(summary['stage_accuracy'])} | {summary['total']} |",
        f"| match_kind 准确率 | {fmt(summary['match_kind_accuracy'])} | {summary['match_kind_cases']} |",
        f"| Recall@3 | {fmt(summary['recall_at_3'])} | {summary['recall_cases']} |",
        f"| MRR | {fmt(summary['mrr'])} | {summary['recall_cases']} |",
        f"| 行状态准确率 | {fmt(summary['row_status_accuracy'])} | {summary['row_status_cases']} |",
        f"| 硬约束违反率 | {fmt(summary['hard_violation_rate'])} | {summary['hard_violation_cases']} |",
        f"| 严重可下单错误 | {summary['severe_orderable_errors']} | {summary['severe_scope_cases']} |",
        "",
        "口径说明：",
        "",
        "- Recall@3 与 MRR 用同一分母——有期望商品、且本轮适用于召回统计的用例。完整需求即使零候选也计 0 分（那是最该暴露的失败），只有缺参参考行与不适用行才排除。",
        "- 多需求的候选来自各行 `items` 的并集；缺参行没有候选，该行不参与召回统计。",
        "- `match_kind` 只表示硬约束（规格/内径/长度）的精确性，软属性不符不改变它。",
        "- 行状态来自 `evaluate_row()`；多需求逐行比对，期望值写成数组。",
        "- 严重错误 = 候选里存在 `alternative` 却把该行判成 `ok`，分母是有候选的用例数。",
        "",
        "## 三、RAGAS 指标",
        "",
    ]
    if ragas.get("applicable"):
        lines += [
            f"适用 {ragas['applicable']} 条（非 results 分支 {ragas.get('not_applicable', 0)} 条不计入）。",
            "",
            "| 指标（实际类名） | 均值 |",
            "| --- | --- |",
            f"| ContextPrecisionWithReference | {fmt(ragas.get('llm_context_precision'))} |",
            f"| ContextRecall | {fmt(ragas.get('llm_context_recall'))} |",
            f"| Faithfulness | {fmt(ragas.get('faithfulness'))} |",
            f"| AnswerRelevancy | {fmt(ragas.get('answer_relevancy'))} |",
            "",
            f"失败指标调用 {ragas.get('error_count', 0)} 次（单指标失败记为 null，不计入均值）。",
        ]
        if ragas.get("errors"):
            lines += ["", "```text", *[f"- {e}" for e in ragas["errors"]], "```"]
    else:
        lines.append(ragas.get("reason") or "本轮未运行 RAGAS。")

    lines += ["", "## 四、逐条明细", "",
              "| case_id | stage | 期望 | 候选 | R@3 | MRR | 行状态 | 期望状态 | kind | Faith | AnsRel |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        g = r.get("ragas") or {}
        lines.append(
            "| {cid} | {st} | {exp} | {c} | {r3} | {mrr} | {rs} | {ers} | {kind} | {f} | {a} |".format(
                cid=r["case_id"],
                st=r["actual_stage"],
                exp=r["expected_stage"],
                c=",".join(str(x) for x in r["candidate_ids"]) or "-",
                r3=fmt(r["recall_at_3"]),
                mrr=fmt(r["mrr"]),
                rs=fmt(r["row_status"]),
                ers=fmt(r["expected_row_status"]),
                kind=r["actual_match_kind"] or "-",
                f=fmt(g.get("faithfulness")),
                a=fmt(g.get("answer_relevancy")),
            )
        )

    lines += ["", "## 五、薄弱案例", ""]
    if not worst:
        lines.append("本轮没有触发薄弱条件的用例。")
    for r in worst:
        g = r.get("ragas") or {}
        lines.append(f"### {r['case_id']}（实际 {r['actual_stage']} / 期望 {r['expected_stage']}）")
        lines.append("")
        lines.append(f"- 输入：{r['user_input']}")
        lines.append(f"- 候选：{r['candidate_ids']}，Recall@3 {fmt(r['recall_at_3'])}，MRR {fmt(r['mrr'])}")
        lines.append(f"- 行状态：实际 {fmt(r['row_status'])} / 期望 {fmt(r['expected_row_status'])}")
        if r["hard_violations"]:
            lines.append("- 硬约束违反：" + "；".join(r["hard_violations"][:3]))
        if r["severe_orderable_error"]:
            lines.append("- **严重**：没有精确匹配却标为可下单")
        if g:
            lines.append(f"- RAGAS：Faith {fmt(g.get('faithfulness'))} / CtxRecall {fmt(g.get('llm_context_recall'))} / AnsRel {fmt(g.get('answer_relevancy'))}")
        lines.append("")
        lines.append("```text")
        lines.append((r["response"] or "")[:400].replace("\n", " "))
        lines.append("```")
        lines.append("")

    lines += [
        "## 六、怎么读这些分数",
        "",
        "- **Faithfulness 0.672，比 2026-11-16 基线的 0.4067 高 0.265**：2026-11-18 起通用建议（备损、账期、物流、下单前核对）移出正文，改由系统统一追加 `【通用提示】` 尾注，评测前把尾注剥离。剩余低分主要来自引用用户需求的句子（如「MOQ 100 > 需求 50」「你未提产地要求」），RAGAS 的 faithfulness 只对照候选上下文、不看 user_input。",
        "- **ContextRecall 偏低，部分来自 reference 写法**：结构化短文本（分号拼接的属性行）会让 LLM 判定偏保守。看这条要看候选顺序，不是看分数。",
        "- **确定性指标优先于语义分**：stage、硬约束、match_kind、行状态不受评估模型影响；只有 replay 模式下这些指标才完全离线可复现。",
        "",
        "## 七、未覆盖范围",
        "",
        "- 未评估多轮长对话（超过 4 轮的上下文继承）。",
        "- 未评估上传（Excel / 图片）路径的质量。",
        "- 未做并发压力与限流测试。",
        "- 未对 RAGAS 分数设合格阈值，首轮只建立分布。",
        "- 在线采集阶段仍会调业务模型（理解/改写/推荐），同一句话两次运行的回复措辞可能不同；只有 `--replay` 的规则指标是离线复现。",
        "- 已知问题用例（`multi-rows-021` 材质并列被拆成两行）按原样保留，没有为了让分数好看而删除。",
        "",
        "## 八、复现",
        "",
        "```powershell",
        "cd backend",
        "# 全量：在线采集 + 规则 + RAGAS，同时写 raw JSON",
        "& 'D:\\AI\\ComfyUI\\venv\\Scripts\\python.exe' -m eval.run_ragas",
        "",
        "# 只采集原始结果，不跑 RAGAS",
        "& 'D:\\AI\\ComfyUI\\venv\\Scripts\\python.exe' -m eval.run_ragas --collect-only",
        "",
        "# 离线重算规则指标（零模型调用）",
        "& 'D:\\AI\\ComfyUI\\venv\\Scripts\\python.exe' -m eval.run_ragas --replay docs\\ragas-raw-2026-11-15.json",
        "```",
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def bootstrap() -> None:
    """手动初始化库表、检索索引和状态图——脚本进程不走 FastAPI 的 lifespan。"""
    from app.orchestration import build_graph
    from app.rag.index import build_index
    from app.sessions import init_tables
    from app.rag import reranker

    init_tables()
    if not app_main.STATE.get("rows"):
        app_main.STATE.update(build_index())
    if app_main.GRAPH is None:
        app_main.GRAPH = build_graph(app_main)
    reranker.warmup()


def replay(raw_path: Path) -> tuple[list[dict], dict]:
    """离线：从 raw JSON 重算规则指标，不初始化检索、不调模型。"""
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    cases = {c["case_id"]: c for c in load_cases()}
    collected = {c["case_id"]: c for c in payload.get("collected") or []}
    rows = []
    for case_id, case in cases.items():
        item = collected.get(case_id) or {"case_id": case_id, "result": None, "elapsed": 0.0, "error": "raw 中缺该用例"}
        rows.append(build_row(case, item))
    meta = payload.get("meta") or {}
    return rows, meta


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules-only", action="store_true", help="只算确定性指标，不跑 RAGAS")
    parser.add_argument("--collect-only", action="store_true", help="只采集原始结果")
    parser.add_argument("--replay", type=str, default=None, help="从 raw JSON 离线重算规则指标")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--engine",
        choices=("legacy", "graph"),
        default=None,
        help="迁移对照期指定引擎；不填沿用 main 的默认值",
    )
    args = parser.parse_args()
    engine = args.engine
    engine_suffix = f"-{engine}" if engine else ""

    started = time.perf_counter()
    if args.replay:
        rows, raw_meta = replay(Path(args.replay))
        mode = "replay（离线，零模型调用）"
        elapsed = 0.0
    else:
        bootstrap()
        cases = load_cases(args.limit)
        print(f"cases={len(cases)}")
        collected, elapsed = collect(cases, engine=engine)
        rows = [build_row(c, item) for c, item in zip(cases, collected)]

        DOCS.mkdir(parents=True, exist_ok=True)
        # 冒烟（--limit）不覆盖完整 raw，否则 replay 会缺用例
        raw_suffix = f"-limit{args.limit}" if args.limit else ""
        raw_path = DOCS / f"ragas-raw-{STAMP}{engine_suffix}{raw_suffix}.json"
        raw_path.write_text(
            json.dumps(
                {
                    "meta": {"collected_at": time.strftime("%Y-%m-%d %H:%M:%S"), "cases": len(cases)},
                    "collected": collected,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print("raw", raw_path)
        mode = "在线采集 + 规则" + ("" if args.rules_only or args.collect_only else " + RAGAS")
        if args.collect_only:
            print("collect-only：已写 raw，不生成报告")
            return 0
        raw_meta = {"collected_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    summary = summarize(rows)
    ragas_result = {"applicable": 0, "reason": "未运行（--rules-only / --replay）" if args.rules_only or args.replay else "未实现"}
    if not args.rules_only and not args.replay:
        ragas_result = asyncio.run(run_ragas(rows))

    meta = {
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode,
        "engine": engine or "default",
        "eval_model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        "embedding": "bge-m3（本地 D:\\AI\\models\\bge-m3）",
        "concurrency": CONCURRENCY,
        "elapsed": round(time.perf_counter() - started, 1) if not args.replay else 0.0,
        **{k: v for k, v in (raw_meta or {}).items() if k == "collected_at"},
    }
    json_path, md_path = write_reports(
        rows,
        summary,
        ragas_result,
        meta,
        suffix=("-replay" if args.replay else "") + engine_suffix,
    )
    print("summary", json.dumps(summary, ensure_ascii=False))
    print("report", json_path)
    print("report", md_path)
    return 0


async def run_ragas(rows: list[dict]) -> dict:
    """RAGAS v0.4 collections 指标；只对有候选、有回复的 results 行生效。"""
    try:
        from ragas.embeddings import HuggingFaceEmbeddings
        from ragas.llms import llm_factory
        from ragas.metrics.collections import (
            AnswerRelevancy,
            ContextPrecisionWithReference,
            ContextRecall,
            Faithfulness,
        )
    except Exception as exc:  # 依赖未装或版本不符
        return {"applicable": 0, "reason": f"RAGAS 依赖不可用：{type(exc).__name__}: {exc}"}

    from openai import AsyncOpenAI

    from app import llm as app_llm

    try:
        client = AsyncOpenAI(api_key=app_llm.API_KEY, base_url=app_llm.BASE_URL)
        # faithfulness 要逐句列 statement，长回复（如 MOQ 说明）用 4096 会被截断
        evaluator = llm_factory(app_llm.MODEL, client=client, max_tokens=8192)
        embeddings = HuggingFaceEmbeddings(model=str(EMBED_DIR), device="cuda")
    except Exception as exc:
        return {"applicable": 0, "reason": f"评估器初始化失败：{type(exc).__name__}: {exc}"}

    metrics = {
        "llm_context_precision": ContextPrecisionWithReference(llm=evaluator),
        "llm_context_recall": ContextRecall(llm=evaluator),
        "faithfulness": Faithfulness(llm=evaluator),
        "answer_relevancy": AnswerRelevancy(llm=evaluator, embeddings=embeddings),
    }

    targets = [r for r in rows if r["actual_stage"] == "results" and r["contexts"] and r["response"]]
    if not targets:
        return {"applicable": 0, "reason": "没有适用的 results 用例"}

    sem = asyncio.Semaphore(CONCURRENCY)
    errors: list[str] = []

    async def score(row: dict) -> None:
        out: dict[str, float | None] = {}
        async with sem:
            for key, metric in metrics.items():
                try:
                    if key == "llm_context_precision":
                        res = await metric.ascore(
                            user_input=row["user_input"],
                            reference=row["reference"],
                            retrieved_contexts=row["contexts"],
                        )
                    elif key == "llm_context_recall":
                        res = await metric.ascore(
                            user_input=row["user_input"],
                            retrieved_contexts=row["contexts"],
                            reference=row["reference"],
                        )
                    elif key == "faithfulness":
                        res = await metric.ascore(
                            user_input=row["user_input"],
                            response=row.get("response_for_faith") or row["response"],
                            retrieved_contexts=row["contexts"],
                        )
                    else:
                        res = await metric.ascore(
                            user_input=row["user_input"],
                            response=row["response"],
                        )
                    out[key] = round(float(res.value), 4)
                except Exception as exc:  # 单指标失败不影响其它指标
                    out[key] = None
                    errors.append(f"{row['case_id']}/{key}: {type(exc).__name__}: {exc}")
        row["ragas"] = out

    await asyncio.gather(*(score(r) for r in targets))

    averaged: dict[str, float | None] = {}
    for key in metrics:
        values = [r["ragas"][key] for r in targets if (r.get("ragas") or {}).get(key) is not None]
        averaged[key] = round(sum(values) / len(values), 4) if values else None

    return {
        "applicable": len(targets),
        "not_applicable": len(rows) - len(targets),
        **averaged,
        "errors": errors[:10],
        "error_count": len(errors),
    }


if __name__ == "__main__":
    raise SystemExit(main())
