"""挂载点归宿注册表（2026-09-18 唯一事实来源）。

画布挂载点支持哪些归宿、每种归宿怎么落库，全部在这里注册。两个通用存储形态：

- ``project_field``：写 ``content_projects.config`` 的一个字段（项目封面 → cover_url、
  项目预告片 → trailer_url）。适合「整个项目共有一份」的产物；
- ``asset``：写 ``workflow_artifacts``，语义与生成节点自带的节点级落库完全一致
  （asset_type + subject_kind/subject_id + variant + version 自增），
  合同直接来自资产类型注册表（app/assets）——新增资产类型码自动成为可用归宿。

**新增一个归宿 = 在 _BUILTIN 加一行（或新增一个资产类型码），触发路径零改动**：
挂载点执行体、run 收尾补漏、连线即落库端点、旧 end.store 绑定——全部只认这张表
（apply_mount_binding 按表分派）。任何地方都不许再写 ``target == "xxx"`` 特判。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..assets import all_types


@dataclass(frozen=True, slots=True)
class MountTarget:
    """一个产物归宿：码、显示名、需要的业务对象、产物形态、存储形态。"""
    code: str          # 归宿码：'project_cover' 或资产类型码（'pro.scene.sheet'…）
    label: str         # 显示名（与前端 MOUNT_TARGETS 的 label 对齐）
    subject: str       # 需要的业务对象：project | element | content_node | attachment | none
    media: str         # 产物形态：image | video | text | …（前端据此取 src/video）
    kind: str          # 存储形态：project_field | asset
    field: str | None = None   # kind=project_field：config 里的字段名


def _project_field(code: str, label: str, field: str, media: str) -> MountTarget:
    return MountTarget(code=code, label=label, subject="project",
                       media=media, kind="project_field", field=field)


# 项目级字段归宿：整项目共有一份，写进项目 config
PROJECT_COVER = _project_field("project_cover", "项目封面", "cover_url", "image")
PROJECT_TRAILER = _project_field("project_trailer", "项目预告片", "trailer_url", "video")

# 资产类型归宿：直接从资产类型注册表生成——资产合同加一条，挂载点自动可用
_ASSET_TARGETS = tuple(
    MountTarget(code=a.code, label=a.name, subject=a.subject_kind,
                media=a.media_kind, kind="asset")
    for a in all_types())

_ALL: tuple[MountTarget, ...] = (PROJECT_COVER, PROJECT_TRAILER) + _ASSET_TARGETS
_BY_CODE: dict[str, MountTarget] = {t.code: t for t in _ALL}


def all_targets() -> tuple[MountTarget, ...]:
    """全部已注册归宿（画布可选清单的后端事实来源）。"""
    return _ALL


def get_target(code: str) -> MountTarget | None:
    """按码取归宿；未注册返回 None（调用方统一按 unknown target skipped）。"""
    return _BY_CODE.get(str(code or "").strip())
