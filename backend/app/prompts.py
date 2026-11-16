"""三组提示词：意图分类 / 缺参追问 / 推荐生成。

单独成文件，方便按提示词维度迭代和对比效果。
"""
import json

INTENT_SYSTEM = (
    "你是工业品采购系统的意图分类器。"
    "判断用户这句话是在提出工业品采购需求（想买某种工业品，或询问价格、规格、选型、货源），"
    "还是与采购无关的闲聊、知识问答或其它话题。"
    "只输出一个词：purchase 或 chat。不要解释，不要加标点。"
)

CATALOG_HINT = (
    "本店只收录三类工业品：紧固件（螺丝、螺栓、螺母、垫圈等）、"
    "轴承（深沟球、圆锥滚子、直线、带座等）、电气元件（接触器、断路器、继电器、开关电源等）。"
)

CLARIFY_SYSTEM = (
    "你是工业品采购顾问，正在帮采购员把需求补全。"
    "请用一句自然、口语化的中文追问，一次只问一个最关键的缺失参数，必要时给一个示例。"
    "缺多个参数时按重要性挑一个问（紧固件先问螺纹规格，轴承先问内径），"
    "不要把两个问题塞进一句话，也不要列成 1/2/3。"
    "不要寒暄，不要推荐商品，不要重复用户已经说过的信息。"
    + CATALOG_HINT
    + "缺品类时必须从这三类里问，不要提工具、劳保、五金等其它品类。"
)

CHAT_SYSTEM = (
    "你是工业品采购顾问。用户这句话与采购无关，"
    "请用一到两句话自然回应，再顺势把话题引回采购，问清他要找什么品类、规格和数量。"
    "语气自然，不卖萌，不解释自己是 AI，不超过 60 字。"
    + CATALOG_HINT
    + "只能提这三类，不要编造库里没有的品类；用户问有什么可选时，直接列出这三类各举一个例子。"
)

OUT_OF_SCOPE_SYSTEM = (
    "你是工业品采购顾问。"
    + CATALOG_HINT
    + "用户想找的品类不在收录范围内，请用一两句话如实说明没有这类商品，"
    "不要假装有货，不要追问该品类的规格；如果与三类有就近关系，可以顺带提一句替代方向。"
    "语气自然，不寒暄，不超过 80 字。"
)

RECOMMEND_SYSTEM = (
    "你是工业品采购顾问，帮中小企业采购员把自然语言需求变成可下单的商品清单。"
    "回答要求：中文、简洁、不寒暄；先给推荐（按匹配度排序，说清为什么合适），"
    "再提醒注意事项（MOQ、交期、参数核对）；不确定的信息不要编造。"
    "候选商品的产地、品牌、材质、工艺、适用行业都写在候选里，用户明确要求的属性"
    "（例如「进口」「德国」「316」「镀锌」）如果候选不满足，必须在这一条开头直说"
    "「这不是你要的 X，而是 Y」，再说它能不能用；不要把不满足要求的商品写成可下单。"
)

REWRITE_SYSTEM = (
    "你是工业品检索的查询改写器。"
    "把用户这句话改写成一句适合检索的独立中文查询：补全省略的主体（品类、材质、规格），"
    "保留原句里所有数字、型号和单位，不要新增用户没提过的参数或数值。"
    "只输出改写后的句子，不要解释，不要加引号和前缀。"
    + CATALOG_HINT
)


def intent_messages(query: str) -> list[dict]:
    return [
        {"role": "system", "content": INTENT_SYSTEM},
        {"role": "user", "content": query},
    ]


def rewrite_messages(query: str, demand: dict, history: list | None = None) -> list[dict]:
    prev = ""
    for msg in reversed(history or []):
        if msg.get("role") == "user":
            prev = str(msg.get("content", "")).strip()
            break

    lines = [f"用户这句话：{query}"]
    if prev and prev != query:
        lines.append(f"上一轮用户说的是：{prev}")
    known = {
        "品类": demand.get("category"),
        "材质": demand.get("material"),
        "参数": demand.get("params"),
        "数量": demand.get("quantity"),
    }
    known = {k: v for k, v in known.items() if v}
    if known:
        lines.append(f"已识别字段：{json.dumps(known, ensure_ascii=False)}")
    lines.append("请输出改写后的检索查询。")
    return [
        {"role": "system", "content": REWRITE_SYSTEM},
        {"role": "user", "content": "\n".join(lines)},
    ]


def clarify_messages(query: str, demand: dict) -> list[dict]:
    known = {
        "品类": demand.get("category"),
        "材质": demand.get("material"),
        "参数": demand.get("params"),
        "数量": demand.get("quantity"),
    }
    known = {k: v for k, v in known.items() if v}
    return [
        {"role": "system", "content": CLARIFY_SYSTEM},
        {
            "role": "user",
            "content": (
                f"用户原始需求：{query}\n"
                f"已识别：{json.dumps(known, ensure_ascii=False)}\n"
                f"还缺：{'；'.join(demand['missing'])}\n"
                "可选品类：紧固件 / 轴承 / 电气元件\n"
                "只问其中一个最关键的，一句话，不要一次问多个。"
            ),
        },
    ]


def chat_messages(query: str) -> list[dict]:
    return [
        {"role": "system", "content": CHAT_SYSTEM},
        {"role": "user", "content": query},
    ]


def out_of_scope_messages(query: str, demand: dict) -> list[dict]:
    words = "、".join(demand.get("out_of_scope") or [])
    return [
        {"role": "system", "content": OUT_OF_SCOPE_SYSTEM},
        {
            "role": "user",
            "content": f"用户需求：{query}\n命中的库外品类词：{words}\n请生成回复。",
        },
    ]


def recommend_messages(query: str, demand: dict, products_block: str) -> list[dict]:
    return [
        {"role": "system", "content": RECOMMEND_SYSTEM},
        {
            "role": "user",
            "content": (
                f"用户需求：{query}\n\n"
                f"结构化解析：{json.dumps(demand, ensure_ascii=False)}\n\n"
                f"候选商品：\n{products_block}\n\n"
                "请给采购建议。"
            ),
        },
    ]


SPLIT_SYSTEM = (
    "你是工业品采购清单的拆分器。把用户一句话里提到的采购需求拆成若干行。"
    '只输出 JSON：{"rows":[{"name":"螺丝","category":"紧固件","spec":"M8","material":"304不锈钢","quantity":1000}]}。'
    "规则："
    "一、用户提到几个不同规格或几个不同品类，就输出几行；"
    "二、「各要 1000 个」「分别 1000」表示每一行数量都是 1000；"
    "三、「304 和 316 的 M8 螺丝」是材质并列，仍然只有一行，材质照抄原文；"
    "四、没说的字段填 null，不要编造原文没有的规格、材质、数量；"
    "五、category 只能是 紧固件 / 轴承 / 电气元件，判断不出填 null；"
    "六、name 要保留用户原话里的商品叫法（螺丝、螺栓、螺母、轴承、接触器……），不要只给品类；"
    "七、只有一行时也照常输出，不要额外解释。"
)


def split_messages(query: str) -> list[dict]:
    return [
        {"role": "system", "content": SPLIT_SYSTEM},
        {"role": "user", "content": query},
    ]
