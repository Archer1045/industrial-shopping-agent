"""FastAPI 入口。"""
import json
import os
import queue
import re
import sys
import tempfile
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import llm, orchestration, prompts, understand
from .db import get_conn
from .demand import (
    clarify_options,
    detect_intent,
    history_demand,
    looks_multi,
    merge_demand,
    merge_with_history,
    normalize,
    parse_demand,
    split_rows_by_rule,
)
from .excel import parse_rows
from .rag import index_manager
from .rag.index import build_index
from .rag.retriever import hybrid_search
from .sessions import (
    add_feedback,
    append_message,
    create_session,
    delete_session,
    feedback_stats,
    get_session,
    history_of,
    init_tables,
    list_sessions,
)
from .vision import image_to_items

STATE: dict = {}

# 主链路就是状态图。旧实现与临时开关已删除。
GRAPH = None


def _answer(
    q: str,
    history: list | None = None,
    top_k: int = 5,
    debug: bool = False,
    on_stage=None,
    on_delta=None,
    on_reset=None,
    is_cancelled=None,
) -> dict:
    """主链路：交给状态图。取消由节点里的闸门抛出，穿透 graph.invoke 交给上层。"""
    if GRAPH is None:
        raise RuntimeError("状态图未初始化")
    # 回调与取消闸门走 RunnableConfig，不进 State（State 将来可能被 checkpoint 序列化）
    hooks = {
        "on_stage": on_stage,
        "on_delta": on_delta,
        "on_reset": on_reset,
        "is_cancelled": is_cancelled,
    }
    final = GRAPH.invoke(
        {
            "query": q,
            "raw_query": q,
            "history": history,
            "top_k": top_k,
            "debug": debug,
        },
        config={"configurable": {"hooks": hooks}},
    )
    result = final.get("result")
    if not result:
        raise RuntimeError("状态图没有产出结果")
    return result


def _classify_intent(q: str) -> str:
    """规则判不出来时交给 LLM。LLM 出错按采购处理，保持原有行为。"""
    try:
        text = llm.chat(prompts.intent_messages(q), temperature=0, max_tokens=8, timeout=15)
        if "chat" in text.lower():
            return "chat"
    except Exception:
        pass
    return "purchase"


def _rewrite_query(q: str, history: list | None, demand: dict) -> str | None:
    """LLM 改写检索 query。只影响召回，硬过滤仍用规则解析出的参数。"""
    if not llm.API_KEY:
        return None
    try:
        text = llm.chat(
            prompts.rewrite_messages(q, demand, history), temperature=0, max_tokens=80, timeout=20
        )
    except Exception:
        return None
    text = text.strip().strip('"').strip("'").strip()
    text = re.sub(r"^(改写|查询|检索)[:：]\s*", "", text)
    if not text or len(text) > 120:
        return None
    return text


def _products_block(results: list[dict]) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        price = f"¥{r['price']}/{r['unit']}" if r["price"] is not None else "价格待询"
        attrs = " | ".join(
            f"{label} {r[key]}"
            for key, label in (
                ("material", "材质"),
                ("spec", "规格"),
                ("model", "型号"),
                ("process", "工艺"),
                ("origin", "产地"),
                ("industry", "适用行业"),
            )
            if r.get(key) and r[key] != "-"
        )
        lines.append(
            f"{i}. {r['name']} | 品牌 {r['brand'] or '-'} | {attrs} | {price} | "
            f"MOQ {r['moq']} | 交期 {r['lead_time']} 天 | {r['description'] or ''}"
        )
    return "\n".join(lines)


def _with_city_note(reply: str, demand: dict) -> str:
    """用户点名产地城市时，如实说明库里只记到国产/进口，不自作主张。"""
    city = demand.get("city")
    if not city:
        return reply
    note = f"> 库里产地只记录到「国产 / 进口」，不记具体城市（你提到的是{city}），以下按其它条件推荐。\n\n"
    return note + reply


ADVISORY_NOTE = (
    "【通用提示】以上价格、MOQ、交期为候选信息，下单前请与供应商核对；"
    "税率、账期、运费以实际结算为准；如需备损，建议按用量加订 3%~5% 并确认是否可拆零。"
)


def _with_advisory(reply: str) -> str:
    """通用提示由系统统一追加，正文只保留可核对的事实。"""
    return reply.rstrip() + "\n\n---\n\n" + ADVISORY_NOTE


def _template_reply(results: list[dict], demand: dict) -> str:
    lines = ["按你的需求，找到这些："]
    for i, r in enumerate(results, 1):
        price = f"¥{r['price']}/{r['unit']}" if r["price"] is not None else "价格待询"
        lines.append(
            f"{i}. {r['name']}（{r['brand'] or '-'}）{price}，MOQ {r['moq']}，交期 {r['lead_time']} 天"
        )
    if demand.get("quantity"):
        lines.append(f"\n需求数量 {demand['quantity']}，注意核对起订量。")
    return "\n".join(lines)


def _warmup_reranker() -> None:
    """后台预热精排模型，失败只打印，不影响服务。"""
    try:
        from .rag import reranker

        reranker.warmup()
    except Exception as exc:  # noqa: BLE001
        print(f"[reranker] 预热失败：{exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global GRAPH
    init_tables()
    STATE.update(build_index())
    # 状态图在启动时编译一次，之后每轮请求复用它，State 按请求新建
    GRAPH = orchestration.build_graph(sys.modules[__name__])
    # 精排模型在后台线程预热：第一次查询就不用等十几秒加载
    threading.Thread(target=_warmup_reranker, daemon=True).start()
    yield
    STATE.clear()
    GRAPH = None


app = FastAPI(title="Industrial Shopping Agent", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"ok": True, "products": len(STATE.get("rows", [])), "llm": bool(llm.API_KEY)}


@app.get("/api/categories")
def categories():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) AS n FROM products GROUP BY category ORDER BY n DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/index/status")
def index_status():
    """索引状态：商品数、最后同步时间、模型标识、向量维度、持久化是否可用。"""
    return index_manager.status()


@app.post("/api/index/sync")
def index_sync():
    """按内容哈希做一次增量同步，成功后整体替换内存索引。"""
    try:
        index = index_manager.sync()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"索引同步失败：{exc}") from exc
    STATE.update(index)
    return {
        "products": index["products"],
        "added": index["added"],
        "modified": index["modified"],
        "deleted": index["deleted"],
        "encoded": index["encoded"],
        "reused": index["reused"],
        "synced_at": index.get("synced_at"),
    }


@app.get("/api/search")
def search(q: str, top_k: int = 10):
    demand = parse_demand(q)
    if demand["missing"]:
        return {"query": q, "demand": demand, "missing": demand["missing"], "count": 0, "items": []}
    results = hybrid_search(
        demand["rewritten_query"], STATE, top_k=top_k, constraints=demand["params"]
    )
    return {"query": q, "demand": demand, "missing": [], "count": len(results), "items": results}


class ChatIn(BaseModel):
    q: str
    history: list[dict] = Field(default_factory=list)
    session_id: str | None = None


class FeedbackIn(BaseModel):
    message_id: int
    rating: str


def _parse_json(text: str) -> dict:
    """从 LLM 输出里取 JSON 对象，容忍 ```json 围栏和前后多余的话。"""
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[-1]
        body = body.rsplit("```", 1)[0]
    left, right = body.find("{"), body.rfind("}")
    if left < 0 or right <= left:
        return {}
    try:
        data = json.loads(body[left : right + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


_CATEGORY_ALIAS = {"紧固件": "螺丝", "轴承": "轴承", "电气元件": "电气元件"}


def _row_query(item: dict) -> str:
    """把拆分器给出的结构化行拼成一句能被 parse_demand 解析的话。

    优先用商品名（「螺丝 M8」比「紧固件 M8」更接近用户说法，检索也准得多）。
    """
    name = str(item.get("name") or "").strip()
    category = str(item.get("category") or "").strip()
    head = name or _CATEGORY_ALIAS.get(category, category)
    parts = [
        head,
        str(item.get("material") or ""),
        str(item.get("spec") or ""),
    ]
    quantity = item.get("quantity")
    if quantity:
        parts.append(f"数量 {quantity}")
    return " ".join(p for p in parts if p)


def _multi_rows(query: str, history: list | None = None) -> list[str]:
    """判成多需求时拆成几行；拆不出来返回空列表，交给单需求流程。

    拆出来的行常常只有值没有品类（用户接在追问后面只回「25mm, 30mm」），
    所以带上历史：哪一行缺品类，就用上一轮聊过的品类补上。
    """
    if not looks_multi(query):
        return []
    rows: list[str] = []
    if llm.API_KEY:
        try:
            text = llm.chat(prompts.split_messages(query), temperature=0, max_tokens=400, timeout=20)
            for item in _parse_json(text).get("rows") or []:
                if isinstance(item, dict):
                    seg = _row_query(item)
                    if seg:
                        rows.append(seg)
        except Exception:  # 拆分失败走规则兜底，不中断对话
            rows = []
    if len(rows) < 2:
        rows = split_rows_by_rule(query)
    if len(rows) < 2:
        return []
    prev = history_demand(history)
    cat = (prev or {}).get("category")
    if cat:
        patched = []
        for row in rows:
            if parse_demand(row)["category"]:
                patched.append(row)
            else:
                patched.append(f"{cat} {row}")
        rows = patched
    return rows


def _multi_row_text(demand: dict, verdict: dict, items: list[dict]) -> str:
    """多需求表格里的展示文案。

    状态统一由 evaluate_row() 给，这里只负责换成人话，不改判断。
    """
    status = verdict["status"]
    if status == "out_of_scope":
        return "不在收录范围（只做紧固件 / 轴承 / 电气元件）"
    if status == "missing_category":
        return "没看出是哪类，补充品类后我再找"
    if status == "missing_param" and items:
        # 多行里逐行追问会把用户绕晕，先按已有参数给参考候选，标清楚缺什么
        lack = "、".join(m.split("（")[0] for m in demand["missing"])
        return f"参数不全（缺{lack}），以下为参考，暂不可下单"
    return verdict["text"]


def _multi_reply(rows: list[str], top_k: int) -> dict:
    """多需求：逐行解析 + 检索，结果按行返回，前端画表格。"""
    out = []
    for idx, row in enumerate(rows, start=1):
        demand = parse_demand(row)
        items: list[dict] = []
        # 库外和缺品类的行不去检索，给候选只会误导
        if demand["category"] and not demand["out_of_scope"]:
            items = hybrid_search(
                demand["rewritten_query"], STATE, top_k=min(top_k, 3), constraints=demand["params"]
            )
        verdict = evaluate_row(demand, items)
        out.append(
            {
                "row_no": idx,
                "query": row,
                "names": [p["name"] for p in items[:1]],
                "items": items,
                "note": _multi_row_text(demand, verdict, items),
                "status": verdict["status"],
            }
        )
    hit = sum(1 for r in out if r["items"])
    summary = f"共 {len(out)} 条需求，匹配到 {hit} 条"
    if hit < len(out):
        summary += f"，{len(out) - hit} 条需要补充或换货"
    return {
        "reply": f"{summary}。明细在右侧。",
        "demand": None,
        "items": [],
        "rows": out,
        "summary": summary,
        "stage": "multi",
    }


def _notify(callback, value) -> None:
    """回调只用于流式进度，前端断开或出错不能影响主链路。"""
    if callback is None:
        return
    try:
        callback(value)
    except Exception:  # noqa: BLE001
        pass


def _raise_if_cancelled(is_cancelled) -> None:
    """客户端断开后立刻中止本轮。

    用在阶段切换和落库之前：只有 on_delta 检查是不够的，
    chat/clarify/multi 这些没有 delta 的分支，以及推荐流结束后到落库之间，
    都可能已经断开却仍然把消息写进库。
    """
    if is_cancelled is not None and is_cancelled():
        raise _StreamCancelled()


def _payload_of(result: dict) -> dict | None:
    """把前端要渲染的内容精简后存库，刷新后卡片和表格还能画出来。"""
    payload: dict = {}
    if result.get("items"):
        payload["items"] = result["items"]
    if result.get("rows"):
        payload["rows"] = result["rows"]
        payload["summary"] = result.get("summary") or ""
    if result.get("options"):
        payload["options"] = result["options"]
    if result.get("stage"):
        payload["stage"] = result["stage"]
    return payload or None


def _chat(
    q: str,
    history: list | None = None,
    top_k: int = 5,
    session_id: str | None = None,
    debug: bool = False,
    on_stage=None,
    on_delta=None,
    on_reset=None,
    is_cancelled=None,
) -> dict:
    # 会话存在时以库里的历史为准，比前端传上来的更完整
    if session_id:
        history = history_of(session_id) or []
    result = _answer(
        q,
        history,
        top_k,
        debug=debug,
        on_stage=on_stage,
        on_delta=on_delta,
        on_reset=on_reset,
        is_cancelled=is_cancelled,
    )
    if session_id and not debug:
        _notify(on_stage, "saving")
        # 落库是最后一道闸：推荐流刚结束、或者根本没有 delta 的分支，
        # 都可能在这之前就断开了，必须在这里再确认一次
        _raise_if_cancelled(is_cancelled)
        append_message(session_id, "user", q)
        # 返回消息 id，前端拿它给这条回答打好评/差评
        result["message_id"] = append_message(
            session_id, "assistant", result["reply"], _payload_of(result)
        )
    return result


@app.get("/api/chat")
def chat(q: str, top_k: int = 5, debug: bool = False):
    return _chat(q, None, top_k, debug=debug)


@app.post("/api/chat")
def chat_post(payload: ChatIn, top_k: int = 5, debug: bool = False):
    return _chat(payload.q, payload.history, top_k, payload.session_id, debug=debug)


class _StreamCancelled(BaseException):
    """客户端断开时用来打断上游流。

    继承 BaseException，这样业务代码里的 `except Exception` 不会把取消吞掉，
    异常会一路抛回 worker，由它决定不落库。
    """


@app.post("/api/chat/stream")
def chat_stream(payload: ChatIn, top_k: int = 5):
    """SSE 流式对话：先推处理阶段，推荐阶段推真实 token 增量，最后给完整结果。"""

    def event_stream():
        events: queue.Queue = queue.Queue()
        cancelled = threading.Event()
        finished = object()

        def put(event: str, data: dict) -> None:
            if cancelled.is_set():
                return
            events.put((event, data))

        def on_delta(text: str) -> None:
            if cancelled.is_set():
                # 抛给 worker，让 llm.chat_stream 的 finally 关闭上游连接
                raise _StreamCancelled()
            put("delta", {"text": text})

        def worker() -> None:
            try:
                result = _chat(
                    payload.q,
                    payload.history,
                    top_k,
                    payload.session_id,
                    on_stage=lambda name: put("stage", {"stage": name}),
                    on_delta=on_delta,
                    on_reset=lambda reason: put("reset", {"reason": str(reason)}),
                    is_cancelled=cancelled.is_set,
                )
                put("result", result)
            except _StreamCancelled:  # 客户端已断开，不再入队也不再落库
                return
            except Exception as exc:  # noqa: BLE001 - 任何未预期异常都要明确告诉前端
                put("error", {"message": str(exc)})
            finally:
                events.put(finished)

        threading.Thread(target=worker, daemon=True).start()
        try:
            while True:
                item = events.get()
                if item is finished:
                    break
                event, data = item
                yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        finally:
            # 生成器关闭（客户端断开）时打断 worker，避免上游模型流继续跑完
            cancelled.set()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/sessions")
def new_session():
    return create_session()


@app.get("/api/sessions")
def sessions_list():
    return list_sessions()


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str):
    data = get_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="会话不存在")
    return data


@app.delete("/api/sessions/{session_id}")
def session_delete(session_id: str):
    delete_session(session_id)
    return {"ok": True}


@app.post("/api/feedback")
def post_feedback(payload: FeedbackIn):
    """给某条助手回答点赞或点踩。同一条消息重复提交以最后一次为准。"""
    try:
        saved = add_feedback(payload.message_id, payload.rating)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not saved:
        raise HTTPException(status_code=404, detail="消息不存在")
    return saved


@app.get("/api/feedback/stats")
def get_feedback_stats():
    return feedback_stats()


@app.get("/api/products/{product_id}")
def product_detail(product_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not row:
        return {"error": "not found"}
    return dict(row)


EXCEL_SUFFIX = (".xlsx", ".xlsm")
IMAGE_SUFFIX = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


# 商品名里常见的头型写法，从具体到泛化排列，供 product_head 取第一个命中的。
HEAD_LABELS = ("内六角圆柱头", "内六角沉头", "平头内六角", "外六角", "内六角")


def product_head(name: str) -> tuple[str | None, str | None]:
    """从商品名读头型，返回 (族, 具体写法)；名里没写头型时返回 (None, None)。

    库里头型只存在于商品名，没有独立字段，所以这里按名字匹配；
    匹配不到就当成「库里没说」，不参与冲突判断，避免误伤。
    """
    for label in HEAD_LABELS:
        if label in name:
            family = "外六角" if label == "外六角" else "内六角"
            return family, label
    return None, None


def _attr_conflicts(demand: dict, product: dict) -> list[str]:
    """用户明确要求、但商品不满足的软属性，逐条说明原因。

    产地/品牌/材质/工艺/行业/头型只做软排序不硬删，代价是可能推出不满足要求的商品，
    这里把差异说清楚，避免把替代品写成「可下单」。
    """
    out = []
    want_origin = demand.get("origin")
    if want_origin:
        have = product.get("origin") or ""
        ok = have == want_origin or (want_origin == "进口" and have.startswith("进口"))
        if not ok:
            out.append(f"产地是{have}，不是{want_origin}")
    want_material = demand.get("material")
    if want_material:
        have = product.get("material") or ""
        if want_material not in have:
            out.append(f"材质是{have}，不是{want_material}")
    name = product.get("name") or ""
    want_head = demand.get("head")
    want_excluded = tuple(demand.get("head_excluded") or ())
    if want_head or want_excluded:
        have_family, have_label = product_head(name)
        if want_head and have_family and have_family != want_head:
            out.append(f"头型是{have_label}，不是{want_head}")
        elif not want_head and have_family in want_excluded:
            out.append(f"头型是{have_label}，属于您排除的类型")
    for field, label in (("process", "工艺"), ("industry", "适用行业"), ("brand", "品牌")):
        want = demand.get(field)
        if want and product.get(field) and want not in str(product.get(field)):
            out.append(f"{label}是{product.get(field)}，不是{want}")
    return out


def evaluate_row(demand: dict, items: list[dict]) -> dict:
    """统一的行级判断，按严重程度从高到低排。

    对话多需求、Excel 上传、图片识别三条入口都走这里，
    避免同一行需求在不同入口得到不同结论——尤其是缺关键参数时不能标「可下单」。
    """
    if demand.get("out_of_scope"):
        return {"status": "out_of_scope", "text": "库外品类"}
    if not demand.get("category"):
        return {"status": "missing_category", "text": "缺品类"}
    if demand.get("missing"):
        lack = "、".join(m.split("（")[0] for m in demand["missing"])
        return {"status": "missing_param", "text": f"缺参数（{lack}），暂不可下单"}
    if not items:
        return {"status": "no_match", "text": "没有匹配的商品，需人工找替代"}
    if items[0].get("match_kind") == "alternative":
        detail = "；".join(items[0].get("mismatches") or [])
        text = f"无精确匹配，仅替代：{detail}" if detail else "无精确匹配，仅替代"
        return {"status": "alternative_only", "text": text}
    conflicts = _attr_conflicts(demand, items[0])
    if conflicts:
        return {"status": "attr_conflict", "text": "；".join(conflicts) + "，仅供参考"}
    qty = demand.get("quantity")
    moq = items[0].get("moq")
    if qty and moq and qty < moq:
        return {"status": "below_moq", "text": f"数量 {qty} 低于起订量 {moq}"}
    return {"status": "ok", "text": "可下单"}


def _row_note(demand: dict, results: list[dict]) -> str:
    """给每行一句判断，方便用户一眼看出哪行要人工处理。"""
    return evaluate_row(demand, results)["text"]


def _rows_from_vision(items: list[dict]) -> list[dict]:
    """把图片识别出的商品项拼成检索用的行，结构与 Excel 解析结果对齐。"""
    rows = []
    for idx, item in enumerate(items, start=1):
        parts = [item.get("name"), item.get("spec"), item.get("material")]
        query = " ".join(str(p).strip() for p in parts if p)
        quantity = item.get("quantity")
        if quantity:
            query = f"{query} 数量 {quantity}"
        rows.append({"row_no": idx, "raw": query, "query": query})
    return rows


def _match_rows(items: list[dict]) -> list[dict]:
    """逐行解析需求并检索，不逐行调 LLM，靠规则改写句喂检索。"""
    rows = []
    for item in items:
        demand = parse_demand(item["query"])
        results = []
        if demand["category"] and not demand["out_of_scope"]:
            results = hybrid_search(
                demand["rewritten_query"], STATE, top_k=3, constraints=demand["params"]
            )
        verdict = evaluate_row(demand, results)
        rows.append(
            {
                "row_no": item["row_no"],
                "raw": item["raw"],
                "query": item["query"],
                "names": [r["name"] for r in results],
                "items": results,
                "note": verdict["text"],
                "status": verdict["status"],
            }
        )
    return rows


@app.post("/api/chat/upload")
async def chat_upload(file: UploadFile = File(...), session_id: str | None = Form(None)):
    """上传采购清单（Excel）或商品截图（图片），逐行匹配商品。"""
    filename = file.filename or "upload"
    suffix = os.path.splitext(filename)[1].lower()
    data = await file.read()

    if suffix in EXCEL_SUFFIX:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            tmp.write(data)
            tmp.close()
            parsed = parse_rows(tmp.name)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"解析失败：{exc}") from exc
        finally:
            tmp.close()
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)
        items = parsed["rows"]
        extra = {"header_row": parsed["header_row"], "fallback": parsed["fallback"], "skipped": parsed["skipped"]}
        stage = "excel"
    elif suffix in IMAGE_SUFFIX:
        try:
            vision_items = image_to_items(data, IMAGE_MIME[suffix])
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"图片识别失败：{exc}") from exc
        if not vision_items:
            raise HTTPException(status_code=400, detail="图里没识别到商品清单，换一张清晰点的图试试")
        items = _rows_from_vision(vision_items)
        extra = {}
        stage = "vision"
    else:
        raise HTTPException(status_code=400, detail="只支持 .xlsx / .png / .jpg / .jpeg / .webp 文件")

    rows = _match_rows(items)
    total = len(rows)
    hit = sum(1 for r in rows if r["items"])
    short = sum(1 for r in rows if r["note"].startswith("数量"))
    summary = f"共识别 {total} 行，匹配到 {hit} 行；{total - hit} 行没找到，{short} 行数量低于起订量。"

    result = {
        "stage": stage,
        "file": filename,
        "rows": rows,
        "summary": summary,
        **extra,
    }

    if session_id:
        # 表格只存渲染需要的字段：首推商品 + 状态，避免把完整候选列表写进消息表
        light = {
            "file": filename,
            "summary": summary,
            "rows": [
                {
                    "row_no": r["row_no"],
                    "query": r["query"],
                    "names": r["names"],
                    "items": r["items"][:1],
                    "note": r["note"],
                    "status": r["status"],
                }
                for r in rows
            ],
        }
        verb = "识别完成" if stage == "vision" else "解析完成"
        append_message(session_id, "user", f"上传了 {filename}")
        result["message_id"] = append_message(
            session_id,
            "assistant",
            f"**{filename}** {verb}，{summary}",
            {"excel": light, "stage": stage},
        )
    return result