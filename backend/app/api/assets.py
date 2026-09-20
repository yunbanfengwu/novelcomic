"""Read-only API for the backend-defined asset type registry and asset instances."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..assets import all_types, get
from ..db import get_pool

router = APIRouter(prefix="/api/assets", tags=["assets"])


def _type_dict(item):
    return {"code": item.code, "name": item.name, "media_kind": item.media_kind,
            "tags": item.tags, "subject_kind": item.subject_kind, "storage": item.storage,
            "operations": item.operations, "async_default": item.async_default,
            "target_ref_kind": item.target_ref_kind,
            "target_content_kind": item.target_content_kind,
            "context_bindings": item.context_bindings,
            "target_scope_levels": [
                {"key": key, "label": label, "required": required}
                for key, label, required in item.target_scope_levels
            ],
            "allows_variant": item.allows_variant, "allows_version": item.allows_version}


@router.get("/types")
async def list_asset_types():
    return [_type_dict(item) for item in all_types()]


@router.get("/types/{code:path}/targets")
async def list_asset_targets(code: str, project_id: int):
    """Return contract-filtered business targets and generic cascade metadata."""
    try:
        item = get(code)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    pool = get_pool()
    if item.target_ref_kind == "element":
        rows = await pool.fetch(
            "SELECT id,kind,name FROM content_elements WHERE project_id=$1 "
            "AND ($2::text IS NULL OR kind=$2) ORDER BY kind,name,id",
            project_id, item.target_content_kind)
        targets = [{"ref": f"element:{row['id']}", "name": row["name"],
                    "kind": row["kind"], "scopes": {}} for row in rows]
        return {"asset_type": _type_dict(item), "levels": [], "targets": targets}
    if item.target_ref_kind == "content_node":
        rows = await pool.fetch(
            "SELECT id,parent_id,kind,seq,title FROM content_nodes "
            "WHERE project_id=$1 AND deleted_at IS NULL ORDER BY seq,id", project_id)
        by_id = {int(row["id"]): row for row in rows}
        targets = []
        for row in rows:
            if item.target_content_kind and row["kind"] != item.target_content_kind:
                continue
            scopes: dict[str, dict[str, str]] = {}
            parent_id = row["parent_id"]
            seen: set[int] = set()
            while parent_id and int(parent_id) not in seen:
                seen.add(int(parent_id))
                parent = by_id.get(int(parent_id))
                if not parent:
                    break
                kind = str(parent["kind"])
                scopes[kind] = {"value": str(parent["id"]), "name": parent["title"]}
                parent_id = parent["parent_id"]
            targets.append({"ref": f"content_node:{row['id']}", "name": row["title"],
                            "kind": row["kind"], "scopes": scopes})
        levels = [{"key": key, "label": label, "required": required}
                  for key, label, required in item.target_scope_levels]
        return {"asset_type": _type_dict(item), "levels": levels, "targets": targets}
    return {"asset_type": _type_dict(item), "levels": [], "targets": []}


@router.get("/types/{code:path}")
async def get_asset_type(code: str):
    try:
        item = get(code)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _type_dict(item)


@router.get("")
async def list_assets(project_id: int, asset_type: str | None = None,
                      subject_kind: str | None = None, subject_id: int | None = None):
    rows = await get_pool().fetch(
        "SELECT id,project_id,asset_type,subject_kind,subject_id,variant,version,attachment_id,url,created_at "
        "FROM workflow_artifacts WHERE project_id=$1 "
        "AND ($2::text IS NULL OR asset_type=$2) "
        "AND ($3::text IS NULL OR subject_kind=$3) "
        "AND ($4::bigint IS NULL OR subject_id=$4) "
        "ORDER BY created_at DESC,id DESC",
        project_id, asset_type, subject_kind, subject_id)
    return [dict(row) for row in rows]
