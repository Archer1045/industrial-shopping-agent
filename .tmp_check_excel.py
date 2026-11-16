"""造三个测试表并调用上传接口，检查逐行匹配结果。"""
import sys
from pathlib import Path

import requests
from openpyxl import Workbook

sys.stdout.reconfigure(encoding="utf-8")

TMP = Path(__file__).parent / ".tmp"
TMP.mkdir(exist_ok=True)


def make_standard():
    wb = Workbook()
    ws = wb.active
    ws.append(["物料名称", "规格型号", "材质", "数量", "单位"])
    ws.append(["内六角螺栓", "M8×30", "304不锈钢", 1000, "个"])
    ws.append(["深沟球轴承", "6204-2RS", "", 50, "个"])
    ws.append(["开关电源", "S-350-24", "", 10, "台"])
    ws.append(["断路器", "DZ47-63 C16", "", 20, "个"])
    ws.append(["扳手", "8寸", "", 5, "把"])
    ws.append(["合计", "", "", 1085, ""])
    path = TMP / "standard.xlsx"
    wb.save(path)
    return path


def make_no_header():
    wb = Workbook()
    ws = wb.active
    ws.append(["内六角圆柱头螺丝", "M10×40", 500])
    ws.append(["深沟球轴承", "6204-2RS", 200])
    path = TMP / "no_header.xlsx"
    wb.save(path)
    return path


def make_odd_names():
    wb = Workbook()
    ws = wb.active
    ws.append(["存货名称", "产品型号", "采购数量", "计量单位", "品牌"])
    ws.append(["交流接触器", "CJX2-1210", 30, "只", "正泰"])
    ws.append(["陶瓷轴承", "6204", 50, "套", ""])
    path = TMP / "odd_names.xlsx"
    wb.save(path)
    return path


def upload(path: Path):
    with path.open("rb") as fh:
        resp = requests.post(
            "http://127.0.0.1:8100/api/chat/upload",
            files={"file": (path.name, fh, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            timeout=120,
        )
    resp.raise_for_status()
    return resp.json()


def main():
    for maker in (make_standard, make_no_header, make_odd_names):
        path = maker()
        data = upload(path)
        print(f"\n=== {path.name} ===")
        print(
            f"header_row={data['header_row']} fallback={data['fallback']} "
            f"skipped={data['skipped']} rows={len(data['rows'])}"
        )
        print(data["summary"])
        for row in data["rows"]:
            print(f"  L{row['row_no']} [{row['note']}] {row['query']} -> {row['names'][:2]}")


if __name__ == "__main__":
    main()
