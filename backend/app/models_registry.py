"""模型注册表运行时：按 purpose 取 active profile（30s 缓存），启动 seed 默认档。"""
import json
import time
from typing import Any

from . import db
from .settings import settings

_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
_TTL = 30.0


def invalidate() -> None:
    _cache.clear()


async def get_active(purpose: str) -> dict[str, Any] | None:
    now = time.monotonic()
    hit = _cache.get(purpose)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    row = await db.get_pool().fetchrow(
        "SELECT * FROM model_profiles WHERE purpose=$1 AND is_active LIMIT 1", purpose
    )
    prof = None
    if row:
        prof = dict(row)
        prof["extra"] = prof["extra"] if isinstance(prof["extra"], dict) else json.loads(prof["extra"] or "{}")
    _cache[purpose] = (now, prof)
    return prof


async def get_for_feature(feature_code: str) -> dict[str, Any] | None:
    """功能配置（feature_model_prefs）取该功能的第一顺位模型档（**唯一实现**）。

    seq 最小者即"默认使用第一个"；功能没配置任何行时返回 None，
    调用方（media._image_profile）回退该 purpose 的 active 档。
    """
    key = f"feature:{feature_code}"
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    row = await db.get_pool().fetchrow(
        "SELECT m.* FROM feature_model_prefs f JOIN model_profiles m ON m.id=f.model_profile_id "
        "WHERE f.feature_code=$1 ORDER BY f.seq, f.model_profile_id LIMIT 1",
        feature_code,
    )
    prof = None
    if row:
        prof = dict(row)
        prof["extra"] = prof["extra"] if isinstance(prof["extra"], dict) else json.loads(prof["extra"] or "{}")
    _cache[key] = (now, prof)
    return prof


async def get_profile(profile_id: int, purpose: str | None = None) -> dict[str, Any] | None:
    """Read a node-selected profile without changing the global active profile."""
    query = "SELECT * FROM model_profiles WHERE id=$1"
    args: tuple[Any, ...] = (profile_id,)
    if purpose:
        query += " AND purpose=$2"
        args = (profile_id, purpose)
    row = await db.get_pool().fetchrow(query, *args)
    if not row:
        return None
    prof = dict(row)
    prof["extra"] = prof["extra"] if isinstance(prof["extra"], dict) else json.loads(prof["extra"] or "{}")
    return prof


# 启动 seed：把 .env 里的现有配置注册成 profile（幂等，按 purpose+name 不存在才插）
_DEFAULTS: list[dict[str, Any]] = [
    dict(purpose="text", provider="openai_compat", name="硅基流动 Qwen2.5-72B",
         base_url="", api_key="", model_name="", active=True, from_settings="llm"),
    dict(purpose="image", provider="grsai", name="GRSAI nano-banana",
         base_url="", api_key="", model_name="", active=True, from_settings="grsai_image"),
    dict(purpose="image", provider="ark", name="火山 Seedream",
         base_url="", api_key="", model_name="doubao-seedream-3-0-t2i-250415", active=False,
         from_settings="ark"),
    dict(purpose="video", provider="grsai", name="GRSAI veo3.1-fast",
         base_url="", api_key="", model_name="", active=True, from_settings="grsai_video"),
    dict(purpose="video", provider="ark", name="火山 Seedance",
         base_url="", api_key="", model_name="", active=False, from_settings="ark_video"),
    # TTS：硅基流动托管 CosyVoice2-0.5B（开源推荐模型的云端版，OpenAI 形 /audio/speech，复用 LLM key）
    dict(purpose="tts", provider="openai_compat", name="硅基流动 CosyVoice2",
         base_url="", api_key="", model_name="FunAudioLLM/CosyVoice2-0.5B", active=True,
         from_settings="llm"),
    # 阿里百炼：OpenAI 兼容模式（compatible-mode/v1），挂档不激活——
    # 免费额度/资源包在系统管理→资源包页选模型后手动切换（provider=dashscope 走通用兼容口）
    dict(purpose="text", provider="dashscope", name="百炼 qwen-plus",
         base_url="", api_key="", model_name="", active=False, from_settings="dashscope"),
    # 向量嵌入：硅基流动 bge-m3（1024 维，多语言/中文强，OpenAI 形 /embeddings，复用 LLM key）
    dict(purpose="embedding", provider="openai_compat", name="硅基流动 bge-m3",
         base_url="", api_key="", model_name="BAAI/bge-m3", active=True,
         from_settings="llm"),
    # Seedance 2.0：唯一支持 reference_image + reference_audio（音画闭环）的视频档。
    # seed 但不激活（账户限额恢复后在系统管理页手动切换）：
    # - seed_key="model"：按 purpose+model_name 判重（默认 purpose+provider 会被已有 ark video 档挡住）
    # - no_auto_active：跳过"ARK 有 key 即激活"分支，绝不压掉当前 active 的 1.5 Pro
    dict(purpose="video", provider="ark", name="火山 Seedance 2.0",
         base_url="", api_key="", model_name="doubao-seedance-2-0-260128", active=False,
         from_settings="ark_video", seed_key="model", no_auto_active=True),
]


async def seed_profiles() -> int:
    """幂等 seed 默认 profile；ARK 有 key 时自动激活 ARK 图/视频档。"""
    pool = db.get_pool()
    inserted = 0
    fill = {
        "llm": (settings.LLM_BASE_URL, settings.LLM_API_KEY, settings.LLM_MODEL),
        "grsai_image": (settings.GRSAI_BASE_URL, settings.GRSAI_API_KEY, settings.GRSAI_IMAGE_MODEL),
        "grsai_video": (settings.GRSAI_BASE_URL, settings.GRSAI_API_KEY, settings.GRSAI_VIDEO_MODEL),
        "ark": (settings.ARK_BASE_URL, settings.ARK_API_KEY, "doubao-seedream-3-0-t2i-250415"),
        "ark_video": (settings.ARK_BASE_URL, settings.ARK_API_KEY, settings.ARK_VIDEO_MODEL),
        "dashscope": (settings.DASHSCOPE_BASE_URL, settings.DASHSCOPE_API_KEY,
                      settings.DASHSCOPE_TEXT_MODEL),
    }
    async with pool.acquire() as conn:
        for d in _DEFAULTS:
            base, key, model = fill[d["from_settings"]]
            model = d["model_name"] or model
            # 判重：默认同 purpose+provider 已有档（含改名/导入的）就不再补默认占位；
            # seed_key="model" 的条目按 purpose+model_name 判重（同 provider 多档并存，如 Seedance 1.5/2.0）
            if d.get("seed_key") == "model":
                row = await conn.fetchrow(
                    "SELECT id FROM model_profiles WHERE purpose=$1 AND model_name=$2",
                    d["purpose"], model,
                )
            else:
                row = await conn.fetchrow(
                    "SELECT id FROM model_profiles WHERE purpose=$1 AND provider=$2",
                    d["purpose"], d["provider"],
                )
            if row:
                continue
            # ARK 档：settings 里有 key 就默认激活（并压掉同 purpose 其它 active）；
            # no_auto_active 的条目除外（如 Seedance 2.0——限额恢复前只挂档不激活）
            active = d["active"]
            if d["provider"] == "ark" and key and not d.get("no_auto_active"):
                active = True
            if active:
                await conn.execute(
                    "UPDATE model_profiles SET is_active=FALSE WHERE purpose=$1", d["purpose"]
                )
            await conn.execute(
                "INSERT INTO model_profiles (purpose, provider, name, base_url, api_key, model_name, is_active) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7)",
                d["purpose"], d["provider"], d["name"], base, key, model, active,
            )
            inserted += 1
    invalidate()
    return inserted
