"""意图判断 + 三段提示词验证（临时脚本）。"""
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8100"

CASES = [
    ("304 不锈钢 M8 螺丝，长度 30mm，1000 个", "results"),
    ("我要买螺丝", "clarify"),
    ("内径 20 的轴承要 50 个", "results"),
    ("24V 开关电源 10 个", "results"),
    ("断路器 16A", "results"),
    ("今天天气怎么样", "chat"),
    ("你好", "chat"),
    ("讲个笑话", "chat"),
    ("螺丝是什么", "chat"),
    ("帮我写个周报", "chat"),
]

ok = 0
for q, expect in CASES:
    try:
        r = requests.get(f"{BASE}/api/chat", params={"q": q}, timeout=120)
        d = r.json()
    except Exception as exc:
        print(f"[ERROR] {q} -> {exc}")
        continue
    hit = "OK " if d.get("stage") == expect else "MISS"
    if hit == "OK ":
        ok += 1
    print(f"{hit} | 期望 {expect:7s} 实际 {d.get('stage'):7s} | items {len(d.get('items', [])):2d} | {q}")
    print(f"      {d.get('reply', '')[:110]}")

print(f"\n{ok}/{len(CASES)} 通过")
