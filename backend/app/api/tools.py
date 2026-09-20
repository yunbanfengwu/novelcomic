"""工具 API（2026-07-29 新增，纯增量）。

一个工具 = 一次可被「技能 / 工作流 / 管理台」调用的能力。清单来源有两处：
内置只读工具（db.schema / db.query）+ services/workflow_actions 注册表里的命名动作。
不为查询逐个封装端点镜像，理由见 services/tools.py 模块头。
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import get_pool
from ..services import tools
from ..users import current_user

router = APIRouter(prefix="/api/tools", tags=["tools"])


class InvokeIn(BaseModel):
    args: dict[str, Any] = {}
    project_id: int | None = None
    source: str = "admin_ui"   # admin_ui | workflow | skill | api


@router.get("")
async def list_tools(user: dict = Depends(current_user)):
    """工具清单。前端渲染菜单用；将来技能侧也从这里取 tool schema。"""
    return {"me": user, "tools": tools.specs()}


@router.get("/calls")
async def recent_calls(tool: str | None = None, limit: int = 50,
                       _user: dict = Depends(current_user)):
    """调用审计：谁在什么时候用什么参数调了哪个工具、成功没有、花了多久。"""
    rows = await get_pool().fetch(
        "SELECT id,tool,caller,source,project_id,args,ok,row_count,error,duration_ms,"
        "created_at FROM tool_calls WHERE ($1::text IS NULL OR tool=$1) "
        "ORDER BY id DESC LIMIT $2", tool, min(max(limit, 1), 200))
    return [dict(r) for r in rows]


@router.post("/{name}/invoke")
async def invoke_tool(name: str, body: InvokeIn, user: dict = Depends(current_user)):
    """调用一个工具。写类工具只放给 admin——现在没有写类工具，闸门先立在这儿。"""
    spec = next((t for t in tools.specs() if t["name"] == name), None)
    if not spec:
        raise HTTPException(404, f"未知工具 {name}")
    if spec.get("writes") and user["role"] != "admin":
        raise HTTPException(403, f"{name} 是写类工具，仅管理员可调用")
    try:
        result = await tools.invoke(
            get_pool(), name, body.args, caller=user["id"],
            source=body.source, project_id=body.project_id)
    except tools.ToolError as e:
        raise HTTPException(400, str(e)) from e
    except ValueError as e:      # 动作自己抛的入参/数据错误，同样是 4xx 不是 500
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "tool": name, "result": result}
