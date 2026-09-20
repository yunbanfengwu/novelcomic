"""知识库组织层 API：文件夹（系统=虚拟视图 / 自定义=显式归属）、缩略图生成、风格选择库。

kb_entries 是唯一知识库表（角色库/音色库/画风库/文风库/提示词块/知识/技能都在其中），
文件夹只是组织与呈现：系统文件夹按 (kind, category) 规则圈条目，不搬数据、不回填，
生成链路（recall_blocks 等）完全不感知文件夹——这是本次扩展不影响稳定性的关键。
"""
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import get_pool

router = APIRouter(prefix="/api", tags=["kb-library"])


def _jsonb(v: Any) -> Any:
    return v if isinstance(v, (dict, list)) else (json.loads(v) if v else {})


def folder_condition(folder: dict[str, Any], siblings: list[dict[str, Any]],
                     args: list[Any]) -> str:
    """把文件夹翻译成 kb_entries 的 WHERE 片段（args 就地追加）。

    自定义文件夹=folder_id 显式归属；系统文件夹只圈 folder_id IS NULL 的条目：
    带 category 的精确圈（画风库/文风库），不带的做该 kind 兜底（扣除同 kind 更具体文件夹）。
    """
    if not folder["system"]:
        args.append(folder["id"])
        return f"folder_id=${len(args)}"
    args.append(folder["kind"])
    cond = f"folder_id IS NULL AND kind=${len(args)}"
    if folder["category"]:
        args.append(folder["category"])
        return f"{cond} AND category=${len(args)}"
    cats = [s["category"] for s in siblings
            if s["system"] and s["kind"] == folder["kind"] and s["category"]]
    if cats:
        args.append(cats)
        cond += f" AND (category IS NULL OR NOT (category = ANY(${len(args)}::text[])))"
    return cond


async def list_folder_rows() -> list[dict[str, Any]]:
    rows = await get_pool().fetch("SELECT * FROM kb_folders ORDER BY seq, id")
    return [dict(r) for r in rows]


# ═══════════ 文件夹 CRUD ═══════════

@router.get("/admin/kb-folders")
async def list_folders():
    """全部文件夹 + 各自条目数（系统文件夹按规则统计，自定义按 folder_id）。"""
    folders = await list_folder_rows()
    out = []
    for f in folders:
        args: list[Any] = []
        cond = folder_condition(f, folders, args)
        n = await get_pool().fetchval(f"SELECT count(*) FROM kb_entries WHERE {cond}", *args)
        out.append({**f, "meta": _jsonb(f["meta"]), "count": n})
    return out


class FolderIn(BaseModel):
    name: str = Field(min_length=1, description="唯一英文/拼音标识")
    title: str = Field(min_length=1, description="展示名，如「世界观设定」")
    kind: str = "knowledge"  # 自定义文件夹内新建条目的默认 kind


@router.post("/admin/kb-folders")
async def create_folder(body: FolderIn):
    dup = await get_pool().fetchval("SELECT 1 FROM kb_folders WHERE name=$1 OR title=$2",
                                    body.name, body.title)
    if dup:
        raise HTTPException(400, "同名文件夹已存在")
    r = await get_pool().fetchrow(
        "INSERT INTO kb_folders (name, title, kind, system) VALUES ($1,$2,$3,FALSE) RETURNING *",
        body.name.strip(), body.title.strip(), body.kind,
    )
    return {**dict(r), "meta": _jsonb(r["meta"]), "count": 0}


class FolderPatch(BaseModel):
    title: str = Field(min_length=1)


@router.put("/admin/kb-folders/{folder_id}")
async def rename_folder(folder_id: int, body: FolderPatch):
    r = await get_pool().fetchrow(
        "UPDATE kb_folders SET title=$2 WHERE id=$1 AND NOT system RETURNING *",
        folder_id, body.title.strip(),
    )
    if not r:
        raise HTTPException(404, "文件夹不存在或为系统文件夹（不可改名）")
    return {**dict(r), "meta": _jsonb(r["meta"])}


@router.delete("/admin/kb-folders/{folder_id}")
async def delete_folder(folder_id: int):
    """删自定义文件夹；其条目 folder_id 置空，自动落回对应 kind 的系统文件夹。"""
    n = await get_pool().execute(
        "DELETE FROM kb_folders WHERE id=$1 AND NOT system", folder_id)
    if n == "DELETE 0":
        raise HTTPException(404, "文件夹不存在或为系统文件夹（不可删除）")
    return {"ok": True}


# ═══════════ 缩略图生成（提示词→生图→OSS 转存→thumbnail_url）═══════════

# 画风封面=角色海报（2026-07-16 用户定稿）：旧"少年剑客眺望云海古城"是动漫武侠意象，
# 会把写实类画风也带成卡通（且它排在锚词前面、被 Seedream 4 前段加权放大）。改为海报式
# 双区构图——前景角色胸像 + 身后呼应场景，主体彻底中性，真实/卡通只由画风锚词决定；
# 且装配时把画风锚词前置（见下方 gen_thumbnail），让"媒介/质感"抢占最高权重段。
_THUMB_SCENE = ("电影级角色海报，双区构图：前景一位主角的胸像特写（面部清晰、眼神有戏、"
                "质感考究、占画面左侧约四成），身后延展出与人物气质呼应的宏大场景环境，"
                "两者合成一张海报级关键视觉，构图饱满、主体突出、光色统一。"
                "画面中禁止任何文字、字幕、标题与水印，no text, no watermark")


class ThumbIn(BaseModel):
    prompt: str | None = Field(default=None, description="留空=用条目 positive/内容+默认示例场景")


@router.post("/admin/kb/{kb_id}/thumbnail")
async def gen_thumbnail(kb_id: int, body: ThumbIn | None = None):
    """为知识库条目生成缩略图：画风类用其正向提示词渲染示例场景，其余按内容示意。"""
    from .. import media

    row = await get_pool().fetchrow("SELECT * FROM kb_entries WHERE id=$1", kb_id)
    if not row:
        raise HTTPException(404, "条目不存在")
    meta = _jsonb(row["meta"])
    custom = (body.prompt or "").strip() if body else ""
    if custom:
        prompt = custom
    elif meta.get("positive"):
        # 画风锚词前置：先钉媒介/质感（写实=真人肤质、卡通=风格化），再接海报场景，
        # 避免中文场景把写实类拉回卡通（Seedream 4 对提示词前段加权最重）
        prompt = f"{meta['positive']}。{_THUMB_SCENE}"
    else:
        prompt = f"{row['name']}，{row['content'][:200]}。概念示意图，{_THUMB_SCENE}"
    # 风格库生成也进 gen_logs（用户 2026-07-14）：source=kb_style_{id}（画风类）/kb_{id}，
    # 反复调提示词重生成的每一次都有记录，可回看对比哪次效果最好
    src = f"kb_style_{kb_id}" if row["category"] == "style" else f"kb_{kb_id}"
    token = media.GEN_AUDIT.set({"kind": "gen_kb_thumb", "source": src})
    try:
        # ARK Seedream 4.x 硬约束：面积 ≥3686400 像素（2560x1440 恰好达标，16:9 契合选择卡片）
        url = await media.generate_image(prompt, size="2560x1440", store_prefix="kb_thumbs")
    except Exception as e:  # noqa: BLE001 — 供应商错误透传（欠费/审核等）
        raise HTTPException(502, str(e)[:300])
    finally:
        media.GEN_AUDIT.reset(token)
    await get_pool().execute(
        "UPDATE kb_entries SET thumbnail_url=$2, updated_at=now() WHERE id=$1", kb_id, url)
    return {"thumbnail_url": url}


# ═══════════ 风格选择库（引导式新建：选择而非输入）═══════════

_STYLE_RULES = {
    "art": ("prompt_block", "style"),
    "writing": ("knowledge", "writing_style"),
}


@router.get("/style-library")
async def style_library(target: str = "art", content_type: str | None = None):
    """画风/文风候选（enabled 且非内部块），引导式新建的选择卡片数据源。"""
    rule = _STYLE_RULES.get(target)
    if not rule:
        raise HTTPException(400, "target 仅支持 art / writing")
    rows = await get_pool().fetch(
        """SELECT id, name, title, description, content, thumbnail_url, tags, meta
           FROM kb_entries
           WHERE kind=$1 AND category=$2 AND enabled
             AND ($3::text IS NULL OR cardinality(tags)=0 OR $3 = ANY(tags))
             AND COALESCE(meta->>'internal','') <> 'true'
           ORDER BY weight DESC, id""",
        *rule, content_type,
    )
    # tags 一并返回：项目/视频选中此画风/文风时，其标签「自带」继承
    # positive 一并返回：封面等出图链路用它（场景中性锚词），不再用会烤死场景的 content
    return [{"id": r["id"], "name": r["name"], "title": r["title"] or r["name"],
             "description": r["description"], "content": r["content"],
             "positive": _jsonb(r["meta"]).get("positive", ""),
             "thumbnail_url": r["thumbnail_url"], "tags": list(r["tags"] or [])} for r in rows]
