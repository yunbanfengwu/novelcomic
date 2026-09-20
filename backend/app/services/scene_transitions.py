"""连续主体感知的跨场景转场检查。

场景视觉合同在换场时必须重置；角色与叙事状态只在同一具名主体继续出现时继承。
本模块只做高置信度确定性门禁，复杂语义交给 subject-aware-scene-transitions Skill。
"""
from __future__ import annotations

import re
from typing import Any

_FLIGHT = ("飞行", "飞向", "飞入", "腾空", "翱翔", "冲入云", "穿越云墙", "扇动翅膀")
_GROUND = ("步行", "走向", "站在", "坐在", "议事厅", "室内", "大厅内", "房间内")
_LEGAL_EVIDENCE = (
    "随后", "之后", "片刻后", "数小时后", "第二天", "翌日", "转场", "蒙太奇",
    "匹配剪辑", "抵达", "来到", "登上", "骑上", "跨上", "乘坐", "起飞",
    "载着", "驮着", "搭乘", "离开后",
)
_FLIGHT_CAPABLE = (
    "龙", "飞龙", "鸟", "双翼", "羽翼", "有翼", "翅膀", "天使",
    "飞行能力", "flight-capable",
)
_LIKELY_GROUNDED = ("人类", "少女", "少年", "男人", "女人", "警察", "侦探", "学生", "human")

SKILL_RULES_FALLBACK = """【连续主体感知转场】
判断跨场景是否需要过渡前，先比较相邻镜头的具名角色：
1. 没有连续角色：允许直接切到新叙事线、平行线或无人物环境建立镜，不得机械补过渡。
2. 有连续角色：换场时重置场景光线/天气/建筑，但继承角色的载具/骑乘、装备、伤势、约束与能力状态。
3. 普通且易懂的地点移动允许省略；只有新状态依赖未展示的骑乘、起飞、载具、换装、受伤、被捕等使能动作，或能力矛盾会造成理解断裂时，才补最小过渡节拍或写明合法时间跳跃/蒙太奇。
4. 禁止把群组中某一角色的能力复制给所有角色；写“岚牙载着洛汐飞行”，不要写“洛汐和岚牙扇动翅膀飞行”。
"""


def _chars(shot: dict[str, Any]) -> list[str]:
    return [str(x).strip() for x in (shot.get("characters") or []) if str(x).strip()]


def _corpus(shot: dict[str, Any]) -> str:
    parts = [
        shot.get("scene"), shot.get("action"), shot.get("description"), shot.get("summary"),
        shot.get("dialogue"),
    ]
    parts.extend(c.get("action") for c in (shot.get("cuts") or []) if isinstance(c, dict))
    return " ".join(str(x or "") for x in parts)


def _same_name(a: str, b: str) -> bool:
    return a == b or (len(a) >= 2 and len(b) >= 2 and (a in b or b in a))


def continuing_subjects(previous: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """返回跨边界继续出现的具名角色；无交集即新叙事线，可直接切场。"""
    return list(dict.fromkeys(
        a for a in _chars(previous)
        if any(_same_name(a, b) for b in _chars(current))
    ))


def _scene_changed(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    a = str(previous.get("scene") or "").strip()
    b = str(current.get("scene") or "").strip()
    return bool(a and b and a != b)


def _explicit_transition(current: dict[str, Any], corpus: str) -> bool:
    transition = current.get("transition") or current.get("scene_transition") or {}
    if isinstance(transition, dict) and transition.get("mode") in {
        "same_subject_ellipsis", "explicit_time_jump", "match_cut_or_montage",
        "approved_director_override",
    }:
        return True
    return any(token in corpus for token in _LEGAL_EVIDENCE)


def _has_mixed_flight_capability(shot: dict[str, Any], subjects: list[str]) -> bool:
    """只有提供角色档案且能高置信识别“可飞+通常不可飞”混合组时才做能力门禁。

    无档案时不猜，避免把两条龙、两个天使或两名飞行英雄误判。
    """
    profiles = shot.get("_character_profiles") or {}
    texts = [str(profiles.get(name) or "") for name in subjects]
    if not any(texts):
        return False
    capable = any(any(token in text for token in _FLIGHT_CAPABLE) for text in texts)
    grounded = any(
        any(token in text for token in _LIKELY_GROUNDED)
        and not any(token in text for token in _FLIGHT_CAPABLE)
        for text in texts
    )
    return capable and grounded


def analyze_boundary(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """判断相邻镜是否需要过渡；不同主体换场永远不因“缺过渡”报错。"""
    overlap = continuing_subjects(previous, current)
    result: dict[str, Any] = {
        "scene_changed": _scene_changed(previous, current),
        "continuing_subjects": overlap,
        "transition_mode": "same_scene",
        "errors": [],
    }
    if not result["scene_changed"]:
        return result
    if not overlap:
        result["transition_mode"] = "new_lane_direct_cut"
        return result

    before = _corpus(previous)
    after = _corpus(current)
    if _explicit_transition(current, after):
        result["transition_mode"] = "same_subject_ellipsis"
        return result

    flight_started = any(x in after for x in _FLIGHT) and not any(x in before for x in _FLIGHT)
    grounded_before = any(x in before for x in _GROUND)
    if flight_started and grounded_before:
        result["transition_mode"] = "bridge_required"
        result["errors"].append({
            "code": "same_subject_unexplained_transport_jump",
            "message": "连续角色从地面/室内状态直接变为飞行，缺少骑乘、载具、起飞、时间跳跃或导演省略证据",
            "subjects": overlap,
        })

    # “A和B飞行/扇动翅膀”会把坐骑能力复制给骑手。要求明确谁承载、谁骑乘。
    joined = r"(?:和|与|、)".join(re.escape(x) for x in overlap[:2])
    if (
        len(overlap) >= 2
        and _has_mixed_flight_capability(current, overlap)
        and re.search(joined + r".{0,12}(?:飞行|飞向|扇动翅膀)", after)
    ):
        if not any(token in after for token in ("载着", "驮着", "骑在", "乘坐", "搭乘")):
            result["transition_mode"] = "bridge_required"
            result["errors"].append({
                "code": "ambiguous_shared_locomotion_capability",
                "message": "多人被合写为共同飞行，未明确骑手/坐骑或载具关系，可能把飞行能力错误赋给人类角色",
                "subjects": overlap,
            })
    if not result["errors"]:
        result["transition_mode"] = "same_subject_ellipsis"
    return result


def validate_scene_boundaries(shots: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for previous, current in zip(shots, shots[1:]):
        audit = analyze_boundary(previous, current)
        for item in audit["errors"]:
            errors.append(
                f"镜{current.get('shot_no')}: {item['code']}：{item['message']}"
            )
    return errors
