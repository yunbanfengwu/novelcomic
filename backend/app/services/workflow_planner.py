"""智能调用规划器：一句提示词 → 子工作流「哪几个节点重生成、哪几个复用」。

问题出在哪（2026-08-04 用户提的第 2 条）：原子节点（图片/视频/文本）炸开输入提示词
就重出那一件产物，语义闭合；而**组合工作流**被引用时，炸开后点生成到底生成子图里的
哪几个节点，图上根本读不出来——引擎只有两档：`force` 命中就整个子图重跑（FORCE_ALL），
不命中就全部「缺才跑」。要么全重来（钱白花），要么什么都不动（点了没反应）。

本模块补的就是中间那一档：把**子图的节点清单 + 每个节点当前有没有产物 + 用户这句话
+ 父运行的上下文轨迹**交给文本模型，让它逐节点判 `reuse` 还是 `generate`，折算成引擎
本来就认的 `force` 集合与节点级 `overrides`。引擎语义一点没变，只是多了一个会填表的人。

两条纪律：
- 「当前有没有产物」不自己写 SQL 探——复用 `workflow.preview_workflow` 那份零副作用预检
  （画布打开时回显已有内容用的就是它），判据只有一份。
- 模型不可用/答非所问一律**降级**回原语义（被点名就整图重跑），并把降级原因如实带回，
  绝不静默按「什么都不重跑」处理——那会让用户以为点了没反应。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import asyncpg

log = logging.getLogger("workflow.planner")

# 会真花钱的节点类型：规划只对它们做「重生成 / 复用」的判断，
# 取数/条件/结束这些跟着跑就行，让模型去判反而是给它制造犯错的机会。
COSTLY_TYPES = {"gen", "llm", "task", "subflow"}

CHARTER = """你是生成流水线的调度员。用户给了一句话，你要决定这条流水线里每个节点\
这次是「复用已有产物」还是「重新生成」。

判断口径：
1. 用户这句话点到的内容，对应节点必须 generate；没点到、且已有产物的节点一律 reuse。
2. 一个节点要 generate，它**下游**依赖其产物的节点也要 generate（上游变了，下游的旧产物就过期了）。
3. exists=false（确定没有产物）的节点一律 generate——那不是选择，是必须。
   exists=null 表示探不出（循环体节点，运行时对每一项各自按「缺才跑」判定），
   这种节点只按用户意图判，不要因为"不确定"就一律 generate。
4. 用户只是换个说法描述同一件事、或没提到任何具体环节时，只 generate 最终产出节点。
5. 能少重跑就少重跑：每次 generate 都在花钱。
6. instruction 只写**用户这次的额外要求**，用自然语言。没有就留空串。
   绝不要把流程里已有的配置、模板或 {{…}} 占位符抄进来。

只输出 JSON，不要解释、不要代码块围栏：
{"nodes":[{"id":"节点id","action":"generate|reuse","instruction":"给这个节点的额外要求，没有就空串"}],
 "reason":"一句话说明这次为什么这么排"}
"""


class PlanError(RuntimeError):
    pass


async def describe(pool: asyncpg.Pool, *, slug: str, version: int | None,
                   inputs: dict[str, Any]) -> list[dict[str, Any]]:
    """子图节点清单 + 每个节点当前有没有产物（零副作用）。

    产物存在性走 preview_workflow —— 与画布「打开就把已有内容带出来」同一份判据。
    预检失败不算致命：清单照给，exists 全按未知（None）处理，模型会按第 3 条全重生成。
    """
    from . import workflow as wf

    child = await wf.load_workflow(pool, slug, version)
    try:
        report = await wf.preview_workflow(pool, slug=slug, version=version, inputs=inputs)
    except Exception as e:  # noqa: BLE001 — 预检是尽力而为，探不出来不该让规划整个失败
        log.warning("智能调用预检失败（%s），按「无产物」规划：%s", slug, e)
        report = {}
    edges = child["graph"].get("edges") or []
    # 循环体节点探不出产物：preview 刻意不展开循环（那要真取数），它们的「缺才跑」
    # 是运行时对每一项各自判的。如实标 exists=None，别拿"不确定"当"没有"——
    # 实测过：当成没有就等于每次都全量重跑，这功能就白做了。
    body = {b for n in (child["graph"].get("nodes") or []) if n.get("type") == "loop"
            for b in ((n.get("config") or {}).get("body") or [])}
    out: list[dict[str, Any]] = []
    for node in child["graph"].get("nodes") or []:
        ntype = str(node.get("type"))
        if ntype not in COSTLY_TYPES:
            continue
        cfg = node.get("config") or {}
        ui = cfg.get("ui") or {}
        seen = report.get(node["id"]) or {}
        exists = None if node["id"] in body else seen.get("exists")
        out.append({
            "id": node["id"], "type": ntype,
            "title": ui.get("title") or node["id"],
            "produces": cfg.get("modality") or ("text" if ntype == "llm" else cfg.get("step") or ntype),
            "exists": exists,
            **({"per_item": True} if node["id"] in body else {}),
            "upstream": [e["from"] for e in edges if e.get("to") == node["id"]],
        })
    return out


def _parse(text: str) -> dict[str, Any]:
    """模型的 JSON。围栏与前后闲话都容忍——判死一次就等于整条链降级，不值得。"""
    body = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise PlanError("模型未返回 JSON")
    try:
        got = json.loads(body[start:end + 1])
    except json.JSONDecodeError as e:
        raise PlanError(f"模型返回的 JSON 解析失败：{e}") from e
    if not isinstance(got, dict) or not isinstance(got.get("nodes"), list):
        raise PlanError("模型返回的 JSON 缺 nodes 数组")
    return got


async def plan(pool: asyncpg.Pool, *, slug: str, version: int | None,
               prompt: str, inputs: dict[str, Any], project_id: int | None = None,
               history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """规划一次智能调用。

    返回 {force, overrides, nodes, reason, degraded?}：
    - force     → 直接就是 run_workflow 的 force 集合（子图内的节点 id）
    - overrides → {节点id: {"instruction": …}}，与画布生成条那条覆盖通道同形
    - degraded  → 有值表示这次没规划成，调用方按原语义（整图重跑）兜底
    """
    from . import agent_runtime

    nodes = await describe(pool, slug=slug, version=version, inputs=inputs)
    if not nodes:
        return {"force": [], "overrides": {}, "nodes": [], "reason": "子流程没有可规划的生成节点"}
    # 只有**确定**没有产物的才算 missing。exists=None 是「探不出」（循环体逐项判），
    # 把它算进 missing 等于每次都全量重跑——那这个功能就没有存在意义了。
    missing = [n["id"] for n in nodes if n.get("exists") is False]

    def degrade(why: str) -> dict[str, Any]:
        log.warning("智能调用规划降级（%s）：%s", slug, why)
        return {"force": [n["id"] for n in nodes], "overrides": {},
                "nodes": nodes, "reason": why, "degraded": why}

    if not str(prompt or "").strip():
        # 没给提示词就没什么好规划的：缺什么补什么，已有的一律复用。
        return {"force": missing, "overrides": {}, "nodes": nodes,
                "reason": "未给提示词，只补齐缺失产物"}

    task = json.dumps({
        "用户要求": prompt,
        "流程": {"slug": slug, "节点": nodes},
        **({"父流程上下文": (history or [])[-12:]} if history else {}),
    }, ensure_ascii=False, default=str)
    try:
        got = _parse(str((await agent_runtime.run(
            pool, charter=CHARTER, task=task, project_id=project_id,
            caller="tapflow_smart_call")).get("output") or ""))
    except Exception as e:  # noqa: BLE001 — 规划不了就降级，不能把用户这次点击判死
        return degrade(f"规划模型不可用或返回无法解析：{e}")

    known = {n["id"] for n in nodes}
    force: list[str] = []
    overrides: dict[str, Any] = {}
    for item in got["nodes"]:
        if not isinstance(item, dict) or str(item.get("id")) not in known:
            continue
        nid = str(item["id"])
        if str(item.get("action")) == "generate":
            force.append(nid)
        text = str(item.get("instruction") or "").strip()
        # 含 {{…}} 的一律丢弃：模型把节点配置里的模板原样抄回来过（实测它把
        # `{{__item__.prompt}}` 当"额外要求"回填）。覆盖层不做占位符解析，
        # 那串字面量会直接进出图提示词，画出来的东西没人看得懂。
        if text and "{{" not in text:
            overrides[nid] = {"instruction": text}
        elif text:
            log.warning("智能调用规划：丢弃含占位符的 instruction（节点 %s）：%s", nid, text[:120])
    # 缺产物的必须跑：模型漏判的那几个由这里兜住（describe 的第 3 条是硬规则，不是建议）。
    force = sorted(set(force) | set(missing), key=lambda x: [n["id"] for n in nodes].index(x))
    if not force:
        return degrade("规划结果一个节点都不重跑，与用户点了生成的意图矛盾")
    log.info("智能调用规划（%s）：重跑 %s / 共 %d 个生成节点 —— %s",
             slug, force, len(nodes), got.get("reason"))
    return {"force": force, "overrides": overrides, "nodes": nodes,
            "reason": str(got.get("reason") or "")}
