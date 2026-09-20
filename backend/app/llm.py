"""LLM 客户端：OpenAI 兼容 chat（文本 / JSON / 流式）。"""
import asyncio
import json
import re
import time
from typing import Any, AsyncIterator

import httpx

from . import models_registry
from .settings import settings

# 读超时 600s：长列表 JSON（12-24 镜分镜表 8000 token）在 72B 级模型上可能超过 300s
_TIMEOUT = httpx.Timeout(600.0, connect=15.0)
_REQUEST_LIMIT = asyncio.Semaphore(2)
_RATE_LIMIT_RETRIES = 5


async def _post(
    client: httpx.AsyncClient,
    url: str,
    *,
    body: dict[str, Any],
    headers: dict[str, str],
) -> httpx.Response:
    """限制并发并对 429 做退避，避免批量逐镜质检把文本供应商打穿。"""
    response: httpx.Response | None = None
    t0 = time.monotonic()
    for attempt in range(_RATE_LIMIT_RETRIES + 1):
        async with _REQUEST_LIMIT:
            response = await client.post(url, json=body, headers=headers)
        if response.status_code != 429 or attempt >= _RATE_LIMIT_RETRIES:
            # P4 计量：非流式 200 响应采集 token usage，fire-and-forget，绝不阻断
            if response.status_code == 200 and not body.get("stream"):
                try:
                    from .services.llm_usage import record_response
                    record_response(body, response.json(),
                                    int((time.monotonic() - t0) * 1000))
                except Exception:  # noqa: BLE001 — 计量失败不影响主链路
                    pass
            return response
        retry_after = response.headers.get("retry-after")
        try:
            delay = float(retry_after) if retry_after else float(2 ** (attempt + 1))
        except ValueError:
            delay = float(2 ** (attempt + 1))
        await asyncio.sleep(min(max(delay, 1.0), 30.0))
    assert response is not None
    return response


async def _profile(purpose: str = "text") -> tuple[str, str, str]:
    """(base_url, api_key, model) —— 模型注册表 active 档（按 purpose），兜底 text 档 → .env。
    purpose="review" 用于提示词/分镜质检：可在系统管理单独配更强的评审模型（未配则回落 text）。"""
    try:
        p = await models_registry.get_active(purpose)
        if not p and purpose != "text":
            p = await models_registry.get_active("text")
    except Exception:  # noqa: BLE001 — 表未建/池未起时兜底 env
        p = None
    if p:
        return p["base_url"].rstrip("/"), p["api_key"], p["model_name"]
    return settings.LLM_BASE_URL.rstrip("/"), settings.LLM_API_KEY, settings.LLM_MODEL


def _headers(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


async def chat_text(system: str, user: str, temperature: float = 0.7) -> str:
    base, key, model = await _profile()
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await _post(
            client, f"{base}/chat/completions", body=body, headers=_headers(key))
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


async def chat_messages(messages: list[dict], temperature: float = 0.7) -> str:
    """多轮对话：messages 为 OpenAI 形 [{role, content}]，首条通常是 system。
    对话面板用：历史 + 画布上下文一起交给模型，比单轮 chat_text 多带了记忆。"""
    base, key, model = await _profile()
    body = {"model": model, "messages": messages, "temperature": temperature}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await _post(
            client, f"{base}/chat/completions", body=body, headers=_headers(key))
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


class ToolCallUnsupported(RuntimeError):
    """当前模型档不支持 function calling —— 换档，别降级成裸文本硬跑。"""


async def chat_tools(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, *,
    purpose: str = "text", temperature: float = 0.3, max_tokens: int | None = None,
) -> dict[str, Any]:
    """OpenAI 兼容 function calling 的单轮：原样返回 assistant message。

    返回值里可能带 tool_calls（模型要调工具）或只有 content（模型给答案了）——
    循环由 services/agent_runtime 驱动，这里只负责一次往返。
    """
    base, key, model = await _profile(purpose)
    body: dict[str, Any] = {
        "model": model, "messages": messages, "temperature": temperature}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if max_tokens:
        body["max_tokens"] = max_tokens
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await _post(
            client, f"{base}/chat/completions", body=body, headers=_headers(key))
        if r.status_code == 400 and tools:
            # 不支持 tools 的模型：明确报错。静默去掉 tools 重试会让智能体"看着在跑但从不调工具"
            raise ToolCallUnsupported(
                f"模型 {model} 不支持 function calling（{r.text[:200]}）；"
                "请在「模型配置」为 text 档换一个支持工具调用的模型")
        r.raise_for_status()
        return r.json()["choices"][0]["message"]


_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _extract_json(text: str) -> Any:
    """容错解析：优先整体 parse，失败则剥 ```json 围栏 / 截取首个 {..} 或 [..]。"""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _JSON_FENCE.search(text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"LLM 未返回可解析 JSON: {text[:300]}")


async def chat_json(
    system: str, user: str, temperature: float = 0.4, max_tokens: int | None = None,
    purpose: str = "text",
) -> Any:
    """要求 LLM 输出 JSON 并解析（提示词中必须已声明 JSON 结构）。
    长列表输出（如 12-24 镜分镜表）须显式给 max_tokens，防止提供商默认值截断 JSON。
    purpose="review" 走专用评审模型档（未配置则自动回落 text 档）。"""
    base, key, model = await _profile(purpose)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    if max_tokens:
        body["max_tokens"] = max_tokens
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await _post(
            client, f"{base}/chat/completions", body=body, headers=_headers(key))
        if r.status_code == 400:
            # 某些模型不支持 response_format，去掉重试
            body.pop("response_format", None)
            r = await _post(
                client, f"{base}/chat/completions", body=body, headers=_headers(key))
        r.raise_for_status()
        return _extract_json(r.json()["choices"][0]["message"]["content"])


async def chat_vision_json(
    system: str, user: str, image_url: str, max_tokens: int = 1200,
    purpose: str = "review",
) -> Any:
    """OpenAI 兼容多模态评审；review 模型不支持视觉时由调用方决定阻断或降级。"""
    base, key, model = await _profile(purpose)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": user},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]},
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await _post(
            client, f"{base}/chat/completions", body=body, headers=_headers(key))
        if r.status_code == 400:
            body.pop("response_format", None)
            r = await _post(
                client, f"{base}/chat/completions", body=body, headers=_headers(key))
        r.raise_for_status()
        return _extract_json(r.json()["choices"][0]["message"]["content"])


async def chat_stream(
    system: str, user: str, temperature: float = 0.7, max_tokens: int | None = None,
) -> AsyncIterator[str]:
    """SSE 流式：逐 token yield 文本增量。长输出（流式拆镜）显式给 max_tokens，
    防提供商默认值把尾部截断。"""
    async for delta in chat_messages_stream(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            temperature=temperature, max_tokens=max_tokens):
        yield delta


async def chat_messages_stream(
    messages: list[dict[str, Any]], temperature: float = 0.7,
    max_tokens: int | None = None,
) -> AsyncIterator[str]:
    """多轮流式：OpenAI 形 messages 逐 token yield 文本增量。
    对话面板的流式回复用：历史 + 画布上下文一起交给模型，边想边出。"""
    base, key, model = await _profile()
    body: dict[str, Any] = {
        "model": model, "messages": messages,
        "temperature": temperature, "stream": True,
    }
    if max_tokens:
        body["max_tokens"] = max_tokens
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        async with client.stream(
            "POST", f"{base}/chat/completions", json=body, headers=_headers(key)
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0]["delta"].get("content")
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                if delta:
                    yield delta
