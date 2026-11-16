"""八维度扩充验收：工艺 / 产地 / 行业 / 型号 能不能影响推荐。"""
import json
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")
API = "http://127.0.0.1:8100"


def ask(q, history=None):
    body = {"q": q, "history": history or []}
    r = requests.post(f"{API}/api/chat", json=body, timeout=180).json()
    return r


def show(title, r, n=3):
    print(f"\n=== {title} ===")
    print("stage:", r.get("stage"))
    print("reply:", (r.get("reply") or "").replace("\n", " ")[:90])
    items = r.get("items") or []
    if r.get("rows"):
        for row in r["rows"]:
            names = "、".join(i["name"] for i in (row.get("items") or [])[:2]) or row.get("note")
            print(f"  row{row['row_no']}: {row['query'][:28]} -> {names}")
    for it in items[:n]:
        print(f"  - {it['name']} | 工艺 {it.get('process')} | 产地 {it.get('origin')} | 行业 {it.get('industry')} | 型号 {it.get('model')}")
    if not items and not r.get("rows"):
        print("  options:", r.get("options"))
    return r


show("1 苏州产的内六角螺丝 M8×30 1000 个", ask("苏州产的内六角螺丝，M8×30，要 1000 个"))
show("2 镀锌的 M8 螺丝 1000 个", ask("镀锌的 M8 螺丝，1000 个"))
show("3 机床用的轴承 内径 20 要 50 个", ask("机床用的轴承，内径 20，要 50 个"))
show("4 型号 6204-2RS 的轴承", ask("6204-2RS 轴承要 100 个"))
show("5 食品机械用的 304 螺丝 M8×30", ask("食品机械用的 304 螺丝 M8×30，500 个"))
show("6 回归：304 不锈钢 M8 螺丝 长度 30mm 1000 个", ask("304 不锈钢 M8 螺丝，长度 30mm，1000 个"))
print("\n--- 多轮 ---")
h1 = ask("我想买螺丝")
print("轮1:", h1.get("stage"), h1.get("reply", "")[:40])
h = [{"role": "user", "content": "我想买螺丝"}, {"role": "assistant", "content": h1.get("reply", "")}]
r2 = ask("M8 的，1000 个，要镀锌的", h)
show("7 多轮继承 + 补工艺", r2)
