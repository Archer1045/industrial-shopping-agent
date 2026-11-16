"""检索冒烟测试。"""
import sys

sys.stdout.reconfigure(encoding="utf-8")

from app.rag.index import build_index
from app.rag.retriever import hybrid_search

print("building index ...")
state = build_index()
print(f"indexed {len(state['rows'])} products")

QUERIES = [
    "304 不锈钢 M8 螺丝，长度 30mm",
    "需要内径 20 的轴承",
    "24V 开关电源",
    "M8 的内六角螺丝",
    "断路器 16A",
]

for q in QUERIES:
    print(f"\n=== {q}")
    for r in hybrid_search(q, state, top_k=3):
        print(f"  [{r['score']:.4f}] {r['name']}  (v={r['vector_rank']}, b={r['bm25_rank']})")
