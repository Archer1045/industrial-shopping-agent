"""需求解析冒烟测试。"""
import sys

sys.stdout.reconfigure(encoding="utf-8")

from app.demand import parse_demand

QUERIES = [
    "我需要 304 不锈钢 M8 螺丝，长度 30mm，1000 个",
    "我要买螺丝",
    "需要一批轴承",
    "内径 20 的轴承要 50 个",
    "24V 开关电源 10 个",
    "断路器 16A",
]

for q in QUERIES:
    d = parse_demand(q)
    print(f"\n=== {q}")
    print(f"  品类: {d['category']} | 材质: {d['material']} | 参数: {d['params']}")
    print(f"  数量: {d['quantity']} | 缺参: {d['missing']}")
    print(f"  改写: {d['rewritten_query']}")
