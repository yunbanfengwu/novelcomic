"""进程内事件总线：任务状态变更 / 流式拆镜逐镜产出 → SSE 推送给前端。

单进程假设与 flow.enqueue 的 app 级幂等去重一致（uvicorn 单 worker 部署）；
多进程扩展时换 Postgres LISTEN/NOTIFY，订阅接口不变。

背压策略：慢消费者队列满即丢事件（不阻塞发布方）——SSE 重连时服务端
先发全量快照（tasks snapshot），丢失的中间事件靠快照收敛，不追溯补发。
"""
import asyncio
import logging
from contextlib import contextmanager
from typing import Any, Iterator

log = logging.getLogger("events")

_QUEUE_SIZE = 256
_subs: dict[int, set[asyncio.Queue]] = {}


def publish(project_id: int | None, event: dict[str, Any]) -> None:
    """向某项目的所有订阅者广播事件。project_id 为空（全局任务如音色样本）不推送。"""
    if not project_id:
        return
    for q in _subs.get(project_id, ()):  # set 迭代期间不会被修改（同一事件循环内无 await）
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("events: project %s 订阅者队列满，丢弃事件 %s", project_id, event.get("type"))


@contextmanager
def subscribe(project_id: int) -> Iterator[asyncio.Queue]:
    """订阅某项目的事件流（SSE 端点用）：with 退出自动清理。"""
    q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_SIZE)
    _subs.setdefault(project_id, set()).add(q)
    try:
        yield q
    finally:
        subs = _subs.get(project_id)
        if subs:
            subs.discard(q)
            if not subs:
                _subs.pop(project_id, None)
