import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

r = requests.get(
    "http://127.0.0.1:8100/api/chat",
    params={"q": "304 不锈钢 M8 螺丝，长度 30mm，要 1000 个"},
    timeout=120,
)
data = r.json()
print("source:", data["source"])
print("items:", len(data["items"]))
print("---")
print(data["reply"])
