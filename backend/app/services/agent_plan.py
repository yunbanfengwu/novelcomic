"""`agent.plan`：挂在 Tapflow 任意位置的「按上下文规划」节点。

它跟普通 llm 节点的分工是清楚的：
- **llm 节点**：作者在图上用 `{{节点.字段}}` 把该看的东西预先填进提示词 —— 人来规划，模型执行。
- **agent.plan**：入参无法预先写死，因为它要干的活就是**自己判断该看上游的哪一部分**。
  上下文可能几十万字，模型多轮取数（outline → search → get 分页）逐步收敛，
  拿够了再组装参数/提示词。轮次上限就是 agent_runtime.MAX_STEPS。

本模块**不含循环**——tool-calling 循环只有 agent_runtime.run 一份实现，这里只是把
运行期 ctx 接进去。同理不含工具注册表、不含提示词拼装。

产出只返回结构，不落库：它是规划/装配节点，写库交给下游既有的命名动作（权威入口不动）。
但它调用的工具**可以**有副作用——那些工具各自就是权威入口，走的是 tools.invoke 与
tool_calls 审计，能查到这一轮模型到底动了什么。
"""
from __future__ import annotations

import json
from typing import Any

import asyncpg

from . import workflow_actions

CHARTER = ("你是一条 Tapflow 里的规划节点。你的产出会被下游节点消费，"
           "所以要给**结构化、可直接使用的结果**，不要复述你的取数过程。")


def _list(value: Any) -> list[Any]:
    """图上填的多选可能是 JSON 字符串、单值或数组，统一成列表。"""
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                loaded = json.loads(text)
            except json.JSONDecodeError:
                return [text]
            return loaded if isinstance(loaded, list) else [loaded]
        return [text]
    return [value]


async def agent_plan(pool: asyncpg.Pool, *, goal: str = "", charter: str = "",
                     tool_names: Any = None, skills: Any = None,
                     folder_ids: Any = None, max_steps: int | None = None,
                     project_id: int | None = None,
                     _ctx: dict[str, Any] | None = None,
                     **_: Any) -> dict[str, Any]:
    """按上下文规划：模型自己分页读 ctx、按需调工具，多轮收敛后给出产物。

    goal 写「要产出什么」（如「组装九宫格分镜要素提示词」），不用写「先读哪个节点」——
    该读哪一段由它自己判断。上游各节点产出通过 ctx.outline / ctx.search / ctx.get
    分页探索，不会一次性灌进上下文。勾了 capability.catalog 时它还能自己查有哪些
    能力可用、缺什么前置。
    """
    from . import agent_runtime

    ctx = _ctx or {}
    if project_id is None:
        # 图上没显式接 project_id 时，从开始节点签名里取——工作流入参一定有它
        inputs = ctx.get("__inputs__")
        if isinstance(inputs, dict):
            project_id = inputs.get("project_id")

    if not (goal or "").strip():
        raise ValueError("agent.plan 需要 goal：说明这个节点要产出什么")

    folders = [int(f) for f in _list(folder_ids) if str(f).strip().isdigit()]
    result = await agent_runtime.run(
        pool,
        charter=(charter or "").strip() or CHARTER,
        task=goal,
        skills=[str(s) for s in _list(skills)],
        folder_ids=folders,
        tool_names=[str(t) for t in _list(tool_names)],
        project_id=project_id,
        flow_ctx=ctx,
        max_steps=max(1, int(max_steps or agent_runtime.MAX_STEPS)),
        caller="workflow",
    )
    steps = result.get("steps") or []
    return {
        "output": result.get("output") or "",
        "steps": steps,
        "step_count": len(steps),
        "tools": result.get("tools") or [],
        # 取数路径是这个节点最该被人看见的东西：模型读了 ctx 的哪几段、调了什么工具。
        # 单独给一份扁平清单，画布/测试页不用自己从 steps 里再剥一层。
        "read_path": [{"tool": s.get("tool"), "args": s.get("args"), "ok": s.get("ok"),
                       "error": s.get("error")} for s in steps],
    }


workflow_actions.register(
    "agent.plan", title="按上下文规划", wants_ctx=True,
    description=(agent_plan.__doc__ or "").strip(),
    params={
        "goal": {"type": "string", "required": True, "desc": "要产出什么（不用写取数步骤）"},
        "charter": {"type": "string", "required": False, "desc": "角色设定，留空用默认"},
        "tool_names": {"type": "array", "required": False, "desc": "授权可调的业务工具名"},
        "skills": {"type": "array", "required": False, "desc": "可用技能 slug"},
        "folder_ids": {"type": "array", "required": False, "desc": "可检索的知识库文件夹 id"},
        "max_steps": {"type": "int", "required": False, "desc": "轮次上限，默认 12"},
        "project_id": {"type": "int", "required": False, "desc": "留空则取开始节点入参"},
    },
    outputs={
        "output": {"type": "string", "desc": "规划产物（下游 {{节点.output}} 引用）"},
        "step_count": {"type": "int", "desc": "实际用了几轮"},
        "read_path": {"type": "array", "desc": "取数路径：读了 ctx 哪几段、调了什么工具"},
    },
)(agent_plan)
