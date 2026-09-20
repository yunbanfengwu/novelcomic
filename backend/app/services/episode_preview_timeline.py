"""Pure helpers for the script ↔ preview ↔ storyboard alignment layer.

The preview video is deliberately treated as evidence, not as the screenplay
or as a finished shot.  A timeline version contains immutable script events
and editable preview segments.  Saving an edit creates a new attachment
version; these helpers validate the client-supplied ranges and rebuild all
story text from server-owned events so a browser cannot inject new plot facts.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

MAX_SEGMENTS = 100
MIN_SEGMENT_S = 0.02
_EPSILON = 0.011


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} 必须是有限数字")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是有限数字") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} 必须是有限数字")
    return result


def _strings(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _beat_no(beat: Mapping[str, Any], fallback: int) -> int:
    raw = beat.get("no", fallback)
    try:
        number = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"第{fallback}个剧情节拍的编号无效") from exc
    if number <= 0:
        raise ValueError(f"第{fallback}个剧情节拍的编号无效")
    return number


def _range_for_beat(
    beat: Mapping[str, Any],
    index: int,
    count: int,
    duration_s: float,
    prefix: str,
) -> tuple[float, float]:
    raw_start = beat.get(f"{prefix}_start_s")
    raw_end = beat.get(f"{prefix}_end_s")
    if raw_start is None or raw_end is None:
        return index * duration_s / count, (index + 1) * duration_s / count
    start = _number(raw_start, f"{prefix}_start_s")
    end = _number(raw_end, f"{prefix}_end_s")
    if start < 0 or end <= start:
        raise ValueError(f"剧情节拍{index + 1}的{prefix}时间范围无效")
    return start, end


def _default_script_bands(
    events: Sequence[Mapping[str, Any]],
    duration_s: float,
) -> list[dict[str, Any]]:
    """Project story durations into one contiguous preview-time script track."""
    weights = [
        max(
            0.0,
            _number(event.get("story_end_s"), "story_end_s")
            - _number(event.get("story_start_s"), "story_start_s"),
        )
        for event in events
    ]
    total = sum(weights)
    if total <= 0:
        weights = [1.0] * len(events)
        total = float(len(events))

    bands: list[dict[str, Any]] = []
    cursor = 0.0
    for index, (event, weight) in enumerate(zip(events, weights, strict=True)):
        end = duration_s if index == len(events) - 1 else cursor + duration_s * weight / total
        bands.append({
            "event_id": str(event["id"]),
            "start_s": round(cursor, 6),
            "end_s": round(end, 6),
        })
        cursor = end
    return bands


def build_initial_timeline(
    *,
    master_attachment_id: int,
    batch_id: str,
    master_meta: Mapping[str, Any],
    frames: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Normalise every experiment mode into one editable preview timeline."""
    beats = list(master_meta.get("beats") or [])
    if not beats:
        beats = [
            beat
            for group in (master_meta.get("groups") or [])
            for beat in (group.get("beats") or [])
        ]
    if not 1 <= len(beats) <= MAX_SEGMENTS:
        raise ValueError("母带必须包含1至100个剧情节拍")

    duration_s = _number(master_meta.get("duration_s") or 5, "duration_s")
    if duration_s <= 0:
        raise ValueError("母带时长必须大于0")
    source_total_s = _number(
        master_meta.get("source_minutes") or 8, "source_minutes"
    ) * 60

    frames_by_beat: dict[int, list[dict[str, Any]]] = {}
    for frame in frames:
        try:
            number = int(frame.get("beat_no") or 0)
            attachment_id = int(frame.get("attachment_id") or 0)
        except (TypeError, ValueError):
            continue
        if number <= 0 or attachment_id <= 0 or not frame.get("url"):
            continue
        frames_by_beat.setdefault(number, []).append({
            "attachment_id": attachment_id,
            "url": str(frame["url"]),
            "at_s": round(_number(frame.get("at_s") or 0, "frame.at_s"), 6),
            "role": str(frame.get("role") or "action"),
        })

    events: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    seen_beat_nos: set[int] = set()
    for index, raw_beat in enumerate(beats):
        if not isinstance(raw_beat, Mapping):
            raise ValueError(f"第{index + 1}个剧情节拍不是对象")
        beat = dict(raw_beat)
        beat_no = _beat_no(beat, index + 1)
        if beat_no in seen_beat_nos:
            raise ValueError(f"剧情节拍编号{beat_no}重复")
        seen_beat_nos.add(beat_no)
        event_id = f"E{beat_no:03d}"
        preview_start, preview_end = _range_for_beat(
            beat, index, len(beats), duration_s, "output"
        )
        story_start, story_end = _range_for_beat(
            beat, index, len(beats), source_total_s, "source"
        )
        preview_start = max(0.0, min(duration_s, preview_start))
        preview_end = max(0.0, min(duration_s, preview_end))
        if preview_end - preview_start < MIN_SEGMENT_S:
            raise ValueError(f"剧情节拍{beat_no}的母带时间过短")

        event = {
            "id": event_id,
            "seq": index + 1,
            "beat_no": beat_no,
            "stage": str(beat.get("stage") or "").strip(),
            "scene": str(beat.get("scene") or "").strip(),
            "shot_size": str(beat.get("shot_size") or "中景").strip(),
            "picture": str(beat.get("picture") or "").strip(),
            "evidence": str(beat.get("evidence") or "").strip(),
            "characters": _strings(beat.get("characters")),
            "story_start_s": round(story_start, 3),
            "story_end_s": round(story_end, 3),
        }
        events.append(event)
        candidates = frames_by_beat.get(beat_no, [])
        selected = candidates[0] if candidates else None
        segments.append({
            "id": f"S{index + 1:03d}",
            "seq": index + 1,
            "script_event_ids": [event_id],
            "beat_nos": [beat_no],
            "preview_start_s": round(preview_start, 6),
            "preview_end_s": round(preview_end, 6),
            "picture": event["picture"],
            "evidence": event["evidence"],
            "stage": event["stage"],
            "scene": event["scene"],
            "shot_size": event["shot_size"],
            "characters": event["characters"],
            "candidate_frames": candidates,
            "selected_frame_attachment_id": (
                selected["attachment_id"] if selected else None
            ),
            "selected_frame_url": selected["url"] if selected else None,
            "confidence": 1.0,
            "locked": False,
            "converted_shot_id": None,
        })

    # Planned outputs can contain tiny floating point gaps.  The editable
    # timeline is a complete partition of the actual preview media.
    segments[0]["preview_start_s"] = 0.0
    for index in range(1, len(segments)):
        boundary = round(segments[index]["preview_start_s"], 6)
        segments[index - 1]["preview_end_s"] = boundary
    segments[-1]["preview_end_s"] = round(duration_s, 6)
    return {
        "type": "episode_preview_timeline",
        "source_attachment_id": master_attachment_id,
        "batch_id": batch_id,
        "mode": str(master_meta.get("mode") or "flash20"),
        "duration_s": duration_s,
        "source_minutes": int(master_meta.get("source_minutes") or 8),
        "events": events,
        "script_bands": _default_script_bands(events, duration_s),
        "segments": segments,
        "status": "draft",
        "preserved": True,
    }


def _event_lookup(timeline: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    events = timeline.get("events") or []
    by_id: dict[str, dict[str, Any]] = {}
    order: dict[str, int] = {}
    for index, event in enumerate(events):
        if not isinstance(event, Mapping) or not event.get("id"):
            raise ValueError("时间线脚本事件无效")
        event_id = str(event["id"])
        by_id[event_id] = dict(event)
        order[event_id] = index
    if not by_id:
        raise ValueError("时间线没有脚本事件")
    return by_id, order


def normalise_edited_segments(
    timeline: Mapping[str, Any],
    raw_segments: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Validate editable fields and rebuild narrative fields from server events."""
    if (
        not isinstance(raw_segments, Sequence)
        or isinstance(raw_segments, (str, bytes, bytearray))
        or not 1 <= len(raw_segments) <= MAX_SEGMENTS
    ):
        raise ValueError("时间线必须包含1至100个片段")
    duration_s = _number(timeline.get("duration_s"), "duration_s")
    event_by_id, event_order = _event_lookup(timeline)
    all_candidates: dict[int, dict[str, Any]] = {}
    for segment in timeline.get("segments") or []:
        for frame in segment.get("candidate_frames") or []:
            try:
                attachment_id = int(frame.get("attachment_id") or 0)
            except (TypeError, ValueError):
                continue
            if attachment_id > 0:
                all_candidates[attachment_id] = dict(frame)

    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    previous_end = 0.0
    previous_event_order = -1
    for index, raw in enumerate(raw_segments):
        if not isinstance(raw, Mapping):
            raise ValueError(f"第{index + 1}个时间线片段无效")
        segment_id = str(raw.get("id") or f"S{index + 1:03d}").strip()
        if not segment_id or segment_id in ids:
            raise ValueError("时间线片段ID为空或重复")
        ids.add(segment_id)
        start = _number(raw.get("preview_start_s"), "preview_start_s")
        end = _number(raw.get("preview_end_s"), "preview_end_s")
        if start < 0 or end > duration_s + _EPSILON or end - start < MIN_SEGMENT_S:
            raise ValueError(f"片段{index + 1}的时间范围无效")
        if index == 0 and abs(start) > _EPSILON:
            raise ValueError("第一个片段必须从0秒开始")
        if index > 0 and abs(start - previous_end) > _EPSILON:
            raise ValueError("相邻片段必须首尾相接，不能重叠或留空")
        previous_end = end

        event_ids = _strings(raw.get("script_event_ids"))
        if not event_ids or any(event_id not in event_by_id for event_id in event_ids):
            raise ValueError(f"片段{index + 1}关联了无效脚本事件")
        indices = sorted(event_order[event_id] for event_id in event_ids)
        if indices[0] < previous_event_order:
            raise ValueError("脚本事件必须保持原剧情顺序")
        previous_event_order = indices[-1]
        ordered_ids = sorted(set(event_ids), key=event_order.__getitem__)
        linked_events = [event_by_id[event_id] for event_id in ordered_ids]

        candidate_ids = []
        for event in linked_events:
            beat_no = int(event.get("beat_no") or 0)
            for base_segment in timeline.get("segments") or []:
                if beat_no in (base_segment.get("beat_nos") or []):
                    candidate_ids.extend(
                        int(frame["attachment_id"])
                        for frame in (base_segment.get("candidate_frames") or [])
                        if frame.get("attachment_id")
                    )
        candidate_ids = list(dict.fromkeys(candidate_ids))
        candidates = [all_candidates[item] for item in candidate_ids if item in all_candidates]
        selected_raw = raw.get("selected_frame_attachment_id")
        selected_id = int(selected_raw) if selected_raw not in (None, "") else None
        if selected_id is not None and selected_id not in candidate_ids:
            raise ValueError(f"片段{index + 1}选择的参考帧不属于关联脚本事件")
        selected = all_candidates.get(selected_id) if selected_id else None

        def join(field: str, separator: str = "；") -> str:
            values = [str(event.get(field) or "").strip() for event in linked_events]
            return separator.join(dict.fromkeys(value for value in values if value))

        result.append({
            "id": segment_id,
            "seq": index + 1,
            "script_event_ids": ordered_ids,
            "beat_nos": [int(event.get("beat_no") or 0) for event in linked_events],
            "preview_start_s": round(0.0 if index == 0 else start, 6),
            "preview_end_s": round(end, 6),
            "picture": join("picture"),
            "evidence": join("evidence", "\n"),
            "stage": join("stage", " / "),
            "scene": join("scene", " / "),
            "shot_size": str(linked_events[0].get("shot_size") or "中景"),
            "characters": list(dict.fromkeys(
                character
                for event in linked_events
                for character in _strings(event.get("characters"))
            )),
            "candidate_frames": candidates,
            "selected_frame_attachment_id": selected_id,
            "selected_frame_url": selected.get("url") if selected else None,
            "confidence": 0.95,
            "locked": bool(raw.get("locked")),
            "converted_shot_id": None,
        })
    if abs(previous_end - duration_s) > _EPSILON:
        raise ValueError("最后一个片段必须覆盖到母带结尾")
    result[-1]["preview_end_s"] = round(duration_s, 6)
    return result


def normalise_script_bands(
    timeline: Mapping[str, Any],
    raw_bands: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Validate the independently draggable script track as a full partition."""
    duration_s = _number(timeline.get("duration_s"), "duration_s")
    event_by_id, event_order = _event_lookup(timeline)
    if raw_bands is None:
        existing = timeline.get("script_bands")
        if isinstance(existing, Sequence) and not isinstance(
            existing, (str, bytes, bytearray)
        ):
            raw_bands = existing
        else:
            return _default_script_bands(list(event_by_id.values()), duration_s)
    if (
        not isinstance(raw_bands, Sequence)
        or isinstance(raw_bands, (str, bytes, bytearray))
        or len(raw_bands) != len(event_by_id)
    ):
        raise ValueError("脚本轨必须完整包含全部脚本事件")

    result: list[dict[str, Any]] = []
    previous_end = 0.0
    seen: set[str] = set()
    for index, raw in enumerate(raw_bands):
        if not isinstance(raw, Mapping):
            raise ValueError(f"第{index + 1}个脚本轨片段无效")
        event_id = str(raw.get("event_id") or "").strip()
        if event_id not in event_by_id or event_id in seen:
            raise ValueError(f"第{index + 1}个脚本轨片段关联了无效事件")
        if event_order[event_id] != index:
            raise ValueError("脚本轨事件必须保持原剧情顺序")
        seen.add(event_id)
        start = _number(raw.get("start_s"), "script_band.start_s")
        end = _number(raw.get("end_s"), "script_band.end_s")
        if start < 0 or end > duration_s + _EPSILON or end - start < MIN_SEGMENT_S:
            raise ValueError(f"第{index + 1}个脚本轨片段的时间范围无效")
        if index == 0 and abs(start) > _EPSILON:
            raise ValueError("脚本轨必须从0秒开始")
        if index > 0 and abs(start - previous_end) > _EPSILON:
            raise ValueError("相邻脚本轨片段必须首尾相接")
        result.append({
            "event_id": event_id,
            "start_s": round(0.0 if index == 0 else start, 6),
            "end_s": round(end, 6),
        })
        previous_end = end
    if abs(previous_end - duration_s) > _EPSILON:
        raise ValueError("脚本轨必须覆盖到母带结尾")
    result[-1]["end_s"] = round(duration_s, 6)
    return result


__all__ = [
    "MAX_SEGMENTS",
    "MIN_SEGMENT_S",
    "build_initial_timeline",
    "normalise_edited_segments",
    "normalise_script_bands",
]
