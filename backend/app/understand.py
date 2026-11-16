"""结构化理解层：一次模型调用，把这句话（连同前几轮）理解成可以执行的需求行。

为什么要有这一层：规则能覆盖 90% 的说法，但接不住多值、指代、否定、修改这几种。
这里让模型负责「听懂」，代码负责「校验」——模型吐出来的每个字段都要过一遍检查，
不合法就丢掉；整段理解失败就返回 None，调用方退回规则链路，保证演示不会崩。
"""
import json
import re

from . import llm

UNDERSTAND_SYSTEM = """你是工业品采购助手的需求理解模块。读用户这句话（可能只是半句，要结合前面几轮），输出 JSON。

格式：
{"intent": "purchase" | "chat" | "unknown", "rows": [{"name": "品类或商品名", "spec": "规格参数", "quantity": 1000}]}

规则：
1. 用户要买东西 → purchase；闲聊或问知识 → chat；实在看不出来 → unknown
2. 一句话里要几个规格、几个品类，就输出几行；只有一个需求就输出一行
3. name 尽量保留用户原话（螺丝、轴承、断路器、接触器）
4. spec 把用户提到的尺寸、型号和限定词原样放进来（M8×30、内径 25mm、6204-2RS、德国、304 不锈钢、镀锌、机床用），限定词丢了检索就找不到对的货
5. quantity 只填数字；说「各要 1000 个」时每行都填 1000；没说就填 null
6. 结合历史：用户只回「25mm, 30mm」时，用历史里的品类把 name 补上
7. 不要编造用户没提的参数，不确定就留空
8. 只输出 JSON，不要解释"""

# 校验用：品类必须是这三类之一，M 号、尺寸、型号只认固定形态
VALID_CATEGORIES = {"紧固件", "轴承", "电气元件"}
_SPEC_OK = re.compile(r"[M㎡]?\d|内径|外径|长度|V|A|mm")
MAX_ROWS = 5


def _extract_json(text: str) -> dict | None:
    """从模型输出里抠出 JSON，容忍 markdown 围栏和前后废话。"""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _clean_row(row: dict) -> dict | None:
    """校验一行：name 和 spec 至少有一个，数量必须是正整数。"""
    if not isinstance(row, dict):
        return None
    name = str(row.get("name") or "").strip()
    spec = str(row.get("spec") or "").strip()
    if not name and not spec:
        return None
    if name and name not in VALID_CATEGORIES and not re.search(r"[\u4e00-\u9fa5A-Za-z]", name):
        name = ""
    qty = row.get("quantity")
    quantity = int(qty) if isinstance(qty, (int, float)) and qty and qty > 0 else None
    spec = spec[:60]
    name = name[:40]
    if not name and not spec:
        return None
    return {"query": f"{name} {spec}".strip() + (f" 数量 {quantity}" if quantity else ""),
            "name": name, "spec": spec, "quantity": quantity}


def understand(query: str, history: list | None = None) -> dict | None:
    """返回 {"intent": ..., "rows": [{"query","name","spec","quantity"}], "raw": 模型原文}。

    任何一步不对都返回 None，调用方走规则链路；这里不抛异常。
    """
    if not llm.API_KEY:
        return None
    messages = [{"role": "system", "content": UNDERSTAND_SYSTEM}]
    for msg in (history or [])[-4:]:
        role = msg.get("role")
        content = str(msg.get("content") or "")[:200]
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": query})

    try:
        text = llm.chat(messages, temperature=0, max_tokens=400, timeout=25)
    except Exception:  # 模型超时或报错：退回规则，不让这一轮对话断掉
        return None

    data = _extract_json(text)
    if not data:
        return None
    intent = data.get("intent")
    if intent not in ("purchase", "chat", "unknown"):
        intent = "unknown"
    rows = [_clean_row(r) for r in (data.get("rows") or [])][:MAX_ROWS]
    rows = [r for r in rows if r]
    if intent == "purchase" and not rows:
        return None
    return {"intent": intent, "rows": rows, "raw": text.strip()[:800]}
