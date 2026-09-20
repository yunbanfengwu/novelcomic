"""案例库 API：案例分组 + 案例条目 CRUD + 素材上传（OSS 直传）。

案例=「标题 + 生成结果（视频/图）+ 提示词 + 带标签的参考素材（图/视频/音频）」，
是浏览型资料，与 kb_entries 知识库分离，规划引擎召回完全不感知本表。
后期项目内优秀镜头可通过 source='project' + project_id/shot_id 发布进来。
"""
import json
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import oss
from ..db import get_pool

router = APIRouter(prefix="/api/case-library", tags=["case-library"])

_MEDIA_EXTS = {".mp4", ".webm", ".mov", ".jpg", ".jpeg", ".png", ".webp",
               ".gif", ".mp3", ".wav", ".m4a", ".aac", ".ogg"}


def _entry_out(r: Any) -> dict:
    d = dict(r)
    d["refs"] = d["refs"] if isinstance(d["refs"], list) else json.loads(d["refs"] or "[]")
    return d


# ═══════════ 分组 ═══════════

@router.get("/groups")
async def list_groups():
    rows = await get_pool().fetch(
        """SELECT g.*, count(e.id) AS count FROM case_groups g
           LEFT JOIN case_entries e ON e.group_id = g.id
           GROUP BY g.id ORDER BY g.seq, g.id""")
    return [dict(r) for r in rows]


class GroupIn(BaseModel):
    title: str = Field(min_length=1)
    seq: int = 0


@router.post("/groups")
async def create_group(body: GroupIn):
    dup = await get_pool().fetchval("SELECT 1 FROM case_groups WHERE title=$1", body.title.strip())
    if dup:
        raise HTTPException(400, "同名分组已存在")
    r = await get_pool().fetchrow(
        "INSERT INTO case_groups (title, seq) VALUES ($1,$2) RETURNING *",
        body.title.strip(), body.seq)
    return {**dict(r), "count": 0}


@router.put("/groups/{group_id}")
async def update_group(group_id: int, body: GroupIn):
    r = await get_pool().fetchrow(
        "UPDATE case_groups SET title=$2, seq=$3 WHERE id=$1 RETURNING *",
        group_id, body.title.strip(), body.seq)
    if not r:
        raise HTTPException(404, "分组不存在")
    return dict(r)


@router.delete("/groups/{group_id}")
async def delete_group(group_id: int):
    """删分组；组内条目 group_id 置空（落到「未分组」），不连带删除案例。"""
    n = await get_pool().execute("DELETE FROM case_groups WHERE id=$1", group_id)
    if n == "DELETE 0":
        raise HTTPException(404, "分组不存在")
    return {"ok": True}


# ═══════════ 条目 ═══════════

@router.get("/entries")
async def list_entries(group_id: int | None = None):
    if group_id is not None:
        rows = await get_pool().fetch(
            "SELECT * FROM case_entries WHERE group_id=$1 ORDER BY seq, id", group_id)
    else:
        rows = await get_pool().fetch("SELECT * FROM case_entries ORDER BY seq, id")
    return [_entry_out(r) for r in rows]


class RefItem(BaseModel):
    kind: str = Field(pattern="^(image|video|audio)$")
    label: str = ""      # 如「图片1」「视频1（动作参考）」「音频1」
    url: str
    cover: str = ""      # 视频参考的封面（可空）


class EntryIn(BaseModel):
    group_id: int | None = None
    title: str = ""
    prompt: str = ""
    note: str = ""
    result_kind: str = Field(default="video", pattern="^(video|image)$")
    result_url: str = ""
    result_cover: str = ""
    refs: list[RefItem] = []
    seq: int = 0


@router.post("/entries")
async def create_entry(body: EntryIn):
    r = await get_pool().fetchrow(
        """INSERT INTO case_entries (group_id, title, prompt, note, result_kind,
               result_url, result_cover, refs, seq)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9) RETURNING *""",
        body.group_id, body.title.strip(), body.prompt, body.note, body.result_kind,
        body.result_url, body.result_cover,
        json.dumps([r.model_dump() for r in body.refs], ensure_ascii=False), body.seq)
    return _entry_out(r)


@router.put("/entries/{entry_id}")
async def update_entry(entry_id: int, body: EntryIn):
    r = await get_pool().fetchrow(
        """UPDATE case_entries SET group_id=$2, title=$3, prompt=$4, note=$5,
               result_kind=$6, result_url=$7, result_cover=$8, refs=$9::jsonb,
               seq=$10, updated_at=now()
           WHERE id=$1 RETURNING *""",
        entry_id, body.group_id, body.title.strip(), body.prompt, body.note,
        body.result_kind, body.result_url, body.result_cover,
        json.dumps([r.model_dump() for r in body.refs], ensure_ascii=False), body.seq)
    if not r:
        raise HTTPException(404, "案例不存在")
    return _entry_out(r)


@router.delete("/entries/{entry_id}")
async def delete_entry(entry_id: int):
    n = await get_pool().execute("DELETE FROM case_entries WHERE id=$1", entry_id)
    if n == "DELETE 0":
        raise HTTPException(404, "案例不存在")
    return {"ok": True}


# ═══════════ 素材上传（图/视频/音频 → OSS）═══════════

@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    ext = ""
    if file.filename and "." in file.filename:
        ext = "." + file.filename.rsplit(".", 1)[-1].lower()
    if ext not in _MEDIA_EXTS:
        raise HTTPException(400, f"不支持的文件类型 {ext or '(无扩展名)'}")
    data = await file.read()
    url = await oss.store_bytes(data, prefix="case-library", ext=ext)
    if not url:
        raise HTTPException(502, "OSS 未配置或上传失败")
    return {"url": url, "name": file.filename, "size": len(data)}
