"""能力目录：把「工具」和「tapflow」抹平成同一种东西，供规划类节点选用。

为什么必须抹平：现在很多能力还是工具（甚至还散在 API 端点里），将来会陆续做成 tapflow。
如果规划节点看得见「这个能力今天是工具、明天是流程」，那每迁移一个能力就要改一次
它的提示词和勾选项——迁移成本被节点数放大。所以对模型只暴露一种条目形状：

    {id, title, description, inputs, outputs, writes, cardinality}

`id` 带 `tool:` / `flow:` 前缀只为**分派**，不参与选择：模型按 description + inputs/outputs
判断该用谁。一个能力从工具变成 tapflow，只是这一条的前缀变了，用它的节点一行不用改。

两边字段本来就是可对齐的，不存在第二套 schema：
`tool.params ↔ workflow.input_schema`、`tool.outputs ↔ workflow.output_schema`、
`tool.writes ↔ 流程里是否含 gen/task 节点`。

**本模块只读、不执行。** `capability.plan_invoke` 是校验器：它回答「这样调合不合法、会
产出什么、要花多少钱」，但绝不真跑。真执行（含动态调 tapflow）是下一步的事，单独开
`capability.invoke` 并配深度/次数/环护栏——在那之前，规划节点最多只能规划。
"""
from __future__ import annotations

import json
from typing import Any

import asyncpg

from . import workflow_actions

# 会花钱的节点类型：gen 出图出视频、task 入队执行体。用来给流程估成本，
# 也用来判定一个流程算不算「写类」——判据与 workflow_planner.COSTLY_TYPES 同源语义。
COSTLY = {"gen", "task"}

# 迁移期的替代关系：老能力被新能力取代时在这里登记一条，`plan_invoke` 会把老 id
# 指向新 id 并在返回里说明。有了它，正在跑的编排不会因为你迁移而断——这是
# 「能力载体会变，调用方不该改」这条设计的兜底，不是可选项。
SUPERSEDED: dict[str, str] = {}

# 元能力：不进目录。它们不产出任何业务产物，只是「查目录 / 做规划」这件事本身。
# 实测必须挡：规划节点看到 agent.plan 在目录里，就把「缺分镜脚本」的解法写成
# 「再调一次 agent.plan」——一个只会规划的东西被当成了能产出内容的能力，
# 于是给出一份看着合理、实则什么都不会发生的计划。
META = {"tool:agent.plan", "tool:capability.catalog", "tool:capability.plan_invoke",
        "flow:agent-plan-demo"}


def _flow_writes(graph: dict[str, Any]) -> tuple[bool, int]:
    """流程是否会产生副作用，以及有几个花钱节点（给 plan_invoke 报成本）。"""
    nodes = (graph or {}).get("nodes") or []
    costly = [n for n in nodes if n.get("type") in COSTLY]
    return bool(costly), len(costly)


def _tool_entry(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"tool:{spec['name']}",
        "kind": "tool",
        "title": spec.get("title") or spec["name"],
        "description": spec.get("description") or "",
        "inputs": spec.get("params") or {},
        "outputs": spec.get("outputs") or {},
        "writes": bool(spec.get("writes")),
        "cardinality": "one",
        "group": spec.get("group") or spec["name"].split(".")[0],
    }


def _flow_entry(row: asyncpg.Record) -> dict[str, Any]:
    from .workflow import output_cardinality

    graph = row["graph"]
    graph = json.loads(graph) if isinstance(graph, str) else (graph or {})
    writes, costly = _flow_writes(graph)
    schema = row["input_schema"]
    outs = row["output_schema"]
    return {
        "id": f"flow:{row['slug']}",
        "kind": "flow",
        "title": row["name"],
        "description": row["description"] or "",
        "inputs": json.loads(schema) if isinstance(schema, str) else (schema or {}),
        "outputs": json.loads(outs) if isinstance(outs, str) else (outs or {}),
        "writes": writes,
        "cardinality": output_cardinality(graph),
        "group": "flow",
        "version": row["version"],
        "costly_nodes": costly,
    }


async def _flows(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    """已发布的可复用流程。

    排除 `subject_id` 非空的画布实例：每个场景/要素在生产态改一次画布就 fork 一份，
    它们是某个具体对象的私有副本，不是可被别人调用的能力（理由同 api/workflows 列表页）。
    同 slug 只取版本最高的一条。
    """
    rows = await pool.fetch(
        "SELECT DISTINCT ON (slug) slug,name,description,version,input_schema,"
        "       output_schema,graph FROM workflows "
        "WHERE status='published' AND subject_id IS NULL "
        "ORDER BY slug, version DESC")
    return [_flow_entry(r) for r in rows]


async def entries(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    """全量目录（未过滤）。管理台与 capability.catalog 共用这一份，不各拼一次。"""
    from . import tools as tool_registry

    out = [_tool_entry(s) for s in tool_registry.specs()]
    out += await _flows(pool)
    out = [e for e in out if e["id"] not in META]
    for e in out:
        if e["id"] in SUPERSEDED:
            e["superseded_by"] = SUPERSEDED[e["id"]]
    return sorted(out, key=lambda e: (e["kind"], e["id"]))


def _matches(entry: dict[str, Any], q: str) -> bool:
    blob = f"{entry['id']} {entry['title']} {entry['description']}".lower()
    return all(w in blob for w in q.lower().split())


async def catalog(pool: asyncpg.Pool, *, query: str = "", kind: str | None = None,
                  writes: bool | None = None, limit: int = 40,
                  **_: Any) -> dict[str, Any]:
    """列出可用能力（工具与 tapflow 一视同仁），按关键词筛。

    条目形状统一为 {id, title, description, inputs, outputs, writes, cardinality}。
    **按 description 和 inputs/outputs 选能力，不要按 id 前缀选**——前缀只表示它当前
    的实现载体（工具还是流程），同一个能力将来可能换载体，语义不变。
    writes=true 的能力有副作用（会落库、会花钱出图），选它之前先想清楚是不是真要。
    选定后用 capability.plan_invoke 校验入参，它会告成本，但不会真跑。
    """
    all_entries = await entries(pool)
    q = (query or "").strip()
    hit = [e for e in all_entries
           if (not q or _matches(e, q))
           and (not kind or e["kind"] == kind)
           and (writes is None or e["writes"] == bool(writes))]
    n = max(1, min(int(limit or 40), 200))
    # 目录本身可能几百条，全量返回就又变成「一次性塞满上下文」——正是要避免的
    return {"query": q, "total": len(hit), "truncated": len(hit) > n,
            "capabilities": [{k: v for k, v in e.items() if k != "costly_nodes"}
                             for e in hit[:n]],
            "note": "结果被截断时请缩小 query 再查；要看某条的完整入参就 plan_invoke。"}


async def plan_invoke(pool: asyncpg.Pool, *, id: str = "",  # noqa: A002 — 对模型就叫 id
                      inputs: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    """**只校验不执行**：这样调这个能力合不合法、会产出什么、会花多少钱。

    返回 ok / missing（缺的必填）/ unknown（多给的）/ outputs（会产出什么）/
    cost（几个出图出视频节点，0 表示不花钱）。缺参数就按 missing 补齐再调一次。
    本工具永不产生副作用，可以随便试。
    """
    given = dict(inputs or {})
    if isinstance(given.get("inputs"), dict) and len(given) == 1:
        # 模型常把 {"inputs": {...}} 再套一层；这不算错，拆开就是（回喂报错纯属浪费一轮）
        given = given["inputs"]

    target = SUPERSEDED.get(id, id)
    entry = next((e for e in await entries(pool) if e["id"] == target), None)
    if not entry:
        raise KeyError(f"未知能力 {id!r}；先用 capability.catalog 查可用 id")

    declared = entry["inputs"] or {}
    missing = [k for k, p in declared.items()
               if isinstance(p, dict) and p.get("required")
               and given.get(k) in (None, "")]
    unknown = [k for k in given if k not in declared]
    out = {
        "id": entry["id"], "kind": entry["kind"], "title": entry["title"],
        "ok": not missing,
        "missing": missing, "unknown": unknown,
        "will_produce": entry["outputs"], "cardinality": entry["cardinality"],
        "writes": entry["writes"],
        "cost": {"costly_nodes": entry.get("costly_nodes", 1 if entry["writes"] else 0),
                 "note": "花钱节点数（出图/出视频/入队执行体）；0 表示纯取数"},
        "executed": False,
        "note": "本工具只校验，没有真跑。当前版本没有真执行入口——请把校验通过的调用"
                "计划写进你的产出里，由人或下游节点决定是否执行。",
    }
    if target != id:
        out["redirected_from"] = id
        out["note"] = f"{id} 已被 {target} 取代，已按新能力校验。" + out["note"]
    return out


workflow_actions.register(
    "capability.catalog", title="能力目录",
    description=(catalog.__doc__ or "").strip(),
    params={
        "query": {"type": "string", "required": False, "desc": "关键词，空格分隔多词取交集"},
        "kind": {"type": "string", "required": False, "desc": "tool 或 flow；留空两者都要"},
        "writes": {"type": "bool", "required": False, "desc": "只看有/无副作用的能力"},
        "limit": {"type": "int", "required": False, "desc": "返回条数，默认 40"},
    },
    outputs={"capabilities": {"type": "array", "desc": "能力条目"},
             "total": {"type": "int", "desc": "命中总数"},
             "truncated": {"type": "bool", "desc": "是否截断"}},
)(catalog)

workflow_actions.register(
    "capability.plan_invoke", title="校验能力调用（不执行）",
    description=(plan_invoke.__doc__ or "").strip(),
    params={
        "id": {"type": "string", "required": True, "desc": "能力 id，如 flow:xxx / tool:xxx"},
        "inputs": {"type": "object", "required": False, "desc": "打算传的入参"},
    },
    outputs={"ok": {"type": "bool", "desc": "入参是否齐备"},
             "missing": {"type": "array", "desc": "缺的必填参数"},
             "will_produce": {"type": "object", "desc": "会产出什么"},
             "cost": {"type": "object", "desc": "成本估计"}},
)(plan_invoke)
