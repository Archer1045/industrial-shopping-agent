"""Excel 采购清单解析：读表、定位表头、逐行拼成检索问句。"""
from __future__ import annotations

import re
from typing import Any

from openpyxl import load_workbook

# 表头关键词。一列只归一个字段，所以长词写在前面更稳。
HEADER_HINTS: dict[str, tuple[str, ...]] = {
    "name": ("物料名称", "产品名称", "商品名称", "存货名称", "品名", "名称", "物料", "产品", "商品", "零件"),
    "spec": ("规格型号", "规格", "型号", "尺寸", "参数"),
    "quantity": ("采购数量", "需求数量", "数量", "采购量", "需求量", "数目", "个数"),
    "unit": ("计量单位", "单位"),
    "material": ("材质", "材料"),
    "brand": ("品牌", "厂家", "供应商"),
}

# 表头一般在前几行里
HEADER_SCAN_ROWS = 5

# 这几种行不是真实需求
SKIP_WORDS = ("合计", "小计", "总计", "备注", "说明", "序号")


def _cell_text(value: Any) -> str:
    """单元格值转干净字符串。浮点整数去掉 .0，日期只保留日期部分。"""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if hasattr(value, "date"):
        try:
            return value.date().isoformat()
        except Exception:
            return str(value)
    return str(value).strip()


def load_rows(path: str) -> list[list[str]]:
    """把第一个 sheet 读成二维字符串数组。"""
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        return [[_cell_text(c) for c in row] for row in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def detect_header(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    """在前几行里找命中字段最多的一行当表头。

    至少命中两个字段且包含品名或规格，否则认为没有表头。
    """
    best_idx, best_map, best_score = -1, {}, 0
    for idx, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        mapping: dict[str, int] = {}
        for col, text in enumerate(row):
            norm = re.sub(r"[\s()（）\[\]【】:：]", "", text)
            if not norm:
                continue
            for field, hints in HEADER_HINTS.items():
                if field in mapping:
                    continue
                if any(h in norm for h in hints):
                    mapping[field] = col
                    break
        if len(mapping) > best_score:
            best_idx, best_map, best_score = idx, mapping, len(mapping)
    if best_score < 2 or not ({"name", "spec"} & set(best_map)):
        return -1, {}
    return best_idx, best_map


def build_query(fields: dict[str, str]) -> str:
    """把一行字段拼成一句自然语言，交给现有的需求解析。"""
    parts = []
    for key in ("name", "spec", "material", "brand"):
        if fields.get(key):
            parts.append(fields[key])
    qty = fields.get("quantity", "")
    if qty:
        num = re.search(r"\d+(?:\.\d+)?", qty)
        parts.append(f"数量 {num.group(0) if num else qty}")
    return " ".join(parts)


def parse_rows(path: str) -> dict:
    """解析 Excel，返回表头信息与逐行问句。"""
    rows = load_rows(path)
    header_idx, mapping = detect_header(rows)
    fallback = header_idx < 0
    if fallback:
        # 认不出表头时按「第一列品名、第二列规格」猜，宁可错也不空转
        mapping = {"name": 0, "spec": 1}
        start = 0
    else:
        start = header_idx + 1

    parsed: list[dict] = []
    skipped = 0
    for offset, row in enumerate(rows[start:]):
        row_no = start + offset + 1
        if not any(row):
            skipped += 1
            continue
        fields = {key: (row[col] if col < len(row) else "") for key, col in mapping.items()}
        name = fields.get("name", "")
        if any(w in name for w in SKIP_WORDS):
            skipped += 1
            continue
        query = build_query(fields)
        if len(query) < 2:
            skipped += 1
            continue
        parsed.append({"row_no": row_no, "raw": fields, "query": query})

    return {
        "header_row": None if fallback else header_idx + 1,
        "mapping": mapping,
        "fallback": fallback,
        "rows": parsed,
        "skipped": skipped,
    }
