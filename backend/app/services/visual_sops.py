"""视觉 SOP 运行时读取：项目级视觉资产生成从已发布 SOP 取 spec
（knowledge_folder / planner / quality_gates），见 project_visual_assets.generate。
编辑/编译/发布链路已随「生产 SOP」管理页一并下线（2026-07-31）；
表数据由 backend/sql 种子维护。"""
from __future__ import annotations

import json
from typing import Any

import asyncpg


def _json(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else json.loads(value or "{}")


def row_dict(row: asyncpg.Record) -> dict[str, Any]:
    return {**dict(row), "spec": _json(row["spec"])}


async def get_published(pool: asyncpg.Pool, asset_role: str) -> dict[str, Any] | None:
    row = await pool.fetchrow(
        "SELECT * FROM visual_sops WHERE asset_role=$1 AND status='published' "
        "ORDER BY version DESC LIMIT 1", asset_role,
    )
    return row_dict(row) if row else None
