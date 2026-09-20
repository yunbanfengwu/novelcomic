"""最小集的 next 段：产物落库 → 通知 → 接着跑（2026-07-29 新增）。

从 `agent_unit` 拆出来的原因是这三件事的失败语义完全不同，混在一个函数里会写歪：

- **回写**失败要按 `on_fail` 处理（跳过 / 停下 / 重试一次）——产物没落库等于白跑；
- **落附件**失败只降级（产物本体已经在 meta 里了，附件是给版本回溯用的）；
- **通知**失败一律只记日志——推送是尽力而为，前端刷新一下就收敛了，
  不能因为没人订阅 SSE 就把整批任务判失败。

`writes` 是**配置驱动的写库**，所以走白名单：只认下面这四个落点，
表名列名都不拼接用户输入。给个自由字符串就能 UPDATE 任意表的设计迟早出事。
"""
from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

from . import events

log = logging.getLogger("agent_next")

# writes 白名单：'表.列.json键' → (SQL 模板, 用哪个 ctx 键定位行)
WRITE_TARGETS: dict[str, tuple[str, str]] = {
    "content_nodes.meta": (
        "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
        "node_id"),
    "content_elements.meta": (
        "UPDATE content_elements SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
        "element_id"),
    "content_elements.state": (
        "UPDATE content_elements SET state = state || $2::jsonb, updated_at=now() WHERE id=$1",
        "element_id"),
    "content_nodes.summary": (
        "UPDATE content_nodes SET summary = $2, updated_at=now() WHERE id=$1",
        "node_id"),
}

ATTACH_KIND = {"image": "image", "video": "video", "audio": "audio"}


class WriteError(Exception):
    """回写失败（落点不认、缺定位 id、或 SQL 没命中行）。"""


def parse_writes(spec: str) -> tuple[str, str, str]:
    """`content_nodes.meta.keyframe_url` → (落点键, ctx 键, json 键)。
    `content_nodes.summary` 这种整列落点没有第三段，json 键给空串。"""
    parts = [p for p in str(spec or "").split(".") if p]
    if len(parts) < 2:
        raise WriteError(f"回写字段 {spec!r} 格式应为 表.列[.json键]")
    target = f"{parts[0]}.{parts[1]}"
    if target not in WRITE_TARGETS:
        raise WriteError(f"不支持的回写落点 {target!r}，可选：{'、'.join(WRITE_TARGETS)}")
    _, ctx_key = WRITE_TARGETS[target]
    return target, ctx_key, ".".join(parts[2:])


async def write_back(pool: asyncpg.Pool, spec: str, value: Any,
                     ctx: dict[str, Any]) -> dict[str, Any]:
    """把产物写回配置指定的那一列。**「缺才跑」判的就是它**，所以写的键必须和
    `agent_batch.SOURCES` 里的 has_artifact 谓词对得上，否则下次批量还会重跑一遍。"""
    target, ctx_key, json_key = parse_writes(spec)
    sql, _ = WRITE_TARGETS[target]
    row_id = ctx.get(ctx_key)
    if row_id is None:
        raise WriteError(f"回写 {spec} 需要上下文 {ctx_key}，本次运行没有")
    payload = json.dumps({json_key: value}, ensure_ascii=False) if json_key else str(value)
    tag = await pool.execute(sql, row_id, payload)
    if tag.endswith(" 0"):
        raise WriteError(f"回写 {spec} 没命中行：{ctx_key}={row_id}")
    return {"target": target, "key": json_key, "id": row_id}


async def attach(pool: asyncpg.Pool, *, kind: str, url: str, ctx: dict[str, Any],
                 meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """媒体产物同时留一份附件，方便版本回溯。非媒体类型（提示词/文本）直接跳过。"""
    a_kind = ATTACH_KIND.get(kind, "")
    if not a_kind or not url:
        return {"skipped": "非媒体产物或无 url"}
    r = await pool.fetchrow(
        "INSERT INTO content_attachments (project_id,node_id,element_id,kind,url,meta) "
        "VALUES ($1,$2,$3,$4,$5,$6::jsonb) RETURNING id",
        ctx.get("project_id"), ctx.get("node_id"), ctx.get("element_id"), a_kind, url,
        json.dumps(meta or {"source": "agent_unit"}, ensure_ascii=False))
    return {"attachment_id": r["id"]}


def notify(targets: list[str], *, project_id: int | None, slug: str,
           payload: dict[str, Any]) -> list[str]:
    """next 段的 callfun：往事件总线推，前端 SSE 收到后刷新对应数据。

    `events.publish` 在没有订阅者时是**静默 no-op**（project_id 为空直接返回），
    所以这里不判断有没有人在听——判了反而会把「没开页面」误报成失败。
    """
    sent: list[str] = []
    for t in targets or []:
        if not t.startswith("frontend."):
            continue  # message.user 等站内信通道未接，先跳过而不是假装发了
        try:
            events.publish(project_id, {"type": t.split(".", 1)[1],
                                        "source": "agent", "flow": slug, **payload})
            sent.append(t)
        except Exception as e:  # noqa: BLE001 — 推送尽力而为，绝不影响产物
            log.warning("notify %s 失败: %s", t, e)
    return sent
