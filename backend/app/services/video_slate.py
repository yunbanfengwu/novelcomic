"""Deterministic one-frame shot slates for episode experiment 16.

The source attachment is immutable: this module downloads it, normalises the
video, replaces only the requested frames with numbered black slates, and
creates a new permanent attachment.  Any failure leaves the source untouched.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw

log = logging.getLogger("video_slate")

_FPS = 24
_MAX_SOURCE_BYTES = 1024 * 1024 * 1024
_DOWNLOAD_TIMEOUT = httpx.Timeout(300.0, connect=15.0)

# A tiny built-in 5x7 font makes ``SHOT 02`` deterministic on every host.  It
# also avoids relying on a Chinese/fontconfig installation in the image.
_GLYPHS: dict[str, tuple[str, ...]] = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    " ": ("00000",) * 7,
}


def _value(item: Mapping[str, Any] | Any, key: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(key)
    try:
        return item[key]
    except (KeyError, TypeError):
        return getattr(item, key, None)


def _output_size(ratio: str) -> tuple[int, int]:
    """Return the fixed 480p canvas requested by the experiment."""
    try:
        left, right = (float(part.strip()) for part in ratio.split(":", 1))
        portrait = left < right
    except (AttributeError, TypeError, ValueError, ZeroDivisionError):
        portrait = ratio.strip().lower() in {"portrait", "vertical"} if isinstance(ratio, str) else False
    return (480, 854) if portrait else (854, 480)


def _validated_duration(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("duration_s 必须是正整数秒")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("duration_s 必须是正整数秒") from exc
    if not math.isfinite(number) or number <= 0 or number > 900 or not number.is_integer():
        raise ValueError("duration_s 必须是 1 到 900 的整数秒")
    return int(number)


def _validated_source(source_attachment: Mapping[str, Any] | Any) -> dict[str, Any]:
    attachment_id = _value(source_attachment, "id")
    url = _value(source_attachment, "url")
    if not isinstance(attachment_id, int) or isinstance(attachment_id, bool) or attachment_id <= 0:
        raise ValueError("原片缺少有效附件 id")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ValueError("原片缺少有效 HTTP(S) URL")
    return {"id": attachment_id, "url": url}


def _markers(beats: Sequence[Mapping[str, Any] | Any], duration_s: int) -> list[dict[str, Any]]:
    """Map beat 2..N start times to exact output-frame indices."""
    if not isinstance(beats, Sequence) or isinstance(beats, (str, bytes)) or not beats:
        raise ValueError("至少需要一个分镜 beat")

    total_frames = duration_s * _FPS
    markers: list[dict[str, Any]] = []
    previous_frame = -1
    for fallback_no, beat in enumerate(beats[1:], start=2):
        raw_time = _value(beat, "output_start_s")
        try:
            time_s = float(raw_time)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"第 {fallback_no} 镜缺少有效 output_start_s") from exc
        if not math.isfinite(time_s):
            raise ValueError(f"第 {fallback_no} 镜 output_start_s 不是有限数值")

        # This intentionally follows the experiment contract: round(t * 24).
        frame = int(round(time_s * _FPS))
        if frame <= 0 or frame >= total_frames:
            raise ValueError(
                f"第 {fallback_no} 镜标记帧 {frame} 超出有效范围 1..{total_frames - 1}")
        if frame <= previous_frame:
            raise ValueError("相邻分镜的镜号板落在同一帧或时间倒序，请重新规划 output_start_s")

        raw_no = _value(beat, "no")
        try:
            shot_no = int(raw_no if raw_no is not None else fallback_no)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"第 {fallback_no} 镜缺少有效镜号") from exc
        if isinstance(raw_no, bool) or not 1 <= shot_no <= 99:
            raise ValueError("镜号必须是 1 到 99 的整数，以便显示两位 ASCII 镜号")

        markers.append({"shot_no": shot_no, "time_s": time_s, "frame": frame})
        previous_frame = frame
    return markers


def _make_slate(path: Path, width: int, height: int, shot_no: int) -> None:
    """Draw a pure-black board and centred white ``SHOT NN`` bitmap label."""
    label = f"SHOT {shot_no:02d}"
    glyph_width = 5
    gap_units = 1
    units_w = len(label) * glyph_width + (len(label) - 1) * gap_units
    scale = max(1, min(width // (units_w + 10), height // 14))
    rendered_w = units_w * scale
    rendered_h = 7 * scale
    origin_x = (width - rendered_w) // 2
    origin_y = (height - rendered_h) // 2

    image = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    cursor_x = origin_x
    for char in label:
        glyph = _GLYPHS[char]
        for row, pixels in enumerate(glyph):
            for column, pixel in enumerate(pixels):
                if pixel == "1":
                    x0 = cursor_x + column * scale
                    y0 = origin_y + row * scale
                    draw.rectangle(
                        (x0, y0, x0 + scale - 1, y0 + scale - 1),
                        fill=(255, 255, 255),
                    )
        cursor_x += (glyph_width + gap_units) * scale
    image.save(path, format="PNG", optimize=True)


async def _download_source(url: str, target: Path) -> None:
    written = 0
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as client:
        async with client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            declared_size = response.headers.get("content-length")
            if declared_size:
                try:
                    if int(declared_size) > _MAX_SOURCE_BYTES:
                        raise RuntimeError("原片超过 1 GiB 安全上限")
                except ValueError:
                    pass
            with target.open("wb") as output:
                async for chunk in response.aiter_bytes():
                    written += len(chunk)
                    if written > _MAX_SOURCE_BYTES:
                        raise RuntimeError("原片超过 1 GiB 安全上限")
                    output.write(chunk)
    if written == 0:
        raise RuntimeError("下载到的原片为空")


def _seconds(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _run_slate(
    source: Path,
    slate_paths: Sequence[Path],
    markers: Sequence[Mapping[str, Any]],
    output: Path,
    width: int,
    height: int,
    duration_s: int,
) -> None:
    """Run the deterministic CFR post-process in a worker thread."""
    from imageio_ffmpeg import get_ffmpeg_exe

    command = [get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
    for slate_path in slate_paths:
        command.extend(["-loop", "1", "-framerate", str(_FPS), "-i", str(slate_path)])
    silent_input = 1 + len(slate_paths)
    command.extend([
        "-f", "lavfi", "-t", str(duration_s),
        "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
    ])

    filters = [
        "[0:v:0]"
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={_FPS},"
        f"tpad=stop_mode=clone:stop_duration={duration_s},"
        f"trim=start=0:duration={duration_s},setpts=PTS-STARTPTS,format=yuv420p[base]"
    ]
    current = "base"
    for index, marker in enumerate(markers):
        slate_label = f"slate{index}"
        output_label = f"marked{index}"
        filters.append(
            f"[{index + 1}:v:0]scale={width}:{height},setsar=1,"
            f"fps={_FPS},setpts=PTS-STARTPTS,format=yuv420p[{slate_label}]"
        )
        filters.append(
            f"[{current}][{slate_label}]overlay=eof_action=repeat:shortest=0:"
            f"enable='eq(n,{int(marker['frame'])})'[{output_label}]"
        )
        current = output_label

    total_frames = duration_s * _FPS
    command.extend([
        "-filter_complex", ";".join(filters),
        "-map", f"[{current}]", "-map", f"{silent_input}:a:0",
        "-map_metadata", "-1",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(_FPS), "-frames:v", str(total_frames),
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-t", str(duration_s), "-movflags", "+faststart",
        str(output),
    ])

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    timeout = max(180, min(1800, duration_s * 20 + 120))
    result = subprocess.run(
        command,
        capture_output=True,
        timeout=timeout,
        creationflags=creationflags,
    )
    if result.returncode != 0:
        error = (result.stderr or b"").decode("utf-8", "ignore").strip()
        raise RuntimeError(error[-2000:] or f"ffmpeg 镜号板后处理失败，退出码 {result.returncode}")
    if not output.exists() or output.stat().st_size == 0:
        raise RuntimeError("ffmpeg 未生成有效的镜号板母带")


async def add_one_frame_slates(
    pool: Any,
    project_id: int,
    node_id: int | None,
    source_attachment: Mapping[str, Any] | Any,
    beats: Sequence[Mapping[str, Any] | Any],
    ratio: str,
    duration_s: int,
    display_name: str,
    meta: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Create a new 480p master with exactly one numbered slate per cut.

    Beat 1 starts the video and therefore has no preceding board.  For each
    following beat, ``round(output_start_s * 24)`` selects the sole replaced
    frame.  The original attachment row and object are never updated/deleted.
    """
    from .. import oss

    source = _validated_source(source_attachment)
    duration = _validated_duration(duration_s)
    markers = _markers(beats, duration)
    width, height = _output_size(ratio)

    with tempfile.TemporaryDirectory(prefix="episode-slate-") as temp_dir:
        directory = Path(temp_dir)
        source_path = directory / "source.video"
        await _download_source(source["url"], source_path)

        slate_paths: list[Path] = []
        for index, marker in enumerate(markers):
            slate_path = directory / f"slate-{index:03d}.png"
            _make_slate(slate_path, width, height, int(marker["shot_no"]))
            slate_paths.append(slate_path)

        output = directory / "slate-master.mp4"
        await asyncio.to_thread(
            _run_slate,
            source_path,
            slate_paths,
            markers,
            output,
            width,
            height,
            duration,
        )
        content = await asyncio.to_thread(output.read_bytes)

    digest = hashlib.sha256(content).hexdigest()
    stored_url = await oss.store_bytes(content, prefix=f"episode_flash/{project_id}", ext=".mp4")
    if not stored_url:
        raise RuntimeError("镜号板母带生成成功，但 OSS 永久存储失败；原片附件保持不变")

    attachment_meta = {
        **dict(meta or {}),
        "type": "episode_flash_master",
        "origin": "slate_postprocess",
        "name": display_name,
        "raw_attachment_id": source["id"],
        "raw_video_url": source["url"],
        "duration_s": duration,
        "markers": markers,
        "spec": {
            "width": width,
            "height": height,
            "fps": _FPS,
            "frame_count": duration * _FPS,
            "pixel_format": "yuv420p",
            "video_codec": "h264/libx264",
            "audio_codec": "aac",
            "audio": "silent-stereo-48000hz",
            "slate_frame_count": len(markers),
            "slate_label": "SHOT NN (built-in 5x7 ASCII bitmap)",
            "slate_background": "#000000",
        },
        "sha256": digest,
        "bytes": len(content),
    }
    row = await pool.fetchrow(
        "INSERT INTO content_attachments (project_id, node_id, kind, url, meta) "
        "VALUES ($1,$2,'video',$3,$4::jsonb) RETURNING id",
        project_id,
        node_id,
        stored_url,
        json.dumps(attachment_meta, ensure_ascii=False),
    )
    attachment_id = row["id"]
    log.info(
        "单帧镜号板母带已落库 attachment=%s raw=%s project=%s markers=%s bytes=%s",
        attachment_id,
        source["id"],
        project_id,
        len(markers),
        len(content),
    )
    return {
        "id": attachment_id,
        "name": display_name,
        "kind": "video",
        "url": stored_url,
        "duration_s": duration,
        "meta": attachment_meta,
    }
