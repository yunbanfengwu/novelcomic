"""Contract for the pro.shot.script asset type only."""
from .base import AssetType

SHOT_SCRIPT = AssetType(
    "pro.shot.script", "分镜脚本", "text", "content_node",
    "content_nodes.meta + workflow_artifacts", ("generate", "read"),
    ("project", "shot", "script"),
    target_ref_kind="content_node",
    target_content_kind="shot",
    context_bindings=(("shot_id", "target.id"), ("chapter_id", "target.parent_id"),
                      ("project_id", "target.project_id")),
    target_scope_levels=(("volume", "卷", False), ("chapter", "章", False)),
)
