"""Generic read path for code-defined asset types.

The registry describes the semantic/media contract.  This module applies that
contract to a typed business reference and keeps legacy project data readable
while new TapFlow outputs are gradually indexed in ``workflow_artifacts``.
"""
from __future__ import annotations

import json
from typing import Any

import asyncpg

from .registry import get


_LEGACY_KEYS = {
    "image": ("sheet_url", "keyframe_url", "image_url", "url"),
    "video": ("video_url", "url"),
    "audio": ("audio_url", "voice_url", "url"),
    "text": ("text", "content", "summary"),
}


def _json_obj(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _legacy_value(meta: Any, media_kind: str) -> str | None:
    """Read only primary/variant output slots; never mistake references for output."""
    obj = _json_obj(meta)
    keys = _LEGACY_KEYS.get(media_kind, ("url",))
    for key in keys:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    variants = obj.get("variants")
    if isinstance(variants, list):
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            for key in keys:
                value = variant.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


def _parse_target_ref(value: str) -> tuple[str, int]:
    try:
        kind, raw_id = str(value or "").split(":", 1)
        ident = int(raw_id)
    except (TypeError, ValueError):
        raise ValueError("target_ref must be <resource_kind>:<id>") from None
    if kind not in {"element", "content_node"} or ident <= 0:
        raise ValueError("target_ref only supports element or content_node")
    return kind, ident


async def read_latest(
    pool: asyncpg.Pool, *, project_id: int, asset_type: str, target_ref: str,
) -> dict[str, Any] | None:
    """Return the latest compatible asset for a typed target without side effects.

    New indexed artifacts are authoritative.  A compatible-media fallback lets a
    generic image workflow display an existing character/prop/scene image for the
    same element.  Legacy meta/attachment reads keep pre-index assets visible.
    """
    contract = get(asset_type)
    if "read" not in contract.operations:
        return None
    target_kind, target_id = _parse_target_ref(target_ref)

    rows = await pool.fetch(
        "SELECT id,asset_type,attachment_id,url FROM workflow_artifacts "
        "WHERE project_id=$1 AND target_kind=$2 AND target_id=$3 "
        "AND url IS NOT NULL AND url<>'' ORDER BY (asset_type=$4) DESC,created_at DESC,id DESC LIMIT 50",
        int(project_id), target_kind, target_id, asset_type)
    for row in rows:
        row_type = str(row["asset_type"] or "")
        try:
            compatible = row_type == asset_type or get(row_type).media_kind == contract.media_kind
        except ValueError:
            compatible = row_type == asset_type
        if compatible and row["url"]:
            return {"url": row["url"], "artifact_id": row["id"],
                    "attachment_id": row["attachment_id"], "asset_type": row_type or asset_type,
                    "source": "workflow_artifact"}

    table = "content_elements" if target_kind == "element" else "content_nodes"
    row = await pool.fetchrow(
        f"SELECT meta FROM {table} WHERE id=$1 AND project_id=$2", target_id, int(project_id))
    value = _legacy_value(row["meta"] if row else None, contract.media_kind)
    if value:
        return {"url": value, "asset_type": asset_type, "source": f"{table}.meta"}

    owner_column = "element_id" if target_kind == "element" else "node_id"
    attachment_kind = {"image": "image", "video": "video", "audio": "audio"}.get(contract.media_kind)
    if attachment_kind:
        attachment = await pool.fetchrow(
            f"SELECT id,url FROM content_attachments WHERE project_id=$1 AND {owner_column}=$2 "
            "AND kind=$3 AND url IS NOT NULL AND url<>'' ORDER BY id DESC LIMIT 1",
            int(project_id), target_id, attachment_kind)
        if attachment and attachment["url"]:
            return {"url": attachment["url"], "attachment_id": attachment["id"],
                    "asset_type": asset_type, "source": "content_attachment"}
    return None
