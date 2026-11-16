"""库外品类与回归验证（临时脚本）。"""
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8100"

SCOPE_CASES = [
    "我想买个扳手",
    "开口扳手",
    "工具",
    "可以给我一些选项吗",
    "我要买螺丝",
]

REGRESSION = [
    "304 不锈钢 M8×30 内六角螺丝，要 1000 个",
    "内径 20 的轴承要 50 个",
    "24V 开关电源 10 个",
    "断路器 16A",
    "今天天气怎么样",
    "螺丝和螺栓有什么区别",
]


def run(title: str, cases: list[str]) -> None:
    print(f"===== {title} =====")
    for q in cases:
        d = requests.get(f"{BASE}/api/chat", params={"q": q}, timeout=120).json()
        reply = d.get("reply", "").replace("\n", " ")
        print(f"[{d.get('stage')}] {q}")
        print(f"    {reply[:110]}")
    print()


run("库外品类 / 选项", SCOPE_CASES)
run("回归", REGRESSION)
