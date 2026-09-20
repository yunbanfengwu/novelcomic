"""统一生成管线框架（2026-07-11 定稿，docs/arch/generation-flow-guards.md）。

所有生成功能同一架构：前置(before) → 执行(run) → next(收尾) —— Vue 路由守卫模式。
- before = beforeEach 守卫：查依赖，能补则补（确定性前置），补不了 raise Blocked
- run    = 渲染：纯执行（LLM/生图/提交视频）；外部异步任务返回 external_id 即释放槽位
- next   = afterEach + next() 流转：质检/校验/产物回写/状态推进；不合格 raise RetryStep
           （计重试次数，超限走 failed——绝不无限循环）；可 enqueue 串下游任务

框架统一负责（业务 Step 无权直接碰）：
- task_queue 状态机 (waiting_deps→)pending→running→(waiting_external→)done/failed/canceled
- 业务状态 content_nodes.meta.gen.<slot> = {state, task_id, at[, error]}，刷新页面可恢复
- 重试：attempt < Step.max_retries 且错误可重试才重排；终态错误（欠费/参数错）直接 failed
- 对账自愈：启动 reconcile（running 遗留判 failed）+ poller 周期 stalled 超时判死
  + waiting_deps 孤儿对账（子已全部终态但父计数未归零的崩溃窗口）

依赖 DAG（2026-07-13 增补，拉式目标导向）：
- Step.missing_deps 声明"我缺什么、谁能生产"→ enqueue_with_deps 一次事务递归解析成树
  （幂等去重天然合并菱形依赖：gen_video 与 gen_keyframe 共享同一个 gen_prompts 子任务）
- 子任务 done → 所有父任务 deps_remaining-1，归零由 waiting_deps 转 pending（callFun 逐级向上）
- 子任务 failed/canceled → 父任务连锁 failed（blocked: 前置失败），继续向上传播
- 每次状态转移经 notify_task 发事件总线 → SSE 推前端（events.py）
"""
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from . import events

log = logging.getLogger("flow")

# ── 预检缓存 TTL（小时）：fingerprint(源文本) + valid_until 双重有效性 ──
PROMPT_REVIEW_TTL_H = 72     # 提示词九维质检
AUDIO_PRECHECK_TTL_H = 24    # 音频预检（音色可能重捏，短一些）

MAX_CHAIN_DEPTH = 3          # Enqueue 链深度上限（防环第二保险，第一保险=同 node+kind 唯一在途）
EXTERNAL_TIMEOUT_S = 1800    # waiting_external 收割超时（ARK 视频最长约 10min，留足余量）
# 被 worker 重启打断后自动重排的次数上限（见 reconcile）：发版不该静默吃掉在途出图，
# 但"一跑就把进程带崩"的任务也不能无限自动重排。1 次足以覆盖正常发版/热重载。
MAX_RESTART_REQUEUES = 1

# 终态错误标记：命中即不重试（重试只会重复失败白烧钱）——欠费/配额/鉴权/参数类。
# 不放裸 "30001"/"balance"/"insufficient" 这类宽子串：响应体里 trace_id 的随机数字或
# 无关英文会误命中，把限流/过载错误误判成欠费终态（媒体层已按 error code 精确判欠费）
_TERMINAL_MARKERS = (
    "余额不足", "欠费", "insufficient balance", "insufficient credits", "quota",
    "invalid api key", "unauthorized", "invalidparameter", "请先装配提示词", "不存在",
)


class Blocked(Exception):
    """前置守卫阻断：依赖缺失且无法自动补齐（error 落库带 blocked: 前缀，写清缺什么）。"""


class RetryStep(Exception):
    """next 判定不符合规范要求重来。计入 attempt，超过 max_retries 落 failed。"""


class RunResult:
    """run 的产出：二选一——同步结果 result，或外部异步任务 external_id（提交即释放）。"""

    def __init__(self, result: dict[str, Any] | None = None, external_id: str | None = None):
        self.result = result or {}
        self.external_id = external_id


class Ctx:
    """一次任务执行的上下文；payload 可被 before 修改（补参考图/音频等），随任务持久化。"""

    def __init__(self, pool: asyncpg.Pool, task: Any, payload: dict[str, Any]):
        self.pool = pool
        self.task = task
        self.payload = payload
        self.task_id: int = task["id"]
        self.project_id: int | None = task["project_id"]
        self.node_id: int | None = task["node_id"]


class Step:
    """一个生成环节。子类实现 before/run/next 并 @register 注册。"""

    kind = ""
    gen_slot: str | None = None  # 业务状态槽：content_nodes.meta.gen.<slot>（需 node_id）
    max_retries = 1              # 默认只允许一次重试（用户 2026-07-11 定稿）
    timeout_s = 300              # running 超时判死（stalled 对账）
    # ── 声明式元数据（供 services/production_canvas 自省 STEPS 出镜级生产画布，不参与调度）──
    # dep_kinds：本 Step 可能派发的硬依赖前置（对齐 missing_deps 里返回的 kind，条件分支忽略）。
    # chains_to：本 Step next 里 enqueue 串出的下游 kind。二者只声明"可能的边"，真实调度仍以
    # missing_deps/next 为准。
    dep_kinds: list[str] = []
    chains_to: list[str] = []
    soft_deps: list[str] = []    # before 隐式前置：before 里就地补/关联的产物（不建独立任务）
    group: str = ""              # 分组（拆镜/提示词/生图/生视频/筹备…）
    manual: bool = False         # 仅手动触发（不进任何自动链）
    # ── 三段式内部说明（依赖单/串下游已由上面的字段表达）──
    before_notes: list[str] = []  # before 做的守卫/补齐/质检/预检（依赖之外）
    run_note: str = ""            # run 一句话：这一步真正产出什么
    next_notes: list[str] = []    # next 做的质检/校验/回写/状态推进（串下游由 chains_to 表达）

    async def missing_deps(
        self, conn: asyncpg.Connection, project_id: int | None,
        node_id: int | None, payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """依赖 DAG 的声明式前置（enqueue_with_deps 入队时调用）：返回**当前缺失**的
        前置产物的生产者任务规格 [{kind, node_id, payload, priority}]。产物已在则不返回。
        与 before 的关系：missing_deps=需要派发子任务的重依赖（LLM/生图）；
        before=就地可补的轻前置（重装配/缓存质检）与最终守卫——依赖满足后 before 仍会复核。"""
        return []

    async def before(self, ctx: Ctx) -> None:  # noqa: B027 — 默认无前置
        pass

    async def run(self, ctx: Ctx) -> RunResult:
        raise NotImplementedError

    async def next(self, ctx: Ctx, result: dict[str, Any]) -> dict[str, Any]:
        return result


STEPS: dict[str, Step] = {}


def register(step_cls: type[Step]) -> type[Step]:
    inst = step_cls()
    assert inst.kind and inst.kind not in STEPS, f"Step kind 重复或为空: {inst.kind}"
    STEPS[inst.kind] = inst
    return step_cls


# ═══════════════ 预检缓存：指纹 + 有效期 ═══════════════

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fingerprint(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def stamp_validity(result: dict[str, Any], source_text: str, ttl_h: int) -> None:
    """给预检结果盖有效性戳：源文本指纹 + 过期时间。"""
    result["fingerprint"] = fingerprint(source_text)
    result["at"] = now_iso()
    result["valid_until"] = (
        datetime.now(timezone.utc) + timedelta(hours=ttl_h)
    ).isoformat(timespec="seconds")


def cache_valid(entry: Any, source_text: str) -> bool:
    """预检缓存仍有效 = 指纹匹配（源没变）且未过期。合格与否不影响有效性——
    预检是"尽力修复+留档"而非阻断，缓存命中即免重跑。"""
    if not isinstance(entry, dict):
        return False
    if entry.get("fingerprint") != fingerprint(source_text):
        return False
    vu = entry.get("valid_until")
    return bool(vu and vu > now_iso())


# ═══════════════ 业务状态 meta.gen.<slot>（只由框架写） ═══════════════

async def set_gen_state(
    pool: asyncpg.Pool, node_id: int | None, slot: str | None,
    state: str, task_id: int | None = None, error: str | None = None,
) -> None:
    if not node_id or not slot:
        return
    entry: dict[str, Any] = {"state": state, "task_id": task_id, "at": now_iso()}
    if error:
        entry["error"] = error[:300]
    await pool.execute(
        "UPDATE content_nodes SET meta = jsonb_set("
        "  CASE WHEN meta ? 'gen' THEN meta ELSE meta || '{\"gen\":{}}'::jsonb END,"
        "  ARRAY['gen',$2::text], $3::jsonb), updated_at=now() WHERE id=$1",
        node_id, slot, json.dumps(entry, ensure_ascii=False),
    )


# ═══════════════ 任务事件（SSE 推送）：状态转移统一经 notify_task 广播 ═══════════════

# 在途状态（worker 可领取或等待中）：幂等去重与前端"进行中"判定共用同一口径
LIVE_STATUSES = ("waiting_deps", "pending", "running", "waiting_external")

_SUMMARY_SQL = (
    "SELECT t.id, t.project_id, t.node_id, t.kind, t.status, t.progress, t.error, t.attempt, "
    "t.priority, t.deps_remaining, t.root_task_id, t.created_at, t.started_at, t.finished_at, "
    "t.payload->>'element_id' AS element_id, "
    "n.kind AS node_kind, n.title AS node_title, n.meta->>'shot_no' AS shot_no, "
    "COALESCE((SELECT array_agg(d.parent_task_id) FROM task_deps d WHERE d.child_task_id=t.id), "
    "'{}') AS parents "
    "FROM task_queue t LEFT JOIN content_nodes n ON n.id = t.node_id "
)


def _summary_dict(r: Any) -> dict[str, Any]:
    d = dict(r)
    for k in ("created_at", "started_at", "finished_at"):
        d[k] = d[k].isoformat() if d[k] else None
    d["parents"] = list(d["parents"] or [])
    # shot_no 展示号：整数直转 int；手动插入镜为小数点分字符串（如 '8.5'）时原样保留
    _sn = d["shot_no"]
    d["shot_no"] = (int(_sn) if _sn and _sn.isdigit() else (_sn or None))
    d["element_id"] = int(d["element_id"]) if d["element_id"] else None
    return d


async def fetch_task_summaries(
    pool: asyncpg.Pool, project_id: int, live_only: bool = False, recent: int = 30,
) -> list[dict[str, Any]]:
    """项目任务摘要（SSE 快照 / REST 列表共用）：在途全量 + 最近 recent 条已结束。"""
    if live_only:
        rows = await pool.fetch(
            _SUMMARY_SQL + "WHERE t.project_id=$1 AND t.status = ANY($2::text[]) ORDER BY t.id",
            project_id, list(LIVE_STATUSES),
        )
    else:
        rows = await pool.fetch(
            _SUMMARY_SQL + "WHERE t.project_id=$1 AND (t.status = ANY($2::text[]) OR t.id IN ("
            "SELECT id FROM task_queue WHERE project_id=$1 AND status NOT IN "
            "(SELECT unnest($2::text[])) ORDER BY id DESC LIMIT $3)) ORDER BY t.id",
            project_id, list(LIVE_STATUSES), recent,
        )
    return [_summary_dict(r) for r in rows]


async def notify_task(pool: asyncpg.Pool, task_id: int) -> None:
    """任务状态变更 → 事件总线（SSE 实时推前端）。查询失败不影响主流程。"""
    try:
        r = await pool.fetchrow(_SUMMARY_SQL + "WHERE t.id=$1", task_id)
        if r:
            events.publish(r["project_id"], {"type": "task", "task": _summary_dict(r)})
    except Exception as e:  # noqa: BLE001 — 推送尽力而为，不阻塞任务本体
        log.warning("notify_task %s 失败: %s", task_id, e)


async def set_progress(pool: asyncpg.Pool, task_id: int, progress: int) -> None:
    """业务 Step 上报进度（如流式拆镜逐镜推进）：只更新 running 中的任务并广播。"""
    await pool.execute(
        "UPDATE task_queue SET progress=$2 WHERE id=$1 AND status='running'",
        task_id, max(0, min(99, progress)),
    )
    await notify_task(pool, task_id)


# ═══════════════ 入队（幂等去重 + 优先级 + 链追踪） ═══════════════

def _payload_key(payload: dict[str, Any]) -> str:
    """去重判别键：要素任务按 element_id；镜批任务按 shot_ids；场景组任务（gen_scene_sheet）
    按 seg——同章不同场景组的出图任务不得互相去重；宫格故事板按 board（同章不同张各自成任务）。

    shot_ids 必须排在 seg 前面：gen_keyframes_group 的 payload **两者都带**（seg 供装配用），
    而「批量首帧」对同一场景超过 GROUP_LIMIT 时按镜号切多批入队——按 seg 判重会让第二批往后
    全部撞上第一批被判为重复，任务照样返回 200、UI 照样显示成功，实际只出了头 6 镜。
    镜批的身份就是它那组镜，不是它属于哪个场景。"""
    if payload.get("element_id") is not None:
        return str(payload["element_id"])
    if payload.get("shot_ids"):
        return "shots:" + ",".join(str(x) for x in payload["shot_ids"])
    if payload.get("seg") is not None:
        return str(payload["seg"])
    if payload.get("board") is not None:
        return f"board:{payload['board']}"
    return ""


async def _find_inflight(
    conn: asyncpg.Connection | asyncpg.Pool, kind: str, project_id: int | None,
    node_id: int | None, elem_key: str,
) -> int | None:
    r = await conn.fetchrow(
        "SELECT id FROM task_queue WHERE kind=$1 AND status = ANY($5::text[]) "
        "AND project_id IS NOT DISTINCT FROM $2 "
        "AND node_id IS NOT DISTINCT FROM $3 "
        # 分支顺序与判定条件必须与 _payload_key 逐条对齐（含 board 分支，含"空数组/JSON null
        # 不算"的口径）：两边算出的键不一致时，要么该去重的漏掉、要么不该去重的误判，两种都静默。
        # 用 ->>' ' IS NOT NULL 而不是 ? 运算符——后者对 JSON null 也为真，与 Python 侧不符。
        "AND CASE "
        "WHEN payload->>'element_id' IS NOT NULL THEN payload->>'element_id' "
        "WHEN jsonb_typeof(payload->'shot_ids')='array' "
        "     AND jsonb_array_length(payload->'shot_ids') > 0 THEN 'shots:' || "
        "  array_to_string(ARRAY(SELECT jsonb_array_elements_text(payload->'shot_ids')), ',') "
        "WHEN payload->>'seg' IS NOT NULL THEN payload->>'seg' "
        "WHEN payload->>'board' IS NOT NULL THEN 'board:' || (payload->>'board') "
        "ELSE '' END = $4 "
        "ORDER BY id LIMIT 1",
        kind, project_id, node_id, elem_key, list(LIVE_STATUSES),
    )
    return r["id"] if r else None


async def enqueue(
    pool: asyncpg.Pool, *, kind: str, project_id: int | None = None,
    node_id: int | None = None, payload: dict[str, Any] | None = None,
    priority: int = 0, root_task_id: int | None = None,
) -> dict[str, Any]:
    """统一入队（无依赖解析——next 链/批量直发用；带前置依赖走 enqueue_with_deps）。
    同 (node_id, kind[, element_id]) 已有在途任务 → 幂等返回已有任务
    （防狂点/批量与单点并发重复入队；单进程 app 级去重足够）。"""
    step = STEPS.get(kind)
    assert step is not None, f"未注册的任务类型: {kind}"
    payload = payload or {}
    tid = await _find_inflight(pool, kind, project_id, node_id, _payload_key(payload))
    if tid:
        return {"task_id": tid, "deduped": True}
    r = await pool.fetchrow(
        "INSERT INTO task_queue (project_id, node_id, kind, payload, priority, root_task_id) "
        "VALUES ($1,$2,$3,$4::jsonb,$5,$6) RETURNING id",
        project_id, node_id, kind, json.dumps(payload, ensure_ascii=False), priority, root_task_id,
    )
    await set_gen_state(pool, node_id, step.gen_slot, "pending", r["id"])
    await notify_task(pool, r["id"])
    return {"task_id": r["id"], "deduped": False}


# ═══════════════ 依赖 DAG：拉式解析（目标导向，逐级向上找依赖） ═══════════════

async def _resolve_deps(
    conn: asyncpg.Connection, *, kind: str, project_id: int | None, node_id: int | None,
    payload: dict[str, Any], priority: int, root_task_id: int | None,
    path: set[tuple[int | None, str]], planned: list[dict[str, Any]],
) -> tuple[int, bool]:
    """在同一事务内递归解析依赖并建任务树，返回 (task_id, deduped)。
    单事务原子性是正确性关键：父+子+依赖边一次提交，worker（另开事务领 pending）
    不可能只看到半棵树；子任务不可能在父边落库前完成。"""
    key = (node_id, kind)
    if key in path:  # 静态 deps 声明本应是 DAG；成环即代码 bug，宁可拒绝入队也不卡死
        raise ValueError(f"依赖解析成环: node={node_id} kind={kind}")
    step = STEPS.get(kind)
    assert step is not None, f"未注册的任务类型: {kind}"
    tid = await _find_inflight(conn, kind, project_id, node_id, _payload_key(payload))
    if tid:
        return tid, True
    missing = await step.missing_deps(conn, project_id, node_id, payload)
    r = await conn.fetchrow(
        "INSERT INTO task_queue (project_id, node_id, kind, payload, priority, root_task_id, status) "
        "VALUES ($1,$2,$3,$4::jsonb,$5,$6,'pending') RETURNING id",
        project_id, node_id, kind, json.dumps(payload, ensure_ascii=False), priority, root_task_id,
    )
    task_id = r["id"]
    planned.append({"task_id": task_id, "kind": kind, "node_id": node_id, "deps": len(missing)})
    child_ids: set[int] = set()
    for spec in missing:
        cid, _ = await _resolve_deps(
            conn, kind=spec["kind"], project_id=project_id,
            node_id=spec.get("node_id", node_id), payload=spec.get("payload") or {},
            priority=spec.get("priority", priority), root_task_id=root_task_id or task_id,
            path=path | {key}, planned=planned,
        )
        child_ids.add(cid)
    for cid in child_ids:
        await conn.execute(
            "INSERT INTO task_deps (parent_task_id, child_task_id) VALUES ($1,$2) "
            "ON CONFLICT DO NOTHING", task_id, cid,
        )
    if child_ids:
        await conn.execute(
            "UPDATE task_queue SET status='waiting_deps', deps_remaining=$2 WHERE id=$1",
            task_id, len(child_ids),
        )
    await set_gen_state(conn, node_id, step.gen_slot,
                        "waiting_deps" if child_ids else "pending", task_id)
    return task_id, False


async def enqueue_with_deps(
    pool: asyncpg.Pool, *, kind: str, project_id: int | None = None,
    node_id: int | None = None, payload: dict[str, Any] | None = None,
    priority: int = 0, root_task_id: int | None = None,
) -> dict[str, Any]:
    """带依赖解析的入队（生成类 API 的统一入口）：按 Step.missing_deps 逐级向上
    找缺失前置，一次事务派发整棵任务树。返回 planned（本次新建的全部任务，
    含子依赖）供前端展示"已自动派发 N 个前置任务"。"""
    planned: list[dict[str, Any]] = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            task_id, deduped = await _resolve_deps(
                conn, kind=kind, project_id=project_id, node_id=node_id,
                payload=payload or {}, priority=priority, root_task_id=root_task_id,
                path=set(), planned=planned,
            )
    for t in planned:  # 提交后统一广播（事务内发事件会泄露未提交状态）
        await notify_task(pool, t["task_id"])
    return {"task_id": task_id, "deduped": deduped, "planned": planned}


# ═══════════════ 编排：一次任务的完整生命周期 ═══════════════

def is_terminal(err: str) -> bool:
    low = err.lower()
    return any(m in low for m in _TERMINAL_MARKERS)


async def _persist_payload(ctx: Ctx) -> None:
    await ctx.pool.execute(
        "UPDATE task_queue SET payload=$2::jsonb WHERE id=$1",
        ctx.task_id, json.dumps(ctx.payload, ensure_ascii=False),
    )


async def _done(pool: asyncpg.Pool, ctx: Ctx, step: Step, result: dict[str, Any]) -> None:
    await pool.execute(
        "UPDATE task_queue SET status='done', progress=100, result=$2::jsonb, finished_at=now() WHERE id=$1",
        ctx.task_id, json.dumps(result, ensure_ascii=False),
    )
    await set_gen_state(pool, ctx.node_id, step.gen_slot, "done", ctx.task_id)
    await notify_task(pool, ctx.task_id)
    await release_parents(pool, ctx.task_id)


async def release_parents(pool: asyncpg.Pool, child_id: int) -> None:
    """子任务完成的向上回调（callFun→宿主）：所有等待中的父任务 deps_remaining-1，
    归零者由 waiting_deps 转 pending（worker 即可领取），并逐个广播。
    崩溃窗口（done 已落库但本函数未跑）由 reconcile_waiting_deps 周期对账兜底。"""
    rows = await pool.fetch(
        "UPDATE task_queue p SET deps_remaining = GREATEST(p.deps_remaining - 1, 0) "
        "FROM task_deps d WHERE d.parent_task_id = p.id AND d.child_task_id = $1 "
        "AND p.status = 'waiting_deps' RETURNING p.id, p.deps_remaining, p.node_id, p.kind",
        child_id,
    )
    for r in rows:
        if r["deps_remaining"] > 0:
            await notify_task(pool, r["id"])
            continue
        ok = await pool.fetchrow(
            "UPDATE task_queue SET status='pending' WHERE id=$1 AND status='waiting_deps' RETURNING id",
            r["id"],
        )
        if ok:
            step = STEPS.get(r["kind"])
            await set_gen_state(pool, r["node_id"], step.gen_slot if step else None,
                                "pending", r["id"])
            await notify_task(pool, r["id"])
            log.info("task %s 前置全部就绪（子 %s 完成），转 pending", r["id"], child_id)


async def _fail(pool: asyncpg.Pool, task: Any, err: str, step: Step | None = None) -> None:
    await pool.execute(
        "UPDATE task_queue SET status='failed', error=$2, finished_at=now() WHERE id=$1",
        task["id"], err,
    )
    if step is None:
        step = STEPS.get(task["kind"])
    if step:
        await set_gen_state(pool, task["node_id"], step.gen_slot, "failed", task["id"], error=err)
    await notify_task(pool, task["id"])
    await fail_parents(pool, task["id"], task["kind"])


async def fail_parents(pool: asyncpg.Pool, child_id: int, child_kind: str) -> None:
    """前置失败/取消的连锁向上传播：等待中的父任务确定性 failed（blocked: 前置失败）——
    没有前置产物盲跑只会白烧钱；父任务在队列面板可见失败原因后手动重试。递归向上到根。"""
    rows = await pool.fetch(
        "SELECT p.* FROM task_queue p JOIN task_deps d ON d.parent_task_id = p.id "
        "WHERE d.child_task_id = $1 AND p.status = 'waiting_deps'",
        child_id,
    )
    for p in rows:
        await _fail(pool, p, f"blocked: 前置任务 #{child_id}({child_kind}) 失败或被取消")


async def _retry_or_fail(pool: asyncpg.Pool, ctx: Ctx, step: Step, err: str) -> None:
    attempt = ctx.task["attempt"] or 0
    if attempt < step.max_retries:
        # 尝试历史留档在 payload.attempts（可观测：为什么重试了）
        ctx.payload.setdefault("attempts", []).append(
            {"attempt": attempt, "error": err[:200], "at": now_iso()})
        await pool.execute(
            "UPDATE task_queue SET status='pending', attempt=attempt+1, payload=$2::jsonb, "
            "started_at=NULL, external_task_id=NULL WHERE id=$1",
            ctx.task_id, json.dumps(ctx.payload, ensure_ascii=False),
        )
        await set_gen_state(pool, ctx.node_id, step.gen_slot, "pending", ctx.task_id)
        await notify_task(pool, ctx.task_id)
        log.info("task %s 重排 (attempt %d→%d): %s", ctx.task_id, attempt, attempt + 1, err[:120])
    else:
        await _fail(pool, ctx.task, f"重试{attempt}次后仍失败: {err}", step)


async def run_task(pool: asyncpg.Pool, task: Any) -> None:
    """worker 对每条 pending 任务调用：before → run → (waiting_external | next → done)。"""
    step = STEPS.get(task["kind"])
    if not step:
        await _fail(pool, task, f"未知任务类型: {task['kind']}")
        return
    payload = task["payload"] if isinstance(task["payload"], dict) else json.loads(task["payload"])
    ctx = Ctx(pool, task, payload)
    from .generation_provenance import finish_task_log, start_task_log
    provenance_log_id = await start_task_log(pool, task, payload)
    await set_gen_state(pool, ctx.node_id, step.gen_slot, "running", ctx.task_id)
    try:
        await step.before(ctx)
        rr = await step.run(ctx)
        if rr.external_id:
            # 提交即释放：before 补齐的 payload（audio_refs/参考图）随任务持久化，重启后收割仍可用
            ctx.payload["submitted_at"] = now_iso()
            await pool.execute(
                "UPDATE task_queue SET status='waiting_external', external_task_id=$2, "
                "payload=$3::jsonb, progress=10 WHERE id=$1",
                ctx.task_id, rr.external_id, json.dumps(ctx.payload, ensure_ascii=False),
            )
            await notify_task(pool, ctx.task_id)
            log.info("task %s → external %s (waiting_external)", ctx.task_id, rr.external_id)
            return
        await _persist_payload(ctx)
        result = await step.next(ctx, rr.result)
        await _done(pool, ctx, step, result)
        await finish_task_log(pool, provenance_log_id, "done", result=result)
    except Blocked as e:
        await finish_task_log(pool, provenance_log_id, "failed", error=f"blocked: {e}")
        await _fail(pool, task, f"blocked: {e}", step)
    except RetryStep as e:
        await finish_task_log(pool, provenance_log_id, "failed", error=f"next rejected: {e}")
        await _retry_or_fail(pool, ctx, step, f"next 判定不合格: {e}")
    except Exception as e:  # noqa: BLE001 — 分类：终态直接失败，可重试按次数
        err = f"{type(e).__name__}: {e}"
        await finish_task_log(pool, provenance_log_id, "failed", error=err)
        if is_terminal(str(e)):
            await _fail(pool, task, err, step)
        else:
            await _retry_or_fail(pool, ctx, step, err)


async def finish_external(pool: asyncpg.Pool, task: Any, ext: dict[str, Any]) -> None:
    """poller 收割外部任务后回调该 Step 的 next。CAS 防重复收割。"""
    r = await pool.fetchrow(
        "UPDATE task_queue SET status='running' WHERE id=$1 AND status='waiting_external' RETURNING id",
        task["id"],
    )
    if not r:
        return
    await notify_task(pool, task["id"])
    step = STEPS[task["kind"]]
    payload = task["payload"] if isinstance(task["payload"], dict) else json.loads(task["payload"])
    ctx = Ctx(pool, task, payload)
    from .generation_provenance import finish_latest_task_log
    try:
        if ext.get("status") == "failed":
            raise RuntimeError(f"外部任务失败: {ext.get('error')}")
        result = await step.next(ctx, ext)
        await _done(pool, ctx, step, result)
        await finish_latest_task_log(pool, task["id"], "done", result=result)
    except RetryStep as e:
        await finish_latest_task_log(
            pool, task["id"], "failed", error=f"next rejected: {e}")
        await _retry_or_fail(pool, ctx, step, f"next 判定不合格: {e}")
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        await finish_latest_task_log(pool, task["id"], "failed", error=err)
        if is_terminal(str(e)):
            await _fail(pool, task, err, step)
        else:
            await _retry_or_fail(pool, ctx, step, err)


# ═══════════════ 对账自愈 ═══════════════

async def reconcile(pool: asyncpg.Pool) -> None:
    """启动对账：上一进程的 running 任务已随进程死亡（热重载杀在途）→ 自动重排，
    重排次数用尽才判 failed 并修正业务状态。
    waiting_external 不动——外部任务还在跑，poller 可继续收割；pending 原样等待重新调度。

    自动重排（2026-07-28）：被重启打断不是业务失败，是运维事件——原先一律判 failed 且不重排，
    线上一次发版就静默打断当时所有在跑的出图/出视频，用户只能自己去队列逐个点重试。
    但不能无脑重排：若某任务本身会把进程带崩，自动重排就是无限重启循环，
    故用独立的 restart_requeues 计数封顶（不动 attempt——那是业务重试的额度）。"""
    # ① 未用尽重排额度的 → 回 pending 重新排队（保留 priority/created_at，取任务顺序不变）。
    #    error 清空：任务此刻是在途而非失败，留着红字会把 UI 带偏；事实由 restart_requeues 承载。
    requeued = await pool.fetch(
        "UPDATE task_queue SET status='pending', started_at=NULL, external_task_id=NULL, "
        "progress=0, error=NULL, restart_requeues=restart_requeues+1 "
        "WHERE status='running' AND restart_requeues < $1 RETURNING id, node_id, kind",
        MAX_RESTART_REQUEUES,
    )
    for r in requeued:
        step = STEPS.get(r["kind"])
        if step:
            await set_gen_state(pool, r["node_id"], step.gen_slot, "pending", r["id"])
        await notify_task(pool, r["id"])
    # ② 额度已用尽（上一轮重启已经救过一次，这次又被打断）→ 判 failed，留给人工重试，
    #    避免"任务一跑就崩进程"演变成重启风暴
    rows = await pool.fetch(
        "UPDATE task_queue SET status='failed', "
        "error='worker 重启，任务多次中断（已自动重排过，请手动重新发起）', "
        "finished_at=now() WHERE status='running' RETURNING id, node_id, kind",
    )
    for r in rows:
        step = STEPS.get(r["kind"])
        if step:
            await set_gen_state(pool, r["node_id"], step.gen_slot, "failed", r["id"],
                                error="worker 重启，任务多次中断")
        await notify_task(pool, r["id"])
    if requeued or rows:
        log.warning("启动对账：%d 条 running 遗留任务自动重排，%d 条重排额度用尽判 failed",
                    len(requeued), len(rows))


async def reconcile_waiting_deps(pool: asyncpg.Pool) -> None:
    """依赖 DAG 对账（启动 + poller 周期）：waiting_deps 父任务的子任务已全部终态、
    但计数未归零（done→release_parents 之间崩溃 / 解析事务提交前子任务恰好完成的竞态窗口）——
    有失败子 → 连锁 failed；全部成功 → 转 pending。无子任务边的 waiting_deps 视为孤儿转 pending。"""
    rows = await pool.fetch(
        "SELECT p.id, p.node_id, p.kind, "
        "  EXISTS (SELECT 1 FROM task_deps d JOIN task_queue c ON c.id=d.child_task_id "
        "          WHERE d.parent_task_id=p.id AND c.status IN ('failed','canceled')) AS has_failed "
        "FROM task_queue p WHERE p.status='waiting_deps' AND NOT EXISTS ("
        "  SELECT 1 FROM task_deps d JOIN task_queue c ON c.id=d.child_task_id "
        "  WHERE d.parent_task_id=p.id AND c.status = ANY($1::text[]))",
        list(LIVE_STATUSES),
    )
    for r in rows:
        if r["has_failed"]:
            await _fail(pool, r, "blocked: 前置任务失败或被取消（对账发现）")
            continue
        ok = await pool.fetchrow(
            "UPDATE task_queue SET status='pending', deps_remaining=0 "
            "WHERE id=$1 AND status='waiting_deps' RETURNING id", r["id"],
        )
        if ok:
            step = STEPS.get(r["kind"])
            await set_gen_state(pool, r["node_id"], step.gen_slot if step else None, "pending", r["id"])
            await notify_task(pool, r["id"])
            log.info("task %s 依赖对账：子任务已全部完成，转 pending", r["id"])


async def check_stalled(pool: asyncpg.Pool) -> None:
    """周期对账（poller 顺带跑）：running 超各 Step 时限 / waiting_external 超收割时限 → 判死。"""
    rows = await pool.fetch(
        "SELECT id, node_id, kind, status, attempt, payload, project_id, "
        "EXTRACT(EPOCH FROM (now() - started_at)) AS age "
        "FROM task_queue WHERE status IN ('running','waiting_external') AND started_at IS NOT NULL",
    )
    for r in rows:
        step = STEPS.get(r["kind"])
        limit = EXTERNAL_TIMEOUT_S if r["status"] == "waiting_external" else (
            step.timeout_s if step else 600)
        if r["age"] and r["age"] > limit:
            await _fail(pool, r, f"超时判死：{r['status']} 超过 {limit}s 无结果", step)
            log.warning("task %s (%s) 超时判死 (%.0fs > %ds)", r["id"], r["kind"], r["age"], limit)
