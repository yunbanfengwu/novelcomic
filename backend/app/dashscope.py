"""阿里云百炼 DashScope 原生异步接口（生图 / 生视频）。**百炼生图与生视频的唯一实现。**

百炼的 OpenAI 兼容模式只覆盖文本/向量，视觉类一律 404（两次实测踩到）：
- `compatible-mode/v1/images/generations` → 404，生图走 `.../text2image/image-synthesis`
- `compatible-mode/v1/videos` → 404，生视频走 `.../video-generation/video-synthesis`
  （2026-08-01：百炼视频档掉进了 media._grsai_video 的 Sora 风格 fallthrough，
  拼出 compatible-mode/v1/videos 这个根本不存在的地址，请求还没到参数校验就被拒）

两者协议完全一致：提交任务（X-DashScope-Async: enable）→ 轮询 /api/v1/tasks/{id}
直到 task_status=SUCCEEDED，故共用下面的 _submit_and_poll 骨架，禁止各写一份。

模型档里存的是兼容模式地址（.../compatible-mode/v1），这里统一还原成同域的
DashScope 根地址——工作空间专属 Key 有自己的 maas 域名，不能写死公共域名。
"""
import asyncio
import logging
import re
from typing import Any

import httpx

log = logging.getLogger("dashscope")

_SUBMIT = "/api/v1/services/aigc/text2image/image-synthesis"
# qwen-image-edit 族走**同步多模态接口**：一次请求直接回图，不支持异步任务协议
# （2026-09-17 实测：对它发 X-DashScope-Async 提交 403 AccessDenied
#  "current user api does not support asynchronous calls"）
_EDIT_SUBMIT = "/api/v1/services/aigc/multimodal-generation/generation"
_VIDEO_SUBMIT = "/api/v1/services/aigc/video-generation/video-synthesis"
_TASK = "/api/v1/tasks/"
_POLL_INTERVAL = 3.0
_TIMEOUT = httpx.Timeout(120.0, connect=15.0)


def native_host(base_url: str) -> str:
    """`https://x/compatible-mode/v1` → `https://x`；已是根地址则原样返回。"""
    s = (base_url or "").rstrip("/")
    for tail in ("/compatible-mode/v1", "/api/v1", "/v1"):
        if s.endswith(tail):
            return s[: -len(tail)]
    return s


def _size(size: str | None) -> str | None:
    """`1024x576` → `1024*576`（DashScope 用星号分隔）。"""
    return size.replace("x", "*").replace("X", "*") if size else None


# 图生视频族：必须带首帧图。i2v/kf2v/s2v/videoedit/videoretalk/数字人一律吃图，
# 只有 t2v（纯文生视频）可以不给。与 resource_map._BAILIAN_VIDEO 的用途不同——
# 那份判"是不是视频模型"，这份判"要不要图"，两者不可互相替代。
_I2V_KEYS = ("i2v", "kf2v", "s2v", "v2v", "videoedit", "videoretalk",
             "animate", "liveportrait", "avatar", "human-")


def _needs_image(model: str) -> bool:
    n = (model or "").lower()
    if "t2v" in n:              # 纯文生视频，给图反而报错
        return False
    # emo（表情驱动）只认前缀，与 resource_map 同一避坑理由：别让 emotion 类模型误命中
    return n.startswith("emo") or any(k in n for k in _I2V_KEYS)


def _image_url(out: dict[str, Any]) -> str | None:
    results = out.get("results") or []
    return (results[0] or {}).get("url") if results else None


async def _submit_and_poll(host: str, api_key: str, path: str, body: dict[str, Any],
                           kind: str, pick, timeout_s: float) -> str:
    """DashScope 异步任务协议：提交 → 轮询 /api/v1/tasks/{id} → 取结果 URL。

    生图/生视频协议完全一致，差别只在提交路径、请求体与结果字段（pick 负责从
    output 里取 URL）。**任何新增的百炼异步能力都必须复用这里，不要再抄一遍轮询。**
    """
    auth = {"Authorization": f"Bearer {api_key}"}
    headers = {**auth, "Content-Type": "application/json", "X-DashScope-Async": "enable"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(f"{host}{path}", headers=headers, json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"百炼{kind}提交失败 HTTP {r.status_code}: {r.text[:300]}")
        task_id = ((r.json().get("output") or {}).get("task_id") or "").strip()
        if not task_id:
            raise RuntimeError(f"百炼{kind}响应缺 task_id: {r.text[:300]}")

        waited = 0.0
        while waited < timeout_s:
            await asyncio.sleep(_POLL_INTERVAL)
            waited += _POLL_INTERVAL
            p = await client.get(f"{host}{_TASK}{task_id}", headers=auth)
            if p.status_code >= 400:
                raise RuntimeError(f"百炼任务查询失败 HTTP {p.status_code}: {p.text[:300]}")
            out = p.json().get("output") or {}
            status = out.get("task_status")
            if status == "SUCCEEDED":
                url = pick(out)
                if not url:
                    raise RuntimeError(f"百炼{kind}成功但缺 url: {p.text[:300]}")
                return url
            if status in ("FAILED", "CANCELED", "UNKNOWN"):
                msg = out.get("message") or out.get("code") or status
                raise RuntimeError(f"百炼{kind}任务失败: {msg}")
        raise TimeoutError(f"百炼{kind}轮询超时（{int(timeout_s)}s，task={task_id}）")


def _wants_sync(model: str, extra: dict[str, Any] | None = None) -> bool:
    """这张图档走**同步多模态接口**还是异步任务接口。

    百炼两代生图接口并存（按模型族路由，模型档 extra.transport 可显式覆盖）：
    - 异步 image-synthesis（提交任务→轮询）：wanx 全系 / wan2.x-image / qwen-image
    - 同步 multimodal-generation（一次请求直接回图）：qwen-image-edit / -edit-plus
      图像编辑族——不支持异步提交（403 AccessDenied），**也不支持 size**，
      输出比例跟随参考图。
    """
    caps = extra or {}
    nested = caps.get("capabilities") if isinstance(caps.get("capabilities"), dict) else {}
    t = caps.get("transport") or nested.get("transport")
    if t:
        return str(t).lower() == "sync"
    return "image-edit" in (model or "").lower()


async def _multimodal_generation(host: str, api_key: str, model: str, prompt: str,
                                 reference_images: list[str] | None,
                                 timeout_s: float) -> str:
    """qwen-image-edit 族：同步多模态接口，参考图进 messages content，直接取回图 URL。

    参考图按顺序放 content 的 image 项（首图是底图，text 是编辑指令）；
    参考图上限 3 张（qwen-image-edit-plus 系契约），超了在这里裁掉并留痕。
    这族模型不认 size/n/水印等 parameters——请求体保持最小，多传反而报错。
    """
    refs = list(reference_images or [])[:3]
    if not refs:
        raise RuntimeError(
            f"{model} 是图像编辑模型，必须提供 1~3 张参考图（底图）；"
            "纯文生图请用 qwen-image / wanx 等模型档。")
    content: list[dict[str, Any]] = [{"image": u} for u in refs]
    content.append({"text": prompt})
    body = {"model": model,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": {}}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    log.info("百炼生图(同步多模态) model=%s 参考图=%d prompt=%d字", model, len(refs), len(prompt))
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=15.0)) as client:
        r = await client.post(f"{host}{_EDIT_SUBMIT}", headers=headers, json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"百炼生图提交失败 HTTP {r.status_code}: {r.text[:300]}")
        try:
            msg = (r.json().get("output") or {}).get("choices", [{}])[0].get("message") or {}
            items = msg.get("content") or []
        except (AttributeError, IndexError, TypeError):
            items = []
        for item in items:
            if isinstance(item, dict) and item.get("image"):
                return str(item["image"])
        raise RuntimeError(f"百炼生图响应缺 image: {r.text[:300]}")


async def image_synthesis(base_url: str, api_key: str, model: str, prompt: str,
                          size: str | None = None, reference_images: list[str] | None = None,
                          timeout_s: float = 300.0,
                          extra: dict[str, Any] | None = None) -> str:
    """提交生图任务并轮询到出图，返回图片 URL（供应商临时地址，需转存请在调用方做）。

    双协议分派（2026-09-17）：图像编辑族（qwen-image-edit*）走同步多模态接口；
    其余（wanx / wan2.x-image / qwen-image）走异步任务接口。调用方只需把模型档
    的 extra 传进来，协议选择在 provider 层收敛，media/admin 两条路自动受益。
    """
    host = native_host(base_url)
    if _wants_sync(model, extra):
        return await _multimodal_generation(host, api_key, model, prompt,
                                            reference_images, timeout_s)
    body: dict[str, Any] = {"model": model, "input": {"prompt": prompt},
                            "parameters": {"n": 1}}
    if _size(size):
        body["parameters"]["size"] = _size(size)
    # 图像编辑类模型（qwen-image-edit / wanx-*-edit）吃参考图；纯文生图模型忽略该字段
    if reference_images:
        body["input"]["images"] = list(reference_images)
    return await _submit_and_poll(host, api_key, _SUBMIT, body,
                                  "生图", _image_url, timeout_s)


def _legacy_img_field(model: str) -> bool:
    """图输入用旧式 `input.img_url`（字符串）还是新式 `input.media`（数组）。

    百炼在 wan2.7 换了契约，两代并存（2026-08-01 实测：给 happyhorse-1.1-i2v 发
    img_url 会得到 `InvalidParameter: Field required: input.media`）：
    - 旧式 img_url：wanx2.1 / wan2.2 / wan2.5 / wan2.6 各 i2v 档
    - 新式 media：wan2.7 起，以及 happyhorse 这类非 wan 系模型

    判据取模型名里的版本号，认不出版本的（happyhorse-1.1-i2v）一律按新契约走——
    新模型只会越来越多，默认押新的比押旧的对。
    """
    m = re.search(r"wanx?(\d+)\.(\d+)", (model or "").lower())
    return bool(m) and (int(m.group(1)), int(m.group(2))) < (2, 7)


async def video_synthesis(base_url: str, api_key: str, model: str, prompt: str,
                          img_url: str | None = None, last_frame_url: str | None = None,
                          duration: int | None = None, resolution: str | None = None,
                          timeout_s: float = 900.0) -> str:
    """提交生视频任务并轮询到出片，返回视频 URL（供应商临时地址，24h 有效，需转存）。

    百炼视频模型分 i2v（图生视频，必须给首帧）与 t2v（文生视频）两族：`_needs_image`
    按模型名判，缺图时直接报清楚，别把含混的供应商报错甩给用户。

    尾帧只有新契约（media 数组）支持——`last_frame` 与 `first_frame` 同传即可约束
    镜头收束到指定画面，正是本项目「接缝帧/跨镜无缝」要的能力；旧契约无此通道，静默忽略。

    ⚠ `prompt_extend` 显式关掉：默认是 **true**，开着百炼会拿自己的 LLM 重写提示词，
    我们精心装配的角色/场景/画风约束会被改没——提示词是生成链路唯一实现的产物，
    不容供应商二次创作。
    ⚠ `resolution` 不传时供应商默认 **1080P**（不是 720P），整集出片成本差一档，
    要省钱在模型档 extra.resolution 里显式配 720P。
    """
    if _needs_image(model) and not img_url:
        raise RuntimeError(
            f"{model} 是图生视频（i2v）模型，必须提供首帧图。"
            "请先生成本镜首帧，或在系统管理换成 t2v（文生视频）模型档。")
    inp: dict[str, Any] = {"prompt": prompt}
    if _legacy_img_field(model):
        if img_url:
            inp["img_url"] = img_url
    else:
        media = [{"type": "first_frame", "url": img_url}] if img_url else []
        if last_frame_url:
            media.append({"type": "last_frame", "url": last_frame_url})
        if media:
            inp["media"] = media
    params: dict[str, Any] = {"prompt_extend": False, "watermark": False}
    if duration:
        params["duration"] = int(duration)
    if resolution:
        params["resolution"] = resolution
    body = {"model": model, "input": inp, "parameters": params}
    log.info("百炼视频提交 model=%s duration=%ss resolution=%s 首帧=%s 尾帧=%s "
             "契约=%s prompt=%d字", model, duration, resolution or "provider_default(1080P)",
             "有" if img_url else "无", "有" if last_frame_url else "无",
             "img_url" if _legacy_img_field(model) else "media", len(prompt))
    return await _submit_and_poll(native_host(base_url), api_key, _VIDEO_SUBMIT, body,
                                  "生视频", lambda out: out.get("video_url"), timeout_s)
