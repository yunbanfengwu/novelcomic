"""The only authority for asset-type codes. Do not infer semantics from code segments."""
from __future__ import annotations

from .base import AssetType
from .com_image import COMMON_IMAGE
from .com_video import COMMON_VIDEO
from .pro_character_sheet import CHARACTER_SHEET
from .pro_prop_sheet import PROP_SHEET
from .pro_scene_brief import SCENE_BRIEF
from .pro_scene_sheet import SCENE_SHEET
from .pro_shot_keyframe import SHOT_KEYFRAME
from .pro_shot_script import SHOT_SCRIPT
from .pro_shot_video import SHOT_VIDEO

_ALL = (SCENE_BRIEF, SCENE_SHEET, CHARACTER_SHEET, PROP_SHEET,
        SHOT_SCRIPT, SHOT_KEYFRAME, SHOT_VIDEO, COMMON_IMAGE, COMMON_VIDEO)
_BY_CODE = {item.code: item for item in _ALL}


def get(code: str) -> AssetType:
    try:
        return _BY_CODE[code]
    except KeyError as exc:
        raise ValueError(f"Unknown asset type: {code}") from exc


def all_types() -> tuple[AssetType, ...]:
    return _ALL


def legacy_type(role: str | None, target_kind: str | None) -> str | None:
    return {
        "scene.sheet": "pro.scene.sheet",
        "shot.keyframe": "pro.shot.keyframe",
        "character.sheet": "pro.character.sheet",
        "prop.sheet": "pro.prop.sheet",
    }.get(role or "")
