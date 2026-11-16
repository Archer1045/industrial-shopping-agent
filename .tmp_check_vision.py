"""测图片上传：走 /api/chat/upload，看识别和匹配结果。"""
import sys
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")

path = Path(__file__).parent / ".tmp" / "purchase.png"
with path.open("rb") as fh:
    resp = requests.post(
        "http://127.0.0.1:8100/api/chat/upload",
        files={"file": (path.name, fh, "image/png")},
        timeout=180,
    )

print("status:", resp.status_code)
if resp.status_code != 200:
    print(resp.text[:800])
    sys.exit(1)

data = resp.json()
print("stage:", data["stage"], "|", data["summary"])
for row in data["rows"]:
    print(f'{row["row_no"]}. {row["raw"]} -> {row["names"] or "无"} | {row["note"]}')
