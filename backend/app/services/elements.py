"""要素 upsert 的唯一实现。

历史上「按 (project_id, kind, name) 找/建要素」有三处近似代码：
api/projects.add_element、pipeline.py、shot_elements.py——各自预填略有出入，
是典型漂移源。本模块收敛为一份：端点与工作流 action 都调这里，禁止再复制。
（pipeline / shot_elements 两处语义有差异，登记为后续收敛项，先不动。）
"""
from __future__ import annotations

import json
from typing import Any

import asyncpg


def _j(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else json.loads(v or "{}")


def prefill(kind: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """按类型预填 state/meta（从 api/projects.add_element 搬移，非复制——端点已改调这里）。"""
    meta: dict[str, Any] = {"needs_image": kind in ("character", "scene"),
                            "needs_voice": kind == "character"}
    if kind == "character":
        state: dict[str, Any] = {"处境": "", "目标": "", "关系": ""}
        meta["外貌提示词"] = ""
    elif kind in ("plotline", "conflict"):
        state = {"进度": "未开始"}
    else:
        state = {}
    return state, meta


async def upsert_element(pool: asyncpg.Pool, *, project_id: int, kind: str, name: str,
                         brief: str = "", ref_url: str | None = None,
                         overwrite_brief: bool = False) -> dict[str, Any]:
    """按 (project_id, kind, name) 找或建要素（撞 UNIQUE 即取已有）。

    - brief：默认**非空才覆盖**（画布跑一遍不该把库里已有简介清掉）；
      overwrite_brief=True 恢复端点老语义（用户手填什么就是什么）。
    - ref_url：合并进 meta.extra_refs（画布上传/连线的参考图挂到要素上，
      供 element_sheet 现有参考图筛选复用，不另写一份筛选）。
    返回 {id, kind, name, brief, created, sheet_url}。
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("要素名必填")
    kind = (kind or "setting").strip() or "setting"
    state, meta = prefill(kind)
    brief_sql = ("EXCLUDED.brief" if overwrite_brief
                 else "CASE WHEN EXCLUDED.brief <> '' THEN EXCLUDED.brief "
                      "ELSE content_elements.brief END")
    r = await pool.fetchrow(
        f"""INSERT INTO content_elements (project_id, kind, name, brief, state, meta)
            VALUES ($1,$2,$3,$4,$5,$6)
            ON CONFLICT (project_id, kind, name) DO UPDATE
              SET brief={brief_sql}, updated_at=now()
            RETURNING id, kind, name, brief, state, meta, (xmax = 0) AS created""",
        project_id, kind, name, (brief or "").strip(),
        json.dumps(state, ensure_ascii=False), json.dumps(meta, ensure_ascii=False))
    d = dict(r)
    emeta = _j(d["meta"])
    if ref_url and all(x.get("url") != ref_url for x in (emeta.get("extra_refs") or [])):
        refs = [*(emeta.get("extra_refs") or []), {"name": "画布参考", "kind": "ref", "url": ref_url}]
        emeta = await pool.fetchval(
            "UPDATE content_elements SET meta = meta || $2::jsonb, updated_at=now() "
            "WHERE id=$1 RETURNING meta",
            d["id"], json.dumps({"extra_refs": refs}, ensure_ascii=False))
        emeta = _j(emeta)
    return {"id": d["id"], "kind": d["kind"], "name": d["name"], "brief": d["brief"],
            "created": bool(d["created"]), "sheet_url": emeta.get("sheet_url"),
            "state": _j(d["state"]), "meta": emeta}


async def find_element(pool: asyncpg.Pool, *, project_id: int, kind: str,
                       name: str) -> dict[str, Any]:
    """只读查找（upsert 的 preview 替身）：预检时探「这个要素在不在、有没有图、
    提示词是什么」，零副作用。"""
    r = await pool.fetchrow(
        "SELECT id, kind, name, brief, meta FROM content_elements "
        "WHERE project_id=$1 AND kind=$2 AND name=$3",
        project_id, (kind or "setting").strip() or "setting", (name or "").strip())
    if not r:
        return {"exists": False, "id": None, "sheet_url": None}
    meta = _j(r["meta"])
    return {"exists": True, "id": r["id"], "kind": r["kind"], "name": r["name"],
            "brief": r["brief"], "sheet_url": meta.get("sheet_url"),
            "sheet_prompt": meta.get("sheet_prompt"),
            "sheet_prompt_user": meta.get("sheet_prompt_user"),
            "sheet_prompt_anchor": meta.get("sheet_prompt_anchor"),
            "extra_refs": meta.get("extra_refs") or []}
