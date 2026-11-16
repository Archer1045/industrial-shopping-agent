"""精排接入后的效果与耗时对比。"""
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8")

B = "http://127.0.0.1:8100"
CASES = [
    "耐高温的轴承，内径 20mm",
    "内六角 M8×30 螺丝",
    "德国进口的 6204 轴承",
    "内径 20 的轴承要 50 个",
    "镀锌 M8×30 螺丝 1000 个",
]

for q in CASES:
    t0 = time.time()
    r = requests.post(f"{B}/api/chat", json={"q": q}, timeout=180).json()
    dt = time.time() - t0
    print(f"\n[{r['stage']}] {q}  ({dt:.1f}s)")
    for it in (r.get("items") or [])[:3]:
        print(
            f"   {it['name'][:26]:<26} rrf={it.get('score')} "
            f"rerank={it.get('rerank_score')} origin={it.get('origin')}"
        )
