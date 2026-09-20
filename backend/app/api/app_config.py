"""系统配置 API：运行期可编辑的全局配置（key-value，jsonb 存整块结构）。

目前只暴露首页背景 home_bg：多组 {image, video}（供后续轮播），前端当前只取第一组。
后续要加别的配置项，按同样的 _get/_set + 一对 GET/PUT 端点扩展即可。
"""
import json

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..db import get_pool

router = APIRouter(prefix="/api/app-config", tags=["app-config"])


async def _get(key: str, default):
    row = await get_pool().fetchrow("SELECT value FROM app_config WHERE key=$1", key)
    if not row:
        return default
    v = row["value"]
    return json.loads(v) if isinstance(v, str) else v


async def _set(key: str, value) -> None:
    await get_pool().execute(
        """INSERT INTO app_config (key, value, updated_at)
           VALUES ($1, $2::jsonb, now())
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""",
        key, json.dumps(value, ensure_ascii=False))


# ═══════════ 首页背景 ═══════════

class BgGroup(BaseModel):
    image: str = ""   # 背景图 URL（视频加载前的封面/回退）
    video: str = ""   # 背景视频 URL（加载完成后自动播放）


class HomeBgIn(BaseModel):
    groups: list[BgGroup] = Field(default_factory=list)


@router.get("/home-bg")
async def get_home_bg():
    return await _get("home_bg", {"groups": []})


@router.put("/home-bg")
async def set_home_bg(body: HomeBgIn):
    data = {"groups": [g.model_dump() for g in body.groups]}
    await _set("home_bg", data)
    return data


# ═══════════ 生成配置 ═══════════

# 生成相关全局开关默认值。整块以 jsonb 存 app_config['gen_config']；
# PUT 做「按提供字段合并」而非整体覆盖——前端多个开关各自即改即存、只发变动字段，互不清零。
_GEN_CONFIG_DEFAULTS = {
    # 生成真人角色卡：True=允许照片级真人写实（用户 2026-07-14 放开的行为，默认沿用）；
    #   False=对人形角色强制虚拟约束（保留物理真实感，但五官不贴近真人），从设定图源头规避火山"疑似真人"拒收。
    "realistic_character": True,
    # 允许项目直接上传到火山虚拟角色库：True=项目角色面板保留「加入火山角色库」入口（默认，沿用现状）；
    #   False=隐藏项目侧直传入口，统一到「角色库」集中管理与备案（角色可分组、一角色多套图）。
    "allow_project_ark_upload": True,
}


class GenConfigIn(BaseModel):
    # 全部可选：只更新显式提供的字段（None=不动），避免单开关保存把其它开关重置为默认。
    realistic_character: bool | None = None
    allow_project_ark_upload: bool | None = None


async def get_gen_config() -> dict:
    """生成相关全局开关（含默认回填）。供生成侧（element_sheet 等）与前端读取。"""
    stored = await _get("gen_config", {})
    return {**_GEN_CONFIG_DEFAULTS, **(stored if isinstance(stored, dict) else {})}


@router.get("/gen-config")
async def get_gen_config_ep():
    return await get_gen_config()


@router.put("/gen-config")
async def set_gen_config(body: GenConfigIn):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    data = {**await get_gen_config(), **patch}
    await _set("gen_config", data)
    return data
