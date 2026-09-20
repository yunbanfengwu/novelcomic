"""媒体生成客户端：按模型注册表 active profile 路由（GRSAI / 火山 ARK / 阿里百炼 可切换）。

接口形状来源 cocc-work 已验证实现：
- GRSAI: OpenAI 形 POST /images/generations（不能传 size）、/videos（Sora 风格）→ {"data":[{"url":..}]}
- ARK 火山引擎:
    生图 Seedream: POST /images/generations（OpenAI 形，支持 size）
    视频 Seedance: POST /contents/generations/tasks 提交 + GET 轮询，
    content 支持 first_frame/last_frame 参考图（I2V 首尾帧）。
- 阿里百炼 dashscope: 视觉类**不在** OpenAI 兼容模式里（images/generations 与 videos
    实测都是 404），生图/生视频一律走 DashScope 原生异步任务，见 app/dashscope.py。

⚠ 每家的分支在 generate_image / generate_video 里必须显式挂到底，认不出的 provider
直接报错——「不是 A 就走 B」的 fallthrough 正是 2026-08-01 百炼视频 404 的成因。
"""
import asyncio
import functools
import json
import logging
import re
from contextvars import ContextVar
from typing import Any

import httpx

from . import models_registry
from .settings import settings

log = logging.getLogger("media")

# ── 生成审计（用户 2026-07-12；2026-07-14 扩展到图片）：调用方在提交前设置上下文
# （任务/镜/章节 + kind/source 来源标记，如 project_10_2_21_video / kb_style_35），
# media 层每次真实提交（含降级级联的每一跳）据此落 gen_logs 一行；
# 视频的异步结果由收割方按 task_id 回写——入参与结果经 task_id + external_task_id 闭环；
# 图片是同步返回，提交与结果同刻一行到位（result.image_url 记 OSS 转存后的永久 URL）──
GEN_AUDIT: ContextVar[dict[str, Any] | None] = ContextVar("GEN_AUDIT", default=None)

# 参考图引用占位符（装配层产出，如"造型与外貌以 @设定图[程遥] 为准"）：
# 真传图时替换为对应 @图片N（引用织入正文使用点，官方案例范式）；
# 未传图的路径（GRSAI/1.x/降级纯文本）清理为普通文字，引用永不落空
_REF_MARKER = re.compile(r"@(?:角色|场景)?设定图\[([^\]]+)\]")


def _ref_name_map(refs: list[dict[str, Any]]) -> dict[str, int]:
    """Build marker aliases for the actual submitted reference order.

    Storyboard assembly distinguishes identity/style assets with display names
    such as ``洛汐角色图片`` and ``洛汐造型`` while prompt markers intentionally
    use the stable element name ``@设定图[洛汐]``.  Exact-name matching therefore
    left the marker unresolved even though the correct image was submitted.
    """
    result: dict[str, int] = {}
    suffixes = ("角色图片", "角色造型", "造型", "设定图", "发型发饰")
    # Later style references must not replace the first/main reference for a
    # character.  setdefault keeps numbering deterministic.
    for no, ref in enumerate(refs, start=1):
        name = str(ref.get("name") or "").strip()
        if not name:
            continue
        result.setdefault(name, no)
        for suffix in suffixes:
            if name.endswith(suffix) and len(name) > len(suffix):
                result.setdefault(name[:-len(suffix)], no)
    return result


def _resolve_ref_markers(prompt: str, name_to_no: dict[str, int] | None = None) -> str:
    """@设定图[名] → @图片N（按实际传图编号）；没传图的名字降级为「名」设定图文字。"""
    def _sub(m: re.Match) -> str:
        no = (name_to_no or {}).get(m.group(1))
        return f"@图片{no}" if no else f"「{m.group(1)}」设定图"
    return _REF_MARKER.sub(_sub, prompt)


def _clean_prompt(prompt: str) -> str:
    """提交前净化（双字段提示词 2026-07-17）：剥离编辑框的分隔线行（——————/锚定提示词：）。
    所有生图/生视频入口统一走这里——任何入口混入分隔线都不发给模型。"""
    from .services.prompt_fields import strip_dividers

    return strip_dividers(prompt or "")


async def _audit_log(*, provider: str, model: str, modality: str, request: dict[str, Any],
                     external_task_id: str | None, status: str, error: str | None = None,
                     result: dict[str, Any] | None = None) -> None:
    """写一行 gen_logs（尽力而为，不阻断生成）；无上下文（非任务场景）静默跳过。
    kind/source 来自上下文：kind=任务类别（gen_video/gen_keyframe/gen_element_sheet/…），
    source=来源标记（project_10_2_21_video / kb_style_35），供按分镜/风格条目筛全部生成记录。"""
    ctx = GEN_AUDIT.get()
    if not ctx:
        return
    try:
        from .db import get_pool

        ctx["attempt"] = int(ctx.get("attempt") or 0) + 1
        await get_pool().execute(
            "INSERT INTO gen_logs (project_id, chapter_id, chapter_title, node_id, shot_no, task_id,"
            " kind, source, attempt_no, provider, model, modality, request, external_task_id, status,"
            " error, result, finished_at,employee_codes,skill_slugs,knowledge_refs,sop_code,"
            " planner_snapshot) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb,"
            " $14,$15,$16,$17::jsonb, CASE WHEN $15 IN ('rejected','failed','done') THEN now() END,"
            " $18::jsonb,$19::jsonb,$20::jsonb,$21,$22::jsonb)",
            ctx.get("project_id"), ctx.get("chapter_id"), ctx.get("chapter_title"),
            ctx.get("node_id"), ctx.get("shot_no"), ctx.get("task_id"),
            ctx.get("kind") or "gen_video", ctx.get("source"),
            ctx["attempt"], provider, model, modality,
            json.dumps(request, ensure_ascii=False), external_task_id, status, error,
            json.dumps(result, ensure_ascii=False) if result else None,
            json.dumps(ctx.get("employee_codes") or [], ensure_ascii=False),
            json.dumps(ctx.get("skill_slugs") or [], ensure_ascii=False),
            json.dumps(ctx.get("knowledge_refs") or [], ensure_ascii=False),
            ctx.get("sop_code"),
            json.dumps(ctx.get("planner_snapshot") or {}, ensure_ascii=False),
        )
    except Exception as e:  # noqa: BLE001
        log.warning("gen_logs 落库失败（忽略）: %s", e)

_TIMEOUT = httpx.Timeout(600.0, connect=15.0)
_GROUP_IMAGE_TIMEOUT = httpx.Timeout(900.0, connect=15.0)
# 组图串行闸：一次组图本身就是 N 张的批量请求，多个组图任务并发只会把供应商打成
# 429 ServerOverloaded（整集出图时 6 个 worker 同时开组图，实测整批全灭），
# 并行没有任何吞吐收益。全进程串行发起，重试期间也不会有别的组图来抢配额。
_GROUP_IMAGE_GATE = asyncio.Semaphore(1)


def _headers(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _ref_cap(p: dict[str, Any], default: int) -> int:
    """本模型的参考图/附件数量上限（2026-09-17 起唯一实现在 model_caps.ref_cap）：
    档里配了 max_refs(>0) 用它，其次 extra.capabilities，再按模型族推断——
    调大模型常因参考图过多 400——提交前按此上限截断多余附件（见系统管理→模型配置）。"""
    from .services import model_caps
    return model_caps.ref_cap(p, default)


async def _image_profile(profile_id: int | None = None,
                         feature_code: str | None = None) -> dict[str, Any]:
    """图片档选取顺序：显式 profile_id（节点/用户点名）> 功能配置第一顺位 > active 档 > .env 兜底。"""
    if profile_id:
        selected = await models_registry.get_profile(profile_id, "image")
        if not selected:
            raise RuntimeError(f"图片模型档案 {profile_id} 不存在或不是图片模型")
        return selected
    if feature_code:
        selected = await models_registry.get_for_feature(feature_code)
        if selected:
            return selected
    p = await models_registry.get_active("image")
    return p or {"provider": "grsai", "base_url": settings.GRSAI_BASE_URL,
                 "api_key": settings.GRSAI_API_KEY, "model_name": settings.GRSAI_IMAGE_MODEL}


async def _video_profile() -> dict[str, Any]:
    p = await models_registry.get_active("video")
    return p or {"provider": "grsai", "base_url": settings.GRSAI_BASE_URL,
                 "api_key": settings.GRSAI_API_KEY, "model_name": settings.GRSAI_VIDEO_MODEL}


# ═══════════ 生图 ═══════════

async def generate_image(
    prompt: str, size: str | None = None, reference_images: list[str] | None = None,
    store_prefix: str | None = None, aspect_ratio: str | None = None,
    profile_id: int | None = None, feature_code: str | None = None,
) -> str:
    """按 active image profile 生图，返回图片 URL。

    GRSAI 不能传 size（400/超时）；ARK Seedream 支持 size（如 1024x576）。
    reference_images：设定图 URL 列表（仅 ARK Seedream 4.x 支持 image 参数）——
    首帧角色一致性的根治：身份从"靠文字碰"变成"照图画"（镜22 实测文字路径必漂）。
    store_prefix：传入则内部完成 OSS 转存并返回永久 URL（供审计日志记录可长期回看的结果图——
    供应商临时 URL 会过期，日志里存它等于没存）。
    """
    prompt = _clean_prompt(prompt)
    p = await _image_profile(profile_id, feature_code)
    # 业务层只声明比例；像素尺寸是 provider/model 的传输协议细节。
    # 显式 size 仅为兼容历史任务保留，新调用应优先传 aspect_ratio。
    if not size and aspect_ratio:
        portrait = aspect_ratio == "9:16"
        if p["provider"] == "ark":
            size = "1440x2560" if portrait else "2560x1440"
        elif p["provider"] == "dashscope":
            size = "1080x1920" if portrait else "1920x1080"
    body: dict[str, Any] = {"model": p["model_name"], "prompt": prompt}
    if p["provider"] == "ark":
        # 中间产物（首帧/设定图）关水印——角标会被 I2V 继承进视频画面；
        # AIGC 合规标识应在成片发布层统一加，而非污染生产素材
        body["watermark"] = False
        if size:
            body["size"] = size
        if reference_images and "seedream-4" in p["model_name"]:
            body["image"] = reference_images[:_ref_cap(p, 4)]
    # 百炼（dashscope）：生图不在 OpenAI 兼容模式里（/images/generations 实测 404），
    # 走 DashScope 原生异步任务；提示词/参考图/审计与其它 provider 同一套
    if p["provider"] == "dashscope":
        from . import dashscope
        # 兼容旧队列：生产画幅历史上按 Seedream 使用 2560x1440；百炼单边上限为 2048。
        # 在 provider 边界等比收敛，避免所有上层调用各自猜模型尺寸。
        dash_size = size
        if size and "x" in size.lower():
            try:
                width, height = (int(x) for x in size.lower().split("x", 1))
                if max(width, height) > 2048:
                    dash_size = "1920x1080" if width >= height else "1080x1920"
            except (TypeError, ValueError):
                pass
        refs_used = (reference_images or [])[:_ref_cap(p, 4)]
        # 审计摘要按**实际提交**的张数算：能力上限 0 的档（如 wanx-v1）裁成 0 张，
        # 仍报「+reference_image×N」就是骗人（2026-09-17 用户实测抓到的假标注）
        summary = f"text[{len(prompt)}字]" + (
            f"+reference_image×{len(refs_used)}" if refs_used else "")
        req = {"model": p["model_name"], "prompt": prompt, "size": dash_size,
               "images": refs_used}
        try:
            url = await dashscope.image_synthesis(
                p["base_url"], p["api_key"], p["model_name"], prompt, dash_size,
                req["images"] or None, extra=p.get("extra") or {})
        except Exception as e:
            await _audit_log(provider=p["provider"], model=p["model_name"], modality=summary,
                             request=req, external_task_id=None, status="failed",
                             error=str(e)[:500])
            raise
        if store_prefix:
            from .oss import store_url
            url = await store_url(url, store_prefix)
        await _audit_log(provider=p["provider"], model=p["model_name"], modality=summary,
                         request=req, external_task_id=None, status="done",
                         result={"image_url": url})
        return url

    if p["provider"] == "minimax":
        ratio = aspect_ratio or "1:1"
        req: dict[str, Any] = {"model": p["model_name"], "prompt": prompt,
                               "aspect_ratio": ratio, "prompt_optimizer": True}
        if reference_images:
            from .services import model_caps
            # subject_reference 是单槽：超过 1 张只取第一张（档案 max_refs 也应配 1）
            req["subject_reference"] = reference_images[:max(1, min(1, _ref_cap(p, 1)))]
        summary = f"text[{len(prompt)}字]" + (f"+reference_image×{len(reference_images)}" if reference_images else "")
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                r = await client.post(f"{p['base_url'].rstrip('/')}/image_generation",
                                      json=req, headers=_headers(p["api_key"]))
                r.raise_for_status()
                data = r.json().get("data") or {}
                urls = data.get("image_urls") if isinstance(data, dict) else None
                if not urls:
                    raise RuntimeError(f"MiniMax 生图响应缺 image_urls: {r.text[:300]}")
                url = str(urls[0])
        except Exception as e:
            await _audit_log(provider=p["provider"], model=p["model_name"], modality=summary,
                             request=req, external_task_id=None, status="failed", error=str(e)[:500])
            raise
        if store_prefix:
            from .oss import store_url
            url = await store_url(url, store_prefix)
        await _audit_log(provider=p["provider"], model=p["model_name"], modality=summary,
                         request=req, external_task_id=None, status="done", result={"image_url": url})
        return url

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:

        async def _post(b: dict[str, Any]) -> str:
            # ARK 实测存在瞬时 400（同一提示词重试即成功，疑似限流/审核抖动）——自动重试 2 次
            last_err: Exception | None = None
            for attempt in range(3):
                if attempt:
                    await asyncio.sleep(3 * attempt)
                r = await client.post(
                    f"{p['base_url'].rstrip('/')}/images/generations",
                    json=b, headers=_headers(p["api_key"]),
                )
                if r.status_code == 400 and "credit" in r.text.lower():
                    raise RuntimeError(f"{p['name'] if 'name' in p else p['provider']} 图片额度不足（insufficient credits）：请充值或在系统管理切换模型")
                if r.status_code in (400, 429) or r.status_code >= 500:
                    last_err = RuntimeError(f"生图 HTTP {r.status_code}: {r.text[:200]}")
                    continue
                r.raise_for_status()
                data = r.json().get("data") or []
                if not data or "url" not in data[0]:
                    raise RuntimeError(f"生图响应缺 url: {r.text[:200]}")
                return data[0]["url"]
            raise last_err or RuntimeError("生图重试耗尽")

        # 审计（与视频同表 gen_logs）：每次 generate_image 调用按最终结局落一行
        # （done/failed），request 记完整入参（提示词全文+参考图），modality 记模态摘要
        summary = f"text[{len(prompt)}字]" + (
            f"+reference_image×{len(body['image'])}" if body.get("image") else "")
        try:
            try:
                url = await _post(body)
            except RuntimeError:
                # 参考图参数不被接受/被审核拦 → 去参考图回退（外貌文字仍在提示词里兜底）
                if "image" not in body:
                    raise
                body.pop("image")
                summary = f"text[{len(prompt)}字]（参考图被拒已回退）"
                url = await _post(body)
        except Exception as e:
            await _audit_log(provider=p["provider"], model=p["model_name"], modality=summary,
                             request=body, external_task_id=None, status="failed",
                             error=str(e)[:500])
            raise
        if store_prefix:
            from .oss import store_url
            url = await store_url(url, store_prefix)
        await _audit_log(provider=p["provider"], model=p["model_name"], modality=summary,
                         request=body, external_task_id=None, status="done",
                         result={"image_url": url})
        return url


async def generate_image_group(
    prompt: str, count: int, size: str | None = None,
    reference_images: list[str] | None = None, store_prefix: str | None = None,
) -> list[str]:
    """Seedream 组图（sequential_image_generation，2026-07-17）：一次请求生成一组
    内容关联的图片——组内共享上下文，角色/场景/画风一致性远优于逐张独立采样
    （分镜整页批量首帧用）。仅 ARK Seedream 4.x+ 支持；参考图数+生成数合计上限 15，
    超出的参考图提交前截断。返回按序的图片 URL 列表——模型可能少生（审核拦截单张等），
    调用方必须按序对位、容忍短缺。"""
    prompt = _clean_prompt(prompt)
    p = await _image_profile()
    if p["provider"] != "ark" or not any(
            v in p["model_name"] for v in ("seedream-4", "seedream-5")):
        raise RuntimeError("组图模式需要火山 ARK Seedream 4.x+ 生图模型"
                           "（系统管理→模型配置切换 active 生图模型）")
    body: dict[str, Any] = {
        "model": p["model_name"], "prompt": prompt, "watermark": False,
        "sequential_image_generation": "auto",
        "sequential_image_generation_options": {"max_images": count},
    }
    if size:
        body["size"] = size
    if reference_images:
        cap = min(_ref_cap(p, 10), max(0, 15 - count))
        body["image"] = reference_images[:cap]

    async with _GROUP_IMAGE_GATE, httpx.AsyncClient(timeout=_GROUP_IMAGE_TIMEOUT) as client:

        async def _post(b: dict[str, Any]) -> list[str]:
            # 与单图同款：ARK 瞬时 400/限流自动重试。429 是供应商过载，
            # 退避要给足时间（整集出图时前面还排着别的组图），线性 3s 太短。
            last_err: Exception | None = None
            for attempt in range(4):
                if attempt:
                    await asyncio.sleep(min(60, 10 * (2 ** (attempt - 1))))
                r = await client.post(
                    f"{p['base_url'].rstrip('/')}/images/generations",
                    json=b, headers=_headers(p["api_key"]),
                )
                if r.status_code == 400 and "credit" in r.text.lower():
                    raise RuntimeError("ARK 图片额度不足（insufficient credits）：请充值或在系统管理切换模型")
                if r.status_code in (400, 429) or r.status_code >= 500:
                    last_err = RuntimeError(f"组图 HTTP {r.status_code}: {r.text[:300]}")
                    continue
                r.raise_for_status()
                urls = [d["url"] for d in (r.json().get("data") or []) if d.get("url")]
                if not urls:
                    raise RuntimeError(f"组图响应无任何图片 url: {r.text[:300]}")
                return urls
            raise last_err or RuntimeError("组图重试耗尽")

        summary = f"text[{len(prompt)}字]→组图×{count}" + (
            f"+reference_image×{len(body['image'])}" if body.get("image") else "")
        try:
            try:
                urls = await _post(body)
            except RuntimeError:
                # 参考图被审核拦（疑似真人等）→ 去参考图回退（提示词内造型文字兜底）
                if "image" not in body:
                    raise
                body.pop("image")
                summary = f"text[{len(prompt)}字]→组图×{count}（参考图被拒已回退）"
                urls = await _post(body)
        except Exception as e:
            await _audit_log(provider=p["provider"], model=p["model_name"], modality=summary,
                             request=body, external_task_id=None, status="failed",
                             error=str(e)[:500])
            raise
        if store_prefix:
            from .oss import store_url
            urls = [await store_url(u, store_prefix) for u in urls]
        await _audit_log(provider=p["provider"], model=p["model_name"], modality=summary,
                         request=body, external_task_id=None, status="done",
                         result={"image_urls": urls, "expected": count})
        return urls


def _parse_provider_error(body: str) -> tuple[int | str | None, str]:
    """供应商错误体 → (code, message)。兼容 {"code":..,"message":..} 与
    OpenAI 风格 {"error":{"code":..,"message":..}}；非 JSON 时 code=None、message=原文。"""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None, body
    if not isinstance(data, dict):
        return None, body
    err = data.get("error") if isinstance(data.get("error"), dict) else data
    code = err.get("code", data.get("code"))
    message = str(err.get("message") or data.get("message") or body)
    return code, message


# ═══════════ 语音合成（TTS）═══════════

# 已验证支持 <|endofprompt|> 自然语言指令的 TTS 模型（model_name 子串匹配）。
# 硅基流动 CosyVoice2-0.5B 实测不支持（会把 instruct 读出来），故不在此列——留空即"全端点关闭 instruct"。
_INSTRUCT_CAPABLE: tuple[str, ...] = ()


async def generate_tts(
    text: str, voice: str, speed: float | None = None, instruct: str | None = None,
) -> bytes:
    """按 active tts profile 合成语音，返回 mp3 字节。

    OpenAI 兼容 /audio/speech（硅基流动托管 CosyVoice2-0.5B 走此协议，
    voice 形如 'FunAudioLLM/CosyVoice2-0.5B:alex' 或上传克隆音色 'speech:xxx:…'）。
    韵律双通道（见 services/prosody.py）：
    - speed：API 数值参数（0.25-4.0），确定性时间缩放；对所有端点都有效；
    - instruct：CosyVoice2 自然语言指令，理论经 <|endofprompt|> 前缀注入驱动停顿/重音/气口。

    ⚠️ 实测（2026-07-16）：硅基流动托管的 CosyVoice2-0.5B 端点**不消费** <|endofprompt|>，
    会把整段 instruct（连同标记）当台词读出来——音频体积随 instruct 长度线性膨胀
    （空/6字/55字 → 41KB/127KB/290KB）。这就是"音色卡通、还念出提示词"的真因。
    因此仅对 _INSTRUCT_CAPABLE 里已验证支持该标记的模型才注入 instruct；其余端点一律忽略
    instruct、只走 voice 选择 + speed。接入火山 doubao 等确认支持后把其 model_name 片段加进白名单。
    """
    p = await models_registry.get_active("tts")
    if not p:
        raise RuntimeError("未配置 TTS 模型档（系统管理→模型配置→🎙 语音合成）")
    if instruct and any(m in p["model_name"] for m in _INSTRUCT_CAPABLE):
        text = f"{instruct}<|endofprompt|>{text}"
    body = {"model": p["model_name"], "input": text, "voice": voice, "response_format": "mp3"}
    if speed and speed != 1.0:
        body["speed"] = speed
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        last_err: Exception | None = None
        for attempt in range(3):
            if attempt:
                await asyncio.sleep(3 * attempt)
            r = await client.post(
                f"{p['base_url'].rstrip('/')}/audio/speech",
                json=body, headers=_headers(p["api_key"]),
            )
            if r.status_code == 200:
                return r.content
            code, message = _parse_provider_error(r.text)
            # 欠费判定只认结构化 error code（30001=硅基余额不足），不再对响应体做子串碰运气
            # （旧逻辑 "30001" in body 会被 trace_id 里随机出现的数字误命中 → 假"欠费"）
            if str(code) == "30001":
                raise RuntimeError("TTS_INSUFFICIENT_BALANCE: 硅基流动账户余额不足")
            err = RuntimeError(f"TTS HTTP {r.status_code}"
                               + (f" code={code}" if code is not None else "")
                               + f": {message[:200]}")
            if r.status_code == 429 or r.status_code >= 500:
                last_err = err  # 限流/过载：有限重试，不当欠费也不当终态
                continue
            raise err
        raise last_err or RuntimeError("TTS 重试耗尽")


# ═══════════ 生视频 ═══════════

async def generate_video(
    prompt: str,
    image_url: str | None = None,
    last_frame_url: str | None = None,
    duration: int = 5,
    ratio: str = "16:9",
) -> dict[str, Any]:
    """按 active video profile 生视频（阻塞至完成），返回 {url, provider}。

    ARK Seedance = 异步任务提交+轮询，支持首尾帧参考图（真 I2V）；
    百炼 dashscope = DashScope 原生异步任务（i2v 吃首帧，不吃多参考图）；
    GRSAI = Sora 风格 /videos（仅文生视频）。

    ⚠ 分支必须穷举到底、认不出就报错。2026-08-01 的 404 事故就是这里原本写成
    「不是 ark 就走 GRSAI」的 fallthrough：百炼档掉进 Sora 风格 /videos，
    拼出 compatible-mode/v1/videos 这个不存在的地址。新增厂商一律在这里显式挂分支。
    """
    prompt = _clean_prompt(prompt)
    p = await _video_profile()
    if p["provider"] == "ark":
        url = await _ark_video(p, prompt, image_url, last_frame_url, duration, ratio)
        return {"url": url, "provider": f"ark:{p['model_name']}"}
    if p["provider"] == "dashscope":
        url = await _dashscope_video(p, _resolve_ref_markers(prompt), image_url,
                                     last_frame_url, duration)
        return {"url": url, "provider": f"dashscope:{p['model_name']}"}
    if p["provider"] == "grsai":
        # GRSAI 纯文生视频：@设定图[名] 引用无图可指，降级为普通文字
        url = await _grsai_video(p, _resolve_ref_markers(prompt), duration)
        return {"url": url, "provider": f"grsai:{p['model_name']}"}
    raise RuntimeError(
        f"当前视频模型档的接口类型 {p['provider']!r} 没有对应的生视频实现"
        f"（模型 {p['model_name']}）。请在系统管理→模型配置换成 ark / dashscope / grsai。")


def _cap_reference_images(refs: list[dict[str, Any]], cap: int) -> list[dict[str, Any]]:
    """Keep temporal anchors and one preview-action frame inside a provider ref limit.

    Canonical character/scene references retain their original order.  A preview
    action frame is reserved as the last available slot so it cannot be silently
    truncated by a long list of identity references.
    """
    if cap <= 0:
        return []
    if len(refs) <= cap:
        return refs
    anchors = [r for r in refs if r.get("kind") in {"keyframe", "lastframe"}]
    preview = next((r for r in refs if r.get("kind") == "preview_action"), None)
    ordinary = [
        r for r in refs
        if r.get("kind") not in {"keyframe", "lastframe", "preview_action"}
    ]
    kept = anchors[:cap]
    if preview is not None and len(kept) < cap:
        ordinary_slots = cap - len(kept) - 1
        kept.extend(ordinary[:ordinary_slots])
        kept.append(preview)
    else:
        kept.extend(ordinary[:cap - len(kept)])
    return kept


# ── 参考图引用句单一实现（2026-07-31 收敛）────────────────────────────────
# 此前「图片N是…」句式在 steps/media 有 6 份近似副本、两张 kind→中文映射表，
# 生图与视频路径对同一批参考图给出不同介绍语义（还出过两处漏配落到默认「场景」的事故）。
# 全站引用句一律走 ref_intro_line；禁止再在任何装配点手拼「图片N是…」。

# kind → 提示词里介绍它的中文名词（生图路径）。装配产出的角色设定图实际是
# character_style（「X造型」「X发型发饰」），与 character 同译「角色」。
REF_KIND_CN = {
    "character": "角色",
    "character_style": "角色",
    "prop": "物件",
    "scene": "场景",
    "scene_sheet": "场景",
    "continuity_frame": "同场景接缝帧",
}
# 视频提交层叠加：可能出现 ark 备案身份图（asset://），须区分「身份」与「服化道造型」，
# 后面的规则句（只锁脸/只锁造型）依赖这一细分。
REF_KIND_CN_VIDEO = {**REF_KIND_CN,
                     "character": "备案角色身份", "character_style": "角色服化道造型"}


def ref_intro_line(i: int, ref: dict[str, Any], video: bool = False,
                   scope: str = "shot") -> str:
    """「图片N是…」引用句单一实现。video=视频提交层（@图片N 前缀 + 身份/造型细分）；
    scope="shot"（单镜口径：本镜…）| "group"（组图口径：不点名单镜）。"""
    head = f"@图片{i} 是" if video else f"图片{i}是"
    kind = ref.get("kind") or ""
    name = ref.get("name", "")
    if kind == "scene_empty":
        return f"{head}本场景的空场景基准图"
    if kind == "scene_sheet":
        return f"{head}本镜场景的空间与角色站位参考图" if scope == "shot" \
            else f"{head}本场景的空间与角色站位参考图"
    if kind == "storyboard":
        return f"{head}本集分镜故事板宫格图（{name}）"
    if kind == "preview_action":
        return f"{head}从本镜预览母带抽取的动作构图参考帧" if scope == "shot" \
            else f"{head}从预览母带抽取的动作构图参考帧"
    if kind == "continuity_frame":
        return f"{head}同场景上一批的接缝帧"
    if kind == "keyframe":
        return f"{head}本镜视频的首帧定格画面"
    if kind == "lastframe":
        return f"{head}本镜视频的尾帧定格画面"
    kind_cn = (REF_KIND_CN_VIDEO if video else REF_KIND_CN).get(kind, "场景")
    return f"{head}{kind_cn}「{name}」的{'造型设定图' if video else '设定图'}"


def _build_ark_content(
    prompt: str,
    model_name: str,
    image_url: str | None = None,
    last_frame_url: str | None = None,
    reference_images: list[dict[str, str]] | None = None,
    audio_refs: list[dict[str, Any]] | None = None,
    max_refs: int | None = None,
) -> list[dict[str, Any]]:
    """纯函数：拼 ARK 视频任务 content 数组（text + 图模态 + 音频模态），可 dry-run 断言。

    ⚠️ ARK 实测（2026-07-12 两轮 400 InvalidParameter）：first/last frame 不能与
    **任何 reference 媒体**（reference_image / reference_audio）混用。
    Seedance 2.0 一律不再用 first_frame 通道：首帧图折算为第 1 张 reference_image，
    提示词声明"图片1是首帧定格画面，视频第一帧与其一致"——首帧/设定图/音频从此可共存。
    非 2.0（1.x 不支持 reference_image）保留 first/last frame 通道，无参考图与音频。

    - reference_audio 仅 Seedance 2.0，ARK 硬约束**必须伴随至少 1 张图**——
      纯文生视频（降级级联终态）时音频自动掐掉，调用方无需特判；
    - 图 ≤4 张（首帧占 1 槽后设定图取前 3）、音频 ≤3 段；引用句在提示词前面动态装配。
    """
    is_v2 = "seedance-2" in model_name
    refs: list[dict[str, str]] = []
    if is_v2:
        if image_url:
            refs.append({"name": "首帧", "kind": "keyframe", "url": image_url})
        if last_frame_url:
            refs.append({"name": "尾帧", "kind": "lastframe", "url": last_frame_url})
        seen = {r["url"] for r in refs}
        refs += [r for r in (reference_images or [])
                 if r.get("url") and r["url"] not in seen]
        # 参考图上限：模型档配了 max_refs(>0) 用它，否则 ARK 默认 4 张；超出自动截断不提交
        cap = max_refs if isinstance(max_refs, int) and max_refs > 0 else 4
        refs = _cap_reference_images(refs, cap)
    audio_refs = (audio_refs or [])[:3]
    use_audio = bool(audio_refs and is_v2 and refs)
    name_to_no = _ref_name_map(refs)
    if refs:
        intro_bits: list[str] = []
        rules: list[str] = []
        has_identity_character = False
        has_strict_character = False
        has_character_style = False
        has_scene_or_prop = False
        for i, r in enumerate(refs, start=1):
            # 首帧/尾帧也登记名字映射：正文里 @设定图[首帧]/@设定图[尾帧] 引用可解析为 @图片N
            intro_bits.append(ref_intro_line(i, r, video=True))
            if r.get("kind") == "keyframe":
                rules.append(f"视频开始参考 @图片{i}：第一帧与其完全一致，画面从它开始自然起动")
            elif r.get("kind") == "lastframe":
                rules.append(f"视频结尾参考 @图片{i}：最后一帧落在它的画面上")
            elif r.get("kind") == "preview_action":
                rules.append(
                    f"@图片{i} 只约束本镜的姿势、动作、朝向、构图与空间关系；"
                    "角色身份、服饰、伤势、武器及场景风格仍以对应设定图和本镜剧情描述为准"
                )
            elif r.get("kind") == "scene_sheet":
                rules.append(f"本镜空间布局与角色站位以 @图片{i} 为准，画面必须发生在该空间内")
            else:
                if r.get("kind") == "character" and r.get("binding") == "identity":
                    has_identity_character = True
                elif r.get("kind") == "character_style":
                    has_character_style = True
                elif r.get("kind") == "character":
                    has_strict_character = True
                else:
                    has_scene_or_prop = True
        if has_identity_character:
            rules.append("带@图片编号的角色图只锁定基础身份、脸型与稳定识别特征；"
                         "服装、伤势、武器、道具、表情、动作和剧情状态以提示词当前分段为准")
        if has_strict_character:
            rules.append("严格按对应角色设定图还原面部特征、发型与服装；"
                         "角色姿势、动作与景别以提示词叙事为准，不照搬设定图构图")
        if has_character_style:
            rules.append("角色造型图只用于还原服装、发饰、妆造、随身道具与指定动作，"
                         "不得从造型图生成或替换五官；人物五官只取对应备案角色身份图")
        if has_scene_or_prop:
            rules.append("场景与物件外观以对应参考图为准，剧情造成的状态变化以提示词为准")
        prompt = "，".join(intro_bits) + "。" + "；".join(rules) + "。" + prompt
    # 正文里的 @设定图[名] 引用按实际传图解析为 @图片N（未传图的降级为普通文字）
    prompt = _resolve_ref_markers(prompt, name_to_no)
    if use_audio:
        audio_bits = [
            f"@audio{i} 是角色「{r.get('speaker', '')}」的声线参考"
            for i, r in enumerate(audio_refs, start=1)
        ]
        prompt = (
            "，".join(audio_bits)
            + "。有对白的角色按对应参考音频的音色与节奏开口，口型与语句同步；参考音频只定声线，台词内容以本提示词为准。"
            + prompt
        )
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if is_v2:
        for r in refs:
            content.append({"type": "image_url", "image_url": {"url": r["url"]}, "role": "reference_image"})
    else:
        if image_url:
            content.append({"type": "image_url", "image_url": {"url": image_url}, "role": "first_frame"})
        if last_frame_url:
            content.append({"type": "image_url", "image_url": {"url": last_frame_url}, "role": "last_frame"})
    if use_audio:
        for r in audio_refs:
            content.append({"type": "audio_url", "audio_url": {"url": r["url"]}, "role": "reference_audio"})
    return content


async def _post_ark_task(p: dict[str, Any], content: list[dict[str, Any]],
                         duration: int, ratio: str,
                         resolution: str | None = None) -> str:
    # Seedance 2.0 的 duration 仅接受 4-15 整数（分镜产出 2-3s 短对白镜会 400 InvalidParameter）。
    # 这是供应商 API 契约的边界防御，不是业务夹紧——业务侧唯一实现是
    # storyboard.clamp_shot_seconds（上限须与此处 4-15 保持一致，media 不 import services 防环）
    if "seedance-2" in p["model_name"]:
        clamped = max(4, min(15, duration))
        if clamped != duration:
            log.info("duration %ss 超出 %s 支持范围(4-15)，夹紧为 %ss",
                     duration, p["model_name"], clamped)
        duration = clamped
    body = {"model": p["model_name"], "content": content, "ratio": ratio,
            "duration": duration, "watermark": False}
    if resolution:
        if resolution not in {"480p", "720p", "1080p"}:
            raise ValueError(f"不支持的视频分辨率：{resolution}")
        body["resolution"] = resolution
    # 可观测性（用户 2026-07-12）：提交前把 content 全量落日志（backend/logs/backend.log）——
    # 排查"到底提交了什么"不再靠猜；错误信息也带模态摘要（text+reference_image×N+…）
    summary = "+".join(
        (c.get("role") or c["type"]) if c["type"] != "text" else f"text[{len(c.get('text') or '')}字]"
        for c in content
    )
    log.info("ARK 视频提交 model=%s duration=%ss ratio=%s resolution=%s 模态=[%s]\n%s",
             p["model_name"], duration, ratio, resolution or "provider_default",
             summary, json.dumps(content, ensure_ascii=False))
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        # 视频提交不重试（用户 2026-07-12 定稿）：400 参数错/审核拒属确定性失败，重试白等；
        # 降级级联（去首帧/纯文本）在 VideoStep 层按错误类型走，不在这里盲重试
        r = await client.post(f"{p['base_url'].rstrip('/')}/contents/generations/tasks",
                              json=body, headers=_headers(p["api_key"]))
        if r.status_code >= 400:
            err = f"视频提交 HTTP {r.status_code} [模态={summary}]: {r.text[:300]}"
            await _audit_log(provider="ark", model=p["model_name"], modality=summary,
                             request=body, external_task_id=None, status="rejected", error=err)
            raise RuntimeError(err)
        ext_id = r.json()["id"]
        await _audit_log(provider="ark", model=p["model_name"], modality=summary,
                         request=body, external_task_id=ext_id, status="accepted")
        return ext_id


async def submit_ark_video(
    prompt: str,
    image_url: str | None = None,
    last_frame_url: str | None = None,
    reference_images: list[dict[str, str]] | None = None,
    duration: int = 5,
    ratio: str = "16:9",
    audio_refs: list[dict[str, Any]] | None = None,
    resolution: str | None = None,
) -> str:
    """提交 ARK Seedance 异步任务，立即返回外部 task_id（不轮询——poller 收割）。

    reference_images：[{name, kind: character|scene, url}] 角色/场景设定图参考
    （role=reference_image，**仅 Seedance 2.0 支持**，1.x 传会 400，按 model 名过滤）。
    audio_refs：[{speaker, url}] 说话角色声线参考（role=reference_audio，仅 Seedance 2.0，
    有对白才传——由音频预检产出；ARK 要求必须伴随至少 1 张图，纯文本路径自动不带）。
    真传参考图/音频时，按官方范式在提示词前面动态加引用句。
    """
    prompt = _clean_prompt(prompt)
    p = await _video_profile()
    if p["provider"] != "ark":
        raise RuntimeError("当前 video active 模型非 ARK")
    # Seedance 2.0：角色若已在角色库注册进火山（Active），参考图改用 asset:// 可信素材，
    # 规避写实设定图被输入审核判"疑似真人"拒收；未注册的保持裸 URL 回退。
    if "seedance-2" in p["model_name"] and reference_images:
        from .db import get_pool
        from .services import ark_assets
        reference_images = await ark_assets.resolve_asset_refs(get_pool(), reference_images)
    content = _build_ark_content(prompt, p["model_name"], image_url, last_frame_url,
                                 reference_images, audio_refs, max_refs=p.get("max_refs"))
    had_audio = any(c.get("role") == "reference_audio" for c in content)
    try:
        return await _post_ark_task(p, content, duration, ratio, resolution)
    except RuntimeError as e:
        # 音频级回退（镜像生图去参考图回退）：音频 URL 审核/格式问题不拖死整镜——剔除音频重试一次
        if had_audio and "audio" in str(e).lower():
            log.warning("ARK 拒收参考音频，剔除音频重试: %s", str(e)[:200])
            content = _build_ark_content(prompt, p["model_name"], image_url, last_frame_url,
                                         reference_images, None, max_refs=p.get("max_refs"))
            return await _post_ark_task(p, content, duration, ratio, resolution)
        raise


async def check_ark_video(external_task_id: str) -> dict[str, Any]:
    """轮询 ARK 任务：{status: pending|done|failed, video_url?, error?}。"""
    p = await _video_profile()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(
            f"{p['base_url'].rstrip('/')}/contents/generations/tasks/{external_task_id}",
            headers=_headers(p["api_key"]))
        r.raise_for_status()
        obj = r.json()
        status = obj.get("status")
        if status == "succeeded":
            return {"status": "done", "video_url": obj["content"]["video_url"]}
        if status == "failed":
            return {"status": "failed", "error": str(obj.get("error", "unknown"))}
        return {"status": "pending"}


async def _ark_video(
    p: dict[str, Any], prompt: str, image_url: str | None,
    last_frame_url: str | None, duration: int, ratio: str,
) -> str:
    """同步封装（提交+等待），供 generate_video 非队列场景。"""
    task_id = await submit_ark_video(prompt, image_url, last_frame_url, None, duration, ratio)
    for _ in range(240):
        await asyncio.sleep(3)
        res = await check_ark_video(task_id)
        if res["status"] == "done":
            return res["video_url"]
        if res["status"] == "failed":
            raise RuntimeError(f"Seedance 任务失败: {res.get('error')}")
    raise TimeoutError(f"Seedance 任务 {task_id} 轮询超时")


async def video_provider_is_ark() -> bool:
    """供 worker 分流：active video 档是否 ARK（走异步提交+poller 收割模式）。"""
    p = await _video_profile()
    return p["provider"] == "ark"


async def video_reference_images_supported() -> bool:
    """当前视频档是否真正支持 @图片N + reference_image，禁止一致性任务静默降级。"""
    p = await _video_profile()
    return p["provider"] == "ark" and "seedance-2" in p["model_name"]


async def video_reference_image_cap() -> int:
    """当前视频档真实可提交的 reference_image 上限；不支持时返回0。"""
    p = await _video_profile()
    if p["provider"] != "ark" or "seedance-2" not in p["model_name"]:
        return 0
    return _ref_cap(p, 4)


async def _dashscope_video(p: dict[str, Any], prompt: str, image_url: str | None,
                           last_frame_url: str | None, duration: int) -> str:
    """百炼生视频：DashScope 原生异步任务（提交+轮询到出片）。

    与 ARK 那条路的差别（上游装配已按 video_reference_images_supported 感知，不会白传）：
    百炼 i2v 吃 **首帧 + 尾帧**，但没有 reference_image / reference_audio 通道，
    角色一致性只能靠首帧 + 提示词全文兜底。尾帧走 media 数组的 last_frame——
    本项目的接缝帧（下一镜首帧当本镜尾帧）在这条路上同样生效。
    分辨率档位在模型档 extra.resolution 配（720P/1080P），留空供应商默认 1080P。
    """
    from . import dashscope

    resolution = (p.get("extra") or {}).get("resolution") or None
    summary = (f"text[{len(prompt)}字]" + ("+first_frame" if image_url else "")
               + ("+last_frame" if last_frame_url else ""))
    req = {"model": p["model_name"], "prompt": prompt, "img_url": image_url,
           "last_frame_url": last_frame_url, "duration": duration, "resolution": resolution}
    submit = functools.partial(
        dashscope.video_synthesis, p["base_url"], p["api_key"], p["model_name"], prompt,
        img_url=image_url, last_frame_url=last_frame_url, resolution=resolution)
    try:
        try:
            url = await submit(duration=duration)
        except RuntimeError as e:
            # 百炼各视频模型的时长取值域不一（wan2.7 收 2-15，别的档可能只收 5/10），
            # 而分镜给的是任意秒数。被按时长拒收时退一步用供应商默认时长重来一次——
            # 成片时长略有出入好过整镜失败；夹紧规则等确认了各模型取值域再收进判据。
            if "duration" not in str(e).lower():
                raise
            log.warning("百炼拒收 duration=%ss，改用供应商默认时长重试: %s", duration, str(e)[:200])
            req["duration"] = None
            url = await submit(duration=None)
    except Exception as e:
        # 与 ARK 提交同款审计：失败也落 gen_logs，排查"到底提交了什么"不靠猜
        await _audit_log(provider="dashscope", model=p["model_name"], modality=summary,
                         request=req, external_task_id=None, status="rejected",
                         error=str(e)[:500])
        raise
    await _audit_log(provider="dashscope", model=p["model_name"], modality=summary,
                     request=req, external_task_id=None, status="done",
                     result={"video_url": url})
    return url


async def _grsai_video(p: dict[str, Any], prompt: str, duration: int) -> str:
    headers = _headers(p["api_key"])
    base = p["base_url"].rstrip("/")
    body = {"model": p["model_name"], "prompt": prompt, "seconds": duration}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(f"{base}/videos", json=body, headers=headers)
        if r.status_code == 400 and "credit" in r.text.lower():
            raise RuntimeError("GRSAI 视频额度不足（insufficient credits）：请充值或在系统管理切换到火山 Seedance")
        r.raise_for_status()
        obj = r.json()
        data = obj.get("data") or []
        if data and isinstance(data, list) and data[0].get("url"):
            return data[0]["url"]
        task_id = obj.get("id")
        if not task_id:
            raise RuntimeError(f"生视频响应无 url 也无任务 id: {r.text[:200]}")
        for _ in range(240):
            await asyncio.sleep(3)
            pr = await client.get(f"{base}/videos/{task_id}", headers=headers)
            pr.raise_for_status()
            po = pr.json()
            status = po.get("status")
            if status in ("completed", "succeeded", "done"):
                url = po.get("url") or (po.get("data") or [{}])[0].get("url")
                if url:
                    return url
                raise RuntimeError(f"任务完成但无 url: {pr.text[:200]}")
            if status in ("failed", "error"):
                raise RuntimeError(f"GRSAI 视频任务失败: {pr.text[:200]}")
        raise TimeoutError("GRSAI 视频轮询超时")
