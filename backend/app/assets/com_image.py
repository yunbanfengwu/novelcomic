"""Contract for the com.image asset type only."""
from .base import AssetType

COMMON_IMAGE = AssetType(
    "com.image", "通用图片", "image", "none",
    "content_attachments + workflow_artifacts", ("upload", "generate", "read", "reference"),
    ("common", "media"),
    async_default=True,
)
