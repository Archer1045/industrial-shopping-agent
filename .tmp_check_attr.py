"""验证：明确的软属性没被满足时，是否如实标注，而不是写成可下单。"""
import json
import requests

BASE = "http://127.0.0.1:8100"


def ask(q: str) -> dict:
    return requests.post(f"{BASE}/api/chat", json={"q": q}, timeout=120).json()


def show(title: str, data: dict) -> None:
    print("=" * 70)
    print(title, "->", data.get("stage"))
    if data.get("rows"):
        for row in data["rows"]:
            first = row["items"][0]["name"] if row["items"] else "-"
            print(f"  行{row['row_no']}: {row['query']} | {first} | {row['note']}")
    print("  回复:", (data.get("reply") or "")[:220].replace("\n", " "))


show("进口轴承 25mm, 30mm", ask("进口轴承 25mm, 30mm"))
show("进口的 6204 轴承", ask("进口的 6204 轴承"))
show("德国轴承 6204", ask("德国轴承 6204"))
show("304 不锈钢 M8×30 螺丝 1000 个", ask("304 不锈钢 M8×30 螺丝，1000 个"))
show("镀锌 M8×30 螺丝 1000 个", ask("镀锌 M8×30 螺丝 1000 个"))
