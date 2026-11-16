import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8100"


def new_session() -> str:
    return requests.post(f"{BASE}/api/sessions", timeout=30).json()["id"]


def ask(sid: str, q: str) -> dict:
    return requests.post(f"{BASE}/api/chat", json={"q": q, "session_id": sid}, timeout=180).json()


def show(tag: str, data: dict) -> None:
    print("-" * 50)
    print(tag, "->", data.get("stage"))
    print("reply:", (data.get("reply") or "").replace("\n", " ")[:120])
    for row in data.get("rows") or []:
        print(f"  行{row['row_no']}: {row['query']} | {(row.get('names') or ['-'])[0]} | {row['note']}")
    for item in data.get("items") or []:
        print("  商品:", item["name"])


if __name__ == "__main__":
    sid = new_session()
    print("会话:", sid)
    show("1 我要买螺丝", ask(sid, "我要买螺丝"))
    show("2 M8 和 M10 各要 1000 个（有上文）", ask(sid, "M8 和 M10 各要 1000 个"))
    show("3 那再加个轴承，内径 20 的 50 个", ask(sid, "那再加个轴承，内径 20 的 50 个"))
