"""Episode master-video concatenation.

Generated group clips are deliberately kept as independent attachments.  This
module only downloads those immutable inputs, normalises them, creates a new
hard-cut master, stores that master permanently in OSS, and inserts one new
attachment row.  A failed concat therefore never removes or mutates a source
attachment.
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

log = logging.getLogger("video_concat")

_FPS = 24
_MAX_PART_BYTES = 512 * 1024 * 1024
_DOWNLOAD_TIMEOUT = httpx.Timeout(300.0, connect=15.0)


def _output_size(ratio: str) -> tuple[int, int]:
    """Return the fixed 480p canvas, preserving portrait/landscape intent."""
    try:
        left, right = (float(value.strip()) for value in ratio.split(":", 1))
        portrait = left < right
    except (AttributeError, TypeError, ValueError, ZeroDivisionError):
        portrait = ratio.strip().lower() in {"portrait", "vertical"} if isinstance(ratio, str) else False
    return (480, 854) if portrait else (854, 480)


def _duration(value: Any, index: int) -> float:
    try:
        duration = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"第 {index} 段缺少有效 duration_s") from exc
    if not math.isfinite(duration) or duration <= 0 or duration > 900:
        raise ValueError(f"第 {index} 段 duration_s 必须在 0 到 900 秒之间")
    return duration


def _part_value(part: Mapping[str, Any] | Any, key: str) -> Any:
    if isinstance(part, Mapping):
        return part.get(key)
    try:
        return part[key]
    except (KeyError, TypeError):
        return getattr(part, key, None)


def _validated_parts(parts: Sequence[Mapping[str, Any] | Any]) -> list[dict[str, Any]]:
    if not parts:
        raise ValueError("至少需要一个分组视频才能拼接母带")

    result: list[dict[str, Any]] = []
    for index, part in enumerate(parts, start=1):
        attachment_id = _part_value(part, "id")
        url = _part_value(part, "url")
        if not isinstance(attachment_id, int) or isinstance(attachment_id, bool) or attachment_id <= 0:
            raise ValueError(f"第 {index} 段缺少有效附件 id")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise ValueError(f"第 {index} 段缺少有效视频 URL")
        result.append({
            "id": attachment_id,
            "url": url,
            "duration_s": _duration(_part_value(part, "duration_s"), index),
        })
    return result


async def _download_part(client: httpx.AsyncClient, url: str, target: Path) -> None:
    written = 0
    async with client.stream("GET", url, follow_redirects=True) as response:
        response.raise_for_status()
        declared_size = response.headers.get("content-length")
        if declared_size:
            try:
                if int(declared_size) > _MAX_PART_BYTES:
                    raise RuntimeError("分组视频超过 512 MiB 安全上限")
            except ValueError:
                pass
        with target.open("wb") as output:
            async for chunk in response.aiter_bytes():
                written += len(chunk)
                if written > _MAX_PART_BYTES:
                    raise RuntimeError("分组视频超过 512 MiB 安全上限")
                output.write(chunk)
    if written == 0:
        raise RuntimeError("下载到的分组视频为空")


def _seconds(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _run_concat(inputs: list[Path], durations: list[float], output: Path, width: int, height: int) -> None:
    """Normalise inputs and concatenate their video tracks; audio is deterministic silence."""
    from imageio_ffmpeg import get_ffmpeg_exe

    total_duration = sum(durations)
    command = [get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y"]
    for source in inputs:
        command.extend(["-i", str(source)])

    # A dedicated silent track avoids concat failures when providers return a
    # mixture of clips with audio, without audio, or with incompatible codecs.
    command.extend([
        "-f", "lavfi", "-t", _seconds(total_duration),
        "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
    ])

    filters: list[str] = []
    for index, duration in enumerate(durations):
        seconds = _seconds(duration)
        filters.append(
            f"[{index}:v:0]"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1,fps={_FPS},setpts=PTS-STARTPTS,"
            f"tpad=stop_mode=clone:stop_duration={seconds},"
            f"trim=start=0:duration={seconds},setpts=PTS-STARTPTS,format=yuv420p[v{index}]"
        )
    concat_inputs = "".join(f"[v{index}]" for index in range(len(inputs)))
    filters.append(f"{concat_inputs}concat=n={len(inputs)}:v=1:a=0[vout]")
    silent_input = len(inputs)

    command.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", f"{silent_input}:a:0",
        "-map_metadata", "-1",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(_FPS),
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-t", _seconds(total_duration), "-movflags", "+faststart",
        str(output),
    ])

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    timeout = max(180, min(1800, int(total_duration * 12 + 120)))
    result = subprocess.run(
        command,
        capture_output=True,
        timeout=timeout,
        creationflags=creationflags,
    )
    if result.returncode != 0:
        error = (result.stderr or b"").decode("utf-8", "ignore").strip()
        raise RuntimeError(error[-2000:] or f"ffmpeg 拼接失败，退出码 {result.returncode}")
    if not output.exists() or output.stat().st_size == 0:
        raise RuntimeError("ffmpeg 未生成有效的母带文件")


async def concat_video_attachments(
    pool: Any,
    project_id: int,
    node_id: int | None,
    parts: Sequence[Mapping[str, Any] | Any],
    ratio: str,
    display_name: str,
    meta: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Create and persist a hard-cut 480p master from existing video attachments.

    ``parts`` must contain ``id``, ``url`` and the expected ``duration_s`` for
    every source clip.  Each clip is padded with its final frame when necessary
    and then trimmed to that expected duration before concatenation.
    """
    from .. import oss

    validated = _validated_parts(parts)
    width, height = _output_size(ratio)
    durations = [part["duration_s"] for part in validated]
    duration_s = sum(durations)

    with tempfile.TemporaryDirectory(prefix="episode-master-") as temp_dir:
        directory = Path(temp_dir)
        inputs = [directory / f"part-{index:03d}.video" for index in range(1, len(validated) + 1)]
        async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT) as client:
            await asyncio.gather(*(
                _download_part(client, part["url"], target)
                for part, target in zip(validated, inputs, strict=True)
            ))

        output = directory / "master.mp4"
        await asyncio.to_thread(_run_concat, inputs, durations, output, width, height)
        content = await asyncio.to_thread(output.read_bytes)

    digest = hashlib.sha256(content).hexdigest()
    stored_url = await oss.store_bytes(content, prefix=f"episode_flash/{project_id}", ext=".mp4")
    if not stored_url:
        raise RuntimeError("母带拼接成功，但 OSS 永久存储失败；分组视频附件均已保留")

    source_attachment_ids = [part["id"] for part in validated]
    attachment_meta = {
        **dict(meta or {}),
        "type": "episode_flash_master",
        "origin": "concat",
        "name": display_name,
        "source_attachment_ids": source_attachment_ids,
        "duration_s": duration_s,
        "sha256": digest,
        "bytes": len(content),
        "concat": {
            "part_count": len(validated),
            "part_durations_s": durations,
            "width": width,
            "height": height,
            "fps": _FPS,
            "pixel_format": "yuv420p",
            "video_codec": "h264/libx264",
            "audio_codec": "aac",
            "audio": "silent-stereo-48000hz",
            "transition": "hard-cut",
        },
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
        "拼接母带已落库 attachment=%s project=%s parts=%s duration=%ss bytes=%s",
        attachment_id, project_id, len(validated), _seconds(duration_s), len(content),
    )
    return {
        "id": attachment_id,
        "name": display_name,
        "kind": "video",
        "url": stored_url,
        "duration_s": duration_s,
        "meta": attachment_meta,
    }
