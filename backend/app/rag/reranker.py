"""cross-encoder 精排：召回之后再用交叉编码器逐条打分。

设计要点：
1. 懒加载。模型约 1 GB，加载要十几秒，不能放进启动路径，
   否则每次改代码重启都要多等一倍时间。
2. 失败降级。模型缺失、显存不够、依赖缺失，都只让精排失效，
   检索继续走规则重排，不影响演示。
3. 只重排不改分。返回的仍然是原来那批候选，只是顺序变了，
   RRF 分数照旧保留，方便排查是融合的问题还是精排的问题。
"""
from __future__ import annotations

import threading

MODEL_DIR = r"D:\AI\models\bge-reranker-base"

_lock = threading.Lock()
_model = None
_failed = False


def doc_text(row: dict) -> str:
    """把一条商品拼成交叉编码器吃的文本。

    顺序按「用户最可能提到的词」排：名称、规格、型号优先，
    后面才是品牌、材质、工艺、产地、行业、说明。
    """
    parts = [
        row.get("name"),
        row.get("spec"),
        row.get("model"),
        row.get("material"),
        row.get("standard"),
        row.get("brand"),
        row.get("process"),
        row.get("origin"),
        row.get("industry"),
        row.get("description"),
    ]
    return " ".join(str(p) for p in parts if p and p != "-")


def available() -> bool:
    """模型目录在、且之前没加载失败过，就认为可用。"""
    if _failed:
        return False
    from pathlib import Path

    return Path(MODEL_DIR).joinpath("pytorch_model.bin").exists()


def _get():
    global _model, _failed
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        try:
            from sentence_transformers import CrossEncoder

            _model = CrossEncoder(MODEL_DIR, max_length=512, device="cuda")
        except Exception as exc:  # 模型或显存问题都降级，不阻断检索
            _failed = True
            print(f"[reranker] 加载失败，精排降级：{exc}")
            return None
    return _model


def score_pairs(pairs: list[tuple[str, str]]) -> list[float]:
    """给 (query, passage) 对打分。模型不可用时返回空列表。"""
    model = _get()
    if model is None or not pairs:
        return []
    scores = model.predict(pairs)
    return [float(s) for s in scores]


def rerank(query: str, rows: list[dict], top_k: int | None = None) -> list[dict]:
    """对传入商品重新排序。模型不可用时原样返回。"""
    if not rows or not available():
        return rows
    scores = score_pairs([(query, doc_text(r)) for r in rows])
    if not scores:
        return rows
    ranked = [r for _, r in sorted(zip(scores, rows), key=lambda x: -x[0])]
    return ranked[:top_k] if top_k else ranked


def warmup() -> None:
    """启动后调用一次，把加载时间挪到用户看不见的地方。"""
    if available():
        _get()
