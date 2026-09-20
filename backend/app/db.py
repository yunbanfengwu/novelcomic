"""asyncpg 连接池 + 启动时幂等应用 schema。"""
from pathlib import Path

import asyncpg

from .settings import settings

_SQL_DIR = Path(__file__).resolve().parent.parent / "sql"

pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global pool
    pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=10)
    # 幂等建表：schema 文件按文件名顺序全部执行
    async with pool.acquire() as conn:
        for f in sorted(_SQL_DIR.glob("*.sql")):
            await conn.execute(f.read_text(encoding="utf-8"))
    return pool


async def close_pool() -> None:
    global pool
    if pool:
        await pool.close()
        pool = None


def get_pool() -> asyncpg.Pool:
    assert pool is not None, "pool not initialized"
    return pool
