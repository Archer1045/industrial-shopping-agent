"""真实 HTTP 流式（切换后只剩状态图一条路径）。"""
import json
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8100"
QUERY = "304 不锈钢 M8 螺丝，长度 30mm，1000 个"

resp = requests.post(f"{BASE}/api/chat/stream", json={"q": QUERY}, stream=True, timeout=180)

stages: list[str] = []
deltas = 0
result = None
error = None
kind = ""
for raw in resp.iter_lines(decode_unicode=False):
    if not raw:
        continue
    line = raw.decode("utf-8")
    if line.startswith("event: "):
        kind = line[7:]
    elif line.startswith("data: "):
        payload = json.loads(line[6:])
        if kind == "stage":
            stages.append(payload["stage"])
        elif kind == "delta":
            deltas += 1
        elif kind == "result":
            result = payload
        elif kind == "error":
            error = payload

print("stages:", stages)
print("deltas:", deltas)
print("error:", error)
if result:
    items = result.get("items") or []
    print("stage:", result.get("stage"), "items:", len(items),
          "kinds:", sorted({i.get("match_kind") for i in items if i.get("match_kind")}))
    print("reply_len:", len(result.get("reply") or ""))
    print("message_id:", bool(result.get("message_id")))
ok = (
    stages == ["understanding", "retrieving", "recommending"]
    and deltas > 50
    and error is None
    and result
    and result.get("stage") == "results"
    and len(result.get("items") or []) == 3
)
print("ALL PASS" if ok else "FAIL")
