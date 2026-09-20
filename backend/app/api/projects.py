"""项目 API：草稿建项目 / 基本信息 / 目录 / 要素 / 偏好 / 资料。"""
import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import llm, oss
from ..db import get_pool
from ..knowledge import style_anchor
from ..users import current_user
from ..services import flow, pipeline, pipeline_stream, volumes
from ..services import elements as elements_service
from ..services.character_context import roster_inline
from ..services.material_ingest import chunk_text, core_excerpt, extract_text

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _jsonb(v: Any) -> Any:
    return v if isinstance(v, (dict, list)) else (json.loads(v) if v else {})


async def _ensure_owner_or_admin(pool, project_id: int, user: dict) -> None:
    """归属闸门（多用户 2026-09-17）：owner 或 admin 放行；其他人一律 404
    ——用「不存在」而不是 403，不向无关用户暴露项目存在性。"""
    row = await pool.fetchrow(
        "SELECT owner_id FROM content_projects WHERE id=$1", project_id)
    if not row or (row["owner_id"] != user["id"] and user["role"] != "admin"):
        raise HTTPException(404, "项目不存在")


def _stream_ndjson(
    runner: Callable[[Callable[[dict[str, Any]], Awaitable[None]]], Awaitable[list[Any]]],
) -> StreamingResponse:
    """把「回调式逐条生成」桥接成 NDJSON 流响应：服务内每落库一条调用 emit(dict) 即推一行；
    末行 {"done": n}（成功）或 {"error": msg}（失败——中途已落库条目照常保留，前端已收到）。"""
    q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def emit(obj: dict[str, Any]) -> None:
        await q.put(obj)

    async def run() -> None:
        try:
            out = await runner(emit)
            await q.put({"done": len(out)})
        except Exception as e:  # noqa: BLE001 — HTTP 已 200，错误以行透传给前端
            await q.put({"error": str(e)[:300]})
        finally:
            await q.put(None)

    async def gen():
        task = asyncio.create_task(run())
        try:
            while (item := await q.get()) is not None:
                yield json.dumps(item, ensure_ascii=False, default=str) + "\n"
        finally:
            task.cancel()  # 客户端断连即停生成（正常结束时任务已完成，cancel 为空操作）

    return StreamingResponse(gen(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class MaterialStaged(BaseModel):
    """引导式新建·暂存资料：文本=content；文件=已直传 OSS 的 url（随建项目一并落库）。"""
    title: str = ""
    source: str = "input"  # input=文本 / upload=文件
    content: str = ""
    url: str | None = None
    size: int | None = None
    content_type: str | None = None
    # Returned by /uploads; kept so the final create request can commit the
    # staged local file and its extracted chunks to the project.
    staging_path: str | None = None
    extracted_text: str = ""
    extractor: str | None = None
    core_excerpt: str = ""


class DraftIn(BaseModel):
    draft: str = Field(min_length=10, description="小说草稿/构思")
    # 引导各步暂存值（空=由 AI 按草稿初拟；非空=覆盖 AI 初拟）
    title: str = ""
    synopsis: str = ""
    storyline: str = ""
    writing_style: str = ""
    art_style: str = ""
    aspect_ratio: str = ""  # 画幅比例（16:9 / 9:16），进 config
    character_mode: str = "virtual"  # real=真人备案身份；virtual=完整虚拟形象
    # 内容类型来自标签分组（video_type）；首个视频类型标签同时作为 project_type，供技能/知识筛选。
    project_type: str = "novel_comic"
    tags: list[str] = Field(default_factory=list)
    materials: list[MaterialStaged] = []


async def _insert_material(conn: Any, project_id: int, m: MaterialStaged) -> None:
    """暂存资料落库：文本→project_materials；上传文件→附件表+资料引用附件。"""
    if m.source == "upload":
        extracted = m.extracted_text or ""
        extractor = m.extractor or "client"
        if not extracted and m.staging_path:
            try:
                p = Path(m.staging_path)
                # Only read files under the process temp directory; this field
                # is a staging reference, never an arbitrary server path.
                if p.is_file() and str(p.resolve()).startswith(str(Path(tempfile.gettempdir()).resolve())):
                    extracted, extractor = extract_text(m.title, p.read_bytes(), m.content_type)
            except OSError:
                extracted = ""
        chunks = chunk_text(extracted)
        att = await conn.fetchrow(
            "INSERT INTO content_attachments (project_id, kind, file_path, url, meta) "
            "VALUES ($1,'material',$2,$3,$4::jsonb) RETURNING id",
            project_id, m.title or "material", m.url,
            json.dumps({"size": m.size, "content_type": m.content_type}, ensure_ascii=False),
        )
        mat = await conn.fetchrow(
            "INSERT INTO project_materials (project_id, title, source, meta) VALUES ($1,$2,'upload',$3::jsonb) RETURNING id",
            project_id, m.title or "material",
            json.dumps({"attachment_id": att["id"], "url": m.url, "size": m.size,
                        "content_type": m.content_type, "local_path": m.staging_path,
                        "extractor": extractor, "processing_status": "processed",
                        "extracted_chars": len(extracted), "chunk_count": len(chunks),
                        "core_excerpt": m.core_excerpt or core_excerpt(extracted)}, ensure_ascii=False),
        )
        material_id = mat["id"]
        if extracted:
            await conn.execute("UPDATE project_materials SET content=$2 WHERE id=$1", material_id, extracted)
        for c in chunks:
            await conn.execute(
                "INSERT INTO project_material_chunks "
                "(material_id,chunk_index,content,summary,char_start,char_end,meta) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)",
                material_id, c["index"], c["content"], c["summary"], c["char_start"], c["char_end"],
                json.dumps({"extractor": extractor}, ensure_ascii=False))
    else:
        title = m.title.strip() or (m.content.strip().splitlines()[0][:24] if m.content.strip() else "文本资料")
        chunks = chunk_text(m.content)
        mat = await conn.fetchrow(
            "INSERT INTO project_materials (project_id, title, source, content, meta) "
            "VALUES ($1,$2,'input',$3,$4::jsonb) RETURNING id",
            project_id, title, m.content,
            json.dumps({"processing_status": "processed", "extracted_chars": len(m.content),
                        "chunk_count": len(chunks), "core_excerpt": core_excerpt(m.content)}, ensure_ascii=False),
        )
        for c in chunks:
            await conn.execute(
                "INSERT INTO project_material_chunks "
                "(material_id,chunk_index,content,summary,char_start,char_end) VALUES ($1,$2,$3,$4,$5,$6)",
                mat["id"], c["index"], c["content"], c["summary"], c["char_start"], c["char_end"],
            )


@router.post("")
async def create_from_draft(body: DraftIn, user: dict = Depends(current_user)):
    """引导式新建终点：项目即时落库（用户暂存值直接写入）+seed 数字员工+暂存资料落库。
    AI 初拟转后台：gen_project_info 补齐用户留空的基本信息字段，完成后自动链 gen_outline_md。"""
    overrides = {
        k: v.strip()
        for k in ("title", "synopsis", "storyline", "writing_style", "art_style", "aspect_ratio", "project_type")
        if (v := getattr(body, k)).strip()
    }
    # 允许前端同时传 project_type 与 tags；视频类型标签优先，旧客户端仍默认为 novel_comic。
    tags = [str(t).strip() for t in body.tags if str(t).strip()]
    project_type = (body.project_type or "").strip()
    # 只把 video_type 分组的标签作为路由类型，避免用户先点了风格标签导致技能误筛。
    if not project_type or project_type == "novel_comic":
        project_type = await get_pool().fetchval(
            "SELECT t.code FROM tags t JOIN tag_groups g ON g.id=t.group_id "
            "WHERE g.code='video_type' AND t.code = ANY($1::text[]) ORDER BY t.seq,t.id LIMIT 1",
            tags) or "novel_comic"
    overrides["project_type"] = project_type
    overrides["tags"] = tags
    if body.character_mode not in ("real", "virtual"):
        raise HTTPException(422, "角色类型必须选择真人或虚拟形象")
    overrides["character_mode"] = body.character_mode
    row = await pipeline.create_project_from_draft(get_pool(), body.draft, overrides)
    # 多用户（2026-09-17）：归属=创建人（pipeline 走 DB 默认列，这里显式回写）
    await get_pool().execute(
        "UPDATE content_projects SET owner_id=$1 WHERE id=$2", user["id"], row["id"])
    async with get_pool().acquire() as conn:
        for m in body.materials:
            await _insert_material(conn, row["id"], m)
    # 基本信息初拟→架构大纲 全部后台补齐（LLM 同步跑会撞网关超时）；入队失败不阻断建项目
    try:
        await flow.enqueue(get_pool(), kind="gen_project_info", project_id=row["id"])
    except Exception:  # noqa: BLE001
        pass
    row["config"] = _jsonb(row.get("config"))
    return row


@router.post("/uploads")
async def upload_file(file: UploadFile = File(...)):
    """引导式新建·文件直传：仅转存 OSS 返回 URL，不落库（项目未建，最后一步随创建一并关联）。"""
    data = await file.read()
    name = file.filename or "material"
    ext = Path(name).suffix or ".bin"
    url = await oss.store_bytes(data, prefix="materials/staging", ext=ext)
    # Keep a local staging copy so the project can be created even when OSS is
    # not configured.  The path is returned as an opaque staging reference.
    stage_dir = Path(tempfile.gettempdir()) / "novelcomic-materials" / "staging"
    stage_dir.mkdir(parents=True, exist_ok=True)
    stage_path = stage_dir / f"{os.urandom(8).hex()}{ext}"
    stage_path.write_bytes(data)
    text, extractor = extract_text(name, data, file.content_type)
    chunks = chunk_text(text)
    # OSS 未配置时 url=None：前端提示未转存，仍可作占位记录
    return {"url": url, "name": name, "size": len(data),
            "content_type": file.content_type, "stored": url is not None,
            "staging_path": str(stage_path), "extractor": extractor,
            "extracted_chars": len(text), "chunk_count": len(chunks),
            "core_excerpt": core_excerpt(text)}


class RestyleIn(BaseModel):
    """草稿态文风/画风评估（项目未建，上下文全由前端暂存值提供）。"""
    target: str = Field(description="writing=文风 / art=画风")
    instruction: str | None = Field(default=None, description="可选微调指令，如'再冷硬一点/更偏水墨'")
    draft: str = ""
    title: str = ""
    synopsis: str = ""
    current: str = Field(default="", description="当前文本（AI 在此基础上调整）")


_RESTYLE_SYS = {
    "writing": "你是资深小说文风顾问。基于作品信息给出一条【文风评估与写作指令】（50-100字：判断最适合的文风流派并给出可执行风格指令，如'莫言式乡土魔幻，长句铺排，感官轰炸'）。只输出这一段文字，不要解释、不要引号。",
    "art": "你是漫剧视觉总监。基于作品信息给出一条【画风评估】（30-60字：判断改编漫剧最适合的画风，如'日漫赛璐璐/国漫水墨/美漫厚涂/电影感写实'之一并说明理由）。只输出这一段文字，不要解释、不要引号。",
}


@router.post("/restyle")
async def restyle(body: RestyleIn):
    """AI 评估文风/画风（草稿态，不落库——前端确认后随创建/更新保存）。"""
    if body.target not in _RESTYLE_SYS:
        raise HTTPException(400, "target 仅支持 writing / art")
    user = (
        f"书名：{body.title or '（未定）'}\n梗概：{body.synopsis or '（未定）'}\n"
        f"当前{'文风' if body.target == 'writing' else '画风'}：{body.current or '（未设定）'}\n"
        f"草稿片段：{body.draft[:1500]}\n\n"
        f"{('微调要求：' + body.instruction) if body.instruction else '请给出你的评估建议。'}"
    )
    suggestion = (await llm.chat_text(_RESTYLE_SYS[body.target], user, temperature=0.8)).strip()
    return {"suggestion": suggestion}


class DraftInfoIn(BaseModel):
    """基本信息步·一键智能生成（草稿态，不落库）：仅需草稿。"""
    draft: str = Field(min_length=10, description="小说草稿/构思")
    project_type: str = Field(default="novel_comic", description="项目类型：novel_comic 走小说向，视频类型标签走宣传企划分版")


@router.post("/draft-info")
async def draft_info(body: DraftInfoIn):
    """基本信息步·星标一键生成：草稿→书名/梗概/主线（草稿态，返回文本不落库，用户可再改）。"""
    info = await pipeline.gen_project_info(body.draft, body.project_type)
    return {
        "title": (info.get("title") or "").strip(),
        "synopsis": (info.get("synopsis") or "").strip(),
        "storyline": (info.get("storyline") or "").strip(),
    }


@router.get("")
async def list_projects(user: dict = Depends(current_user)):
    """项目列表（多用户 2026-09-17）：非 admin 只看自己的，admin 看全部。"""
    where = "WHERE deleted_at IS NULL"   # 白名单拼接：用户输入只走 $n 参数，不进 SQL 文本
    args: list = []
    if user["role"] != "admin":
        where += " AND owner_id = $1"
        args.append(user["id"])
    rows = await get_pool().fetch(
        "SELECT id, title, project_type, synopsis, writing_style, art_style, status, "
        f"config, created_at FROM content_projects {where} ORDER BY id DESC", *args
    )
    return [{**dict(r), "config": _jsonb(r["config"])} for r in rows]


# ═══════════ 回收站（软删除）═══════════
# 注意：静态段 /trash 必须声明在泛化的 /{project_id} 之前，否则会被当作 int 路径参数解析 422。

@router.get("/trash")
async def list_trash(user: dict = Depends(current_user)):
    """回收站列表：已软删除的项目（含封面用 config），按删除时间倒序；非 admin 只看自己的。"""
    where = "WHERE deleted_at IS NOT NULL"
    args: list = []
    if user["role"] != "admin":
        where += " AND owner_id = $1"
        args.append(user["id"])
    rows = await get_pool().fetch(
        "SELECT id, title, synopsis, config, deleted_at, created_at FROM content_projects "
        f"{where} ORDER BY deleted_at DESC", *args
    )
    return [{**dict(r), "config": _jsonb(r["config"])} for r in rows]


@router.delete("/{project_id}")
async def soft_delete_project(project_id: int, user: dict = Depends(current_user)):
    """软删除项目（移入回收站）：仅置 deleted_at，数据与产物全保留，可恢复。"""
    await _ensure_owner_or_admin(get_pool(), project_id, user)
    r = await get_pool().fetchrow(
        "UPDATE content_projects SET deleted_at=now(), updated_at=now() "
        "WHERE id=$1 AND deleted_at IS NULL RETURNING id", project_id,
    )
    if not r:
        raise HTTPException(404, "项目不存在或已在回收站")
    return {"ok": True, "id": project_id}


@router.post("/{project_id}/restore")
async def restore_project(project_id: int, user: dict = Depends(current_user)):
    """从回收站恢复项目：清空 deleted_at。"""
    await _ensure_owner_or_admin(get_pool(), project_id, user)
    r = await get_pool().fetchrow(
        "UPDATE content_projects SET deleted_at=NULL, updated_at=now() "
        "WHERE id=$1 AND deleted_at IS NOT NULL RETURNING id", project_id,
    )
    if not r:
        raise HTTPException(404, "项目不在回收站")
    return {"ok": True, "id": project_id}


@router.delete("/{project_id}/purge")
async def purge_project(project_id: int, user: dict = Depends(current_user)):
    """彻底删除项目：物理 DELETE，级联清除目录/正文/要素/任务/资料等全部关联（不可恢复）。
    仅允许删除已在回收站的项目，防止误删在用项目。"""
    await _ensure_owner_or_admin(get_pool(), project_id, user)
    r = await get_pool().fetchrow(
        "DELETE FROM content_projects WHERE id=$1 AND deleted_at IS NOT NULL RETURNING id", project_id,
    )
    if not r:
        raise HTTPException(404, "项目不在回收站（请先移入回收站再彻底删除）")
    return {"ok": True, "id": project_id}


@router.get("/{project_id}")
async def get_project(project_id: int, user: dict = Depends(current_user)):
    await _ensure_owner_or_admin(get_pool(), project_id, user)
    r = await get_pool().fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
    if not r:
        raise HTTPException(404, "项目不存在")
    d = dict(r)
    d["config"] = _jsonb(d["config"])
    agents = await get_pool().fetch(
        "SELECT code, name, role, charter FROM agents WHERE project_id=$1 ORDER BY id", project_id
    )
    d["employees"] = [dict(a) for a in agents]
    return d


class ProjectPatch(BaseModel):
    """引导式新建/基本信息编辑：按需更新，均可空（跳过=不改）。"""
    title: str | None = None
    synopsis: str | None = None
    writing_style: str | None = None
    art_style: str | None = None
    storyline: str | None = None
    project_type: str | None = None
    outline_md: str | None = None  # 大纲手动改稿：只覆盖文本，不触发 AI 重新生成


@router.patch("/{project_id}")
async def update_project(project_id: int, body: ProjectPatch):
    """更新项目基本信息（书名/梗概/文风/画风/主线/大纲）——引导式新建各步保存 + 大纲手动改稿落此。"""
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        r = await get_pool().fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
        if not r:
            raise HTTPException(404, "项目不存在")
        return {**dict(r), "config": _jsonb(r["config"])}
    cols = ", ".join(f"{k}=${i}" for i, k in enumerate(fields, start=2))
    r = await get_pool().fetchrow(
        f"UPDATE content_projects SET {cols}, updated_at=now() WHERE id=$1 RETURNING *",
        project_id, *fields.values(),
    )
    if not r:
        raise HTTPException(404, "项目不存在")
    return {**dict(r), "config": _jsonb(r["config"])}


@router.post("/{project_id}/gen-info")
async def ensure_project_info(project_id: int):
    """补拟基本信息+大纲（后台任务链 gen_project_info→gen_outline_md，幂等去重）：
    总览页发现缺大纲时自动调用；老项目/创建时入队失败的兜底入口。"""
    if not await get_pool().fetchval("SELECT 1 FROM content_projects WHERE id=$1", project_id):
        raise HTTPException(404, "项目不存在")
    return await flow.enqueue(get_pool(), kind="gen_project_info", project_id=project_id)


@router.post("/{project_id}/element-kinds")
async def gen_element_kinds(project_id: int):
    """AI 按剧情判定项目要素类型（后台任务，写 config.element_kinds，幂等去重）：
    核心要素页发现缺类型时自动调用；大纲任务完成后也会自动链发。"""
    if not await get_pool().fetchval("SELECT 1 FROM content_projects WHERE id=$1", project_id):
        raise HTTPException(404, "项目不存在")
    return await flow.enqueue(get_pool(), kind="gen_element_kinds", project_id=project_id)


class VoiceDesignIn(BaseModel):
    instruction: str | None = Field(default=None, description="可选简单指令，如'再冷一点/像老船长'；空=按性格自主设计")


@router.post("/{project_id}/elements/{element_id}/voice")
async def design_element_voice(project_id: int, element_id: int, body: VoiceDesignIn | None = None):
    """捏音色：为角色设计并绑定专属音色（库有契合则复用，否则新建项目级音色）。"""
    from ..services import voice_casting

    try:
        return await voice_casting.design_voice(
            get_pool(), project_id, element_id, body.instruction if body else None
        )
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/{project_id}/voices/cast")
async def cast_all_voices(project_id: int):
    """批量选角：为所有未绑定音色的角色自动捏音色（按性格自主设计）。"""
    from ..services import voice_casting

    rows = await get_pool().fetch(
        "SELECT id, name, meta FROM content_elements WHERE project_id=$1 AND kind='character'", project_id
    )
    out = []
    for r in rows:
        meta = _jsonb(r["meta"])
        if meta.get("voice"):
            continue
        try:
            res = await voice_casting.design_voice(get_pool(), project_id, r["id"], None)
            out.append({"element": r["name"], **res["binding"], "reused": res["reused"]})
        except Exception as e:  # noqa: BLE001 — 单角色失败不阻塞批量
            out.append({"element": r["name"], "error": str(e)[:120]})
    return {"cast": out}


@router.post("/{project_id}/elements/annotate-voices")
async def annotate_voice_profiles(project_id: int):
    """存量补标注：为缺 voice_profile 的角色批量判定发声形态（vocal_mode/language/timbre_brief）。幂等。"""
    from ..services import voice_casting

    return await voice_casting.annotate_voice_profiles(get_pool(), project_id)


class ConfigIn(BaseModel):
    config: dict[str, Any] = Field(description="要合并进 config 的键值（如 aspect_ratio: 16:9 / 9:16）")


@router.patch("/{project_id}/config")
async def update_config(project_id: int, body: ConfigIn):
    """合并更新项目 config（画幅比例等轻引用；视频生成与工作台预览按此执行）。"""
    r = await get_pool().fetchrow(
        "UPDATE content_projects SET config = config || $2::jsonb, updated_at=now() "
        "WHERE id=$1 RETURNING config",
        project_id, json.dumps(body.config, ensure_ascii=False),
    )
    if not r:
        raise HTTPException(404, "项目不存在")
    # Keep the normalized column in sync so agent runtime can route skills even
    # when the overview editor persists the type through the config endpoint.
    project_type = str(body.config.get("project_type") or "").strip()
    if not project_type and isinstance(body.config.get("tags"), list):
        project_type = await get_pool().fetchval(
            "SELECT t.code FROM tags t JOIN tag_groups g ON g.id=t.group_id "
            "WHERE g.code='video_type' AND t.code = ANY($1::text[]) ORDER BY t.seq,t.id LIMIT 1",
            [str(t).strip() for t in body.config["tags"] if str(t).strip()]) or "novel_comic"
    if project_type:
        await get_pool().execute(
            "UPDATE content_projects SET project_type=$2, updated_at=now() WHERE id=$1",
            project_id, project_type,
        )
    return {"config": _jsonb(r["config"])}


class CoverRef(BaseModel):
    name: str
    kind: str = "asset"
    url: str


class CoverIn(BaseModel):
    prompt: str | None = Field(default=None, description="留空=简介+画风提示词自动拼接")
    refs: list[CoverRef] | None = Field(default=None, description="手选参考图（喂给出图模型）")


class ProjectVisualIn(BaseModel):
    prompt: str | None = None
    refs: list[CoverRef] | None = None


@router.get("/{project_id}/visual-assets")
async def list_project_visual_assets(project_id: int):
    from ..services.project_visual_assets import list_assets

    return await list_assets(get_pool(), project_id)


@router.post("/{project_id}/visual-assets/{asset_role}")
async def generate_project_visual_asset(
    project_id: int, asset_role: str, body: ProjectVisualIn | None = None,
):
    """生成一版项目视觉锚点；每次新增版本和附件，绝不覆盖历史。"""
    from ..services.project_visual_assets import generate

    try:
        return await generate(
            get_pool(), project_id, asset_role,
            prompt=body.prompt if body else None,
            reference_urls=(
                [r.url for r in body.refs if r.url]
                if body is not None and body.refs is not None else None
            ),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, str(e)[:300])


@router.post("/{project_id}/cover")
async def generate_cover(project_id: int, body: CoverIn | None = None):
    """生成项目封面：小说简介 + 所选画风提示词渲染，按项目画幅比例出图，存 OSS 记入 config.cover_url。"""
    from .. import media

    r = await get_pool().fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
    if not r:
        raise HTTPException(404, "项目不存在")
    from ..services import prompt_fields as pf

    cfg = _jsonb(r["config"])
    # ARK Seedream 4.x 面积硬约束 ≥3686400 像素：2560x1440 / 1440x2560 恰好达标
    size = "1440x2560" if cfg.get("aspect_ratio") == "9:16" else "2560x1440"
    prompt = (body.prompt or "").strip() if body else ""
    cover_user, cover_anchor = "", ""
    _seg = pf.split_edit_text(prompt) if prompt else None
    if _seg:  # 弹框双段编辑：拆段留存，提交剥分隔线
        cover_user, cover_anchor = _seg
        prompt = pf.compose(cover_user, cover_anchor)
    if not prompt:
        # 画风锚词单一实现见 knowledge.style_anchor（封面/关键视觉/预告片共用）
        pos = await style_anchor(get_pool(), r["art_style"] or "")
        # 措辞风格中立（2026-07-14）："封面插画"会把写实/电影感画风拉向插画质感——
        # 质感一律交给画风正向词决定。双字段：user=剧情叙事，anchor=封面版式+禁文字+画风锚词
        cover_user = r["synopsis"] or ""
        cover_anchor = f"封面画面，完整单幅，构图饱满，no text, no watermark。{pos}"
        prompt = pf.compose(cover_user, cover_anchor)
    # 手选参考图：入参 refs=全量池（含停用，持久化）；按 config.cover_ref_off 过滤出启用项喂给出图模型
    off = set(cfg.get("cover_ref_off") or [])
    pool = [rf.model_dump() for rf in body.refs] if (body and body.refs is not None) \
        else list(cfg.get("cover_refs") or [])
    ref_urls = [rf["url"] for rf in pool if rf.get("url") and rf.get("name") not in off][:4]
    token = media.GEN_AUDIT.set({"project_id": project_id, "kind": "gen_cover",
                                 "source": f"project_{project_id}_cover"})
    try:
        url = await media.generate_image(
            prompt, size=size, reference_images=ref_urls or None, store_prefix="covers")
    except Exception as e:  # noqa: BLE001 — 供应商错误透传（欠费/审核等）
        raise HTTPException(502, str(e)[:300])
    finally:
        media.GEN_AUDIT.reset(token)
    # 参考图+提示词都落库（config）：下次打开保留上次编辑，参考图池持久（含停用项）；
    # 双字段留存（有分段才写，整段直传保持旧形态）
    patch = {"cover_url": url, "cover_prompt": prompt, "cover_refs": pool,
             **({"cover_prompt_user": cover_user, "cover_prompt_anchor": cover_anchor}
                if (cover_user or cover_anchor) else {})}
    await get_pool().execute(
        "UPDATE content_projects SET config = config || $2::jsonb, updated_at=now() WHERE id=$1",
        project_id, json.dumps(patch, ensure_ascii=False),
    )
    return {"cover_url": url, "prompt": prompt}


class CoverAiEditIn(BaseModel):
    instruction: str            # 修改要求（空=按简介+画风重写）
    prompt: str | None = None   # 编辑框当前内容（可能未保存）


@router.post("/{project_id}/cover/prompt/ai-edit")
async def ai_edit_cover_prompt(project_id: int, body: CoverAiEditIn):
    """AI 按要求改写封面提示词（同步返回，不落库——前端回填编辑框，确认后再生成）。
    以小说简介 + 画风为事实边界；instruction 为空=按简介与画风重写一版。"""
    r = await get_pool().fetchrow(
        "SELECT synopsis, art_style FROM content_projects WHERE id=$1", project_id)
    if not r:
        raise HTTPException(404, "项目不存在")
    cur = (body.prompt or "").strip()
    system = (
        "你是封面插画生图提示词工程师。生成/修改小说封面的生图提示词，只输出最终提示词本身，"
        "不要任何解释或前后缀。硬约束：①以下方小说简介与画风为事实依据，画面须贴合故事内核；"
        "②保留封面属性（完整单幅、构图饱满、no text/no watermark）与画风锚词；③中文为主。"
    )
    user = (
        f"【小说简介】{r['synopsis'] or '（无）'}\n【画风】{r['art_style'] or '（未指定）'}\n\n"
        f"【当前封面提示词】\n{cur or '（尚无，请新写一版）'}"
        + (f"\n\n【修改要求】\n{body.instruction.strip()}" if body.instruction.strip()
           else "\n\n【要求】按简介与画风重新写一版更贴合的封面提示词。")
    )
    try:
        out = (await llm.chat_text(system, user, temperature=0.5)).strip()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"AI 修改失败：{e}")
    if not out:
        raise HTTPException(502, "AI 返回为空，请重试")
    return {"prompt": out}


@router.post("/{project_id}/cover/key-visual")
async def gen_cover_key_visual(project_id: int):
    """蒸馏封面「海报级关键视觉」：LLM 据梗概/主线/主角提炼一句剧情专属画面（主角+环境+氛围），
    再拼画风 positive 锚词（场景中性）。不落库——前端回填编辑框，可再改再生成。
    治"整段梗概硬灌 + 画风 content 烤死场景 → 每张封面都一样、不贴剧情"。"""
    r = await get_pool().fetchrow(
        "SELECT title, synopsis, storyline, art_style FROM content_projects WHERE id=$1", project_id)
    if not r:
        raise HTTPException(404, "项目不存在")
    # 主要角色（前若干个）带进去，让海报前景主角贴合本作而非泛泛人物
    chars = await get_pool().fetch(
        "SELECT name, brief FROM content_elements WHERE project_id=$1 AND kind='character' "
        "ORDER BY id LIMIT 5", project_id)
    char_lines = "；".join(roster_inline(c["name"], c["brief"]) for c in chars) or "（未建）"
    system = (
        "你是电影海报视觉总监。据小说【梗概】【主线】【主要角色】，提炼一张封面海报的关键视觉画面。要求：\n"
        "① 只描述画面内容：前景主角（可辨的外形/神态）+ 与之呼应的标志性环境/世界 + 氛围与光色；\n"
        "② 要能『一图代表全书』且专属本故事——出现本作特有的意象/元素，不是泛泛的风景或人物站立；\n"
        "③ 绝不写画风/媒介/渲染/镜头/相机术语（动画/3D/写实/景别/焦段/光圈等一律不写，那些交给画风锚词）；\n"
        "④ 不写文字/字幕/分镜；40-90 字中文。只输出这段画面描述本身，不要解释或前后缀。"
    )
    user = (
        f"【标题】{r['title']}\n【梗概】{r['synopsis'] or '（无）'}\n"
        f"【主线】{r['storyline'] or '（无）'}\n【主要角色】{char_lines}\n\n"
        "请给出这本书封面海报的关键视觉画面。"
    )
    try:
        key_visual = (await llm.chat_text(system, user, temperature=0.6)).strip()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"关键视觉生成失败：{e}")
    if not key_visual:
        raise HTTPException(502, "AI 返回为空，请重试")
    # 画风锚词单一实现见 knowledge.style_anchor（封面/关键视觉/预告片共用）
    pos = await style_anchor(get_pool(), r["art_style"] or "")
    prompt = (f"{key_visual}。电影海报级关键视觉，前景主角突出、身后场景呼应，完整单幅，构图饱满，"
              f"画面中禁止任何文字、字幕、标题与水印，no text, no watermark。{pos}")
    return {"prompt": prompt, "key_visual": key_visual}


class TrailerPromptIn(BaseModel):
    instruction: str | None = None   # 修改要求；空=蒸馏一版全新提示词
    prompt: str | None = None        # 编辑框当前内容（配合 instruction 做 AI 改写）


@router.post("/{project_id}/trailer/prompt")
async def gen_trailer_prompt(project_id: int, body: TrailerPromptIn | None = None):
    """先导预告片提示词：无 instruction=蒸馏全剧 5 节点（开端→结局硬切蒙太奇）并附默认参考图
    （已有设定图的主要角色）；有 instruction=按要求 AI 改写当前提示词。均不落库——
    前端回填编辑框，保存/生成时经 config.trailer_* 持久化。"""
    from ..services import trailer

    r = await get_pool().fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
    if not r:
        raise HTTPException(404, "项目不存在")
    instruction = (body.instruction or "").strip() if body else ""
    try:
        if instruction:
            prompt = await trailer.rewrite_prompt(r, instruction, (body.prompt or "").strip())
            return {"prompt": prompt, "refs": None}
        return await trailer.distill_prompt(get_pool(), r)
    except Exception as e:  # noqa: BLE001 — LLM 错误透传
        raise HTTPException(502, f"预告片提示词生成失败：{str(e)[:300]}")


class TrailerIn(BaseModel):
    prompt: str
    refs: list[CoverRef] | None = None  # 启用中的参考图（角色设定图等，喂给 Seedance）


@router.post("/{project_id}/trailer")
async def generate_trailer(project_id: int, body: TrailerIn):
    """生成先导预告片：15s 硬切蒙太奇（Seedance 同步等待，走素材视频同一收割链路），
    OSS 转存后写 config.trailer_url/trailer_prompt + 附件（kind=video, meta.type=trailer，
    素材库可见）+ gen_logs（kind=gen_trailer）。参考图经 media 层原链路（Active 角色换 asset://）。"""
    from .. import media
    from ..services import asset_gen, trailer

    r = await get_pool().fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
    if not r:
        raise HTTPException(404, "项目不存在")
    prompt = (body.prompt or "").strip()
    if not prompt:
        raise HTTPException(400, "请填写提示词")
    refs = [{"name": rf.name, "kind": rf.kind, "url": rf.url} for rf in (body.refs or []) if rf.url]
    ratio = "9:16" if _jsonb(r["config"]).get("aspect_ratio") == "9:16" else "16:9"
    token = media.GEN_AUDIT.set({"project_id": project_id, "kind": "gen_trailer",
                                 "source": f"project_{project_id}_trailer"})
    try:
        out = await asset_gen.generate_video_asset(
            get_pool(), project_id, prompt, refs, ratio=ratio, duration=trailer.TOTAL_S,
            store_dir="trailer", meta_type="trailer", display_name="先导预告片")
    except Exception as e:  # noqa: BLE001 — 供应商错误透传（审核/欠费等）
        raise HTTPException(502, str(e)[:300])
    finally:
        media.GEN_AUDIT.reset(token)
    await get_pool().execute(
        "UPDATE content_projects SET config = config || $2::jsonb, updated_at=now() WHERE id=$1",
        project_id, json.dumps({"trailer_url": out["url"], "trailer_prompt": prompt},
                               ensure_ascii=False))
    return {"trailer_url": out["url"], "prompt": prompt}


@router.post("/{project_id}/outline-md")
async def regenerate_outline_md(project_id: int):
    """重新生成长篇架构大纲（Markdown 全文），落库并返回。"""
    r = await get_pool().fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
    if not r:
        raise HTTPException(404, "项目不存在")
    d = dict(r)
    d["config"] = _jsonb(d["config"])
    try:
        review = await pipeline.gen_outline_md_with_review(d)
        md = review.pop("revised_markdown")
    except Exception as e:  # noqa: BLE001 — 供应商错误透传（欠费/审核等）
        raise HTTPException(502, str(e)[:300])
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            await pipeline.archive_outline_version(
                conn, project_id, d.get("outline_md"), reason="sync_regenerate")
            await conn.execute(
                "UPDATE content_projects SET outline_md=$2, config=config || $3::jsonb, "
                "updated_at=now() WHERE id=$1",
                project_id, md,
                json.dumps({"outline_content_review": review}, ensure_ascii=False))
    return {"outline_md": md, "content_review": review}


@router.post("/{project_id}/outline-md/task")
async def regenerate_outline_md_task(project_id: int):
    """后台重新生成并质检架构大纲，旧稿在任务成功前保持不变。"""
    exists = await get_pool().fetchval(
        "SELECT EXISTS(SELECT 1 FROM content_projects WHERE id=$1)", project_id)
    if not exists:
        raise HTTPException(404, "项目不存在")
    return await flow.enqueue(
        get_pool(), kind="gen_outline_md", project_id=project_id,
        payload={"trigger": "manual_regenerate", "content_stage": "development"},
    )


@router.post("/{project_id}/outline-md/stream")
async def regenerate_outline_md_stream(project_id: int):
    """流式重新生成架构大纲：逐 token 推送文本增量（前端边生成边显示，长输出不再撞网关超时）；
    流完整结束后清洗落库（中途断流不落库，库内保留旧稿）。"""
    r = await get_pool().fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
    if not r:
        raise HTTPException(404, "项目不存在")
    d = dict(r)
    d["config"] = _jsonb(d["config"])

    async def gen():
        chunks: list[str] = []
        try:
            async for delta in pipeline.gen_outline_md_stream(d):
                chunks.append(delta)
                yield delta
        except Exception as e:  # noqa: BLE001 — 流中报错：以标记行透传给前端，不落库
            yield f"\n\n【生成失败】{str(e)[:200]}"
            return
        md = pipeline.clean_outline_md("".join(chunks))
        if md:
            review = await pipeline.review_outline_development(d, md)
            md = review.pop("revised_markdown")
            async with get_pool().acquire() as conn:
                async with conn.transaction():
                    await pipeline.archive_outline_version(
                        conn, project_id, d.get("outline_md"), reason="stream_regenerate")
                    await conn.execute(
                        "UPDATE content_projects SET outline_md=$2, config=config || $3::jsonb, "
                        "updated_at=now() WHERE id=$1",
                        project_id, md,
                        json.dumps({"outline_content_review": review}, ensure_ascii=False))

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class OutlineIn(BaseModel):
    count: int = Field(ge=1, le=200, description="需要多少章")


@router.post("/{project_id}/outline")
async def build_outline(project_id: int, body: OutlineIn):
    """生成目录：每章带故事线流水账（可先问用户要多少章）。"""
    try:
        return await pipeline.build_outline(get_pool(), project_id, body.count)
    except ValueError as e:
        raise HTTPException(404, str(e))


class AppendIn(BaseModel):
    requirement: str = ""  # 续写要求：如"续写10章"/"让XX复活"；空则续写1章。章数由模型按要求判断


@router.post("/{project_id}/outline/append")
async def append_chapters(project_id: int, body: AppendIn | None = None):
    """新增（续写）章节：按续写要求紧接目录末尾生成 1..N 章并落库。"""
    try:
        return await pipeline.append_chapters(
            get_pool(), project_id, (body.requirement if body else "") or "")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{project_id}/outline/append/stream")
async def append_chapters_stream(project_id: int, body: AppendIn | None = None):
    """流式新增章节（NDJSON）：LLM 按固定 MD 逐章输出，后端解析到一章立即落库并推一行
    {"chapter": {...}}（尚无目录时生成整本初始目录，同样逐章推送）；崩坏/零产出自动回退一次性 JSON。"""
    requirement = (body.requirement if body else "") or ""

    async def runner(emit: Callable[[dict[str, Any]], Awaitable[None]]) -> list[Any]:
        return await pipeline_stream.stream_append_chapters(
            get_pool(), project_id, requirement, lambda c: emit({"chapter": c}))

    return _stream_ndjson(runner)


@router.get("/{project_id}/outline")
async def get_outline(project_id: int):
    rows = await get_pool().fetch(
        "SELECT id, seq, title, summary, status, parent_id FROM content_nodes "
        "WHERE project_id=$1 AND kind='chapter' ORDER BY seq", project_id,
    )
    return [dict(r) for r in rows]


@router.delete("/{project_id}/chapters/{node_id}")
async def delete_chapter(project_id: int, node_id: int):
    """删除一集及其正文、分镜、附件和出现索引。仅允许删除本项目的 chapter 节点。"""
    r = await get_pool().fetchrow(
        "DELETE FROM content_nodes WHERE id=$1 AND project_id=$2 AND kind='chapter' "
        "RETURNING id, seq", node_id, project_id)
    if not r:
        raise HTTPException(404, "剧集不存在")
    return {"ok": True, "id": r["id"], "seq": r["seq"]}


# ═══════════ 卷（分卷分组）═══════════
# 卷=content_nodes(kind='volume')，章节 parent_id 指向所属卷；卷可覆盖项目的
# 画风/文风/画幅比例/要素类型（存 meta，空=继承项目），核心要素仍项目级跨卷共享。

@router.get("/{project_id}/volumes")
async def list_volumes(project_id: int):
    """卷列表（按卷序）：返回每卷 id/seq/标题、覆盖项（去空，未覆盖=继承项目）、章节数。"""
    rows = await get_pool().fetch(
        """SELECT v.id, v.seq, v.title, v.meta,
                  (SELECT count(*) FROM content_nodes c
                    WHERE c.parent_id=v.id AND c.kind='chapter') AS chapter_count
           FROM content_nodes v
           WHERE v.project_id=$1 AND v.kind='volume' ORDER BY v.seq, v.id""",
        project_id,
    )
    return [
        {"id": r["id"], "seq": r["seq"], "title": r["title"],
         "chapter_count": r["chapter_count"], "overrides": volumes.clean_overrides(_jsonb(r["meta"]))}
        for r in rows
    ]


class VolumeCreate(BaseModel):
    title: str | None = None  # 空=按卷序自动命名「第N卷」


async def _insert_volume(conn: Any, project_id: int, seq: int, title: str) -> Any:
    return await conn.fetchrow(
        "INSERT INTO content_nodes (project_id, kind, seq, title) "
        "VALUES ($1,'volume',$2,$3) RETURNING id, seq, title",
        project_id, seq, title,
    )


@router.post("/{project_id}/volumes")
async def create_volume(project_id: int, body: VolumeCreate | None = None):
    """新建卷（追加到末尾），返回新卷。首次建卷=正式进入「分卷」形态：
    先把既有散章（隐式卷1）收编为真实『第一卷』，再追加本次的新卷（默认「第二卷」）。
    此后新章节续写默认落到最后一卷。"""
    if not await get_pool().fetchval("SELECT 1 FROM content_projects WHERE id=$1", project_id):
        raise HTTPException(404, "项目不存在")
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            n = await conn.fetchval(
                "SELECT count(*) FROM content_nodes WHERE project_id=$1 AND kind='volume'", project_id)
            if n == 0:
                # 首次建卷：既有散章收编为『第一卷』（parent_id NULL → 第一卷 id）
                first = await _insert_volume(conn, project_id, 1, volumes.cn_ordinal(1))
                await conn.execute(
                    "UPDATE content_nodes SET parent_id=$2, updated_at=now() "
                    "WHERE project_id=$1 AND kind='chapter' AND parent_id IS NULL",
                    project_id, first["id"],
                )
                seq = 2
            else:
                seq = (await conn.fetchval(
                    "SELECT max(seq) FROM content_nodes WHERE project_id=$1 AND kind='volume'",
                    project_id) or 0) + 1
            title = (body.title.strip() if body and body.title else "") or volumes.cn_ordinal(seq)
            r = await _insert_volume(conn, project_id, seq, title)
    return {**dict(r), "chapter_count": 0, "overrides": {}}


class VolumePatch(BaseModel):
    """改卷：只更新提供的字段。覆盖项传空串/空数组=清除该覆盖（回到继承项目）。"""
    title: str | None = None
    art_style: str | None = None
    writing_style: str | None = None
    aspect_ratio: str | None = None
    element_kinds: list[dict[str, Any]] | None = None


@router.patch("/{project_id}/volumes/{volume_id}")
async def update_volume(project_id: int, volume_id: int, body: VolumePatch):
    """改卷标题与覆盖项（画风/文风/画幅比例/要素类型）。覆盖项合并进 meta，空值即清除覆盖。"""
    row = await get_pool().fetchrow(
        "SELECT id FROM content_nodes WHERE id=$1 AND project_id=$2 AND kind='volume'",
        volume_id, project_id,
    )
    if not row:
        raise HTTPException(404, "卷不存在")
    patch = body.model_dump(exclude_unset=True)
    meta_upd = {k: patch[k] for k in ("art_style", "writing_style", "aspect_ratio", "element_kinds")
                if k in patch}
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            if "title" in patch and patch["title"] is not None:
                await conn.execute(
                    "UPDATE content_nodes SET title=$2, updated_at=now() WHERE id=$1",
                    volume_id, patch["title"].strip() or "未命名卷",
                )
            if meta_upd:
                await conn.execute(
                    "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
                    volume_id, json.dumps(meta_upd, ensure_ascii=False),
                )
            r = await conn.fetchrow(
                """SELECT v.id, v.seq, v.title, v.meta,
                          (SELECT count(*) FROM content_nodes c
                            WHERE c.parent_id=v.id AND c.kind='chapter') AS chapter_count
                   FROM content_nodes v WHERE v.id=$1""", volume_id)
    return {"id": r["id"], "seq": r["seq"], "title": r["title"],
            "chapter_count": r["chapter_count"], "overrides": volumes.clean_overrides(_jsonb(r["meta"]))}


@router.delete("/{project_id}/volumes/{volume_id}")
async def delete_volume(project_id: int, volume_id: int):
    """删卷：把旗下章节并入相邻卷（优先前一卷，否则后一卷）后删除本卷。
    删的是最后一个卷时，章节回落为「无卷」（隐式卷1，目录恢复平铺）。章节及正文/分镜全部保留。"""
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            vol = await conn.fetchrow(
                "SELECT id, seq FROM content_nodes WHERE id=$1 AND project_id=$2 AND kind='volume'",
                volume_id, project_id,
            )
            if not vol:
                raise HTTPException(404, "卷不存在")
            # 相邻卷（优先前一卷，否则后一卷）；已是唯一卷则 None=章节回落无卷（平铺）
            target = await conn.fetchval(
                "SELECT id FROM content_nodes WHERE project_id=$1 AND kind='volume' AND id<>$2 "
                "ORDER BY (seq > $3), abs(seq - $3), seq LIMIT 1",
                project_id, volume_id, vol["seq"],
            )
            # 章节先改嫁/回落（parent_id ON DELETE CASCADE：不先搬走，删卷会连章节一起删）
            moved = await conn.fetchval(
                "WITH m AS (UPDATE content_nodes SET parent_id=$2, updated_at=now() "
                "WHERE parent_id=$1 AND kind='chapter' RETURNING 1) SELECT count(*) FROM m",
                volume_id, target,
            )
            await conn.execute("DELETE FROM content_nodes WHERE id=$1", volume_id)
    return {"ok": True, "id": volume_id, "moved_chapters": moved, "into_volume": target}


class MoveChapterIn(BaseModel):
    volume_id: int


@router.post("/{project_id}/chapters/{node_id}/move")
async def move_chapter(project_id: int, node_id: int, body: MoveChapterIn):
    """把章节移动到指定卷（分组管理）。章节的 seq（第N集）不变，仅改归属卷。"""
    vol = await get_pool().fetchval(
        "SELECT 1 FROM content_nodes WHERE id=$1 AND project_id=$2 AND kind='volume'",
        body.volume_id, project_id,
    )
    if not vol:
        raise HTTPException(404, "目标卷不存在")
    r = await get_pool().fetchrow(
        "UPDATE content_nodes SET parent_id=$3, updated_at=now() "
        "WHERE id=$1 AND project_id=$2 AND kind='chapter' RETURNING id",
        node_id, project_id, body.volume_id,
    )
    if not r:
        raise HTTPException(404, "章节不存在")
    return {"ok": True, "id": node_id, "volume_id": body.volume_id}


@router.post("/{project_id}/elements")
async def build_elements(project_id: int):
    """生成核心要素（角色/场景/阴谋线/冲突线/伏笔）+ 出现索引预填。"""
    try:
        return await pipeline.build_elements(get_pool(), project_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{project_id}/elements")
async def get_elements(project_id: int):
    rows = await get_pool().fetch(
        """SELECT e.id, e.kind, e.name, e.brief, e.state, e.meta,
                  COALESCE(array_agg(n.seq ORDER BY n.seq) FILTER (WHERE n.seq IS NOT NULL), '{}') AS appears_in
           FROM content_elements e
           LEFT JOIN element_appearances ea ON ea.element_id = e.id
           LEFT JOIN content_nodes n ON n.id = ea.node_id
           WHERE e.project_id=$1
           GROUP BY e.id ORDER BY e.kind, e.id""",
        project_id,
    )
    return [
        {**dict(r), "state": _jsonb(r["state"]), "meta": _jsonb(r["meta"]),
         "appears_in": list(r["appears_in"])}
        for r in rows
    ]


class ElementIn(BaseModel):
    kind: str = "setting"  # character/scene/plotline/conflict/foreshadow/setting
    name: str
    brief: str = ""


@router.post("/{project_id}/elements/add")
async def add_element(project_id: int, body: ElementIn):
    """手动新增单个核心要素（用户输入 kind/name/brief）。
    落库走唯一实现 services/elements.upsert_element（端点老语义=brief 全覆盖）。"""
    try:
        d = await elements_service.upsert_element(
            get_pool(), project_id=project_id, kind=body.kind, name=body.name,
            brief=body.brief, overwrite_brief=True)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": d["id"], "kind": d["kind"], "name": d["name"], "brief": d["brief"],
            "state": d["state"], "meta": d["meta"], "appears_in": []}


class ElementsGenIn(BaseModel):
    requirement: str = ""


@router.post("/{project_id}/elements/add_ai")
async def add_elements_ai(project_id: int, body: ElementsGenIn):
    """按自由文本要求 AI 新增核心要素（生成一个还是多个由模型按要求判断；留空=依目录重建全部）。"""
    try:
        return await pipeline.add_elements_ai(get_pool(), project_id, body.requirement)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{project_id}/elements/add_ai/stream")
async def add_elements_ai_stream(project_id: int, body: ElementsGenIn):
    """流式生成核心要素（NDJSON）：LLM 按固定 MD 逐个要素输出，后端解析到一个立即落库并推一行
    {"element": {...}}；要求留空=依目录全量抽取（无目录先流式建目录，章节以 {"chapter": {...}} 推送）；
    崩坏/零产出自动回退一次性 JSON。"""

    async def runner(emit: Callable[[dict[str, Any]], Awaitable[None]]) -> list[Any]:
        return await pipeline_stream.stream_elements(
            get_pool(), project_id, body.requirement,
            lambda c: emit({"chapter": c}), lambda e: emit({"element": e}))

    return _stream_ndjson(runner)


class MemoryIn(BaseModel):
    content: str
    agent_code: str | None = None
    kind: str = "soft"


@router.post("/{project_id}/memories")
async def add_memory(project_id: int, body: MemoryIn):
    """项目级用户偏好，如「写作员工用莫言的语言写」(agent_code=writer)。"""
    r = await get_pool().fetchrow(
        "INSERT INTO project_memories (project_id, agent_code, kind, content) "
        "VALUES ($1,$2,$3,$4) RETURNING *",
        project_id, body.agent_code, body.kind, body.content,
    )
    return dict(r)


@router.get("/{project_id}/memories")
async def list_memories(project_id: int):
    rows = await get_pool().fetch(
        "SELECT * FROM project_memories WHERE project_id=$1 ORDER BY id DESC", project_id
    )
    return [dict(r) for r in rows]


# ═══════════ 项目资料（引导式新建·相关材料/原始小说）═══════════
# 项目资料：文件转存 OSS/临时目录后抽取为正文和可分页 chunks，供后续智能体渐进式读取。

def _material_row(r: dict[str, Any]) -> dict[str, Any]:
    meta = _jsonb(r["meta"])
    return {
        "id": r["id"], "title": r["title"], "source": r["source"],
        "url": meta.get("url"), "chars": len(r.get("content") or ""),
        "chunk_count": meta.get("chunk_count"), "processing_status": meta.get("processing_status") or ("processed" if r.get("content") else "pending"),
        "core_excerpt": meta.get("core_excerpt"), "content_type": meta.get("content_type"),
        "created_at": r["created_at"],
    }


@router.get("/{project_id}/materials")
async def list_materials(project_id: int):
    rows = await get_pool().fetch(
        "SELECT m.id, m.title, m.source, m.content, m.meta, m.created_at, "
        "(SELECT count(*) FROM project_material_chunks c WHERE c.material_id=m.id) AS chunk_count "
        "FROM project_materials m "
        "WHERE project_id=$1 ORDER BY id DESC", project_id,
    )
    out = []
    for row in rows:
        item = _material_row(dict(row))
        if item.get("chunk_count") is None:
            item["chunk_count"] = int(row["chunk_count"] or 0)
        out.append(item)
    return out


class MaterialTextIn(BaseModel):
    title: str = ""
    content: str = Field(min_length=1, description="资料原文/构思")


@router.post("/{project_id}/materials")
async def add_material_text(project_id: int, body: MaterialTextIn):
    """文本资料：直接落 project_materials（source=input），不经附件表。"""
    title = (body.title or "").strip() or (body.content.strip().splitlines()[0][:24] or "文本资料")
    chunks = chunk_text(body.content)
    async with get_pool().acquire() as conn:
      async with conn.transaction():
        r = await conn.fetchrow(
        "INSERT INTO project_materials (project_id, title, source, content) "
        "VALUES ($1,$2,'input',$3) RETURNING id, title, source, content, meta, created_at",
        project_id, title, body.content,
        )
        for c in chunks:
            await conn.execute(
                "INSERT INTO project_material_chunks "
                "(material_id,chunk_index,content,summary,char_start,char_end) VALUES ($1,$2,$3,$4,$5,$6)",
                r["id"], c["index"], c["content"], c["summary"], c["char_start"], c["char_end"],
            )
    out = _material_row(dict(r))
    out.update({"chunk_count": len(chunks), "extracted_chars": len(body.content),
                "core_excerpt": core_excerpt(body.content), "processing_status": "processed"})
    return out


@router.get("/{project_id}/materials/{material_id}/chunks")
async def list_material_chunks(project_id: int, material_id: int, offset: int = 0, limit: int = 20):
    """分页读取资料分段，供渐进式大纲/剧集生成使用。"""
    if limit < 1 or limit > 100:
        raise HTTPException(422, "limit 必须在 1-100 之间")
    material = await get_pool().fetchrow(
        "SELECT id,title,meta FROM project_materials WHERE id=$1 AND project_id=$2", material_id, project_id)
    if not material:
        raise HTTPException(404, "资料不存在")
    rows = await get_pool().fetch(
        "SELECT id,chunk_index,content,summary,char_start,char_end,meta FROM project_material_chunks "
        "WHERE material_id=$1 ORDER BY chunk_index LIMIT $2 OFFSET $3", material_id, limit, max(0, offset))
    total = await get_pool().fetchval("SELECT count(*) FROM project_material_chunks WHERE material_id=$1", material_id)
    return {"material_id": material_id, "title": material["title"], "offset": max(0, offset),
            "limit": limit, "total": int(total or 0), "items": [dict(r) for r in rows]}


class MaterialAnalyzeIn(BaseModel):
    force: bool = False


@router.post("/{project_id}/materials/{material_id}/analyze")
async def analyze_material(project_id: int, material_id: int, body: MaterialAnalyzeIn | None = None):
    """Use the configured LLM to detect an existing outline/episode structure.

    This is intentionally an explicit operation: uploading a large document stays
    fast and deterministic, while the expensive semantic pass can be retried or
    run again after the user replaces a material.
    """
    row = await get_pool().fetchrow(
        "SELECT id,title,content,meta FROM project_materials WHERE id=$1 AND project_id=$2",
        material_id, project_id,
    )
    if not row:
        raise HTTPException(404, "资料不存在")
    meta = _jsonb(row["meta"])
    if not (body and body.force) and isinstance(meta.get("analysis"), dict):
        return {"material_id": material_id, "analysis": meta["analysis"], "cached": True}
    chunks = await get_pool().fetch(
        "SELECT content,summary FROM project_material_chunks WHERE material_id=$1 "
        "ORDER BY chunk_index LIMIT 32", material_id)
    source = "\n\n".join((c["content"] or c["summary"] or "") for c in chunks)
    if not source:
        source = row["content"] or ""
    if not source.strip():
        raise HTTPException(422, "资料没有可解析的文本")
    system = (
        "你是资料结构解析器。只根据输入资料识别其中已经明确写出的故事事实，"
        "不要补写缺失剧情。严格输出 JSON："
        '{"summary":"核心内容摘要","outline_present":true或false,'
        '"outline":"已有大纲原文或空字符串",'
        '"episodes":[{"seq":1,"title":"","summary":""}],'
        '"facts":["明确事实"]}'
    )
    try:
        analysis = await llm.chat_json(system, source[:48000], max_tokens=5000, purpose="material_analysis")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"资料结构解析失败：{str(exc)[:200]}") from exc
    meta.update({"analysis": analysis, "processing_status": "analyzed"})
    await get_pool().execute(
        "UPDATE project_materials SET meta=$2::jsonb WHERE id=$1",
        material_id, json.dumps(meta, ensure_ascii=False),
    )
    return {"material_id": material_id, "analysis": analysis, "cached": False}


@router.post("/{project_id}/materials/upload")
async def upload_material(project_id: int, file: UploadFile = File(...)):
    """上传资料并立即做本地抽取、分段；后续智能体可按 chunk 增量读取。"""
    if not await get_pool().fetchval("SELECT 1 FROM content_projects WHERE id=$1", project_id):
        raise HTTPException(404, "项目不存在")
    data = await file.read()
    name = file.filename or "material"
    ext = Path(name).suffix or ".bin"
    url = await oss.store_bytes(data, prefix=f"materials/{project_id}", ext=ext)
    stage_dir = Path(tempfile.gettempdir()) / "novelcomic-materials" / str(project_id)
    stage_dir.mkdir(parents=True, exist_ok=True)
    stage_path = stage_dir / f"{os.urandom(8).hex()}{ext}"
    stage_path.write_bytes(data)
    text, extractor = extract_text(name, data, file.content_type)
    chunks = chunk_text(text)
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            att = await conn.fetchrow(
                "INSERT INTO content_attachments (project_id, kind, file_path, url, meta) "
                "VALUES ($1,'material',$2,$3,$4::jsonb) RETURNING id",
                project_id, name, url,
                json.dumps({"size": len(data), "content_type": file.content_type}, ensure_ascii=False),
            )
            r = await conn.fetchrow(
                "INSERT INTO project_materials (project_id, title, source, meta) "
                "VALUES ($1,$2,'upload',$3::jsonb) RETURNING id, title, source, content, meta, created_at",
                project_id, name,
                json.dumps({"attachment_id": att["id"], "url": url, "size": len(data),
                            "content_type": file.content_type, "local_path": str(stage_path),
                            "extractor": extractor, "processing_status": "processed",
                            "extracted_chars": len(text), "chunk_count": len(chunks),
                            "core_excerpt": core_excerpt(text)}, ensure_ascii=False),
            )
            if text:
                await conn.execute("UPDATE project_materials SET content=$2 WHERE id=$1", r["id"], text)
            for c in chunks:
                await conn.execute(
                    "INSERT INTO project_material_chunks "
                    "(material_id,chunk_index,content,summary,char_start,char_end,meta) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)",
                    r["id"], c["index"], c["content"], c["summary"], c["char_start"], c["char_end"],
                    json.dumps({"extractor": extractor}, ensure_ascii=False),
                )
    out = _material_row(dict(r))
    out["stored"] = url is not None  # OSS 未配置时 url 为空，仍留档但提示未落 OSS
    out.update({"chars": len(text), "extractor": extractor, "extracted_chars": len(text),
                "chunk_count": len(chunks), "core_excerpt": core_excerpt(text),
                "staging_path": str(stage_path)})
    return out


@router.delete("/{project_id}/materials/{material_id}")
async def delete_material(project_id: int, material_id: int):
    """删除资料；若引用附件则一并删附件表记录。"""
    r = await get_pool().fetchrow(
        "SELECT meta FROM project_materials WHERE id=$1 AND project_id=$2", material_id, project_id,
    )
    if not r:
        raise HTTPException(404, "资料不存在")
    att_id = _jsonb(r["meta"]).get("attachment_id")
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            if att_id:
                await conn.execute("DELETE FROM content_attachments WHERE id=$1", att_id)
            await conn.execute("DELETE FROM project_materials WHERE id=$1", material_id)
    return {"ok": True}


@router.get("/{project_id}/assets")
async def list_assets(project_id: int):
    """项目图片资产清单（公共图片生成弹框·添加参考面板）：
    要素设定图（含无图要素，可作镜级关联）/ 章级宫格故事板 / 各镜首帧 / 封面。"""
    pool = get_pool()
    proj = await pool.fetchrow("SELECT config FROM content_projects WHERE id=$1", project_id)
    if not proj:
        raise HTTPException(404, "项目不存在")
    out: list[dict[str, Any]] = []
    els = await pool.fetch(
        "SELECT id, kind, name, meta FROM content_elements "
        "WHERE project_id=$1 AND kind IN ('character','scene') ORDER BY kind, id", project_id,
    )
    from ..services import element_variants as ev
    for e in els:
        em = _jsonb(e["meta"])
        if ev.has_variants(em):
            for v in ev.variants_of(em):
                label = f"{e['name']}·{v.get('tag')}" if v.get("tag") else e["name"]
                out.append({"group": "要素设定图", "kind": e["kind"], "name": label,
                            "url": v.get("sheet_url"), "element_id": e["id"],
                            "variant_id": v.get("id")})
        else:
            out.append({"group": "要素设定图", "kind": e["kind"], "name": e["name"],
                        "url": em.get("sheet_url"), "element_id": e["id"]})
    chaps = await pool.fetch(
        "SELECT id, seq, meta FROM content_nodes WHERE project_id=$1 AND kind='chapter' ORDER BY seq",
        project_id,
    )
    for c in chaps:
        for b in (_jsonb(c["meta"]).get("storyboard_overview") or {}).get("boards") or []:
            if b.get("url"):
                out.append({"group": "故事板", "kind": "storyboard",
                            "name": f"故事板·第{c['seq']}章第{b['no']}张", "url": b["url"]})
    shots = await pool.fetch(
        "SELECT s.seq, s.meta, c.seq AS chap FROM content_nodes s "
        "JOIN content_nodes c ON c.id = s.parent_id "
        "WHERE c.project_id=$1 AND s.kind='shot' AND s.deleted_at IS NULL ORDER BY c.seq, s.seq",
        project_id,
    )
    for s in shots:
        sm = _jsonb(s["meta"])
        if sm.get("keyframe_url"):
            out.append({"group": "首帧", "kind": "keyframe",
                        "name": f"首帧·第{s['chap']}章镜{sm.get('shot_no') or s['seq']}",
                        "url": sm["keyframe_url"]})
        if sm.get("last_frame_url"):
            out.append({"group": "尾帧", "kind": "lastframe",
                        "name": f"尾帧·第{s['chap']}章镜{sm.get('shot_no') or s['seq']}",
                        "url": sm["last_frame_url"]})
    cover = _jsonb(proj["config"]).get("cover_url")
    if cover:
        out.append({"group": "封面", "kind": "cover", "name": "封面", "url": cover})
    # 手选参考图池（上传/生成的独立参考图，附件表 meta.type=ref）——也可作任意生成的参考
    refs = await pool.fetch(
        "SELECT id, url, meta FROM content_attachments "
        "WHERE project_id=$1 AND kind='image' AND (meta->>'type')='ref' AND url IS NOT NULL "
        "ORDER BY id DESC", project_id)
    for rf in refs:
        rm = _jsonb(rf["meta"])
        out.append({"group": "参考图", "kind": "image",
                    "name": rm.get("name") or f"参考图{rf['id']}", "url": rf["url"]})
    return out


# ── 独立参考图：上传 / 生成 / AI 写提示词（公共图片生成弹框·素材面板）──────────────

@router.post("/{project_id}/assets/upload")
async def upload_asset(project_id: int, file: UploadFile = File(...)):
    """上传一张参考图（素材面板「上传参考图」）：转存 OSS + 落附件表（kind=image, meta.type=ref），返回作参考。"""
    if not await get_pool().fetchval("SELECT 1 FROM content_projects WHERE id=$1", project_id):
        raise HTTPException(404, "项目不存在")
    data = await file.read()
    fname = file.filename or "参考图"
    ext = Path(fname).suffix or ".png"
    url = await oss.store_bytes(data, prefix=f"refs/{project_id}", ext=ext)
    if not url:
        raise HTTPException(502, "OSS 未配置，参考图未能转存")
    att = await get_pool().fetchrow(
        "INSERT INTO content_attachments (project_id, kind, file_path, url, meta) "
        "VALUES ($1,'image',$2,$3,$4::jsonb) RETURNING id",
        project_id, fname, url,
        json.dumps({"type": "ref", "origin": "upload", "name": Path(fname).stem or fname,
                    "size": len(data), "content_type": file.content_type}, ensure_ascii=False))
    return {"id": att["id"], "name": Path(fname).stem or f"参考图{att['id']}", "kind": "image", "url": url}


@router.post("/{project_id}/assets/frame-from-video")
async def asset_frame_from_video(
    project_id: int,
    at_sec: float = Form(...),            # 抽取时间点（秒）——前端 <video> 拖轴/逐帧定位后回传
    video_url: str | None = Form(None),   # 项目任意视频 URL；与 file 二选一
    file: UploadFile | None = File(None),  # 临时上传的视频文件；与 video_url 二选一
):
    """从视频按时间点抽一帧存为项目参考图（素材库「从视频中抽」）：ffmpeg 秒级抽全分辨率帧
    → 转存 OSS → 落附件表（kind=image, meta.type=ref, origin=video_frame），返回作参考。
    视频源为已有 URL（项目任意视频）或临时上传件（抽完即删，不落库）。与 shots 的镜级
    frame-from-video 区别：不绑定某镜首/尾帧，产物入项目参考图池、可被任意生成引用。"""
    if not await get_pool().fetchval("SELECT 1 FROM content_projects WHERE id=$1", project_id):
        raise HTTPException(404, "项目不存在")
    if not (video_url or "").strip() and file is None:
        raise HTTPException(400, "需提供 video_url 或上传 file")
    from ..services.frames import extract_frame

    tmp_path: str | None = None
    try:
        if file is not None:
            import tempfile
            data = await file.read()
            if not data:
                raise HTTPException(400, "上传的视频为空")
            suffix = Path(file.filename or "").suffix or ".mp4"
            tf = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tf.write(data)
            tf.close()
            tmp_path = tf.name
            src = tmp_path
        else:
            src = video_url  # type: ignore[assignment]
        try:
            content = await extract_frame(src, "first", at_sec=max(at_sec, 0.0))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"抽帧失败：{e}")
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
    url = await oss.store_bytes(content, prefix=f"refs/{project_id}", ext=".jpeg")
    if not url:
        raise HTTPException(502, "OSS 未配置，抽帧结果未能转存")
    att = await get_pool().fetchrow(
        "INSERT INTO content_attachments (project_id, kind, url, meta) "
        "VALUES ($1,'image',$2,$3::jsonb) RETURNING id",
        project_id, url,
        json.dumps({"type": "ref", "origin": "video_frame"}, ensure_ascii=False))
    return {"id": att["id"], "name": f"视频帧{att['id']}", "kind": "image", "url": url}


class VideoCoverIn(BaseModel):
    video_url: str
    attachment_id: int | None = None  # 视频附件 id；gen_logs 找回项（无附件）不传


@router.post("/{project_id}/assets/video-cover")
async def gen_video_cover(project_id: int, body: VideoCoverIn):
    """给素材库里没有封面的视频补封面（hover「生成封面」）：ffmpeg 抽首帧 → 转存 OSS。
    有附件的另落一条 video_cover 图片附件、回填视频行 meta.cover_url + cover_attachment_id
    （与 steps.py 生成视频时的自动封面同构）；若所属镜头当前用的就是这条视频，同步补镜头
    meta.video_cover_url 作 <video poster>。找回项（附件已随重拆丢失，仅 gen_logs 留存）
    把 cover_url 并进对应日志的 result，asset-library 读它出缩略。"""
    from ..services.frames import extract_frame

    pool = get_pool()
    if not await pool.fetchval("SELECT 1 FROM content_projects WHERE id=$1", project_id):
        raise HTTPException(404, "项目不存在")
    video_url = (body.video_url or "").strip()
    if not video_url:
        raise HTTPException(400, "缺少 video_url")
    try:
        frame = await extract_frame(video_url, "first")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"抽帧失败：{e}")
    cover = await oss.store_bytes(frame, prefix=f"video_cover/{project_id}", ext=".jpeg")
    if not cover:
        raise HTTPException(502, "OSS 未配置，封面未能转存")
    if body.attachment_id:
        att = await pool.fetchrow(
            "SELECT id, node_id FROM content_attachments "
            "WHERE id=$1 AND project_id=$2 AND kind='video'", body.attachment_id, project_id)
        if not att:
            raise HTTPException(404, "视频附件不存在")
        cover_att_id = await pool.fetchval(
            "INSERT INTO content_attachments (project_id, node_id, kind, url, meta) "
            "VALUES ($1,$2,'image',$3,$4::jsonb) RETURNING id",
            project_id, att["node_id"], cover,
            json.dumps({"type": "video_cover", "from": "video_first_frame"}, ensure_ascii=False))
        await pool.execute(
            "UPDATE content_attachments SET meta = COALESCE(meta,'{}'::jsonb) || $2::jsonb, "
            "cover_attachment_id=$3 WHERE id=$1",
            att["id"], json.dumps({"cover_url": cover}), cover_att_id)
        if att["node_id"]:
            await pool.execute(
                "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() "
                "WHERE id=$1 AND meta->>'video_url' = $3",
                att["node_id"], json.dumps({"video_cover_url": cover}), video_url)
    else:
        await pool.execute(
            "UPDATE gen_logs SET result = result || $2::jsonb "
            "WHERE project_id=$1 AND status='done' AND result->>'video_url' = $3",
            project_id, json.dumps({"cover_url": cover}), video_url)
    return {"cover_url": cover}


class AssetGenIn(BaseModel):
    prompt: str
    refs: list[CoverRef] | None = None  # 子弹框自身挑的参考图（喂给出图模型）
    media: str = "image"        # image=生成图片（默认，兼容旧「生成参考图」）｜video=生成素材视频
    use_project: bool = False   # 参考项目总体设定（年代/世界观/画风锚）——新增素材弹框默认勾选
    use_kb: bool = False        # 采用系统知识构建（画风块+质量词织入）；两开关全关=纯享模式
    duration: int = 5           # 视频时长（秒），仅 media=video 生效


@router.post("/{project_id}/assets/generate")
async def generate_asset(project_id: int, body: AssetGenIn):
    """生成一张独立参考图或一段素材视频（素材面板「生成参考图」/新增素材弹框「生成图片/生成视频」）。

    提示词先按 use_project/use_kb 两开关装配（全关=纯享模式，原样直达大模型，见 services/asset_gen）。
    图片：出图存 OSS + 附件表（meta.type=ref, origin=gen），经 GEN_AUDIT 落 gen_logs，按项目画幅出图。
    视频：同步生成落附件表（kind=video, meta.type=asset）；参考图经 media 层原链路，
    Seedance 2.0 下角色库已 Active 的角色自动换 asset:// 可信素材（纯享模式同样生效）。"""
    from .. import media
    from ..services import asset_gen

    r = await get_pool().fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
    if not r:
        raise HTTPException(404, "项目不存在")
    prompt = (body.prompt or "").strip()
    if not prompt:
        raise HTTPException(400, "请填写提示词")
    prompt = await asset_gen.assemble_asset_prompt(
        get_pool(), r, prompt,
        use_project=body.use_project, use_kb=body.use_kb, media=body.media)
    portrait = _jsonb(r["config"]).get("aspect_ratio") == "9:16"
    if body.media == "video":
        refs = [{"name": rf.name, "kind": rf.kind, "url": rf.url} for rf in (body.refs or []) if rf.url]
        token = media.GEN_AUDIT.set({"project_id": project_id, "kind": "gen_asset_video",
                                     "source": f"project_{project_id}_asset"})
        try:
            return await asset_gen.generate_video_asset(
                get_pool(), project_id, prompt, refs,
                ratio="9:16" if portrait else "16:9", duration=body.duration)
        except Exception as e:  # noqa: BLE001 — 供应商错误透传
            raise HTTPException(502, str(e)[:300])
        finally:
            media.GEN_AUDIT.reset(token)
    # ARK Seedream 4.x 面积硬约束 ≥3686400 像素：2560x1440 / 1440x2560 恰好达标
    size = "1440x2560" if portrait else "2560x1440"
    ref_urls = [rf.url for rf in (body.refs or []) if rf.url][:4]
    token = media.GEN_AUDIT.set({"project_id": project_id, "kind": "gen_ref",
                                 "source": f"project_{project_id}_ref"})
    try:
        url = await media.generate_image(
            prompt, size=size, reference_images=ref_urls or None, store_prefix="refs")
    except Exception as e:  # noqa: BLE001 — 供应商错误透传
        raise HTTPException(502, str(e)[:300])
    finally:
        media.GEN_AUDIT.reset(token)
    att = await get_pool().fetchrow(
        "INSERT INTO content_attachments (project_id, kind, url, meta) "
        "VALUES ($1,'image',$2,$3::jsonb) RETURNING id",
        project_id, url,
        json.dumps({"type": "ref", "origin": "gen", "prompt": prompt}, ensure_ascii=False))
    name = f"参考图{att['id']}"
    return {"id": att["id"], "name": name, "kind": "image", "url": url}


class AssetAiIn(BaseModel):
    instruction: str
    prompt: str | None = None
    media: str = "image"      # image=生图提示词（默认）｜video=视频生成提示词
    use_project: bool = True  # 起草时是否带项目题材/画风（纯享模式下前端传 False）


@router.post("/{project_id}/assets/ai-prompt")
async def ai_prompt_asset(project_id: int, body: AssetAiIn):
    """AI 写/改素材生成提示词（同步返回回填编辑框，不落库）；空指令=新写一版。
    media=video 时按视频提示词口径起草；use_project=False（纯享模式）不带项目题材上下文。"""
    r = await get_pool().fetchrow("SELECT synopsis, art_style FROM content_projects WHERE id=$1", project_id)
    if not r:
        raise HTTPException(404, "项目不存在")
    cur = (body.prompt or "").strip()
    is_video = body.media == "video"
    system = (("你是视频生成提示词工程师。生成/修改一段短视频的生成提示词（画面内容、镜头运动与节奏），"
               "只输出最终提示词本身，不要解释或前后缀。中文为主。") if is_video else
              ("你是图像生成提示词工程师。生成/修改一张参考图的生图提示词，只输出最终提示词本身，"
               "不要解释或前后缀。保留画质/构图必要词，中文为主。"))
    noun = "视频" if is_video else "参考图"
    ctx = (f"【项目题材】{r['synopsis'] or ''}｜画风：{r['art_style'] or ''}\n\n"
           if body.use_project else "")
    user = (f"{ctx}【当前提示词】\n{cur or '（尚无，请新写一版）'}"
            + (f"\n\n【修改要求】\n{body.instruction.strip()}" if body.instruction.strip()
               else f"\n\n【要求】新写一版清晰可用的{noun}提示词。"))
    try:
        out = (await llm.chat_text(system, user, temperature=0.5)).strip()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"AI 生成失败：{e}")
    if not out:
        raise HTTPException(502, "AI 返回为空，请重试")
    return {"prompt": out}


@router.get("/{project_id}/asset-library")
async def asset_library(project_id: int):
    """生成/素材库：项目内全部生成/上传产物（图/视频/音频）+ 封面，分组返回供浏览、用作参考、设为封面。

    除现存附件外，并入 gen_logs 中成功产出（status=done）的历史生成结果——用于找回「重新拆镜后
    镜节点被删、附件随 ON DELETE CASCADE 一并丢失」的首帧/视频：gen_logs 无外键、重拆不删，
    且结果 URL 已 OSS 永久化，是这些资源的唯一留存。按 URL 去重，与现存附件重复的不再重复出。"""
    pool = get_pool()
    proj = await pool.fetchrow("SELECT config FROM content_projects WHERE id=$1", project_id)
    if not proj:
        raise HTTPException(404, "项目不存在")
    rows = await pool.fetch(
        "SELECT a.id, a.kind, a.url, a.meta, a.element_id, e.name AS elem_name, "
        "s.meta AS shot_meta, c.seq AS chap_seq "
        "FROM content_attachments a "
        "LEFT JOIN content_elements e ON e.id = a.element_id "
        "LEFT JOIN content_nodes s ON s.id = a.node_id AND s.kind='shot' "
        "LEFT JOIN content_nodes c ON c.id = s.parent_id "
        "WHERE a.project_id=$1 AND a.url IS NOT NULL AND a.kind <> 'material' "
        "ORDER BY a.created_at DESC, a.id DESC", project_id)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for a in rows:
        m = _jsonb(a["meta"])
        mtype = m.get("type")
        kind = a["kind"]
        if mtype == "video_cover":
            continue  # 视频封面是派生物，已在视频卡上作缩略，单列一张徒增重复
        if kind == "video":
            group, mkind = "视频", "video"
        elif kind == "audio":
            group, mkind = "音频", "audio"
        else:
            group = {"sheet": "要素设定图", "keyframe": "首帧", "last_keyframe": "尾帧",
                     "ref": "参考图"}.get(mtype, "图片")
            mkind = "image"
        if a["elem_name"]:
            name = f"{a['elem_name']}·设定图"
        elif a["shot_meta"]:
            sm = _jsonb(a["shot_meta"])
            cn = f"第{a['chap_seq']}章" if a["chap_seq"] else ""
            name = f"{group}·{cn}镜{sm.get('shot_no') or ''}"
        else:
            name = m.get("name") or f"{group}{a['id']}"
        seen.add(a["url"])
        item = {"id": a["id"], "group": group, "media": mkind, "kind": kind,
                "name": name, "url": a["url"], "recovered": False}
        if mkind == "video" and m.get("cover_url"):
            item["cover_url"] = m["cover_url"]  # 视频封面（首帧），供列表做缩略/poster
        out.append(item)
    # 并入 gen_logs 成功产出但已无对应附件的历史结果（多为重拆丢失的首帧/视频）
    logs = await pool.fetch(
        "SELECT kind, chapter_title, shot_no, result FROM gen_logs "
        "WHERE project_id=$1 AND status='done' AND result IS NOT NULL "
        "ORDER BY created_at DESC, id DESC", project_id)
    _LOG_GROUP = {
        "gen_video": ("视频", "video"), "gen_keyframe": ("首帧", "image"),
        "gen_last_keyframe": ("尾帧", "image"),
        "gen_element_sheet": ("要素设定图", "image"), "gen_ref": ("参考图", "image"),
        "gen_cover": ("封面图", "image")}
    for g in logs:
        r = _jsonb(g["result"])
        url = r.get("video_url") or r.get("image_url")
        if not url or url in seen:
            continue
        seen.add(url)
        group, mkind = _LOG_GROUP.get(
            g["kind"], ("视频", "video") if r.get("video_url") else ("图片", "image"))
        ct = g["chapter_title"] or ""
        name = (f"{group}·{ct}镜{g['shot_no']}" if g["shot_no"]
                else f"{group}·{ct}" if ct else group)
        item = {"id": None, "group": group, "media": mkind, "kind": g["kind"],
                "name": name, "url": url, "recovered": True}
        if mkind == "video" and r.get("cover_url"):
            item["cover_url"] = r["cover_url"]  # 找回项补的封面（gen_video_cover 写回 result）
        out.append(item)
    cover = _jsonb(proj["config"]).get("cover_url")
    if cover:
        out.insert(0, {"id": None, "group": "封面", "media": "image", "kind": "cover",
                       "name": "封面", "url": cover, "recovered": False})
    return out


class ElementPromptIn(BaseModel):
    prompt: str
    variant_id: str | None = None   # 多形态：改哪个形态的外貌提示词；空=主/默认形态


@router.patch("/{project_id}/elements/{element_id}/prompt")
async def save_element_prompt(project_id: int, element_id: int, body: ElementPromptIn):
    """保存要素的生图提示词（前端公共图片生成弹框的存储回调）：
    角色 → meta.外貌提示词（身份锚点，改动后设定图指纹失配自动重生成）；其余（场景等）→ brief。
    多形态角色：写回指定形态的外貌提示词（主形态镜像回顶层）。"""
    from ..services import element_variants as ev

    from ..services import prompt_fields as pf

    row = await get_pool().fetchrow(
        "SELECT kind, meta FROM content_elements WHERE id=$1 AND project_id=$2", element_id, project_id
    )
    if not row:
        raise HTTPException(404, "要素不存在")
    meta = _jsonb(row["meta"])
    # 双字段（2026-07-17）：编辑框含分隔线 → 上段=外貌/描述（源数据），下段=设定图锚定段——
    # 锚定段改动落 meta.sheet_prompt_anchor 并打冻结标记（装配不再刷新它）
    text = (body.prompt or "").strip()
    anchor_patch: dict[str, Any] = {}
    seg = pf.split_edit_text(text)
    if seg:
        text, anchor = seg
        if anchor != (meta.get("sheet_prompt_anchor") or ""):
            anchor_patch = {"sheet_prompt_anchor": anchor, "sheet_prompt_anchor_edited": True}
    if row["kind"] == "character":
        if ev.has_variants(meta):
            variants = [dict(v) for v in ev.variants_of(meta)]
            tgt = next((v for v in variants if v.get("id") == body.variant_id), variants[0])
            tgt["外貌提示词"] = text
            patch = ev.mirror_patch(variants)
        else:
            patch = {"外貌提示词": text}
        await get_pool().execute(
            "UPDATE content_elements SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
            element_id, json.dumps({**patch, **anchor_patch}, ensure_ascii=False),
        )
    else:
        await get_pool().execute(
            "UPDATE content_elements SET brief=$2, updated_at=now() WHERE id=$1", element_id, text
        )
        if anchor_patch:
            await get_pool().execute(
                "UPDATE content_elements SET meta = meta || $2::jsonb WHERE id=$1",
                element_id, json.dumps(anchor_patch, ensure_ascii=False))
    return {"ok": True}


class ElementEditIn(BaseModel):
    """要素基本信息手动编辑：名称/描述，均可空（None=不改）。"""
    name: str | None = None
    brief: str | None = None


@router.patch("/{project_id}/elements/{element_id}")
async def update_element(project_id: int, element_id: int, body: ElementEditIn):
    """手动编辑核心要素的名称/描述（brief=剧情描述简介，对所有类型通用）。
    注意：角色的生图「外貌提示词」走 /prompt（meta.外貌提示词），此处 brief 是剧情描述，不影响设定图指纹。"""
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if "name" in fields:
        fields["name"] = fields["name"].strip()
        if not fields["name"]:
            raise HTTPException(400, "名称不能为空")
    if not fields:
        raise HTTPException(400, "无更新字段")
    cols = ", ".join(f"{k}=${i}" for i, k in enumerate(fields, start=3))
    r = await get_pool().fetchrow(
        f"UPDATE content_elements SET {cols}, updated_at=now() "
        f"WHERE id=$1 AND project_id=$2 RETURNING id",
        element_id, project_id, *fields.values(),
    )
    if not r:
        raise HTTPException(404, "要素不存在")
    return {"ok": True}
    return {"ok": True}


class ElementAgeIn(BaseModel):
    age_years: int  # 角色具体年龄数字（1-120）


@router.patch("/{project_id}/elements/{element_id}/age")
async def set_element_age(project_id: int, element_id: int, body: ElementAgeIn):
    """角色年龄滑块：存 meta.age_years（数字）。捏音色/外貌补档以此为最优先年龄依据。"""
    if not 1 <= body.age_years <= 120:
        raise HTTPException(400, "年龄须在 1-120 之间")
    r = await get_pool().fetchrow(
        "UPDATE content_elements SET meta = meta || $3::jsonb, updated_at=now() "
        "WHERE id=$1 AND project_id=$2 RETURNING id",
        element_id, project_id, json.dumps({"age_years": body.age_years}, ensure_ascii=False),
    )
    if not r:
        raise HTTPException(404, "要素不存在")
    return {"ok": True, "age_years": body.age_years}


class ElementAppearsIn(BaseModel):
    seqs: list[int] = []   # 出现章节 seq 列表（手动标注）


@router.patch("/{project_id}/elements/{element_id}/appears")
async def update_element_appears(project_id: int, element_id: int, body: ElementAppearsIn):
    """手动编辑要素「出现章节」：按 seq 列表重建 element_appearances 索引行。
    仅增删（保留已有行的 snapshot 状态快照，不误伤回写内容）；未匹配到本项目章节的 seq 忽略。"""
    pool = get_pool()
    if not await pool.fetchval(
            "SELECT 1 FROM content_elements WHERE id=$1 AND project_id=$2", element_id, project_id):
        raise HTTPException(404, "要素不存在")
    seqs = sorted({int(s) for s in body.seqs})
    rows = await pool.fetch(
        "SELECT id FROM content_nodes "
        "WHERE project_id=$1 AND kind='chapter' AND seq = ANY($2::int[])",
        project_id, seqs)
    want = [r["id"] for r in rows]
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 删掉不再选中的出现行（want 为空数组时 ANY 恒 false → 清空全部）
            await conn.execute(
                "DELETE FROM element_appearances WHERE element_id=$1 "
                "AND NOT (node_id = ANY($2::bigint[]))", element_id, want)
            # 新增选中但尚无的（保留已有行 snapshot）
            for nid in want:
                await conn.execute(
                    "INSERT INTO element_appearances (project_id, element_id, node_id, snapshot) "
                    "VALUES ($1,$2,$3,'（手动标注）') ON CONFLICT (element_id, node_id) DO NOTHING",
                    project_id, element_id, nid)
    fresh = await pool.fetch(
        "SELECT n.seq FROM element_appearances ea JOIN content_nodes n ON n.id=ea.node_id "
        "WHERE ea.element_id=$1 ORDER BY n.seq", element_id)
    return {"appears_in": [r["seq"] for r in fresh]}


class ProfileGenIn(BaseModel):
    hints: str | None = None   # 用户补充要点（年龄/身份/年代等），可空


@router.post("/{project_id}/elements/{element_id}/profile/gen")
async def gen_element_profile_ep(
    project_id: int, element_id: int, body: ProfileGenIn | None = None
):
    """后置补全结构化档案 + 派生中文外貌提示词（标签短语式）并落库。角色=年龄/性别/身份/时代服饰/体貌（多形态）；
    关键道具=材质/形制/纹样/年代贴合。年代锚取 config.era（未填据梗概/主线/画风推断）——治"古装现代脸/穿越道具"。"""
    from ..services.element_profile import gen_element_profile

    try:
        return await gen_element_profile(
            get_pool(), project_id, element_id, (body.hints if body else "") or ""
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"档案生成失败：{e}")


class ProfileSaveIn(BaseModel):
    profile: dict[str, Any]   # {年龄段,性别,身份,时代服饰,体貌}


@router.patch("/{project_id}/elements/{element_id}/profile")
async def save_element_profile(project_id: int, element_id: int, body: ProfileSaveIn):
    """保存用户手改的结构化档案（不动外貌提示词——外貌走 save_element_prompt/ai-edit）。"""
    r = await get_pool().fetchrow(
        "UPDATE content_elements SET meta = meta || $2::jsonb, updated_at=now() "
        "WHERE id=$1 AND project_id=$3 RETURNING id",
        element_id, json.dumps({"profile": body.profile}, ensure_ascii=False), project_id,
    )
    if not r:
        raise HTTPException(404, "要素不存在")


class CharacterIdentityIn(BaseModel):
    """真人项目角色与系统备案身份的显式绑定；空值表示解除绑定。"""
    ark_character_id: int | None = None


@router.patch("/{project_id}/elements/{element_id}/identity")
async def bind_character_identity(
    project_id: int, element_id: int, body: CharacterIdentityIn
):
    elem = await get_pool().fetchrow(
        "SELECT kind FROM content_elements WHERE id=$1 AND project_id=$2",
        element_id, project_id,
    )
    if not elem:
        raise HTTPException(404, "角色不存在")
    if elem["kind"] != "character":
        raise HTTPException(400, "只有角色要素可以绑定备案身份")
    identity = None
    if body.ark_character_id is not None:
        identity = await get_pool().fetchrow(
            "SELECT id, name, image_url, ark_status, ark_asset_id "
            "FROM ark_characters WHERE id=$1",
            body.ark_character_id,
        )
        if not identity:
            raise HTTPException(404, "备案角色不存在")
        if identity["ark_status"] != "active" or not identity["ark_asset_id"]:
            raise HTTPException(400, "该角色尚未完成备案，只有已备案角色可以绑定")
    patch = {
        "identity_character_id": identity["id"] if identity else None,
        "identity_character_name": identity["name"] if identity else "",
        "identity_image_url": identity["image_url"] if identity else "",
    }
    await get_pool().execute(
        "UPDATE content_elements SET meta = meta || $2::jsonb, updated_at=now() "
        "WHERE id=$1",
        element_id, json.dumps(patch, ensure_ascii=False),
    )
    return patch


class VariantIn(BaseModel):
    id: str | None = None       # 已有图带 id（保留其图/外貌/档案）；新图留空
    tag: str = ""               # 可选短标签（乞丐/皇后/变身后），不填自动
    desc: str = ""              # 一句可选描述（供弱匹配自动选图）
    inherit_ref: bool = True    # 生成时沿用上一张图为参考（关掉=整容/变身/换景）


class VariantsSaveIn(BaseModel):
    variants: list[VariantIn]


def _apply_variants(meta: dict, items: list[VariantIn]) -> tuple[dict, list[dict]]:
    """把前端给的图清单落成 (patch, out)：按 id 保留已有图的图/外貌/档案；
    ≤1 张时折叠回单图（清空 variants，仅剩图镜像回顶层）。首次由单图拆出多图时，
    第一张继承当前顶层图与外貌，避免图库瞬间空掉。"""
    from ..services import element_variants as ev

    had = ev.has_variants(meta)
    prev_by_id = {v.get("id"): v for v in ev.variants_of(meta)}
    top = ev.default_variant(meta)
    out: list[dict[str, Any]] = []
    ids: list[str] = []
    for i, item in enumerate(items):
        tag = (item.tag or "").strip()
        prev = prev_by_id.get(item.id) if item.id else None
        if prev is None and not had and i == 0:
            prev = top
        vid = item.id or ev.slugify_tag(tag or "img", ids)
        if vid in ids:
            vid = ev.slugify_tag(tag or vid, ids)
        ids.append(vid)
        v = {"id": vid, "tag": tag, "desc": (item.desc or "").strip(),
             "inherit_ref": bool(item.inherit_ref),
             "外貌提示词": (prev or {}).get("外貌提示词") or "",
             "sheet_url": (prev or {}).get("sheet_url"),
             "sheet_fingerprint": (prev or {}).get("sheet_fingerprint")}
        for k in ("profile", "sheet_prompt", "sheet_negative",
                  "sheet_prompt_user", "sheet_prompt_anchor"):
            if (prev or {}).get(k) is not None:
                v[k] = prev[k]
        out.append(v)
    if len(out) <= 1:
        keep = out[0] if out else top
        patch = {"variants": None, ev.DESC_MIRROR: keep.get("desc") or "",
                 **{k: keep.get(k) for k in ev.SHEET_FIELDS}}
        if isinstance(keep.get("profile"), dict):
            patch["profile"] = keep["profile"]
    else:
        patch = ev.mirror_patch(out)
        if isinstance(out[0].get("profile"), dict):
            patch["profile"] = out[0]["profile"]
    return patch, out


@router.patch("/{project_id}/elements/{element_id}/variants")
async def save_element_variants(project_id: int, element_id: int, body: VariantsSaveIn):
    """保存要素的设定图清单（改描述 / 沿用开关 / 删除 / 排序）。按 id 保留已有图的图与外貌。"""
    meta = await _element_meta(element_id, project_id)
    patch, out = _apply_variants(meta, body.variants)
    await get_pool().execute(
        "UPDATE content_elements SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
        element_id, json.dumps(patch, ensure_ascii=False))
    return {"variants": out}


@router.post("/{project_id}/elements/{element_id}/variants/add")
async def add_element_variant(project_id: int, element_id: int):
    """加一张空设定图（直接加图，不必先命名形态）：单图要素先把当前图落成第一张，再追加一张
    新图——外貌提示词/档案沿用主图（同一角色/要素），inherit_ref=True（默认沿用上一张相貌/风格），
    无图待生成。返回新图 id，供前端立即打开出图弹框。"""
    from ..services import element_variants as ev

    meta = await _element_meta(element_id, project_id)
    existing = ev.variants_of(meta)
    items = [VariantIn(id=v.get("id"), tag=v.get("tag") or "", desc=v.get("desc") or "",
                       inherit_ref=ev.inherit_enabled(v)) for v in existing]
    items.append(VariantIn(id=None, tag="", desc="", inherit_ref=True))
    patch, out = _apply_variants(meta, items)
    # 新图的外貌/档案沿用主图（同一人物/要素，仅情境不同），出图前就锚住身份
    prim = ev.primary_variant(meta)
    new = out[-1]
    new["外貌提示词"] = prim.get("外貌提示词") or ""
    if isinstance(prim.get("profile"), dict):
        new["profile"] = prim["profile"]
    patch = ev.mirror_patch(out)
    if isinstance(out[0].get("profile"), dict):
        patch["profile"] = out[0]["profile"]
    await get_pool().execute(
        "UPDATE content_elements SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
        element_id, json.dumps(patch, ensure_ascii=False))
    return {"id": new["id"], "variants": out}


async def _element_meta(element_id: int, project_id: int) -> dict:
    row = await get_pool().fetchrow(
        "SELECT meta FROM content_elements WHERE id=$1 AND project_id=$2", element_id, project_id)
    if not row:
        raise HTTPException(404, "要素不存在")
    return _jsonb(row["meta"])


class ElementRef(BaseModel):
    name: str
    kind: str = "asset"
    url: str


class ElementExtraRefIn(BaseModel):
    add: ElementRef | None = None
    remove: str | None = None  # 参考名


@router.patch("/{project_id}/elements/{element_id}/extra-refs")
async def update_element_extra_refs(project_id: int, element_id: int, body: ElementExtraRefIn):
    """增删要素设定图的手选参考图（公共图片生成弹框·资产面板挑的项目图片资产）。
    存 meta.extra_refs，生成设定图时并入参考图池喂给出图模型；启停走 sheet_ref_off（按名）。"""
    if not body.add and not body.remove:
        raise HTTPException(400, "缺少 add 或 remove")
    meta = await _element_meta(element_id, project_id)
    refs = list(meta.get("extra_refs") or [])
    if body.add:
        refs = [r for r in refs if r.get("name") != body.add.name] + [body.add.model_dump()]
    if body.remove:
        refs = [r for r in refs if r.get("name") != body.remove]
    await get_pool().execute(
        "UPDATE content_elements SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
        element_id, json.dumps({"extra_refs": refs}, ensure_ascii=False))
    return {"extra_refs": refs}


class ElementRefsIn(BaseModel):
    off: list[str]  # 设定图生成时停用的参考图名单


@router.patch("/{project_id}/elements/{element_id}/refs")
async def update_element_refs(project_id: int, element_id: int, body: ElementRefsIn):
    """要素设定图参考图启停：停用的参考名生成时不上传其图（存 meta.sheet_ref_off）。"""
    await _element_meta(element_id, project_id)  # 存在性校验
    await get_pool().execute(
        "UPDATE content_elements SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
        element_id, json.dumps({"sheet_ref_off": body.off}, ensure_ascii=False))
    return {"sheet_ref_off": body.off}


class ElementAiEditIn(BaseModel):
    instruction: str            # 修改要求（空=按设定重写）
    prompt: str | None = None   # 编辑框当前内容（可能未保存），缺省用库内值
    variant_id: str | None = None   # 多形态：基线取哪个形态的外貌提示词


@router.post("/{project_id}/elements/{element_id}/prompt/ai-edit")
async def ai_edit_element_prompt(project_id: int, element_id: int, body: ElementAiEditIn):
    """AI 按要求改写要素生图提示词（同步返回，不落库——前端回填编辑框，确认后再保存）。
    以要素自身设定（名称/简介）为事实边界；instruction 为空=按设定重写一版。
    角色改写「外貌提示词」（中文标签短语式外貌描述锚点）；场景等改写描述（brief）。"""
    from ..llm import chat_text

    row = await get_pool().fetchrow(
        "SELECT kind, name, brief, meta FROM content_elements WHERE id=$1 AND project_id=$2",
        element_id, project_id)
    if not row:
        raise HTTPException(404, "要素不存在")
    is_char = row["kind"] == "character"
    meta = _jsonb(row["meta"])
    from ..services import element_variants as ev

    _base = ev.pick_variant(meta, chosen_id=body.variant_id).get("外貌提示词") if is_char else None
    cur = (body.prompt or "").strip() or (_base if is_char else row["brief"]) or ""
    # 双字段：编辑框含分隔线 → AI 只改上段（外貌/描述），锚定段原样拼回
    from ..services import prompt_fields as pf

    _seg = pf.split_edit_text(cur)
    _anchor: str | None = None
    if _seg:
        cur, _anchor = _seg
    field_cn = "角色外貌提示词（用于生图的中文标签短语式外貌描述，身份锚点）" if is_char else "场景/要素设定描述"
    system = (
        f"你是设定图生图提示词工程师。生成/修改给定要素的{field_cn}，只输出最终提示词本身，"
        "不要任何解释或前后缀。硬约束：①以下方要素设定（名称/简介）为事实依据，不得偏离其身份与设定；"
        + ("②角色外貌提示词用中文、标签短语式（顿号分隔、精炼），聚焦稳定可复现的外貌特征"
           "（发型发色/眼睛/体型/标志物/服饰），不写动作场景；专业术语无贴切中文时才夹英文。"
           if is_char else "②聚焦该要素的稳定视觉特征，不写具体分镜画面。")
    )
    kind_cn = {"character": "角色", "scene": "场景", "item": "道具"}.get(row["kind"], row["kind"])
    user = (
        f"【要素】{kind_cn}·{row['name']}\n"
        f"【设定简介】{row['brief'] or '（无）'}\n\n【当前提示词】\n{cur or '（尚无，请新写一版）'}"
        + (f"\n\n【修改要求】\n{body.instruction.strip()}" if body.instruction.strip()
           else "\n\n【要求】按上述设定重新写一版更贴合的提示词。")
    )
    try:
        out = (await chat_text(system, user, temperature=0.4)).strip()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"AI 修改失败：{e}")
    if not out:
        raise HTTPException(502, "AI 返回为空，请重试")
    if _anchor:
        out = pf.join_for_edit(pf.strip_dividers(out), _anchor)  # 锚定段原样拼回编辑框
    return {"prompt": out}


class ApplyImageIn(BaseModel):
    url: str
    variant_id: str | None = None   # 多形态：把图应用到哪个形态；空=主/默认形态


@router.post("/{project_id}/elements/{element_id}/apply-image")
async def apply_element_image(project_id: int, element_id: int, body: ApplyImageIn):
    """直接把一张图应用为该要素的设定图（跳过生成）：写 meta.sheet_url + 落附件表；
    同步刷新 sheet_fingerprint，避免被镜级前置判定为过期而自动重生成覆盖。
    多形态：写到指定形态（主形态镜像回顶层）。"""
    if not (body.url or "").strip():
        raise HTTPException(400, "缺少图片 url")
    row = await get_pool().fetchrow(
        "SELECT brief, meta FROM content_elements WHERE id=$1 AND project_id=$2", element_id, project_id)
    if not row:
        raise HTTPException(404, "要素不存在")
    from ..services import element_variants as ev
    from ..services import flow

    meta = _jsonb(row["meta"])
    variant = ev.find_variant(meta, body.variant_id) or ev.primary_variant(meta)
    fp = flow.fingerprint(ev.sheet_source(variant, row["brief"]))
    patch = ev.set_variant_sheet(meta, body.variant_id, body.url, fp)
    async with get_pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO content_attachments (project_id, element_id, kind, url, meta) "
            "VALUES ($1,$2,'image',$3,$4::jsonb)",
            project_id, element_id, body.url,
            json.dumps({"type": "sheet", "origin": "applied",
                        "variant_id": variant.get("id"), "tag": variant.get("tag") or ""},
                       ensure_ascii=False))
        await conn.execute(
            "UPDATE content_elements SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
            element_id, json.dumps(patch, ensure_ascii=False))
    return {"sheet_url": body.url}


@router.post("/{project_id}/elements/{element_id}/sheet")
async def gen_element_sheet(project_id: int, element_id: int, variant_id: str | None = None):
    """生成要素设定图（角色=三视图/特写/动作/色板身份版；场景=概念图）。异步任务。
    variant_id：多形态要素为哪个身份/阶段出图；空=主/默认形态。"""
    from ..services.element_sheet import assemble_element_sheet_prompt, element_refs

    try:
        prompts = await assemble_element_sheet_prompt(get_pool(), project_id, element_id, variant_id)
        # 手选参考图（extra_refs 去停用项）+「沿用上一张」注入：唯一实现在 element_refs，
        # 真人项目禁沿用这条规则只写在那一处，端点与工作流不会各改各的
        refs = await element_refs(get_pool(), project_id, element_id, variant_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    from ..services import flow

    q = await flow.enqueue(
        get_pool(), kind="gen_element_sheet", project_id=project_id,
        payload={"prompt": prompts["sheet_prompt"], "element_id": element_id,
                 "variant_id": variant_id, "reference_images": refs,
                 "hair_prompt": prompts.get("hair_sheet_prompt") or ""}, priority=10,
    )
    return {**q, **prompts}


class ChapterWriteIn(BaseModel):
    target_minutes: int | None = None
    creative_brief: str | None = None
    required_terms: list[str] | None = None
    forbidden_terms: list[str] | None = None


@router.post("/{project_id}/chapters/{node_id}/write")
async def write_chapter(project_id: int, node_id: int, body: ChapterWriteIn | None = None):
    """生成章节正文（核心原则1检索管线 + 回写三件）。"""
    target_minutes = body.target_minutes if body else None
    if target_minutes is not None and not 6 <= target_minutes <= 10:
        raise HTTPException(422, "目标成片时长必须在6至10分钟之间")
    try:
        return await pipeline.write_chapter(
            get_pool(), project_id, node_id, target_minutes=target_minutes,
            creative_brief=body.creative_brief if body else None,
            required_terms=body.required_terms if body else None,
            forbidden_terms=body.forbidden_terms if body else None)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)[:500])


@router.post("/{project_id}/chapters/{node_id}/write/stream")
async def write_chapter_stream(project_id: int, node_id: int,
                               body: ChapterWriteIn | None = None):
    """流式生成章节正文：逐 token 推送（前端边写边显示，长输出不撞网关超时）。
    完整流结束后走与一次性版相同的落库+回写三件；中途断流不落库（保留旧稿）。
    注意：流里含末尾 <STATE> 回写块，前端展示时按 <STATE> 截断。

    2026-07-28 实测修：此前本接口既不收请求体、也从不把 target_minutes 传给
    chapter_prompt，更没有一次性版那套字数硬验收——前端走的就是这条流式路径，于是
    「目标 6 分钟」实际只产出 346 字（下限的 1/4）而无人察觉，拆出来 8 镜共 42 秒。
    现在参数与一次性版对齐，并在落库前复核同一套验收。
    流式不便像一次性版那样重写 3 次（用户已经看着它写完了），故不丢稿，
    改为在流尾追加一行显式的验收警告，由用户决定是否重生成。"""
    node = await get_pool().fetchrow(
        "SELECT id FROM content_nodes WHERE id=$1 AND project_id=$2 AND kind='chapter'",
        node_id, project_id)
    if not node:
        raise HTTPException(404, "章节不存在")
    target_minutes = body.target_minutes if body else None
    if target_minutes is not None and not 6 <= target_minutes <= 10:
        raise HTTPException(422, "目标成片时长必须在6至10分钟之间")
    system, user = await pipeline.chapter_prompt(
        get_pool(), project_id, node_id, target_minutes=target_minutes,
        creative_brief=body.creative_brief if body else None)

    async def gen():
        chunks: list[str] = []
        try:
            async for delta in llm.chat_stream(system, user):
                chunks.append(delta)
                yield delta
        except Exception as e:  # noqa: BLE001 — 流中报错：标记行透传，不落库
            yield f"\n\n【生成失败】{str(e)[:200]}"
            return
        raw = "".join(chunks)
        if raw.strip():
            await pipeline.persist_chapter(get_pool(), project_id, node_id, raw)
            warn = pipeline.chapter_acceptance_errors(
                raw, target_minutes=target_minutes,
                required_terms=body.required_terms if body else None,
                forbidden_terms=body.forbidden_terms if body else None)
            if warn:
                yield f"\n\n【验收未通过】{'；'.join(warn)}。已保存草稿，建议重新生成。"

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{project_id}/chapters/{node_id}/body")
async def get_body(project_id: int, node_id: int):
    r = await get_pool().fetchrow(
        "SELECT content, word_count, updated_at FROM content_bodies "
        "WHERE node_id=$1 ORDER BY version DESC LIMIT 1", node_id,
    )
    return dict(r) if r else {"content": "", "word_count": 0}


class BodyIn(BaseModel):
    content: str = ""


@router.put("/{project_id}/chapters/{node_id}/body")
async def save_body(project_id: int, node_id: int, body: BodyIn):
    """手动保存/编辑章节正文：只覆盖正文文本，不跑 <STATE> 回写（要素状态/流水账不受人工改稿影响）。"""
    content = body.content
    pool = get_pool()
    node = await pool.fetchrow(
        "SELECT id FROM content_nodes WHERE id=$1 AND project_id=$2 AND kind='chapter'",
        node_id, project_id)
    if not node:
        raise HTTPException(404, "章节不存在")
    async with pool.acquire() as conn:
        async with conn.transaction():
            version = await conn.fetchval(
                "SELECT coalesce(max(version),0)+1 FROM content_bodies WHERE node_id=$1", node_id)
            await conn.execute(
                "INSERT INTO content_bodies (project_id, node_id, content, word_count, version) "
                "VALUES ($1,$2,$3,$4,$5)", project_id, node_id, content, len(content), version,
            )
            await conn.execute(
                "UPDATE content_nodes SET status='drafted', updated_at=now() WHERE id=$1", node_id)
    return {"content": content, "word_count": len(content)}
