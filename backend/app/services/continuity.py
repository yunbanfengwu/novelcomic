"""Phase 1 确定性连续性校验；不调用模型，不通过则禁止下游生成。"""
from __future__ import annotations

from typing import Any

HARD_LOCK_KEYS = (
    "location_id", "scene_version", "story_day", "time_of_day", "weather",
    "lighting_direction", "color_temperature", "palette", "camera_axis",
    "environment_type", "enclosure", "ceiling_state", "primary_light_source",
    "architectural_topology",
)
LEGAL_TRANSITIONS = {
    "explicit_script_action", "explicit_time_jump", "scene_change",
    "approved_director_override", "match_cut", "montage",
}

_OUTDOOR_FLIGHT_TOKENS = (
    "飞向雷暴", "飞向云", "飞入云", "冲入云", "飞向天空", "飞上天空",
    "一跃而起，飞", "一跃而起飞", "腾空飞向", "take off", "fly into",
)
_EXIT_TRANSITION_TOKENS = (
    "走出", "离开", "穿过门", "穿过拱门", "通过出口", "来到露台",
    "抵达室外", "来到室外", "冲出", "飞出", "出口", "门外",
)


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if not isinstance(value, dict):
        return {prefix: value}
    out: dict[str, Any] = {}
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(child, dict):
            out.update(_flatten(child, path))
        else:
            out[path] = child
    return out


def validate_shot(
    hard_locks: dict[str, Any],
    before_state: dict[str, Any],
    action_transition: dict[str, Any],
    after_state: dict[str, Any],
    script_evidence: dict[str, Any],
    previous_after_state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    before, after = _flatten(before_state), _flatten(after_state)
    previous = _flatten(previous_after_state or {})
    evidence_text = str(script_evidence.get("quote") or script_evidence.get("text") or "").strip()
    event_ids = script_evidence.get("event_ids") or []
    if not evidence_text or not event_ids:
        errors.append({"code": "missing_script_evidence", "message": "Shot 缺少可追溯剧情证据"})

    # 室内空间不能为了满足“飞向天空/云墙”等动作而被模型擅自掀掉屋顶。
    # 若剧本确实要从室内转到室外，必须先显式写出经过门/出口的场景转换。
    if (
        hard_locks.get("enclosure") == "interior"
        and any(token.lower() in evidence_text.lower() for token in _OUTDOOR_FLIGHT_TOKENS)
        and not any(token.lower() in evidence_text.lower() for token in _EXIT_TRANSITION_TOKENS)
    ):
        errors.append({
            "code": "indoor_action_breaks_enclosure",
            "message": "室内场景出现直接飞向天空/云层的动作，缺少门、出口或场景转换证据",
        })

    for key in HARD_LOCK_KEYS:
        expected = hard_locks.get(key)
        if expected is None:
            continue
        if key in before and before[key] != expected:
            errors.append({"code": "scene_hard_lock_before", "field": key,
                           "expected": expected, "actual": before[key]})
        if key in after and after[key] != expected:
            errors.append({"code": "scene_hard_lock_after", "field": key,
                           "expected": expected, "actual": after[key]})

    for key, expected in previous.items():
        if key in before and before[key] != expected:
            errors.append({"code": "adjacent_state_mismatch", "field": key,
                           "expected": expected, "actual": before[key]})

    changes = {
        key: {"from": before.get(key), "to": value}
        for key, value in after.items() if key in before and before[key] != value
    }
    declared = action_transition.get("changes") or {}
    transition_type = action_transition.get("type")
    for key, actual in changes.items():
        declaration = declared.get(key)
        if not declaration:
            errors.append({"code": "undeclared_state_change", "field": key, **actual})
            continue
        if transition_type not in LEGAL_TRANSITIONS:
            errors.append({"code": "illegal_transition_type", "field": key,
                           "transition_type": transition_type})
        if not evidence_text:
            errors.append({"code": "state_change_without_evidence", "field": key})
        if declaration.get("from") != actual["from"] or declaration.get("to") != actual["to"]:
            errors.append({"code": "transition_declaration_mismatch", "field": key,
                           "actual": actual, "declared": declaration})
    return errors


def assert_generation_ready(*args: Any, **kwargs: Any) -> None:
    errors = validate_shot(*args, **kwargs)
    if errors:
        codes = ", ".join(str(e["code"]) for e in errors)
        raise ValueError(f"连续性校验未通过，禁止生成：{codes}")
