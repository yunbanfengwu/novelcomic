"""工作流可调用的「命名动作」注册表。

为什么需要它：现有系统的**装配逻辑不在 Step 里，而在 API 端点里**。
以 gen_element_sheet 为例——Step 只负责拿 payload 调模型出图，而提示词装配、
参考图筛选、「沿用上一张」的判断，全在 api/projects.py 那 40 行端点里。
所以工作流的 task 节点直接入队是喂不出正确 payload 的。

action 节点就是这个缺口的通用补法：注册表里放**纯函数式的薄封装**，复用与端点
完全相同的代码路径（不复制逻辑），工作流按名字调用。这样既不用动 steps.py，
也不会让工作流和 HTTP 端点的行为漂移。

等某个 Step 的装配逻辑将来下沉进 before() 了，对应的 action 就可以删掉，
工作流图里换成普通 task 节点即可——图是数据，改图不用发版。
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

import asyncpg

import json

Action = Callable[..., Awaitable[dict[str, Any]]]
_REGISTRY: dict[str, Action] = {}
_META: dict[str, dict[str, Any]] = {}


def _canvas_context_value(value: Any, *, refs: list[dict[str, Any]], texts: list[str],
                         seen: set[str] | None = None, depth: int = 0) -> None:
    """Collect safe, typed material from an upstream canvas result.

    Canvas preparation is deliberately a small, deterministic action.  It does
    not expose the hidden system prompt to the user; it only turns upstream
    outputs into the explicit ``prompt``/``reference_images`` contract consumed
    by the next generation node.  Keeping this collector here makes the same
    preparation node usable by image, video, scene, poster and storyboard
    canvases.
    """
    if depth > 5 or value is None:
        return
    if seen is None:
        seen = set()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return
        if text.startswith(("http://", "https://", "data:", "blob:")):
            if text not in seen:
                seen.add(text)
                refs.append({"name": "上游参考素材", "kind": "canvas", "url": text})
        elif len(text) <= 12000 and text not in texts:
            texts.append(text)
        return
    if isinstance(value, list):
        for item in value[:32]:
            _canvas_context_value(item, refs=refs, texts=texts, seen=seen, depth=depth + 1)
        return
    if not isinstance(value, dict):
        return
    # Preserve explicit reference metadata where a previous node supplied it.
    for key in ("reference_images", "refs", "references", "items"):
        raw = value.get(key)
        if isinstance(raw, list):
            for item in raw[:16]:
                if isinstance(item, dict):
                    url = (item.get("url") or item.get("image_url") or item.get("sheet_url")
                           or item.get("video_url") or item.get("first_frame_url")
                           or item.get("last_frame_url"))
                    if isinstance(url, str) and url.strip() and url not in seen:
                        seen.add(url)
                        refs.append({"name": str(item.get("name") or "上游参考素材"),
                                     "kind": str(item.get("kind") or "canvas"),
                                     "url": url})
                else:
                    _canvas_context_value(item, refs=refs, texts=texts, seen=seen, depth=depth + 1)
    for key in ("text", "prompt", "summary", "instruction", "content", "description"):
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip() and raw.strip() not in texts:
            texts.append(raw.strip()[:12000])
    for key, raw in value.items():
        if key in {"reference_images", "refs", "references", "items", "text", "prompt",
                   "summary", "instruction", "content", "description", "phase"}:
            continue
        if key in {"first_frame_url", "last_frame_url"} and isinstance(raw, str) and raw.strip():
            url = raw.strip()
            if url not in seen:
                seen.add(url)
                refs.append({"name": "upstream frame", "kind":
                             "first_frame" if key == "first_frame_url" else "last_frame",
                             "url": url})
            continue
        if key in {"url", "image_url", "sheet_url", "video_url", "ref_url",
                   "reference_url", "value"}:
            _canvas_context_value(raw, refs=refs, texts=texts, seen=seen, depth=depth + 1)


async def canvas_prepare_context(pool: asyncpg.Pool, *, project_id: int | None = None,
                                purpose: str = "", prompt: str = "",
                                _ctx: dict[str, Any] | None = None,
                                **_: Any) -> dict[str, Any]:
    """Prepare one common upstream contract for every Tapflow canvas.

    The action reads only explicit inbound node results and start inputs.  The
    generation step remains responsible for its business-specific before/next
    hooks (scene blocking, shot continuity, OSS persistence, and so on).  This
    makes the preparation node observable and reusable without duplicating those
    production pipelines.
    """
    ctx = _ctx or {}
    refs: list[dict[str, Any]] = []
    texts: list[str] = []
    seen: set[str] = set()
    for src in ctx.get("__in__") or []:
        _canvas_context_value(ctx.get(src), refs=refs, texts=texts, seen=seen)
    _canvas_context_value(ctx.get("__inputs__") or {}, refs=refs, texts=texts, seen=seen)
    explicit = str(prompt or "").strip()
    prepared_prompt = explicit or (texts[0] if texts else "")
    # Media-specific frame channels are explicit so an I2V node never has to
    # guess which upstream URL should become its first/last frame.
    first = next((r["url"] for r in refs if r.get("kind") in {"first_frame", "keyframe"}), None)
    last = next((r["url"] for r in refs if r.get("kind") in {"last_frame", "tail_frame"}), None)
    if not first and refs and str(purpose).lower() in {"video", "shot_video"}:
        first = refs[0]["url"]
    summary = f"{purpose or 'canvas'}：已读取 {len(refs)} 个上游参考素材"
    if texts:
        summary += f"，整理 {len(texts)} 段文本上下文"
    return {
        "prompt": prepared_prompt,
        "text": summary,
        "summary": summary,
        "reference_images": refs[:8],
        **({"first_frame_url": first} if first else {}),
        **({"last_frame_url": last} if last else {}),
        "ready": bool(prepared_prompt or refs or texts),
        "project_id": project_id,
        "purpose": purpose,
    }


def register(name: str, *, title: str = "", description: str = "",
             params: dict[str, Any] | None = None,
             outputs: dict[str, Any] | None = None,
             writes: bool = False,
             wants_ctx: bool = False) -> Callable[[Action], Action]:
    """注册一个命名动作。

    title/params/outputs/writes 是给**工具菜单**用的（见 services/tools.py）——同一个注册表既是
    工作流的 action 节点来源，也是技能可调用的工具清单，不另起第二套注册表。
    params/outputs 用极简形式 {"字段名": {"type": "int", "required": true,
    "desc": "…"}}。数组输出可额外声明 items.properties，供 Tapflow 循环体直接选择
    当前项字段；这仍不是第二套 schema，只是工具注册合同本身。

    `wants_ctx=True`：该动作额外收一个 `_ctx=<运行期 ctx 整体>`。绝大多数动作**不该**要它——
    动作的入参应当由图上的 `{{节点.字段}}` 显式声明，谁依赖谁一眼可见。只有「规划类」动作
    例外：它要干的事就是自己判断该看上游的哪一部分，入参无法预先写死（见 agent_plan）。
    `_ctx` 是内存态、不进 `tool_calls` 审计参数，也不出现在 params 里（模型不可传）。
    """
    def deco(fn: Action) -> Action:
        _REGISTRY[name] = fn
        _META[name] = {
            "name": name,
            "title": title or name,
            "description": description or (fn.__doc__ or "").strip(),
            "params": params or {},
            "outputs": outputs or {},
            "writes": writes,
            "wants_ctx": wants_ctx,
        }
        return fn
    return deco


register("canvas.prepare_context", title="画布生成前准备", wants_ctx=True, params={
    "project_id": {"type": "int", "required": False, "desc": "项目 id"},
    "purpose": {"type": "string", "required": False, "desc": "scene/position/poster/storyboard/video 等用途"},
    "prompt": {"type": "string", "required": False, "desc": "用户显式需求"},
}, outputs={
    "prompt": {"type": "string", "desc": "交给下游生成节点的可见需求层"},
    "text": {"type": "string", "desc": "准备摘要"},
    "reference_images": {"type": "array", "desc": "上游图片/视频参考"},
    "first_frame_url": {"type": "string"},
    "last_frame_url": {"type": "string"},
    "ready": {"type": "bool"},
})(canvas_prepare_context)


@register("canvas.collect_refs", title="收集对象参考素材", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id（校验归属）"},
    "shot_id": {"type": "int", "required": False, "desc": "分镜 id（查分镜关联要素与已有产物）"},
    "element_ids": {"type": "list", "required": False, "desc": "显式要素 id 列表（不给时从对象 meta 推导）"},
}, outputs={
    "refs": {"type": "array", "desc": "参考素材 [{name,kind,url}]，prepare_context 直接识别"},
    "keyframe_url": {"type": "string", "desc": "已有的首帧（若有）"},
    "storyboard_url": {"type": "string", "desc": "已有的分镜图（若有）"},
    "text": {"type": "string", "desc": "素材摘要（进生成上下文）"},
})
async def canvas_collect_refs(pool, *, project_id: int, shot_id: int | None = None,
                              element_ids: list[Any] | None = None, **_) -> dict[str, Any]:
    """按业务对象收集**已有**参考素材（只读，幂等）。

    修的是「参考素材不回显」的编排缺口：shot-video-canvas 的 prepare_context
    原本只连 start（拿到 project_id/shot_id 两个数），无素材源可读——分镜
    明明装填过要素设定图/章节分镜图/首帧，画布上永远“已读取 0 个上游参考素材”。
    本动作按数据现状收集，零写死：
    - shot.meta.element_ids → content_elements 的 name/sheet_url（要素设定图）
    - shot.meta.reference_images / reference_urls（用户手动上传的参考）
    - shot.meta.keyframe_url / storyboard_image_url / storyboard_cell_url
    返回的 refs 形如 prepare_context 识别的 {name,kind,url} 列表，接在
    prepare_context 上游即可被自动聚合进生成上下文与画布回显。
    """
    if shot_id is None and not element_ids:
        return {"refs": [], "text": "", "summary": "无对象可查"}
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    meta: dict[str, Any] = {}
    if shot_id is not None:
        row = await pool.fetchrow(
            "SELECT meta FROM content_nodes WHERE id=$1 AND project_id=$2 AND kind='shot'",
            shot_id, project_id)
        if row is None:
            raise ValueError(f"分镜不存在或项目不匹配: shot_id={shot_id} project_id={project_id}")
        meta = row["meta"] if isinstance(row["meta"], dict) else json.loads(row["meta"] or "{}")
    # 1) 要素设定图：meta.element_ids 优先，其次显式参数
    ids = meta.get("element_ids") or element_ids or []
    if isinstance(ids, (int, str)):
        ids = [ids]
    el_ids = [int(e) for e in ids if isinstance(e, (int, str)) and str(e).strip().isdigit()]
    if el_ids:
        rows = await pool.fetch(
            "SELECT id, name, meta FROM content_elements "
            "WHERE id = ANY($1::int[]) AND project_id=$2 ORDER BY id", el_ids, project_id)
        for r in rows:
            em = r["meta"] if isinstance(r["meta"], dict) else json.loads(r["meta"] or "{}")
            url = (em.get("sheet_url") or em.get("image_url") or em.get("url")) if isinstance(em, dict) else None
            if isinstance(url, str) and url.strip() and url not in seen:
                seen.add(url)
                refs.append({"name": r["name"], "kind": "element", "url": url})
    # 2) 用户手动上传的参考图（兼容 reference_images 列表与 reference_urls 字符串列表）
    for item in meta.get("reference_images") or []:
        if isinstance(item, dict):
            url = item.get("url") or item.get("image_url")
            name = item.get("name") or "参考图"
        else:
            url, name = item, "参考图"
        if isinstance(url, str) and url.strip() and url not in seen:
            seen.add(url)
            refs.append({"name": name, "kind": "reference", "url": url})
    for url in meta.get("reference_urls") or []:
        if isinstance(url, str) and url.strip() and url not in seen:
            seen.add(url)
            refs.append({"name": "参考图", "kind": "reference", "url": url})
    # 3) 已有产物：首帧/分镜图（有就带着，供下游 skip 或做参考）
    keyframe = meta.get("keyframe_url")
    if isinstance(keyframe, str) and keyframe.strip() and keyframe not in seen:
        seen.add(keyframe)
        refs.append({"name": "已有首帧", "kind": "keyframe", "url": keyframe})
    storyboard = None
    for cand in (meta.get("storyboard_image_url"), meta.get("storyboard_cell_url"),
                 (meta.get("storyboard_ref") or {}).get("url")
                 if isinstance(meta.get("storyboard_ref"), dict) else None):
        if isinstance(cand, str) and cand.strip():
            storyboard = cand
            break
    if isinstance(storyboard, str) and storyboard.strip() and storyboard not in seen:
        seen.add(storyboard)
        refs.append({"name": "分镜图", "kind": "storyboard", "url": storyboard})
    names = "、".join(str(r["name"]) for r in refs[:8]) if refs else ""
    summary = (f"已收集 {len(refs)} 个参考素材：{names}" if refs
               else "未找到该分镜已装填的参考素材")
    return {"refs": refs, "keyframe_url": keyframe if isinstance(keyframe, str) else None,
            "text": summary, "summary": summary}


async def project_visual_prepare(pool: asyncpg.Pool, *, project_id: int,
                                 role: str = "project_cover_poster",
                                 prompt: str = "", **_: Any) -> dict[str, Any]:
    """Read a project's visual anchors before a poster/anchor is generated."""
    from .project_visual_assets import ROLES, _automatic_references

    if role not in ROLES:
        raise ValueError("unknown project visual asset role")
    async with pool.acquire() as conn:
        urls = await _automatic_references(conn, project_id, role)
    refs = [{"name": "project visual anchor", "kind": "project_anchor", "url": url}
            for url in urls if isinstance(url, str) and url.strip()]
    return {
        "prompt": str(prompt or "").strip(),
        "text": f"read {len(refs)} project visual anchors",
        "summary": f"read {len(refs)} project visual anchors",
        "reference_images": refs,
        "ready": bool(refs or str(prompt or "").strip()),
        "role": role,
        "project_id": project_id,
    }


register("project_visual.prepare", title="Read project visual references", params={
    "project_id": {"type": "int", "required": True, "desc": "project id"},
    "role": {"type": "string", "required": False, "desc": "visual asset role"},
    "prompt": {"type": "string", "required": False, "desc": "user request"},
}, outputs={
    "prompt": {"type": "string"},
    "text": {"type": "string"},
    "reference_images": {"type": "array"},
    "ready": {"type": "bool"},
})(project_visual_prepare)


async def project_visual_generate(pool: asyncpg.Pool, *, project_id: int,
                                  role: str = "project_cover_poster",
                                  prompt: str = "",
                                  reference_urls: Any = None,
                                  **_: Any) -> dict[str, Any]:
    """Generate and persist a project visual asset through its OSS-aware service."""
    from .project_visual_assets import generate

    urls: list[str] | None = None
    if isinstance(reference_urls, list):
        urls = []
        for item in reference_urls:
            if isinstance(item, str) and item.strip():
                urls.append(item.strip())
            elif isinstance(item, dict):
                url = item.get("url") or item.get("image_url") or item.get("sheet_url")
                if isinstance(url, str) and url.strip():
                    urls.append(url.strip())
    result = await generate(pool, project_id, role, str(prompt or "").strip() or None, urls)
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    return {
        **result,
        "url": result.get("url"),
        "image_url": result.get("url"),
        "reference_images": meta.get("reference_urls", urls or []),
        "role": role,
        "project_id": project_id,
    }


register("project_visual.generate", title="Generate project visual asset", params={
    "project_id": {"type": "int", "required": True, "desc": "project id"},
    "role": {"type": "string", "required": False, "desc": "visual asset role"},
    "prompt": {"type": "string", "required": False, "desc": "user request"},
    "reference_urls": {"type": "array", "required": False, "desc": "reference urls"},
}, outputs={
    "url": {"type": "string"},
    "image_url": {"type": "string"},
    "prompt": {"type": "string"},
    "reference_images": {"type": "array"},
}, writes=True)(project_visual_generate)


_EXTRA_LOADED = False


def _ensure_loaded() -> None:
    """把拆到独立模块里的动作也注册进来。

    本文件自带的动作在模块 import 时就注册了，独立模块（能力目录、规划节点）没人
    import 就不会出现在清单里，表现为「画布上选不到 / 说未注册」。放在读取入口做
    惰性触发，而不是本文件顶部 import：那些模块反过来要用本注册表，会成环。
    """
    global _EXTRA_LOADED
    if _EXTRA_LOADED:
        return
    _EXTRA_LOADED = True   # 先置位：被注册的模块万一回头调 get()，不会递归
    from . import agent_plan, capabilities  # noqa: F401 — import 即注册


def get(name: str) -> Action | None:
    _ensure_loaded()
    return _REGISTRY.get(name)


def names() -> list[str]:
    _ensure_loaded()
    return sorted(_REGISTRY)


def spec(name: str) -> dict[str, Any] | None:
    _ensure_loaded()
    return _META.get(name)


def specs() -> list[dict[str, Any]]:
    _ensure_loaded()
    return [_META[n] for n in sorted(_META)]


@register("asset.route_related_elements", title="智能路由关联要素", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "element_ids": {"type": "array", "required": True, "desc": "上游关联要素 id 集合"},
}, outputs={
    "descriptors": {
        "type": "array", "desc": "按资产类型路由后的全部要素描述符",
        "items": {"type": "object", "properties": {
            "asset_type": {"type": "string", "desc": "目标资产类型"},
            "operation": {"type": "string", "desc": "资产操作"},
            "target_ref": {"type": "string", "desc": "业务目标引用"},
            "element_id": {"type": "int", "desc": "要素 id"},
            "element_kind": {"type": "string", "desc": "要素类型"},
            "name": {"type": "string", "desc": "要素名称"},
            "prompt": {"type": "string", "desc": "默认生成指令"},
            "url": {"type": "string", "desc": "已有资产地址（如有）"},
        }},
    },
    "scene_items": {"type": "array", "desc": "场景设定图描述符"},
    "common_image_items": {"type": "array", "desc": "通用图片描述符"},
})
async def asset_route_related_elements(pool: asyncpg.Pool, *, project_id: int,
                                       element_ids: list[int] | None = None,
                                       kinds: list[str] | None = None,
                                       **_: Any) -> dict[str, Any]:
    """Return typed AssetDescriptor-like records for the multi-element canvas.

    Scene elements route to the existing dedicated scene-sheet canvas. All other
    element kinds route to a common image until their dedicated contracts exist.
    The routing decision uses stable IDs and asset types, never element names.
    """
    ids = list(dict.fromkeys(int(value) for value in (element_ids or []) if int(value) > 0))
    if not ids:
        return {"descriptors": [], "scene_items": [], "common_image_items": []}
    rows = await pool.fetch(
        "SELECT id,kind,name FROM content_elements WHERE project_id=$1 AND id=ANY($2::bigint[]) "
        "AND ($3::text[] IS NULL OR kind=ANY($3::text[])) ORDER BY id",
        project_id, ids, kinds or None)
    if not kinds and len(rows) != len(ids):
        raise ValueError("Some related element IDs do not belong to this project")
    from ..assets import read_latest

    descriptors: list[dict[str, Any]] = []
    for row in rows:
        is_scene = row["kind"] == "scene"
        asset_type = "pro.scene.sheet" if is_scene else "com.image"
        target_ref = f"element:{row['id']}"
        existing = await read_latest(pool, project_id=project_id,
                                     asset_type=asset_type, target_ref=target_ref)
        descriptors.append({
            "asset_type": asset_type,
            "operation": "generate",
            "target_ref": target_ref,
            "element_id": row["id"], "element_kind": row["kind"], "name": row["name"],
            "prompt": f"为项目要素「{row['name']}」生成一张可复用的概念素材图，突出其核心外观与辨识特征，不要文字或水印。",
            **({"url": existing["url"], "existing_asset": existing} if existing else {}),
        })
    return {
        "descriptors": descriptors,
        "scene_items": [item for item in descriptors if item["asset_type"] == "pro.scene.sheet"],
        "common_image_items": [item for item in descriptors if item["asset_type"] == "com.image"],
    }


@register("asset.resolve_generation_source", title="解析智能生成数据源", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "source_type": {"type": "string", "required": False,
                    "desc": "explicit.element_ids | shot.dynamic_elements | chapter.appearing_elements | project.elements"},
    "source_ref": {"type": "string", "required": False,
                   "desc": "例如 content_node:819、content_node:769、project:25"},
    "material_kind": {"type": "string", "required": False,
                      "desc": "可选单一素材类型，例如 scene；用于限制候选要素"},
    "filters": {"type": "object", "required": False,
                "desc": "可选 {kinds:[character,scene,item,...]}"},
    # Temporary compatibility for callers saved before the source contract.
    "related_element_ids": {"type": "array", "required": False,
                            "desc": "兼容旧调用；等价 explicit.element_ids"},
    "shot_id": {"type": "int", "required": False,
                "desc": "兼容旧调用；等价 source_ref=content_node:<id>"},
    "chapter_id": {"type": "int", "required": False,
                   "desc": "未指定 source_type 时，作为本集范围"},
}, outputs={
    "descriptors": {
        "type": "array", "desc": "可直接作为循环数据源的资产描述符",
        "items": {"type": "object", "properties": {
            "asset_type": {"type": "string", "desc": "目标资产类型"},
            "operation": {"type": "string", "desc": "资产操作"},
            "target_ref": {"type": "string", "desc": "业务目标引用"},
            "element_id": {"type": "int", "desc": "要素 id"},
            "element_kind": {"type": "string", "desc": "要素类型"},
            "name": {"type": "string", "desc": "要素名称"},
            "prompt": {"type": "string", "desc": "默认生成指令"},
            "url": {"type": "string", "desc": "已有资产地址（如有）"},
        }},
    },
    "scene_items": {"type": "array", "desc": "场景设定图描述符"},
    "common_image_items": {"type": "array", "desc": "通用图片描述符"},
    "source_type": {"type": "string", "desc": "实际使用的来源类型"},
    "source_ref": {"type": "string", "desc": "实际使用的来源对象"},
    "filters": {"type": "object", "desc": "已应用的筛选条件"},
    "source_items": {"type": "array", "desc": "来源对象中的原始要素"},
})
async def asset_resolve_generation_source(
    pool: asyncpg.Pool, *, project_id: int, source_type: str | None = None,
    source_ref: str | None = None, filters: dict[str, Any] | None = None,
    material_kind: str | None = None,
    source: str | None = None,
    related_element_ids: list[int] | None = None, shot_id: int | None = None,
    chapter_id: int | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Resolve an explicit business scope into typed asset descriptors.

    A source type is part of the canvas contract.  The tool never infers
    chapter/project scope from a shot's legacy ``meta.element_ids`` field.
    """
    legacy_map = {"related_elements": "explicit.element_ids",
                  "shot_dynamic_elements": "shot.dynamic_elements"}
    source_type = source_type or legacy_map.get(source or "") or (
        "shot.dynamic_elements" if shot_id else
        "chapter.appearing_elements" if chapter_id else
        "explicit.element_ids" if related_element_ids else "project.elements")
    if not source_ref and shot_id:
        source_ref = f"content_node:{int(shot_id)}"
    if not source_ref and chapter_id:
        source_ref = f"content_node:{int(chapter_id)}"
    if not source_ref and source_type == "project.elements":
        source_ref = f"project:{int(project_id)}"
    selected_kind = str(material_kind or "").strip() or None
    allowed_kinds = ([selected_kind] if selected_kind else
                     [str(x) for x in ((filters or {}).get("kinds") or []) if str(x)] or None)

    def ref_id(expected_kind: str) -> int:
        try:
            kind, raw_id = str(source_ref or "").split(":", 1)
            ident = int(raw_id)
        except (TypeError, ValueError):
            raise ValueError(f"{source_type} requires source_ref={expected_kind}:<id>") from None
        if kind != expected_kind or ident <= 0:
            raise ValueError(f"{source_type} requires source_ref={expected_kind}:<id>")
        return ident

    if source_type == "explicit.element_ids":
        source_items = [{"id": int(value), "source": "explicit"}
                        for value in (related_element_ids or []) if int(value) > 0]
    elif source_type == "shot.dynamic_elements":
        sid = ref_id("content_node")
        owner = await pool.fetchval(
            "SELECT project_id FROM content_nodes WHERE id=$1 AND kind='shot' AND deleted_at IS NULL", sid)
        if owner is None or int(owner) != int(project_id):
            raise ValueError("shot source_ref does not belong to this project")
        rows = await pool.fetch(
            "SELECT DISTINCT e.id,e.kind,e.name FROM element_appearances a "
            "JOIN content_elements e ON e.id=a.element_id WHERE a.node_id=$1 AND e.project_id=$2 ORDER BY e.id",
            sid, project_id)
        source_items = [{**dict(row), "source": "shot.appearance"} for row in rows]
    elif source_type == "chapter.appearing_elements":
        chapter_id = ref_id("content_node")
        rows = await pool.fetch(
            "SELECT DISTINCT e.id,e.kind,e.name FROM content_nodes n "
            "JOIN element_appearances a ON a.node_id=n.id JOIN content_elements e ON e.id=a.element_id "
            "WHERE ((n.id=$1 AND n.project_id=$2 AND n.kind='chapter' AND n.deleted_at IS NULL) "
            "OR (n.parent_id=$1 AND n.project_id=$2 AND n.kind='shot' AND n.deleted_at IS NULL)) ORDER BY e.id",
            chapter_id, project_id)
        source_items = [{**dict(row), "source": "chapter.appearance"} for row in rows]
    elif source_type == "project.elements":
        pid = ref_id("project")
        if pid != int(project_id):
            raise ValueError("project source_ref must match project_id")
        rows = await pool.fetch("SELECT id,kind,name FROM content_elements WHERE project_id=$1 ORDER BY id", project_id)
        source_items = [{**dict(row), "source": "project"} for row in rows]
    else:
        raise ValueError(f"Unsupported generation source_type: {source_type}")

    element_ids = list(dict.fromkeys(int(item["id"]) for item in source_items))
    routed = await asset_route_related_elements(pool, project_id=project_id,
                                                element_ids=element_ids, kinds=allowed_kinds)
    return {**routed, "source_type": source_type, "source_ref": source_ref,
            "filters": {"kinds": allowed_kinds or []}, "source_items": source_items}


@register("asset.resolve_source", title="解析素材来源", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "source": {"type": "object", "required": True,
               "desc": "标准来源对象：kind=prompt_matches 或 related_elements"},
}, outputs={
    "descriptors": {"type": "array", "desc": "按资产类型路由的素材描述符"},
    "element_ids": {"type": "array", "desc": "稳定要素 ID"},
    "source_type": {"type": "string", "desc": "实际解析的来源类型"},
    "source_ref": {"type": "string", "desc": "实际解析的来源对象"},
})
async def asset_resolve_source(pool: asyncpg.Pool, *, project_id: int,
                               source: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    """Resolve one declarative source contract into typed asset descriptors."""
    source = source or {}
    kind = str(source.get("kind") or "related_elements")
    common = {
        "candidate_source_type": source.get("source_type"),
        "candidate_source_ref": source.get("source_ref"),
        "candidate_element_ids": source.get("related_element_ids"),
        "material_kind": source.get("material_kind"),
        "filters": source.get("filters"),
        "shot_id": source.get("shot_id"),
    }
    if kind == "prompt_matches":
        return await asset_resolve_prompt_elements(
            pool, project_id=project_id, prompt_text=str(source.get("prompt_text") or ""), **common)
    if kind == "related_elements":
        return await asset_resolve_generation_source(
            pool, project_id=project_id,
            source_type=source.get("source_type"), source_ref=source.get("source_ref"),
            related_element_ids=source.get("related_element_ids"),
            material_kind=source.get("material_kind"), filters=source.get("filters"),
            shot_id=source.get("shot_id"))
    raise ValueError(f"Unsupported source kind: {kind}")


@register("asset.resolve_prompt_elements", title="从定格提示词提取关联要素", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "prompt_text": {"type": "string", "required": False,
                    "desc": "上游生成的关键帧定格画面提示词；为空时透传候选范围"},
    "candidate_source_type": {"type": "string", "required": False,
                              "default": "shot.dynamic_elements",
                              "desc": "候选范围，默认使用本镜已关联要素"},
    "candidate_source_ref": {"type": "string", "required": False,
                             "desc": "候选范围引用，例如 content_node:819"},
    "candidate_element_ids": {"type": "array", "required": False,
                              "desc": "显式候选要素 id"},
    "material_kind": {"type": "string", "required": False,
                      "desc": "可选单一素材类型，例如 scene；用于限制候选要素"},
    "filters": {"type": "object", "required": False,
                "desc": "候选要素筛选条件"},
    "shot_id": {"type": "int", "required": False,
                "desc": "candidate_source_ref 的兼容分镜 id"},
    "chapter_id": {"type": "int", "required": False,
                   "desc": "未指定候选范围时，作为本集范围"},
}, outputs={
    "prompt_text": {"type": "string", "desc": "已检查的定格画面提示词"},
    "element_ids": {"type": "array", "desc": "提示词实际引用的规范要素 id"},
    "descriptors": {
        "type": "array", "desc": "提示词实际引用的资产描述符",
        "items": {"type": "object", "properties": {
            "asset_type": {"type": "string"}, "target_ref": {"type": "string"},
            "element_id": {"type": "int"}, "element_kind": {"type": "string"},
            "name": {"type": "string"}, "prompt": {"type": "string"},
            "url": {"type": "string"},
        }},
    },
    "matches": {"type": "array", "desc": "规范名称在提示词中的命中记录"},
    "candidate_items": {"type": "array", "desc": "参与匹配的闭集候选"},
    "source_type": {"type": "string", "desc": "实际使用的候选来源类型"},
    "source_ref": {"type": "string", "desc": "实际使用的候选来源对象"},
})
async def asset_resolve_prompt_elements(
    pool: asyncpg.Pool, *, project_id: int, prompt_text: str = "",
    candidate_source_type: str | None = None, candidate_source_ref: str | None = None,
    candidate_element_ids: list[int] | None = None,
    material_kind: str | None = None, filters: dict[str, Any] | None = None,
    shot_id: int | None = None, chapter_id: int | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Extract canonical element references from a generated still-frame prompt.

    Prompt generation is required to use canonical project element names. Matching
    is therefore deterministic and closed-world: this tool can select only an ID
    returned by the supplied candidate scope, and never invents a new element.
    """
    prompt = str(prompt_text or "").strip()
    source_type = candidate_source_type or (
        "shot.dynamic_elements" if shot_id or candidate_source_ref else
        "chapter.appearing_elements" if chapter_id else
        "explicit.element_ids")
    resolved = await asset_resolve_generation_source(
        pool, project_id=project_id, source_type=source_type,
        source_ref=candidate_source_ref, related_element_ids=candidate_element_ids,
        material_kind=material_kind, filters=filters,
        shot_id=shot_id, chapter_id=chapter_id)
    candidates = [item for item in (resolved.get("descriptors") or [])
                  if isinstance(item, dict) and item.get("element_id")]
    normalized_prompt = "".join(prompt.casefold().split())
    matched: list[dict[str, Any]] = []
    descriptors: list[dict[str, Any]] = []
    for item in candidates:
        name = str(item.get("name") or "").strip()
        normalized_name = "".join(name.casefold().split())
        if not normalized_name or (prompt and normalized_name not in normalized_prompt):
            continue
        descriptors.append(item)
        matched.append({
            "element_id": int(item["element_id"]), "name": name,
            "evidence": ("规范名称出现在定格画面提示词中" if prompt
                         else "未提供提示词，使用调用方候选范围"),
        })
    return {
        "prompt_text": prompt,
        "element_ids": [item["element_id"] for item in matched],
        "descriptors": descriptors,
        "matches": matched,
        "candidate_items": [
            {"element_id": int(item["element_id"]),
             "element_kind": item.get("element_kind"), "name": item.get("name")}
            for item in candidates
        ],
        "source_type": source_type, "source_ref": resolved.get("source_ref"),
    }


@register("asset.resolve_frame_elements", title="Identify elements in keyframe", params={
    "project_id": {"type": "int", "required": True, "desc": "Project id"},
    "image_url": {"type": "string", "required": True,
                   "desc": "The generated still image to inspect"},
    "candidate_source_type": {"type": "string", "required": False,
                               "default": "shot.dynamic_elements",
                               "desc": "Candidate scope, for example shot.dynamic_elements"},
    "candidate_source_ref": {"type": "string", "required": False,
                              "desc": "Candidate scope reference, for example content_node:819"},
    "candidate_element_ids": {"type": "array", "required": False,
                               "desc": "Explicit candidate element ids"},
    "filters": {"type": "object", "required": False,
                "desc": "Optional candidate filters, for example {kinds:[character,scene]}"},
    "shot_id": {"type": "int", "required": False,
                "desc": "Compatibility fallback for candidate_source_ref"},
    "min_confidence": {"type": "number", "required": False, "default": 0.55,
                        "desc": "Minimum visual match confidence"},
}, outputs={
    "image_url": {"type": "string", "desc": "Inspected keyframe URL"},
    "element_ids": {"type": "array", "desc": "Element ids visible in this keyframe"},
    "descriptors": {
        "type": "array", "desc": "Typed descriptors for elements visible in this keyframe",
        "items": {"type": "object", "properties": {
            "asset_type": {"type": "string"}, "target_ref": {"type": "string"},
            "element_id": {"type": "int"}, "element_kind": {"type": "string"},
            "name": {"type": "string"}, "prompt": {"type": "string"},
            "url": {"type": "string"},
        }},
    },
    "matches": {"type": "array", "desc": "Visual model matches with confidence and evidence"},
    "candidate_items": {"type": "array", "desc": "Candidate elements considered by the matcher"},
    "source_type": {"type": "string", "desc": "Resolved candidate source type"},
    "source_ref": {"type": "string", "desc": "Resolved candidate source reference"},
})
async def asset_resolve_frame_elements(
    pool: asyncpg.Pool, *, project_id: int, image_url: str,
    candidate_source_type: str | None = None, candidate_source_ref: str | None = None,
    candidate_element_ids: list[int] | None = None,
    filters: dict[str, Any] | None = None, shot_id: int | None = None,
    min_confidence: float = 0.55, **_: Any,
) -> dict[str, Any]:
    """Match a generated still against a bounded set of project elements.

    The model is never allowed to invent an element: it must return ids from
    the candidate descriptors supplied in the prompt.  This keeps the action
    reusable for shot, chapter, project, or explicitly selected candidate
    scopes while preserving the full shot scope for later video workflows.
    """
    if not str(image_url or "").strip():
        raise ValueError("image_url is required")
    source_type = candidate_source_type or (
        "shot.dynamic_elements" if shot_id or candidate_source_ref else "explicit.element_ids")
    resolved = await asset_resolve_generation_source(
        pool, project_id=project_id, source_type=source_type,
        source_ref=candidate_source_ref, filters=filters,
        related_element_ids=candidate_element_ids, shot_id=shot_id)
    candidates = [d for d in (resolved.get("descriptors") or [])
                  if isinstance(d, dict) and d.get("element_id")]
    if not candidates:
        return {
            "image_url": image_url, "element_ids": [], "descriptors": [], "matches": [],
            "candidate_items": [], "source_type": source_type,
            "source_ref": resolved.get("source_ref"),
        }

    # Keep the vision prompt deliberately closed-world.  Names are hints for
    # the model; the numeric id is the only value accepted below.
    candidate_lines = "\n".join(
        f"- id={int(item['element_id'])}; kind={item.get('element_kind') or ''}; "
        f"name={item.get('name') or ''}"
        for item in candidates)
    system = (
        "You inspect a generated still frame for a workflow asset router. "
        "Return JSON only with this shape: "
        '{"matches":[{"element_id":123,"confidence":0.0,"evidence":"..."}]}. '
        "Only select elements visibly present in the image. Never invent ids, "
        "and do not select an element merely because it belongs to the shot. "
        "Use the supplied candidate list as a closed set."
    )
    user = (
        "Candidate elements:\n" + candidate_lines +
        "\n\nInspect the still image and return only visible candidates. "
        "Confidence must be between 0 and 1."
    )
    from .. import llm

    vision = await llm.chat_vision_json(system, user, image_url,
                                        max_tokens=max(1200, min(4000, len(candidates) * 100)))
    raw_matches = vision.get("matches") if isinstance(vision, dict) else vision
    if not isinstance(raw_matches, list):
        raw_matches = []
    by_id = {int(item["element_id"]): item for item in candidates}
    by_name = {str(item.get("name") or "").strip().casefold(): int(item["element_id"])
               for item in candidates if str(item.get("name") or "").strip()}
    threshold = max(0.0, min(1.0, float(min_confidence or 0.0)))
    matches: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in raw_matches:
        if not isinstance(raw, dict):
            continue
        try:
            ident = int(raw.get("element_id"))
        except (TypeError, ValueError):
            ident = by_name.get(str(raw.get("name") or "").strip().casefold(), 0)
        if ident not in by_id or ident in seen:
            continue
        try:
            confidence = float(raw.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < threshold:
            continue
        seen.add(ident)
        matches.append({
            "element_id": ident, "name": by_id[ident].get("name"),
            "confidence": max(0.0, min(1.0, confidence)),
            "evidence": str(raw.get("evidence") or raw.get("reason") or "").strip(),
        })
    descriptors = [by_id[ident] for ident in (m["element_id"] for m in matches)]
    return {
        "image_url": image_url,
        "element_ids": [m["element_id"] for m in matches],
        "descriptors": descriptors,
        "matches": matches,
        "candidate_items": [
            {"element_id": int(item["element_id"]), "element_kind": item.get("element_kind"),
             "name": item.get("name")} for item in candidates
        ],
        "source_type": source_type, "source_ref": resolved.get("source_ref"),
    }


# ═══════════ 要素设定图（角色 / 场景）═══════════

@register("element_sheet.prepare", title="装配要素设定图 payload", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "element_id": {"type": "int", "required": True, "desc": "要素 id（角色/场景）"},
    "variant_id": {"type": "string", "required": False, "desc": "造型变体 id，留空取主造型"},
})
async def element_sheet_prepare(pool: asyncpg.Pool, *, project_id: int, element_id: int,
                                variant_id: str | None = None, **_: Any) -> dict[str, Any]:
    """装配要素设定图的出图 payload。与 api/projects.py 的 gen_element_sheet 端点同源——
    这里只做参数搬运，提示词装配在 element_sheet.assemble_element_sheet_prompt、
    参考图筛选在 element_sheet.element_refs，两者都是全站唯一实现。"""
    from .element_sheet import assemble_element_sheet_prompt, element_refs

    prompts = await assemble_element_sheet_prompt(pool, project_id, element_id, variant_id)
    refs = await element_refs(pool, project_id, element_id, variant_id)
    return {
        "prompt": prompts["sheet_prompt"], "element_id": element_id,
        "variant_id": variant_id, "reference_images": refs,
        "hair_prompt": prompts.get("hair_sheet_prompt") or "",
    }


@register("element.layers", title="要素设定图·分层提示词", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "element_id": {"type": "int", "required": True, "desc": "要素 id（角色/场景/道具）"},
    "variant_id": {"type": "string", "required": False, "desc": "造型变体 id，留空取主造型"},
})
async def element_layers(pool: asyncpg.Pool, *, project_id: int, element_id: int,
                         variant_id: str | None = None, **_: Any) -> dict[str, Any]:
    """要素设定图提示词的**分层产物**：user（叙事，可再拼上游文本与用户指令）/
    anchor（版式+画风+质量+偏好，锁死不许画布改）/ negative / hair / refs（参考图）。

    画布的通用生成节点靠这个拿层。**零副作用**（不写 meta），所以运行预检也能直接调，
    参数一填画布上就能看到真实提示词。装配本体仍是 element_sheet 那一份。"""
    from .element_sheet import element_prompt_layers, element_refs

    # 提示词分层与参考图筛选读的是同一行要素：取一次传给两边，别各查各的
    row = await pool.fetchrow(
        "SELECT e.meta, p.config AS project_config FROM content_elements e "
        "JOIN content_projects p ON p.id=e.project_id WHERE e.id=$1 AND e.project_id=$2",
        element_id, project_id)
    layers = await element_prompt_layers(pool, project_id, element_id, variant_id)
    refs = await element_refs(pool, project_id, element_id, variant_id, row=row)
    return {**layers, "refs": refs}


@register("qc.review", title="通用质检（判法来自技能）", params={
    "skill": {"type": "string", "required": True, "desc": "质检技能名（kb 里的 reviewer 条目）"},
    "text": {"type": "string", "required": False, "desc": "待检文本（判提示词时给）"},
    "image_url": {"type": "string", "required": False, "desc": "待检图片（判画面时给，走视觉模型）"},
    "project_id": {"type": "int", "required": False, "desc": "项目 id（取项目级覆盖的规则）"},
    "prev_feedback": {"type": "string", "required": False, "desc": "上一轮问题清单，重判时带上"},
})
async def qc_review(pool: asyncpg.Pool, *, skill: str, text: str = "",
                    image_url: str | None = None, project_id: int | None = None,
                    prev_feedback: str = "", locked: str = "",
                    **_: Any) -> dict[str, Any]:
    """画布质检段的执行体：判法来自技能，输出结构由代码强制（合格/得分/问题）。
    本体在 storyboard.review_by_skill，与镜级质检共用同一套规则装配，不另写一份。

    locked = 已随提示词下发、判据改不动的硬约束段（anchor）。只作事实告知——
    不给它，判据会要求 text 段重复 anchor 里已有的要求，判不过又无从改起。"""
    from .storyboard import review_by_skill

    return await review_by_skill(pool, project_id, skill=skill, text=text,
                                 image_url=image_url, prev_feedback=prev_feedback,
                                 locked=locked)


@register("element.set_brief", title="回写要素简介", writes=True, params={
    "element_id": {"type": "int", "required": True, "desc": "要素 id"},
    "brief": {"type": "string", "required": True, "desc": "简介正文"},
})
async def element_set_brief(pool: asyncpg.Pool, *, element_id: int, brief: str,
                            **_: Any) -> dict[str, Any]:
    """把 LLM 写出来的场景/角色介绍回写到要素 brief。

    为什么不走 agent_next 的 writes 白名单：那份白名单只认 meta/state/summary 四个落点，
    brief 是**正文列**不是 jsonb 合并，语义不同（覆盖而非 ||）。做成具名动作而不是
    往白名单塞自由 SQL——写库入口一律具名，是那份白名单本来的用意。"""
    text = (brief or "").strip()
    if not text:
        return {"written": False, "reason": "空内容不覆盖已有简介"}
    await pool.execute(
        "UPDATE content_elements SET brief=$2, updated_at=now() WHERE id=$1", element_id, text)
    return {"written": True, "element_id": element_id, "len": len(text)}


@register("element.upsert", title="要素查找或创建", writes=True, params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "kind": {"type": "string", "required": True, "desc": "character/scene/setting/…"},
    "name": {"type": "string", "required": True, "desc": "要素名（项目内同类唯一）"},
    "element_id": {"type": "int", "required": False, "desc": "existing target element id"},
    "brief": {"type": "string", "required": False, "desc": "简介/说明；非空才覆盖已有"},
    "ref_url": {"type": "string", "required": False, "desc": "参考图 url，合并进 meta.extra_refs"},
})
async def element_upsert(pool: asyncpg.Pool, *, project_id: int, kind: str, name: str,
                         element_id: int | None = None, brief: str = "", ref_url: str | None = None,
                         **_: Any) -> dict[str, Any]:
    """按 (project_id, kind, name) 找或建要素——画布 next/关联节点：把画布上的
    文本说明落成项目要素（资产自动入库的「归属」一步）。本体在 services/elements.py。"""
    if element_id:
        row = await pool.fetchrow(
            "SELECT id,kind,name,brief,state,meta FROM content_elements WHERE id=$1 AND project_id=$2",
            element_id, project_id)
        if not row or row["kind"] != kind:
            raise ValueError("Target element does not exist or has a different kind")
        import json
        meta = row["meta"] if isinstance(row["meta"], dict) else json.loads(row["meta"] or "{}")
        state = row["state"] if isinstance(row["state"], dict) else json.loads(row["state"] or "{}")
        return {"id": row["id"], "kind": row["kind"], "name": row["name"],
                "brief": row["brief"], "created": False, "sheet_url": meta.get("sheet_url"),
                "state": state, "meta": meta}
    from .elements import upsert_element

    return await upsert_element(pool, project_id=project_id, kind=kind, name=name,
                                brief=brief, ref_url=ref_url or None)


@register("element.find", title="要素只读查找", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "kind": {"type": "string", "required": True, "desc": "character/scene/…"},
    "name": {"type": "string", "required": True, "desc": "要素名"},
})
async def element_find(pool: asyncpg.Pool, *, project_id: int, kind: str, name: str,
                       **_: Any) -> dict[str, Any]:
    """element.upsert 的只读替身（工作流 preview 预检用）：探要素在不在、
    有没有设定图、已存提示词——零副作用。"""
    from .elements import find_element

    return await find_element(pool, project_id=project_id, kind=kind, name=name)


# ═══════════ 分镜首帧 Tapflow（与现有 InfiniteMediaCanvas 并行对比）═══════════

@register("shot.keyframe.context", title="分镜首帧·上下文与参考摘要", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "shot_id": {"type": "int", "required": True, "desc": "分镜 id"},
})
async def shot_keyframe_context(pool: asyncpg.Pool, *, project_id: int, shot_id: int,
                                **_: Any) -> dict[str, Any]:
    """面板、旧无限画布、Tapflow 的共同对账读点：引用只从统一关系服务解析。"""
    import json
    from . import references

    row = await pool.fetchrow(
        "SELECT title,summary,meta FROM content_nodes WHERE id=$1 AND project_id=$2 "
        "AND kind='shot' AND deleted_at IS NULL", shot_id, project_id)
    if not row:
        return {"text": "分镜不存在", "summary": "分镜不存在", "reference_images": []}
    meta = row["meta"] if isinstance(row["meta"], dict) else json.loads(row["meta"] or "{}")
    refs = await references.resolved_images(
        pool, project_id=project_id, subject_kind="shot", subject_id=shot_id, purpose="image")
    lines = [f"分镜：{row['title']}", f"画面：{row['summary'] or ''}",
             f"首帧提示词：{meta.get('image_prompt') or '待生成'}",
             "统一参考资产：" + ("、".join(r["name"] for r in refs) or "无")]
    text = "\n".join(lines)
    return {"text": text, "summary": text, "reference_images": refs,
            "shot_id": shot_id, "keyframe_url": meta.get("keyframe_url")}


@register("shot.keyframe.layers", title="分镜首帧·统一装配层", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "shot_id": {"type": "int", "required": True, "desc": "分镜 id"},
    "prompt_text": {"type": "string", "required": False, "desc": "上游关键帧定格提示词"},
    "include_element_refs": {"type": "bool", "required": False, "default": True,
                              "desc": "Whether to include all shot element reference images"},
})
async def shot_keyframe_layers(pool: asyncpg.Pool, *, project_id: int, shot_id: int,
                               prompt_text: str = "", include_element_refs: bool = True,
                               **_: Any) -> dict[str, Any]:
    """给 Tapflow gen 节点提供 user/anchor/refs；refs 与实际旧生产画布同源。"""
    import json
    from . import references

    row = await pool.fetchrow(
        "SELECT summary,meta FROM content_nodes WHERE id=$1 AND project_id=$2 AND kind='shot'",
        shot_id, project_id)
    if not row:
        return {"user": "", "anchor": "", "negative": "", "refs": []}
    meta = row["meta"] if isinstance(row["meta"], dict) else json.loads(row["meta"] or "{}")
    user = meta.get("image_prompt_user")
    anchor = meta.get("image_prompt_anchor")
    if not user and not anchor:
        user, anchor = meta.get("image_prompt") or row["summary"] or "", ""
    refs = await references.resolved_images(
        pool, project_id=project_id, subject_kind="shot", subject_id=shot_id, purpose="image")
    if not include_element_refs:
        refs = [ref for ref in refs if not ref.get("element_id")]
    # prompt_text 已通过可见文本节点直接入 gen；这里仅提供锁定层，避免正文重复拼两遍。
    return {"user": "" if prompt_text else (user or ""), "anchor": anchor or "",
            "negative": "", "refs": refs}


@register("shot.keyframe.script", title="分镜首帧·分镜脚本", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "shot_id": {"type": "int", "required": True, "desc": "分镜 id"},
})
async def shot_keyframe_script(pool: asyncpg.Pool, *, project_id: int, shot_id: int,
                               **_: Any) -> dict[str, Any]:
    """第一文本节点：把镜头时序/动作/运镜投影成可检查的分镜脚本。"""
    import json

    row = await pool.fetchrow(
        "SELECT summary,meta FROM content_nodes WHERE id=$1 AND project_id=$2 AND kind='shot'",
        shot_id, project_id)
    if not row:
        return {"text": "", "source": "missing"}
    meta = row["meta"] if isinstance(row["meta"], dict) else json.loads(row["meta"] or "{}")
    text = str(meta.get("video_prompt_textonly") or "").strip()
    if not text:
        cuts = meta.get("cuts") or []
        text = " → ".join(
            f"（{c.get('seconds') or '?'}秒·{c.get('scale') or '镜头'}·{c.get('camera_move') or '固定'}）"
            f"{c.get('subject') or '主体'}：{c.get('action') or ''}" for c in cuts if isinstance(c, dict))
    return {"text": text or str(row["summary"] or ""), "source": "shot_script",
            "cut_count": len(meta.get("cuts") or [])}


@register("shot.keyframe.skill_manifest", title="分镜首帧·实际技能清单", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
})
async def shot_keyframe_skill_manifest(pool: asyncpg.Pool, *, project_id: int, **_: Any) -> dict[str, Any]:
    """投影真实调用链中的技能来源，不虚构一个新的画布技能。"""
    sop = await pool.fetchrow(
        "SELECT spec FROM visual_sops WHERE asset_role='gen_keyframe' AND status='published' "
        "ORDER BY version DESC LIMIT 1")
    import json
    spec = (sop["spec"] if isinstance(sop["spec"], dict) else json.loads(sop["spec"] or "{}")) if sop else {}
    reviewer = await pool.fetchrow(
        "SELECT id,name,scope,project_id FROM kb_entries WHERE kind='skill' "
        "AND agent_code='reviewer' AND name='首帧提示词质检' "
        "AND (project_id=$1 OR project_id IS NULL) ORDER BY project_id NULLS LAST LIMIT 1", project_id)
    skills = [{"name": spec.get("skill_name") or "分镜提示词装配",
               "source": "visual_sop:shot_keyframe_sop"}]
    if reviewer:
        skills.append({"name": reviewer["name"], "source": "kb_entries",
                       "id": reviewer["id"], "scope": reviewer["scope"]})
    return {"skills": skills, "text": "；".join(x["name"] for x in skills)}


@register("shot.keyframe.knowledge", title="分镜首帧·实际知识召回", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "shot_id": {"type": "int", "required": True, "desc": "分镜 id"},
})
async def shot_keyframe_knowledge(pool: asyncpg.Pool, *, project_id: int, shot_id: int,
                                  **_: Any) -> dict[str, Any]:
    """与 assemble_shot_prompts 同口径展示本镜实际会读取的知识类别和命中项。"""
    import json
    from ..knowledge import get_block, recall_blocks

    row = await pool.fetchrow(
        "SELECT n.parent_id,n.meta,p.art_style FROM content_nodes n JOIN content_projects p "
        "ON p.id=n.project_id WHERE n.id=$1 AND n.project_id=$2 AND n.kind='shot'",
        shot_id, project_id)
    if not row:
        return {"blocks": [], "text": ""}
    meta = row["meta"] if isinstance(row["meta"], dict) else json.loads(row["meta"] or "{}")
    first = (meta.get("cuts") or [{}])[0]
    scale = first.get("scale") or meta.get("scale") or "中景"
    blocks = []
    async def add(category: str, item: Any) -> None:
        if item:
            blocks.append({"category": category, "name": item.get("name") or category,
                           "id": item.get("id")})
    await add("camera", await get_block(pool, "camera", scale))
    lens_by_scale = {"大特写": "100mm微距", "特写": "85mm长焦", "近景": "50mm标准",
                     "中景": "35mm标准", "全景": "35mm标准", "远景": "24mm广角",
                     "大远景": "16mm超广角"}
    if lens_by_scale.get(scale):
        await add("lens", await get_block(pool, "lens", lens_by_scale[scale]))
    await add("quality", await get_block(pool, "quality", "通用质量词"))
    await add("negative", await get_block(pool, "quality", "通用负面词"))
    for category, query in (("style", row["art_style"] or "日漫"),
                            ("lighting", meta.get("lighting")),
                            ("motion", meta.get("motion_hint"))):
        if query and query != "无":
            for item in await recall_blocks(pool, query, [category], project_id, top_k=1):
                await add(category, item)
    return {"blocks": blocks, "text": "；".join(f"{b['category']}:{b['name']}" for b in blocks)}


@register("shot.keyframe.prompt_text", title="分镜首帧·关键帧定格画面提示词", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "shot_id": {"type": "int", "required": True, "desc": "分镜 id"},
    "script": {"type": "string", "required": True, "desc": "上游分镜脚本"},
})
async def shot_keyframe_prompt_text(pool: asyncpg.Pool, *, project_id: int, shot_id: int,
                                    script: str, **_: Any) -> dict[str, Any]:
    """第二文本节点：输出首帧定格提示词；脚本是显式输入，确保文本血缘可追踪。"""
    import json

    row = await pool.fetchrow(
        "SELECT summary,meta FROM content_nodes WHERE id=$1 AND project_id=$2 AND kind='shot'",
        shot_id, project_id)
    if not row:
        return {"text": "", "source": "missing"}
    meta = row["meta"] if isinstance(row["meta"], dict) else json.loads(row["meta"] or "{}")
    text = str(meta.get("image_prompt_user") or meta.get("image_prompt_raw")
               or meta.get("image_prompt") or "").strip()
    if not text:
        first = (meta.get("cuts") or [{}])[0]
        instant = first.get("action") if isinstance(first, dict) else ""
        text = f"{row['summary'] or script}。首帧定格瞬间：{instant or script}"
    return {"text": text, "source": "image_prompt", "script": script}


@register("shot.set_image_prompt", title="回写关键帧提示词", writes=True, params={
    "shot_id": {"type": "int", "required": True, "desc": "分镜 id"},
    "text": {"type": "string", "required": True, "desc": "文本节点生成的最终提示词"},
})
async def shot_set_image_prompt(pool: asyncpg.Pool, *, shot_id: int, text: str,
                                **_: Any) -> dict[str, Any]:
    """LLM 文本节点的唯一落点；质检与 gen_keyframe 随后读取同一份文本。"""
    import json
    value = (text or "").strip()
    if not value:
        raise ValueError("关键帧提示词为空，不回写")
    await pool.execute(
        "UPDATE content_nodes SET meta=meta || $2::jsonb,updated_at=now() "
        "WHERE id=$1 AND kind='shot'",
        shot_id, json.dumps({"image_prompt": value, "image_prompt_user": value,
                             "image_prompt_edited": False,
                             "image_prompt_user_edited": False}, ensure_ascii=False))
    return {"written": True, "length": len(value)}


@register("element.sheet_exists", title="要素设定图是否已生成", params={
    "element_id": {"type": "int", "required": True, "desc": "要素 id"},
})
async def element_sheet_exists(pool: asyncpg.Pool, *, element_id: int, **_: Any) -> dict[str, Any]:
    """要素设定图是否已生成——「缺才跑」的预置检查器（比让用户在画布上写 SQL 友好）。"""
    url = await pool.fetchval(
        "SELECT meta->>'sheet_url' FROM content_elements WHERE id=$1", element_id)
    return {"exists": bool(url), "sheet_url": url}


@register("shot.elements", title="取本镜出场要素", params={
    "project_id": {"type": "int", "required": False, "desc": "项目 id，用于防止跨项目读取"},
    "shot_id": {"type": "int", "required": True, "desc": "分镜节点 id（content_nodes.id）"},
})
async def shot_elements(pool: asyncpg.Pool, *, shot_id: int, project_id: int | None = None,
                        **_: Any) -> dict[str, Any]:
    """输出循环所需的稳定、结构化要素合同，而不只是若干 id。"""
    import json

    shot = await pool.fetchrow(
        "SELECT project_id,meta FROM content_nodes WHERE id=$1 AND kind='shot' "
        "AND deleted_at IS NULL", shot_id)
    if not shot or (project_id is not None and int(shot["project_id"]) != int(project_id)):
        return {"items": [], "count": 0, "missing": [], "required_count": 0}
    meta = shot["meta"] if isinstance(shot["meta"], dict) else json.loads(shot["meta"] or "{}")
    # element_appearances is the canonical relation.  Older/manual shots may
    # only have meta.element_ids, so use it as a read-compatible fallback.
    linked_ids = [int(value) for value in (meta.get("element_ids") or [])
                  if str(value).isdigit() and int(value) > 0]
    required_by_id = {
        int(r["element_id"]): r for r in (meta.get("required_refs") or [])
        if isinstance(r, dict) and str(r.get("element_id") or "").isdigit()
        and (not r.get("targets") or "image" in r.get("targets", []))
    }
    variant_map = meta.get("element_variant_ids") or meta.get("element_variants") or {}
    rows = await pool.fetch(
        "SELECT DISTINCT e.id, e.name, e.kind, e.meta->>'sheet_url' AS sheet_url "
        "FROM content_elements e LEFT JOIN element_appearances a ON a.element_id=e.id "
        "WHERE e.project_id=$2 AND (a.node_id=$1 OR e.id=ANY($3::bigint[])) ORDER BY e.id",
        shot_id, int(shot["project_id"]), linked_ids)
    items = []
    for raw in rows:
        item = dict(raw)
        req = required_by_id.get(int(item["id"]), {})
        targets = req.get("targets") or ["image"]
        item.update({
            "required": bool(req.get("required", True)),
            "role": req.get("role") or item["kind"],
            "targets": targets,
            "variant_id": variant_map.get(str(item["id"])) or variant_map.get(item["name"]),
        })
        items.append(item)
    return {"items": items, "count": len(items),
            "required_count": sum(1 for i in items if i["required"]),
            "missing": [i for i in items if not i["sheet_url"]]}


@register("shot.keyframe.extra_references", title="分镜首帧·额外参考资产", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "shot_id": {"type": "int", "required": True, "desc": "分镜 id"},
})
async def shot_keyframe_extra_references(pool: asyncpg.Pool, *, project_id: int, shot_id: int,
                                         **_: Any) -> dict[str, Any]:
    """只返回非要素引用；要素图由循环分支提供，避免同一资产重复进入模型。"""
    from . import references

    rows = await references.list_resolved(
        pool, project_id=project_id, subject_kind="shot", subject_id=shot_id, purpose="image")
    refs = [{"name": r["name"], "kind": r["kind"], "url": r["url"],
             "reference_id": r["id"], "source": "extra"}
            for r in rows if r["enabled"] and r.get("url") and r["source_kind"] != "element"]
    return {"refs": refs, "count": len(refs)}


# ═══════════ 镜级守卫（gen_keyframe 2.0：守卫链外置给自主编排）═══════════
# 这一组是 steps._shot_gen_before 硬编码守卫的具名工具版：每个守卫一个工具，
# 由 g.shot-* 小编排在前置段直接调（可改配置、可删、可换顺序——编排即真相）。
# 全部幂等/带缓存：重复调用命中指纹即零成本。失败只记录不炸链（与 _before 语义一致），
# 安全底线（连续性硬门、角色硬闸）仍留在 gen_keyframe_v2 的 Step 本体里。

@register("shot.ensure_elements", title="取本镜出场要素", writes=True, params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "shot_id": {"type": "int", "required": True, "desc": "分镜节点 id"},
    "force": {"type": "bool", "required": False, "desc": "无视指纹缓存强制重判"},
})
async def shot_ensure_elements(pool: asyncpg.Pool, *, project_id: int, shot_id: int,
                               force: bool = False, **_: Any) -> dict[str, Any]:
    """已列全直接取用；缺则模型按正文判定补建入库并关联本镜（剧本指纹缓存 168h）。"""
    from .shot_elements import ensure_shot_required_elements

    ids = await ensure_shot_required_elements(pool, project_id, shot_id, force=force)
    return {"element_ids": ids, "count": len(ids)}


@register("shot.ensure_sheets", title="补要素设定图", writes=True, params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "shot_id": {"type": "int", "required": True, "desc": "分镜节点 id"},
    "force": {"type": "bool", "required": False, "desc": "无视指纹强制重出设定图（会花钱）"},
})
async def shot_ensure_sheets(pool: asyncpg.Pool, *, project_id: int, shot_id: int,
                             force: bool = False, **_: Any) -> dict[str, Any]:
    """本镜关联要素缺设定图/外貌指纹失配 → 真实出图补齐（会花钱；指纹命中零成本）。"""
    from types import SimpleNamespace

    from . import steps as steps_mod

    shim = SimpleNamespace(pool=pool, project_id=project_id, node_id=shot_id, task_id=None)
    changed = await steps_mod._ensure_element_sheets(shim, force=force)  # noqa: SLF001 — 同包复用，不复制逻辑
    return {"generated": bool(changed)}


@register("shot.ensure_blocking", title="场景站位兜底", writes=True, params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "shot_id": {"type": "int", "required": True, "desc": "分镜节点 id"},
    "force": {"type": "bool", "required": False, "desc": "无视指纹缓存强制重规划"},
})
async def shot_ensure_blocking(pool: asyncpg.Pool, *, project_id: int, shot_id: int,
                               force: bool = False, **_: Any) -> dict[str, Any]:
    """本镜所在场景组缺站位链 → 先空间规划（组内剧本指纹缓存 168h）。"""
    import json as _json

    from .scene_blocking import ensure_scene_blocking

    row = await pool.fetchrow(
        "SELECT parent_id, meta FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id)
    if not row:
        raise ValueError("分镜不存在")
    meta = row["meta"] if isinstance(row["meta"], dict) else _json.loads(row["meta"] or "{}")
    out = await ensure_scene_blocking(pool, project_id, row["parent_id"],
                                      only_seg=meta.get("scene_seg"), force=force)
    # ensure_scene_blocking 的 groups 是**组数（int）**，不是列表——早先这里套了 len()，
    # 真跑必炸 TypeError（画布上表现为本步红字、且当时还拦不住后续出图）
    out = out or {}
    return {"groups": int(out.get("groups") or 0),
            "planned": out.get("planned") or [], "skipped": out.get("skipped") or []}


@register("shot.reassemble_prompts", title="重装配提示词与参考图", writes=True, params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "shot_id": {"type": "int", "required": True, "desc": "分镜节点 id"},
    "qc_feedback": {"type": "string", "required": False,
                    "desc": "质检回退带入的上轮问题与产物（留档进 meta，供画布与复盘）"},
})
async def shot_reassemble_prompts(pool: asyncpg.Pool, *, project_id: int, shot_id: int,
                                  qc_feedback: str = "", **_: Any) -> dict[str, Any]:
    """重装配三套提示词 + 参考图（指向要素当前最新设定图），结果写回 shot.meta。
    纯 DB+字符串装配，零模型成本；手编提示词（*_edited）由装配内部尊重。
    质检回退重跑时 qc_feedback 留档到 meta.qc_feedback_last；针对问题的提示词重生成
    由质检环节的重构（review_image_prompt 内部唯一实现）完成，这里不另起一份。"""
    import json as _json

    from .storyboard import assemble_shot_prompts

    if (qc_feedback or "").strip():
        await pool.execute(
            "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
            shot_id, _json.dumps({"qc_feedback_last": qc_feedback[:2000]}, ensure_ascii=False))
    fresh = await assemble_shot_prompts(pool, project_id, shot_id)
    return {"text": fresh.get("image_prompt") or "",
            "image_prompt": fresh.get("image_prompt") or "",
            "image_prompt_len": len(fresh.get("image_prompt") or ""),
            "reference_images": len(fresh.get("reference_images") or []),
            "duration_s": fresh.get("duration_s")}


@register("shot.assert_continuity", title="连续性硬门", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "shot_id": {"type": "int", "required": True, "desc": "分镜节点 id"},
})
async def shot_assert_continuity(pool: asyncpg.Pool, *, project_id: int, shot_id: int,
                                 **_: Any) -> dict[str, Any]:
    """连续性记录未就绪（缺记录/校验不过）就不许出图——接不上茬的图先画出来最难收拾。
    2026-07-31 从 gen_keyframe_v2 的内置守卫外化：配它的编排设 on_tool_fail=stop，
    失败即停链，出图不入队。"""
    from .continuity_records import assert_shot_generation_ready

    await assert_shot_generation_ready(pool, shot_id)
    return {"ready": True}


@register("shot.prepare_keyframe", title="首帧出图参数准备", writes=True, params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "shot_id": {"type": "int", "required": True, "desc": "分镜节点 id"},
})
async def shot_prepare_keyframe(pool: asyncpg.Pool, *, project_id: int, shot_id: int,
                                **_: Any) -> dict[str, Any]:
    """出图前的参数准备（原 gen_keyframe_v2 内置守卫，2026-07-31 外化为可编排节点）：
    画幅尺寸、wide 景别软化标记、按本镜停用名单筛掉不该传的参考图。
    结果落 meta.keyframe_prep，由 production_canvas.step_payload 读进入队 payload——
    **删掉这个编排节点 = 真的不做这些准备**，不再在 Step 里偷偷重算一遍。"""
    import json as _json
    from types import SimpleNamespace

    from . import steps as steps_mod

    row = await pool.fetchrow(
        "SELECT meta FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id)
    if not row:
        raise ValueError("分镜不存在")
    meta = row["meta"] if isinstance(row["meta"], dict) else _json.loads(row["meta"] or "{}")
    if not meta.get("image_prompt"):
        raise ValueError("缺首帧提示词：请先跑「单镜提示词装配 / 重装配提示词」前置")
    shim = SimpleNamespace(pool=pool, project_id=project_id, node_id=shot_id, task_id=None)
    ratio = await steps_mod._frame_aspect_ratio(shim)  # noqa: SLF001 — provider 决定像素
    first_cut = (meta.get("cuts") or [{}])[0]
    scale = first_cut.get("scale") or meta.get("scale", "")
    off = steps_mod._refs_off(meta, "image")  # noqa: SLF001
    refs = [r for r in (meta.get("reference_images") or []) if r.get("name") not in off]
    prep = {"aspect_ratio": ratio, "wide_frame": scale in ("全景", "远景", "大远景"),
            "reference_images": refs}
    await pool.execute(
        "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
        shot_id, _json.dumps({"keyframe_prep": prep}, ensure_ascii=False))
    return {"aspect_ratio": ratio, "wide_frame": prep["wide_frame"], "reference_images": len(refs),
            "dropped_refs": sorted(off) or None}


@register("shot.review_image_prompt", title="首帧提示词质检", writes=True, params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "shot_id": {"type": "int", "required": True, "desc": "分镜节点 id"},
    "prev_feedback": {"type": "string", "required": False,
                      "desc": "上一轮质检的问题清单（回退重试时传入，重构须针对性解决）"},
})
async def shot_review_image_prompt(pool: asyncpg.Pool, *, project_id: int, shot_id: int,
                                   prev_feedback: str = "", **_: Any) -> dict[str, Any]:
    """首帧提示词十维质检：不合格自动重构→复审，结果带指纹+72h 有效期落
    meta.prompt_review_image（gen_keyframe_v2 出图前不再重跑质检，以此为准）。"""
    from .storyboard import review_image_prompt

    rv = await review_image_prompt(pool, project_id, shot_id, prev_feedback=prev_feedback)
    return {"text": rv.get("image_prompt") or "", "合格": rv.get("合格"),
            "得分": rv.get("得分"), "重构": bool(rv.get("重构")),
            "有保留": bool(rv.get("有保留")),
            "问题": (rv.get("复审问题") if rv.get("重构") else rv.get("问题")) or []}


# ═══════════ 通用只读查询 ═══════════
# 这些用 db.query 一条 SQL 也能查，之所以还封成具名工具：技能调用时「按名字要东西」
# 比「自己拼 SQL」稳得多。原则是**只封高频且入参极简的**，不做端点的镜像。

@register("project.info", title="项目基本信息", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
})
async def project_info(pool: asyncpg.Pool, *, project_id: int, **_: Any) -> dict[str, Any]:
    """项目基本信息 + 章节/分镜/要素计数（技能开工前的第一手上下文）。"""
    row = await pool.fetchrow(
        "SELECT id,title,project_type,synopsis,writing_style,art_style,storyline,"
        "status,owner_id,config,created_at,updated_at FROM content_projects "
        "WHERE id=$1 AND deleted_at IS NULL", project_id)
    if not row:
        raise ValueError(f"项目 {project_id} 不存在")
    stats = await pool.fetchrow(
        "SELECT (SELECT count(*) FROM content_nodes WHERE project_id=$1 AND kind='chapter') AS chapters,"
        "       (SELECT count(*) FROM content_nodes WHERE project_id=$1 AND kind='shot')    AS shots,"
        "       (SELECT count(*) FROM content_elements WHERE project_id=$1)                 AS elements",
        project_id)
    return {**dict(row), **dict(stats)}


@register("chapter.info", title="本章基本信息", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "shot_id": {"type": "int", "required": False, "desc": "镜 id（给它就自动取所属章）"},
    "chapter_id": {"type": "int", "required": False, "desc": "章 id；与 shot_id 二选一"},
})
async def chapter_info(pool: asyncpg.Pool, *, project_id: int, shot_id: int | None = None,
                       chapter_id: int | None = None, **_: Any) -> dict[str, Any]:
    """本章的基本盘：标题/梗概/正文长度/镜头数/场景归组概览。
    单镜链路上下文只有镜 id，所以给 shot_id 时自动向上取所属章。"""
    import json as _json

    cid = chapter_id
    if cid is None and shot_id:
        cid = await pool.fetchval(
            "SELECT parent_id FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id)
    if not cid:
        raise ValueError("chapter_id 与 shot_id 至少给一个（shot_id 会自动取所属章）")
    row = await pool.fetchrow(
        "SELECT id,title,seq,summary,meta FROM content_nodes "
        "WHERE id=$1 AND project_id=$2 AND kind='chapter'", cid, project_id)
    if not row:
        raise ValueError(f"章 {cid} 不存在（project={project_id}）")
    meta = row["meta"] if isinstance(row["meta"], dict) else _json.loads(row["meta"] or "{}")
    groups = ((meta.get("scene_blocking") or {}).get("groups")) or []
    # 正文在 content_bodies（多版本，取最新）——不在 content_nodes 上
    body = await pool.fetchval(
        "SELECT content FROM content_bodies WHERE node_id=$1 ORDER BY version DESC LIMIT 1",
        cid) or ""
    shots = await pool.fetchval(
        "SELECT count(*) FROM content_nodes WHERE parent_id=$1 AND kind='shot' "
        "AND deleted_at IS NULL", cid)
    return {
        "chapter_id": row["id"], "title": row["title"], "seq": row["seq"],
        "summary": row["summary"], "content_len": len(body),
        "shots": shots,
        "scene_groups": [{"seg": g.get("seg"), "scene": g.get("scene"),
                          "shot_nos": g.get("shot_nos")} for g in groups],
    }


# 章级分镜清单是全站唯一实现：HTTP 端点 GET /chapters/{id}/shots 也 import 这里，
# 不再各写一句 SQL。它同时是 Tapflow 循环的数据源——items 声明了 items.properties，
# 画布「设为循环」才能让循环体引 {{item.shot_id}}。
_SHOT_ITEM_PROPS = {
    "shot_id": {"type": "int", "desc": "分镜节点 id（下游 shot.* 工具的入参）"},
    "shot_no": {"type": "string", "desc": "展示镜号（可能是 8.5 这种小数）"},
    "seq": {"type": "int", "desc": "排序键"},
    "title": {"type": "string", "desc": "镜头标题"},
    "summary": {"type": "string", "desc": "画面描述"},
    "action": {"type": "string", "desc": "动作"},
    "dialogue": {"type": "string", "desc": "对白"},
    "scene": {"type": "string", "desc": "场景名"},
    "scale": {"type": "string", "desc": "景别"},
    "duration_s": {"type": "int", "desc": "时长（秒）"},
    "cuts": {"type": "int", "desc": "CUT 数（0=还没跑单镜时间轴）"},
    "image_prompt": {"type": "string", "desc": "首帧提示词（空=未装配）"},
    "keyframe_url": {"type": "string", "desc": "关键帧地址（空=未出图）"},
    "storyboard_ref": {"type": "object", "desc": "九宫格定位：第几张第几格 + 整图 url"},
    "detail_pending": {"type": "bool", "desc": "还是粗拆骨架、未做详细展开"},
}


@register("chapter.shots", title="本章分镜清单", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "chapter_id": {"type": "int", "required": True, "desc": "章节节点 id"},
}, outputs={
    "items": {"type": "array", "desc": "按镜序排列的分镜清单（循环数据源）",
              "items": {"type": "object", "properties": _SHOT_ITEM_PROPS}},
    "count": {"type": "int", "desc": "分镜数"},
    "pending_details": {"type": "int", "desc": "还没详细展开的镜数"},
    "with_keyframe": {"type": "int", "desc": "已出关键帧的镜数"},
})
async def chapter_shots(pool: asyncpg.Pool, *, project_id: int, chapter_id: int,
                        **_: Any) -> dict[str, Any]:
    """取本章的分镜脚本清单（只读）：每镜的镜号/画面/动作/对白/景别/时长，以及
    提示词、关键帧、总览宫格定位的**就绪状态**。要遍历一章的每一镜就从这里取 items。
    空数组表示本章还没拆镜——那要先跑 chapter.ensure_storyboard。"""
    import json as _json

    rows = await pool.fetch(
        "SELECT id, seq, title, summary, status, meta FROM content_nodes "
        "WHERE parent_id=$1 AND project_id=$2 AND kind='shot' AND deleted_at IS NULL "
        "ORDER BY seq", chapter_id, project_id)
    items = []
    for row in rows:
        meta = row["meta"] if isinstance(row["meta"], dict) else _json.loads(row["meta"] or "{}")
        items.append({
            "shot_id": row["id"], "seq": row["seq"], "status": row["status"],
            "shot_no": str(meta.get("shot_no") or row["seq"]),
            "title": row["title"], "summary": row["summary"] or "",
            "action": meta.get("action") or "", "dialogue": meta.get("dialogue") or "",
            "scene": meta.get("scene") or "", "scale": meta.get("scale") or "",
            "duration_s": meta.get("duration_s"),
            "cuts": len(meta.get("cuts") or []),
            "image_prompt": meta.get("image_prompt") or "",
            "keyframe_url": meta.get("keyframe_url") or "",
            "storyboard_ref": meta.get("storyboard_ref") or {},
            "detail_pending": bool(meta.get("detail_pending")),
            # 端点的历史返回形状靠这两个字段还原，别删（见 api/shots.list_shots）
            "meta": meta,
        })
    return {
        "chapter_id": chapter_id, "items": items, "count": len(items),
        "pending_details": sum(1 for i in items if i["detail_pending"]),
        "with_keyframe": sum(1 for i in items if i["keyframe_url"]),
    }


@register("chapter.ensure_storyboard", title="分镜脚本生成或查询", writes=True, params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "chapter_id": {"type": "int", "required": True, "desc": "章节节点 id"},
    "force": {"type": "bool", "required": False,
              "desc": "已有分镜也重拆（会清空重来并花钱），默认 false"},
}, outputs={
    "items": {"type": "array", "desc": "分镜清单（形状同 chapter.shots，循环数据源）",
              "items": {"type": "object", "properties": _SHOT_ITEM_PROPS}},
    "count": {"type": "int", "desc": "分镜数"},
    "generated": {"type": "bool", "desc": "本次是否真的跑了拆镜"},
    "tasks": {"type": "array", "desc": "本次派发并等待的任务 id"},
})
async def chapter_ensure_storyboard(pool: asyncpg.Pool, *, project_id: int, chapter_id: int,
                                    force: bool = False, **_: Any) -> dict[str, Any]:
    """确保本章有可用的分镜脚本，然后返回清单——**缺才跑**：已有详细分镜直接返回
    （零成本零副作用），只有粗拆骨架就补详细展开，一镜都没有才从章节正文拆镜。
    产出 items 可直接作为「逐镜」循环的数据源。force=true 才会重拆（花钱且会重排时间轴）。

    拆镜本体仍是 breakdown_chapter / expand_shot_details 两个 Step，这里只负责
    「判断该不该跑 + 等它跑完 + 回读清单」，不复制任何拆镜逻辑。"""
    from . import flow
    from .workflow import _await_task  # noqa: PLC0415,SLF001 — 等任务终态只此一份实现

    existing = await chapter_shots(pool, project_id=project_id, chapter_id=chapter_id)
    if existing["count"] and not existing["pending_details"] and not force:
        return {**existing, "generated": False, "tasks": [],
                "reason": "本章已有详细分镜，未重跑"}

    tasks: list[int] = []

    async def run(kind: str) -> dict[str, Any]:
        q = await flow.enqueue_with_deps(pool, kind=kind, project_id=project_id,
                                         node_id=chapter_id, payload={}, priority=5)
        task_id = q.get("task_id")
        tasks.append(task_id)
        status, err, result = await _await_task(pool, task_id)
        if status != "done":
            raise ValueError(f"{kind} 失败: {err}")
        return result

    if existing["count"] and not force:
        # 只是粗拆没展开：补第二阶段就够，不重拆骨架（重拆会把已有镜清空重来）
        await run("expand_shot_details")
    else:
        result = await run("breakdown_chapter")
        # 粗拆的 next 会自动串出详细展开（见 BreakdownStep.next）——等它，
        # 否则这里返回的是一份还没展开的骨架，下游按详细字段取值全是空
        details = result.get("details_task")
        if details:
            tasks.append(int(details))
            status, err, _r = await _await_task(pool, int(details))
            if status != "done":
                raise ValueError(f"expand_shot_details 失败: {err}")

    fresh = await chapter_shots(pool, project_id=project_id, chapter_id=chapter_id)
    return {**fresh, "generated": True, "tasks": tasks}


@register("shot.info", title="本镜基本信息与场景锚定", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "shot_id": {"type": "int", "required": True, "desc": "分镜节点 id"},
})
async def shot_info(pool: asyncpg.Pool, *, project_id: int, shot_id: int,
                    **_: Any) -> dict[str, Any]:
    """本镜剧本要素（画面/动作/对白/景别/时长/切镜）+ **所属场景组的锚定**
    （空间描述、站位、空场景基准图与站位图 URL）——出图前"这一镜在哪、怎么站"的事实来源。"""
    import json as _json

    def _j(v: Any) -> dict[str, Any]:
        return v if isinstance(v, dict) else _json.loads(v or "{}")

    row = await pool.fetchrow(
        "SELECT id,parent_id,seq,summary,meta FROM content_nodes "
        "WHERE id=$1 AND project_id=$2 AND kind='shot'", shot_id, project_id)
    if not row:
        raise ValueError(f"分镜 {shot_id} 不存在（project={project_id}）")
    meta = _j(row["meta"])
    chapter = await pool.fetchrow(
        "SELECT meta FROM content_nodes WHERE id=$1", row["parent_id"])
    groups = ((_j(chapter["meta"]).get("scene_blocking") or {}).get("groups")) or [] \
        if chapter else []
    seg = meta.get("scene_seg")
    g = next((x for x in groups if x.get("seg") == seg), None)
    anchor = {
        "seg": seg, "scene": (g or {}).get("scene") or meta.get("scene"),
        "space": (g or {}).get("space"), "anchors": (g or {}).get("anchors"),
        "empty_url": (g or {}).get("empty_url"), "sheet_url": (g or {}).get("sheet_url"),
    } if g else {"seg": seg, "scene": meta.get("scene")}
    return {
        "shot_id": row["id"], "shot_no": meta.get("shot_no") or row["seq"],
        "summary": row["summary"], "action": meta.get("action"),
        "dialogue": meta.get("dialogue"), "scale": meta.get("scale"),
        "angle": meta.get("angle"), "lens_feel": meta.get("lens_feel"),
        "duration_s": meta.get("duration_s"), "cuts": len(meta.get("cuts") or []),
        "characters": meta.get("characters") or [],
        "scene_anchor": anchor,
    }


def _element_summary(kind: str, name: str, brief: str | None,
                     meta: dict[str, Any]) -> str:
    """要素的人类可读摘要（画布「场景信息 / 角色信息」节点直出这一段）。
    只做取数+排版，不掺任何提示词工程——出图提示词是 element_sheet 的活，不在这里分叉。"""
    lines = [f"{name}"]
    if brief:
        lines.append(str(brief))
    if kind == "character" and meta.get("外貌提示词"):
        lines.append(f"外貌：{meta['外貌提示词']}")
    profile = meta.get("profile") if isinstance(meta.get("profile"), dict) else {}
    feats = "；".join(f"{k}：{v}" for k, v in profile.items() if v)
    if feats:
        lines.append(f"设定：{feats}")
    variants = [v.get("name") for v in (meta.get("variants") or []) if v.get("name")]
    if len(variants) > 1:
        lines.append(f"形态：{'、'.join(str(v) for v in variants)}")
    refs = [r.get("name") for r in (meta.get("extra_refs") or []) if r.get("url")]
    if refs:
        lines.append(f"参考图：{len(refs)} 张（{'、'.join(str(r) for r in refs[:3])}）")
    return "\n".join(lines)


@register("element.get", title="要素详情（含设定图）", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "element_id": {"type": "int", "required": False, "desc": "要素 id；与 name / target_ref 三选一"},
    "target_ref": {"type": "string", "required": False,
                   "desc": "目标引用 element:{id}；素材库画布用它传归属（与 element_id 等价）"},
    "name": {"type": "string", "required": False, "desc": "要素名，按名字取"},
})
async def element_get(pool: asyncpg.Pool, *, project_id: int, element_id: int | None = None,
                      target_ref: str | None = None, name: str | None = None,
                      **_: Any) -> dict[str, Any]:
    """取某个要素的设定与图片（设定图 + 各造型变体图 + 附件里的历史出图）。
    summary 是人类可读摘要（画布上「场景信息 / 素材信息」节点直出这一段）。
    定位方式三选一：element_id（智能参数卡路径）/ target_ref（素材库画布路径，
    生产态入参只带 element:{id} 引用）/ name（按名字取）。"""
    # 空串一律当没填：运行面板里未填的可选入参常以空串传进来，
    # 不挡一道就会拿 "" 去 match element_id/$2::bigint 炸出类型错
    element_id = int(element_id) if element_id not in (None, "") else None
    name = name or None
    if not element_id and target_ref:
        from .resource_refs import parse
        ref = parse(target_ref)
        if not ref or ref[0] != "element":
            raise ValueError(f"target_ref {target_ref!r} 不是 element:<id> 形式的要素引用")
        element_id = int(ref[1])
    if not element_id and not name:
        raise ValueError("请先选择素材要素（element_id / target_ref / name 至少给一个）")
    row = await pool.fetchrow(
        "SELECT id,kind,name,brief,state,meta,created_at,updated_at FROM content_elements "
        "WHERE project_id=$1 AND ($2::bigint IS NULL OR id=$2) "
        "AND ($3::text IS NULL OR name=$3) LIMIT 1", project_id, element_id, name)
    if not row:
        raise ValueError(f"要素不存在（project={project_id} id={element_id} name={name}）")
    import json

    meta = row["meta"] if isinstance(row["meta"], dict) else json.loads(row["meta"] or "{}")
    summary = _element_summary(row["kind"], row["name"], row["brief"], meta)
    imgs = await pool.fetch(
        "SELECT id,kind,url,created_at FROM content_attachments "
        "WHERE element_id=$1 AND url IS NOT NULL ORDER BY id DESC LIMIT 20", row["id"])
    return {
        "id": row["id"], "kind": row["kind"], "name": row["name"], "brief": row["brief"],
        "state": row["state"], "meta": meta, "summary": summary,
        "sheet_url": meta.get("sheet_url"),
        "variants": [{"id": v.get("id"), "name": v.get("name"), "sheet_url": v.get("sheet_url")}
                     for v in (meta.get("variants") or [])],
        # attachments 逐字段挑出来：created_at 转 ISO 字符串——
        # asyncpg 给的是 datetime，原样进 ctx 会在后续 json.dumps 时炸掉整个 run
        #（「Object of type datetime is not JSON serializable」，2026-09-18 画布 run 全挂的根因）。
        "attachments": [
            {"id": r["id"], "kind": r["kind"], "url": r["url"],
             "created_at": r["created_at"].isoformat() if r["created_at"] else None}
            for r in imgs
        ],
    }


@register("trailer.distill", title="预告片·蒸馏提示词", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
}, outputs={
    "prompt": {"type": "string", "desc": "15s 硬切蒙太奇预告片提示词（含硬约束骨架与引用句）"},
    "refs": {"type": "array", "items": {"type": "object",
             "properties": {"name": {"type": "string"}, "kind": {"type": "string"},
                            "url": {"type": "string"}}},
             "desc": "默认参考图（前几位有设定图的角色）"},
})
async def trailer_distill(pool: asyncpg.Pool, *, project_id: int, **_: Any) -> dict[str, Any]:
    """先导预告片提示词蒸馏：与 POST /projects/{id}/trailer/prompt 同一条代码路径。"""
    from . import trailer
    row = await pool.fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
    if not row:
        raise ValueError(f"项目不存在 id={project_id}")
    return await trailer.distill_prompt(pool, row)


@register("scene.batch_plan", title="批量首帧·场景分组计划", params={
    "project_id": {"type": "int", "required": True, "desc": "项目 id"},
    "chapter_id": {"type": "int", "required": True, "desc": "章（集）id"},
    "seg": {"type": "int", "desc": "只装该场景组（可缺省=全部场景组）"},
}, outputs={
    "batches": {"type": "array", "items": {"type": "object",
                 "properties": {"seg": {"type": "int"}, "scene": {"type": "string"},
                                "contract_id": {"type": "string"},
                                "shot_ids": {"type": "array", "items": {"type": "int"}},
                                "refs": {"type": "array", "items": {"type": "object"}}}},
                 "desc": "按（场景组号×连续性合同）切好的批次，loop 逐批派 gen_keyframes_group"},
    "total_shots": {"type": "int"},
})
async def scene_batch_plan(pool: asyncpg.Pool, *, project_id: int, chapter_id: int,
                           seg: int | None = None, **_: Any) -> dict[str, Any]:
    """把整集分镜按场景切组并列出每组的参考图池——与前端 sceneBatches()+GROUP_LIMIT 同一算法
    的服务端版，供批量首帧画布的 loop 节点逐批入队 gen_keyframes_group。
    供应商硬约束「参考图+生成数≤15」：每批压到 6 镜留足参考槽，超出按镜号序切多条。"""
    import json as _json
    GROUP_LIMIT = 6  # 与前端 lib/batchKeyframeBoard.GROUP_LIMIT 同值同源
    rows = await pool.fetch(
        "SELECT id, meta FROM content_nodes WHERE project_id=$1 AND parent_id=$2 "
        "AND kind='shot' AND deleted_at IS NULL ORDER BY sort_order, id", project_id, chapter_id)
    order: list[str] = []
    batches: dict[str, dict[str, Any]] = {}
    for r in rows:
        meta = r["meta"] if isinstance(r["meta"], dict) else _json.loads(r["meta"] or "{}")
        s = int(meta.get("scene_seg") or 1)
        contract = str(meta.get("continuity", {}).get("scene_contract_id") or "")
        key = f"{s}:{contract}"
        b = batches.get(key)
        if not b:
            b = {"seg": s, "scene": str(meta.get("scene") or ""), "contract_id": contract or None,
                 "shot_ids": [], "refs": []}
            batches[key] = b
            order.append(key)
        b["shot_ids"].append(r["id"])
    out: list[dict[str, Any]] = []
    part_no = 0
    for key in order:
        b = batches[key]
        if seg is not None and int(b["seg"]) != int(seg):
            continue
        # 参考池同前端 sceneBatches()：批内按名字去重、剔除故事板格位图，
        # 场景站位图是整组的空间/光线主锚，排角色设定图之前
        by_name: dict[str, dict[str, Any]] = {}
        for sid in b["shot_ids"]:
            row = next(x for x in rows if x["id"] == sid)
            meta = row["meta"] if isinstance(row["meta"], dict) else _json.loads(row["meta"] or "{}")
            for rf in (meta.get("reference_images") or []):
                if not rf.get("url") or rf.get("kind") == "storyboard" or rf["name"] in by_name:
                    continue
                by_name[rf["name"]] = {"name": rf["name"], "kind": rf.get("kind") or "canvas",
                                        "url": rf["url"]}
        refs = list(by_name.values())
        refs.sort(key=lambda x: 0 if x.get("kind") == "scene_sheet" else 1)
        ids = b["shot_ids"]
        for i in range(0, len(ids), GROUP_LIMIT):
            part_no += 1
            out.append({**b, "part": part_no,
                        "part_count": (len(ids) + GROUP_LIMIT - 1) // GROUP_LIMIT,
                        "shot_ids": ids[i:i + GROUP_LIMIT], "refs": refs})
    return {"batches": out, "total_shots": len(rows)}
