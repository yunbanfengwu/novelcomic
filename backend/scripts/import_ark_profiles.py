"""从 cocc-work 库静默导入 ARK 模型档（key 不打印、不落日志）。

导入：Seedream 4.0/4.5（image）+ Seedance 1.5 Pro/2.0（video），并激活
Seedream 4.0 与 Seedance 1.5 Pro（cocc-work 已验证的默认档）。
用法：backend/.venv/Scripts/python.exe scripts/import_ark_profiles.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg  # noqa: E402

from app.settings import settings  # noqa: E402

COCC_DSN = "postgresql://postgres:123456@localhost:5432/ai_worker_v3_pg"

# (cocc-work profile id, purpose, 显示名, activate)
IMPORTS = [
    ("doubao-image",                  "image", "火山 Seedream 4.0", True),
    ("doubao-seedream-4-5",           "image", "火山 Seedream 4.5", False),
    ("doubao-seedance-1-5-pro",       "video", "火山 Seedance 1.5 Pro", True),
    ("doubao-seedance",               "video", "火山 Seedance 2.0", False),
    ("doubao-seedance-fast",          "video", "火山 Seedance 2.0 Fast", False),
    ("doubao-seedance-1-0-pro",       "video", "火山 Seedance 1.0 Pro", False),
    ("doubao-seedance-1-0-pro-fast",  "video", "火山 Seedance 1.0 Pro Fast", False),
    ("doubao-seedance-1-0-lite-i2v",  "video", "火山 Seedance 1.0 Lite i2v", False),
    ("doubao-seedance-1-0-lite-t2v",  "video", "火山 Seedance 1.0 Lite t2v", False),
]


async def main() -> None:
    src = await asyncpg.connect(COCC_DSN)
    dst = await asyncpg.connect(settings.DATABASE_URL)
    for src_id, purpose, name, activate in IMPORTS:
        row = await src.fetchrow(
            "SELECT base_url, api_key, model_name FROM model_profiles WHERE id=$1", src_id
        )
        if not row or not row["api_key"]:
            print(f"SKIP {name}: 源档不存在或无 key")
            continue
        # 覆盖 seed 的占位"火山 Seedream/Seedance"或按名 upsert
        placeholder = {"image": "火山 Seedream", "video": "火山 Seedance"}[purpose]
        existing = await dst.fetchrow(
            "SELECT id FROM model_profiles WHERE purpose=$1 AND name IN ($2,$3)",
            purpose, name, placeholder,
        )
        if existing:
            await dst.execute(
                "UPDATE model_profiles SET name=$2, provider='ark', base_url=$3, api_key=$4, "
                "model_name=$5, updated_at=now() WHERE id=$1",
                existing["id"], name, row["base_url"], row["api_key"], row["model_name"],
            )
            pid = existing["id"]
            print(f"UPDATED {name} (model={row['model_name']}, key=已导入)")
        else:
            r = await dst.fetchrow(
                "INSERT INTO model_profiles (purpose, provider, name, base_url, api_key, model_name) "
                "VALUES ($1,'ark',$2,$3,$4,$5) RETURNING id",
                purpose, name, row["base_url"], row["api_key"], row["model_name"],
            )
            pid = r["id"]
            print(f"INSERTED {name} (model={row['model_name']}, key=已导入)")
        if activate:
            await dst.execute("UPDATE model_profiles SET is_active=FALSE WHERE purpose=$1", purpose)
            await dst.execute("UPDATE model_profiles SET is_active=TRUE WHERE id=$1", pid)
            print(f"ACTIVATED {name} ← 当前 {purpose} 模型")
    await src.close()
    await dst.close()
    print("DONE.")


if __name__ == "__main__":
    asyncio.run(main())
