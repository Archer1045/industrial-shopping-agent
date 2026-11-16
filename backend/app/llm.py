"""DeepSeek LLM 调用（零额外依赖，手写 .env 解析）。"""
import json
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent.parent


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_env()

BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")


def chat_stream(
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 1200,
    timeout: int = 90,
):
    """流式调用 DeepSeek，逐块产出真实文本增量。

    只产出模型自己给的 delta.content，不做定时切片。
    """
    if not API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置")

    response = requests.post(
        f"{BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        },
        stream=True,
        timeout=timeout,
    )
    try:
        response.raise_for_status()
        for raw in response.iter_lines(decode_unicode=False):
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except ValueError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            piece = (choices[0].get("delta") or {}).get("content")
            if piece:
                yield piece
    finally:
        response.close()


def chat(messages: list[dict], temperature: float = 0.7, max_tokens: int = 1200, timeout: int = 90) -> str:
    """调用 DeepSeek 对话接口，返回文本。"""
    if not API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置")

    response = requests.post(
        f"{BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]
