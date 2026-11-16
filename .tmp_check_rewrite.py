"""验证 query 改写：同义词归一、LLM 改写效果、单轮与多轮回归。"""
import sys

import requests

sys.path.insert(0, r"D:\workSpace\code\industrial-shopping-agent\backend")
sys.stdout.reconfigure(encoding="utf-8")

from app.demand import normalize, parse_demand  # noqa: E402

BASE = "http://127.0.0.1:8100"


def ask(q, history=None):
    if history is None:
        d = requests.get(BASE + "/api/chat", params={"q": q}, timeout=120).json()
    else:
        d = requests.post(BASE + "/api/chat", json={"q": q, "history": history}, timeout=120).json()
    items = d.get("items") or []
    first = items[0]["name"] if items else "-"
    rw = (d.get("rewritten") or "-")[:46]
    print(f"[{d['stage']}] {q} | rw={rw} | n={len(items)} | first={first}")
    if d["stage"] in ("chat", "out_of_scope", "clarify"):
        print(f"    reply: {(d.get('reply') or '').replace(chr(10), ' ')[:70]}")
    return d


def run_turns(queries):
    history = []
    for q in queries:
        d = ask(q, history or None)
        history.append({"role": "user", "content": q})
        history.append({"role": "assistant", "content": (d.get("reply") or "")[:200]})


print("== 1. 同义词归一（规则层）==")
for s in ["杯头 M8×30 螺丝 1000 个", "空开 16A", "球轴承 内径 20 的 50 个", "电源模块 24V 10 个", "罗丝 M8"]:
    d = parse_demand(s)
    print(
        f"  {s} -> cat={d['category']} mat={d['material']} params={d['params']} "
        f"qty={d['quantity']} missing={d['missing']}"
    )

print("\n== 2. 别称端到端 ==")
for q in ["杯头 M8×30 螺丝 1000 个", "空开 16A", "球轴承 内径 20 的 50 个", "24V 电源模块 10 个"]:
    ask(q)

print("\n== 3. 单轮回归 10 条 ==")
for q in [
    "304 不锈钢 M8×30 内六角螺丝，要 1000 个",
    "我要买螺丝",
    "内径 20 的轴承要 50 个",
    "要能耐高温的轴承",
    "24V 开关电源 10 个",
    "断路器 16A",
    "碳钢镀锌 M8×30 外六角螺栓 2000 个",
    "交流接触器 220V",
    "今天天气怎么样",
    "螺丝和螺栓有什么区别",
]:
    ask(q)

print("\n== 4. 多轮 ==")
print("-- 补充规格")
run_turns(["我要买螺丝", "M8 的，1000 个"])
print("-- 改数量、换规格")
run_turns(["304 不锈钢 M8 螺丝 1000 个", "要 2000 个", "换成 M10 的，2000 个"])
print("-- 库外转库内")
run_turns(["我想买个扳手", "那轴承呢"])
print("-- 闲聊转采购")
run_turns(["今天天气不错", "我要买螺丝"])
print("-- 选项与库外")
run_turns(["开口扳手", "可以给我一些选项吗"])
