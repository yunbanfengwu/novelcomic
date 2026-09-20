"""Token 用量计量（P4 · 2026-09-17 新增，纯增量）——计费地基。

采集点收敛在 llm._post（所有非流式 chat_* 的唯一咽喉）：
每次 200 响应解析 usage → fire-and-forget 写 llm_usage（100 号迁移）。
原则：
- **绝不阻断生成**：计量任何一步失败都静默吞掉，主链路无感知；
- **fire-and-forget**：INSERT 用独立 task，不增加调用方延迟；
- 流式（chat_stream）SSE 增量通常不带 usage，且走的是独立 stream 通道，
  本期不采（要采需开 stream_options.include_usage，等真实需要时再补）。

口径：计费按 (日 × 模型) 聚合 tokens 与调用次数；caller/purpose 在 llm 层拿不到，
不做猜测——真需要时由上层把 caller 塞进 body 的扩展字段再透传。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any


def extract_usage(payload: dict[str, Any] | None) -> dict[str, int] | None:
    """从 OpenAI 兼容响应体提取 usage（纯函数，容错：缺字段按 0 计，无 usage 返回 None）。"""
    if not isinstance(payload, dict):
        return None
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or (prompt + completion))
    return {"prompt_tokens": prompt, "completion_tokens": completion,
            "total_tokens": total}


_INSERT = (
    "INSERT INTO llm_usage(model,prompt_tokens,completion_tokens,total_tokens,"
    "duration_ms) VALUES ($1,$2,$3,$4,$5)"
)


def record_response(body: dict[str, Any] | None, payload: dict[str, Any] | None,
                    duration_ms: int) -> None:
    """解析响应并排队落库（fire-and-forget）。同步入口，内部起 task。"""
    usage = extract_usage(payload)
    if not usage:
        return
    model = str((body or {}).get("model") or "unknown")
    row = (model, usage["prompt_tokens"], usage["completion_tokens"],
           usage["total_tokens"], max(0, int(duration_ms or 0)))

    async def _write() -> None:
        try:
            from ..db import get_pool  # 延迟导入：避免 llm←→db 启动顺序耦合
            await get_pool().execute(_INSERT, *row)
        except Exception:  # noqa: BLE001 — 计量写失败不反噬业务
            pass

    try:
        task = asyncio.get_running_loop().create_task(_write())
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
    except RuntimeError:
        pass  # 无事件循环（脚本/同步上下文）→ 放弃本次计量


# ── 聚合 SQL（纯函数：SQL 与参数一并返回，单测断言形状）────────────────────

def _days(days: int) -> str:
    return str(max(1, min(int(days if days is not None else 30), 365)))


def summary_sql(days: int) -> tuple[str, list]:
    """按日 × 模型聚合（计费对账口径）。"""
    sql = """
    SELECT to_char(date_trunc('day', created_at), 'YYYY-MM-DD') AS day,
           model,
           count(*)::int AS calls,
           sum(prompt_tokens)::bigint AS prompt_tokens,
           sum(completion_tokens)::bigint AS completion_tokens,
           sum(total_tokens)::bigint AS total_tokens,
           avg(duration_ms)::int AS avg_ms
    FROM llm_usage
    WHERE created_at >= now() - ($1::text || ' days')::interval
    GROUP BY day, model
    ORDER BY day DESC, total_tokens DESC
    """
    return sql, [_days(days)]


def total_sql(days: int) -> tuple[str, list]:
    """同窗口总量（对账首行）。"""
    sql = """
    SELECT count(*)::int AS calls,
           coalesce(sum(prompt_tokens), 0)::bigint AS prompt_tokens,
           coalesce(sum(completion_tokens), 0)::bigint AS completion_tokens,
           coalesce(sum(total_tokens), 0)::bigint AS total_tokens
    FROM llm_usage
    WHERE created_at >= now() - ($1::text || ' days')::interval
    """
    return sql, [_days(days)]
