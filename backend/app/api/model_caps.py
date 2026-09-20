"""模型能力档案 API：前端画布/生成条自适应的数据源（公开只读，绝不含 api_key）。

GET /api/models/capabilities?purpose=image
→ {"active": {...能力...}, "profiles": [ {...能力...} ]}

前端拿到 active.capabilities 就能决定：参考图槽显示几个（refs.max/refs.kind）、
比例下拉给哪些选项（aspects）、模型名显示什么（profile.name）——
系统管理切换 active 档后 models_registry 30s 缓存过期，画布自动适配。
"""
import json
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import models_registry
from ..db import get_pool
from ..services import model_caps

router = APIRouter(prefix="/api/models", tags=["models"])

_PURPOSES = ("image", "video", "text", "tts", "embedding")


def _profile_out(row: Any) -> dict[str, Any]:
    """一条模型档的对外形状：id/名称/厂商/真实模型名/激活态 + 归一化能力。无密钥。"""
    p = dict(row)
    extra = p.get("extra")
    if not isinstance(extra, dict):
        try:
            import json as _json
            extra = json.loads(extra or "{}")
        except (TypeError, ValueError):
            extra = {}
    return {
        "id": p.get("id"),
        "name": p.get("name"),
        "provider": p.get("provider"),
        "model_name": p.get("model_name"),
        "is_active": bool(p.get("is_active")),
        "max_refs": p.get("max_refs"),
        "capabilities": model_caps.capabilities(p),
    }


@router.get("/capabilities")
async def get_capabilities(purpose: str = "image"):
    """按用途返回全部档 + active 档的归一化能力（画布自适应数据源）。"""
    if purpose not in _PURPOSES:
        return JSONResponse({"error": f"purpose 只支持 {'/'.join(_PURPOSES)}"}, status_code=422)
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, name, provider, model_name, is_active, max_refs, extra "
        "FROM model_profiles WHERE purpose=$1 ORDER BY is_active DESC, id", purpose)
    profiles = []
    active = None
    for r in rows:
        item = _profile_out(r)
        item["extra"] = r["extra"] if isinstance(r["extra"], dict) else None
        profiles.append(item)
        if item["is_active"] and active is None:
            active = item
    return {"purpose": purpose, "active": active, "profiles": profiles}
