"""Token 用量查询 API（P4 · 2026-09-17 新增，纯增量）。

只读对账口径：按 日×模型 聚合。写入在 llm._post（services/llm_usage.py），
本模块不提供写接口——计量是基础设施，不该被业务侧手工插数。
"""
from typing import Any

from fastapi import APIRouter, Depends, Query

from ..db import get_pool
from ..services import llm_usage
from ..users import current_user

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("/summary")
async def summary(days: int = Query(default=30, ge=1, le=365),
                  user: dict = Depends(current_user)) -> dict[str, Any]:
    """token 用量：总量 + 按日×模型 明细（计费对账）。"""
    pool = get_pool()
    tsql, targs = llm_usage.total_sql(days)
    total = await pool.fetchrow(tsql, *targs)
    ssql, sargs = llm_usage.summary_sql(days)
    rows = await pool.fetch(ssql, *sargs)
    return {"days": days, "total": dict(total or {}),
            "by_day_model": [dict(r) for r in rows]}
