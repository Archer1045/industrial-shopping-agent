"""10 条演示问句实测（临时脚本）。"""
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8100"

CASES = [
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
]

for i, q in enumerate(CASES, 1):
    try:
        d = requests.get(f"{BASE}/api/chat", params={"q": q}, timeout=120).json()
    except Exception as exc:
        print(f"[{i:02d}] ERROR {q}: {exc}")
        continue
    names = " / ".join(p["name"] for p in d.get("items", [])[:3])
    print(f"[{i:02d}] {q}")
    print(f"     stage={d.get('stage')} source={d.get('source')} items={len(d.get('items', []))}")
    print(f"     reply: {d.get('reply', '').replace(chr(10), ' ')[:150]}")
    if names:
        print(f"     命中: {names}")
    print()
