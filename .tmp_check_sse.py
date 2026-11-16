"""SSE 流式对话冒烟：事件序列、真实增量、最终结果与落库一致性。"""
import json

import requests

BASE = "http://127.0.0.1:8100"


def collect(q, session_id=None, top_k=5):
    body = {"q": q, "session_id": session_id}
    events = []
    with requests.post(f"{BASE}/api/chat/stream", json=body, params={"top_k": top_k}, stream=True, timeout=180) as resp:
        assert resp.status_code == 200, resp.status_code
        assert resp.headers["content-type"].startswith("text/event-stream"), resp.headers["content-type"]
        event, data_lines = None, []
        for raw in resp.iter_lines(decode_unicode=False):
            if raw == b"":
                if event is not None:
                    events.append((event, json.loads("\n".join(data_lines))))
                event, data_lines = None, []
                continue
            line = raw.decode("utf-8")
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
    return events


def main():
    sid = requests.post(f"{BASE}/api/sessions", timeout=30).json()["id"]
    try:
        events = collect("304 不锈钢 M8 螺丝，长度 30mm，1000 个", session_id=sid, top_k=3)
        names = [e for e, _ in events]
        stages = [d["stage"] for e, d in events if e == "stage"]
        deltas = [d["text"] for e, d in events if e == "delta"]
        results = [d for e, d in events if e == "result"]
        errors = [d for e, d in events if e == "error"]

        print("events:", names)
        print("stages:", stages)
        print("delta count:", len(deltas))
        print("first delta:", (deltas[0][:40] if deltas else None))
        print("errors:", errors)

        assert not errors, errors
        assert "result" in names, names
        assert "understanding" in stages, stages
        assert "retrieving" in stages, stages
        assert "recommending" in stages, stages
        assert "saving" in stages, stages
        assert len(deltas) >= 2, len(deltas)

        result = results[-1]
        streamed = "".join(deltas)
        assert result["stage"] == "results", result["stage"]
        assert result["message_id"], result["message_id"]
        # 最终正文可以比流式文本多前缀（替代品说明、城市说明），但流式文本必须是它的子串
        assert streamed.strip() in result["reply"], (streamed[:80], result["reply"][:80])

        detail = requests.get(f"{BASE}/api/sessions/{sid}", timeout=30).json()
        msgs = detail["messages"]
        print("messages:", [(m["role"], len(m["text"])) for m in msgs])
        assert len(msgs) == 2, len(msgs)
        assert msgs[0]["role"] == "user" and msgs[1]["role"] == "assistant"
        assert msgs[1]["text"] == result["reply"], "落库正文与最终结果不一致"
        assert msgs[1]["id"] == result["message_id"], "message_id 不一致"

        # 非推荐分支也要给完整 result，不伪造 token
        events2 = collect("你好", session_id=sid)
        names2 = [e for e, _ in events2]
        deltas2 = [d for e, d in events2 if e == "delta"]
        assert "result" in names2, names2
        assert not deltas2, deltas2
        print("chat branch:", names2, events2[-1][1]["stage"])
    finally:
        requests.delete(f"{BASE}/api/sessions/{sid}", timeout=30)

    print("ALL PASS")


if __name__ == "__main__":
    main()
