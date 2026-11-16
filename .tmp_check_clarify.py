"""验证缺参追问顺序与多轮参数继承。"""
import io
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8100"


def post(q: str, session_id: str | None = None) -> dict:
    body = {"q": q}
    if session_id:
        body["session_id"] = session_id
    return requests.post(f"{BASE}/api/chat", json=body, timeout=120).json()


def show(tag: str, data: dict) -> None:
    names = [item.get("name", "") for item in data.get("items") or []]
    reply = (data.get("reply") or "").replace("\n", " ")[:70]
    print(f"  [{data.get('stage')}] {reply}")
    if names:
        print(f"    首位: {names[0]}")


print("=== 场景：我要买螺丝 -> 对，m8 -> 要50mm的 ===")
sid = requests.post(f"{BASE}/api/sessions", timeout=30).json()["id"]
for q in ["我要买螺丝", "对，m8", "要50mm的"]:
    print(f"[用户] {q}")
    show(q, post(q, sid))

print("\n=== 回归：单轮完整需求 ===")
show("", post("304 不锈钢 M8 螺丝，长度 30mm，1000 个"))

print("\n=== 回归：轴承 ===")
show("", post("内径 20 的轴承要 50 个"))

print("\n=== 回归：库外 ===")
show("", post("我要买扳手"))
