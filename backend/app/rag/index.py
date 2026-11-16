"""商品编码文本与索引构建兼容入口。"""


def product_text(row) -> str:
    """商品用于向量化的文本，八个维度都拼进去，用户提到哪个都能召回。"""
    parts = [
        row["name"],
        row["category"],
        row["brand"] or "",
        row["material"] or "",
        row["spec"] or "",
        row["model"] or "",
        row["process"] or "",
        row["origin"] or "",
        row["industry"] or "",
        row["standard"] or "",
        row["description"] or "",
    ]
    return " ".join(p for p in parts if p and p != "-")


def build_index() -> dict:
    """兼容入口：委托 IndexManager 做增量构建，返回结构保持不变。"""
    # 延迟导入，避免 index 与 index_manager 相互导入
    from . import index_manager

    return index_manager.build_index()
