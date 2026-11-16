"""图片识别：调 deepseek-flash 的视觉能力，把截图里的商品清单读成结构化行。"""
from __future__ import annotations

import base64
import json
import re

import requests

from . import llm

VISION_MODEL = "deepseek-flash"

VISION_SYSTEM = """你是工业品采购清单识别助手。看图，把里面的商品逐行读出来，只输出 JSON，不要任何解释。

输出格式：
{"items":[{"name":"商品名称","spec":"规格型号","material":"材质","quantity":1000,"unit":"个"}]}

规则：
- name 填商品名称（如 内六角螺栓、深沟球轴承、断路器），spec 填规格型号（如 M8×30、6204-2RS、DZ47-63 C16）
- quantity 只填数字，图片里没写就填 null；unit 是单位（个、套、台、只），没写就填 null
- 只读图片里真实存在的内容，不要根据常识补充或编造
- 图片里没有商品清单，返回 {"items":[]}"""


def _extract_json(text: str) -> dict:
    """从模型输出里取出 JSON，容错处理代码块围栏与前后废话。"""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def image_to_items(data: bytes, mime: str) -> list[dict]:
    """图片二进制转成商品行列表。识别失败时抛异常，由调用方决定怎么报错。"""
    if not llm.API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置")

    b64 = base64.b64encode(data).decode("utf-8")
    messages = [
        {"role": "system", "content": VISION_SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "读出这张图里的商品清单。"},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        },
    ]

    response = requests.post(
        f"{llm.BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {llm.API_KEY}", "Content-Type": "application/json"},
        json={"model": VISION_MODEL, "messages": messages, "temperature": 0, "max_tokens": 1200},
        timeout=120,
    )
    response.raise_for_status()
    text = response.json()["choices"][0]["message"]["content"]
    parsed = _extract_json(text)
    items = parsed.get("items") or []
    if not isinstance(items, list):
        raise ValueError("模型返回的 items 不是列表")
    return [item for item in items if isinstance(item, dict) and (item.get("name") or item.get("spec"))]
