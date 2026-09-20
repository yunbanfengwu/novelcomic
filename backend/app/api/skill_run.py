"""技能试运行 + 用量可见（2026-09-17 新增，纯增量）。

P2 补强：技能装上之后要有两个闭环——
① dry-run：拿 SKILL.md 全文当 charter，走 agent_runtime.run 的完整 tool-calling
  循环（工具白名单只留 skill.read/kb.search，max_steps 收紧），返回产物 + steps 轨迹，
  让"装了但不知道好不好用"变成"跑一次看轨迹"；
② usage：从 tool_calls 审计聚合（35 号迁移已有表），回答"这个技能被谁/哪里/调了多少次"。
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..db import get_pool
from ..services import agent_runtime
from ..users import current_user

router = APIRouter(prefix="/api/skills", tags=["skill-run"])


class DryRunBody(BaseModel):
    """试运行入参：任务 + 可选知识范围。不给任何业务工具（沙箱）。"""
    task: str = Field(min_length=1, max_length=8000)
    project_id: int | None = None
    folder_ids: list[int] = Field(default_factory=list)
    max_steps: int = Field(default=6, ge=1, le=12)


@router.post("/{slug}/dry-run")
async def dry_run(slug: str, body: DryRunBody,
                  user: dict = Depends(current_user)) -> dict[str, Any]:
    """单技能沙箱试运行。

    charter=SKILL.md 全文（技能本体），skills=[slug] 只是让 skill.read 可读它的附件；
    tool_names=[] 意味着不挂任何业务工具——试运行只验证"读法 + 做法"，不碰数据。
    """
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT slug,name,description,skill_md FROM skill_packages "
        "WHERE slug=$1 AND status='installed'", slug)
    if not row:
        raise HTTPException(404, f"技能 {slug!r} 未安装")
    charter = row["skill_md"] or f"你是技能「{row['name']}」。"
    try:
        result = await agent_runtime.run(
            pool, charter=charter, task=body.task, skills=[slug],
            folder_ids=body.folder_ids, tool_names=[],
            project_id=body.project_id, max_steps=body.max_steps,
            caller=user["id"])
    except agent_runtime.AgentError as e:
        raise HTTPException(422, f"试运行失败：{e}") from e
    return {"slug": slug, "name": row["name"], "output": result["output"],
            "steps": result["steps"], "max_steps": body.max_steps}


def usage_sql(slug: str, days: int) -> tuple[str, list]:
    """skill.read 审计的按日聚合 SQL（纯函数：SQL 与参数一并返回，单测断言形状）。"""
    sql = """
    SELECT caller, source,
           to_char(date_trunc('day', created_at), 'YYYY-MM-DD') AS day,
           count(*)::int AS calls,
           count(*) FILTER (WHERE NOT ok)::int AS failures,
           avg(duration_ms)::int AS avg_ms
    FROM tool_calls
    WHERE tool = 'skill.read' AND args->>'slug' = $1
      AND created_at >= now() - ($2::text || ' days')::interval
    GROUP BY caller, source, day
    ORDER BY day DESC, calls DESC
    """
    return sql, [slug, str(max(1, min(int(days if days is not None else 30), 90)))]


def usage_total_sql(slug: str, days: int) -> tuple[str, list]:
    """同一窗口的总量聚合（纯函数）。"""
    sql = """
    SELECT count(*)::int AS calls,
           count(*) FILTER (WHERE NOT ok)::int AS failures,
           count(DISTINCT caller)::int AS callers,
           avg(duration_ms)::int AS avg_ms,
           max(created_at)::text AS last_used_at
    FROM tool_calls
    WHERE tool = 'skill.read' AND args->>'slug' = $1
      AND created_at >= now() - ($2::text || ' days')::interval
    """
    return sql, [slug, str(max(1, min(int(days if days is not None else 30), 90)))]


@router.get("/{slug}/usage")
async def usage(slug: str, days: int = Query(default=30, ge=1, le=90),
                user: dict = Depends(current_user)) -> dict[str, Any]:
    """技能被谁/哪里/调了多少次（数据来自 tool_calls 审计，只读）。"""
    pool = get_pool()
    if not await pool.fetchval("SELECT 1 FROM skill_packages WHERE slug=$1", slug):
        raise HTTPException(404, f"技能 {slug!r} 不存在")
    sql, args = usage_sql(slug, days)
    rows = await pool.fetch(sql, *args)
    tsql, targs = usage_total_sql(slug, days)
    total = await pool.fetchrow(tsql, *targs)
    return {"slug": slug, "days": days, "total": dict(total or {}),
            "by_day": [dict(r) for r in rows]}
