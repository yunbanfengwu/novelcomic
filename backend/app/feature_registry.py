"""功能 code 的唯一权威（模型管理→功能配置）：后端写死功能清单，配置只配"每个功能用哪些模型、什么顺序"。

- 功能 = 一类生成能力（九宫格生成/关键帧生成/…），比 purpose 大类更细一层；
- 每个功能可在系统管理→模型管理→功能配置里挂一组同 purpose 的模型档并排序，
  运行时取第一个（models_registry.get_for_feature），没配置则回退该 purpose 的 active 档；
- 新增功能只能加在这里（照 assets/registry.py 的模式），禁止在别处散落功能字符串。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Feature:
    code: str
    label: str
    purpose: str  # 允许挂载的模型大类（model_profiles.purpose）
    hint: str = ""


FEATURES: tuple[Feature, ...] = (
    Feature("nine_grid", "九宫格生成", "image",
            "故事板九宫格（3×3 九格同图）；对应画布模板 nine-grid-keyframe-reference"),
    Feature("keyframe", "关键帧生成", "image", "镜级首帧/尾帧关键帧（单镜出图路径）"),
    Feature("storyboard_grid", "宫格故事板", "image", "章级分镜总览宫格（gen_overview_grid）"),
    Feature("scene_sheet", "场景图生成", "image", "空场景基准图与角色站位图（两阶段场景链路）"),
    Feature("element_sheet", "要素设定图", "image", "角色/道具/场景设定图（含镜级前置的自动补齐）"),
    Feature("canvas_image", "画布出图", "image", "画布 gen 节点未指定模型/功能时的自由出图"),
)

_BY_CODE = {f.code: f for f in FEATURES}


def get(code: str) -> Feature:
    try:
        return _BY_CODE[code]
    except KeyError as exc:
        raise ValueError(f"Unknown feature code: {code}") from exc


def all_features() -> tuple[Feature, ...]:
    return FEATURES
