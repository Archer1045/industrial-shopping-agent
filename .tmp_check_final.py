# -*- coding: utf-8 -*-
"""最终回归：单轮 + 小写 m8 + 元对话插话。"""
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8100/api/chat"


def ask(q, history=None):
    if history is None:
        return requests.get(BASE, params={"q": q}, timeout=180).json()
    return requests.post(BASE, json={"q": q, "history": history}, timeout=180).json()


def brief(d):
    demand = d.get("demand") or {}
    return "stage=%s category=%s spec=%s size=%s qty=%s" % (
        d.get("stage"),
        demand.get("category"),
        (demand.get("params") or {}).get("spec_m"),
        (demand.get("params") or {}).get("size"),
        demand.get("quantity"),
    )


print("== 单轮 ==")
d1 = ask("304 不锈钢 M8×30 内六角螺丝，要 1000 个")
print("单轮", brief(d1), "items=%d" % len(d1.get("items") or []))

print("== 组 8：小写 m8 + 元对话 ==")
d2 = ask("我要买螺丝")
print("1 我要买螺丝 ->", brief(d2), "|", d2["reply"][:40])

h1 = [
    {"role": "user", "content": "我要买螺丝"},
    {"role": "assistant", "content": d2["reply"]},
]
d3 = ask("m8", h1)
print("2 m8 ->", brief(d3), "|", d3["reply"][:40])

h2 = h1 + [
    {"role": "user", "content": "m8"},
    {"role": "assistant", "content": d3["reply"]},
]
d3b = ask("30mm", h2)
print("2b 30mm ->", brief(d3b), "| items=%d" % len(d3b.get("items") or []))

h3 = h2 + [
    {"role": "user", "content": "30mm"},
    {"role": "assistant", "content": d3b["reply"]},
]
d4 = ask("问题一个一个来，我都不知道要回哪个了", h3)
print("3 元对话 ->", brief(d4), "|", d4["reply"][:50])

print("== 判定 ==")
ok = (
    d1.get("stage") == "results"
    and d2.get("stage") == "clarify"
    and d3.get("stage") == "clarify"
    and (d3.get("demand") or {}).get("params", {}).get("spec_m") == "M8"
    and d3b.get("stage") == "results"
    and (d3b.get("demand") or {}).get("params", {}).get("length") == "30mm"
    and not (d4.get("stage") == "clarify" and not (d4.get("demand") or {}).get("category"))
)
print("ALL PASS" if ok else "FAILED")
