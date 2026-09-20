"""一次性迁移：把已存产物（第三方 CDN URL）转存到自己的 OSS 并回写。

扫三处：content_attachments.url、分镜 meta.storyboard_image_url/video_url、要素 meta.sheet_url。
已在 OSS（bucket 域名）的跳过。用法：backend/.venv/Scripts/python.exe scripts/migrate_cdn_to_oss.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg  # noqa: E402

from app.oss import store_url  # noqa: E402
from app.settings import settings  # noqa: E402


def _is_oss(url: str) -> bool:
    return settings.OSS_BUCKET and f"{settings.OSS_BUCKET}.{settings.OSS_ENDPOINT}" in (url or "")


async def main() -> None:
    conn = await asyncpg.connect(settings.DATABASE_URL)
    moved = 0

    # ① 附件表
    for row in await conn.fetch("SELECT id, url, kind FROM content_attachments WHERE url IS NOT NULL"):
        if _is_oss(row["url"]):
            continue
        prefix = {"storyboard_image": "storyboard", "video": "video"}.get(row["kind"], "sheet")
        new = await store_url(row["url"], prefix)
        if new != row["url"]:
            await conn.execute("UPDATE content_attachments SET url=$2 WHERE id=$1", row["id"], new)
            moved += 1
            print(f"attachment #{row['id']} → {new}")

    # ② 分镜 meta
    for row in await conn.fetch(
        "SELECT id, meta FROM content_nodes WHERE kind='shot' "
        "AND (meta ? 'storyboard_image_url' OR meta ? 'video_url')"
    ):
        meta = json.loads(row["meta"]) if isinstance(row["meta"], str) else dict(row["meta"])
        patch = {}
        for key, prefix in (("storyboard_image_url", "storyboard"), ("video_url", "video")):
            url = meta.get(key)
            if url and not _is_oss(url):
                new = await store_url(url, prefix)
                if new != url:
                    patch[key] = new
        if patch:
            await conn.execute(
                "UPDATE content_nodes SET meta = meta || $2::jsonb WHERE id=$1",
                row["id"], json.dumps(patch, ensure_ascii=False),
            )
            moved += len(patch)
            print(f"shot #{row['id']} → {patch}")

    # ③ 要素设定图
    for row in await conn.fetch(
        "SELECT id, meta FROM content_elements WHERE meta ? 'sheet_url'"
    ):
        meta = json.loads(row["meta"]) if isinstance(row["meta"], str) else dict(row["meta"])
        url = meta.get("sheet_url")
        if url and not _is_oss(url):
            new = await store_url(url, "sheet")
            if new != url:
                await conn.execute(
                    "UPDATE content_elements SET meta = meta || $2::jsonb WHERE id=$1",
                    row["id"], json.dumps({"sheet_url": new}, ensure_ascii=False),
                )
                moved += 1
                print(f"element #{row['id']} → {new}")

    await conn.close()
    print(f"\nDONE. 转存 {moved} 个产物到 OSS ({settings.OSS_BUCKET})")


if __name__ == "__main__":
    asyncio.run(main())
