"""LangGraph 编排层。

把 main._answer() 里串联的分支搬成显式节点。业务逻辑原样复用：
检索、精排、需求解析、推荐提示词都不在这里重写，节点只负责「什么时候调谁」。

回调（stage/delta/reset）和取消闸门通过 `RunnableConfig` 的 `configurable.hooks`
传入，不放进 State —— State 是将来可能被 checkpoint 序列化的东西，函数对象不能进去。
"""

from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph


class ShoppingState(TypedDict, total=False):
    """单轮请求的状态。

    每次 invoke 新建，不跨会话复用，也不含数据库对象。
    回调与取消函数**不在** State 里，见 `_hook()`。
    """

    # 输入
    query: str
    raw_query: str
    history: list
    top_k: int
    debug: bool

    # 中间结果
    understood: dict | None
    intent: str
    rows: list
    demand: dict
    rewritten_query: str
    items: list

    # 最终结果
    result: dict


def _hook(config: RunnableConfig, name: str) -> Any:
    """从 RunnableConfig 取回调。

    回调只在本次请求的调用链上存在，不进 State —— 一旦将来引入 checkpointer，
    State 会被序列化，函数对象既无法序列化也不该被持久化。
    """

    configurable = (config or {}).get("configurable") or {}
    hooks = configurable.get("hooks") or {}
    return hooks.get(name)


def build_graph(deps: Any) -> Any:
    """用注入的依赖编译状态图。

    deps 是 main 模块本身，节点通过它调用共享函数（通知、取消检查、
    理解层、需求解析、检索、推荐）。这样 orchestration 不反向 import main，
    单独测试时可以传一个替身。
    """

    def ok(state: ShoppingState) -> bool:
        return bool(state.get("result"))

    def prepare(state: ShoppingState, config: RunnableConfig) -> dict:
        """理解层 + 本次查询。"""
        deps._notify(_hook(config, "on_stage"), "understanding")
        deps._raise_if_cancelled(_hook(config, "is_cancelled"))

        raw = state["query"]
        history = state.get("history")
        understood = deps.understand.understand(raw, history)

        if state.get("debug"):
            return {
                "understood": understood,
                "result": {
                    "reply": "",
                    "demand": None,
                    "items": [],
                    "stage": "debug",
                    "understand": understood,
                },
            }

        intent = ""
        rows: list = []
        if understood:
            # 模型偶尔会漏字段，这里按「缺了就当没有」处理，不能让它把整轮对话打崩
            intent = understood.get("intent") or ""
            rows = [r["query"] for r in (understood.get("rows") or [])]
            if len(rows) == 1:
                query = rows[0]
            else:
                query = deps.merge_with_history(raw, history) or raw
        else:
            # 追问后的补充句（如「M8 的，1000 个」）与上一轮原话合并后再解析
            query = deps.merge_with_history(raw, history) or raw

        return {"understood": understood, "intent": intent, "rows": rows, "query": query}

    def resolve_intent(state: ShoppingState, config: RunnableConfig) -> dict:
        """规则判意图；判不出来时结合历史，避免元对话被判成闲聊。"""
        if state.get("intent"):
            return {}
        query = state["query"]
        history = state.get("history")
        intent = deps.detect_intent(query)
        if intent == "unknown":
            prev = deps.history_demand(history)
            intent = "purchase" if prev and prev.get("category") else deps._classify_intent(query)
        return {"intent": intent}

    def chat_reply(state: ShoppingState, config: RunnableConfig) -> dict:
        source = "llm"
        reply = "我是工业品采购顾问，想找什么品类、要什么规格和数量，直接说就行。"
        if deps.llm.API_KEY:
            try:
                reply = deps.llm.chat(
                    deps.prompts.chat_messages(state["query"]), temperature=0.6, max_tokens=120
                )
            except Exception as exc:  # LLM 失败时给固定引导，保证演示不中断
                source = f"template (llm error: {exc})"
        return {
            "result": {
                "reply": reply,
                "demand": None,
                "items": [],
                "stage": "chat",
                "source": source,
            }
        }

    def multi_reply(state: ShoppingState, config: RunnableConfig) -> dict:
        return {"result": deps._multi_reply(state["rows"], state.get("top_k") or 5)}

    def parse(state: ShoppingState, config: RunnableConfig) -> dict:
        """单需求：解析 + 继承历史里已经说过的品类与参数。"""
        query = state["query"]
        history = state.get("history")
        demand = deps.parse_demand(query)
        if not demand["category"] and not demand["out_of_scope"]:
            demand = deps.merge_demand(demand, deps.history_demand(history))
        return {"demand": demand}

    def out_of_scope_reply(state: ShoppingState, config: RunnableConfig) -> dict:
        demand = state["demand"]
        query = state["query"]
        words = "、".join(demand["out_of_scope"])
        text = f"目前只收录紧固件、轴承、电气元件三类，{words}这类商品暂时没有。"
        if deps.llm.API_KEY:
            try:
                text = deps.llm.chat(
                    deps.prompts.out_of_scope_messages(query, demand),
                    temperature=0.3,
                    max_tokens=200,
                )
            except Exception:  # LLM 失败时保留模板回复
                pass
        return {"result": {"reply": text, "demand": demand, "items": [], "stage": "out_of_scope"}}

    def clarify_reply(state: ShoppingState, config: RunnableConfig) -> dict:
        demand = state["demand"]
        query = state["query"]
        text = "还差一点信息才能帮你找：" + "；".join(demand["missing"]) + "。"
        if deps.llm.API_KEY:
            try:
                text = deps.llm.chat(
                    deps.prompts.clarify_messages(query, demand),
                    temperature=0.3,
                    max_tokens=200,
                )
            except Exception:  # LLM 失败时保留模板追问
                pass
        return {
            "result": {
                "reply": text,
                "demand": demand,
                "items": [],
                "stage": "clarify",
                "options": deps.clarify_options(demand),
            }
        }

    def retrieve(state: ShoppingState, config: RunnableConfig) -> dict:
        demand = state["demand"]
        query = state["query"]
        top_k = state.get("top_k") or 5
        q_for_search = deps._rewrite_query(
            deps.normalize(query), state.get("history"), demand
        ) or demand["rewritten_query"]
        deps._notify(_hook(config, "on_stage"), "retrieving")
        deps._raise_if_cancelled(_hook(config, "is_cancelled"))
        results = deps.hybrid_search(
            q_for_search, deps.STATE, top_k=top_k, constraints=demand["params"]
        )
        return {"items": results, "rewritten_query": q_for_search}

    def empty_reply(state: ShoppingState, config: RunnableConfig) -> dict:
        return {
            "result": {
                "reply": "没有找到匹配的商品，可以换个说法或放宽参数试试。",
                "demand": state["demand"],
                "items": [],
                "stage": "empty",
            }
        }

    def recommend(state: ShoppingState, config: RunnableConfig) -> dict:
        """生成推荐正文。流式入口由回调决定走 chat_stream 还是 chat。"""
        demand = state["demand"]
        query = state["query"]
        results = state["items"]
        q_for_search = state.get("rewritten_query") or demand["rewritten_query"]
        on_delta = _hook(config, "on_delta")

        source = "template"
        reply = deps._template_reply(results, demand)
        if deps.llm.API_KEY:
            messages = deps.prompts.recommend_messages(
                query, demand, deps._products_block(results)
            )
            deps._notify(_hook(config, "on_stage"), "recommending")
            if on_delta is not None:
                # 流式入口：边生成边把真实增量推给前端，最后用累积文本当权威结果
                chunks: list = []
                try:
                    for piece in deps.llm.chat_stream(messages, temperature=0.3, max_tokens=900):
                        chunks.append(piece)
                        deps._notify(on_delta, piece)
                    streamed = "".join(chunks).strip()
                    if not streamed:
                        raise RuntimeError("流式返回为空")
                    reply = streamed
                    source = "llm"
                except Exception as exc:  # 中途失败：让前端清掉半截文本，改用模板
                    deps._notify(_hook(config, "on_reset"), "stream failed")
                    reply = deps._template_reply(results, demand)
                    source = f"template (stream error: {exc})"
            else:
                try:
                    reply = deps.llm.chat(messages, temperature=0.3, max_tokens=900)
                    source = "llm"
                except Exception as exc:  # LLM 失败时回退模板，保证演示不中断
                    reply = deps._template_reply(results, demand)
                    source = f"template (llm error: {exc})"

        # 没有精确命中时先说清楚：给出的只是替代品，不能当成满足要求的现货
        if results[0].get("match_kind") == "alternative":
            detail = "；".join(results[0].get("mismatches") or [])
            head = (
                f"> 没有完全匹配的规格（{detail}），以下是可替代的候选，下单前请确认是否可用。"
                if detail
                else "> 没有完全匹配的规格，以下是可替代的候选。"
            )
            reply = head + "\n\n" + reply

        return {
            "result": {
                "reply": deps._with_advisory(deps._with_city_note(reply, demand)),
                "demand": demand,
                "items": results,
                "stage": "results",
                "source": source,
                "rewritten": q_for_search,
            }
        }

    # ---- 条件边 ----

    def after_prepare(state: ShoppingState) -> str:
        if ok(state):
            return "end"
        return "chat_reply" if state.get("intent") == "chat" else "resolve_intent"

    def after_resolve(state: ShoppingState) -> str:
        return "chat_reply" if state.get("intent") == "chat" else "expand_rows"

    def expand_rows(state: ShoppingState, config: RunnableConfig) -> dict:
        """理解层没拆、但规则能拆出多行时，补一次拆分。"""
        rows = state.get("rows") or []
        if not rows:
            rows = deps._multi_rows(state["query"], state.get("history"))
        return {"rows": rows}

    def after_expand(state: ShoppingState) -> str:
        rows = state.get("rows") or []
        return "multi_reply" if len(rows) >= 2 else "parse"

    def after_missing(state: ShoppingState) -> str:
        demand = state["demand"]
        if not demand["missing"]:
            return "retrieve"
        return "out_of_scope_reply" if demand.get("out_of_scope") else "clarify_reply"

    def after_retrieve(state: ShoppingState) -> str:
        return "empty_reply" if not state.get("items") else "recommend"

    def finish(state: ShoppingState, config: RunnableConfig) -> dict:
        return {}

    graph = StateGraph(ShoppingState)
    graph.add_node("prepare", prepare)
    graph.add_node("resolve_intent", resolve_intent)
    graph.add_node("chat_reply", chat_reply)
    graph.add_node("expand_rows", expand_rows)
    graph.add_node("multi_reply", multi_reply)
    graph.add_node("parse", parse)
    graph.add_node("out_of_scope_reply", out_of_scope_reply)
    graph.add_node("clarify_reply", clarify_reply)
    graph.add_node("retrieve", retrieve)
    graph.add_node("empty_reply", empty_reply)
    graph.add_node("recommend", recommend)
    graph.add_node("finish", finish)

    graph.add_edge(START, "prepare")
    graph.add_conditional_edges(
        "prepare",
        after_prepare,
        {"end": "finish", "chat_reply": "chat_reply", "resolve_intent": "resolve_intent"},
    )
    graph.add_conditional_edges(
        "resolve_intent",
        after_resolve,
        {"chat_reply": "chat_reply", "expand_rows": "expand_rows"},
    )
    graph.add_conditional_edges(
        "expand_rows",
        after_expand,
        {"multi_reply": "multi_reply", "parse": "parse"},
    )
    graph.add_conditional_edges(
        "parse",
        after_missing,
        {
            "retrieve": "retrieve",
            "out_of_scope_reply": "out_of_scope_reply",
            "clarify_reply": "clarify_reply",
        },
    )
    graph.add_conditional_edges(
        "retrieve",
        after_retrieve,
        {"empty_reply": "empty_reply", "recommend": "recommend"},
    )

    for node in (
        "chat_reply",
        "multi_reply",
        "out_of_scope_reply",
        "clarify_reply",
        "empty_reply",
        "recommend",
    ):
        graph.add_edge(node, END)
    graph.add_edge("finish", END)

    return graph.compile()


def draw_mermaid(app: Any) -> str:
    """返回 Mermaid 文本，用于检查分支是否连通、有没有死路。"""
    return app.get_graph().draw_mermaid()
