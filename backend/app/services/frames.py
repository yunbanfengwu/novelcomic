"""视频抽帧：用 imageio-ffmpeg 自带的静态 ffmpeg 抽取视频首帧/尾帧（JPEG 字节）。

视频存 OSS（HTTP URL），ffmpeg 直接以 URL 为输入——尾帧用 -sseof 从末尾倒退起播，
配合 OSS 的 Range 请求只拉尾部数据，不必整段下载。直连失败（协议不支持/网络抖动）时
兜底：httpx 下载到临时文件再抽。抽出的字节由调用方转存 OSS 落库。
"""
import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path

import httpx

log = logging.getLogger("frames")

_TIMEOUT = 120  # 秒：镜头视频仅数秒~十几秒，超时即视为异常


def _run_ffmpeg(args: list[str]) -> None:
    p = subprocess.run(args, capture_output=True, timeout=_TIMEOUT)
    if p.returncode != 0:
        err = (p.stderr or b"").decode("utf-8", "ignore").strip()
        raise RuntimeError(err[-300:] or f"ffmpeg 退出码 {p.returncode}")


def _extract(src: str, position: str, at_sec: float | None = None) -> bytes:
    """src=视频 URL 或本地路径；position='first'|'last'；at_sec 非空则抽该秒的一帧（覆盖 position）。
    同步执行，丢线程池调用。"""
    from imageio_ffmpeg import get_ffmpeg_exe  # 延迟导入：缺包时报错收敛到调用方

    exe = get_ffmpeg_exe()

    def _has(p: str) -> bool:
        return Path(p).exists() and Path(p).stat().st_size > 0

    with tempfile.TemporaryDirectory() as td:
        out = str(Path(td) / "frame.jpg")
        base = [exe, "-v", "error", "-y"]
        if at_sec is not None:
            ts = f"{max(at_sec, 0.0):.3f}"
            # ① -ss 放 -i 前：按关键帧快进（URL 走 Range 只拉所需片段），快。
            #    但当 at_sec 落到最后一个关键帧之后/视频结尾时会「no packets」越界失败（-22）。
            try:
                _run_ffmpeg(base + ["-ss", ts, "-i", src, "-frames:v", "1", "-q:v", "2", out])
            except RuntimeError:
                pass
            # ② 快进取不到帧：-ss 放 -i 后，从头解码到该秒（慢但稳，镜头视频仅数秒无妨）。
            if not _has(out):
                try:
                    _run_ffmpeg(base + ["-i", src, "-ss", ts, "-frames:v", "1", "-q:v", "2", out])
                except RuntimeError:
                    pass
            # ③ at_sec 越过视频结尾（前端拖轴回传了 ≥时长的值）：退化取最后一帧，保证有图返回。
            if not _has(out):
                try:
                    _run_ffmpeg(base + ["-sseof", "-1", "-i", src, "-update", "1", "-q:v", "2", out])
                except RuntimeError:
                    pass
        elif position == "first":
            _run_ffmpeg(base + ["-i", src, "-frames:v", "1", "-q:v", "2", out])
        else:
            # -sseof -3：从末尾倒退 3 秒起解码；-update 1 反复覆写同一文件=只留最后一帧
            try:
                _run_ffmpeg(base + ["-sseof", "-3", "-i", src, "-update", "1", "-q:v", "2", out])
            except RuntimeError:
                pass
            if not Path(out).exists() or Path(out).stat().st_size == 0:
                # 视频不足 3 秒时 -sseof 可能越界取不到帧：整段解码只留最后一帧兜底
                _run_ffmpeg(base + ["-i", src, "-update", "1", "-q:v", "2", out])
        data = Path(out).read_bytes() if Path(out).exists() else b""
    if not data:
        raise RuntimeError("未取到帧（视频可能损坏或为空）")
    return data


async def extract_frame(video_url: str, position: str, at_sec: float | None = None) -> bytes:
    """抽取视频一帧返回 JPEG 字节；at_sec 非空=抽该秒的帧，否则按 position 取首/尾帧。失败抛 RuntimeError。
    video_url 为本地路径时直接抽，不走「下载后重试」兜底（那只对 http(s) URL 有意义）。"""
    is_url = video_url.startswith(("http://", "https://"))
    try:
        return await asyncio.to_thread(_extract, video_url, position, at_sec)
    except Exception as e:  # noqa: BLE001 — 直连失败降级为下载后抽帧
        if not is_url:
            raise
        log.info("ffmpeg 直连 URL 抽帧失败（%s），改为下载后抽帧", e)
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=15.0)) as client:
        r = await client.get(video_url, follow_redirects=True)
        r.raise_for_status()
        content = r.content
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    try:
        tmp.write(content)
        tmp.close()
        return await asyncio.to_thread(_extract, tmp.name, position, at_sec)
    finally:
        Path(tmp.name).unlink(missing_ok=True)
