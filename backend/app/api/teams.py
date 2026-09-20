"""团队与项目分享 API（P5 · 2026-09-17 新增，纯增量，最小集）。

团队 CRUD / 成员管理 / 项目分享。ACL 判定在 services/teams——
本模块是参数与权限薄壳；其余业务 API 接入 assert_project_access 后即获得团队授权。
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..db import get_pool
from ..services import teams
from ..users import current_user

router = APIRouter(prefix="/api/teams", tags=["teams"])


class TeamBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class MemberBody(BaseModel):
    user_id: str = Field(min_length=1, max_length=100)
    role: str = Field(default="member", pattern="^(admin|member)$")


class ShareBody(BaseModel):
    project_id: int
    can_write: bool = False


@router.post("")
async def create_team(body: TeamBody,
                      user: dict = Depends(current_user)) -> dict[str, Any]:
    """建团队；创建者自动成为 admin 成员。"""
    try:
        return await teams.create_team(get_pool(), name=body.name,
                                       description=body.description,
                                       created_by=user["id"])
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("")
async def my_teams(user: dict = Depends(current_user)) -> dict[str, Any]:
    """我所在的团队（含角色）。"""
    return {"teams": await teams.list_user_teams(get_pool(), user["id"])}


@router.get("/{team_id}")
async def team_detail(team_id: int,
                      user: dict = Depends(current_user)) -> dict[str, Any]:
    """团队详情：成员 + 已分享项目。非成员不可见。"""
    pool = get_pool()
    try:
        await teams.assert_team_admin(pool, team_id, user["id"])
    except teams.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except teams.AccessDenied:
        # 非管理员成员只回团队基本信息，不给成员/项目清单（最小暴露）
        detail = await teams.team_detail(pool, team_id)
        if not detail:
            raise HTTPException(404, f"团队 {team_id} 不存在")
        return {"team": detail["team"], "members": [], "projects": [],
                "restricted": True}
    detail = await teams.team_detail(pool, team_id)
    if not detail:
        raise HTTPException(404, f"团队 {team_id} 不存在")
    return detail


@router.post("/{team_id}/members")
async def add_member(team_id: int, body: MemberBody,
                     user: dict = Depends(current_user)) -> dict[str, Any]:
    pool = get_pool()
    try:
        await teams.assert_team_admin(pool, team_id, user["id"])
        return await teams.add_member(pool, team_id, body.user_id, body.role)
    except teams.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except teams.AccessDenied as e:
        raise HTTPException(403, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.delete("/{team_id}/members/{user_id}")
async def remove_member(team_id: int, user_id: str,
                        user: dict = Depends(current_user)) -> dict[str, Any]:
    pool = get_pool()
    try:
        await teams.assert_team_admin(pool, team_id, user["id"])
    except teams.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except teams.AccessDenied as e:
        raise HTTPException(403, str(e)) from e
    return {"removed": await teams.remove_member(pool, team_id, user_id)}


@router.post("/{team_id}/projects")
async def share_project(team_id: int, body: ShareBody,
                        user: dict = Depends(current_user)) -> dict[str, Any]:
    """分享项目给团队（只有项目 owner 能分享；can_write=FALSE 只读）。"""
    pool = get_pool()
    try:
        await teams.assert_team_admin(pool, team_id, user["id"])
        return await teams.share_project(pool, team_id, body.project_id,
                                         can_write=body.can_write,
                                         actor_id=user["id"])
    except teams.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except teams.AccessDenied as e:
        raise HTTPException(403, str(e)) from e


@router.delete("/{team_id}/projects/{project_id}")
async def unshare_project(team_id: int, project_id: int,
                          user: dict = Depends(current_user)) -> dict[str, Any]:
    pool = get_pool()
    try:
        await teams.assert_team_admin(pool, team_id, user["id"])
    except teams.NotFound as e:
        raise HTTPException(404, str(e)) from e
    except teams.AccessDenied as e:
        raise HTTPException(403, str(e)) from e
    return {"removed": await teams.unshare_project(pool, team_id, project_id)}
