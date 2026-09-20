"""Contract for the pro.scene.sheet asset type only."""
from .base import AssetType

SCENE_SHEET = AssetType(
    "pro.scene.sheet", "场景设定图", "image", "element",
    "content_attachments + workflow_artifacts", ("generate", "read", "reference"),
    ("project", "scene", "sheet", "design"),
    async_default=True, allows_variant=True,
    target_ref_kind="element",
    target_content_kind="scene",
    context_bindings=(
        ("element_id", "target.id"),
        ("scene_name", "target.name"),
        ("project_id", "target.project_id"),
    ),
)
