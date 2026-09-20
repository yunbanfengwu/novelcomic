"""团队与项目分享（P5 · 2026-09-17 新增，纯增量）——ACL 地基。

归属根不变：content_projects.owner_id 永远直通（读+写）；团队分享只是授权视图。
判定收敛在 decide_access（纯函数）+ assert_project_access（落库查询），
后续所有 API 的鉴权都从这里走，不再各自手写 owner 判断。

授权语义（最小心智模型）：
- owner：读写直通；
- 团队成员：所分享项目可读；任一分享 can_write=TRUE 才可写；
- 非成员：拒绝（不做匿名只读，避免"分享即公开"的意外）。
"""
from __future__ import annotations

from typing import Any

import asyncpg


class AccessDenied(Exception):
    """访问被拒（调用方映射 403，不是 500）。"""


class NotFound(Exception):
    """项目或团队不存在（调用方映射 404）。"""


# ── ACL 判定（纯函数，单测主战场）─────────────────────────────────────────

def decide_access(*, owner_id: str | None, is_member: bool, any_write: bool,
                  user_id: str, write: bool) -> bool:
    """单点判定：owner 直通；成员读=是成员，写=任一分享可写；其余拒绝。"""
    if owner_id == user_id:
        return True
    if not is_member:
        return False
    return any_write if write else True


async def assert_project_access(pool: asyncpg.Pool, project_id: int, user_id: str,
                                *, write: bool = False) -> None:
    """鉴权闸门：不通过抛 AccessDenied / NotFound。后续 API 在写路径前调用。"""
    row = await pool.fetchrow(
        """
        SELECT cp.owner_id,
               bool_or(tm.user_id IS NOT NULL)                AS is_member,
               coalesce(bool_or(tp.can_write) FILTER (WHERE tm.user_id IS NOT NULL),
                        FALSE)                                 AS any_write
        FROM content_projects cp
        LEFT JOIN team_projects tp ON tp.project_id = cp.id
        LEFT JOIN team_members  tm ON tm.team_id = tp.team_id AND tm.user_id = $2
        WHERE cp.id = $1
        GROUP BY cp.owner_id
        """,
        project_id, user_id)
    if row is None:
        raise NotFound(f"项目 {project_id} 不存在")
    if not decide_access(owner_id=row["owner_id"], is_member=row["is_member"],
                         any_write=row["any_write"], user_id=user_id, write=write):
        raise AccessDenied(
            f"用户 {user_id} 对项目 {project_id} 无{'写' if write else '读'}权限")


# ── 团队管理 ──────────────────────────────────────────────────────────────

async def create_team(pool: asyncpg.Pool, *, name: str, created_by: str,
                      description: str | None = None) -> dict[str, Any]:
    """建团队；创建者自动成为 admin 成员（否则没人能管这个团队）。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("团队名不能为空")
    async with pool.acquire() as conn, conn.transaction():
        try:
            team_id = await conn.fetchval(
                "INSERT INTO teams(name,description,created_by) VALUES($1,$2,$3) "
                "RETURNING id", name, description, created_by)
        except asyncpg.UniqueViolationError as e:
            raise ValueError(f"团队名 {name!r} 已存在") from e
        await conn.execute(
            "INSERT INTO team_members(team_id,user_id,role) VALUES($1,$2,'admin') "
            "ON CONFLICT DO NOTHING", team_id, created_by)
    return {"team_id": team_id, "name": name}


async def assert_team_admin(pool: asyncpg.Pool, team_id: int, actor_id: str) -> None:
    """成员/分享管理闸门：团队创建者、团队 admin、系统 admin 三者之一。"""
    row = await pool.fetchrow(
        "SELECT t.created_by, tm.role FROM teams t "
        "LEFT JOIN team_members tm ON tm.team_id=t.id AND tm.user_id=$2 "
        "WHERE t.id=$1", team_id, actor_id)
    if row is None:
        raise NotFound(f"团队 {team_id} 不存在")
    if row["created_by"] == actor_id or row["role"] == "admin":
        return
    role = await pool.fetchval("SELECT role FROM users WHERE id=$1", actor_id)
    if role != "admin":
        raise AccessDenied(f"用户 {actor_id} 不是团队 {team_id} 的管理员")


async def add_member(pool: asyncpg.Pool, team_id: int, user_id: str,
                     role: str = "member") -> dict[str, Any]:
    if role not in ("admin", "member"):
        raise ValueError("role 只能是 admin 或 member")
    n = await pool.execute(
        "INSERT INTO team_members(team_id,user_id,role) VALUES($1,$2,$3) "
        "ON CONFLICT (team_id,user_id) DO UPDATE SET role=EXCLUDED.role",
        team_id, user_id, role)
    return {"team_id": team_id, "user_id": user_id, "role": role}


async def remove_member(pool: asyncpg.Pool, team_id: int, user_id: str) -> int:
    n = await pool.fetchval(
        "WITH d AS (DELETE FROM team_members WHERE team_id=$1 AND user_id=$2 "
        "RETURNING 1) SELECT count(*) FROM d", team_id, user_id)
    return n or 0


async def share_project(pool: asyncpg.Pool, team_id: int, project_id: int,
                        *, can_write: bool = False,
                        actor_id: str) -> dict[str, Any]:
    """把项目分享给团队。闸门：actor 必须是项目 owner（或系统 admin）——
    不是 owner 没资格送别人的项目；分享权限与团队管理权限分开判定。"""
    owner = await pool.fetchval("SELECT owner_id FROM content_projects WHERE id=$1",
                                project_id)
    if owner is None:
        raise NotFound(f"项目 {project_id} 不存在")
    if owner != actor_id:
        role = await pool.fetchval("SELECT role FROM users WHERE id=$1", actor_id)
        if role != "admin":
            raise AccessDenied(f"只有项目 owner 能分享项目 {project_id}")
    await pool.execute(
        "INSERT INTO team_projects(team_id,project_id,can_write) VALUES($1,$2,$3) "
        "ON CONFLICT (team_id,project_id) DO UPDATE SET can_write=EXCLUDED.can_write",
        team_id, project_id, can_write)
    return {"team_id": team_id, "project_id": project_id, "can_write": can_write}


async def unshare_project(pool: asyncpg.Pool, team_id: int, project_id: int) -> int:
    n = await pool.fetchval(
        "WITH d AS (DELETE FROM team_projects WHERE team_id=$1 AND project_id=$2 "
        "RETURNING 1) SELECT count(*) FROM d", team_id, project_id)
    return n or 0


async def list_user_teams(pool: asyncpg.Pool, user_id: str) -> list[dict[str, Any]]:
    """我在的团队（含我在其中的角色）。"""
    rows = await pool.fetch(
        "SELECT t.id, t.name, t.description, t.created_by, tm.role "
        "FROM teams t JOIN team_members tm ON tm.team_id=t.id AND tm.user_id=$1 "
        "ORDER BY t.id", user_id)
    return [dict(r) for r in rows]


async def team_detail(pool: asyncpg.Pool, team_id: int) -> dict[str, Any] | None:
    """团队详情：成员 + 已分享项目。"""
    team = await pool.fetchrow(
        "SELECT id,name,description,created_by,created_at FROM teams WHERE id=$1",
        team_id)
    if not team:
        return None
    members = await pool.fetch(
        "SELECT user_id, role, joined_at FROM team_members WHERE team_id=$1 "
        "ORDER BY role, user_id", team_id)
    projects = await pool.fetch(
        "SELECT tp.project_id, tp.can_write, cp.title AS project_title "
        "FROM team_projects tp JOIN content_projects cp ON cp.id=tp.project_id "
        "WHERE tp.team_id=$1 ORDER BY tp.project_id", team_id)
    return {"team": dict(team),
            "members": [dict(m) for m in members],
            "projects": [dict(p) for p in projects]}
