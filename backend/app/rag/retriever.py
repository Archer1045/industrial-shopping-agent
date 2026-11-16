"""混合检索：FAISS + BM25 + RRF 融合 + 参数硬过滤。"""
import re

import jieba
import numpy as np

from .embedder import encode
from . import reranker

RRF_K = 60

# 精排候选池：融合后取前这么多条交给交叉编码器。
# 48 条商品一次全排也就 26ms，池子给大一点不影响速度。
RERANK_POOL = 20

# 头型、结构类修饰词：用户明确提及时，命中的商品排到前面
SHAPE_WORDS = ("内六角", "外六角", "沉头", "圆柱头", "盘头", "半圆头", "平头", "法兰")

# 软属性：命中加分但不硬过滤。用户说「要 304 的」，316 仍可作为备选出现。
SOFT_FIELDS = ("brand", "material", "process", "origin", "industry")
ORIGIN_SHORT = ("国产", "进口", "德国", "德标", "日本", "日标", "原装")
INDUSTRY_SHORT = ("机床", "汽车", "电子", "建筑", "化工", "食品", "物流", "新能源", "自动化", "通用装配")
MATERIAL_HINT = ("304", "316", "不锈钢", "碳钢", "镀锌", "黄铜", "尼龙")
PROCESS_HINT = ("电镀锌", "热镀锌", "镀镍", "发黑", "钝化", "冷镦", "热处理", "喷塑", "压铸", "注塑", "车削", "冲压", "挤压", "烧结")

# 用户报型号时（6204 / 6204-2RS / DZ47-63），命中的排前面。
# 四位数字后面跟量词（1000 个）不算型号。
MODEL_RE = re.compile(
    r"[A-Za-z]{0,4}\d{2,5}\s*[-－]\s*[0-9A-Za-z]{1,8}"
    r"|(?<![\d.])\d{4}(?!\s*(?:个|件|只|根|片|套|台|米))"
)


def _query_category(query: str) -> str | None:
    """从 query 里认出用户要的品类，用于精排时把跨品类候选压后。"""
    from ..demand import CATEGORY_WORDS

    for cat, words in CATEGORY_WORDS.items():
        if cat in query or any(w in query for w in words):
            return cat
    return None


def _attr_hits(row: dict, query: str) -> int:
    """统计这条商品在用户 query 里命中了几个软属性。"""
    hits = 0
    for field in SOFT_FIELDS:
        val = row.get(field) or ""
        if not val or val == "-":
            continue
        if val in query:
            hits += 1
            continue
        # 产地是「国产 / 进口·德国 / 进口·日本」，说「进口」要算命中所有进口件，
        # 说「德国」「日本」则只算对应国家的
        if field == "origin" and (
            ("进口" in query and val.startswith("进口"))
            or ("德国" in query and "德国" in val)
            or ("日本" in query and "日本" in val)
            or ("国产" in query and val == "国产")
        ):
            hits += 1
        elif field == "industry" and any(s in query and s in val for s in INDUSTRY_SHORT):
            hits += 1
    return hits


def _has_soft_hint(query: str) -> bool:
    """query 里是否提到任何软属性，没提到就不用重排。"""
    return any(s in query for s in MATERIAL_HINT + PROCESS_HINT + ORIGIN_SHORT + INDUSTRY_SHORT)


def extract_params(query: str) -> dict:
    """从 query 提取可硬过滤的参数（内径/长度/M 规格）。"""
    params = {}
    m = re.search(r"内径\s*(\d+(?:\.\d+)?)", query)
    if m:
        params["size"] = f"{m.group(1)}mm"
    m = re.search(r"长度\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)?", query)
    if m:
        params["length"] = f"{m.group(1)}mm"
    # 「M8×30」同时给出螺纹规格和长度；大小写都认
    pair = re.search(r"(?<![A-Za-z])[Mm](\d+)\s*[×xX*]\s*(\d+)", query)
    if pair:
        params["spec_m"] = f"M{pair.group(1)}"
        params["length"] = f"{pair.group(2)}mm"
        return params
    m = re.search(r"(?<![A-Za-z])[Mm](\d+)(?![0-9])", query)
    if m:
        params["spec_m"] = f"M{m.group(1)}"
    return params


def _match(row: dict, params: dict) -> bool:
    if "size" in params and params["size"] not in (row.get("size") or ""):
        return False
    if "length" in params and params["length"] not in (row.get("length") or ""):
        return False
    if "spec_m" in params and params["spec_m"] not in (row.get("spec") or ""):
        return False
    return True


def _mismatches(row: dict, params: dict) -> list[str]:
    """列出商品与硬约束不符的项，用作替代品的说明。"""
    out = []
    if "size" in params and params["size"] not in (row.get("size") or ""):
        out.append(f"内径要求 {params['size']}，候选 {row.get('size') or '未标注'}")
    if "length" in params and params["length"] not in (row.get("length") or ""):
        out.append(f"长度要求 {params['length']}，候选 {row.get('length') or '未标注'}")
    if "spec_m" in params and params["spec_m"] not in (row.get("spec") or ""):
        out.append(f"规格要求 {params['spec_m']}，候选 {row.get('spec') or '未标注'}")
    return out


def hybrid_search(
    query: str,
    state: dict,
    top_k: int = 10,
    constraints: dict | None = None,
) -> list[dict]:
    """返回带分数的商品列表。

    query 只负责语义召回（可以是 LLM 改写过的句子）；
    constraints 是代码校验后的结构化参数，给了就用它做硬过滤，
    不再从 query 里二次提取，避免改写文本污染规格判断。
    """
    rows = state["rows"]
    id_index = {pid: i for i, pid in enumerate(state["ids"])}

    # 向量召回（扩大范围，给过滤留余量）
    qv = encode([query])[0].astype(np.float32).reshape(1, -1)
    n = min(max(top_k * 5, 20), len(rows))
    _, indices = state["faiss"].search(qv, n)
    vec_ranks = {}
    for rank, idx in enumerate(indices[0]):
        if idx < 0:
            continue
        vec_ranks[state["ids"][int(idx)]] = rank

    # BM25 召回
    tokens = list(jieba.cut(query))
    scores = state["bm25"].get_scores(tokens)
    order = np.argsort(-scores)[:n]
    bm_ranks = {state["ids"][int(i)]: rank for rank, i in enumerate(order)}

    # RRF 融合
    fused = {}
    for pid, rank in vec_ranks.items():
        fused[pid] = fused.get(pid, 0.0) + 1.0 / (RRF_K + rank + 1)
    for pid, rank in bm_ranks.items():
        fused[pid] = fused.get(pid, 0.0) + 1.0 / (RRF_K + rank + 1)

    ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
    rerank_scores: dict[int, float] = {}

    # 参数硬过滤：有精确命中就只保留精确的；
    # 一条都没有时不再静默回退，而是保留结果并整体标记为「替代品」。
    params = constraints if constraints is not None else extract_params(query)
    match_kind = "exact"
    if params:
        exact = [(pid, s) for pid, s in ranked if _match(rows[id_index[pid]], params)]
        if exact:
            ranked = exact
        else:
            match_kind = "alternative"

    # 头型等修饰词重排：用户明确说了「内六角/沉头」，命中的排前面，但不硬删
    wanted = [w for w in SHAPE_WORDS if w in query]
    if wanted:

        def _hit(pid: int) -> bool:
            row = rows[id_index[pid]]
            text = f"{row.get('name') or ''} {row.get('description') or ''}"
            return any(w in text for w in wanted)

        ranked = sorted(ranked, key=lambda kv: (not _hit(kv[0]), -kv[1]))

    # 型号重排：用户报了型号（6204 / 6204-2RS / DZ47-63），命中的排前面
    model_hits = [m.group(0) for m in MODEL_RE.finditer(query)]
    if model_hits:
        def _model_hit(pid: int) -> bool:
            row = rows[id_index[pid]]
            hay = f"{row.get('model') or ''} {row.get('name') or ''} {row.get('spec') or ''}"
            return any(m in hay for m in model_hits)

        ranked = sorted(ranked, key=lambda kv: (not _model_hit(kv[0]), -kv[1]))

    # 软属性重排：品牌 / 材质 / 工艺 / 产地 / 行业，命中越多越靠前，但不硬删
    # 用户说「要 304 的」时，316 仍可作为备选出现，所以只排序不过滤
    if _has_soft_hint(query):
        ranked = sorted(
            ranked,
            key=lambda kv: (-_attr_hits(rows[id_index[kv[0]]], query), -kv[1]),
        )

    # cross-encoder 精排：只对融合后的前 RERANK_POOL 条打分重排，
    # 用交叉编码器逐条阅读 query 和商品原文，比关键词重合更准。
    #
    # 注意：交叉编码器对「产地=德国」这种结构化约束不敏感（实测会把国产件排到
    # 进口件前面），所以软属性命中数仍然是第一排序键，精排只用来打破同分。
    if len(ranked) > 1 and reranker.available():
        pool = ranked[:RERANK_POOL]
        texts = [reranker.doc_text(rows[id_index[pid]]) for pid, _ in pool]
        scores = reranker.score_pairs([(query, t) for t in texts])
        if scores:
            hits = [_attr_hits(rows[id_index[pid]], query) for pid, _ in pool]
            cat = _query_category(query)
            wrong_cat = [
                bool(cat) and rows[id_index[pid]].get("category") != cat for pid, _ in pool
            ]
            order = sorted(
                range(len(scores)),
                key=lambda i: (wrong_cat[i], -hits[i], -scores[i]),
            )
            reranked = [pool[i] for i in order]
            for i, (pid, _rrf) in enumerate(reranked):
                rerank_scores[pid] = round(scores[order[i]], 4)
            ranked = reranked + ranked[RERANK_POOL:]

    results = []
    for pid, score in ranked[:top_k]:
        row = rows[id_index[pid]].copy()
        row["score"] = round(score, 6)
        row["vector_rank"] = vec_ranks.get(pid)
        row["bm25_rank"] = bm_ranks.get(pid)
        row["match_kind"] = match_kind
        if match_kind == "alternative":
            row["mismatches"] = _mismatches(row, params)
        if pid in rerank_scores:
            row["rerank_score"] = rerank_scores[pid]
        results.append(row)
    return results
