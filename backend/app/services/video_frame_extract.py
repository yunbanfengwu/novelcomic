"""Extract one representative JPEG for every planned episode beat.

This service is intentionally independent from the experiment-16 slate
pipeline.  It never looks for black frames or shot numbers: the requested
timeline is the sole source of truth.  HTTP inputs are downloaded exactly
once to a temporary file and local inputs are opened read-only.
"""

from __future__ import annotations

import asyncio
import io
import math
import os
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import httpx
from PIL import Image

_MAX_FRAMES = 100
_MAX_SOURCE_BYTES = 1024 * 1024 * 1024
_DOWNLOAD_TIMEOUT = httpx.Timeout(300.0, connect=15.0)


def _value(item: Mapping[str, Any] | Any, key: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(key)
    try:
        return item[key]
    except (KeyError, TypeError):
        return getattr(item, key, None)


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def _validated_duration(value: Any) -> float:
    duration = _finite_number(value, "duration_s")
    if duration <= 0:
        raise ValueError("duration_s must be greater than zero")
    return duration


def _validated_dimension(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer between 16 and 4096")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer between 16 and 4096") from exc
    if not math.isfinite(number) or not number.is_integer() or not 16 <= number <= 4096:
        raise ValueError(f"{field} must be an integer between 16 and 4096")
    return int(number)


def _beat_number(beat: Mapping[str, Any] | Any, fallback: int) -> int:
    raw = _value(beat, "no")
    if raw is None:
        raw = _value(beat, "beat_no")
    if raw is None:
        raw = _value(beat, "shot_no")
    if raw is None:
        return fallback
    if isinstance(raw, bool):
        raise ValueError(f"beat {fallback} has an invalid beat number")
    try:
        number = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"beat {fallback} has an invalid beat number") from exc
    if not math.isfinite(number) or not number.is_integer() or number <= 0:
        raise ValueError(f"beat {fallback} has an invalid beat number")
    return int(number)


def _timeline_points(
    beats: Sequence[Mapping[str, Any] | Any],
    duration_s: float,
) -> list[tuple[int, float]]:
    if (
        not isinstance(beats, Sequence)
        or isinstance(beats, (str, bytes, bytearray))
        or not beats
    ):
        raise ValueError("beats must contain between 1 and 100 items")
    if len(beats) > _MAX_FRAMES:
        raise ValueError("beats must contain between 1 and 100 items")

    equal_span = duration_s / len(beats)
    points: list[tuple[int, float]] = []
    seen_numbers: set[int] = set()
    previous_at = -1.0
    for index, beat in enumerate(beats, start=1):
        beat_no = _beat_number(beat, index)
        if beat_no in seen_numbers:
            raise ValueError(f"duplicate beat number: {beat_no}")

        raw_start = _value(beat, "output_start_s")
        raw_end = _value(beat, "output_end_s")
        if raw_start is None or raw_end is None:
            # A missing boundary falls back to this beat's equal share of the
            # declared output duration.  Supplied boundaries on other beats
            # remain authoritative.
            at_s = (index - 0.5) * equal_span
        else:
            start_s = _finite_number(raw_start, f"beat {beat_no} output_start_s")
            end_s = _finite_number(raw_end, f"beat {beat_no} output_end_s")
            if start_s < 0 or end_s <= start_s or end_s > duration_s:
                raise ValueError(
                    f"beat {beat_no} timeline must satisfy "
                    "0 <= output_start_s < output_end_s <= duration_s"
                )
            at_s = start_s + (end_s - start_s) / 2.0

        if not 0 <= at_s < duration_s:
            raise ValueError(f"beat {beat_no} extraction time is outside the video")
        if at_s <= previous_at:
            raise ValueError("beat extraction times must be strictly increasing")

        points.append((beat_no, at_s))
        seen_numbers.add(beat_no)
        previous_at = at_s
    return points


def _local_source(video_url: str | os.PathLike[str]) -> Path | None:
    if isinstance(video_url, os.PathLike):
        candidate = Path(video_url)
    elif isinstance(video_url, str) and video_url.strip():
        # ``urlparse('C:\\video.mp4')`` treats ``C`` as a URI scheme, so
        # recognise an ordinary Windows drive path before parsing URLs.
        if len(video_url) >= 2 and video_url[0].isalpha() and video_url[1] == ":":
            candidate = Path(video_url)
        else:
            parsed = urlparse(video_url)
            if parsed.scheme.lower() in {"http", "https"}:
                return None
            if parsed.scheme.lower() == "file":
                candidate = Path(url2pathname(unquote(parsed.path)))
            elif parsed.scheme:
                raise ValueError("video_url must be a local path or an HTTP(S) URL")
            else:
                candidate = Path(video_url)
    else:
        raise ValueError("video_url must be a local path or an HTTP(S) URL")

    candidate = candidate.expanduser().resolve()
    if not candidate.is_file():
        raise ValueError(f"local video does not exist or is not a file: {candidate}")
    size = candidate.stat().st_size
    if size <= 0:
        raise ValueError("local video is empty")
    if size > _MAX_SOURCE_BYTES:
        raise ValueError("video exceeds the 1 GiB safety limit")
    return candidate


async def _download_http(url: str, target: Path) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("video_url must be a local path or an HTTP(S) URL")

    written = 0
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, trust_env=False) as client:
        async with client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            declared_size = response.headers.get("content-length")
            if declared_size:
                try:
                    if int(declared_size) > _MAX_SOURCE_BYTES:
                        raise RuntimeError("video exceeds the 1 GiB safety limit")
                except ValueError:
                    pass
            with target.open("wb") as output:
                async for chunk in response.aiter_bytes():
                    written += len(chunk)
                    if written > _MAX_SOURCE_BYTES:
                        raise RuntimeError("video exceeds the 1 GiB safety limit")
                    output.write(chunk)
    if written == 0:
        raise RuntimeError("downloaded video is empty")


def _extract_one(
    source: Path,
    target: Path,
    at_s: float,
    width: int,
    height: int,
) -> bytes:
    from imageio_ffmpeg import get_ffmpeg_exe

    filters = (
        f"scale={width}:{height}:"
        "force_original_aspect_ratio=decrease:force_divisible_by=2,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        "setsar=1"
    )
    command = [
        get_ffmpeg_exe(),
        "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{at_s:.9f}",
        "-i", str(source),
        "-map", "0:v:0", "-an", "-sn", "-dn",
        "-map_metadata", "-1",
        "-vf", filters,
        "-frames:v", "1", "-q:v", "2",
        str(target),
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
        raise RuntimeError(error[-2000:] or f"ffmpeg frame extraction failed at {at_s:.6f}s")
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f"video has no decodable frame at {at_s:.6f}s")

    raw = target.read_bytes()
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            if image.format != "JPEG":
                raise RuntimeError("ffmpeg output is not JPEG")
            if image.size != (width, height):
                raise RuntimeError(
                    f"unexpected JPEG size {image.width}x{image.height}; "
                    f"expected {width}x{height}"
                )
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"invalid JPEG extracted at {at_s:.6f}s") from exc
    return raw


async def extract_timeline_frames(
    video_url: str | os.PathLike[str],
    beats: Sequence[Mapping[str, Any] | Any],
    duration_s: int | float,
    *,
    width: int = 854,
    height: int = 480,
) -> list[dict[str, Any]]:
    """Return one midpoint JPEG per beat, in strictly increasing time order.

    If either output boundary is missing for a beat, that beat uses the
    midpoint of its equal share of ``duration_s``.  At most 100 beats are
    accepted.  The source file and caller-owned data are never modified.
    """
    duration = _validated_duration(duration_s)
    output_width = _validated_dimension(width, "width")
    output_height = _validated_dimension(height, "height")
    points = _timeline_points(beats, duration)
    local_source = _local_source(video_url)

    with tempfile.TemporaryDirectory(prefix="episode-frame-extract-") as temp_dir:
        directory = Path(temp_dir)
        if local_source is None:
            source = directory / "source.video"
            await _download_http(str(video_url), source)
        else:
            source = local_source

        frames: list[dict[str, Any]] = []
        for index, (beat_no, at_s) in enumerate(points, start=1):
            target = directory / f"beat-{index:03d}.jpg"
            jpeg_bytes = await asyncio.to_thread(
                _extract_one,
                source,
                target,
                at_s,
                output_width,
                output_height,
            )
            frames.append({
                "beat_no": beat_no,
                "at_s": at_s,
                "jpeg_bytes": jpeg_bytes,
                "width": output_width,
                "height": output_height,
            })
    return frames


__all__ = ["extract_timeline_frames"]
