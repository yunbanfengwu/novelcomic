"""任务队列 worker：N 协程并发取任务 → flow.run_task（统一守卫管线，业务在 steps.py）。

火山 ARK 图/视频为异步范式：Step.run 提交任务返回 external_id → status=waiting_external
→ 释放 worker 槽位；poller 每 5s 收割（flow.finish_external 回调该 Step 的 next），
并顺带跑超时对账（flow.check_stalled）。启动时先对账（flow.reconcile：热重载杀在途的自愈）。
"""
import asyncio
import logging
import traceback

import asyncpg

from .. import media
from . import flow
from . import steps  # noqa: F401 — 导入即注册全部 Step

log = logging.getLogger("worker")

# 任务全部 IO-bound（等 LLM/生图/视频接口），6 并发不增加本机负担；
# 上限受 db 池(max_size=10)与供应商限流约束，再往上调先扩池
_CONCURRENCY = 6


async def _poll_external(pool: asyncpg.Pool) -> None:
    """收割 waiting_external 任务（ARK 异步）→ 回调 Step.next（CAS 防重复收割）。"""
    rows = await pool.fetch(
        "SELECT * FROM task_queue WHERE status='waiting_external' AND external_task_id IS NOT NULL"
    )
    for task in rows:
        try:
            res = await media.check_ark_video(task["external_task_id"])
        except Exception as e:  # noqa: BLE001 — 单次查询失败下轮再试
            log.warning("poll %s 查询失败: %s", task["external_task_id"], e)
            continue
        if res["status"] in ("done", "failed"):
            if res["status"] == "failed":
                # 审计闭环：外部任务生成失败，把该单 accepted 提交记录标为 failed
                await pool.execute(
                    "UPDATE gen_logs SET status='failed', error=$2, finished_at=now() "
                    "WHERE task_id=$1 AND status='accepted'",
                    task["id"], str(res.get("error") or "")[:500],
                )
            await flow.finish_external(pool, task, res)
            log.info("task %s external %s", task["id"], res["status"])


async def _worker_one(pool: asyncpg.Pool, stop: asyncio.Event, wid: int) -> None:
    while not stop.is_set():
        task = None
        async with pool.acquire() as conn:
            async with conn.transaction():
                task = await conn.fetchrow(
                    "SELECT * FROM task_queue WHERE status='pending' "
                    "ORDER BY priority DESC, created_at LIMIT 1 FOR UPDATE SKIP LOCKED"
                )
                if task:
                    await conn.execute(
                        "UPDATE task_queue SET status='running', started_at=now() WHERE id=$1",
                        task["id"],
                    )
        if not task:
            try:
                await asyncio.wait_for(stop.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
            continue
        await flow.notify_task(pool, task["id"])  # pending→running 广播（SSE）
        try:
            await flow.run_task(pool, task)
        except Exception as e:  # noqa: BLE001 — 框架自身异常兜底，不炸 worker
            log.error("worker#%d task %s 框架异常: %s\n%s", wid, task["id"], e, traceback.format_exc())
            try:
                await flow._fail(pool, task, f"框架异常 {type(e).__name__}: {e}")  # noqa: SLF001
            except Exception:  # noqa: BLE001
                pass


async def worker_loop(pool: asyncpg.Pool, stop: asyncio.Event) -> None:
    """启动对账 + N 个执行协程 + 1 个外部任务 poller（收割+超时对账）。"""
    await flow.reconcile(pool)
    log.info("task worker started (%d workers + poller), steps=%s",
             _CONCURRENCY, sorted(flow.STEPS))

    async def poller() -> None:
        while not stop.is_set():
            try:
                await _poll_external(pool)
                await flow.check_stalled(pool)
                await flow.reconcile_waiting_deps(pool)  # 依赖 DAG 崩溃窗口/竞态对账
            except Exception as e:  # noqa: BLE001
                log.error("poller error: %s", e)
            try:
                await asyncio.wait_for(stop.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass

    await asyncio.gather(
        *(_worker_one(pool, stop, i) for i in range(_CONCURRENCY)),
        poller(),
    )
