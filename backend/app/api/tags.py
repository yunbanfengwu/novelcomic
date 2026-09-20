"""标签词表 API：标签分组 + 标签 CRUD（系统管理维护）。

kb_entries.tags TEXT[] 存标签 code，条目打标复用该列（不新增关联表）。
视频类型/风格类型 为 system 受保护分组：可改 title、禁改 code、禁删除。
仿 kb_library.py 直连 get_pool()，无 service 层。
"""
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import get_pool

router = APIRouter(prefix="/api/admin", tags=["tags"])


# ═══════════ 标签分组 + 标签（嵌套）═══════════

@router.get("/tag-groups")
async def list_tag_groups() -> list[dict[str, Any]]:
    """全部分组 + 其下标签（均按 seq, id 排序）。"""
    groups = await get_pool().fetch("SELECT * FROM tag_groups ORDER BY seq, id")
    tags = await get_pool().fetch("SELECT * FROM tags ORDER BY seq, id")
    by_group: dict[int, list[dict[str, Any]]] = {}
    for t in tags:
        by_group.setdefault(t["group_id"], []).append(dict(t))
    return [{**dict(g), "tags": by_group.get(g["id"], [])} for g in groups]


class GroupIn(BaseModel):
    code: str = Field(min_length=1, description="英文唯一标识")
    title: str = Field(min_length=1)
    seq: int = 100


@router.post("/tag-groups")
async def create_group(body: GroupIn):
    dup = await get_pool().fetchval("SELECT 1 FROM tag_groups WHERE code=$1", body.code.strip())
    if dup:
        raise HTTPException(400, "同 code 分组已存在")
    r = await get_pool().fetchrow(
        "INSERT INTO tag_groups (code, title, seq, system) VALUES ($1,$2,$3,FALSE) RETURNING *",
        body.code.strip(), body.title.strip(), body.seq,
    )
    return {**dict(r), "tags": []}


class GroupPatch(BaseModel):
    title: str = Field(min_length=1)
    seq: int | None = None


@router.put("/tag-groups/{group_id}")
async def update_group(group_id: int, body: GroupPatch):
    """改 title/排序（system 分组也可改 title，但不能改 code、不能删）。"""
    r = await get_pool().fetchrow(
        """UPDATE tag_groups SET title=$2, seq=COALESCE($3, seq) WHERE id=$1 RETURNING *""",
        group_id, body.title.strip(), body.seq,
    )
    if not r:
        raise HTTPException(404, "分组不存在")
    return dict(r)


@router.delete("/tag-groups/{group_id}")
async def delete_group(group_id: int):
    """删自定义分组（CASCADE 删其标签）；system 分组禁删。"""
    n = await get_pool().execute("DELETE FROM tag_groups WHERE id=$1 AND NOT system", group_id)
    if n == "DELETE 0":
        raise HTTPException(404, "分组不存在或为内置分组（不可删除）")
    return {"ok": True}


# ═══════════ 标签 CRUD ═══════════

class TagIn(BaseModel):
    group_id: int
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    thumbnail_url: str | None = None
    seq: int = 100


@router.post("/tags")
async def create_tag(body: TagIn):
    g = await get_pool().fetchval("SELECT 1 FROM tag_groups WHERE id=$1", body.group_id)
    if not g:
        raise HTTPException(404, "分组不存在")
    dup = await get_pool().fetchval("SELECT 1 FROM tags WHERE code=$1", body.code.strip())
    if dup:
        raise HTTPException(400, "同 code 标签已存在")
    r = await get_pool().fetchrow(
        """INSERT INTO tags (group_id, code, name, thumbnail_url, seq)
           VALUES ($1,$2,$3,$4,$5) RETURNING *""",
        body.group_id, body.code.strip(), body.name.strip(),
        (body.thumbnail_url or "").strip() or None, body.seq,
    )
    return dict(r)


class TagPatch(BaseModel):
    name: str = Field(min_length=1)
    thumbnail_url: str | None = None
    seq: int | None = None


@router.put("/tags/{tag_id}")
async def update_tag(tag_id: int, body: TagPatch):
    """改 name/缩略图/排序（code 不可改——它是条目里已存的引用键）。"""
    r = await get_pool().fetchrow(
        """UPDATE tags SET name=$2, thumbnail_url=$3, seq=COALESCE($4, seq)
           WHERE id=$1 RETURNING *""",
        tag_id, body.name.strip(), (body.thumbnail_url or "").strip() or None, body.seq,
    )
    if not r:
        raise HTTPException(404, "标签不存在")
    return dict(r)


@router.delete("/tags/{tag_id}")
async def delete_tag(tag_id: int):
    n = await get_pool().execute("DELETE FROM tags WHERE id=$1", tag_id)
    if n == "DELETE 0":
        raise HTTPException(404, "标签不存在")
    return {"ok": True}
