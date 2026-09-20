"""智能体规划落库（P3 · 2026-09-17 新增，纯增量）。

P3 补强：规划此前只活在 agent_runtime 单次运行的 steps 里，进程一断进度全丢。
本模块把规划变成一等实体（99 号迁移）：

- create_plan：goal → LLM 生成有序步骤 JSON（容错解析，见 parse_steps）→ 落库；
- advance：取最小未完成 seq 的步骤 → 组 charter（目标 + 前序产物 + 本步指令）→
  走 agent_runtime.run 完整循环 → 回写 step 状态与 result；
- retry_step / resume：单步重试、崩溃恢复（running 归位 pending），都不牵连整计划。

状态机（纯函数 step_transition，DB CHECK 只兜非法字面量）：
  pending  --start-->  running --done--> done
                              --fail--> failed
  failed  --retry-->   pending（显式重试，advance 不自动捡失败步）
  running --resume-->  pending（进程崩溃后的归位，幂等）
  任何跳跃（如 pending→done）都拒绝——状态错了比计划断了更难查。

授权边界：step.tool_hints 只是提示，**不构成工具授权**；真正放给 advance 的
工具白名单来自 plan.meta.tool_names（创建计划时显式声明），缺省为空=纯读思考步。
"""
from __future__ import annotations

import json
from typing import Any

import asyncpg

from .. import llm
from . import agent_runtime


class PlannerError(Exception):
    """规划层可预期失败（对调用方 422，不是 500）。"""


# ── 纯函数：步骤 JSON 容错解析 ─────────────────────────────────────────────

def parse_steps(raw: str | list | dict) -> list[dict[str, Any]]:
    """把 LLM 回复解析成步骤列表。模型输出形态不可控，这里统一兜住：
    - 已是 list → 直接用；dict → 取常见键（steps/plan/steps_list）；
    - 字符串 → 剥 ```json 围栏 → 取第一个 [ … ] 或 { … } 片段再解析；
    - 单步对象/单字符串都容忍成一步；空结果视为生成失败（宁可不落库，不留半截计划）。
    """
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        for key in ("steps", "plan", "items", "steps_list"):
            if isinstance(raw.get(key), list):
                items = raw[key]
                break
        else:
            items = [raw]  # 单步对象
    else:
        text = (raw or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[-1] if "\n" in text else text
        start = min((i for i in (text.find("["), text.find("{")) if i != -1),
                    default=-1)
        if start == -1:
            raise PlannerError(f"模型未返回步骤 JSON：{text[:120]!r}")
        for end_ch in ("]", "}"):
            end = text.rfind(end_ch)
            if end > start:
                try:
                    return parse_steps(json.loads(text[start:end + 1]))
                except json.JSONDecodeError:
                    continue
        raise PlannerError(f"步骤 JSON 无法解析：{text[:120]!r}")

    steps: list[dict[str, Any]] = []
    for i, item in enumerate(items, 1):
        if isinstance(item, str):
            item = {"title": item}
        if not isinstance(item, dict) or not str(item.get("title") or "").strip():
            continue  # 没有标题的步骤直接丢弃，不落半截
        hints = item.get("tool_hints") or item.get("tools") or []
        if isinstance(hints, str):
            hints = [h.strip() for h in hints.split(",") if h.strip()]
        steps.append({
            "seq": len(steps) + 1,  # seq 一律连续重编，容忍模型跳号
            "title": str(item["title"]).strip()[:300],
            "detail": (str(item.get("detail")).strip()
                       if item.get("detail") else None),
            "tool_hints": [str(h) for h in hints][:8],
        })
    if not steps:
        raise PlannerError("模型返回的步骤列表为空")
    return steps


# ── 状态机（纯函数，禁止跳跃）──────────────────────────────────────────────

_STEP_TRANSITIONS: dict[str, dict[str, str]] = {
    "pending":  {"start": "running", "skip": "skipped"},
    "running":  {"done": "done", "fail": "failed", "resume": "pending"},
    "failed":   {"retry": "pending", "skip": "skipped"},
    "done":     {},
    "skipped":  {"retry": "pending"},
}


def step_transition(cur: str, action: str) -> str:
    """步骤状态流转。非法流转抛 ValueError——状态错了比断了更危险。"""
    nxt = _STEP_TRANSITIONS.get(cur, {}).get(action)
    if nxt is None:
        raise ValueError(f"非法状态流转：{cur} --{action}--> ?")
    return nxt


def plan_status_after(status_now: str, *, any_pending: bool,
                      last_step_failed: bool) -> str:
    """计划级状态推导（纯函数）：跑起来=running；没得跑且最后一步没挂=done；挂了=failed。"""
    if status_now == "aborted":
        return "aborted"
    if any_pending:
        return "running"
    return "failed" if last_step_failed else "done"


def progress(steps: list[dict[str, Any]]) -> dict[str, int]:
    """步骤进度快照（纯函数）：advance 返回值的一部分，前端画进度条。"""
    counts = {"pending": 0, "running": 0, "done": 0, "failed": 0, "skipped": 0}
    for s in steps:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    return {"total": len(steps), "next_seq": next(
        (s["seq"] for s in sorted(steps, key=lambda x: x["seq"])
         if s["status"] == "pending"), None), **counts}


def step_charter(goal: str, steps: list[dict[str, Any]], upto: dict[str, Any]) -> str:
    """advance 的 charter（纯函数）：目标 + 前序步骤产物 + 本步指令。

    前序只带 title+result 摘要（结果可能很大，截 400 字），模型要的是"做到哪了"，
    不是全量重放——全量上下文是 kb/ctx 工具的活。
    """
    parts = [f"# 计划目标\n{goal}", "# 本步任务"]
    if upto.get("detail"):
        parts.append(upto["detail"])
    if upto.get("tool_hints"):
        parts.append("建议工具（仅供判断，授权由系统控制）："
                     + "、".join(upto["tool_hints"]))
    prior = [s for s in steps if s["seq"] < upto["seq"] and s["status"] == "done"]
    if prior:
        lines = []
        for s in prior:
            res = s.get("result") or {}
            brief = json.dumps(res, ensure_ascii=False)[:400] if res else "（无产物）"
            lines.append(f"- 步骤{s['seq']} {s['title']}：{brief}")
        parts.append("# 前序已完成\n" + "\n".join(lines))
    return "\n\n".join(parts)


# ── 落库与推进 ────────────────────────────────────────────────────────────

PLANNER_SYSTEM = (
    "你是项目规划器。把用户目标拆成 3~8 个可独立执行、可验证的步骤，"
    "输出 JSON 数组：[{\"title\": \"一句话做什么\", \"detail\": \"执行指令（给执行智能体看，"
    "含需要的查询/产出要求）\", \"tool_hints\": [\"工具名\"]}]。"
    "只输出 JSON，不要解释。步骤之间是数据依赖关系：后一步可以用前一步的产物。")


async def create_plan(pool: asyncpg.Pool, *, goal: str, project_id: int | None,
                      created_by: str, meta: dict[str, Any] | None = None,
                      max_steps: int = 8) -> dict[str, Any]:
    """goal → LLM 拆步 → 落库（draft 状态）。LLM 失败抛 PlannerError，不留半截计划。"""
    goal = (goal or "").strip()
    if not goal:
        raise PlannerError("目标不能为空")
    try:
        raw = await llm.chat_json(PLANNER_SYSTEM, goal, temperature=0.3)
    except Exception as e:  # noqa: BLE001 — 生成失败要给调用方明确原因
        raise PlannerError(f"步骤生成失败：{type(e).__name__}: {e}") from e
    steps = parse_steps(raw)[:max_steps]
    async with pool.acquire() as conn, conn.transaction():
        plan_id = await conn.fetchval(
            "INSERT INTO agent_plans(project_id,goal,status,created_by,meta) "
            "VALUES($1,$2,'draft',$3,$4::jsonb) RETURNING id",
            project_id, goal, created_by,
            json.dumps({"tool_names": (meta or {}).get("tool_names") or []},
                       ensure_ascii=False))
        for s in steps:
            await conn.execute(
                "INSERT INTO agent_plan_steps(plan_id,seq,title,detail,tool_hints) "
                "VALUES($1,$2,$3,$4,$5::text[])",
                plan_id, s["seq"], s["title"], s["detail"], s["tool_hints"])
    return {"plan_id": plan_id, "goal": goal, "steps": steps}


async def _load_plan(pool: asyncpg.Pool, plan_id: int) -> dict[str, Any] | None:
    row = await pool.fetchrow("SELECT * FROM agent_plans WHERE id=$1", plan_id)
    return dict(row) if row else None


async def advance(pool: asyncpg.Pool, plan_id: int, *, caller: str = "sys_dev",
                  runner=None) -> dict[str, Any]:
    """推进计划：跑下一个 pending 步并回写。

    runner 可注入（测试桩）；缺省就是 agent_runtime.run 完整循环。
    幂等恢复：开跑前把卡在 running 的步归位 pending（进程崩溃后的 resume 语义）。
    """
    plan = await _load_plan(pool, plan_id)
    if not plan:
        raise PlannerError(f"计划 {plan_id} 不存在")
    if plan["status"] in ("done", "aborted"):
        raise PlannerError(f"计划已 {plan['status']}，无需推进")

    async with pool.acquire() as conn:
        # 崩溃恢复：running → pending（幂等，重复调用无副作用）
        await conn.execute(
            "UPDATE agent_plan_steps SET status='pending', started_at=NULL "
            "WHERE plan_id=$1 AND status='running'", plan_id)
        steps = [dict(r) for r in await pool.fetch(
            "SELECT id,seq,title,detail,tool_hints,status,result,error "
            "FROM agent_plan_steps WHERE plan_id=$1 ORDER BY seq", plan_id)]
        nxt = next((s for s in steps if s["status"] == "pending"), None)
        if nxt is None:
            failed = any(s["status"] == "failed" for s in steps)
            new_status = plan_status_after(plan["status"], any_pending=False,
                                           last_step_failed=failed)
            await pool.execute(
                "UPDATE agent_plans SET status=$2, updated_at=now() WHERE id=$1",
                plan_id, new_status)
            return {"plan_id": plan_id, "status": new_status,
                    "progress": progress(steps), "step": None,
                    "message": "没有待执行步骤；失败步骤用 retry 重试"}

        new_status = step_transition(nxt["status"], "start")
        await pool.execute(
            "UPDATE agent_plan_steps SET status=$2, started_at=now() WHERE id=$1",
            nxt["id"], new_status)
        await pool.execute(
            "UPDATE agent_plans SET status='running', current_seq=$2, updated_at=now() "
            "WHERE id=$1", plan_id, nxt["seq"])

    tool_names = ((plan.get("meta") or {}).get("tool_names")
                  if isinstance(plan.get("meta"), dict) else None) or []
    charter = step_charter(plan["goal"], steps, nxt)
    ok, result_payload, error = True, None, None
    try:
        run = runner or agent_runtime.run
        out = await run(pool, charter=charter, task=nxt["title"],
                        tool_names=tool_names, project_id=plan["project_id"],
                        caller=caller, max_steps=8)
        result_payload = {"output": out.get("output"),
                          "steps": out.get("steps", [])[-5:]}  # 轨迹只留尾巴，防膨胀
    except Exception as e:  # noqa: BLE001 — 步骤失败不炸计划，记下原因可单步重试
        ok, error = False, f"{type(e).__name__}: {e}"

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE agent_plan_steps SET status=$2, result=$3::jsonb, error=$4, "
            "finished_at=now() WHERE id=$1",
            nxt["id"], "done" if ok else "failed",
            json.dumps(result_payload, ensure_ascii=False, default=str)
            if ok else None, error)
        steps = [dict(r) for r in await pool.fetch(
            "SELECT id,seq,title,detail,tool_hints,status,result,error "
            "FROM agent_plan_steps WHERE plan_id=$1 ORDER BY seq", plan_id)]
        failed = any(s["status"] == "failed" for s in steps)
        plan_status = plan_status_after(
            "running", any_pending=any(s["status"] == "pending" for s in steps),
            last_step_failed=failed)
        await conn.execute(
            "UPDATE agent_plans SET status=$2, updated_at=now() WHERE id=$1",
            plan_id, plan_status)

    return {"plan_id": plan_id, "status": plan_status,
            "progress": progress(steps),
            "step": {"seq": nxt["seq"], "title": nxt["title"],
                     "status": "done" if ok else "failed", "error": error}}


async def retry_step(pool: asyncpg.Pool, plan_id: int, seq: int,
                     *, caller: str = "sys_dev") -> dict[str, Any]:
    """单步重试：failed/skipped → pending，再走一次 advance（按 seq 顺序自然轮到它）。"""
    plan = await _load_plan(pool, plan_id)
    if not plan:
        raise PlannerError(f"计划 {plan_id} 不存在")
    row = await pool.fetchrow(
        "SELECT id,status FROM agent_plan_steps WHERE plan_id=$1 AND seq=$2",
        plan_id, seq)
    if not row:
        raise PlannerError(f"步骤 {seq} 不存在")
    new_status = step_transition(row["status"], "retry")
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "UPDATE agent_plan_steps SET status=$2, error=NULL, result=NULL "
            "WHERE id=$1", row["id"], new_status)
        await conn.execute(
            "UPDATE agent_plans SET status='running', updated_at=now() WHERE id=$1",
            plan_id)
    return await advance(pool, plan_id, caller=caller)
