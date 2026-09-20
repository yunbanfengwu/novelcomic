"""分镜回收站 API（跨项目，可按项目筛选）：列出被软删除的分镜（手动删除本镜 / 重拆镜整集移入），
彻底删除（物理级联清附件行；OSS 文件与项目回收站同口径不主动清）。依产品要求：暂不做恢复。

同一次删除的所有镜共享同一 deleted_at（Postgres now() 每语句求值一次）→ 前端按 (章, deleted_at)
天然分组成「一批」（重拆镜=整集一批；删除本镜=单镜一批）。只呈现存活项目的回收分镜——
项目本身在回收站的走项目回收站处理。
"""
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import get_pool

router = APIRouter(prefix="/api/shot-trash", tags=["shot-trash"])


def _jsonb(v: Any) -> Any:
    return v if isinstance(v, (dict, list)) else (json.loads(v) if v else {})


@router.get("/projects")
async def trash_projects():
    """有回收分镜的项目清单（供回收站内项目筛选下拉）：项目名 + 回收镜数 + 最近删除时间。"""
    rows = await get_pool().fetch(
        "SELECT s.project_id, p.title, count(*) AS cnt, max(s.deleted_at) AS last_deleted "
        "FROM content_nodes s JOIN content_projects p ON p.id = s.project_id "
        "WHERE s.kind='shot' AND s.deleted_at IS NOT NULL AND p.deleted_at IS NULL "
        "GROUP BY s.project_id, p.title ORDER BY last_deleted DESC"
    )
    return [dict(r) for r in rows]


@router.get("")
async def list_shot_trash(project_id: int | None = None):
    """回收分镜列表（可选按项目筛选）：带项目/章节标注 + 视频/首帧缩略图字段（取自 meta），
    按删除时间倒序。前端按 (chapter_id, deleted_at) 分组成批次展示。"""
    rows = await get_pool().fetch(
        "SELECT s.id, s.project_id, s.parent_id AS chapter_id, s.seq, s.summary, s.meta, s.deleted_at, "
        "p.title AS project_title, c.seq AS chapter_seq, c.title AS chapter_title "
        "FROM content_nodes s "
        "JOIN content_projects p ON p.id = s.project_id "
        "LEFT JOIN content_nodes c ON c.id = s.parent_id "
        "WHERE s.kind='shot' AND s.deleted_at IS NOT NULL AND p.deleted_at IS NULL "
        "AND ($1::bigint IS NULL OR s.project_id=$1) "
        "ORDER BY s.deleted_at DESC, c.seq, s.seq",
        project_id,
    )
    out = []
    for r in rows:
        m = _jsonb(r["meta"])
        out.append({
            "id": r["id"], "project_id": r["project_id"], "project_title": r["project_title"],
            "chapter_id": r["chapter_id"], "chapter_seq": r["chapter_seq"],
            "chapter_title": r["chapter_title"], "seq": r["seq"],
            "shot_no": m.get("shot_no"), "summary": r["summary"],
            "duration_s": m.get("duration_s"),
            "video_url": m.get("video_url"),
            "video_cover_url": m.get("video_cover_url") or m.get("keyframe_url"),
            "keyframe_url": m.get("keyframe_url"),
            "last_frame_url": m.get("last_frame_url"),
            "deleted_at": r["deleted_at"],
        })
    return out


@router.delete("/{shot_id}")
async def purge_shot(shot_id: int):
    """彻底删除单个回收分镜（物理删除，附件行随 FK 级联清理）：仅限已在回收站的镜。"""
    r = await get_pool().execute(
        "DELETE FROM content_nodes WHERE id=$1 AND kind='shot' AND deleted_at IS NOT NULL", shot_id)
    if r.rsplit(" ", 1)[-1] == "0":
        raise HTTPException(404, "分镜不在回收站")
    return {"ok": True, "id": shot_id}


class PurgeBatchIn(BaseModel):
    shot_ids: list[int]


@router.post("/purge-batch")
async def purge_shot_batch(body: PurgeBatchIn):
    """彻底删除一批回收分镜（如整集/整批）：只物理删已在回收站的镜，返回实际删除数。"""
    if not body.shot_ids:
        raise HTTPException(400, "缺少 shot_ids")
    r = await get_pool().execute(
        "DELETE FROM content_nodes WHERE kind='shot' AND deleted_at IS NOT NULL AND id = ANY($1::bigint[])",
        body.shot_ids)
    return {"ok": True, "deleted": int(r.rsplit(" ", 1)[-1])}
