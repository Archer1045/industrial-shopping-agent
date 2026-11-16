"""假上游 SSE 测试：delta 拼接、reset、error、落库次数、取消穿透。

不依赖真实 DeepSeek，跑在 TestClient 上。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app import llm, main, understand  # noqa: E402
from app.sessions import create_session, delete_session, get_session  # noqa: E402

client = None


def parse_events(text: str):
    events = []
    event, data = None, []
    for line in text.split("\n"):
        if line == "":
            if event is not None:
                events.append((event, json.loads("\n".join(data))))
            event, data = None, []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
    return events


def run_stream(q: str, sid: str):
    with client.stream("POST", "/api/chat/stream", json={"q": q, "session_id": sid}) as r:
        assert r.status_code == 200, r.status_code
        assert "text/event-stream" in r.headers["content-type"]
        body = "".join(r.iter_text())
    return parse_events(body)


def with_answer_patched(fn):
    """替换真实推荐调用，保留理解层（它会调用 llm.chat 做意图判断，这里也让它是假的）。"""

    def fake_chat(messages, temperature=0.7, max_tokens=1200, timeout=90):
        joined = json.dumps(messages, ensure_ascii=False)
        if "推荐" in joined or "候选" in joined:
            return "**模板兜底**：以下是可替代的候选。"
        return "好的，我来帮你找。"

    old_stream = llm.chat_stream
    old_chat = llm.chat
    llm.chat_stream = fn
    llm.chat = fake_chat
    return old_stream, old_chat


def restore(old_stream, old_chat):
    llm.chat_stream = old_stream
    llm.chat = old_chat


def case_success():
    pieces = ["**推荐（按匹配度排序）**", "\n\n1. 304 内六角", " M8×30，¥0.35/个"]

    def fake_stream(messages, **kw):
        for p in pieces:
            yield p

    old = with_answer_patched(fake_stream)
    sid = create_session()["id"]
    try:
        events = run_stream("304 不锈钢 M8 螺丝，长度 30mm，1000 个", sid)
        names = [e for e, _ in events]
        deltas = [d["text"] for e, d in events if e == "delta"]
        results = [d for e, d in events if e == "result"]
        errors = [d for e, d in events if e == "error"]
        print("A events:", names[:6], "...", names[-2:])
        if errors:
            print("A error:", errors)
            raise AssertionError(errors[0]["message"])
        assert deltas == pieces, deltas
        assert results, "缺少 result"
        result = results[-1]
        assert result["reply"].startswith("**推荐（按匹配度排序）**"), result["reply"][:40]
        assert result["message_id"], result["message_id"]
        msgs = get_session(sid)["messages"]
        assert len(msgs) == 2, msgs
        assert msgs[1]["text"] == result["reply"]
        assert msgs[1]["id"] == result["message_id"]
        print("A ok: delta", len(deltas), "live落库 2 条")
    finally:
        restore(*old)
        delete_session(sid)


def case_reset():
    def fake_stream(messages, **kw):
        yield "**写到一半"
        raise RuntimeError("上游炸了")

    old = with_answer_patched(fake_stream)
    sid = create_session()["id"]
    try:
        events = run_stream("304 不锈钢 M8 螺丝，长度 30mm，1000 个", sid)
        names = [e for e, _ in events]
        resets = [d for e, d in events if e == "reset"]
        results = [d for e, d in events if e == "result"]
        deltas = [d["text"] for e, d in events if e == "delta"]
        print("B events:", names)
        assert deltas == ["**写到一半"], deltas
        assert resets, "缺少 reset"
        assert results, "缺少 result"
        reply = results[-1]["reply"]
        assert "写到一半" not in reply, "模板结果里残留了半截文本"
        assert reply.strip(), "模板结果为空"
        assert reply.count("按你的需求") <= 1, "模板内容重复拼接"
        msgs = get_session(sid)["messages"]
        assert len(msgs) == 2, msgs
        assert msgs[1]["text"] == reply
        print("B ok: reset 后走模板，落库 2 条且无重复")
    finally:
        restore(*old)
        delete_session(sid)


def case_error():
    def boom(*args, **kwargs):
        raise RuntimeError("理解层挂了")

    old_understand = understand.understand
    old = with_answer_patched(lambda m, **kw: iter(()))
    understand.understand = boom
    sid = create_session()["id"]
    try:
        events = run_stream("304 不锈钢 M8 螺丝，长度 30mm，1000 个", sid)
        names = [e for e, _ in events]
        errors = [d for e, d in events if e == "error"]
        results = [d for e, d in events if e == "result"]
        print("C events:", names)
        assert errors, "缺少 error 事件"
        assert not results, "失败路径不应伪造 result"
        msgs = get_session(sid)["messages"]
        assert len(msgs) == 0, msgs
        print("C ok: error 且不落库")
    finally:
        understand.understand = old_understand
        restore(*old)
        delete_session(sid)


def case_cancel():
    """取消异常必须穿透 _answer 的 except Exception，且不落库。"""
    calls = {"n": 0}

    def boom(text):
        calls["n"] += 1
        raise main._StreamCancelled()

    old = with_answer_patched(lambda m, **kw: iter(["a", "b", "c"]))
    sid = create_session()["id"]
    try:
        try:
            main._chat("304 不锈钢 M8 螺丝，长度 30mm，1000 个", session_id=sid, on_delta=boom)
        except main._StreamCancelled:
            pass
        else:
            raise AssertionError("取消没有穿透到调用方")
        assert calls["n"] == 1, calls
        assert get_session(sid)["messages"] == [], "取消后不应落库"
        print("D ok: 取消穿透，未落库")
    finally:
        restore(*old)
        delete_session(sid)


def case_cancel_without_delta():
    """没有 delta 的分支（这里走 chat）在理解阶段断开，也不能落库。"""
    old = with_answer_patched(lambda m, **kw: "你好呀，想买点什么？")
    sid = create_session()["id"]
    flag = {"on": False}

    def on_stage(name):
        if name == "understanding":
            flag["on"] = True

    try:
        try:
            main._chat("你好", session_id=sid, on_stage=on_stage, is_cancelled=lambda: flag["on"])
        except main._StreamCancelled:
            pass
        else:
            raise AssertionError("非 delta 分支的取消没有生效")
        assert get_session(sid)["messages"] == [], "非 delta 分支取消后不应落库"
        print("E ok: 无 delta 分支取消，未落库")
    finally:
        restore(*old)
        delete_session(sid)


def case_cancel_before_save():
    """结果已经算完、落库之前断开，同样不能写库。"""
    old = with_answer_patched(lambda m, **kw: "你要买哪种螺纹规格的螺丝，比如 M8？")
    sid = create_session()["id"]
    flag = {"on": False}

    def on_stage(name):
        if name == "saving":
            flag["on"] = True

    try:
        try:
            main._chat(
                "我要买螺丝", session_id=sid, on_stage=on_stage, is_cancelled=lambda: flag["on"]
            )
        except main._StreamCancelled:
            pass
        else:
            raise AssertionError("saving 前的取消没有生效")
        assert get_session(sid)["messages"] == [], "saving 前取消后不应落库"
        print("F ok: 落库前取消，未落库")
    finally:
        restore(*old)
        delete_session(sid)


if __name__ == "__main__":
    # 用 with 触发 lifespan，把 FAISS / BM25 索引准备好，否则 hybrid_search 拿不到 STATE
    with TestClient(main.app) as c:
        client = c
        case_success()
        case_reset()
        case_error()
        case_cancel()
        case_cancel_without_delta()
        case_cancel_before_save()
    print("ALL PASS")
