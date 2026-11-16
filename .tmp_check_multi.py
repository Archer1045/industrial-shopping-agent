"""多轮上下文验证（临时脚本）。"""
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8100"


def chat(q: str, history: list) -> dict:
    return requests.post(
        f"{BASE}/api/chat", json={"q": q, "history": history}, timeout=180
    ).json()


def show(tag: str, d: dict) -> None:
    reply = (d.get("reply") or "").replace("\n", " ")
    print(f"[{d.get('stage')}] {tag}")
    print(f"    {reply[:110]}")
    if d.get("items"):
        print(f"    items={len(d['items'])} 首个={d['items'][0]['name']}")
    demand = d.get("demand") or {}
    if demand:
        print(f"    category={demand.get('category')} qty={demand.get('quantity')} missing={demand.get('missing')}")


def turn(prev_q: str, prev_reply: str, q: str, tag: str) -> dict:
    history = [
        {"role": "user", "content": prev_q},
        {"role": "assistant", "content": prev_reply[:200]},
    ]
    d = chat(q, history)
    show(tag, d)
    return d


print("===== 1. 螺丝缺规格 → 补 M8 和数量 =====")
d = chat("我要买螺丝", [])
show("我要买螺丝", d)
d = turn("我要买螺丝", d["reply"], "M8 的，1000 个", "M8 的，1000 个")
print()

print("===== 2. 完整需求 → 只补数量 =====")
d = chat("304 不锈钢 M8 螺丝 1000 个", [])
show("304 不锈钢 M8 螺丝 1000 个", d)
d = turn("304 不锈钢 M8 螺丝 1000 个", d["reply"], "要 2000 个", "要 2000 个")
print()

print("===== 3. 库外扳手 → 换轴承 =====")
d = chat("我想买个扳手", [])
show("我想买个扳手", d)
d = turn("我想买个扳手", d["reply"], "那轴承呢", "那轴承呢")
print()

print("===== 4. 闲聊 → 转采购 =====")
d = chat("今天天气怎么样", [])
show("今天天气怎么样", d)
d = turn("今天天气怎么样", d["reply"], "我要买螺丝", "我要买螺丝")
print()

print("===== 5. 追问后再回一句「对」 =====")
d = chat("我要买螺丝", [])
show("我要买螺丝", d)
d = turn("我要买螺丝", d["reply"], "对", "对")
print()

print("===== 6. 上一轮说扳手，这轮说开口扳手 =====")
d = chat("我想买个扳手", [])
show("我想买个扳手", d)
d = turn("我想买个扳手", d["reply"], "开口扳手", "开口扳手")
print()

print("===== 7. 上一轮问轴承，这轮问有什么选项 =====")
d = chat("内径 20 的轴承要 50 个", [])
show("内径 20 的轴承要 50 个", d)
d = turn("内径 20 的轴承要 50 个", d["reply"], "可以给我一些选项吗", "可以给我一些选项吗")
