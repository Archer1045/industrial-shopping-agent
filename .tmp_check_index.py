"""IndexManager 增量索引验证：临时数据库 + 临时目录，含故障注入，不碰真实数据。"""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

BASE = Path(r"D:\workSpace\code\industrial-shopping-agent\backend")
sys.path.insert(0, str(BASE))

from app.rag import index_manager as im  # noqa: E402

REAL_DB = BASE.parent / "data" / "products.db"
tmpdir = Path(tempfile.mkdtemp(prefix="idx2-"))
tmp_db = tmpdir / "products.db"
idx_dir = tmpdir / "index"
idx_dir.mkdir()

conn = sqlite3.connect(tmp_db)
conn.row_factory = sqlite3.Row
src = sqlite3.connect(REAL_DB)
src.row_factory = sqlite3.Row
schema = src.execute(
    "SELECT sql FROM sqlite_master WHERE type='table' AND name='products'"
).fetchone()[0]
conn.execute(schema)
cols = [r["name"] for r in src.execute("PRAGMA table_info(products)")]
rows = src.execute("SELECT * FROM products ORDER BY id").fetchall()
conn.executemany(
    f"INSERT INTO products ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
    [tuple(r[c] for c in cols) for r in rows],
)
conn.commit()


def _conn():
    c = sqlite3.connect(tmp_db)
    c.row_factory = sqlite3.Row
    return c


im.get_conn = _conn
im.INDEX_DIR = idx_dir
im.CURRENT_FILE = idx_dir / "current.json"

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + ((" | " + extra) if extra else ""))


# 1. 首次构建
idx = im.build_index()
check("首次：全部编码", idx["encoded"] == 48, f"encoded={idx['encoded']}")
check("首次：added=48", idx["added"] == 48, f"added={idx['added']}")
check("首次：products=48", idx["products"] == 48)
check("manifest 生成", im.CURRENT_FILE.exists())

# 2. 无变化
idx2 = im.build_index()
check("无变化：0 编码", idx2["encoded"] == 0, f"encoded={idx2['encoded']}")
check("无变化：reused=48", idx2["reused"] == 48)
check("无变化：added/modified/deleted 全 0",
      (idx2["added"], idx2["modified"], idx2["deleted"]) == (0, 0, 0),
      str((idx2["added"], idx2["modified"], idx2["deleted"])))

# 3. 修改一条
conn.execute("UPDATE products SET description = description || ' 改动' WHERE id = ?", (idx["ids"][0],))
conn.commit()
idx3 = im.build_index()
check("修改：encoded=1", idx3["encoded"] == 1, f"encoded={idx3['encoded']}")
check("修改：modified=1", idx3["modified"] == 1, f"modified={idx3['modified']}")
check("修改：reused=47", idx3["reused"] == 47)
check("修改：added/deleted=0", (idx3["added"], idx3["deleted"]) == (0, 0))

# 4. 新增
conn.execute(
    "INSERT INTO products (name, category, brand, material, spec, price, unit, moq, stock, lead_time)"
    " VALUES ('测试新增螺丝', '紧固件', '测试牌', '304 不锈钢', 'M6×20mm', 0.1, '个', 100, 1000, 2)"
)
conn.commit()
idx4 = im.build_index()
check("新增：added=1", idx4["added"] == 1, f"added={idx4['added']}")
check("新增：encoded=1", idx4["encoded"] == 1)
check("新增：products=49", idx4["products"] == 49)

# 5. 删除
conn.execute("DELETE FROM products WHERE name = '测试新增螺丝'")
conn.commit()
idx5 = im.build_index()
check("删除：deleted=1", idx5["deleted"] == 1, f"deleted={idx5['deleted']}")
check("删除：encoded=0", idx5["encoded"] == 0)
check("删除：products=48", idx5["products"] == 48)

# 6. 故障注入：改一条后让 manifest 切换失败，旧代际必须仍然可用
conn.execute("UPDATE products SET description = description || ' 第二次改动' WHERE id = ?", (idx["ids"][1],))
conn.commit()
real_replace = os.replace


def boom(src_path, dst_path):
    if str(dst_path).endswith("current.json"):
        raise OSError("injected: manifest swap failed")
    return real_replace(src_path, dst_path)


im.os.replace = boom
raised = False
try:
    im.build_index()
except OSError:
    raised = True
finally:
    im.os.replace = real_replace
check("故障注入：同步抛异常", raised)

status_after_fail = im.status()
check("故障注入：旧代际仍可用", status_after_fail["persisted"] is True, str(status_after_fail))

idx6 = im.build_index()
check("故障后重建：识别为 modified=1", idx6["modified"] == 1, f"modified={idx6['modified']}")
check("故障后重建：未误用半成品向量", idx6["encoded"] == 1, f"encoded={idx6['encoded']}")

# 7. 删除非 meta 文件 -> persisted 必须为 False
gen = im._current_gen()
(gen / "ids.json").unlink()
check("缺 ids.json：persisted=False", im.status()["persisted"] is False, str(im.status()))
idx7 = im.build_index()
check("缺文件后重建：全量编码", idx7["encoded"] == len(idx7["ids"]), f"encoded={idx7['encoded']}")
check("重建后：persisted 恢复 True", im.status()["persisted"] is True)

# 8. 向量维度与 meta 不一致 -> persisted 必须为 False，并走全量重建
gen = im._current_gen()
meta_path = gen / "meta.json"
bad_meta = json.loads(meta_path.read_text(encoding="utf-8"))
bad_meta["dim"] = bad_meta["dim"] + 1
meta_path.write_text(json.dumps(bad_meta, ensure_ascii=False), encoding="utf-8")
check("维度不符：persisted=False", im.status()["persisted"] is False, str(im.status()))
idx8 = im.build_index()
check("维度不符后重建：全量编码", idx8["encoded"] == len(idx8["ids"]), f"encoded={idx8['encoded']}")
check("维度不符后重建：persisted 恢复 True", im.status()["persisted"] is True)
check(
    "维度不符后重建：meta.dim 与向量一致",
    im.status()["dim"] == idx8["vectors"].shape[1],
    f"dim={im.status()['dim']} shape={idx8['vectors'].shape}",
)

# 9. 真实库未被改动
real = sqlite3.connect(REAL_DB)
real_cnt = real.execute("SELECT COUNT(*) FROM products").fetchone()[0]
real.close()
check("真实库仍是 48 条", real_cnt == 48, f"count={real_cnt}")

# 10. 代际清理：只保留 2 代
gens = [p for p in idx_dir.iterdir() if p.is_dir() and p.name.startswith("gen-")]
check("代际目录不超过 2 个", len(gens) <= 2, f"gens={[g.name for g in gens]}")

conn.close()
src.close()
print("\nALL PASS" if all(results) else f"\n{results.count(False)} FAILED")
print("临时目录:", tmpdir)
