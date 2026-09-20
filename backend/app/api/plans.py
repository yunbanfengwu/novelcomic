"""智能体规划 API（P3 · 2026-09-17 新增，纯增量）。

计划是"落库的一等实体"：建（LLM 拆步）→ 推进（跑下一步回写）→ 单步重试 →
按项目列出。状态机与执行在 services/planner.py，这里只做参数与权限薄壳。
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..db import get_pool
from ..services import planner
from ..users import current_user

router = APIRouter(prefix="/api/plans", tags=["plans"])


class PlanBody(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    project_id: int | None = None
    tool_names: list[str] = Field(default_factory=list)  # 授权给步骤执行的工具白名单


async def _plan_or_404(pool, plan_id: int) -> dict[str, Any]:
    plan = await planner._load_plan(pool, plan_id)
    if not plan:
        raise HTTPException(404, f"计划 {plan_id} 不存在")
    return plan


@router.post("")
async def create_plan(body: PlanBody,
                      user: dict = Depends(current_user)) -> dict[str, Any]:
    """目标 → LLM 拆步 → 落库（draft）。执行走 /advance，一步一调。"""
    try:
        out = await planner.create_plan(
            get_pool(), goal=body.goal, project_id=body.project_id,
            created_by=user["id"],
            meta={"tool_names": body.tool_names} if body.tool_names else None)
    except planner.PlannerError as e:
        raise HTTPException(422, str(e)) from e
    return out


@router.get("")
async def list_plans(project_id: int | None = None,
                     limit: int = Query(default=20, ge=1, le=100),
                     user: dict = Depends(current_user)) -> dict[str, Any]:
    """按项目列计划（不带 project_id 则列全局计划）。"""
    rows = await get_pool().fetch(
        "SELECT id,project_id,goal,status,current_seq,created_by,created_at,updated_at "
        "FROM agent_plans WHERE ($1::bigint IS NULL OR project_id=$1) "
        "ORDER BY id DESC LIMIT $2", project_id, limit)
    return {"plans": [dict(r) for r in rows]}


@router.get("/{plan_id}")
async def get_plan(plan_id: int,
                   user: dict = Depends(current_user)) -> dict[str, Any]:
    """计划详情：含全部步骤（状态/产物/错误），前端画进度与步骤卡。"""
    pool = get_pool()
    plan = await _plan_or_404(pool, plan_id)
    steps = await pool.fetch(
        "SELECT id,seq,title,detail,tool_hints,status,result,error,"
        "started_at,finished_at FROM agent_plan_steps WHERE plan_id=$1 ORDER BY seq",
        plan_id)
    return {"plan": plan, "steps": [dict(s) for s in steps],
            "progress": planner.progress([dict(s) for s in steps])}


@router.post("/{plan_id}/advance")
async def advance(plan_id: int,
                  user: dict = Depends(current_user)) -> dict[str, Any]:
    """推进一步：跑下一个 pending 步骤并回写；可重复调用直到 done/failed。"""
    try:
        return await planner.advance(get_pool(), plan_id, caller=user["id"])
    except planner.PlannerError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/{plan_id}/steps/{seq}/retry")
async def retry_step(plan_id: int, seq: int,
                     user: dict = Depends(current_user)) -> dict[str, Any]:
    """单步重试：只复活失败/跳过的这一步，成功步不重跑。"""
    try:
        return await planner.retry_step(get_pool(), plan_id, seq, caller=user["id"])
    except (planner.PlannerError, ValueError) as e:
        raise HTTPException(422, str(e)) from e


@router.post("/{plan_id}/abort")
async def abort(plan_id: int, user: dict = Depends(current_user)) -> dict[str, Any]:
    """人工终止（幂等）：running 的步骤留痕，后续不可再 advance。"""
    pool = get_pool()
    plan = await _plan_or_404(pool, plan_id)
    await pool.execute(
        "UPDATE agent_plans SET status='aborted', updated_at=now() WHERE id=$1",
        plan_id)
    return {"plan_id": plan_id, "status": "aborted",
            "was": plan["status"]}
