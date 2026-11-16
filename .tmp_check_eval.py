"""RAGAS 复评口径的断言测试（revision 3）。

不联网、不调模型，只验证 build_row / summarize 的指标口径。
"""
import sys
from pathlib import Path

BACKEND = Path(r"D:\workSpace\code\industrial-shopping-agent\backend")
sys.path.insert(0, str(BACKEND))

from eval.run_ragas import build_row, summarize  # noqa: E402

FAILED = []


def check(name: str, got, want) -> None:
    ok = got == want
    print(("  ok  " if ok else "  FAIL") + f" {name}: got={got!r} want={want!r}")
    if not ok:
        FAILED.append(name)


def case(case_id: str, **kw) -> dict:
    base = {
        "case_id": case_id,
        "user_input": "x",
        "expected_stage": "results",
        "expected_product_ids": [],
        "expected_row_status": None,
        "required_hard_constraints": {},
    }
    base.update(kw)
    return base


def collected(items=None, rows=None, stage="results", demand=None, reply="r") -> dict:
    return {
        "case_id": "x",
        "result": {"stage": stage, "items": items or [], "rows": rows or [], "demand": demand or {}, "reply": reply},
        "elapsed": 1.0,
        "error": None,
    }


def item(pid: int, kind: str = "exact", spec: str = "M8x30mm", size: str = "", length: str = "30mm") -> dict:
    return {"id": pid, "name": f"p{pid}", "spec": spec, "size": size, "length": length, "match_kind": kind}


print("[1] MRR 与 Recall 同分母，0 分也计入")
full_demand = {"category": "紧固件", "missing": [], "out_of_scope": []}
hit = build_row(case("a", expected_product_ids=[1]),
                collected(items=[item(1), item(2)], demand=full_demand))
miss = build_row(case("b", expected_product_ids=[9]),
                 collected(items=[item(1), item(2)], demand=full_demand))
check("hit.recall", hit["recall_at_3"], 1.0)
check("hit.mrr", hit["mrr"], 1.0)
check("miss.recall", miss["recall_at_3"], 0.0)
check("miss.mrr", miss["mrr"], 0.0)
s = summarize([hit, miss])
check("mean recall", s["recall_at_3"], 0.5)
check("mean mrr", s["mrr"], 0.5)
check("recall cases", s["recall_cases"], 2)

print("[2] 多需求候选来自各行 items，缺参行不参与召回")
multi_rows = [
    {"row_no": 1, "status": "ok", "items": [item(91)]},
    {"row_no": 2, "status": "missing_param", "items": []},
]
row = build_row(case("m", expected_stage="multi", expected_product_ids=[91]),
                collected(rows=multi_rows, stage="multi"))
check("multi candidate ids", row["candidate_ids"], [91])
check("multi recall", row["recall_at_3"], 1.0)
check("multi row status", row["row_status"], ["ok", "missing_param"])

print("[3] 零候选的完整需求记 0 分（不是不适用）")
empty = build_row(case("e", expected_product_ids=[91]), collected(items=[]))
check("empty recall is 0", empty["recall_at_3"], 0.0)
check("empty mrr is 0", empty["mrr"], 0.0)
check("empty applicable", empty["recall_applicable"], True)

print("[4] 无状态（clarify 阶段）不被当成缺参")
clarify = build_row(case("c", expected_stage="clarify", expected_product_ids=[]),
                    collected(items=[], stage="clarify", reply="请问螺纹规格"))
check("clarify recall None", clarify["recall_at_3"], None)
check("clarify all_missing False", clarify["recall_applicable"], False)

print("[5] match_kind 只看硬约束，软属性不影响")
exact = build_row(case("k", expected_match_kind="exact"), collected(items=[item(1, "exact")]))
check("kind ok", exact["match_kind_ok"], True)

print("[6] 行状态比对：单值 / 多行 / not_applicable")
ok_status = build_row(case("s1", expected_row_status="ok"),
                      collected(items=[item(1)], demand={"category": "紧固件"}))
check("status single", ok_status["row_status_ok"], True)
na = build_row(case("s2", expected_row_status="not_applicable"), collected(items=[], stage="chat", reply="hi"))
check("status not_applicable", na["row_status_ok"], True)
list_status = build_row(case("s3", expected_row_status=["ok", "missing_param"]),
                        collected(rows=multi_rows, stage="multi"))
check("status list", list_status["row_status_ok"], True)
list_bad = build_row(case("s4", expected_row_status="ok"),
                     collected(rows=multi_rows, stage="multi"))
check("status list vs single", list_bad["row_status_ok"], False)

print("[7] severe：替代结果被判成 ok")
sev = build_row(case("v", expected_stage="results"),
                collected(items=[item(1, "alternative")], demand={"category": "紧固件"}))
check("severe false when not ok", sev["severe_orderable_error"], False)

print()
if FAILED:
    print("FAILED:", FAILED)
    raise SystemExit(1)
print("ALL PASS")
