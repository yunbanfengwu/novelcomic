"""Backend-owned canonical inputs resolved from the fixed smart selectors.

The UI submits only project / asset type / volume / chapter / shot / material.
This module expands those choices into stable canonical parameters, then matches
them to a workflow's public input schema. Adding a canonical field belongs here,
not in workflow-specific frontend branches.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

import asyncpg

from ..assets import get as get_asset_type


class CanonicalInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SmartInputSelection:
    project_id: int | None = None
    asset_type: str | None = None
    volume_id: int | None = None
    chapter_id: int | None = None
    shot_id: int | None = None
    material_kind: str | None = None
    material_ref: str | None = None


@dataclass(frozen=True, slots=True)
class CanonicalParameter:
    key: str
    value: Any
    label_zh: str
    value_type: str
    source: str
    display: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "value": self.value, "label_zh": self.label_zh,
            "type": self.value_type, "source": self.source,
            **({"display": self.display} if self.display else {}),
        }


@dataclass(frozen=True, slots=True)
class CanonicalField:
    label_zh: str
    value_type: str


STANDARD_FIELDS: dict[str, CanonicalField] = {
    "project_id": CanonicalField("项目", "int"),
    "project_title": CanonicalField("项目名称", "string"),
    "asset_type": CanonicalField("资产类型", "string"),
    "volume_id": CanonicalField("卷", "int"),
    "volume_title": CanonicalField("卷名称", "string"),
    "chapter_id": CanonicalField("章", "int"),
    "chapter_title": CanonicalField("章名称", "string"),
    "shot_id": CanonicalField("分镜", "int"),
    "shot_title": CanonicalField("分镜名称", "string"),
    "content_node_id": CanonicalField("内容节点", "int"),
    "content_node_kind": CanonicalField("内容节点类型", "string"),
    "content_node_title": CanonicalField("内容节点名称", "string"),
    "element_id": CanonicalField("要素", "int"),
    "element_kind": CanonicalField("要素类型", "string"),
    "element_name": CanonicalField("要素名称", "string"),
    "scene_id": CanonicalField("场景", "int"),
    "scene_name": CanonicalField("场景名称", "string"),
    "character_id": CanonicalField("角色", "int"),
    "character_name": CanonicalField("角色名称", "string"),
    "prop_id": CanonicalField("道具", "int"),
    "prop_name": CanonicalField("道具名称", "string"),
    "material_ref": CanonicalField("素材", "resource"),
    "material_id": CanonicalField("素材 ID", "int"),
    "material_kind": CanonicalField("素材类型", "string"),
    "material_name": CanonicalField("素材名称", "string"),
    "material_url": CanonicalField("素材地址", "string"),
    "target_ref": CanonicalField("关联对象", "resource"),
    "target_kind": CanonicalField("关联对象类型", "string"),
    "target_id": CanonicalField("关联对象 ID", "int"),
    "target_name": CanonicalField("关联对象名称", "string"),
    "source_type": CanonicalField("来源类型", "string"),
    "source_ref": CanonicalField("来源对象", "resource"),
    "related_element_ids": CanonicalField("指定要素", "array"),
}


@dataclass(slots=True)
class CanonicalInputs:
    _parameters: dict[str, CanonicalParameter] = field(default_factory=dict)

    def put(self, key: str, value: Any, *, source: str,
            display: str | None = None, label_zh: str | None = None,
            value_type: str | None = None) -> None:
        if value is None or value == "":
            return
        field_spec = STANDARD_FIELDS.get(key, CanonicalField(key, "string"))
        previous = self._parameters.get(key)
        self._parameters[key] = CanonicalParameter(
            key=key, value=value,
            label_zh=label_zh or (previous.label_zh if previous else field_spec.label_zh),
            value_type=value_type or (previous.value_type if previous else field_spec.value_type),
            source=source, display=display or (previous.display if previous else None))

    def get(self, key: str) -> CanonicalParameter | None:
        return self._parameters.get(key)

    def parameters(self) -> list[dict[str, Any]]:
        return [item.as_dict() for item in self._parameters.values()]

    def labels(self, input_schema: dict[str, Any]) -> dict[str, str]:
        """Chinese display names for public canonical fields in a workflow schema."""
        labels: dict[str, str] = {}
        for key, raw_field in input_schema.items():
            schema_field = raw_field if isinstance(raw_field, dict) else {}
            if (schema_field.get("ui") or {}).get("hide"):
                continue
            parameter = self.get(key)
            field_spec = STANDARD_FIELDS.get(key)
            if parameter:
                labels[key] = parameter.label_zh
            elif field_spec:
                labels[key] = field_spec.label_zh
        return labels

    def match(self, input_schema: dict[str, Any]) -> dict[str, str]:
        """Return only public workflow inputs whose keys are canonical matches."""
        matched: dict[str, str] = {}
        for key, raw_field in input_schema.items():
            schema_field = raw_field if isinstance(raw_field, dict) else {}
            if (schema_field.get("ui") or {}).get("hide"):
                continue
            parameter = self.get(key)
            if not parameter:
                continue
            if key in {"project_id", "volume_id", "chapter_id", "shot_id", "target_ref"} \
                    and parameter.display:
                matched[key] = parameter.display
            elif isinstance(parameter.value, (dict, list)):
                matched[key] = json.dumps(parameter.value, ensure_ascii=False, separators=(",", ":"))
            else:
                matched[key] = str(parameter.value)
        return matched


def _positive(value: int | None) -> int | None:
    return value if value and value > 0 else None


def _parse_material_ref(value: str | None) -> tuple[str, int] | None:
    if not value:
        return None
    try:
        kind, raw_id = value.split(":", 1)
        ident = int(raw_id)
    except (TypeError, ValueError):
        raise CanonicalInputError("material_ref must be <resource_kind>:<id>") from None
    if kind not in {"element", "attachment"} or ident <= 0:
        raise CanonicalInputError("material_ref only supports element or attachment")
    return kind, ident


def _friendly(ident: int, name: str) -> str:
    return f"{ident} · {name}"


def _material_url(meta: Any) -> str | None:
    data = meta if isinstance(meta, dict) else {}
    if data.get("sheet_url"):
        return str(data["sheet_url"])
    for variant in data.get("variants") or []:
        if isinstance(variant, dict) and variant.get("sheet_url"):
            return str(variant["sheet_url"])
    return None


async def resolve_canonical_inputs(pool: asyncpg.Pool,
                                   selection: SmartInputSelection) -> CanonicalInputs:
    """Resolve fixed smart choices into an extensible canonical parameter set."""
    node_cache: dict[int, dict[str, Any] | None] = {}

    async def node(ident: int | None) -> dict[str, Any] | None:
        if not ident:
            return None
        if ident not in node_cache:
            row = await pool.fetchrow(
                "SELECT id,project_id,parent_id,kind,title FROM content_nodes "
                "WHERE id=$1 AND deleted_at IS NULL", ident)
            node_cache[ident] = dict(row) if row else None
        return node_cache[ident]

    async def ancestors(row: dict[str, Any] | None) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[int] = set()
        parent_id = int(row["parent_id"]) if row and row.get("parent_id") else None
        while parent_id and parent_id not in seen:
            seen.add(parent_id)
            parent = await node(parent_id)
            if not parent:
                break
            result.append(parent)
            parent_id = int(parent["parent_id"]) if parent.get("parent_id") else None
        return result

    volume = await node(_positive(selection.volume_id))
    chapter = await node(_positive(selection.chapter_id))
    shot = await node(_positive(selection.shot_id))
    for expected, row in (("volume", volume), ("chapter", chapter), ("shot", shot)):
        selected_id = getattr(selection, f"{expected}_id")
        if selected_id and (not row or row["kind"] != expected):
            raise CanonicalInputError(f"{expected}_id does not reference a {expected}")

    shot_ancestors = await ancestors(shot)
    inferred_chapter = next((item for item in shot_ancestors if item["kind"] == "chapter"), None)
    if chapter and inferred_chapter and chapter["id"] != inferred_chapter["id"]:
        raise CanonicalInputError("shot_id does not belong to chapter_id")
    chapter = chapter or inferred_chapter
    chapter_ancestors = await ancestors(chapter)
    inferred_volume = next((item for item in chapter_ancestors if item["kind"] == "volume"), None)
    if volume and inferred_volume and volume["id"] != inferred_volume["id"]:
        raise CanonicalInputError("chapter_id does not belong to volume_id")
    volume = volume or inferred_volume

    selected_material_kind = (selection.material_kind or "").strip() or None
    material_kind_id = _parse_material_ref(selection.material_ref)
    material: dict[str, Any] | None = None
    attachment: dict[str, Any] | None = None
    if material_kind_id and material_kind_id[0] == "element":
        row = await pool.fetchrow(
            "SELECT id,project_id,kind,name,meta FROM content_elements WHERE id=$1",
            material_kind_id[1])
        material = dict(row) if row else None
        if not material:
            raise CanonicalInputError("material_ref element does not exist")
    elif material_kind_id:
        row = await pool.fetchrow(
            "SELECT id,project_id,kind,url,meta FROM content_attachments WHERE id=$1",
            material_kind_id[1])
        attachment = dict(row) if row else None
        if not attachment:
            raise CanonicalInputError("material_ref attachment does not exist")
    resolved_material_kind = str((material or attachment or {}).get("kind") or "") or None
    if selected_material_kind and resolved_material_kind \
            and selected_material_kind != resolved_material_kind:
        raise CanonicalInputError("material_ref does not match material_kind")

    project_ids = {
        int(value) for value in (
            _positive(selection.project_id),
            volume and volume["project_id"], chapter and chapter["project_id"],
            shot and shot["project_id"], material and material["project_id"],
            attachment and attachment["project_id"],
        ) if value
    }
    if len(project_ids) > 1:
        raise CanonicalInputError("smart selections must belong to the same project")
    project_id = next(iter(project_ids), None)
    project = None
    if project_id:
        row = await pool.fetchrow(
            "SELECT id,title FROM content_projects WHERE id=$1 AND deleted_at IS NULL", project_id)
        project = dict(row) if row else None
        if not project:
            raise CanonicalInputError("project does not exist")

    canonical = CanonicalInputs()
    if project:
        canonical.put("project_id", project["id"], source="project",
                      display=_friendly(project["id"], project["title"]))
        canonical.put("project_title", project["title"], source="project")
    if selection.asset_type:
        try:
            asset = get_asset_type(selection.asset_type)
        except ValueError as exc:
            raise CanonicalInputError(str(exc)) from exc
        canonical.put("asset_type", asset.code, source="asset_contract")
    else:
        asset = None
    canonical.put("material_kind", selected_material_kind or resolved_material_kind,
                  source="material_selection")

    for key, row in (("volume", volume), ("chapter", chapter), ("shot", shot)):
        if not row:
            continue
        canonical.put(f"{key}_id", row["id"], source="content_node",
                      display=_friendly(row["id"], row["title"]))
        canonical.put(f"{key}_title", row["title"], source="content_node")

    if shot:
        canonical.put("content_node_id", shot["id"], source="content_node")
        canonical.put("content_node_kind", shot["kind"], source="content_node")
        canonical.put("content_node_title", shot["title"], source="content_node")

    material_ref = None
    if material:
        material_ref = f"element:{material['id']}"
        canonical.put("material_ref", material_ref, source="element",
                      display=f"{material_ref} · {material['name']}")
        canonical.put("material_id", material["id"], source="element")
        canonical.put("material_kind", material["kind"], source="element")
        canonical.put("material_name", material["name"], source="element")
        canonical.put("material_url", _material_url(material.get("meta")), source="element")
        canonical.put("element_id", material["id"], source="element")
        canonical.put("element_kind", material["kind"], source="element")
        canonical.put("element_name", material["name"], source="element")
        if material["kind"] in {"scene", "character", "prop"}:
            canonical.put(f"{material['kind']}_id", material["id"], source="element")
            canonical.put(f"{material['kind']}_name", material["name"], source="element")
        canonical.put("related_element_ids", [material["id"]], source="element")
    elif attachment:
        material_ref = f"attachment:{attachment['id']}"
        material_name = str((attachment.get("meta") or {}).get("name") or f"附件 {attachment['id']}")
        canonical.put("material_ref", material_ref, source="attachment",
                      display=f"{material_ref} · {material_name}")
        canonical.put("material_id", attachment["id"], source="attachment")
        canonical.put("material_kind", attachment["kind"], source="attachment")
        canonical.put("material_name", material_name, source="attachment")
        canonical.put("material_url", attachment.get("url"), source="attachment")

    if shot:
        source_ref, source_type = f"content_node:{shot['id']}", "shot.dynamic_elements"
    elif chapter:
        source_ref, source_type = f"content_node:{chapter['id']}", "chapter.appearing_elements"
    elif material:
        source_ref, source_type = material_ref, "explicit.element_ids"
    elif project:
        source_ref, source_type = f"project:{project['id']}", "project.elements"
    else:
        source_ref = source_type = None
    canonical.put("source_ref", source_ref, source="selection_scope")
    canonical.put("source_type", source_type, source="selection_scope")

    target: dict[str, Any] | None = None
    target_ref: str | None = None
    if asset and asset.target_ref_kind == "element" and material:
        if not asset.target_content_kind or material["kind"] == asset.target_content_kind:
            target, target_ref = material, f"element:{material['id']}"
    elif asset and asset.target_ref_kind == "content_node":
        candidates = [item for item in (shot, chapter, volume) if item]
        target = next((item for item in candidates
                       if not asset.target_content_kind or item["kind"] == asset.target_content_kind), None)
        if target:
            target_ref = f"content_node:{target['id']}"
    elif asset and asset.target_ref_kind == "attachment" and attachment:
        target, target_ref = attachment, f"attachment:{attachment['id']}"

    if target and target_ref:
        target_name = str(target.get("name") or target.get("title") or f"{target['id']}")
        canonical.put("target_ref", target_ref, source="asset_contract",
                      display=f"{target_ref} · {target_name}")
        canonical.put("target_kind", target_ref.split(":", 1)[0], source="asset_contract")
        canonical.put("target_id", target["id"], source="asset_contract")
        canonical.put("target_name", target_name, source="asset_contract")

        path_values = {
            "target.id": target["id"],
            "target.name": target_name,
            "target.kind": target.get("kind"),
            "target.parent_id": target.get("parent_id"),
            "target.project_id": target.get("project_id"),
        }
        for key, path in asset.context_bindings:
            canonical.put(key, path_values.get(path), source="asset_contract")

    return canonical
