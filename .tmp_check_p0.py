"""P0 三项改动的验证：3.4 硬约束来源、3.3 替代品标记、3.1 行评估。"""
import io
import requests
from openpyxl import Workbook

B = "http://127.0.0.1:8100"


def ask(q, history=None):
    return requests.post(f"{B}/api/chat", json={"q": q, "history": history or []}, timeout=120).json()


def line(name):
    print("-" * 60, name)


line("3.4/3.3 精确命中：M8×30 螺丝")
r = ask("304 不锈钢 M8×30 螺丝，1000 个")
print("stage", r["stage"], "kind", r["items"][0]["match_kind"] if r["items"] else None)
print("top", r["items"][0]["name"] if r["items"] else None)

line("3.3 库内无此规格：M12×80 螺丝（应标替代）")
r = ask("M12×80 螺丝，100 个")
print("stage", r["stage"], "count", len(r["items"]))
if r["items"]:
    it = r["items"][0]
    print("kind", it["match_kind"], "mismatches", it.get("mismatches"))
print("reply head:", r["reply"][:80].replace("\n", " "))

line("3.3 轴承无精确内径：内径 17mm 的深沟球轴承")
r = ask("内径 17mm 的深沟球轴承，10 个")
print("stage", r["stage"])
if r["items"]:
    it = r["items"][0]
    print("kind", it["match_kind"], "mismatches", it.get("mismatches"))

line("3.1 Excel 缺参数行")
wb = Workbook()
ws = wb.active
ws.append(["物料名称", "规格型号", "数量"])
ws.append(["内六角螺栓", "M8", "1000"])
ws.append(["深沟球轴承", "", "50"])
ws.append(["内六角螺栓 M8×30 304不锈钢", "", "1000"])
buf = io.BytesIO()
wb.save(buf)
buf.seek(0)
files = {"file": ("p0.xlsx", buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
u = requests.post(f"{B}/api/chat/upload", files=files, timeout=180).json()
for row in u["rows"]:
    print(row["row_no"], "|", row.get("status"), "|", row["note"][:40])

line("3.1 多需求缺参行")
r = ask("螺丝 M8 和 M10 各要 1000 个")
for row in r.get("rows", []):
    print(row["row_no"], "|", row.get("status"), "|", row["note"][:40])

line("回归：库外 / 闲聊 / 追问")
print("扳手 ->", ask("我想买个扳手")["stage"])
print("天气 ->", ask("今天天气不错")["stage"])
print("我要买螺丝 ->", ask("我要买螺丝")["stage"])
