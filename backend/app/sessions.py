"""会话与消息持久化。

会话记录存 SQLite，刷新页面、换标签页、重开浏览器都还能看到历史对话。
前端只负责渲染，真正的历史以这里为准。
"""
import json
import uuid
from datetime import datetime

from .db import get_conn

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '新对话',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    payload TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS feedback (
    message_id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    rating TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

DEFAULT_TITLE = "新对话"
TITLE_LIMIT = 20


def init_tables() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _touch(conn, sid: str) -> None:
    conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (_now(), sid))


def create_session(title: str = DEFAULT_TITLE) -> dict:
    sid = uuid.uuid4().hex[:12]
    now = _now()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (sid, title, now, now),
        )
    return {"id": sid, "title": title, "created_at": now, "updated_at": now, "count": 0}


def list_sessions() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.title, s.created_at, s.updated_at,
                   (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS count
            FROM sessions s
            ORDER BY s.updated_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_session(sid: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
        if not row:
            return None
        msgs = conn.execute(
            "SELECT m.id, m.role, m.content, m.payload, m.created_at, f.rating "
            "FROM messages m LEFT JOIN feedback f ON f.message_id = m.id "
            "WHERE m.session_id = ? ORDER BY m.id",
            (sid,),
        ).fetchall()
    data = dict(row)
    data["messages"] = [
        {
            "id": m["id"],
            "role": m["role"],
            "text": m["content"],
            "payload": json.loads(m["payload"]) if m["payload"] else None,
            "rating": m["rating"],
            "created_at": m["created_at"],
        }
        for m in msgs
    ]
    return data


def delete_session(sid: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (sid,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))


def append_message(sid: str, role: str, content: str, payload: dict | None = None) -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT title FROM sessions WHERE id = ?", (sid,)).fetchone()
        if not row:
            raise ValueError(f"会话不存在：{sid}")
        cur = conn.execute(
            "INSERT INTO messages (session_id, role, content, payload, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                sid,
                role,
                content,
                json.dumps(payload, ensure_ascii=False) if payload else None,
                _now(),
            ),
        )
        # 第一条用户消息自动当标题，方便在侧栏里认出来
        if role == "user" and row["title"] == DEFAULT_TITLE:
            title = content.strip().replace("\n", " ")[:TITLE_LIMIT] or DEFAULT_TITLE
            conn.execute("UPDATE sessions SET title = ? WHERE id = ?", (title, sid))
        _touch(conn, sid)
        return cur.lastrowid


def add_feedback(message_id: int, rating: str) -> dict | None:
    """记录一条评价。同一条消息重复评价就覆盖，不保留历史。"""
    if rating not in ("up", "down"):
        raise ValueError(f"rating 只能是 up 或 down：{rating}")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT session_id FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "INSERT INTO feedback (message_id, session_id, rating, created_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(message_id) DO UPDATE SET rating = excluded.rating, "
            "created_at = excluded.created_at",
            (message_id, row["session_id"], rating, _now()),
        )
    return {"message_id": message_id, "rating": rating}


def feedback_stats() -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT rating, COUNT(*) AS n FROM feedback GROUP BY rating"
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE role = 'assistant'"
        ).fetchone()[0]
    counts = {r["rating"]: r["n"] for r in rows}
    up = counts.get("up", 0)
    down = counts.get("down", 0)
    rated = up + down
    return {
        "up": up,
        "down": down,
        "rated": rated,
        "assistant_total": total,
        "rate": round(rated / total, 3) if total else 0.0,
    }


def history_of(sid: str, limit: int = 8) -> list[dict]:
    """取最近若干条消息给需求合并用，顺序按时间正序。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (sid, limit),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
