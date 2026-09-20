"""Contract for the com.video asset type only."""
from .base import AssetType

COMMON_VIDEO = AssetType(
    "com.video", "通用视频", "video", "none",
    "content_attachments + workflow_artifacts", ("upload", "generate", "read", "reference"),
    ("common", "media"),
    async_default=True,
)
