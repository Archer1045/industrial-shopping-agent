"""需求解析：品类 / 材质 / 规格 / 数量 / 缺参判断。

先用规则解析（不依赖 LLM），后续可在此基础上叠加 LLM 结构化抽取。
"""
import re

CATEGORY_WORDS = {
    "紧固件": ["螺丝", "螺栓", "螺钉", "螺母", "垫圈", "垫片", "自攻", "膨胀"],
    "轴承": ["轴承"],
    "电气元件": ["接触器", "断路器", "继电器", "开关电源", "变频器", "端子", "导轨", "指示灯", "按钮", "热继电器"],
}

MATERIAL_WORDS = {
    "304不锈钢": ["304", "不锈钢"],
    "碳钢": ["碳钢", "镀锌"],
}

UNIT_WORDS = ("个", "件", "只", "根", "片", "套", "台", "米")

# 工艺 / 产地 / 应用行业：这三个维度不进硬过滤（用户说「镀锌的」也可能接受别的），
# 但必须认得出来，才能参与排序和改写。
PROCESS_WORDS = (
    "电镀锌", "热镀锌", "镀镍", "发黑", "钝化", "冷镦", "热处理",
    "喷塑", "压铸", "注塑", "车削", "冲压", "挤压", "烧结",
)

# 产地只区分国产 / 进口，进口再分国家——采购时「德国件还是日本件」是要分开问的。
# 键是用户可能的说法，值是库里的标准写法。
ORIGIN_ALIASES = {
    "德国": "进口·德国",
    "德标": "进口·德国",
    "德系": "进口·德国",
    "德国货": "进口·德国",
    "日本": "进口·日本",
    "日标": "进口·日本",
    "日系": "进口·日本",
    "日本货": "进口·日本",
    "进口": "进口",
    "原装": "进口",
    "国产": "国产",
    "国内": "国产",
    "国标": "国产",
}

INDUSTRY_ALIASES = {
    "机床": "机床设备",
    "汽车": "汽车零部件",
    "电子": "电子电气",
    "建筑": "建筑工程",
    "化工": "化工设备",
    "食品": "食品机械",
    "物流": "物流仓储",
    "新能源": "新能源",
    "自动化": "自动化设备",
    "通用装配": "通用装配",
}

# 形如 6204-2RS / DZ47-63 / S-350-24 的厂家型号，或轴承惯用的四位数字型号（6204）。
# 四位数字后面跟量词（「1000 个」）不算型号。
# 用户已经点名具体型号时，内径之类的参数就不用再追问了。
MODEL_RE = re.compile(
    r"[A-Za-z]{0,4}\d{2,5}\s*[-－]\s*[0-9A-Za-z]{1,8}"
    r"|(?<![\d.])\d{4}(?!\s*(?:个|件|只|根|片|套|台|米))"
)


def extract_model(text: str) -> str | None:
    m = MODEL_RE.search(text)
    return m.group(0).replace(" ", "") if m else None


# 产地词表。库里只记到「国产 / 进口·德国 / 进口·日本」，
# 用户如果点名城市（苏州、宁波等），这里识别出来，回复里如实说明不记城市
CITY_WORDS = (
    "苏州", "宁波", "温州", "东莞", "佛山", "深圳", "潍坊", "邯郸",
    "天津", "上海", "瓦房店", "江苏", "浙江", "广东", "山东", "河北", "辽宁",
)


def extract_city(text: str) -> str | None:
    for w in CITY_WORDS:
        if w in text:
            return w
    return None


def extract_attrs(text: str) -> dict:
    """提取工艺 / 产地 / 应用行业。返回的是种子数据里的标准写法。"""
    attrs: dict[str, str] = {}
    for w in PROCESS_WORDS:
        if w in text:
            attrs["process"] = w
            break
    for k, v in ORIGIN_ALIASES.items():
        if k in text:
            attrs["origin"] = v
            break
    for k, v in INDUSTRY_ALIASES.items():
        if k in text:
            attrs["industry"] = v
            break
    return attrs


# 头型：用户明确说了头型时才参与「能不能标可下单」的判断。
# 商品库里没有独立字段，头型写在商品名里（「内六角圆柱头」「内六角沉头」「外六角」），
# 所以按族比较。内六角族只认「内六角」：裸「沉头」是头部形状，不等于内六角，不参与判断。
# 顺序有讲究：先判外六角，因为「内六角」里也含「六角」。
HEAD_WORDS = {
    "外六角": ("外六角", "六角头"),
    "内六角": ("内六角",),
}

# 否定词：直接作用在头型词上时，该头型族算「被排除」。
# 「除了外六角都行」「别给我外六角」「我不太想要外六角」都靠这里识别。
_NEGATION_WORDS = (
    "不要", "不用", "不需要", "无需", "别用", "别给", "不是", "非",
    "除了", "不太想", "不太想要", "不想要",
)

# 放宽词：两族同时点名且出现这些词时，头型不作为约束；整句只有放宽词时清掉历史头型
_RELAX_WORDS = ("都行", "都可以", "都接受", "都ok", "无所谓", "哪种都", "不限", "随便", "都要")

# 否定词与头型词之间允许夹的连词（「外六角和内六角都不要」）
_HEAD_CONNECTORS = set("和与及、都也还就")
# 否定词后允许夹的填充词（「别给我外六角」）
_HEAD_FILLERS = set("我你给要用来拿选想")

# 子句分隔：放宽判定只看同一子句，避免「数量不限」这种跨句误伤
_CLAUSE_SPLIT = re.compile(r"[，,。；;！!？?\n]+")


def _clauses(text: str) -> list[str]:
    """按中文标点切子句。"""
    return [c.strip() for c in _CLAUSE_SPLIT.split(text or "") if c.strip()]


# 头型词后面跟「的 + 属性」时是修饰语（「外六角的价格」「内六角的交期」），不算点名
_HEAD_ATTRIBUTE_WORDS = ("价格", "价", "数量", "预算", "交期", "运费", "贵", "便宜", "多", "少")


def _is_head_modifier(text: str, after: str) -> bool:
    """头型词后面是不是「的 + 价格/数量/交期」这类属性修饰语。"""
    if not after.startswith("的"):
        return False
    rest = after[1:]
    return any(rest.startswith(w) for w in _HEAD_ATTRIBUTE_WORDS)


def _negated_heads(text: str) -> list[str]:
    """收集被否定词直接作用到的头型族（按出现顺序）。

    revision 4 起不再「子句里出现否定词就排除该子句全部头型」，改为看否定词与头型词的
    邻接关系：否定词后跳过填充词紧跟的头型算排除；否定词前跳过连词与头型词收集到的族
    也算（「外六角和内六角都不要」）。中间隔着「价格」「数量」这类非连词时不算，
    所以「外六角的价格不要太贵」不会误判成排除外六角。
    """
    hit: list[str] = []
    all_words = [(head, w) for head, words in HEAD_WORDS.items() for w in words]
    for neg in _NEGATION_WORDS:
        start = 0
        while True:
            idx = text.find(neg, start)
            if idx < 0:
                break
            start = idx + len(neg)
            # 后向：否定词后面紧跟的头型词
            j = idx + len(neg)
            while j < len(text) and text[j] in _HEAD_FILLERS:
                j += 1
            for head, w in all_words:
                if text.startswith(w, j) and head not in hit:
                    hit.append(head)
            # 前向：否定词前面，跳过连词与头型词
            pos = idx
            while pos > 0:
                pos -= 1
                if text[pos] in _HEAD_CONNECTORS:
                    continue
                matched = None
                matched_len = 0
                for head, w in all_words:
                    if pos + 1 - len(w) >= 0 and text[pos + 1 - len(w):pos + 1] == w:
                        matched = head
                        matched_len = len(w)
                        break
                if matched:
                    if matched not in hit:
                        hit.append(matched)
                    # 跳过整个头型词，继续往前找并列的族
                    pos = pos + 1 - matched_len
                    continue
                break
    # 按族在文本里第一次出现的位置排序，避免并列双否定返回顺序和原句不一致
    order: dict[str, int] = {}
    for idx, head in _heads_by_position(text):
        order.setdefault(head, idx)
    hit.sort(key=lambda h: order.get(h, len(text)))
    return hit


def _heads_by_position(text: str) -> list[tuple[int, str]]:
    """按出现位置列出头型词，用于「最近一次表态」取值。

    「外六角的价格」「内六角的交期」这类是修饰语，不算点名要这一族，跳过。
    """
    found: list[tuple[int, str]] = []
    for head, words in HEAD_WORDS.items():
        for w in words:
            start = 0
            while True:
                idx = text.find(w, start)
                if idx < 0:
                    break
                start = idx + len(w)
                if _is_head_modifier(text, text[idx + len(w):]):
                    continue
                found.append((idx, head))
    found.sort()
    return found


def _tagged_heads(text: str) -> tuple[list[str], list[str]]:
    """扫描文本里的头型词，返回 (点名的族, 被排除的族)。

    按出现顺序返回，点名的族里不含被否定的；两族都可能同时出现在两个列表之一。
    """
    negated = _negated_heads(text)
    mentioned: list[str] = []
    for _, head in _heads_by_position(text):
        if head in negated or head in mentioned:
            continue
        mentioned.append(head)
    return mentioned, negated


def _clause_relaxed(text: str) -> bool:
    """放宽词是否与头型词出现在同一子句（「外六角内六角都行」）。"""
    for clause in _clauses(text):
        if not any(w in clause for w in _RELAX_WORDS):
            continue
        if any(any(w in clause for w in words) for words in HEAD_WORDS.values()):
            return True
    return False


def _bare_relax(text: str) -> bool:
    """整句只有放宽词时才算「头型不限」；「数量不限」「价格随便」不算。"""
    rest = text.strip()
    for w in _RELAX_WORDS:
        rest = rest.replace(w, "")
    rest = re.sub(r"[，,。；;！!？?\s]+", "", rest)
    return rest in ("", "头型", "都", "哪个", "哪种")


def extract_head(text: str) -> str | None:
    """提取用户点名的头型族；没点名头型时返回 None，后续不做头型判定。

    同句改口按出现顺序取最近一次表态（「要外六角，改成内六角」→ 内六角）；
    否定语境（「不要外六角」）不算点名；两族都点名且带放宽词时也不作约束。
    """
    mentioned, _ = _tagged_heads(text)
    named = set(mentioned)
    if len(named) == 2 and _clause_relaxed(text):
        return None
    if _bare_relax(text):
        return None
    return mentioned[-1] if mentioned else None


def excluded_heads(text: str) -> tuple[str, ...]:
    """提取用户明确排除的头型族，和 extract_head 互补。

    只有没点名要哪一族时才参与判定：「除了外六角都行」「不要外六角了」
    「外六角和内六角都不要」都在这里表达。点名了某族时排除只是衬句，忽略。
    """
    mentioned, negated = _tagged_heads(text)
    if mentioned:
        return ()
    return tuple(negated)


def head_explicit(text: str) -> bool:
    """文本是否对头型做了明确表态：点名某一族、明确排除，或单纯放宽。

    用来区分「没提头型」和「明确不要某个头型」，后者合并历史画像时不能被旧值盖回去。
    """
    mentioned, negated = _tagged_heads(text)
    named = set(mentioned)
    if len(named) == 2 and _clause_relaxed(text):
        return True
    if not named and not negated and _bare_relax(text):
        return True
    return bool(named) or bool(negated)


# 意图判断用的词表。品类名本身也算——用户会直接说「我要紧固件」
_ALL_CATEGORY_WORDS = tuple(
    [w for words in CATEGORY_WORDS.values() for w in words] + list(CATEGORY_WORDS.keys())
)
_ALL_MATERIAL_WORDS = tuple(w for words in MATERIAL_WORDS.values() for w in words)
BUY_WORDS = ("买", "采购", "要", "需要", "找", "询价", "报价", "订货", "下单", "有没有")
KNOWLEDGE_WORDS = ("是什么", "什么是", "怎么选", "怎么挑", "有什么区别", "区别", "为什么", "怎么用", "介绍一下", "原理")
CHAT_WORDS = (
    "你好", "您好", "在吗", "hello", "hi", "谢谢", "感谢", "再见", "你是谁", "你叫什么",
    "几点", "日期", "几号", "星期几", "天气", "笑话", "唱歌", "累", "困", "无聊", "吃饭",
)

# 商品库只收录紧固件 / 轴承 / 电气元件，这些词命中时说明用户问的是库外品类
OUT_OF_SCOPE_WORDS = (
    "工具", "扳手", "螺丝刀", "起子", "钳子", "老虎钳", "尖嘴钳", "锤子", "卷尺",
    "游标卡尺", "千分尺", "量具", "电钻", "钻头", "切割片", "砂纸", "焊条", "焊机",
    "劳保", "手套", "安全帽", "工作服", "工具包", "工具箱", "电动工具", "气动工具",
    "套筒", "批头",
)

# 口语别称归一：先把用户说法换成词表里的标准写法，再做解析
# 替换后的词必须保住品类关键词（如「球轴承」要替成「深沟球轴承」而不是「深沟球」）
SYNONYMS = {
    "空气开关": "断路器",
    "空开": "断路器",
    "电源模块": "开关电源",
    "杯头": "内六角",
    "圆柱头": "内六角",
    "球轴承": "深沟球轴承",
    "轴成": "轴承",
    "罗丝": "螺丝",
}


def normalize(text: str) -> str:
    """把口语别称替换成标准写法。只替已知词，不改变其它内容。"""
    for k, v in SYNONYMS.items():
        if k in text and v not in text:
            text = text.replace(k, v)
    return text


def extract_params(query: str) -> dict:
    """提取可硬过滤的参数。多轮合并时取最后一次出现的值。"""
    params = {}
    hits = re.findall(r"内径\s*(\d+(?:\.\d+)?)", query)
    if hits:
        params["size"] = f"{hits[-1]}mm"
    hits = re.findall(r"长度\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)?", query)
    if hits:
        params["length"] = f"{hits[-1]}mm"
    # 大小写都认：用户常直接输「m8」，只认大写会把规格当成没填
    # 「M8×30」这种写法同时给出螺纹规格和长度，一次抽两个
    pair = re.findall(r"(?<![A-Za-z])[Mm](\d+)\s*[×xX*]\s*(\d+)", query)
    if pair:
        params["spec_m"] = f"M{pair[-1][0]}"
        params["length"] = f"{pair[-1][1]}mm"
    else:
        hits = re.findall(r"(?<![A-Za-z])[Mm](\d+)(?![0-9])", query)
        if hits:
            params["spec_m"] = f"M{hits[-1]}"
    hits = re.findall(r"\d+(?:\.\d+)?\s*(?:V|伏|A|安)\b", query)
    if hits:
        params["electrical"] = hits[-1].strip()
    # 已经有螺纹规格、这轮又没说内径时，裸写的「50mm」按长度算
    # 限定「有 spec_m 且无 size」是为了不把「内径 20mm」误当长度
    if "spec_m" in params and "length" not in params and "size" not in params:
        bare = re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:mm|毫米)", query)
        if bare:
            params["length"] = f"{bare[-1]}mm"
    return params


def detect_intent(query: str) -> str:
    """规则快速判断意图，返回 "purchase" | "chat" | "unknown"。

    规则判不出来才返回 unknown，交给 LLM 兜底，避免把正常采购问句误判成闲聊。
    """
    text = normalize(query.strip())

    # 命中库外品类词（工具、劳保等）说明用户想买但库里没有，按采购走，交给 out_of_scope 分支回应
    if any(w in text for w in OUT_OF_SCOPE_WORDS):
        return "purchase"

    has_category = any(w in text for w in _ALL_CATEGORY_WORDS)
    has_param = bool(extract_params(text))
    has_material = any(w in text for w in _ALL_MATERIAL_WORDS)
    has_attr = bool(extract_attrs(text))
    has_qty = bool(re.search(rf"\d+\s*(?:{'|'.join(UNIT_WORDS)})", text))
    has_buy = any(w in text for w in BUY_WORDS)

    if has_category and (has_param or has_material or has_attr or has_qty or has_buy):
        return "purchase"
    if has_category and any(w in text for w in KNOWLEDGE_WORDS):
        return "chat"
    if any(w in text for w in CHAT_WORDS):
        return "chat"
    return "unknown"


# 当前句看起来是在独立提问时，不并入上一轮
_QUESTION_MARKS = ("?", "？", "吗", "什么", "怎么", "为什么", "哪个", "哪些", "哪类", "多少钱")


def merge_with_history(query: str, history: list | None) -> str | None:
    """把「追问后的补充句」与上一轮用户原话拼起来，交给同一套规则解析。

    只有当前句不含品类、不含库外品类、不像闲聊或独立提问，且上一轮说过品类时才合并。
    返回合并后的 query；不需要合并时返回 None，调用方按单轮处理。
    """
    text = (query or "").strip()
    if not text:
        return None
    if any(w in text for w in _ALL_CATEGORY_WORDS):
        return None
    if any(w in text for w in OUT_OF_SCOPE_WORDS):
        return None
    if any(w in text for w in CHAT_WORDS):
        return None
    if any(w in text for w in _QUESTION_MARKS):
        return None

    parts: list[str] = []
    for msg in reversed(history or []):
        if msg.get("role") != "user":
            continue
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        parts.append(content)
        # 找到最近一条带品类的原话就停：再往前的轮次和当前需求无关
        if any(w in content for w in _ALL_CATEGORY_WORDS):
            break
        if len(parts) >= 3:
            break
    if not any(any(w in p for w in _ALL_CATEGORY_WORDS) for p in parts):
        return None
    # 中间几轮补的参数（「对，m8」）也要带上，否则合并后还是缺规格
    return f"{' '.join(reversed(parts))} {text}"


def _head_from_users(users: list[str]) -> tuple[str | None, tuple[str, ...]]:
    """按时间倒序找最近一次明确的头型表态。

    返回 (要的族, 排除的族)。最近一句点名了某一族就取它；明确排除时累积前面几轮的
    排除族（「不要外六角」+「内六角也不要」两族都排除）；两族放宽或单纯说「随便」
    时返回 None，用来清除更早的旧头型。全程没提过头型也返回 (None, ())。
    """
    excluded: list[str] = []
    for text in reversed(users):
        norm = normalize(text)
        mentioned, negated = _tagged_heads(norm)
        named = set(mentioned)
        if len(named) == 2 and _clause_relaxed(norm):
            return None, ()
        if mentioned:
            return mentioned[-1], ()
        if negated:
            for head in negated:
                if head not in excluded:
                    excluded.insert(0, head)
            continue
        if _bare_relax(norm):
            # 只说「随便 / 哪个都行」：头型不限
            return None, ()
    return (None, tuple(excluded)) if excluded else (None, ())


def history_demand(history: list | None, limit: int = 4) -> dict | None:
    """把历史里最近几条用户原话依次解析并累积，得到「目前已经知道什么」的画像。

    当前句是元对话（如「问题一个一个来」「不对」）时用它继承上下文，避免从零重新问品类。
    """
    users = [
        str(m.get("content", "")).strip()
        for m in (history or [])
        if m.get("role") == "user" and str(m.get("content", "")).strip()
    ][-limit:]
    # 头型单独按「最近一次明确表态」取值，不从累积文本里取：
    # 累积文本按顺序会先命中外六角，用户改成内六角后仍保留旧值，后续只说数量也会继承错误
    latest_head, latest_excluded = _head_from_users(users)
    acc_text = ""
    acc = None
    for text in users:
        acc_text = f"{acc_text} {text}".strip()
        # 参数用累积文本解析，才能跨句生效（先「m8」再「30mm」，长度要看得到 M 号）
        d = parse_demand(acc_text)
        # 品类用单句判断，避免用户改口换品类时被前面的旧品类盖住
        single = parse_demand(text)
        if acc is None:
            acc = {
                "category": single["category"],
                "material": d["material"],
                "head": latest_head,
                "head_excluded": latest_excluded,
                "process": d.get("process"),
                "origin": d.get("origin"),
                "industry": d.get("industry"),
                "params": dict(d["params"]),
                "quantity": d["quantity"],
            }
            continue
        # 后说的覆盖先说的，用户改口时以最新为准
        if single["category"]:
            acc["category"] = single["category"]
        if d["material"]:
            acc["material"] = d["material"]
        for key in ("process", "origin", "industry"):
            if d.get(key):
                acc[key] = d[key]
        acc["params"].update(d["params"])
        if d["quantity"]:
            acc["quantity"] = d["quantity"]
    return acc


def merge_demand(current: dict, prev: dict | None) -> dict:
    """当前句没带品类时，继承历史画像里的品类/材质/参数/数量，再重算缺参。"""
    if not prev or current["category"] or not prev.get("category"):
        return current

    merged = dict(current)
    merged["category"] = prev["category"]
    merged["material"] = current["material"] or prev.get("material")
    # 当前句明确表态时以当前为准；纯否定要累积历史排除族，只有放宽才清空
    if current.get("head_explicit"):
        merged["head"] = current.get("head")
        if current.get("head_relaxed"):
            merged["head_excluded"] = ()
        elif current.get("head"):
            merged["head_excluded"] = tuple(current.get("head_excluded") or ())
        else:
            prev_excluded = tuple(prev.get("head_excluded") or ())
            merged["head_excluded"] = tuple(
                dict.fromkeys([*prev_excluded, *(current.get("head_excluded") or ())])
            )
    else:
        merged["head"] = current.get("head") or prev.get("head")
        merged["head_excluded"] = current.get("head_excluded") or prev.get("head_excluded") or ()
    merged["head_relaxed"] = bool(current.get("head_relaxed"))
    for key in ("process", "origin", "industry"):
        merged[key] = current.get(key) or prev.get(key)
    params = dict(prev.get("params") or {})
    params.update(current["params"])
    merged["params"] = params
    merged["quantity"] = current["quantity"] or prev.get("quantity")
    merged["missing"] = _compute_missing(merged["category"], params)
    merged["rewritten_query"] = _build_rewritten(
        merged["category"],
        merged["material"],
        params,
        current["raw_query"],
        {
            "process": merged.get("process"),
            "origin": merged.get("origin"),
            "industry": merged.get("industry"),
        },
    )
    return merged


def _compute_missing(category: str | None, params: dict, has_model: bool = False) -> list[str]:
    """按品类判断还缺哪些关键参数，一次只返回下一个要问的。

    用户已经报出厂家型号（6204-2RS / DZ47-63）时不再追问内径——
    型号比内径更精确，直接按型号召回就行。
    """
    if not category:
        return ["品类（紧固件 / 轴承 / 电气元件）"]
    if category == "紧固件":
        if "spec_m" not in params:
            return ["螺纹规格（如 M8）"]
        if "length" not in params:
            return ["长度（如 30mm）"]
    elif category == "轴承" and "size" not in params and not has_model:
        return ["内径（如 20mm）"]
    return []


# 追问时可点选的标准规格。按行业常用值给，不按库存给：
# 标准规格该有就有，有没有货是另一回事，采购本来就是要问货期的。
CATEGORY_OPTIONS = ["紧固件", "轴承", "电气元件"]
SPEC_OPTIONS = ["M4", "M5", "M6", "M8", "M10", "M12"]
LENGTH_OPTIONS = ["10mm", "15mm", "20mm", "30mm", "40mm", "50mm", "60mm"]
BORE_OPTIONS = ["8mm", "10mm", "12mm", "15mm", "20mm", "25mm", "30mm"]


def clarify_options(demand: dict) -> list[str]:
    """按还缺的那一项给出可点选的标准规格，让用户少打字。"""
    missing = demand.get("missing") or []
    if not missing:
        return []
    head = missing[0]
    if head.startswith("品类"):
        return list(CATEGORY_OPTIONS)
    if head.startswith("螺纹规格"):
        return list(SPEC_OPTIONS)
    if head.startswith("长度"):
        return list(LENGTH_OPTIONS)
    if head.startswith("内径"):
        return list(BORE_OPTIONS)
    return []


def _build_rewritten(
    category: str | None,
    material: str | None,
    params: dict,
    text: str,
    attrs: dict | None = None,
) -> str:
    """拼检索用的改写 query：标准品类 + 材质 + 关键参数 + 工艺产地行业 + 原句。"""
    attrs = attrs or {}
    parts = [category or "", material or ""]
    if "spec_m" in params:
        parts.append(params["spec_m"])
    elif "size" in params:
        parts.append(f"内径 {params['size']}")
    if "length" in params:
        parts.append(f"长度 {params['length']}")
    parts.append(attrs.get("process") or "")
    parts.append(attrs.get("origin") or "")
    parts.append(attrs.get("industry") or "")
    parts.append(text)
    return " ".join(p for p in parts if p)


def parse_demand(query: str) -> dict:
    """解析用户需求。"""
    text = normalize(query)

    category = None
    for cat, words in CATEGORY_WORDS.items():
        if cat in text or any(w in text for w in words):
            category = cat
            break

    material = None
    for mat, words in MATERIAL_WORDS.items():
        if any(w in text for w in words):
            material = mat
            break

    params = extract_params(text)
    attrs = extract_attrs(text)

    # 轴承：用户接在追问后面只写裸尺寸（「25mm」）时，按内径算。
    # 限定 category == 轴承，是为了不跟螺丝「裸 50mm 算长度」的规则打架；
    # 负向前瞻排除 M8×30 里的 30。
    if category == "轴承" and "size" not in params:
        bare = re.findall(r"(?<![\d.×xX*])(\d+(?:\.\d+)?)\s*(?:mm|毫米)", text)
        if bare:
            params["size"] = f"{bare[-1]}mm"

    qty = None
    qty_matches = re.findall(rf"(\d+)\s*(?:{'|'.join(UNIT_WORDS)})", text)
    if not qty_matches:
        # 拆分器和图片识别拼出来的行是「数量 1000」，没有单位
        qty_matches = re.findall(r"数量\s*(\d+)", text)
    if qty_matches:
        # 多轮合并时后面的数量才是用户新补充的，取最后一个
        qty = int(qty_matches[-1])

    missing = _compute_missing(category, params, has_model=bool(extract_model(text)))

    # 用户说的是库外品类（工具 / 劳保等），单独标记，避免被当成「缺品类」反复追问
    out_of_scope = [w for w in OUT_OF_SCOPE_WORDS if w in text]

    # 检索用的改写 query
    rewritten = _build_rewritten(category, material, params, text, attrs)

    return {
        "raw_query": query,
        "category": category,
        "material": material,
        "head": extract_head(text),
        "head_excluded": excluded_heads(text),
        "head_explicit": head_explicit(text),
        "head_relaxed": _bare_relax(text) or _clause_relaxed(text),
        "process": attrs.get("process"),
        "origin": attrs.get("origin"),
        "industry": attrs.get("industry"),
        "city": extract_city(text),
        "params": params,
        "quantity": qty,
        "missing": missing,
        "out_of_scope": out_of_scope,
        "rewritten_query": rewritten,
    }


# 多需求：一句话里可能同时要几个规格、几个品类。
# 判据不用「和」字——「304 和 316 的 M8 螺丝」只有一个 M 号，是一个需求。
# 用「不同 M 号的数量」和「不同品类的数量」，宁可漏判交给 LLM，也不要随手切错。
_ROW_SPLIT = re.compile(r"[,，、]|以及|和|与")
_SHARE_WORDS = ("各", "分别", "都要", "每种", "各要")
_QTY_RE = re.compile(r"(\d+)\s*(?:个|件|只|根|片|套|台|米)")


def looks_multi(text: str) -> bool:
    """粗判是否可能是两条以上需求。

    三种信号：不同 M 号、不同品类、不同内径/长度值（25mm 和 30mm 是两条需求）。
    「M8×30 的 30」是长度不是内径，用负向前瞻排除掉。
    """
    specs = set(re.findall(r"(?<![A-Za-z])[Mm](\d+)(?![0-9])", text))
    if len(specs) >= 2:
        return True
    cats = {c for c, words in CATEGORY_WORDS.items() if c in text or any(w in text for w in words)}
    if len(cats) >= 2:
        return True
    # 裸写的多个尺寸值：25mm, 30mm
    sizes = set(re.findall(r"(?<![\d.×xX*])(\d+(?:\.\d+)?)\s*(?:mm|毫米)", text))
    return len(sizes) >= 2


def split_rows_by_rule(text: str) -> list[str]:
    """规则切分兜底：按逗号/顿号/和/与 切段，再补齐公共品类和「各」的数量。"""
    parts = [p.strip() for p in _ROW_SPLIT.split(text) if p.strip()]
    if len(parts) < 2:
        return []
    cats = [c for c, words in CATEGORY_WORDS.items() if c in text or any(w in text for w in words)]
    global_cat = cats[0] if len(cats) == 1 else ""
    share = any(w in text for w in _SHARE_WORDS)
    qty_hits = _QTY_RE.findall(text)
    share_qty = qty_hits[0] if (share and len(qty_hits) == 1) else ""
    rows = []
    for part in parts:
        seg = part
        if global_cat and global_cat not in seg and not any(w in seg for w in CATEGORY_WORDS[global_cat]):
            seg = f"{global_cat} {seg}"
        if share_qty and not _QTY_RE.search(seg):
            seg = f"{seg} {share_qty} 个"
        rows.append(seg)
    return rows
