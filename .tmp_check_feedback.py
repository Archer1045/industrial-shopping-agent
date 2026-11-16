import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

base = "http://127.0.0.1:8100"

sid = requests.post(base + "/api/sessions", timeout=30).json()["id"]
print("session:", sid)

chat = requests.post(
    base + "/api/chat",
    json={"q": "304 不锈钢 M8 螺丝，长度 30mm，1000 个", "session_id": sid},
    timeout=180,
).json()
mid = chat.get("message_id")
print("chat:", chat["stage"], "message_id:", mid)

r1 = requests.post(base + "/api/feedback", json={"message_id": mid, "rating": "up"}, timeout=30)
print("up:", r1.status_code, r1.json())

r2 = requests.post(base + "/api/feedback", json={"message_id": mid, "rating": "down"}, timeout=30)
print("改为 down:", r2.status_code, r2.json())

bad = requests.post(base + "/api/feedback", json={"message_id": mid, "rating": "meh"}, timeout=30)
print("非法 rating:", bad.status_code)

missing = requests.post(base + "/api/feedback", json={"message_id": 999999, "rating": "up"}, timeout=30)
print("不存在的消息:", missing.status_code)

detail = requests.get(base + "/api/sessions/" + sid, timeout=30).json()
print("详情里最后一条 rating:", detail["messages"][-1]["rating"], "| id:", detail["messages"][-1]["id"])

stats = requests.get(base + "/api/feedback/stats", timeout=30).json()
print("stats:", stats)
