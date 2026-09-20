"""Contract for the pro.shot.video asset type only."""
from .base import AssetType

SHOT_VIDEO = AssetType(
    "pro.shot.video", "分镜视频", "video", "content_node",
    "content_attachments + workflow_artifacts", ("generate", "read", "reference"),
    ("project", "shot", "video"),
    async_default=True,
    target_ref_kind="content_node",
    target_content_kind="shot",
    context_bindings=(("shot_id", "target.id"), ("chapter_id", "target.parent_id"),
                      ("project_id", "target.project_id")),
    target_scope_levels=(("volume", "卷", False), ("chapter", "章", False)),
)
