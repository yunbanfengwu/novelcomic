"""Split a slate-marked master strictly from its preset beat timeline.

This module deliberately does *not* inspect pixels or try to recognise the
black ``SHOT NN`` boards.  Experiment 16 already placed each board at the
known frame ``round(beat.output_start_s * source_fps)``.  We therefore remove
exactly that scheduled frame before producing one clip per beat.  The source
file is opened read-only and is never modified or deleted.
"""

from __future__ import annotations

import asyncio
import math
import os
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import httpx

_OUTPUT_FPS = 24
_OUTPUT_WIDTH = 854
_OUTPUT_HEIGHT = 480
_MAX_SOURCE_BYTES = 1024 * 1024 * 1024
_DOWNLOAD_TIMEOUT = httpx.Timeout(300.0, connect=15.0)
_FRAME_PROGRESS = re.compile(r"^frame=(\d+)\s*$", re.MULTILINE)


def _value(item: Mapping[str, Any] | Any, key: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(key)
    try:
        return item[key]
    except (KeyError, TypeError):
        return getattr(item, key, None)


def _validated_fps(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("fps 必须是正数")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("fps 必须是正数") from exc
    if not math.isfinite(number) or number <= 0 or number > 240:
        raise ValueError("fps 必须是 0 到 240 之间的有限正数")
    return number


def _validated_frame_count(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("frame_count 必须是正整数")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("frame_count 必须是正整数") from exc
    if not math.isfinite(number) or number <= 0 or not number.is_integer():
        raise ValueError("frame_count 必须是正整数")
    return int(number)


def _normalised_fps(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def _local_source(video_url: str | os.PathLike[str]) -> Path | None:
    """Return a local source path, or ``None`` for HTTP(S) input."""
    if isinstance(video_url, os.PathLike):
        candidate = Path(video_url)
    elif isinstance(video_url, str):
        parsed = urlparse(video_url)
        if parsed.scheme.lower() in {"http", "https"}:
            return None
        if parsed.scheme.lower() == "file":
            candidate = Path(url2pathname(unquote(parsed.path)))
        else:
            candidate = Path(video_url)
    else:
        raise ValueError("video_url 必须是本地路径或 HTTP(S) URL")

    candidate = candidate.expanduser().resolve()
    if not candidate.is_file():
        raise ValueError(f"本地母带不存在或不是文件：{candidate}")
    size = candidate.stat().st_size
    if size <= 0:
        raise ValueError("本地母带为空")
    if size > _MAX_SOURCE_BYTES:
        raise ValueError("母带超过 1 GiB 安全上限")
    return candidate


async def _download_http(url: str, target: Path) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("video_url 必须是本地路径或 HTTP(S) URL")

    written = 0
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, trust_env=False) as client:
        async with client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            declared_size = response.headers.get("content-length")
            if declared_size:
                try:
                    if int(declared_size) > _MAX_SOURCE_BYTES:
                        raise RuntimeError("母带超过 1 GiB 安全上限")
                except ValueError:
                    pass
            with target.open("wb") as output:
                async for chunk in response.aiter_bytes():
                    written += len(chunk)
                    if written > _MAX_SOURCE_BYTES:
                        raise RuntimeError("母带超过 1 GiB 安全上限")
                    output.write(chunk)
    if written == 0:
        raise RuntimeError("下载到的母带为空")


def _probe_frame_count(source: Path) -> int:
    """Count video packets without decoding; the result is exact for the CFR master."""
    from imageio_ffmpeg import get_ffmpeg_exe

    command = [
        get_ffmpeg_exe(),
        "-hide_banner", "-loglevel", "error", "-nostats",
        "-progress", "pipe:1",
        "-i", str(source),
        "-map", "0:v:0", "-an", "-c:v", "copy",
        "-f", "null", os.devnull,
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=300,
        creationflags=creationflags,
    )
    if result.returncode != 0:
        error = (result.stderr or "").strip()
        raise RuntimeError(error[-2000:] or f"ffmpeg 读取母带帧数失败，退出码 {result.returncode}")
    matches = _FRAME_PROGRESS.findall(result.stdout or "")
    if not matches or int(matches[-1]) <= 0:
        raise RuntimeError("无法从母带读取有效视频帧数")
    return int(matches[-1])


def _planned_segments(
    beats: Sequence[Mapping[str, Any] | Any],
    source_fps: float,
    source_frame_count: int,
) -> tuple[list[int], list[dict[str, Any]]]:
    if not isinstance(beats, Sequence) or isinstance(beats, (str, bytes)) or not beats:
        raise ValueError("beats 至少需要一个分镜")
    if len(beats) > 999:
        raise ValueError("一次最多拆分 999 个分镜")

    boundary_frames: list[int] = []
    shot_numbers: list[int] = []
    previous_time = -1.0
    previous_boundary = -1
    for index, beat in enumerate(beats, start=1):
        raw_time = _value(beat, "output_start_s")
        try:
            time_s = float(raw_time)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"第 {index} 镜缺少有效 output_start_s") from exc
        if not math.isfinite(time_s) or time_s < 0:
            raise ValueError(f"第 {index} 镜 output_start_s 必须是非负有限数")
        if time_s <= previous_time:
            raise ValueError("分镜 output_start_s 必须严格递增")

        boundary = int(round(time_s * source_fps))
        if boundary <= previous_boundary:
            raise ValueError("相邻分镜按 fps 换算后落在同一帧或发生倒序")
        if boundary >= source_frame_count:
            raise ValueError(f"第 {index} 镜边界帧 {boundary} 超出母带范围")

        raw_no = _value(beat, "no")
        if raw_no is None:
            shot_no = index
        else:
            if isinstance(raw_no, bool):
                raise ValueError(f"第 {index} 镜缺少有效镜号")
            try:
                number = float(raw_no)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"第 {index} 镜缺少有效镜号") from exc
            if not math.isfinite(number) or not number.is_integer() or not 1 <= number <= 9999:
                raise ValueError(f"第 {index} 镜号必须是 1 到 9999 的整数")
            shot_no = int(number)

        boundary_frames.append(boundary)
        shot_numbers.append(shot_no)
        previous_time = time_s
        previous_boundary = boundary

    if boundary_frames[0] != 0:
        raise ValueError("第 1 镜 output_start_s 必须从母带第 0 帧开始")
    if len(set(shot_numbers)) != len(shot_numbers):
        raise ValueError("镜号不得重复")

    segments: list[dict[str, Any]] = []
    for index, (shot_no, boundary) in enumerate(zip(shot_numbers, boundary_frames, strict=True)):
        # Beat 1 has no preceding board.  From beat 2 onward, the scheduled
        # boundary itself is the one-frame board and content begins after it.
        start_frame = boundary if index == 0 else boundary + 1
        end_frame = (
            boundary_frames[index + 1]
            if index + 1 < len(boundary_frames)
            else source_frame_count
        )
        content_frames = end_frame - start_frame
        if content_frames < 1:
            raise ValueError(
                f"第 {shot_no} 镜排除边界镜号板后没有剧情帧："
                f"start_frame={start_frame}, end_frame={end_frame}"
            )
        segments.append({
            "shot_no": shot_no,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "frame_count": content_frames,
            "start_s": start_frame / source_fps,
            "end_s": end_frame / source_fps,
        })
    return boundary_frames, segments


def _run_segment(source: Path, segment: Mapping[str, Any], video_path: Path, keyframe_path: Path) -> None:
    """Encode one exact source-frame range and its first included frame."""
    from imageio_ffmpeg import get_ffmpeg_exe

    start_frame = int(segment["start_frame"])
    end_frame = int(segment["end_frame"])
    frame_count = int(segment["frame_count"])
    common = (
        f"scale={_OUTPUT_WIDTH}:{_OUTPUT_HEIGHT}:"
        "force_original_aspect_ratio=decrease:force_divisible_by=2,"
        f"pad={_OUTPUT_WIDTH}:{_OUTPUT_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        "setsar=1"
    )
    filters = (
        f"[0:v:0]select='between(n,{start_frame},{end_frame - 1})',"
        f"setpts=N/({_OUTPUT_FPS}*TB),{common},format=yuv420p[clip];"
        f"[0:v:0]select='eq(n,{start_frame})',{common}[keyframe]"
    )
    command = [
        get_ffmpeg_exe(),
        "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source),
        "-filter_complex", filters,
        "-map", "[clip]", "-an",
        "-map_metadata", "-1",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(_OUTPUT_FPS),
        "-frames:v", str(frame_count), "-movflags", "+faststart",
        str(video_path),
        "-map", "[keyframe]", "-frames:v", "1", "-q:v", "2",
        str(keyframe_path),
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        command,
        capture_output=True,
        timeout=300,
        creationflags=creationflags,
    )
    if result.returncode != 0:
        error = (result.stderr or b"").decode("utf-8", "ignore").strip()
        raise RuntimeError(error[-2000:] or f"ffmpeg 拆分第 {segment['shot_no']} 镜失败")
    if not video_path.is_file() or video_path.stat().st_size == 0:
        raise RuntimeError(f"第 {segment['shot_no']} 镜没有生成有效 MP4")
    if not keyframe_path.is_file() or keyframe_path.stat().st_size == 0:
        raise RuntimeError(f"第 {segment['shot_no']} 镜没有生成首帧 JPEG")

    actual_frames = _probe_frame_count(video_path)
    if actual_frames != frame_count:
        raise RuntimeError(
            f"第 {segment['shot_no']} 镜帧数校验失败：计划 {frame_count}，实际 {actual_frames}"
        )


async def split_by_preset_timeline(
    video_url: str | os.PathLike[str],
    beats: Sequence[Mapping[str, Any] | Any],
    *,
    fps: int | float = 24,
    frame_count: int | None = None,
) -> dict[str, Any]:
    """Return one 480p/24fps mini MP4 per beat using only preset boundaries.

    ``fps`` and ``frame_count`` should come from the immutable master
    attachment's ``meta.spec`` when available.  If ``frame_count`` is omitted,
    it is probed without decoding.  ``boundary_frames`` contains every planned
    beat start; boundary 0 is ordinary content, while boundaries 2..N are the
    known one-frame boards and are excluded.  Segment ``end_frame`` is
    exclusive.  No source object, file, frame, or attachment is deleted.
    """
    source_fps = _validated_fps(fps)
    local_source = _local_source(video_url)

    with tempfile.TemporaryDirectory(prefix="episode-preset-split-") as temp_dir:
        directory = Path(temp_dir)
        if local_source is None:
            source = directory / "source.video"
            await _download_http(str(video_url), source)
        else:
            source = local_source

        source_frame_count = (
            _validated_frame_count(frame_count)
            if frame_count is not None
            else await asyncio.to_thread(_probe_frame_count, source)
        )
        boundary_frames, planned = _planned_segments(beats, source_fps, source_frame_count)

        result_segments: list[dict[str, Any]] = []
        for index, segment in enumerate(planned, start=1):
            video_path = directory / f"shot-{index:03d}.mp4"
            keyframe_path = directory / f"shot-{index:03d}-first.jpg"
            await asyncio.to_thread(_run_segment, source, segment, video_path, keyframe_path)
            result_segments.append({
                **segment,
                "video_bytes": await asyncio.to_thread(video_path.read_bytes),
                "keyframe_bytes": await asyncio.to_thread(keyframe_path.read_bytes),
            })

    total_content_frames = sum(segment["frame_count"] for segment in result_segments)
    return {
        "fps": _normalised_fps(source_fps),
        "source_frame_count": source_frame_count,
        "boundary_frames": boundary_frames,
        "total_content_frames": total_content_frames,
        "segments": result_segments,
    }


__all__ = ["split_by_preset_timeline"]
