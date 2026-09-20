"""Typed business-resource references used by workflow inputs and artifacts."""
from __future__ import annotations

from typing import Any

import asyncpg


class ResourceRefError(ValueError):
    pass


def parse(value: Any) -> tuple[str, int] | None:
    if isinstance(value, dict):
        kind, ident = value.get("kind") or value.get("type"), value.get("id")
    elif isinstance(value, str) and ":" in value:
        kind, ident = value.split(":", 1)
    else:
        return None
    try:
        ident = int(ident)
    except (TypeError, ValueError):
        raise ResourceRefError("target_ref must be <resource_kind>:<id>") from None
    if kind not in {"element", "content_node"} or ident <= 0:
        raise ResourceRefError("target_ref only supports element or content_node")
    return str(kind), ident


async def normalize_inputs(pool: asyncpg.Pool, inputs: dict[str, Any], project_id: int | None) -> dict[str, Any]:
    """Expand a typed target into legacy aliases consumed by existing operations."""
    out = dict(inputs or {})
    ref = parse(out.get("target_ref"))
    if not ref:
        return out
    kind, ident = ref
    out["target_ref"] = f"{kind}:{ident}"
    pid = int(project_id or out.get("project_id") or 0)
    if not pid:
        raise ResourceRefError("project_id is required with target_ref")
    out["project_id"] = pid
    if kind == "element":
        row = await pool.fetchrow(
            "SELECT id,kind,name FROM content_elements WHERE id=$1 AND project_id=$2", ident, pid)
        if not row:
            raise ResourceRefError("target element does not belong to this project")
        out["element_id"] = ident
        if row["kind"] == "scene":
            out.setdefault("scene_name", row["name"])
        return out
    row = await pool.fetchrow(
        "SELECT id,kind,parent_id,title FROM content_nodes WHERE id=$1 AND project_id=$2 AND deleted_at IS NULL", ident, pid)
    if not row:
        raise ResourceRefError("target content node does not belong to this project")
    if row["kind"] == "shot":
        out["shot_id"] = ident
        if row["parent_id"]:
            out.setdefault("chapter_id", row["parent_id"])
    return out


def target_from_inputs(inputs: dict[str, Any], fallback_node_id: int | None) -> tuple[str, int] | None:
    ref = parse(inputs.get("target_ref"))
    if ref:
        return ref
    if inputs.get("element_id"):
        return "element", int(inputs["element_id"])
    if inputs.get("shot_id"):
        return "content_node", int(inputs["shot_id"])
    if fallback_node_id:
        return "content_node", int(fallback_node_id)
    return None


def output_slot(config: dict[str, Any], inputs: dict[str, Any]) -> tuple[str, str | None] | None:
    """Read the user-facing output contract; legacy artifact_role is compatibility only."""
    raw = config.get("output_slot")
    if isinstance(raw, str) and raw:
        return raw, None
    if isinstance(raw, dict) and raw.get("role"):
        variant = raw.get("variant")
        if isinstance(variant, str) and variant == "{{input.variant_id}}":
            variant = inputs.get("variant_id")
        return str(raw["role"]), str(variant) if variant else None
    if config.get("artifact_role"):
        return str(config["artifact_role"]), None
    return None
