from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import get_pool
from ..services import references

router = APIRouter(prefix="/api/projects/{project_id}/references", tags=["references"])


class ReferenceIn(BaseModel):
    subject_kind: str
    subject_id: int
    purpose: str = "image"
    source_kind: str
    source_id: int | None = None
    canvas_slug: str = ""
    node_key: str = ""
    role: str = "manual"
    enabled: bool = True
    snapshot: dict[str, Any] = Field(default_factory=dict)


@router.get("")
async def list_references(project_id: int, subject_kind: str, subject_id: int,
                          purpose: str = "image"):
    return await references.list_resolved(
        get_pool(), project_id=project_id, subject_kind=subject_kind,
        subject_id=subject_id, purpose=purpose)


@router.post("")
async def add_reference(project_id: int, body: ReferenceIn):
    if body.source_kind not in {"element", "attachment", "canvas_node", "url"}:
        raise HTTPException(400, "不支持的参考来源")
    if body.subject_kind == "shot":
        try:
            return await references.add_shot_reference(
                get_pool(), project_id=project_id, shot_id=body.subject_id,
                purpose=body.purpose, source_kind=body.source_kind,
                source_id=body.source_id, snapshot=body.snapshot)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return await references.upsert(
        get_pool(), project_id=project_id, subject_kind=body.subject_kind,
        subject_id=body.subject_id, purpose=body.purpose, source_kind=body.source_kind,
        source_id=body.source_id, canvas_slug=body.canvas_slug, node_key=body.node_key,
        role=body.role, enabled=body.enabled, snapshot=body.snapshot)


@router.delete("/{reference_id}")
async def delete_reference(project_id: int, reference_id: int):
    if await references.remove_shot_reference(
            get_pool(), project_id=project_id, reference_id=reference_id):
        return {"ok": True}
    status = await get_pool().execute(
        "DELETE FROM content_reference_links WHERE id=$1 AND project_id=$2", reference_id, project_id)
    if status.endswith("0"):
        raise HTTPException(404, "参考关系不存在")
    return {"ok": True}
