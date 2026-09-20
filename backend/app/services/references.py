"""统一参考关系：稳定身份是主键，URL 只是可追溯快照。

旧生产仍读 content_nodes.meta.reference_images/extra_refs/element_ids，因此迁移期采用：
旧入口写 meta 后 sync_shot_from_legacy；新入口写关系后 mirror_shot_to_legacy。
两边最终都经过本模块，避免三套 UI 各自维护一份引用关系。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

import asyncpg


def _j(v: Any) -> dict[str, Any]:
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return {}


def source_key(source_kind: str, *, source_id: int | None = None,
               canvas_slug: str = "", node_key: str = "", url: str = "") -> str:
    if source_kind in {"element", "attachment"} and source_id:
        return f"{source_kind}:{source_id}"
    if source_kind == "canvas_node" and canvas_slug and node_key:
        return f"canvas:{canvas_slug}:{node_key}"
    return "url:" + hashlib.sha256((url or "").encode("utf-8")).hexdigest()[:24]


async def upsert(pool: asyncpg.Pool, *, project_id: int, subject_kind: str, subject_id: int,
                 purpose: str, source_kind: str, source_id: int | None = None,
                 canvas_slug: str = "", node_key: str = "", role: str = "manual",
                 enabled: bool = True, seq: int = 0,
                 snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    snap = snapshot or {}
    key = source_key(source_kind, source_id=source_id, canvas_slug=canvas_slug,
                     node_key=node_key, url=str(snap.get("url") or ""))
    row = await pool.fetchrow(
        "INSERT INTO content_reference_links(project_id,subject_kind,subject_id,purpose,"
        "source_kind,source_key,source_id,source_canvas_slug,source_node_key,role,enabled,seq,snapshot) "
        "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb) "
        "ON CONFLICT(project_id,subject_kind,subject_id,purpose,source_key) DO UPDATE SET "
        "project_id=excluded.project_id,source_id=excluded.source_id,"
        "source_canvas_slug=excluded.source_canvas_slug,source_node_key=excluded.source_node_key,"
        "role=excluded.role,enabled=excluded.enabled,seq=excluded.seq,snapshot=excluded.snapshot,"
        "updated_at=now() RETURNING *",
        project_id, subject_kind, subject_id, purpose, source_kind, key, source_id,
        canvas_slug or None, node_key or None, role, enabled, seq,
        json.dumps(snap, ensure_ascii=False))
    return dict(row)


async def _attachment_id(pool: asyncpg.Pool, project_id: int, url: str) -> int | None:
    if not url:
        return None
    return await pool.fetchval(
        "SELECT id FROM content_attachments WHERE project_id=$1 AND url=$2 ORDER BY id DESC LIMIT 1",
        project_id, url)


async def sync_shot_from_legacy(pool: asyncpg.Pool, project_id: int, shot_id: int,
                                purpose: str = "image") -> None:
    """把现有面板/生产字段收敛进关系表；幂等，可在每次读取前自愈历史数据。"""
    row = await pool.fetchrow(
        "SELECT meta FROM content_nodes WHERE id=$1 AND project_id=$2 AND kind='shot'", shot_id, project_id)
    if not row:
        return
    meta = _j(row["meta"])
    off = set((_j(meta.get("ref_off"))).get(purpose) or [])
    desired: set[str] = set()
    seq = 0
    element_ids = [int(x) for x in (meta.get("element_ids") or []) if str(x).isdigit()]
    target = "image" if purpose == "image" else "video"
    for required in meta.get("required_refs") or []:
        rid = required.get("element_id")
        targets = required.get("targets") or []
        if rid and (not targets or target in targets) and int(rid) not in element_ids:
            element_ids.append(int(rid))
    if element_ids:
        elems = await pool.fetch(
            "SELECT id,kind,name,meta FROM content_elements WHERE project_id=$1 AND id=ANY($2::bigint[])",
            project_id, element_ids)
        by_id = {int(e["id"]): e for e in elems}
        for eid in element_ids:
            e = by_id.get(eid)
            if not e:
                continue
            em = _j(e["meta"])
            snap = {"name": e["name"], "kind": e["kind"], "url": em.get("sheet_url")}
            got = await upsert(pool, project_id=project_id, subject_kind="shot", subject_id=shot_id,
                               purpose=purpose, source_kind="element", source_id=eid,
                               role=str(e["kind"]), enabled=e["name"] not in off, seq=seq, snapshot=snap)
            desired.add(got["source_key"]); seq += 1
    extras = [*(meta.get("extra_refs") or [])]
    # 场景组空间图等不是普通 element，但也是生产面板已经装配好的稳定引用。
    # element 引用按 id 解析最新设定图，这里只补充非 element 的 reference_images。
    element_urls = {
        str((_j(e["meta"])).get("sheet_url") or "") for e in (elems if element_ids else [])
    }
    seen_urls = {str(r.get("url") or "") for r in extras}
    for ref in meta.get("reference_images") or []:
        url = str(ref.get("url") or "")
        if url and url not in element_urls and url not in seen_urls:
            extras.append(ref)
            seen_urls.add(url)
    sb = meta.get("storyboard_ref") or {}
    if purpose == "image" and sb.get("url"):
        extras.append({"name": "故事板", "kind": "storyboard", "url": sb["url"]})
    for ref in extras:
        url = str(ref.get("url") or "")
        if not url:
            continue
        aid = await _attachment_id(pool, project_id, url)
        sk = "attachment" if aid else "url"
        got = await upsert(pool, project_id=project_id, subject_kind="shot", subject_id=shot_id,
                           purpose=purpose, source_kind=sk, source_id=aid, role="manual",
                           enabled=str(ref.get("name") or "") not in off, seq=seq,
                           snapshot={"name": ref.get("name"), "kind": ref.get("kind"), "url": url})
        desired.add(got["source_key"]); seq += 1
    # 关系表是镜像后的真源：面板已移除的条目同步删除，避免旧画布仍看到幽灵参考。
    if desired:
        await pool.execute(
            "DELETE FROM content_reference_links WHERE project_id=$1 AND subject_kind='shot' "
            "AND subject_id=$2 AND purpose=$3 AND NOT(source_key=ANY($4::text[]))",
            project_id, shot_id, purpose, list(desired))
    else:
        await pool.execute(
            "DELETE FROM content_reference_links WHERE project_id=$1 AND subject_kind='shot' "
            "AND subject_id=$2 AND purpose=$3", project_id, shot_id, purpose)


async def list_resolved(pool: asyncpg.Pool, *, project_id: int, subject_kind: str,
                        subject_id: int, purpose: str = "image") -> list[dict[str, Any]]:
    if subject_kind == "shot":
        await sync_shot_from_legacy(pool, project_id, subject_id, purpose)
    rows = await pool.fetch(
        "SELECT * FROM content_reference_links WHERE project_id=$1 AND subject_kind=$2 "
        "AND subject_id=$3 AND purpose=$4 ORDER BY seq,id",
        project_id, subject_kind, subject_id, purpose)
    out: list[dict[str, Any]] = []
    for raw in rows:
        r = dict(raw); snap = _j(r["snapshot"])
        if r["source_kind"] == "element" and r["source_id"]:
            e = await pool.fetchrow("SELECT kind,name,meta FROM content_elements WHERE id=$1", r["source_id"])
            if e:
                em = _j(e["meta"]); snap.update({"name": e["name"], "kind": e["kind"],
                                                  "url": em.get("sheet_url")})
        elif r["source_kind"] == "attachment" and r["source_id"]:
            a = await pool.fetchrow("SELECT kind,url,meta FROM content_attachments WHERE id=$1", r["source_id"])
            if a:
                am = _j(a["meta"]); snap.update({"url": a["url"],
                    "name": am.get("name") or snap.get("name"), "kind": snap.get("kind") or a["kind"]})
        r["snapshot"] = snap
        r.update({"name": snap.get("name") or r["source_key"], "kind": snap.get("kind") or r["role"],
                  "url": snap.get("url")})
        out.append(r)
    return out


async def resolved_images(pool: asyncpg.Pool, *, project_id: int, subject_kind: str,
                          subject_id: int, purpose: str = "image") -> list[dict[str, Any]]:
    return [{"name": r["name"], "kind": r["kind"], "url": r["url"],
             "element_id": r["source_id"] if r["source_kind"] == "element" else None,
             "reference_id": r["id"]}
            for r in await list_resolved(pool, project_id=project_id, subject_kind=subject_kind,
                                         subject_id=subject_id, purpose=purpose)
            if r["enabled"] and r.get("url")]


async def add_shot_reference(pool: asyncpg.Pool, *, project_id: int, shot_id: int,
                             purpose: str, source_kind: str,
                             source_id: int | None = None,
                             snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """新画布写入时回写兼容字段；旧面板无需理解关系表也能立即看到。"""
    row = await pool.fetchrow(
        "SELECT meta FROM content_nodes WHERE id=$1 AND project_id=$2 AND kind='shot'",
        shot_id, project_id)
    if not row:
        raise ValueError("shot not found")
    meta = _j(row["meta"])
    snap = snapshot or {}
    if source_kind == "element" and source_id:
        elem = await pool.fetchrow(
            "SELECT id,kind,name FROM content_elements WHERE id=$1 AND project_id=$2",
            source_id, project_id)
        if not elem:
            raise ValueError("element not found")
        ids = [int(x) for x in (meta.get("element_ids") or []) if str(x).isdigit()]
        if source_id not in ids:
            ids.append(source_id)
        meta["element_ids"] = ids
        chars = list(meta.get("characters") or [])
        if elem["kind"] == "character" and elem["name"] not in chars:
            chars.append(elem["name"])
        meta["characters"] = chars
        if elem["kind"] == "scene" and not meta.get("scene_element"):
            meta["scene_element"] = elem["name"]
        await pool.execute(
            "INSERT INTO element_appearances(project_id,element_id,node_id,snapshot) "
            "VALUES($1,$2,$3,'') ON CONFLICT(element_id,node_id) DO NOTHING",
            project_id, source_id, shot_id)
    elif snap.get("url"):
        refs = list(meta.get("extra_refs") or [])
        if not any((r.get("url") == snap.get("url")) for r in refs):
            refs.append({"name": snap.get("name") or "参考资产",
                         "kind": snap.get("kind") or source_kind,
                         "url": snap["url"]})
        meta["extra_refs"] = refs
    else:
        raise ValueError("reference requires element id or url")
    await pool.execute("UPDATE content_nodes SET meta=$1::jsonb,updated_at=now() WHERE id=$2",
                       json.dumps(meta, ensure_ascii=False), shot_id)
    if source_kind == "element":
        from .storyboard import assemble_shot_prompts
        await assemble_shot_prompts(pool, project_id, shot_id)
    for target_purpose in ("image", "video", "last"):
        await sync_shot_from_legacy(pool, project_id, shot_id, target_purpose)
    key = source_key(source_kind, source_id=source_id, url=str(snap.get("url") or ""))
    rows = await list_resolved(pool, project_id=project_id, subject_kind="shot",
                               subject_id=shot_id, purpose=purpose)
    return next((r for r in rows if r["source_key"] == key), rows[-1] if rows else {})


async def remove_shot_reference(pool: asyncpg.Pool, *, project_id: int,
                                reference_id: int) -> bool:
    """从统一关系删除时同步清理旧 meta，避免旧无限画布重新把它投影回来。"""
    rel = await pool.fetchrow(
        "SELECT * FROM content_reference_links WHERE id=$1 AND project_id=$2 "
        "AND subject_kind='shot'", reference_id, project_id)
    if not rel:
        return False
    row = await pool.fetchrow("SELECT meta FROM content_nodes WHERE id=$1", rel["subject_id"])
    if not row:
        return False
    meta = _j(row["meta"])
    snap = _j(rel["snapshot"])
    if rel["source_kind"] == "element" and rel["source_id"]:
        eid = int(rel["source_id"])
        elem = await pool.fetchrow("SELECT kind,name FROM content_elements WHERE id=$1", eid)
        meta["element_ids"] = [int(x) for x in (meta.get("element_ids") or [])
                               if str(x).isdigit() and int(x) != eid]
        if elem:
            meta["characters"] = [name for name in (meta.get("characters") or [])
                                  if name != elem["name"]]
            if meta.get("scene_element") == elem["name"]:
                meta["scene_element"] = "无"
        await pool.execute(
            "DELETE FROM element_appearances WHERE element_id=$1 AND node_id=$2", eid,
            rel["subject_id"])
    else:
        meta["extra_refs"] = [r for r in (meta.get("extra_refs") or [])
                              if not ((snap.get("url") and r.get("url") == snap.get("url"))
                                      or (snap.get("name") and r.get("name") == snap.get("name")))]
    await pool.execute("UPDATE content_nodes SET meta=$1::jsonb,updated_at=now() WHERE id=$2",
                       json.dumps(meta, ensure_ascii=False), rel["subject_id"])
    if rel["source_kind"] == "element":
        from .storyboard import assemble_shot_prompts
        await assemble_shot_prompts(pool, project_id, int(rel["subject_id"]))
    for target_purpose in ("image", "video", "last"):
        await sync_shot_from_legacy(pool, project_id, int(rel["subject_id"]), target_purpose)
    return True
