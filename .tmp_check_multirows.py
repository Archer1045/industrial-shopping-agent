import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

API = "http://127.0.0.1:8100/api/chat"


def ask(q: str, history=None) -> dict:
    payload = {"q": q, "history": history or []}
    return requests.post(API, json=payload, timeout=180).json()


def show(title: str, data: dict) -> None:
    print("=" * 60)
    print(title, "->", data.get("stage"))
    print("reply:", (data.get("reply") or "").replace("\n", " ")[:160])
    for row in data.get("rows") or []:
        names = " / ".join(row.get("names") or []) or "-"
        print(f"  行{row['row_no']}: {row['query']} | {names} | {row['note']}")
    for item in data.get("items") or []:
        print("  商品:", item["name"], item["price"], item["moq"])


if __name__ == "__main__":
    show("A. M8 和 M10 各要 1000 个", ask("M8 和 M10 各要 1000 个"))
    show("B. M8, M10 螺丝", ask("M8, M10 螺丝"))
    show("C. 304 和 316 的 M8 螺丝（不该切）", ask("304 和 316 的 M8 螺丝 1000 个"))
    show("D. 螺丝和轴承各要一点", ask("螺丝和轴承都要买，螺丝 M8 的 1000 个，轴承内径 20 的 50 个"))
    show("E. 单需求完整", ask("304 不锈钢 M8 螺丝，长度 30mm，1000 个"))
    show("F. 缺参追问", ask("我要买螺丝"))
