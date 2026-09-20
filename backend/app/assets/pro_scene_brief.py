"""Contract for the pro.scene.brief asset type only."""
from .base import AssetType

SCENE_BRIEF = AssetType(
    "pro.scene.brief", "场景简介", "text", "element",
    "content_elements.meta + workflow_artifacts", ("generate", "read"),
    ("project", "scene", "brief"),
    target_ref_kind="element",
    target_content_kind="scene",
    context_bindings=(("element_id", "target.id"), ("scene_name", "target.name"),
                      ("project_id", "target.project_id")),
)
