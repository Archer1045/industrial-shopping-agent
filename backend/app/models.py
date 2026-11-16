"""表结构与初始化。"""
from .db import get_conn

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    brand TEXT,
    material TEXT,
    spec TEXT,
    model TEXT,
    size TEXT,
    length TEXT,
    standard TEXT,
    process TEXT,
    origin TEXT,
    industry TEXT,
    price REAL,
    unit TEXT DEFAULT '个',
    moq INTEGER DEFAULT 1,
    stock INTEGER DEFAULT 0,
    lead_time INTEGER DEFAULT 3,
    description TEXT
);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_material ON products(material);
"""

# 老库补列：早期版本没有 model / process / origin / industry
EXTRA_COLUMNS = (
    ("model", "TEXT"),
    ("process", "TEXT"),
    ("origin", "TEXT"),
    ("industry", "TEXT"),
)

# 依赖新列的索引，必须等 ALTER TABLE 之后建
EXTRA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);
CREATE INDEX IF NOT EXISTS idx_products_industry ON products(industry);
"""


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        have = {row["name"] for row in conn.execute("PRAGMA table_info(products)")}
        for col, col_type in EXTRA_COLUMNS:
            if col not in have:
                conn.execute(f"ALTER TABLE products ADD COLUMN {col} {col_type}")
        conn.executescript(EXTRA_INDEXES)
