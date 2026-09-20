"""用户 API（只读）。

现在只有两个内置账号 sys_dev / sys_admin，不开放增删——真要加用户，先接登录。
"""
from fastapi import APIRouter, Depends

from ..db import get_pool
from ..users import current_user

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("")
async def list_users(_user: dict = Depends(current_user)):
    rows = await get_pool().fetch(
        "SELECT id, name, role, enabled, created_at FROM users ORDER BY role DESC, id")
    return [dict(r) for r in rows]


@router.get("/me")
async def me(user: dict = Depends(current_user)):
    return user
