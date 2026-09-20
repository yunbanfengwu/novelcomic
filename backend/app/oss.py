"""OSS 转存：生成产物（图/视频）从第三方 CDN 下载后转存到用户自己的阿里云 OSS。

配置照搬 cocc-work upload_service.py（oss2 SDK，bucket=taskox）。
第三方生图/生视频服务（如 GRSAI 的 aitohumanize.com CDN）的 URL 有失效风险，
所有产物落库前先转存 OSS，失败时兜底返回原 URL（不阻塞主流程）。
"""
import asyncio
import logging
import uuid

import httpx

from .settings import settings

log = logging.getLogger("oss")

_bucket = None


def _get_bucket():
    global _bucket
    if _bucket is not None:
        return _bucket
    if not (settings.OSS_ACCESS_KEY and settings.OSS_SECRET_KEY and settings.OSS_BUCKET):
        return None
    try:
        import oss2
        auth = oss2.Auth(settings.OSS_ACCESS_KEY, settings.OSS_SECRET_KEY)
        _bucket = oss2.Bucket(auth, f"https://{settings.OSS_ENDPOINT}", settings.OSS_BUCKET)
        return _bucket
    except ImportError:
        log.warning("oss2 未安装，产物不转存。pip install oss2")
        return None
    except Exception as e:  # noqa: BLE001
        log.warning("OSS 初始化失败: %s", e)
        return None


_EXT_BY_TYPE = {"image/jpeg": ".jpeg", "image/png": ".png", "image/webp": ".webp",
                "video/mp4": ".mp4", "video/webm": ".webm"}


async def store_bytes(content: bytes, prefix: str = "misc", ext: str = ".bin") -> str | None:
    """把内存字节直接转存 OSS（TTS 音频等直出字节流的产物），返回 OSS URL；OSS 不可用返回 None。"""
    bucket = _get_bucket()
    if not bucket:
        return None
    try:
        key = f"novelcomic/{prefix}/{uuid.uuid4().hex}{ext}"
        await asyncio.to_thread(bucket.put_object, key, content)
        oss_url = (f"{settings.OSS_BASE_URL}/{key}" if settings.OSS_BASE_URL
                   else f"https://{settings.OSS_BUCKET}.{settings.OSS_ENDPOINT}/{key}")
        log.info("OSS 转存字节 → %s (%d bytes)", key, len(content))
        return oss_url
    except Exception as e:  # noqa: BLE001
        log.warning("OSS 字节转存失败: %s", e)
        return None


async def store_url(url: str, prefix: str = "misc") -> str:
    """下载 url 内容并转存 OSS，返回 OSS URL；OSS 不可用或失败时返回原 URL。"""
    bucket = _get_bucket()
    if not bucket:
        return url
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=15.0)) as client:
            r = await client.get(url, follow_redirects=True)
            r.raise_for_status()
            content = r.content
            ctype = r.headers.get("content-type", "").split(";")[0].strip()
        ext = _EXT_BY_TYPE.get(ctype) or ("." + url.rsplit(".", 1)[-1] if "." in url.rsplit("/", 1)[-1] else ".bin")
        key = f"novelcomic/{prefix}/{uuid.uuid4().hex}{ext}"
        # oss2 是同步 SDK，丢线程池避免卡事件循环
        await asyncio.to_thread(bucket.put_object, key, content)
        oss_url = (f"{settings.OSS_BASE_URL}/{key}" if settings.OSS_BASE_URL
                   else f"https://{settings.OSS_BUCKET}.{settings.OSS_ENDPOINT}/{key}")
        log.info("OSS 转存 %s → %s (%d bytes)", url[:60], key, len(content))
        return oss_url
    except Exception as e:  # noqa: BLE001 — 转存失败不阻塞主流程
        log.warning("OSS 转存失败，沿用原 URL: %s (%s)", url[:80], e)
        return url
