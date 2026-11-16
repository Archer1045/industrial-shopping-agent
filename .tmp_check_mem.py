"""验证记忆修复：小写 m8 / 元对话继承上下文 / 澄清只问一个。"""
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8100/api/chat"


def ask(q, history=None):
    return requests.post(BASE, json={"q": q, "history": history or []}, timeout=120).json()


def show(label, d, extra=""):
    items = d.get("items") or []
    names = ", ".join(i["name"][:20] for i in items[:2])
    print(f"[{d['stage']:12s}] {label}")
    print("   reply:", d["reply"].replace("\n", " ")[:110])
    if names:
        print("   items:", names, extra)
    print()


U = lambda t: {"role": "user", "content": t}
A = lambda t: {"role": "assistant", "content": t}

# 1 单轮：缺规格，应该只问一个问题
show("我要买螺丝", ask("我要买螺丝"))

# 2 小写 m8 补充：修复后应直接出清单
h = [U("我要买螺丝"), A("你要买哪种螺纹规格的螺丝，比如 M8？")]
d = ask("m8", h)
show("m8（history: 我要买螺丝）", d, f"spec_m={d['demand']['params'].get('spec_m')}")

# 3 元对话：不应重问品类
h3 = [
    U("我要买螺丝"),
    A("你要买哪种螺纹规格的螺丝，比如 M8？"),
    U("m8"),
    A("长度多少？"),
]
d = ask("问题一个一个来，我都不知道要回哪个了", h3)
show("问题一个一个来（history 含 m8）", d)

# 4 换话题：当前句有品类，不继承历史
h4 = [U("我要买螺丝"), A("要哪种规格？")]
d = ask("内径 20 的轴承要 50 个", h4)
show("内径 20 的轴承要 50 个（history 是螺丝）", d, f"category={d['demand']['category']}")

# 5 库外品类不继承
d = ask("我要买扳手", h4)
show("我要买扳手（history 是螺丝）", d)

# 6 原有补充句合并仍正常
d = ask("M8 的，1000 个", h4)
show("M8 的，1000 个", d, f"qty={d['demand']['quantity']}")

# 7 单轮完整需求回归
d = ask("304 不锈钢 M8 螺丝，长度 30mm，1000 个")
show("304 不锈钢 M8x30 1000 个", d, f"qty={d['demand']['quantity']}")
