"""独立角色库 API：角色 CRUD + 形象图上传/生成 + 单向注册火山素材库。

与 kb_entries 知识库完全分离（旧的 kind='role' 角色库是知识库文件夹，不参与生成，已弃用）。
角色 = 形象图 + 名称/描述；新建/更换形象图后自动把形象图注册进火山私域虚拟人像库，
拿到 asset_id 后生成视频时可用 asset://<id> 作可信参考图。见 services/ark_assets.py。
"""
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import media, oss
from ..db import get_pool
from ..services import ark_assets

router = APIRouter(prefix="/api/character-library", tags=["character-library"])

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".gif", ".heic", ".heif"}
_CATEGORIES = {"system", "work"}  # 系统生成 / 作品产出


def _out(r: Any) -> dict:
    d = dict(r)
    d["tags"] = list(d.get("tags") or [])
    return d


@router.get("/characters")
async def list_characters(source_project_id: int | None = None):
    if source_project_id is not None:
        rows = await get_pool().fetch(
            "SELECT * FROM ark_characters WHERE source_project_id=$1 ORDER BY seq, id",
            source_project_id)
    else:
        rows = await get_pool().fetch("SELECT * FROM ark_characters ORDER BY seq, id")
    return [_out(r) for r in rows]


@router.get("/characters/{char_id}")
async def get_character(char_id: int):
    r = await get_pool().fetchrow("SELECT * FROM ark_characters WHERE id=$1", char_id)
    if not r:
        raise HTTPException(404, "角色不存在")
    return _out(r)


class CharacterIn(BaseModel):
    name: str = Field(min_length=1)
    category: str = "system"
    group_name: str = ""              # 角色分组（folder）：同分组=同一逻辑角色的多套图；空=未分组
    owner_user: str = ""              # 归属用户（暂无用户系统，可空）
    source_work: str = ""             # 来源作品名
    source_project_id: int | None = None
    description: str = ""
    gender: str = "neutral"
    age: str = "adult"
    tags: list[str] = []
    image_url: str = ""
    seq: int = 0


def _norm_category(category: str) -> str:
    return category if category in _CATEGORIES else "system"


@router.post("/characters")
async def create_character(body: CharacterIn):
    # 作品产出且未显式带作品名时，用来源项目标题回填 source_work（便于角色库检索/展示）
    source_work = body.source_work
    if not source_work and body.source_project_id is not None:
        source_work = await get_pool().fetchval(
            "SELECT title FROM content_projects WHERE id=$1", body.source_project_id) or ""
    r = await get_pool().fetchrow(
        """INSERT INTO ark_characters
               (name, category, group_name, owner_user, source_work, source_project_id,
                description, gender, age, tags, image_url, ark_project, seq)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) RETURNING *""",
        body.name.strip(), _norm_category(body.category), body.group_name.strip(),
        body.owner_user, source_work, body.source_project_id, body.description, body.gender,
        body.age, body.tags, body.image_url, _default_project(), body.seq)
    # 有形象图即自动单向注册火山
    if body.image_url:
        ark_assets.spawn_register(get_pool(), r["id"])
    return _out(r)


@router.put("/characters/{char_id}")
async def update_character(char_id: int, body: CharacterIn):
    old = await get_pool().fetchrow(
        "SELECT image_url, ark_group_id, ark_project FROM ark_characters WHERE id=$1", char_id)
    if not old:
        raise HTTPException(404, "角色不存在")
    image_changed = body.image_url and body.image_url != old["image_url"]
    # 换了形象图 → 重置火山状态、清掉旧组（换脸需重新入库）
    r = await get_pool().fetchrow(
        """UPDATE ark_characters SET name=$2, category=$3, owner_user=$4, source_work=$5,
               source_project_id=$6, description=$7, gender=$8, age=$9,
               tags=$10, image_url=$11, seq=$12, group_name=$14,
               ark_status = CASE WHEN $13 THEN 'pending' ELSE ark_status END,
               ark_group_id = CASE WHEN $13 THEN '' ELSE ark_group_id END,
               ark_asset_id = CASE WHEN $13 THEN '' ELSE ark_asset_id END,
               ark_error = CASE WHEN $13 THEN '' ELSE ark_error END,
               updated_at=now()
           WHERE id=$1 RETURNING *""",
        char_id, body.name.strip(), _norm_category(body.category), body.owner_user,
        body.source_work, body.source_project_id, body.description, body.gender, body.age,
        body.tags, body.image_url, body.seq, bool(image_changed), body.group_name.strip())
    if image_changed:
        # 换图＝火山侧删旧建新（Asset 内容不可变）：先尽力删旧组避免遗留占额度，再重注册
        if old["ark_group_id"] and ark_assets.is_configured():
            try:
                await ark_assets.delete_asset_group(
                    old["ark_group_id"], old["ark_project"] or _default_project())
            except Exception:  # noqa: BLE001 — 删旧失败不阻塞重注册
                pass
        ark_assets.spawn_register(get_pool(), char_id)
    return _out(r)


@router.post("/characters/{char_id}/register")
async def register_character(char_id: int):
    """手动重试单向注册（形象图入库失败/超时后使用）。"""
    r = await get_pool().fetchrow("SELECT image_url FROM ark_characters WHERE id=$1", char_id)
    if not r:
        raise HTTPException(404, "角色不存在")
    if not r["image_url"]:
        raise HTTPException(400, "该角色还没有形象图，先上传或生成一张")
    if not ark_assets.is_configured():
        raise HTTPException(400, "后端未配置 VOLC_AK/VOLC_SK，无法对接火山素材库")
    await get_pool().execute(
        "UPDATE ark_characters SET ark_status='pending', ark_error='', updated_at=now() WHERE id=$1",
        char_id)
    ark_assets.spawn_register(get_pool(), char_id)
    return {"ok": True}


@router.post("/characters/{char_id}/unregister")
async def unregister_character(char_id: int):
    """解除火山备案：删火山素材组、状态退回 pending，但保留本地角色与形象图（可后续再重注册）。"""
    r = await get_pool().fetchrow(
        "SELECT ark_group_id, ark_project FROM ark_characters WHERE id=$1", char_id)
    if not r:
        raise HTTPException(404, "角色不存在")
    # 尽力删火山组；即便火山侧已不存在/删除失败，也照常重置本地状态（与整条删除同策略）
    if r["ark_group_id"] and ark_assets.is_configured():
        try:
            await ark_assets.delete_asset_group(r["ark_group_id"], r["ark_project"] or _default_project())
        except Exception:  # noqa: BLE001
            pass
    await get_pool().execute(
        """UPDATE ark_characters SET ark_status='pending', ark_group_id='', ark_asset_id='',
               ark_error='', updated_at=now() WHERE id=$1""",
        char_id)
    return {"ok": True}


@router.delete("/characters/{char_id}")
async def delete_character(char_id: int):
    r = await get_pool().fetchrow(
        "SELECT ark_group_id, ark_project FROM ark_characters WHERE id=$1", char_id)
    if not r:
        raise HTTPException(404, "角色不存在")
    # 尽力删火山侧素材组（失败不阻塞本地删除）
    if r["ark_group_id"] and ark_assets.is_configured():
        try:
            await ark_assets.delete_asset_group(r["ark_group_id"], r["ark_project"] or _default_project())
        except Exception:  # noqa: BLE001
            pass
    await get_pool().execute("DELETE FROM ark_characters WHERE id=$1", char_id)
    return {"ok": True}


class RenameGroupIn(BaseModel):
    category: str
    old_name: str
    new_name: str = ""  # 空=把整组移出分组（各条目变独立角色）


@router.post("/rename-group")
async def rename_group(body: RenameGroupIn):
    """批量重命名/合并/解散一个分组：把某分类下 group_name=old 的全部条目改为 new。
    不触碰火山备案（分组仅本地组织形态）。"""
    n = await get_pool().execute(
        "UPDATE ark_characters SET group_name=$1, updated_at=now() WHERE category=$2 AND group_name=$3",
        body.new_name.strip(), _norm_category(body.category), body.old_name)
    return {"ok": True, "updated": int(n.split()[-1]) if n else 0}


# ═══════════ 形象图：上传 / 生成 ═══════════

@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    ext = ""
    if file.filename and "." in file.filename:
        ext = "." + file.filename.rsplit(".", 1)[-1].lower()
    if ext not in _IMAGE_EXTS:
        raise HTTPException(400, f"不支持的图片类型 {ext or '(无扩展名)'}")
    data = await file.read()
    url = await oss.store_bytes(data, prefix="character-library", ext=ext)
    if not url:
        raise HTTPException(502, "OSS 未配置或上传失败")
    return {"url": url, "name": file.filename, "size": len(data)}


class GenImageIn(BaseModel):
    prompt: str = Field(min_length=1)
    size: str = "1728x2304"  # 竖版 3:4（火山人像资产推荐竖版）；Seedream 4.x 要求 ≥3686400px，故不可低于此


@router.post("/generate-image")
async def generate_image(body: GenImageIn):
    """按描述生成一张形象图并转存 OSS，返回公网 URL（不落库，前端拿到后随角色保存）。"""
    try:
        filing_prompt = (
            "真人角色备案身份照，角色五官身份必须清晰稳定；正面视角，平视镜头，"
            "中性表情，无遮挡，头发不遮挡眉眼与脸部轮廓；纯白背景，"
            "全身穿无纹样、无配饰、无品牌标识的白色素衣。"
            "只用于固定人物五官身份，不设计剧情服饰、动作或道具。"
        )
        url = await media.generate_image(
            f"{filing_prompt}\n角色要求：{body.prompt}",
            size=body.size, store_prefix="character-library")
    except Exception as e:  # noqa: BLE001 — 供应商错误透传
        raise HTTPException(502, str(e)[:300])
    return {"url": url}


def _default_project() -> str:
    from ..settings import settings
    return settings.ARK_PROJECT_NAME or "default"
