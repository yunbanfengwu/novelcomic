"""当前用户。

系统还没有登录/鉴权，本模块只是那个位置的**占位实现**：用户从请求头 `X-User-Id` 来，
缺省 sys_dev。等真正接入登录时，只需要把这里换成解析会话/JWT，所有调用方不用改
——业务侧一律通过 `current_user` 依赖拿人，不各自去读请求头。
"""
from fastapi import Header, HTTPException

from .db import get_pool

DEFAULT_USER_ID = "sys_dev"


async def current_user(
    x_user_id: str = Header(default=DEFAULT_USER_ID, alias="X-User-Id"),
) -> dict:
    """返回 users 表里的当前用户行。未知/停用用户直接 401，不静默回退默认用户
    ——静默回退会把「前端传错了 id」伪装成「一切正常」。"""
    row = await get_pool().fetchrow(
        "SELECT id, name, role, enabled FROM users WHERE id = $1", x_user_id)
    if not row or not row["enabled"]:
        raise HTTPException(401, f"未知或已停用的用户：{x_user_id}")
    return dict(row)
