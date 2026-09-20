"""Contract for the pro.prop.sheet asset type only."""
from .base import AssetType

PROP_SHEET = AssetType(
    "pro.prop.sheet", "道具设定图", "image", "element",
    "content_attachments + workflow_artifacts", ("generate", "read", "reference"),
    ("project", "prop", "sheet", "design"),
    async_default=True, allows_variant=True,
    target_ref_kind="element",
    target_content_kind="prop",
    context_bindings=(("element_id", "target.id"), ("prop_name", "target.name"),
                      ("project_id", "target.project_id")),
)
