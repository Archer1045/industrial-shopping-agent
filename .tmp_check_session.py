"""会话持久化接口自测：新建、多轮、读详情、列表、删除、老接口兼容。"""
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")
B = "http://127.0.0.1:8100"

s = requests.post(f"{B}/api/sessions", timeout=30).json()
sid = s["id"]
print("新建会话:", sid, "|", s["title"])

r1 = requests.post(f"{B}/api/chat", json={"q": "我要买螺丝", "session_id": sid}, timeout=180).json()
print("第1轮:", r1["stage"], "|", r1["reply"][:40].replace("\n", " "))

r2 = requests.post(f"{B}/api/chat", json={"q": "M8 的，1000 个", "session_id": sid}, timeout=180).json()
print("第2轮:", r2["stage"], "|", r2["items"][0]["name"] if r2["items"] else "-")

d = requests.get(f"{B}/api/sessions/{sid}", timeout=30).json()
print("会话标题:", d["title"], "| 消息数:", len(d["messages"]))
for m in d["messages"]:
    print("  ", m["role"], m["text"][:36].replace("\n", " "), "payload:", list((m["payload"] or {}).keys()))

lst = requests.get(f"{B}/api/sessions", timeout=30).json()
print("会话列表:", len(lst), "条 | 首条:", lst[0]["title"], "| count:", lst[0]["count"])

old = requests.get(f"{B}/api/chat", params={"q": "内径 20 的轴承要 50 个"}, timeout=180).json()
print("老接口(无 session):", old["stage"])

requests.delete(f"{B}/api/sessions/{sid}", timeout=30)
print("删除后列表:", len(requests.get(f"{B}/api/sessions", timeout=30).json()), "条")
