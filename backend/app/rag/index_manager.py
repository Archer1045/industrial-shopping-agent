"""索引管理：向量持久化与按内容增量编码。

设计要点：
- 向量按商品 ID 复用，哈希覆盖完整 product_text()，文本没变就不重新编码。
- 持久化采用「代际目录 + manifest 指针」：每次同步把四个文件整套写进新的
  `gen-*` 目录，全部写完后再原子替换 `current.json` 指向它。任何一步失败，
  指针仍指向上一代，旧索引完整可用，不会出现新旧文件混用。
- FAISS 与 BM25 每次同步全量重建：数据量小，重建成本极低，
  能保证 rows / ids / texts / vectors 的位置映射与现有检索完全一致。
- 任一环节失败都抛异常，由调用方保留旧 STATE。
"""
import hashlib
import json
import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

import faiss
import jieba
import numpy as np
from rank_bm25 import BM25Okapi

from ..db import ROOT, get_conn
from .embedder import MODEL_DIR, encode
from .index import product_text

INDEX_DIR = ROOT / "data" / "index"
CURRENT_FILE = INDEX_DIR / "current.json"
KEEP_GENERATIONS = 2

FORMAT_VERSION = 1
MODEL_TAG = f"bge-m3:{MODEL_DIR}"

_sync_lock = threading.Lock()


def content_hash(text: str) -> str:
    """商品编码文本的稳定哈希，用于判断是否需要重新编码。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _current_gen() -> Path | None:
    """读 manifest 指针，返回当前可用代际目录；不可用时返回 None。"""
    if not CURRENT_FILE.exists():
        return None
    try:
        data = json.loads(CURRENT_FILE.read_text(encoding="utf-8"))
        gen = INDEX_DIR / str(data["gen"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return gen if gen.is_dir() else None


def _read_persisted() -> tuple[dict[int, np.ndarray], dict[int, str], dict] | None:
    """读当前代际索引；任何缺失、损坏或不一致都返回 None，由调用方全量重建。"""
    gen = _current_gen()
    if gen is None:
        return None

    vectors_file = gen / "vectors.npy"
    ids_file = gen / "ids.json"
    hashes_file = gen / "hashes.json"
    meta_file = gen / "meta.json"
    if not all(p.exists() for p in (vectors_file, ids_file, hashes_file, meta_file)):
        return None

    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        vectors = np.load(vectors_file)
        ids = json.loads(ids_file.read_text(encoding="utf-8"))
        hashes = json.loads(hashes_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    if meta.get("format_version") != FORMAT_VERSION or meta.get("model") != MODEL_TAG:
        return None
    dim = meta.get("dim")
    if (
        not isinstance(dim, int)
        or vectors.ndim != 2
        or vectors.shape[1] != dim
        or len(ids) != vectors.shape[0]
        or len(hashes) != len(ids)
    ):
        return None
    if int(meta.get("count", -1)) != len(ids):
        return None

    # 维度必须由真实向量核对：meta 写 1024、文件却是别的维度时不能当成可用索引
    by_id = {int(pid): vectors[i] for i, pid in enumerate(ids)}
    hash_by_id = {int(pid): hashes[i] for i, pid in enumerate(ids)}
    return by_id, hash_by_id, meta


def _write_persisted(ids: list[int], vectors: np.ndarray, hashes: list[str]) -> str:
    """整套写入新代际目录，最后原子切换 manifest。返回新代际名。"""
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    gen_name = f"gen-{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"
    gen = INDEX_DIR / gen_name
    gen.mkdir()

    meta = {
        "format_version": FORMAT_VERSION,
        "model": MODEL_TAG,
        "dim": int(vectors.shape[1]),
        "count": len(ids),
        "synced_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "gen": gen_name,
    }

    np.save(gen / "vectors.npy", vectors)
    (gen / "ids.json").write_text(json.dumps(ids, ensure_ascii=False), encoding="utf-8")
    (gen / "hashes.json").write_text(json.dumps(hashes, ensure_ascii=False), encoding="utf-8")
    (gen / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # 只有整套文件都落盘后，才让指针指向新代际；替换是原子的
    tmp = INDEX_DIR / "current.json.tmp"
    tmp.write_text(json.dumps({"gen": gen_name}, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CURRENT_FILE)

    _cleanup_old(gen_name)
    return gen_name


def _cleanup_old(keep: str) -> None:
    """只保留当前和上一代，其余代际目录删除；失败不影响主流程。"""
    try:
        gens = sorted(p for p in INDEX_DIR.iterdir() if p.is_dir() and p.name.startswith("gen-"))
    except OSError:
        return
    keep_names = {keep}
    older = [g for g in gens if g.name != keep]
    for g in older[-(KEEP_GENERATIONS - 1):]:
        keep_names.add(g.name)
    for g in gens:
        if g.name not in keep_names:
            shutil.rmtree(g, ignore_errors=True)


def build_index(force_full: bool = False) -> dict:
    """构建索引。数据库无变化时复用持久化向量，不重新编码。"""
    with _sync_lock:
        with get_conn() as conn:
            rows = conn.execute("SELECT * FROM products ORDER BY id").fetchall()

        if not rows:
            raise RuntimeError("products 表为空，请先运行 python -m app.seed")

        ids = [int(r["id"]) for r in rows]
        texts = [product_text(r) for r in rows]
        hashes = [content_hash(t) for t in texts]

        persisted = None if force_full else _read_persisted()
        old_hashes = persisted[1] if persisted is not None else {}
        old_vectors = persisted[0] if persisted is not None else {}

        reused: list[np.ndarray | None] = [None] * len(rows)
        modified = 0
        for i, pid in enumerate(ids):
            if pid in old_vectors and old_hashes.get(pid) == hashes[i]:
                reused[i] = old_vectors[pid]
            elif pid in old_vectors:
                modified += 1

        todo = [i for i, v in enumerate(reused) if v is None]
        if todo:
            fresh = encode([texts[i] for i in todo])
            for slot, vec in zip(todo, fresh):
                reused[slot] = vec

        vectors = np.vstack([v for v in reused if v is not None]).astype("float32")
        if vectors.shape[0] != len(rows):
            raise RuntimeError("向量行数与商品数不一致，索引构建中止")

        faiss_index = faiss.IndexFlatIP(vectors.shape[1])
        faiss_index.add(vectors)

        tokens = [list(jieba.cut(t)) for t in texts]
        bm25 = BM25Okapi(tokens)

        _write_persisted(ids, vectors, hashes)

        current_ids = set(ids)
        old_ids = set(old_vectors)
        added = len(current_ids - old_ids)
        deleted = len(old_ids - current_ids)

        return {
            "rows": [dict(r) for r in rows],
            "ids": ids,
            "texts": texts,
            "vectors": vectors,
            "faiss": faiss_index,
            "bm25": bm25,
            "products": len(ids),
            "encoded": len(todo),
            "reused": len(ids) - len(todo),
            "added": added,
            "modified": modified,
            "deleted": deleted,
        }


def sync() -> dict:
    """执行一次同步，返回完整状态与本次增量统计。"""
    index = build_index()
    index["synced_at"] = _read_meta().get("synced_at")
    return index


def status() -> dict:
    """索引状态；persisted 基于整套文件能否真正加载，而不是只看 meta。"""
    meta = _read_meta()
    usable = _read_persisted() is not None
    return {
        "products": meta.get("count"),
        "synced_at": meta.get("synced_at"),
        "model": meta.get("model"),
        "dim": meta.get("dim"),
        "format_version": meta.get("format_version"),
        "persisted": usable,
        "generation": meta.get("gen"),
    }


def _read_meta() -> dict:
    gen = _current_gen()
    if gen is None:
        return {"ok": False}
    meta_file = gen / "meta.json"
    if not meta_file.exists():
        return {"ok": False}
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False}
    meta["ok"] = True
    return meta
