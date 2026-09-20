"""Contract for the pro.character.sheet asset type only."""
from .base import AssetType

CHARACTER_SHEET = AssetType(
    "pro.character.sheet", "角色设定图", "image", "element",
    "content_attachments + workflow_artifacts", ("generate", "read", "reference"),
    ("project", "character", "sheet", "design"),
    async_default=True, allows_variant=True,
    target_ref_kind="element",
    target_content_kind="character",
    context_bindings=(("element_id", "target.id"), ("character_name", "target.name"),
                      ("project_id", "target.project_id")),
)
