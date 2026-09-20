"""模型能力档案（Model Capability Profile）——「模型=数据」的唯一实现。

行业共识（Replicate/fal.ai 的 schema 驱动、即梦/TapNow 的能力感知 UI）：
**模型差异应该是数据，不是代码**。每个视觉模型的传输协议、参考图槽位、
比例/尺寸支持各不相同，把它们声明在模型档里（或按模型族推断出默认值），
服务端在 provider 边界按档案裁剪请求，前端按档案渲染控件——
系统管理里切换模型，画布 30 秒内自动适配，任何一层都不用改代码。

三层取值（从高到低）：
1. 档内显式声明：`extra.capabilities.{...}` / `max_refs` 列（系统管理可配）
2. 按 provider+模型名推断（各族契约写在这里，新模型不配也能跑对）
3. 全局兜底：不限制（None），由 provider 现有逻辑兜
"""
import re
from typing import Any

# 参考图的语义角色：决定前端槽位文案与后端传参字段
REF_KIND_NONE = "none"            # 纯文生图，不吃参考图
REF_KIND_EDIT_BASE = "edit_base"  # 图像编辑族：首图是底图（qwen-image-edit 系）
REF_KIND_SUBJECT = "subject"      # 主体参考（minimax subject_reference）
REF_KIND_REFERENCE = "reference"  # 通用参考图（seedream image / 前端素材）

_COMMON_ASPECTS = ["1:1", "16:9", "9:16", "4:3", "3:4"]


def capabilities(profile: dict[str, Any] | None) -> dict[str, Any]:
    """归一化出一张模型的能力档案。profile 缺字段也能给出可用的形状。"""
    p = profile or {}
    extra = p.get("extra") if isinstance(p.get("extra"), dict) else {}
    caps = extra.get("capabilities") if isinstance(extra.get("capabilities"), dict) else {}
    provider = (p.get("provider") or "").lower()
    model = (p.get("model_name") or "").lower()

    transport = caps.get("transport") or extra.get("transport")
    if not transport:
        transport = _infer_transport(provider, model)

    ref_cap = caps.get("refs") if isinstance(caps.get("refs"), dict) else {}
    ref_max = _explicit_ref_max(p, ref_cap)
    ref_kind = ref_cap.get("kind")
    if ref_max is None or ref_kind is None:
        inferred_max, inferred_kind = _infer_refs(provider, model)
        if ref_max is None:
            ref_max = inferred_max
        if ref_kind is None:
            ref_kind = (inferred_kind if ref_max else REF_KIND_NONE)

    aspects = caps.get("aspects")
    if aspects is not None and not (isinstance(aspects, list) and aspects):
        aspects = None
    if aspects is None and provider == "minimax":
        aspects = ["1:1", "16:9", "9:16", "4:3", "3:4", "21:9"]

    return {
        "transport": transport,
        "refs": {"max": int(ref_max or 0), "kind": ref_kind or REF_KIND_NONE},
        # None = 不由档案约束（provider 默认/跟随参考图）；非空列表=前端可选范围
        "aspects": aspects,
        "sizes": caps.get("sizes") if isinstance(caps.get("sizes"), list) and caps.get("sizes") else None,
    }


def _infer_transport(provider: str, model: str) -> str | None:
    """按 provider/模型名推断传输协议。只标注已知差异，认不出返回 None 走 provider 默认。"""
    if provider == "dashscope":
        return "sync" if "image-edit" in model else "async"
    return "http_json"  # minimax/grsai/ark 等普通同步 REST 或各自任务协议，由 media.py 分派


def _explicit_ref_max(profile: dict[str, Any], caps: dict[str, Any]) -> int | None:
    """档内显式声明的参考图上限：max_refs 列优先，其次 capabilities.refs.max。"""
    n = profile.get("max_refs")
    if isinstance(n, int) and n > 0:
        return n
    n = caps.get("max")
    if isinstance(n, int) and n >= 0:
        return n
    return None


def _infer_refs(provider: str, model: str) -> tuple[int | None, str | None]:
    """按模型族推断参考图数量与语义。**认不出返回 (None, None)**——
    显式配置永远优先；推断是兜底不是猜测游戏，宁缺毋滥。"""
    if provider == "dashscope":
        if "image-edit" in model:
            return 3, REF_KIND_EDIT_BASE   # qwen-image-edit 族：1~3 张，首图是底图
        return 0, REF_KIND_NONE            # qwen-image / wanx / wan2.x-image 纯文生图
    if provider == "minimax":
        return 1, REF_KIND_SUBJECT         # subject_reference 单槽
    if provider == "ark" and "seedream-4" in model:
        return 4, REF_KIND_REFERENCE       # seedream 4.x 支持多参考图
    if provider == "ark" and "seedream" in model:
        return 0, REF_KIND_NONE
    if provider == "grsai":
        return 0, REF_KIND_NONE
    return None, None


# ── media.py 现有 _ref_cap 的归一化替代（保持行为兼容）────────────────────

def ref_cap(profile: dict[str, Any], default: int) -> int:
    """参考图截断上限：显式 max_refs(>0) > capabilities.refs.max(≥0) > provider 推断 > default。"""
    extra = profile.get("extra") if isinstance(profile.get("extra"), dict) else {}
    caps = extra.get("capabilities") if isinstance(extra.get("capabilities"), dict) else {}
    n = _explicit_ref_max(profile or {}, caps)
    if n is None:
        inferred, _ = _infer_refs((profile or {}).get("provider") or "",
                                  (profile or {}).get("model_name") or "")
        n = inferred
    return int(n) if isinstance(n, int) and n >= 0 else default


def ref_kind(profile: dict[str, Any]) -> str:
    """参考图语义角色：前端槽位文案与后端取用字段共用。"""
    extra = profile.get("extra") if isinstance(profile.get("extra"), dict) else {}
    caps = extra.get("capabilities") if isinstance(extra.get("capabilities"), dict) else {}
    kind = caps.get("kind")
    if not kind:
        _, kind = _infer_refs((profile or {}).get("provider") or "",
                              (profile or {}).get("model_name") or "")
    return kind or REF_KIND_NONE
