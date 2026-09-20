"""工作流解释器：把 workflows.graph 里的节点/边解释执行。

与 steps.py 的关系：这里**不重写任何生成逻辑**。task 节点就是包一层已注册的 Step
（gen_element_sheet / gen_scene_empty / …），所以迁移一个任务 = 在画布上摆一个节点，
不用动 steps.py 那 2484 行。粗粒度是刻意的——复用的单位是「工作流」而不是「节点」，
细粒度拆分等画布真正用起来、知道哪里需要插手了再做。

执行模型参照 ComfyUI（PR #2666 执行模型翻转）：
- 前往后拓扑排序（不是后往前递归）；
- 运行时节点展开：loop 节点把自己展开成 N 份子图 —— 循环不是原语，是展开；
- 惰性求值留给 branch 节点（本版未实现）。

⚠️ v1 的取舍：WorkflowStep 在自己的 run() 里**串行驱动**整张图，逐个 await 子任务完成。
好处是实现简单、语义直观、失败点集中；代价是一次工作流运行会占住一个 worker 槽
（子任务本身仍跑在别的 worker 上，不影响并发出图）。等编排复杂到需要真并行时，
再改成"节点入队 + 工作流任务重入"的模型——那时表结构不用动，workflow_node_runs
已经按 (run_id, node_key, iteration) 记录了断点。
"""
from __future__ import annotations

import asyncio
import json
import re
import logging
from typing import Any

import asyncpg

log = logging.getLogger("workflow")

MAX_DEPTH = 5          # 子工作流嵌套上限（A 调 B 调 A 在保存时就该被查环拦下，这里是兜底）
_POLL_S = 3
_TASK_TIMEOUT_S = 1800


# 强制重跑的通配符。subflow 节点被点名重跑时，子图内所有节点都要跟着重跑——
# 内外层节点 id 天然不同名，只按 id 下传对不上号。
FORCE_ALL = "*"


def _forced(key: str, force: frozenset[str] | set[str]) -> bool:
    """这个节点这一轮要不要无视「缺才跑」。"""
    return FORCE_ALL in force or key in force


class WorkflowError(RuntimeError):
    pass


def _j(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else json.loads(v or "{}")


# ═══════════ 图的静态检查（保存时调用，别等跑起来才炸）═══════════

def validate_graph(graph: dict[str, Any]) -> list[str]:
    """返回问题列表（空=通过）。保存工作流时调用。"""
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    errors: list[str] = []
    ids = [n.get("id") for n in nodes]
    if len(ids) != len(set(ids)):
        errors.append("存在重复的节点 id")
    known = set(ids)
    for e in edges:
        if e.get("from") not in known or e.get("to") not in known:
            errors.append(f"边 {e.get('from')}→{e.get('to')} 指向不存在的节点")
    # start/end 声明的是「被当子工作流调用时的签名」。智能体编排的入参是运行上下文
    # （project_id / node_id，全局统一），不需要每张图各自声明——故改为「至多一个」。
    starts = [n for n in nodes if n.get("type") == "start"]
    ends = [n for n in nodes if n.get("type") == "end"]
    if len(starts) > 1:
        errors.append(f"开始节点最多一个（当前 {len(starts)} 个）")
    if len(ends) > 1:
        errors.append(f"结束节点最多一个（当前 {len(ends)} 个）")
    # 挂载点（2026-09-17）：同一画布上同一个归宿只能有一个节点——两个「项目封面」
    # 挂载点意味着两条线都能写封面，最后谁写谁就是封面，那是靠运行顺序抽奖。
    # 要换归宿就改那个节点的声明，不要再加一个。
    seen_mounts: set[tuple[str, str]] = set()
    for n in nodes:
        if n.get("type") != "mount":
            continue
        mcfg = n.get("config") or {}
        sig = (str(mcfg.get("target") or ""),
               json.dumps(mcfg.get("subject") or {}, sort_keys=True, ensure_ascii=False))
        if sig in seen_mounts:
            errors.append(f"挂载点重复：{sig[0] or '（未声明归宿）'} 在同一张画布上只能有一个")
        seen_mounts.add(sig)
    if _has_cycle(ids, edges):
        errors.append("图中存在环——工作流必须是有向无环图（循环请用 loop 节点）")
    return errors


def _has_cycle(ids: list[Any], edges: list[dict[str, Any]]) -> bool:
    adj: dict[Any, list[Any]] = {i: [] for i in ids}
    for e in edges:
        if e.get("from") in adj and e.get("to") in adj:
            adj[e["from"]].append(e["to"])
    WHITE, GREY, BLACK = 0, 1, 2
    color = dict.fromkeys(ids, WHITE)

    def visit(u: Any) -> bool:
        color[u] = GREY
        for v in adj[u]:
            if color[v] == GREY or (color[v] == WHITE and visit(v)):
                return True
        color[u] = BLACK
        return False

    return any(color[i] == WHITE and visit(i) for i in ids)


def topo_order(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """前往后拓扑排序（ComfyUI 执行模型翻转的做法）。图已由 validate_graph 保证无环。"""
    nodes = {n["id"]: n for n in (graph.get("nodes") or [])}
    edges = graph.get("edges") or []
    indeg = dict.fromkeys(nodes, 0)
    adj: dict[Any, list[Any]] = {i: [] for i in nodes}
    for e in edges:
        if e.get("from") in nodes and e.get("to") in nodes:
            adj[e["from"]].append(e["to"])
            indeg[e["to"]] += 1
    ready = [i for i, d in indeg.items() if d == 0]
    out: list[dict[str, Any]] = []
    while ready:
        cur = ready.pop(0)
        out.append(nodes[cur])
        for nxt in adj[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
    if len(out) != len(nodes):
        raise WorkflowError("拓扑排序未覆盖全部节点——图中可能有环")
    return out


# ═══════════ 取定义 ═══════════

async def load_workflow(pool: asyncpg.Pool, slug: str, version: int | None = None) -> dict[str, Any]:
    """按 slug + version 取定义。version 省略时取最新**已发布**版本——
    引用方固定版本是刻意的：否则改一下被引用的工作流，所有调用方行为当场全变。"""
    if version is not None:
        row = await pool.fetchrow(
            "SELECT * FROM workflows WHERE slug=$1 AND version=$2", slug, version)
    else:
        row = await pool.fetchrow(
            "SELECT * FROM workflows WHERE slug=$1 AND status='published' "
            "ORDER BY version DESC LIMIT 1", slug)
    if not row:
        raise WorkflowError(f"工作流不存在或未发布: {slug}" + (f" v{version}" if version else ""))
    d = dict(row)
    d["graph"] = _j(d["graph"])
    d["input_schema"] = _j(d["input_schema"])
    d["output_schema"] = _j(d["output_schema"])
    _apply_asset_input_contract(d)
    d["output_cardinality"] = output_cardinality(d["graph"])
    d["subflow_contracts"] = await subflow_contracts(pool, d["graph"])
    # Tapflow 的工具节点直接消费同一份系统工具合同：选择工具后自动得到入参/出参，
    # 画布定义不再复制一份容易漂移的 schema。
    from . import tools as tool_registry
    wanted_tools = {
        str((node.get("config") or {}).get("name"))
        for node in (d["graph"].get("nodes") or [])
        if node.get("type") == "action" and (node.get("config") or {}).get("name")
    }
    d["tool_contracts"] = {
        spec["name"]: spec for spec in tool_registry.specs()
        if spec["name"] in wanted_tools
    }
    return d


def output_cardinality(graph: dict[str, Any]) -> str:
    """Derive a workflow's public output shape from its terminal graph.

    A workflow is multi-child when its end node receives a loop aggregate, or
    more than one distinct upstream product.  This is a contract, not a UI hint.
    """
    nodes = {str(n.get("id")): n for n in (graph.get("nodes") or [])}
    edges = graph.get("edges") or []
    for end in (n for n in nodes.values() if n.get("type") == "end"):
        inbound = [str(e.get("from")) for e in edges if str(e.get("to")) == str(end.get("id"))]
        if len(set(inbound)) > 1 or any(nodes.get(node_id, {}).get("type") == "loop" for node_id in inbound):
            return "many"
    return "one"


async def subflow_contracts(pool: asyncpg.Pool, graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Expose direct subflow output contracts to the canvas projection."""
    refs = {(str((n.get("config") or {}).get("slug")), (n.get("config") or {}).get("version"))
            for n in (graph.get("nodes") or []) if n.get("type") == "subflow"
            and (n.get("config") or {}).get("slug")}
    contracts: dict[str, dict[str, Any]] = {}
    for child_slug, child_version in refs:
        if child_version is None:
            row = await pool.fetchrow("SELECT version,graph,smart_call,name FROM workflows WHERE slug=$1 AND status='published' ORDER BY version DESC LIMIT 1", child_slug)
        else:
            row = await pool.fetchrow("SELECT version,graph,smart_call,name FROM workflows WHERE slug=$1 AND version=$2", child_slug, child_version)
        if row:
            child_graph = _j(row["graph"])
            contracts[child_slug] = {"version": row["version"], "name": row["name"],
                                     "output_cardinality": output_cardinality(child_graph),
                                     "is_multi_child": output_cardinality(child_graph) == "many",
                                     # 画布靠它决定这张引用卡能不能「炸开」输入提示词。
                                     "smart_call": bool(row["smart_call"])}
    return contracts


def _apply_asset_type_contract(wf: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Normalize a canvas's declared output type into its public run contract.

    Existing callers that only provide a typed business target remain compatible. New
    callers may send ``asset_type`` explicitly, but cannot switch a canvas to a
    different production contract by doing so.
    """
    declared = {
        str((node.get("config") or {}).get("asset_type"))
        for node in (wf.get("graph", {}).get("nodes") or [])
        if node.get("type") == "gen" and (node.get("config") or {}).get("asset_type")
    }
    declared.update(str(code) for code in (wf.get("graph", {}).get("asset_types") or []) if code)
    if len(declared) != 1:
        # A multi-output canvas routes type per generating node. A top-level
        # asset_type would be ambiguous and must never leak into child flows.
        normalized = dict(inputs)
        normalized.pop("asset_type", None)
        return normalized
    expected = declared.pop()
    supplied = inputs.get("asset_type")
    if supplied and supplied != expected:
        raise WorkflowError(
            f"Canvas {wf['slug']} produces {expected}; asset_type={supplied} is not allowed"
        )
    normalized = dict(inputs)
    normalized["asset_type"] = expected
    return normalized


def _declared_asset_type(wf: dict[str, Any]) -> str | None:
    codes = {str((n.get("config") or {}).get("asset_type")) for n in (wf.get("graph", {}).get("nodes") or [])
             if n.get("type") == "gen" and (n.get("config") or {}).get("asset_type")}
    codes.update(str(code) for code in (wf.get("graph", {}).get("asset_types") or []) if code)
    return codes.pop() if len(codes) == 1 else None


def _apply_asset_input_contract(wf: dict[str, Any]) -> None:
    """Make the asset contract, rather than a canvas hint, drive target selection."""
    from ..assets import get as get_asset_type
    code = _declared_asset_type(wf)
    if not code:
        return
    asset = get_asset_type(code)
    asset_field = dict(wf["input_schema"].get("asset_type") or {})
    asset_field.update({
        "type": "asset_type", "required": True, "desc": "资产类型",
        "allowed_values": [code], "seq": 1,
    })
    asset_field.pop("ui", None)
    wf["input_schema"]["asset_type"] = asset_field
    if not asset.target_ref_kind:
        return
    target = dict(wf["input_schema"].get("target_ref") or {})
    target.update({"type": "resource", "required": True, "desc": "关联对象", "seq": 2})
    target["resource_kinds"] = [f"{asset.target_ref_kind}:{asset.target_content_kind}"
                                if asset.target_content_kind else asset.target_ref_kind]
    wf["input_schema"]["target_ref"] = target


async def _resolve_asset_target(pool: asyncpg.Pool, inputs: dict[str, Any]) -> dict[str, Any]:
    """Resolve target_ref into declared context aliases through the asset contract."""
    from ..assets import get as get_asset_type
    from .resource_refs import parse
    code = inputs.get("asset_type")
    # Multi-output router canvases intentionally have no single target contract;
    # their children apply their own contracts after routing.
    if not code:
        return inputs
    asset = get_asset_type(str(code))
    if not asset.target_ref_kind:
        return inputs
    ref = parse(inputs.get("target_ref"))
    if ((not ref or ref[0] != asset.target_ref_kind)
            and asset.target_ref_kind == "content_node"
            and asset.target_content_kind == "shot" and inputs.get("shot_id")):
        # 「缺什么补什么」（2026-09-20）：分镜类资产（关键帧/视频/尾帧）的关联对象
        # 就是该分镜自身的 content_node——合约里 shot_id 本来就绑定 target.id。
        # 父画布 subflow 只透传 shot_id/project_id（如 shot-video-canvas 的
        # 「首帧（缺才跑）」），调用链拿不到 target_ref 时按 shot_id 等价推导，
        # 不再让「执行整张画布」在子流程入口直接断链。推导后仍走下方常规校验
        # （kind/project 归属），语义不变。
        try:
            shot_id = int(inputs["shot_id"])
        except (TypeError, ValueError):
            shot_id = 0
        if shot_id > 0:
            ref = ("content_node", shot_id)
            inputs = {**inputs, "target_ref": f"content_node:{shot_id}"}
    if not ref or ref[0] != asset.target_ref_kind:
        raise WorkflowError(f"{asset.name}必须选择{asset.target_ref_kind}类型的关联对象")
    out = dict(inputs)
    if asset.target_ref_kind == "content_node":
        row = await pool.fetchrow(
            "SELECT id,kind,parent_id,project_id,title AS name FROM content_nodes "
            "WHERE id=$1 AND deleted_at IS NULL", ref[1])
    elif asset.target_ref_kind == "element":
        row = await pool.fetchrow(
            "SELECT id,kind,NULL::bigint AS parent_id,project_id,name FROM content_elements WHERE id=$1",
            ref[1])
    else:
        return out
    if not row or (asset.target_content_kind and row["kind"] != asset.target_content_kind):
        raise WorkflowError(f"所选关联对象不是{asset.target_content_kind or '允许的内容类型'}")
    if int(out["project_id"]) != row["project_id"]:
        raise WorkflowError("所选关联内容不属于当前项目")
    values = {"target.id": row["id"], "target.parent_id": row["parent_id"],
              "target.project_id": row["project_id"], "target.name": row["name"],
              "target.kind": row["kind"]}
    for key, path in asset.context_bindings:
        if values.get(path) is not None:
            out[key] = values[path]
    return out


# ═══════════ 运行 ═══════════

async def start_run(pool: asyncpg.Pool, *, slug: str, version: int | None,
                    project_id: int | None, node_id: int | None,
                    inputs: dict[str, Any], task_id: int | None = None,
                    parent_run_id: int | None = None, depth: int = 0,
                    options: dict[str, Any] | None = None) -> int:
    """预建 workflow_runs 行并返回 run_id——异步入口先拿 id 立即返回给前端，
    再把真正的执行丢给后台的 run_workflow(run_id=…)。

    options 是「怎么跑」的整份提交（force/stop_after/force_all/range/node_overrides），
    原样落 run_options 列：画布下次打开靠它回填运行范围与强制重跑开关。"""
    from .resource_refs import ResourceRefError, normalize_inputs
    wf = await load_workflow(pool, slug, version)
    try:
        inputs = await normalize_inputs(pool, inputs, project_id)
    except ResourceRefError as e:
        raise WorkflowError(str(e)) from e
    inputs = _apply_asset_type_contract(wf, inputs)
    inputs = await _resolve_asset_target(pool, inputs)
    return await pool.fetchval(
        "INSERT INTO workflow_runs(workflow_id,project_id,node_id,parent_run_id,depth,"
        "task_id,inputs,run_options) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb) RETURNING id",
        wf["id"], project_id, node_id, parent_run_id, depth, task_id,
        json.dumps(inputs, ensure_ascii=False),
        json.dumps(options or {}, ensure_ascii=False))


def _mount_upstream(wf: dict[str, Any], key: str, ctx: dict[str, Any]) -> tuple[str | None, str, str]:
    """挂载点的上游产物：沿入边反向 BFS 收可达节点，取 trace 里**最后生成**的那张。

    多张候选时以「最近一次生成」为准——用户重跑上游，挂载点就指向新的那张；
    这也天然满足了连通性把关（孤岛/支线节点根本不是它的上游，收不到）。"""
    graph = wf.get("graph") or {}
    inc: dict[str, list[str]] = {}
    for e in graph.get("edges") or []:
        inc.setdefault(str(e.get("to")), []).append(str(e.get("from")))
    reach: set[str] = set()
    stack = list(inc.get(str(key)) or [])
    while stack:
        nid = stack.pop()
        if nid in reach:
            continue
        reach.add(nid)
        stack.extend(inc.get(nid) or [])
    best: tuple[str, str, str] | None = None
    for step in ctx.get("__trace__") or []:
        nid = str(step.get("node") or "")
        if nid not in reach:
            continue
        # 不按节点类型过滤：上传/素材（value）节点连过来同样是一个真产物——
        # 「就把这一版现有的图存成封面」是最常见的用法，只认 gen 会让它报
        # 「上游没有可用产物」。判据只有一条：这个节点的输出里真的带 url。
        out = step.get("outputs") or {}
        url = next((out[k] for k in _URL_KEYS if isinstance(out.get(k), str) and out[k]), None)
        if url:
            best = (url, str(out.get("prompt") or ""), nid)
    return best or (None, "", "")


def _mount_subject(cfg: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any] | None:
    """挂载点的业务对象：节点自己声明优先（入口默认挂载点就是这么钉住的），
    没声明就按运行入参推断（角色/场景/镜从 target_ref 来）。"""
    sub = cfg.get("subject")
    if isinstance(sub, dict) and sub.get("kind") and sub.get("id"):
        try:
            return {"kind": str(sub["kind"]), "id": int(sub["id"])}
        except (TypeError, ValueError):
            return None
    from .resource_refs import target_from_inputs
    tgt = target_from_inputs(_artifact_inputs(ctx), None)
    return {"kind": tgt[0], "id": tgt[1]} if tgt else None


async def _auto_store_on_finish(pool: asyncpg.Pool, *, wf: dict[str, Any],
                                ctx: dict[str, Any], project_id: int | None,
                                depth: int) -> None:
    """run 收尾的产物落库补漏（2026-09-17）：单节点/区间试跑时 end 节点不在本次
    范围内，画布作者声明的 store.target 没机会执行——产物只躺在画布附件里，
    业务页（项目概览封面）看不到，用户会以为「画布里生成了，总览却没更新」。

    落库按「画布绑定」走而不是按拓扑走：这张画布声明了产物归宿（store.target），
    本次 run 又真的新产出了图，就照绑定落库。end 本次执行过的话它自己已落过
    （end 分派里的 apply_end_binding），这里跳过；loop/subflow 的子运行不重复落；
    skip 命中的历史产物回显不算新生成，不落。"""
    if not project_id or depth > 0:
        return
    nodes = (wf.get("graph") or {}).get("nodes") or []
    from . import tapflow_ai
    # ① 挂载点（2026-09-17 通用标准方案）：本次 run 没跑到的挂载点补落库——
    # 「连到挂载点的产物才落」由 _mount_upstream 的上游 BFS 天然保证。
    for m in nodes:
        if m.get("type") != "mount" or m.get("id") in ctx:
            continue
        mcfg = m.get("config") or {}
        url, prompt, cand = _mount_upstream(wf, str(m.get("id")), ctx)
        if not url:
            continue
        stored = await tapflow_ai.apply_mount_binding(
            pool, project_id=project_id, outputs={"url": url, "prompt": prompt},
            target=str(mcfg.get("target") or ""), subject=_mount_subject(mcfg, ctx),
            variant=(str(mcfg["variant"]) if mcfg.get("variant") else None))
        log.info("run 收尾挂载点落库（%s 未在本次范围，产物来自 %s）：%s",
                 m.get("id"), cand, stored)
    # ② 旧 end.config.store 兼容（历史画布）：画布作者声明的 store.target 没机会执行时补漏
    end = next((n for n in nodes
                if n.get("type") == "end"), None)
    if not end or end.get("id") in ctx:
        return
    ecfg = end.get("config") or {}
    binding = ecfg.get("store") if isinstance(ecfg, dict) else None
    if not (isinstance(binding, dict) and binding.get("target")):
        return
    url = prompt = None
    cand_node = ""
    for step in reversed(ctx.get("__trace__") or []):
        if step.get("type") != "gen":
            continue
        out = step.get("outputs") or {}
        if out.get("skipped"):
            continue
        cand = next((out[k] for k in _URL_KEYS if isinstance(out.get(k), str) and out[k]), None)
        if cand:
            url, prompt, cand_node = cand, str(out.get("prompt") or ""), str(step.get("node") or "")
            break
    if not url:
        return
    # 连通性把关（2026-09-17 用户定稿）：画布声明的 store.target 是**最终产物**的归宿——
    # 只有沿连线能走到 end 的节点产物才配落库。孤岛节点/支线节点（比如随手拖出来
    # 试模型的「一只小猫」）不连通 end，它的图只留在画布上，不许顶掉项目封面。
    end_id = str(end.get("id"))
    out_map: dict[str, list[str]] = {}
    for e in (wf.get("graph") or {}).get("edges") or []:
        out_map.setdefault(str(e.get("from")), []).append(str(e.get("to")))
    reach: set[str] = set()
    stack = [cand_node]
    reachable = False
    while stack:
        nid = stack.pop()
        if nid in reach:
            continue
        reach.add(nid)
        if nid == end_id:
            reachable = True
            break
        stack.extend(out_map.get(nid) or [])
    if not reachable:
        log.info("run 收尾跳过落库：产物节点 %s 不连通 end（孤岛/支线产物不占用绑定归宿）", cand_node)
        return
    from . import tapflow_ai
    stored = await tapflow_ai.apply_end_binding(
        pool, project_id=project_id, outputs={"url": url, "prompt": prompt},
        binding=binding, auto_store=False)
    log.info("run 收尾产物落库（end 未在本次范围）：%s", stored)


async def run_workflow(pool: asyncpg.Pool, *, slug: str, version: int | None,
                       project_id: int | None, node_id: int | None,
                       inputs: dict[str, Any], task_id: int | None = None,
                       parent_run_id: int | None = None, depth: int = 0,
                       run_id: int | None = None,
                       force: frozenset[str] | set[str] = frozenset(),
                       overrides: dict[str, Any] | None = None,
                       stop_after: str | None = None,
                       options: dict[str, Any] | None = None) -> dict[str, Any]:
    """执行一个工作流，返回结束节点收集到的输出。

    run_id 给了就复用 start_run 预建的行、不再自建；force 是节点 id 集合——命中的
    task/subflow 节点跳过「缺才跑」强制重出（子工作流沿用同一集合，v1 按名字命中）。
    overrides 是节点级入参覆盖 {节点id: {instruction: …}}——画布生成条里改的提示词
    经它进来当**指令层**，改得动 user 段，改不动 anchor 段。

    stop_after 是「跑到这个节点为止」。注意**没有对应的「从哪开始」**：整图永远从头
    往后走，起点之前的节点靠「缺才跑」自然变成只查不生成——这样上游的值照样进 ctx，
    链不会断。画布上的「开始节点」是靠 force 表达的（它及其之后强制重跑）。"""
    if depth > MAX_DEPTH:
        raise WorkflowError(f"子工作流嵌套超过 {MAX_DEPTH} 层，疑似递归引用")
    from .resource_refs import ResourceRefError, normalize_inputs
    wf = await load_workflow(pool, slug, version)
    try:
        inputs = await normalize_inputs(pool, inputs, project_id)
    except ResourceRefError as e:
        raise WorkflowError(str(e)) from e
    inputs = _apply_asset_type_contract(wf, inputs)
    inputs = await _resolve_asset_target(pool, inputs)
    if run_id is None:
        run_id = await pool.fetchval(
            "INSERT INTO workflow_runs(workflow_id,project_id,node_id,parent_run_id,depth,"
            "task_id,inputs,run_options) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb) "
            "RETURNING id",
            wf["id"], project_id, node_id, parent_run_id, depth, task_id,
            json.dumps(inputs, ensure_ascii=False),
            json.dumps(options or {}, ensure_ascii=False))
    log.info("workflow %s v%s run=%s depth=%s 开始", slug, wf["version"], run_id, depth)

    # ctx 是节点间传值的载体：node_key → 该节点的输出
    # __trace__/__node_inputs__ 在这里就建好（而不是让 setdefault 现场创建）：
    # loop 体是 `dict(ctx)` 浅拷贝，容器先在这儿存在，各轮 append 才汇到同一份。
    ctx: dict[str, Any] = {"__inputs__": dict(inputs), "__overrides__": dict(overrides or {}),
                           "__trace__": [], "__node_inputs__": {}}
    outputs: dict[str, Any] = {}
    try:
        # 循环体节点只由 loop 节点驱动，不能在顶层再跑一遍——它们通常没有入边，
        # 顶层拓扑序会把它们当独立起点执行，而那时 __item__ 还没绑定。
        body_ids = {b for n in (wf["graph"].get("nodes") or [])
                    if n.get("type") == "loop"
                    for b in ((n.get("config") or {}).get("body") or [])}
        for node in topo_order(wf["graph"]):
            if node["id"] in body_ids:
                continue
            res = await _run_node(pool, node, ctx=ctx, run_id=run_id, wf=wf,
                                  project_id=project_id, node_id=node_id, depth=depth,
                                  force=force)
            ctx[node["id"]] = res
            if node.get("type") == "end":
                outputs = res or {}
            if stop_after and node["id"] == stop_after:
                log.info("workflow run=%s 在节点 %s 处按 stop_after 停下", run_id, stop_after)
                outputs = {**outputs, "stopped_at": stop_after}
                break
        try:
            await _auto_store_on_finish(pool, wf=wf, ctx=ctx,
                                        project_id=project_id, depth=depth)
        except Exception:  # noqa: BLE001 — 落库补漏不影响 run 本身的结果
            log.warning("workflow run=%s 收尾产物落库失败", run_id, exc_info=True)
        await pool.execute(
            "UPDATE workflow_runs SET status='done', outputs=$2::jsonb, context=$3::jsonb, "
            "finished_at=now() WHERE id=$1", run_id,
            json.dumps(outputs, ensure_ascii=False),
            json.dumps(ctx.get("__trace__") or [], ensure_ascii=False, default=str))
        return outputs
    except Exception as e:
        # 失败时的轨迹比成功时更有用：跑到哪一步、那一步收到了什么，全在里面。
        await pool.execute(
            "UPDATE workflow_runs SET status='failed', error=$2, context=$3::jsonb, "
            "finished_at=now() WHERE id=$1", run_id, str(e)[:800],
            json.dumps(ctx.get("__trace__") or [], ensure_ascii=False, default=str))
        raise


async def _node_run_row(pool: asyncpg.Pool, run_id: int, key: str, iteration: int,
                        inputs: dict[str, Any], ctx: dict[str, Any] | None = None) -> int:
    # 节点入参进 ctx 的同时落库：这是**唯一**记录「这个节点收到了什么」的地方，
    # 下游 {{inputs.节点.字段}} 与运行轨迹都从这一份读，不另开第二条通道。
    if ctx is not None:
        ctx.setdefault("__node_inputs__", {})[key] = inputs
    return await pool.fetchval(
        "INSERT INTO workflow_node_runs(run_id,node_key,iteration,status,inputs) "
        "VALUES ($1,$2,$3,'running',$4::jsonb) "
        "ON CONFLICT (run_id,node_key,iteration) DO UPDATE SET status='running' RETURNING id",
        run_id, key, iteration, json.dumps(inputs, ensure_ascii=False))


async def _node_phase(pool: asyncpg.Pool, nr_id: int, phase: str) -> None:
    """把节点**内部**的子阶段写进 outputs.phase（装配提示词 / 质检中 / 出图中）。

    为什么不加列、不另开通道：node_runs.status 是节点级的（running 就一个值），
    而一个 gen 节点里有三段、每段几十秒；task_queue 里那条出图任务有自己的状态，
    但装配与质检根本不入队，推不出来。outputs 本来就是画布每轮轮询都读的 jsonb，
    往里塞一个 phase 是零 schema 变更、零新通道的做法。"""
    await pool.execute(
        "UPDATE workflow_node_runs SET outputs = outputs || $2::jsonb WHERE id=$1",
        nr_id, json.dumps({"phase": phase}, ensure_ascii=False))


async def _finish_node(pool: asyncpg.Pool, nr_id: int, status: str,
                       outputs: dict[str, Any] | None = None,
                       skip_reason: str | None = None, error: str | None = None) -> None:
    await pool.execute(
        "UPDATE workflow_node_runs SET status=$2, outputs=$3::jsonb, skip_reason=$4, "
        "error=$5, finished_at=now() WHERE id=$1",
        nr_id, status, json.dumps(outputs or {}, ensure_ascii=False), skip_reason,
        (error or None) and error[:800])


def _resolve(spec: Any, ctx: dict[str, Any]) -> Any:
    """入参映射：'{{start.chapter_id}}' → ctx['start']['chapter_id']；其余原样。

    聚合形式 '{{@in.url}}'：按入边顺序收集各上游节点输出的该字段（非空）成列表——
    画布上「拖线即引用」（多张图连进生成节点当参考图）的执行语义。上游字段本身是
    列表时展开合并。'{{@in}}' 不带字段=收集上游完整输出。入边序由 _run_node 在
    分派前写进 ctx['__in__']。"""
    if not isinstance(spec, str) or not (spec.startswith("{{") and spec.endswith("}}")):
        return spec
    path = spec[2:-2].strip().split(".")
    if path[0] == "@in":
        out: list[Any] = []
        for src in ctx.get("__in__") or []:
            cur: Any = ctx.get(src)
            for p in path[1:]:
                cur = cur.get(p) if isinstance(cur, dict) else None
            if cur is None:
                continue
            out.extend(cur) if isinstance(cur, list) else out.append(cur)
        return out
    if path[0] == "ctx":
        # 运行上下文的显式读法。`{{ctx}}` 是整份轨迹（各节点入参/出参），
        # `{{ctx.节点.字段}}` 与 `{{节点.字段}}` 等价——同一份 ctx，只是读得出意图。
        if len(path) == 1:
            return ctx.get("__trace__") or []
        path = path[1:]
    if path[0] == "inputs" and len(path) > 1:
        # 出参一直可引用，入参原来引用不到。`{{inputs.节点.字段}}` 补上这一半，
        # 让「上游节点当时收到了什么」也成为可下传的上下文。
        cur = (ctx.get("__node_inputs__") or {}).get(path[1])
        for p in path[2:]:
            if isinstance(cur, dict):
                cur = cur.get(p)
            else:
                return None
        return cur
    cur = ctx.get("__inputs__") if path[0] == "input" else ctx.get(path[0])
    for p in path[1:]:
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return None
    return cur


_TPL = re.compile(r"\{\{[^{}]+\}\}")
# 「整串就是一个占位符」——那种要保住原类型，走 _resolve；其余走 _fill。
_FULL_TPL = re.compile(r"^\s*\{\{[^{}]+\}\}\s*$")


def _instruction(cfg: dict[str, Any], ctx: dict[str, Any]) -> Any:
    """gen 节点的 instruction 取值（唯一实现：出图、复用回显、预检共用）。

    它是**句子**，占位符嵌在中间——「{{input.grid_prompt}}。严格以…为参考」。
    `_resolve` 只认「整串就是一个占位符」，句子里的原样返回，于是那串 `{{input.…}}`
    会一路进到出图提示词里（实测：预检回来的提示词第一句就是字面量 `{{input.grid_prompt}}`，
    画布生成条里显示的、真发给出图模型的，都是它）。这与 llm 节点的 task 是同一个坑，
    那边早已用 _fill，这边漏了。
    整串是一个占位符的仍走 _resolve：循环体里 `instruction: "{{__item__.prompt}}"`
    要拿到那一项的原值，不能被字符串化。
    """
    spec = cfg.get("instruction")
    if isinstance(spec, str) and "{{" in spec and not _FULL_TPL.match(spec):
        return _fill(spec, ctx)
    return _resolve(spec, ctx)


def _fill(text: str, ctx: dict[str, Any]) -> str:
    """把**嵌在句子里**的占位符替换掉：「项目 {{input.project_id}} 的场景「{{input.scene_name}}」」。

    _resolve 只认「整串就是一个占位符」（那样才能保住 int/list 原类型），
    句子里的占位符它原样返回——LLM 节点的 task 正是这种，不填就把字面量
    `{{input.scene_name}}` 发给模型（实测模型回「因不知具体场景名，以…为例」）。
    与 agent_runtime.fill 同一用途，只是取值走本模块的 ctx。"""
    if not text or "{{" not in text:
        return text
    return _TPL.sub(lambda m: ("" if (v := _resolve(m.group(0), ctx)) is None else str(v)), text)


def _resolve_any(spec: Any, ctx: dict[str, Any]) -> Any:
    """递归解析：list/dict 逐层下钻，叶子字符串走 _resolve——
    让 payload 里嵌套结构（如 [{name, url: '{{input.ref_url}}'}]）也能带占位符。"""
    if isinstance(spec, list):
        return [_resolve_any(v, ctx) for v in spec]
    if isinstance(spec, dict):
        return {k: _resolve_any(v, ctx) for k, v in spec.items()}
    return _resolve(spec, ctx)


def _resolve_all(cfg: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    return {k: _resolve_any(v, ctx) for k, v in (cfg or {}).items()}


def _inbound(wf: dict[str, Any], key: str) -> list[str]:
    """节点入边的上游 id 序（边在 graph 里的书写序）——'{{@in.*}}' 聚合的取数依据。"""
    return [e["from"] for e in (wf["graph"].get("edges") or []) if e.get("to") == key]


def _condition_branch(cfg: dict[str, Any], ctx: dict[str, Any]) -> str | None:
    """Return the first matching branch id; the else branch is the final fallback."""
    branches = cfg.get("branches")
    if not isinstance(branches, list):
        # Compatibility for graphs saved before condition branches existed.
        return "if-1" if _run_if_matches({"run_if": cfg.get("when")}, ctx) else "else"
    for index, branch in enumerate(branches):
        if not isinstance(branch, dict):
            continue
        branch_id = str(branch.get("id") or ("else" if branch.get("kind") == "else" else f"if-{index + 1}"))
        if branch.get("kind") == "else":
            return branch_id
        clauses = branch.get("clauses") or []
        if not isinstance(clauses, list):
            clauses = []
        matches = True
        for clause in clauses:
            if not isinstance(clause, dict):
                continue
            actual = _resolve(clause.get("left"), ctx)
            operator = str(clause.get("operator") or "truthy")
            expected = _resolve(clause.get("right"), ctx)
            if operator == "equals": ok = actual == expected
            elif operator == "not_equals": ok = actual != expected
            elif operator == "contains": ok = expected in actual if isinstance(actual, (str, list, dict)) else False
            elif operator == "empty": ok = actual is None or actual == "" or actual == [] or actual == {}
            else: ok = bool(actual)
            if not ok:
                matches = False
                break
        if matches:
            return branch_id
    return None


def _condition_edge_is_active(wf: dict[str, Any], key: str, ctx: dict[str, Any]) -> bool:
    """A branch edge is active only when its source condition selected that branch."""
    gated = [e for e in (wf["graph"].get("edges") or [])
             if e.get("to") == key and e.get("branch")]
    if not gated:
        return True
    return any((ctx.get(str(edge.get("from"))) or {}).get("matched_branch") == edge.get("branch")
               for edge in gated)


def _run_if_matches(cfg: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """Evaluate a deliberately small, declarative branch guard for loop bodies."""
    condition = cfg.get("run_if")
    if not isinstance(condition, dict):
        return True
    actual = _resolve(condition.get("value"), ctx)
    if "equals" in condition:
        return actual == condition["equals"]
    if "not_equals" in condition:
        return actual != condition["not_equals"]
    return bool(actual)


async def _run_node(pool: asyncpg.Pool, node: dict[str, Any], *, ctx: dict[str, Any],
                    run_id: int, wf: dict[str, Any], project_id: int | None,
                    node_id: int | None, depth: int, iteration: int = 0,
                    force: frozenset[str] | set[str] = frozenset()) -> Any:
    """分派 + **记一条运行轨迹**。

    轨迹（ctx['__trace__']）是「这一轮都发生了什么」的唯一记录：节点、类型、标题、
    入参、出参，按真实执行序排列。它有两个消费方，都不再自己拼一份：
    落 workflow_runs.context 供回看，以及 workflow_planner 当历史对话喂给模型。
    包在这一层是刻意的——每个节点类型各自 append 迟早会漏掉某一种。"""
    out = await _dispatch_node(pool, node, ctx=ctx, run_id=run_id, wf=wf,
                              project_id=project_id, node_id=node_id, depth=depth,
                              iteration=iteration, force=force)
    trace = ctx.setdefault("__trace__", [])
    if isinstance(trace, list):
        trace.append({
            "node": node["id"], "type": node.get("type"),
            "title": ((node.get("config") or {}).get("ui") or {}).get("title") or node["id"],
            "iteration": iteration,
            "inputs": (ctx.get("__node_inputs__") or {}).get(node["id"]),
            "outputs": _trace_value(out),
        })
    return out


def _trace_value(value: Any, depth: int = 0) -> Any:
    """轨迹只留能读的摘要：长文截断、深层结构折叠。整份 ctx 原样落库会有几 MB，
    既撑爆 run 行也塞不进模型上下文。"""
    if isinstance(value, str):
        return value if len(value) <= 600 else value[:600] + f"…（共 {len(value)} 字）"
    if isinstance(value, dict):
        if depth >= 3:
            return {"…": f"{len(value)} 个字段"}
        return {k: _trace_value(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        if depth >= 3:
            return f"{len(value)} 项"
        head = [_trace_value(v, depth + 1) for v in value[:10]]
        return head if len(value) <= 10 else [*head, f"…另有 {len(value) - 10} 项"]
    return value


async def _dispatch_node(pool: asyncpg.Pool, node: dict[str, Any], *, ctx: dict[str, Any],
                         run_id: int, wf: dict[str, Any], project_id: int | None,
                         node_id: int | None, depth: int, iteration: int = 0,
                         force: frozenset[str] | set[str] = frozenset()) -> Any:
    # iteration：循环体节点必须带上本轮序号，否则 N 轮都写 (run_id,node_key,0)，
    # 撞同一个唯一索引互相覆盖，画布上回放循环就只剩最后一格。
    ntype = node.get("type")
    key = node["id"]
    cfg = node.get("config") or {}
    ctx["__in__"] = _inbound(wf, key)
    ctx["__graph__"] = _graph_index(wf)   # 上文回溯的目录（标题/类型/入边）

    if not _condition_edge_is_active(wf, key, ctx):
        return {"skipped": True, "reason": "condition branch does not match"}

    if not _run_if_matches(cfg, ctx):
        return {"skipped": True, "reason": "asset type branch does not match"}

    if ntype == "start":
        # 开始节点即签名：把外部入参按 input_schema 暴露给下游
        return dict(ctx.get("__inputs__") or {})

    if ntype == "value":
        # 画布自由素材节点（文本/上传图/参数常量）：config.value 原样解析后进 ctx，
        # 供下游 {{节点.字段}} / {{@in.url}} 引用。没有副作用，只是数据。
        nr = await _node_run_row(pool, run_id, key, iteration, {}, ctx=ctx)
        out = _resolve_all(cfg.get("value") or {}, ctx)
        await _finish_node(pool, nr, "done", out)
        return out

    if ntype == "condition":
        nr = await _node_run_row(pool, run_id, key, iteration, {}, ctx=ctx)
        if not isinstance(cfg.get("branches"), list):
            when = cfg.get("when") or {}
            actual = _resolve(when.get("value"), ctx) if isinstance(when, dict) else None
            operator = str(when.get("operator") or "truthy") if isinstance(when, dict) else "truthy"
            matched = actual == when.get("equals") if operator == "equals" else actual != when.get("not_equals") if operator == "not_equals" else bool(actual)
            out = {"matched": matched, "value": _resolve_any(cfg.get("then") if matched else cfg.get("else"), ctx), "actual": actual}
        else:
            out = {"matched_branch": _condition_branch(cfg, ctx)}
        await _finish_node(pool, nr, "done", out)
        return out

    if ntype == "end":
        nr = await _node_run_row(pool, run_id, key, iteration, {}, ctx=ctx)
        out = _resolve_all(cfg.get("outputs") or {}, ctx)
        await _finish_node(pool, nr, "done", out)
        # 产物存储（2026-09-17）：end 节点声明 store.target 就按绑定落库（如封面画布
        # → config.cover_url）；没绑定但开了 aiStore，由模型从白名单动作里规划存哪。
        # 失败只记日志：存储挂了不该把一次成功的生成判成 failed。
        if project_id and (isinstance(cfg.get("store"), dict) or cfg.get("aiStore")):
            try:
                from . import tapflow_ai
                stored = await tapflow_ai.apply_end_binding(
                    pool, project_id=project_id, outputs=out if isinstance(out, dict) else {},
                    binding=cfg.get("store"), auto_store=bool(cfg.get("aiStore")))
                log.info("end 节点 %s 产物存储：%s", key, stored)
            except Exception:  # noqa: BLE001
                log.warning("end 节点 %s 产物存储异常（run %s）", key, run_id, exc_info=True)
        return out

    if ntype == "mount":
        # 挂载点（2026-09-17 通用标准方案）：画布上独立声明的产物归宿——
        # 连到它的产物就是它要存的那张（多张候选取最近生成的），真实数据指向它。
        nr = await _node_run_row(pool, run_id, key, iteration, {}, ctx=ctx)
        url, prompt, src = _mount_upstream(wf, key, ctx)
        target = str(cfg.get("target") or "")
        if not url:
            out = {"stored": "skipped", "reason": "上游没有可用产物", "target": target}
        elif not project_id:
            out = {"stored": "skipped", "reason": "没有项目上下文", "target": target}
        else:
            from . import tapflow_ai
            stored = await tapflow_ai.apply_mount_binding(
                pool, project_id=project_id, outputs={"url": url, "prompt": prompt},
                target=target, subject=_mount_subject(cfg, ctx),
                variant=(str(cfg["variant"]) if cfg.get("variant") else None))
            out = {"url": url, "prompt": prompt, "source_node": src,
                   "target": target, **stored}
            log.info("挂载点 %s（%s）落库：%s（产物来自 %s）", key, target, stored, src)
        await _finish_node(pool, nr, "done", out)
        return out

    if ntype == "action":
        # 命名动作：补上"装配逻辑在 API 端点里、不在 Step 里"这个缺口（见 workflow_actions 模块头）
        from . import workflow_actions

        name = cfg.get("name") or ""
        fn = workflow_actions.get(name)
        if not fn:
            raise WorkflowError(
                f"未注册的动作 {cfg.get('name')!r}（可用: {', '.join(workflow_actions.names())}）")
        args = _resolve_all(cfg.get("args") or {}, ctx)
        nr = await _node_run_row(pool, run_id, key, iteration, args, ctx=ctx)
        # 规划类动作（wants_ctx）额外收整份 ctx：它的活就是自己判断该读上游的哪一部分，
        # 入参无法预先写死成 {{节点.字段}}。见 workflow_actions.register 的说明。
        spec = workflow_actions.spec(name) or {}
        # 不要无条件带上 flow_ctx=None：普通动作的调用签名保持原样，这一层改动就
        # 只影响规划类节点，既有工作流的调用形状一个字节都不变。
        extra = {"_ctx": ctx} if spec.get("wants_ctx") else {}
        ctx_kw = {"flow_ctx": ctx} if spec.get("wants_ctx") else {}
        try:
            # 画布新增的真正工具节点走统一调用入口，从而复用必填校验与 tool_calls 审计。
            # 历史 action 节点保持原路径，避免一次改动改变既有生产工作流的审计副作用。
            if ((cfg.get("ui") or {}).get("tap") == "tool"):
                from . import tools as tool_registry
                out = await tool_registry.invoke(
                    pool, name, args, caller="workflow", source="workflow",
                    project_id=project_id, **ctx_kw)
            else:
                out = await fn(pool, **args, **extra)
        except Exception as e:
            await _finish_node(pool, nr, "failed", {}, error=str(e))
            raise WorkflowError(f"动作节点 {key} 失败: {e}") from e
        await _finish_node(pool, nr, "done", out)
        return out

    if ntype == "gen":
        return await _run_gen_node(pool, node, ctx=ctx, run_id=run_id,
                                   project_id=project_id, node_id=node_id,
                                   iteration=iteration, force=force)

    if ntype == "llm":
        return await _run_llm_node(pool, node, ctx=ctx, run_id=run_id,
                                   project_id=project_id, node_id=node_id,
                                   iteration=iteration, force=force)

    if ntype == "task":
        return await _run_task_node(pool, node, ctx=ctx, run_id=run_id,
                                    project_id=project_id, node_id=node_id,
                                    iteration=iteration, force=force)

    if ntype == "subflow":
        return await _run_subflow_node(pool, node, ctx=ctx, run_id=run_id,
                                       project_id=project_id, node_id=node_id, depth=depth,
                                       iteration=iteration, force=force)

    if ntype == "loop":
        return await _run_loop_node(pool, node, ctx=ctx, run_id=run_id, wf=wf,
                                    project_id=project_id, node_id=node_id, depth=depth,
                                    force=force)

    raise WorkflowError(f"未知节点类型: {ntype}（节点 {key}）")


# ═══════════ 通用生成节点（画布上的图片/视频/音频节点）═══════════
# 提示词三层装配 —— 全站唯一的合成口径，各模态差异只在装配器内部，不外溢到画布：
#   user   = 装配器叙事段 ⊕ 上游文本节点产物 ⊕ 本节点用户指令（越靠后解释权越强）
#   anchor = 装配器结构段（版式/画风锚/质量词/偏好）—— 只来自 bind，画布改不了
# 合成一律走 prompt_fields.compose，不在这里另写拼接规则。

_TEXT_KEYS = ("text", "output", "summary")     # 上游文本节点产出的正文字段（按序取第一个非空）
_URL_KEYS = ("url", "sheet_url", "image_url", "video_url")   # 上游媒体节点产出的产物地址


def _upstream_media(ctx: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """按入边序收集上游产物，并按**类型**分流（画布「拖线即引用」的执行语义）：
    文本类 → 提示词素材；媒体类 → 参考图/帧。上游同时给了文本和 url 的（如 gen 节点
    返回 {url, prompt}）只取 url，不然会把上一张图的提示词又拼进来。"""
    texts: list[str] = []
    refs: list[dict[str, Any]] = []
    def append_nested(value: Any, source: str) -> None:
        """collect 边不制造节点：递归展开 loop/subflow 产物，直接作为下游参考。"""
        if isinstance(value, list):
            for item in value:
                append_nested(item, source)
            return
        if not isinstance(value, dict):
            return
        url = next((value[k] for k in _URL_KEYS
                    if isinstance(value.get(k), str) and value[k]), None)
        if url:
            refs.append({"name": value.get("name") or source,
                         "kind": value.get("kind") or "canvas", "url": url,
                         **({"element_id": value["element_id"]} if value.get("element_id") else {})})
            return
        for key in ("refs", "items", "reference_images", "results"):
            if key in value:
                append_nested(value[key], source)
        # loop body 的 key 是模板节点 id，不属于固定协议；继续递归其对象值。
        for key, nested in value.items():
            if key not in {"refs", "items", "reference_images", "results"} \
                    and isinstance(nested, (dict, list)):
                append_nested(nested, source)

    for src in ctx.get("__in__") or []:
        out = ctx.get(src)
        if not isinstance(out, dict):
            continue
        url = next((out[k] for k in _URL_KEYS if isinstance(out.get(k), str) and out[k]), None)
        if url:
            refs.append({"name": src, "kind": "canvas", "url": url})
            continue
        append_nested(out, src)
        txt = next((out[k] for k in _TEXT_KEYS if isinstance(out.get(k), str) and out[k]), None)
        if txt:
            texts.append(txt)
    return texts, refs


_ROUTE_KEYS = {"project_id", "target_ref", "element_id", "shot_id", "node_id",
               "chapter_id", "force_all"}   # 寻址/路由键：不是创作内容，不进上文
_CTX_ITEM_MAX = 400        # 单条上文截断（字）
_CTX_BLOCK_MAX = 3600      # 整块上文截断：上文是给模型「知道有什么」的，不是全文照搬


def _graph_index(wf: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """画布轻量拓扑：id → 标题/类型/直接上游。给 _canvas_context 做祖先回溯与
    「这条上文是谁」的标注用——只取目录信息，不携带 config 执行数据。"""
    idx: dict[str, dict[str, Any]] = {}
    for n in ((wf.get("graph") or {}).get("nodes")) or []:
        nid = str(n.get("id"))
        cfg = n.get("config") or {}
        ui = cfg.get("ui") if isinstance(cfg.get("ui"), dict) else {}
        idx[nid] = {
            "title": str((ui or {}).get("title") or nid),
            "type": str(n.get("type")),
            "in": _inbound(wf, nid),
        }
    return idx


async def _active_image_ref_cap(pool: asyncpg.Pool) -> int | None:
    """当前 active 出图档的参考图上限（能力档案，None=未知不判断）。
    上文标注要与真实提交一致：模型不吃参考图（如 wanx-v1）时，
    图片行不能谎称「已作为参考图传入」——用户看着提示词以为图传了，实际被裁了。"""
    try:
        from .. import models_registry
        prof = await models_registry.get_active("image")
        if not prof:
            return None
        from . import model_caps
        return model_caps.ref_cap(prof, 4)
    except Exception:  # noqa: BLE001 — 能力查不到时不改变旧标注
        return None


def _ctx_line(nid: str, out: Any, meta: dict[str, Any], ref_cap: int | None = None,
              img_no: int | None = None, *, passed: bool | None = None,
              label: str | None = None) -> str | None:
    """一个上游节点的产物 → 一行带标注的上文。空产物返回 None。
    ref_cap：当前出图档的参考图上限（能力档案）——0=模型不吃参考图，
    图片行不许谎称「已作为参考图传入」（2026-09-17 用户实测抓到的假标注）。
    img_no：本图是提交的第几张参考图——与提示词里的 @图片N 一一对应
    （Seedream 多图引用的官方写法：图1、图2…模型按序号对图）。
    passed/label：提交名单口径（2026-09-18 定稿）——True=按提交名单标注
    「已作为{label}传入」（首帧/尾帧/第 N 张参考图）；False=如实标
    「未传入模型（仅文字参考）」，绝不谎称已传；None=旧口径按 img_no。"""
    title = str(meta.get("title") or nid)
    ntype = str(meta.get("type") or "")
    if ntype == "start" or nid == "start":
        return None  # start 的信息走统一的「项目/入参」行，不按产物处理
    if not isinstance(out, dict):
        return None
    if out.get("skipped") and not next((out[k] for k in (*_TEXT_KEYS, *_URL_KEYS)
                                        if isinstance(out.get(k), str) and out[k]), None):
        return None  # 纯跳过且**没有任何产物回显**（url/文本都没有）才不算上文——
    # 带图回显的 skip（缺才跑命中，上游已有产物）照样要标进上文：
    # 不然参考图传了、上文却不写「图片1「小猫」」，@图片N 的对应关系就断了
    #（2026-09-17 端到端实测：上文明明该有小猫行，却被当纯跳过扔了）
    url = next((out[k] for k in _URL_KEYS if isinstance(out.get(k), str) and out[k]), None)
    if url:
        if passed is False:
            return f"图片「{title}」：未传入模型（仅文字参考，不算已提交的参考图）"
        if passed is True and label:
            return f"图片{img_no}「{title}」：已作为{label}传入"
        if ref_cap is not None and ref_cap <= 0:
            return f"图片「{title}」：（当前出图模型不支持参考图，此图仅供文字参考）"
        if img_no:
            return f"图片{img_no}「{title}」：已作为第 {img_no} 张参考图传入"
        return f"图片「{title}」：已作为参考图传入"
    txt = next((out[k] for k in _TEXT_KEYS if isinstance(out.get(k), str) and out[k]), None)
    if txt:
        return f"文本「{title}」：{str(txt)[:_CTX_ITEM_MAX]}"
    return None


async def _canvas_context(pool: asyncpg.Pool, ctx: dict[str, Any], *,
                          project_id: int | None = None, only: bool = False,
                          submitted: list[tuple[str, str]] | None = None) -> str:
    """画布上文（通用语义，2026-09-18 定稿）：**上下文严格跟连线走，标注必须如实**。

    沿连线回溯全部上游，按「标题（类型）：内容」标注成清单交给写提示词的模型——
    上游有什么，模型就看见什么、按需取用、自主规划提示词。项目行/入参行只代表
    start 的信息：**start 连得到**（直接或经上游链）才在列；手拖的孤岛节点不再被
    无条件注入项目画风/旧封面这类入参（2026-09-17 的「图片节点天然知道项目设定」
    废止——实测它会污染与项目无关的独立生成）。

    submitted：本次**真正提交给模型**的媒体 [(url, 用途), …]（按提交顺序）。图片行
    的「已作为第 N 张参考图/首帧传入」以此为准；没提交的祖先图如实标「未传入模型
    （仅文字参考）」——祖先回溯把没提交的图也编号成「已传入」是实测抓到的假标注，
    会诱导规划模型引用不存在的图。None=调用方不提供（退回按上文出现顺序编号的旧
    口径）；LLM 文本节点传 []（不吃图，图片行全部如实标未传入）。

    only=True（生成条手选了参考节点）时只看直接入边这几个，不向上递归——
    手选的语义就是「我明确只要这几个」。项目行由 project_id 直接取库
    （title/画风/主线/画幅/文风）。"""
    g = ctx.get("__graph__") or {}
    roots = [str(x) for x in (ctx.get("__in__") or [])]
    # 祖先回溯：近→远收集后反转为远→近（start 端在前，读起来像对话历史）
    if only:
        order = list(dict.fromkeys(roots))
    else:
        order, visited = [], set()
        stack = list(dict.fromkeys(roots))
        while stack:
            nid = stack.pop(0)
            if nid in visited:
                continue
            visited.add(nid)
            order.append(nid)
            for src in ((g.get(nid) or {}).get("in")) or []:
                if str(src) not in visited:
                    stack.append(str(src))
        order.reverse()
    if not order:
        # 连线拓扑即上下文（2026-09-17 用户定稿，2026-09-18 重申）：**没有任何被
        # 采纳的上游连线 = 独立生成**。入参/项目设定一概不注入——从空白拖出的
        # 图片节点写「一只小猫」，出的就该是纯小猫。
        return ""
    # 项目行/入参行代表的是 start 的信息：start 连得到（直接或经上游链）才在列
    start_wired = any(nid == "start" or (g.get(nid) or {}).get("type") == "start"
                      for nid in order)
    lines: list[str] = []
    img_cap = await _active_image_ref_cap(pool)
    # 标注口径二选一：有提交名单（submitted）→ 图片行只按**真正提交**的数组编号
    # 与标注（如实）；没名单（旧口径/直调）→ 按上文出现顺序给图编号（图片1、图片2…）
    sub_map: dict[str, tuple[int, str]] = {}
    if submitted is not None:
        for i, (u, lab) in enumerate(submitted, 1):
            sub_map.setdefault(str(u), (i, lab))
    img_no = 0
    for nid in order:
        out = ctx.get(nid)
        has_url = isinstance(out, dict) and any(
            isinstance(out.get(k), str) and out.get(k) for k in _URL_KEYS)
        if submitted is None:
            line = _ctx_line(nid, out, g.get(nid) or {}, img_cap,
                             img_no + 1 if has_url and img_cap != 0 else None)
            if line:
                lines.append(line)
                if has_url and img_cap != 0:
                    img_no += 1
            continue
        url = next((out[k] for k in _URL_KEYS
                    if isinstance(out.get(k), str) and out[k]), None) if has_url else None
        hit = sub_map.get(url) if url else None
        line = _ctx_line(nid, out, g.get(nid) or {}, img_cap,
                         hit[0] if hit else None, passed=bool(hit),
                         label=hit[1] if hit else None)
        if line:
            lines.append(line)
    if start_wired:
        # start 的入参（章/镜/要素等定位值）与项目设定，只随连得到 start 的节点注入
        inputs = ctx.get("__inputs__") or {}
        facts = "；".join(f"{k} {v}" for k, v in (inputs or {}).items()
                         if v not in (None, "") and k not in _ROUTE_KEYS)
        if facts:
            lines.insert(0, f"入参：{str(facts)[:_CTX_ITEM_MAX]}")
    if start_wired and project_id:
        try:
            row = await pool.fetchrow(
                "SELECT title, art_style, storyline, writing_style, config"
                " FROM content_projects WHERE id=$1", int(project_id))
            if row:
                bits = [f"项目「{row['title']}」"]
                for label, val in (("画风", row["art_style"]), ("主线", row["storyline"]),
                                   ("文风", row["writing_style"])):
                    if (val or "").strip():
                        bits.append(f"{label} {str(val)[:200]}")
                cfg_raw = row["config"]
                if cfg_raw:
                    cfg_d = json.loads(cfg_raw) if isinstance(cfg_raw, str) else cfg_raw
                    asp = (cfg_d or {}).get("aspect") or (cfg_d or {}).get("cover_aspect")
                    if asp:
                        bits.append(f"画幅 {asp}")
                lines.insert(0, bits[0] + "：" + "；".join(bits[1:]) if len(bits) > 1 else bits[0])
        except Exception:  # noqa: BLE001 — 上文取不到不该挡住生成
            pass
    if not lines:
        return ""
    block = "\n".join(f"- {x}" for x in lines)
    if len(block) > _CTX_BLOCK_MAX:
        block = block[:_CTX_BLOCK_MAX]
    return ("【画布上文】连线传来的上游内容，按需取用、自行组织进提示词；"
            "标注「已传入」的图在本次提交给模型的参考媒体里，"
            "未标注的仅供文字理解：\n" + block)


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for r in refs:
        u = r.get("url")
        if u and u not in seen:
            seen.add(u)
            out.append(r)
    return out


def _submitted_media(payload: dict[str, Any], modality: str) -> list[tuple[str, str]]:
    """本次**真正提交给模型**的媒体 [(url, 用途标注), …]，按提交顺序。

    画布上文的「已传入」标注以此为准——标注必须与提交数组一一对应，不许把没
    提交的祖先图也编号成「已传入」（假标注会诱导规划模型引用不存在的图，
    2026-09-18 用户实测：视频节点上文写了 3 张「已传入」，实际只提交了 2 张）。"""
    if modality == "video":
        first = payload.get("first_frame_url")
        last = payload.get("last_frame_url")
        if first and last and first != last:
            return [(str(first), "首帧"), (str(last), "尾帧")]
        if first:
            return [(str(first), "首帧与尾帧" if last else "首帧")]
        if last:
            return [(str(last), "尾帧")]
        return []
    if modality == "audio":
        a = payload.get("reference_audio")
        return [(str(a), "参考音频")] if a else []
    out: list[tuple[str, str]] = []
    for i, r in enumerate(payload.get("reference_images") or [], 1):
        u = r.get("url") if isinstance(r, dict) else r
        if isinstance(u, str) and u:
            out.append((u, f"第 {i} 张参考图"))
    return out


async def _record_artifact_provenance(pool: asyncpg.Pool, *, run_id: int, node_run_id: int,
                                      node_key: str, iteration: int, project_id: int | None,
                                      node_id: int | None, inputs: dict[str, Any], cfg: dict[str, Any],
                                      url: str | None) -> None:
    """Link an output to both its business target and its exact producing run."""
    if not project_id or not url:
        return
    from ..assets import get as get_asset_type, legacy_type
    from .resource_refs import output_slot, target_from_inputs
    slot = output_slot(cfg, inputs)
    if not slot:
        return
    target = target_from_inputs(inputs, node_id)
    asset_type = str(cfg.get("asset_type") or legacy_type(slot[0], target[0]) or "") or None
    asset_contract = None
    if asset_type:
        asset_contract = get_asset_type(asset_type)
        if target and asset_contract.subject_kind != "none" and asset_contract.subject_kind != target[0]:
            raise WorkflowError(
                f"Asset type {asset_type} requires subject_kind={asset_contract.subject_kind}, "
                f"but this node received {target[0]}"
            )
    attachment_id = await pool.fetchval(
        "SELECT id FROM content_attachments WHERE project_id=$1 AND url=$2 ORDER BY id DESC LIMIT 1",
        project_id, url)
    # A common asset has no business subject. Its attachment itself is the legacy
    # target required by workflow_artifacts, while subject_kind stays 'none'.
    if not target and asset_contract and asset_contract.subject_kind == "none" and attachment_id:
        target = ("attachment", attachment_id)
    if not target:
        return
    subject_kind = asset_contract.subject_kind if asset_contract else target[0]
    subject_id = None if subject_kind == "none" else target[1]
    artifact_id = await pool.fetchval(
        "INSERT INTO workflow_artifacts(project_id,attachment_id,target_kind,target_id,role,variant,url,"
        "asset_type,subject_kind,subject_id,version) "
        "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,"
        "COALESCE((SELECT MAX(version)+1 FROM workflow_artifacts "
        "WHERE project_id=$1 AND asset_type IS NOT DISTINCT FROM $8 "
        "AND subject_kind=$9 AND subject_id IS NOT DISTINCT FROM $10 AND variant IS NOT DISTINCT FROM $6), 1)) "
        "RETURNING id",
        project_id, attachment_id, target[0], target[1], slot[0], slot[1], url, asset_type,
        subject_kind, subject_id)
    workflow_id = await pool.fetchval("SELECT workflow_id FROM workflow_runs WHERE id=$1", run_id)
    await pool.execute(
        "INSERT INTO workflow_artifact_provenance(artifact_id,workflow_id,workflow_run_id,workflow_node_run_id,node_key,iteration,operation) "
        "VALUES($1,$2,$3,$4,$5,$6,$7)", artifact_id, workflow_id, run_id, node_run_id,
        node_key, iteration, str(cfg.get("operation") or cfg.get("step") or ""))


def _artifact_inputs(ctx: dict[str, Any]) -> dict[str, Any]:
    """Use the current loop descriptor as the artifact target, when present."""
    inputs = dict(ctx.get("__inputs__") or {})
    item = ctx.get("__item__")
    if isinstance(item, dict):
        for key in ("target_ref", "project_id"):
            if item.get(key) is not None:
                inputs[key] = item[key]
    return inputs


async def _run_gen_node(pool: asyncpg.Pool, node: dict[str, Any], *, ctx: dict[str, Any],
                        run_id: int, project_id: int | None, node_id: int | None,
                        iteration: int = 0,
                        force: frozenset[str] | set[str] = frozenset()) -> Any:
    """通用媒体生成节点：三层装配 → 入队既有 Step → 产物 url 直出 outputs。

    出图/出视频本体不在这里——config.step 指名复用哪个已注册 Step（落库、附件、
    meta 回写全按那个 Step 的 next 走），本节点只负责把 payload 装配对。"""
    from . import flow

    cfg = node.get("config") or {}
    key = node["id"]
    modality = cfg.get("modality") or "image"
    step = cfg.get("step")
    if not step:
        raise WorkflowError(f"gen 节点 {key} 缺 config.step（要入队哪个生成步骤）")
    if cfg.get("require_upstream_success"):
        failed = [(src, ctx.get(src, {}).get("failed")) for src in (ctx.get("__in__") or [])
                  if isinstance(ctx.get(src), dict) and int(ctx[src].get("failed") or 0) > 0]
        if failed:
            detail = "、".join(f"{src}({count})" for src, count in failed)
            raise WorkflowError(f"上游参考生成存在失败实例，已阻断本节点：{detail}")

    # 先建 run 行再干活：一个 gen 节点里有装配→质检→出图三段，每段几十秒，
    # 画布只看 running/done 分不出在哪一段（右上角那枚徽标就没得显示）。
    # 阶段写进 outputs.phase，轮询顺带就带回去了，不用加列也不用另开通道。
    nr = await _node_run_row(pool, run_id, key, iteration,
                             {"step": step, "modality": modality}, ctx=ctx)

    # Reuse is decided before model prompt assembly. A skipped image must not
    # spend an LLM call merely to recreate a prompt that will never be generated;
    # the small display-only recovery below only reads a configured layer source.
    # The second check below remains in place to close the race with another run.
    if not cfg.get("force") and not _forced(key, force):
        done, why, val = await _already_done(pool, cfg, ctx)
        if done:
            out = {"skipped": True, "reason": why, "url": val}
            out.update(await _reused_gen_outputs(pool, cfg, ctx, key))
            await _finish_node(pool, nr, "skipped", out, skip_reason=why)
            await _record_artifact_provenance(
                pool, run_id=run_id, node_run_id=nr, node_key=key,
                iteration=iteration, project_id=project_id, node_id=node_id,
                inputs=_artifact_inputs(ctx), cfg=cfg, url=val)
            return out

    await _node_phase(pool, nr, "装配材料")
    layers, refs = await _assemble_layers(pool, cfg, ctx)
    # 通配键兜底：本节点在**子工作流里**跑时，外层给的是引用节点的 id，
    # 内层节点名对不上——subflow 把外层那份挂到 FORCE_ALL 键上供内层取用
    _ovr = ctx.get("__overrides__") or {}
    override = _ovr.get(key) or _ovr.get(FORCE_ALL) or {}
    # 画布生成条里手选了参考节点，就只收这几个上游，不再无差别收全部入边。
    # 传的是**节点 id** 不是 url：节点重跑后产物会变，按 id 取才永远是最新那份。
    picked = override.get("ref_nodes")
    if isinstance(picked, list):
        # 手选顺序即参考顺序：@图片N / 参考图第 N 张都按这个序（不是入边拓扑序）
        up_ctx = {**ctx, "__in__": [x for x in picked if x in set(ctx.get("__in__") or [])]}
    else:
        up_ctx = ctx
    _, up_refs = _upstream_media(up_ctx)   # 媒体照旧按类型进参考图
    # 参考名单先行：先定「本次真正提交给模型的媒体」（截断/首尾帧取舍都落定），
    # 画布上文的标注才有据可依——「已传入」必须与提交数组一一对应，不许多算
    #（2026-09-18 用户实测：祖先回溯把没提交的图也编号成「已传入」，纯假标注）
    all_refs = _dedupe_refs([*refs, *up_refs])
    payload = _resolve_all(cfg.get("payload") or {}, ctx)
    if cfg.get("model_profile_id"):
        payload["model_profile_id"] = int(cfg["model_profile_id"])
    # 功能配置：节点点名功能 code（如九宫格），生成侧按功能的模型顺序取第一个
    if cfg.get("feature_code"):
        payload["feature_code"] = str(cfg["feature_code"])
    if layers.get("hair"):
        payload["hair_prompt"] = layers["hair"]
    notes = _apply_refs(payload, all_refs, modality, cfg)
    # 画布上文（通用语义）：上下文严格跟连线走——上游产物带如实标注交给模型
    # 按需取用、自主规划提示词；项目/入参行只在 start 连得到时在列。
    ctx_block = await _canvas_context(
        pool, up_ctx, project_id=project_id, only=isinstance(picked, list),
        submitted=_submitted_media(payload, modality))
    # anchor 在两条分支外先绑定：手编分支不重算它，但下面质检要用同一个名字，
    # 留着「只在 else 里赋值」迟早会在某次改动后炸成 NameError
    anchor = ""
    # 生成条里写的是**用户需求层**（override.prompt 优先，其次 instruction，最后画布
    # 作者配的默认指令）——「一只小猫在等待空气炸锅产出的鸡腿」这样的短句就够。
    # 系统层（实体叙事/画布上文/系统提示词/技能）由节点绑定**隐式挂载**：这里拼进
    # material 交给写提示词模型按需取用，不回显、不占用户的输入框（2026-09-17 定稿）。
    instruction = override.get("prompt")
    if not str(instruction or "").strip():
        instruction = override.get("instruction")
    if instruction is None:
        instruction = _instruction(cfg, ctx)
    # 料的顺序就是模型阅读的优先级（2026-09-17 用户实测抓到的主次颠倒）：
    # **需求句独立成段放最前**——上一版把需求粘在上文块尾部（「…强化记忆点。@Image
    # 吃汉堡」），需求被几百字的项目设定淹没，出图只剩汉堡没有小猫。现在：
    # ①【本次需求】一行开门见山；②画布上文（带图片编号，与提交参考图一一对应）
    # 在后按需引用；③装配器叙事殿后。
    material = "\n".join(x.strip() for x in
                         [f"【本次需求】{instruction}" if str(instruction or "").strip() else "",
                          ctx_block, layers.get("user") or ""]
                         if x and str(x).strip())
    await _node_phase(pool, nr, "分析提示词")
    # 配了系统提示词 → 用它当规划员的风格指令；没配 → 内置默认规划员。
    # 两条路都走同一个 AI 主路：先对需求/材料做生成前分析（要点进 run 日志），
    # 再写出图提示词——拼串兜底已退役（提案 A，回显语义分裂的根源）。
    written, analysis = await _write_prompt_by_charter(
        pool, cfg, material=material, project_id=project_id, node_key=key,
        subject_name=str(layers.get("name") or ""), flow_ctx=ctx)
    prompt = written
    # 质检判的是「写出来的这段」——它本身就是可改的那份，没有锁死的 anchor 要豁免
    user, anchor = written, ""
    # 分析要点对用户可见：进 run 的阶段与产物（轮询投影 → run 卡明细一行），
    # 完整提示词仍只回填生成条（系统层不占输入框）
    if analysis:
        await _node_phase(pool, nr, f"提示词分析：{analysis.splitlines()[0][:80]}")
    log.info("gen 节点 %s 提示词来源：AI 主路（需求层 %d 字→提示词 %d 字）", key,
             len(str(instruction or "")), len(prompt))
    payload["prompt"] = prompt

    if not cfg.get("force") and not _forced(key, force):
        done, why, val = await _already_done(pool, cfg, ctx)
        if done:
            await _finish_node(pool, nr, "skipped", {"url": val, "prompt": prompt,
                                                       "reference_images": all_refs},
                               skip_reason=why)
            await _record_artifact_provenance(pool, run_id=run_id, node_run_id=nr, node_key=key,
                                              iteration=iteration, project_id=project_id, node_id=node_id,
                                              inputs=_artifact_inputs(ctx), cfg=cfg, url=val)
            return {"skipped": True, "reason": why, "url": val, "prompt": prompt,
                    "reference_images": all_refs}

    # 出图前质检：判提示词，不合格就带着问题清单重装配再判，用尽次数则**停链**——
    # 这一档的价值就是「还没花出图的钱」，所以判不过绝不入队
    qc_out: dict[str, Any] | None = None
    qc = cfg.get("qc") or {}
    if qc.get("on") and (qc.get("stage") or "prompt") == "prompt":
        # anchor 必须传**上面选定的那份**（画布配置优先）。
        # 传 layers 那份会踩一个隐蔽的坑：本循环返回 compose(user, anchor) 并**覆盖 prompt**，
        # 于是画布配的约束段在质检这一步被默默换回装配器默认值——实测 run 69 就是这样，
        # 日志显示 anchor 来自画布配置，落库的提示词里却一个字都没有。
        prompt, qc_out = await _qc_prompt_loop(
            pool, qc, user=user, anchor=anchor,
            project_id=project_id, node_key=key, nr_id=nr)
        payload["prompt"] = prompt
        if not qc_out.get("passed"):
            # 结论包成 {"qc": …}，与 done 分支同一形状——画布那枚徽标一处解析就够
            await _finish_node(pool, nr, "failed",
                               {"qc": qc_out, "prompt": prompt,
                                "anchor": layers.get("anchor") or ""},
                               error=f"提示词质检未通过：{qc_out.get('issues')}")
            raise WorkflowError(
                f"节点 {key} 提示词质检未通过（{qc_out.get('rounds')} 轮后仍不合格），未出图")

    target_node = _resolve(cfg.get("node_id"), ctx) or node_id
    await _node_phase(pool, nr, {"video": "视频生成中", "audio": "音频生成中"}
                      .get(modality, "图片生成中"))
    q = await flow.enqueue_with_deps(pool, kind=step, project_id=project_id,
                                     node_id=target_node, payload=payload,
                                     priority=cfg.get("priority", 10))
    task_id = q.get("task_id")
    await pool.execute("UPDATE workflow_node_runs SET task_id=$2 WHERE id=$1", nr, task_id)
    status, err, result = await _await_task(pool, task_id)
    if status != "done":
        await _finish_node(pool, nr, "failed", {}, error=err)
        raise WorkflowError(f"生成节点 {key}（{step}）失败: {err}")
    # 产物直出：画布靠这个把图挂到卡上，不必再二次探。
    # **本次任务自己的产物优先**，探库只作兜底（画布上拖出来的自由节点没有 skip_if，
    # 产物不属于任何要素，探无可探，只能从任务结果拿）。顺序反过来会踩一个隐蔽的坑：
    # 探库返回的是「此刻库里最新的那条」，而本次产物要等下面 _record_artifact_provenance
    # 才落库——于是强制重跑时报出去的是**上一版**的 url。实测（run 376）：图确实重出了
    # （task 1069 产出 93d65353.png），节点产物与 artifacts 记的却还是旧的 c3475355.png，
    # 画布上看着像"点了没反应"。智能调用让强制重跑成为常态，这条必须是对的。
    _ok, _why, existing = await _already_done(pool, cfg, ctx)
    url = _produced_url(result, existing)

    # 出图后质检：判画面。这一档钱已经花了，不合格只能重出，所以重试次数直接等于重出次数
    if qc.get("on") and qc.get("stage") == "image" and url:
        await _node_phase(pool, nr, "画面质检中")
        qc_out = await _qc_image_loop(pool, qc, url=url, project_id=project_id, node_key=key)
        url = qc_out.get("url") or url

    out = {"task_id": task_id, "url": url, "prompt": prompt,
           "reference_images": all_refs, **({"notes": notes} if notes else {}),
           **({"prompt_analysis": analysis} if analysis else {}),
           **({"qc": qc_out, "anchor": layers.get("anchor") or ""} if qc_out else {})}
    await _finish_node(pool, nr, "done", out)
    await _record_artifact_provenance(pool, run_id=run_id, node_run_id=nr, node_key=key,
                                      iteration=iteration, project_id=project_id, node_id=node_id,
                                      inputs=_artifact_inputs(ctx), cfg=cfg, url=url)
    return out


async def _qc_prompt_loop(pool: asyncpg.Pool, qc: dict[str, Any], *, user: str, anchor: str,
                          project_id: int | None, node_key: str,
                          nr_id: int | None = None) -> tuple[str, dict[str, Any]]:
    """出图前的提示词质检 + 回退重写。判法来自技能，阈值/次数是本条产线的策略。

    **只判 user 段（叙事内容），不判 anchor 段**——这一条是踩出来的：
    anchor 里本来就有画风库的「cinematic, masterpiece, best quality」这类词表，
    以及项目画风原文（「飞龙有可信的生物结构与皮膜细节」），拿判叙事的尺子去量它，
    必然轮轮不合格；而 anchor 是系统锁死的，用户和模型都改不动，判了也没有出路。
    能改的才判，这与三层装配的分工一致。

    回退用质检返回的 `重构提示词` 全文替换 user 段（与 review_image_prompt 的重构同一路数），
    绝不把问题清单拼进提示词——那是说给质检看的话，出图模型会当画面内容画进去。"""
    from . import workflow_actions
    from .prompt_fields import compose

    skill = qc.get("skill")
    if not skill:
        return compose(user, anchor), {"passed": True, "skipped": "未绑质检技能"}
    threshold = int(qc.get("threshold") or 0)
    rounds = int(qc.get("retry") or 0)
    fn = workflow_actions.get("qc.review")
    feedback = ""
    last: dict[str, Any] = {}
    for i in range(rounds + 1):
        if nr_id:
            await _node_phase(pool, nr_id,
                              "质检中" if i == 0 else f"质检中 · 第 {i + 1} 轮")
        # anchor 作为「已生效的硬约束」告知判据：判的仍只有可改的 user 段，
        # 但判据得知道版式/禁令已经随提示词下发了，否则会判「未体现无活物要求」
        # ——那条要求就写在 anchor 里，user 段根本不该重复（实测 run 71 死在这）
        rv = await fn(pool, skill=skill, text=user, project_id=project_id,
                      prev_feedback=feedback, locked=anchor)  # type: ignore[misc]
        score = int(rv.get("得分") or 0)
        ok = bool(rv.get("合格")) and score >= threshold
        # user 一并带出：手动「重新生成」要拿**被判的那段**当输入。
        # 拿合成后的整段去重写，等于把 anchor（画风词表/质量词）也送进判据——
        # 那是本函数开头写明踩过的坑，必然轮轮不合格。
        last = {"passed": ok, "score": score, "issues": rv.get("问题") or [],
                "rounds": i + 1, "user": user,
                **({"degraded": rv["降级"]} if rv.get("降级") else {})}
        log.info("gen 节点 %s 提示词质检第 %d 轮：%s 分 / 合格线 %s → %s",
                 node_key, i + 1, score, threshold, "通过" if ok else "不通过")
        if ok or i == rounds:
            return compose(user, anchor), last
        feedback = "；".join(str(x) for x in (rv.get("问题") or []))[:800]
        rebuilt = rv.get("重构提示词") or ""
        if not rebuilt:
            # 质检说不合格却给不出重写版 → 再跑一轮也只是原地打转，如实停在这
            last["issues"] = [*last["issues"], "质检未给出重构提示词，不再重试"]
            return compose(user, anchor), last
        user = rebuilt
    return compose(user, anchor), last


async def _qc_image_loop(pool: asyncpg.Pool, qc: dict[str, Any], *, url: str,
                         project_id: int | None, node_key: str) -> dict[str, Any]:
    """出图后的画面质检。**只判不重出**——重出要重新入队一整轮，那是画布上「强制重跑」
    该干的事；这里如实给结论与问题，把是否重来交回给人（钱已经花掉了，别自动再花一遍）。"""
    from . import workflow_actions

    skill = qc.get("skill")
    if not skill:
        return {"passed": True, "skipped": "未绑质检技能", "url": url}
    fn = workflow_actions.get("qc.review")
    rv = await fn(pool, skill=skill, image_url=url, project_id=project_id)  # type: ignore[misc]
    score = int(rv.get("得分") or 0)
    ok = bool(rv.get("合格")) and score >= int(qc.get("threshold") or 0)
    log.info("gen 节点 %s 画面质检：%s 分 → %s", node_key, score, "通过" if ok else "不通过")
    return {"passed": ok, "score": score, "issues": rv.get("问题") or [], "url": url,
            **({"degraded": rv["降级"]} if rv.get("降级") else {})}


async def _write_prompt_by_charter(pool: asyncpg.Pool, cfg: dict[str, Any], *,
                                   material: str, project_id: int | None,
                                   node_key: str, subject_name: str = "",
                                   flow_ctx: dict[str, Any] | None = None) -> tuple[str, str]:
    """画布上配的**系统提示词 + 技能 + 知识库 + 工具** → 跑一次文本模型，写出**出图提示词**。

    这是画布配置真正起作用的地方，也是 tapflow 的核心语义（2026-08-01 用户定稿）：

        系统提示词 + 技能 + 知识库 + 取数
                 ↓ 文本模型
              出图提示词        ← 生成条里显示的就是这一段
                 ↓ 出图模型
                图片

    系统提示词是给**写提示词的那个模型**的 system，不是拼给出图模型的约束段——
    拼错位置的后果实测过（run 70）：技能正文被出图模型当画面内容，图上直接印出
    技能 slug、还满屏画人。技能是方法论文档，只有文本模型读得懂。

    material = 装配器取到的料（要素设定 / 上游文本节点产物 / 生成条里的指令）。

    2026-09-18 改版（提案 A 落地，docs/arch/tapflow-simplify-and-element-canvas.md）：
    ① **charter 分支扶正为唯一主路**——没配 charter 的 gen 节点用内置默认提示词规划员，
       不再回落到装配器拼串（拼串正是「系统层整段回显进输入框」的根源）；
    ② **出图/出视频前先对提示词做合理性分析**：需求是否明确、材料是否充分、
       与产物类型是否匹配——分析要点随输出返回，调用方落进 run 日志可见；
    ③ 写不出来就报错（返回空串的时代结束了）——拼串兜底退役，错误原因如实上扌。

    返回 (final_prompt, analysis)：analysis 是【分析】段的纯文本（可能为空），
    final_prompt 是【提示词】段——解析不出标记时整段当提示词，向后安全。"""
    charter = str(cfg.get("charter") or "").strip()
    if not charter:
        # 内置默认规划员（2026-09-18）：没配系统提示词的 gen 节点也走 AI 主路。
        # 只做两件事：把材料包（需求句 + 画布上文 + 要素叙事）组织成一条干净的
        # 出图/出视频提示词；生成前先检查需求与材料的合理性（主体、风格、时长、
        # 比例、材料缺口），让问题在出图**前**暴露而不是烧完一次生成才暴露。
        charter = (
            "你是出图/出视频的提示词规划员。你会收到一份材料包：【本次需求】是用户的一句话需求，"
            "【画布上文】是连线带来的上游产物与项目信息，其余是要素档案叙事等系统层材料。\n"
            "任务分两步：\n"
            "1. 先分析本次生成的合理性：需求是否明确可执行、材料是否支撑这个需求"
            "（主体是否有据可依、参考图是否够用、与产物类型是否匹配、有无互相矛盾的要求），"
            "把要点写成 1~3 条短句，每条一行，以【分析】开头；"
            "2. 再写出最终提示词：融合材料里的设定与画风，需求不明确处按材料中最合" 
            "理的理解补全，不要编造材料里不存在的设定，以【提示词】开头。\n"
            "只输出这两段，不要输出其它内容。出视频时提示词要含运镜与节奏描述，"
            "出图时提示词要含构图与光线描述。"
        )
    else:
        charter = f"{charter}\n\n输出格式：先以【分析】开头写 1~3 条生成前检查要点（每条一行），再以【提示词】开头写最终出图/出视频提示词。只输出这两段。"
    from . import agent_runtime

    skills = [str(x) for x in (cfg.get("skills") or []) if x]
    folder_ids = [int(x) for x in (cfg.get("folder_ids") or []) if str(x).isdigit()]
    tools = [str(x) for x in (cfg.get("tools") or []) if x]
    # autoContext（2026-09-17）：上下文查询方式交给 AI 自主规划——不再要求人把
    # project_info 等取数工具逐个勾上。开启后默认挂全部只读工具 + 画布 ctx 探索
    # （ctx.outline/search/get/trace），模型按提示词自己决定查项目信息、翻上游
    # 产物还是检索知识库。新画布因此只需一句提示词即可跑通，不必预配工具清单。
    if cfg.get("autoContext"):
        from . import tapflow_ai
        auto_tools = tapflow_ai.readonly_tool_names()
        tools = sorted(set(tools) | set(auto_tools))
        flow_ctx = flow_ctx or {}
    try:
        out = await agent_runtime.run(
            pool, charter=charter, task=material, skills=skills,
            folder_ids=folder_ids, tool_names=tools, project_id=project_id,
            flow_ctx=flow_ctx, caller="tapflow_gen")
    except Exception as e:  # noqa: BLE001 — 拼串兜底已退役（提案 A）：失败如实上扌
        raise WorkflowError(f"提示词规划失败（模型调用异常）：{e}") from e
    text = str(out.get("output") or "").strip()
    if not text:
        raise WorkflowError("提示词规划失败：模型返回为空")
    # 解析【分析】/【提示词】两段；没有标记时整段当提示词（向后安全，
    # 存量 charter 的输出本就是纯提示词）
    analysis = ""
    if "【提示词】" in text:
        head, _, tail = text.partition("【提示词】")
        prompt = tail.strip() or head.strip()
        analysis = head.replace("【分析】", "").strip()
    else:
        prompt = text
    # 主体名兜底：**画的是哪个地方/对象，名字必须在提示词里**。
    # 料里已经让它领头了（element_sheet 场景分支），这里再兜一道——模型改写时
    # 把名字丢了，出来的就是"另一个地方"（实测：废弃仓库画成了江南小镇河道）。
    if prompt and subject_name and subject_name not in prompt:
        prompt = f"{subject_name}：{prompt}"
        log.info("gen 节点 %s 提示词未见主体名「%s」，已补在开头", node_key, subject_name)
    # 画风兜底：**只补一个画风名称关键词**，且先看文里有没有。
    # 刻意不在 charter/输入里加"必须体现画风"这类约束，也不追加整段锚词——
    # 模型换个措辞（「水墨国漫风」vs「国漫水墨」）子串就匹配不上，届时尾巴上挂一大段
    # 反而成赘述。补一个词即使偶尔与文中重复也无害，漏了就漏了，不值得为它加复杂度。
    if prompt and project_id:
        from ..knowledge import style_anchor_named
        art = await pool.fetchval("SELECT art_style FROM content_projects WHERE id=$1", project_id)
        if (art or "").strip():
            _, style_name = await style_anchor_named(pool, art)
            if style_name and style_name not in prompt:
                prompt = f"{prompt}，{style_name}"
                log.info("gen 节点 %s 未见画风名「%s」，已补", node_key, style_name)
    log.info("gen 节点 %s 提示词由模型写出（%d 字，分析 %d 条，技能 %d / 知识库 %d / 工具 %d）",
             node_key, len(prompt), len([x for x in analysis.splitlines() if x.strip()]),
             len(skills), len(folder_ids), len(tools))
    return prompt, analysis


async def _assemble_layers(pool: asyncpg.Pool, cfg: dict[str, Any],
                           ctx: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """跑 config.assemble 指名的装配器（如 element.layers）拿分层提示词与实体参考图。
    不配装配器 = 自由素材节点：只有上游与用户指令，没有实体叙事段与版式锚。"""
    from . import workflow_actions

    spec = cfg.get("assemble") or {}
    name = spec.get("name")
    if not name:
        return {}, []
    fn = workflow_actions.get(name)
    if not fn:
        raise WorkflowError(f"未注册的装配器 {name!r}")
    layers = await fn(pool, **_resolve_all(spec.get("args") or {}, ctx))
    refs = [r for r in (layers.get("refs") or []) if isinstance(r, dict) and r.get("url")]
    return layers, refs


async def _reused_gen_outputs(pool: asyncpg.Pool, cfg: dict[str, Any],
                              ctx: dict[str, Any], key: str = "") -> dict[str, Any]:
    """复用产物（skip 命中）时回填生成条要显示的**用户需求层**。

    常规复用快路径刻意在提示词装配**之前**结束——不会为一张不会重出的图花一次
    LLM 调用；但子工作流的瞬态循环卡仍需要 prompt/参考图 payload。只读装配器
    能零模型调用地重建参考图；提示词回显只取用户需求（override/instruction）：
    上文、实体叙事是系统隐式挂载，实跑时才进模型，不进用户的输入框（2026-09-17）。
    """
    if cfg.get("charter"):
        return {}
    spec = cfg.get("assemble")
    if not isinstance(spec, dict) or not spec.get("name"):
        return {}
    try:
        layers, refs = await _assemble_layers(pool, cfg, ctx)
        _, up_refs = _upstream_media(ctx)
        # 回显只放**用户需求层**：上次生成条里写的需求（override 优先，其次画布配的
        # 默认指令）。实跑的完整提示词（含上文等系统层）不进输入框——用户看到的
        # 就是自己的需求，改起来也是在改需求，而不是在改一段看不懂的拼装文本。
        _ovr = ctx.get("__overrides__") or {}
        override = _ovr.get(key) or {}
        instruction = _instruction(cfg, ctx)
        shown = str(override.get("prompt") or override.get("instruction")
                    or instruction or "")
        return {
            "prompt": shown,
            "reference_images": _dedupe_refs([*refs, *up_refs]),
        }
    except Exception as e:  # noqa: BLE001 - display recovery must not block reuse
        log.warning("复用生成产物时回填提示词失败：%s", e)
        return {}


def _apply_refs(payload: dict[str, Any], refs: list[dict[str, Any]], modality: str,
                cfg: dict[str, Any]) -> list[str]:
    """按模态把参考图放进 payload，并**如实记录被丢弃的**（静默截断会让人以为都参与了）。"""
    notes: list[str] = []
    if modality == "video":
        # ARK Seedance 是 I2V：只吃首帧（+可选尾帧）。画布上连四张图进视频节点是表意的，
        # 真跑时中间那些进不了模型——必须说出来，不能默默吞掉。
        if refs:
            payload["first_frame_url"] = refs[0]["url"]
        if len(refs) > 1:
            payload["last_frame_url"] = refs[-1]["url"]
        if len(refs) > 2:
            dropped = [r.get("name") or r["url"] for r in refs[1:-1]]
            notes.append(f"视频只取首/尾帧，中间 {len(dropped)} 张未进模型：{'、'.join(map(str, dropped))}")
        return notes
    if modality == "audio":
        if refs:
            payload["reference_audio"] = refs[0]["url"]
        return notes
    cap = int(cfg.get("max_refs") or 4)
    # A canvas may also receive user-uploaded reference images through its start
    # inputs. Preserve those, then add resolved upstream assets without duplicates.
    seeded = payload.get("reference_images") or []
    if isinstance(seeded, str):
        seeded = [seeded]          # 单个 url 也合法：包成列表，防止被当可迭代逐字符展开
    seeded_refs = [{"url": value, "name": "输入参考图"} if isinstance(value, str) else value
                   for value in seeded if isinstance(value, (str, dict))]
    refs = _dedupe_refs([*seeded_refs, *refs])
    payload["reference_images"] = refs[:cap]
    if len(refs) > cap:
        dropped = [r.get("name") or r["url"] for r in refs[cap:]]
        notes.append(f"参考图上限 {cap} 张，未传：{'、'.join(map(str, dropped))}")
    return notes


async def _run_llm_node(pool: asyncpg.Pool, node: dict[str, Any], *, ctx: dict[str, Any],
                        run_id: int, project_id: int | None, node_id: int | None,
                        iteration: int = 0,
                        force: frozenset[str] | set[str] = frozenset()) -> Any:
    """LLM 文本节点：落到 agent_runtime.run_batch（技能/知识库/工具那一整套现成的），
    不在工作流里另起一个模型调用路径。上游文本按连线序拼进 task 的上下文段。

    「缺才跑」在这里尤其重要——每跑一次就是一次真实模型调用。skip_if 探到已有产物
    （如要素已经有简介）就直接把已有的那份当输出返回，下游照样拿得到文本。"""
    from . import agent_runtime

    cfg = node.get("config") or {}
    key = node["id"]
    # task/charter 是**句子**，占位符嵌在中间——必须用 _fill 而不是 _resolve
    task = _fill(str(cfg.get("task") or ""), ctx)
    charter = _fill(str(cfg.get("charter") or ""), ctx)
    # 通配键兜底：本节点在**子工作流里**跑时，外层给的是引用节点的 id，
    # 内层节点名对不上——subflow 把外层那份挂到 FORCE_ALL 键上供内层取用
    _ovr = ctx.get("__overrides__") or {}
    override = _ovr.get(key) or _ovr.get(FORCE_ALL) or {}
    # 与媒体生成节点一致：生成条手选了参考节点后，只把这些直属上游交给模型。
    # 选的是节点 id 而非当前文本，节点重跑后仍会自动取到最新产物。
    picked = override.get("ref_nodes")
    if isinstance(picked, list):
        # 同媒体分支：手选顺序即参考顺序
        up_ctx = {**ctx, "__in__": [x for x in picked if x in set(ctx.get("__in__") or [])]}
    else:
        up_ctx = ctx
    # LLM 文本节点不吃任何图：submitted=[] 让图片行如实标「未传入模型」，
    # 不许谎称「已作为参考图传入」（标注如实，2026-09-18 定稿）
    ctx_block = await _canvas_context(pool, up_ctx, project_id=project_id,
                                      only=isinstance(picked, list), submitted=[])
    if override.get("instruction"):
        task = f"{task}\n\n【本次附加要求】\n{override['instruction']}"
    if ctx_block:
        task = ctx_block + "\n\n" + task
    nr = await _node_run_row(pool, run_id, key, iteration,
                             {"task_len": len(task), "task": task[:2000]}, ctx=ctx)

    # 手编覆盖：画布上把这段正文改过了 → **模型不跑**，改的那份直接当产出，
    # 并照常走 write 落库。不这么做的话，改了画布上的介绍，下游装配器读的还是库里旧的，
    # 出来的图不对还看不出为什么（装配器只认库，不认画布）。
    if str(override.get("text") or "").strip():
        res = {"text": str(override["text"]), "edited": True}
        log.info("llm 节点 %s 用手编正文覆盖（%d 字），不调模型", key, len(res["text"]))
        await _llm_write_back(pool, cfg, ctx, key, res)
        await _finish_node(pool, nr, "done", {"text": res["text"], "edited": True,
                                              **({"write": res["write"]} if "write" in res else {})})
        return res

    if not cfg.get("force") and not _forced(key, force):
        done, why, val = await _already_done(pool, cfg, ctx)
        if done:
            out = {"text": val if isinstance(val, str) else "", "skipped": True}
            await _finish_node(pool, nr, "skipped", out, skip_reason=why)
            return out
    try:
        out = await agent_runtime.run_batch(
            pool, charter=charter, task=task,
            skills=cfg.get("skills") or [], folder_ids=cfg.get("folder_ids") or [],
            tool_names=cfg.get("tools") or [],
            project_id=project_id, node_id=_resolve(cfg.get("node_id"), ctx) or node_id,
            element_id=_resolve(cfg.get("element_id"), ctx),
            caller="tapflow_canvas")
    except Exception as e:
        await _finish_node(pool, nr, "failed", {}, error=str(e))
        raise WorkflowError(f"LLM 节点 {key} 失败: {e}") from e
    results = out.get("results") or []
    text = str((results[0] or {}).get("output") or "") if results else ""
    res = {"text": text, "ran": out.get("ran"),
           "steps": (results[0] or {}).get("steps") if results else None}
    await _llm_write_back(pool, cfg, ctx, key, res)
    await _finish_node(pool, nr, "done", {"text": text, "ran": out.get("ran"),
                                          **({"write": res["write"]} if "write" in res else {})})
    return res


async def _llm_write_back(pool: asyncpg.Pool, cfg: dict[str, Any], ctx: dict[str, Any],
                          key: str, res: dict[str, Any]) -> None:
    """LLM 节点的产物落库：走 config.write 指名的**具名动作**，不是自由 SQL。

    写库入口一律具名，「这张编排会改哪张表」在图上就读得出来（与 agent_next 那份
    writes 白名单同一个用意）。模型跑出来的和手编覆盖的都走这里，落库路径只有一条。"""
    from . import workflow_actions

    w = cfg.get("write") or {}
    if not w.get("name") or not res.get("text"):
        return
    fn = workflow_actions.get(w["name"])
    if not fn:
        raise WorkflowError(f"未注册的回写动作 {w['name']!r}")
    res["write"] = await fn(pool, **_resolve_all(w.get("args") or {}, {**ctx, key: res}))


async def _run_task_node(pool: asyncpg.Pool, node: dict[str, Any], *, ctx: dict[str, Any],
                         run_id: int, project_id: int | None, node_id: int | None,
                         iteration: int = 0,
                         force: frozenset[str] | set[str] = frozenset()) -> Any:
    """task 节点 = 包一层已注册的 Step。派任务后 await 它跑完（见模块头的 v1 取舍）。"""
    from . import flow

    cfg = node.get("config") or {}
    kind = cfg.get("kind")
    if not kind:
        raise WorkflowError(f"task 节点 {node['id']} 缺 config.kind")
    payload = _resolve_all(cfg.get("payload") or {}, ctx)
    target_node = _resolve(cfg.get("node_id"), ctx) or node_id
    nr = await _node_run_row(pool, run_id, node["id"], iteration,
                             {"kind": kind, "payload": payload}, ctx=ctx)

    # 「缺才跑」：产物已在就跳过。默认语义必须如此——否则每次批量都会把已有产物
    # 重新生成一遍覆盖掉（2026-07-28 批量首帧正是踩了这个坑）。想强制重跑：
    # 图里写死走 config.force，单次运行走 run 入参 force=[节点id]。
    if not cfg.get("force") and not _forced(node["id"], force):
        done, why, val = await _already_done(pool, cfg, ctx)
        if done:
            # 跳过时也把探到的产物带出去——画布靠它把已有的图挂回卡上
            await _finish_node(pool, nr, "skipped", {"url": val}, skip_reason=why)
            return {"skipped": True, "reason": why, "url": val}

    q = await flow.enqueue_with_deps(
        pool, kind=kind, project_id=project_id, node_id=target_node,
        payload=payload, priority=cfg.get("priority", 10))
    task_id = q.get("task_id")
    await pool.execute("UPDATE workflow_node_runs SET task_id=$2 WHERE id=$1", nr, task_id)
    status, err, result = await _await_task(pool, task_id)
    if status != "done":
        await _finish_node(pool, nr, "failed", {}, error=err)
        raise WorkflowError(f"节点 {node['id']}（{kind}）失败: {err}")
    # 产物直出：省得画布/下游为了拿 url 再绕一个只读 action。
    # 与 gen 节点同序：本次任务的产物优先，探库兜底（理由见 _run_gen_node 那处注释）。
    _ok, _why, existing = await _already_done(pool, cfg, ctx)
    url = _produced_url(result, existing)
    out = {"task_id": task_id, **({"url": url} if url else {})}
    await _finish_node(pool, nr, "done", out)
    return out


async def _already_done(pool: asyncpg.Pool, cfg: dict[str, Any],
                        ctx: dict[str, Any]) -> tuple[bool, str, Any]:
    """产物存在性检查。config.skip_if = {sql, args} —— 返回非空即视为已生成。
    第三项是探到的值本身（如 sheet_url），preview 模式靠它回显已有产物。"""
    # Generic target + slot existence is authoritative. It works for elements,
    # content nodes and future asset types without per-workflow SQL.
    from ..assets import read_latest
    from .resource_refs import output_slot, target_from_inputs
    # A loop body belongs to the descriptor's business target, not to the outer
    # workflow target (for example the shot that requested several element images).
    inputs = _artifact_inputs(ctx)
    target = target_from_inputs(inputs, None)
    slot = output_slot(cfg, inputs)
    if target and slot and inputs.get("project_id"):
        row = await pool.fetchrow(
            "SELECT url FROM workflow_artifacts WHERE project_id=$1 AND target_kind=$2 "
            "AND target_id=$3 AND role=$4 AND variant IS NOT DISTINCT FROM $5 "
            "ORDER BY id DESC LIMIT 1", int(inputs["project_id"]), target[0], target[1], slot[0], slot[1])
        if row and row["url"]:
            return True, "该目标的产物槽位已有内容，跳过", row["url"]
    # The workflow-level asset_type describes the canvas' final product, not every
    # intermediate node. Reusing it for an LLM/action/subflow makes an existing
    # keyframe satisfy unrelated nodes and can even feed the image URL downstream
    # as if it were prompt text. Only nodes that declare an asset contract (directly
    # or through an output slot) may fall back to the workflow input asset type.
    asset_type = str(cfg.get("asset_type") or (inputs.get("asset_type") if slot else "") or "")
    if asset_type and inputs.get("project_id") and inputs.get("target_ref"):
        existing = await read_latest(
            pool, project_id=int(inputs["project_id"]), asset_type=asset_type,
            target_ref=str(inputs["target_ref"]))
        if existing and existing.get("url"):
            return True, "该关联对象已有兼容资产，跳过", existing["url"]
    skip = cfg.get("skip_if")
    if not skip or not skip.get("sql"):
        return False, "", None
    args = [_resolve(a, ctx) for a in (skip.get("args") or [])]
    if args and all(a is None for a in args):
        return False, "", None   # 依赖的上游值还没有（如要素尚未创建）——视为「缺」
    # 部分参数为 None 时照传：模板 SQL 里本就写了 COALESCE($N, 默认值)（如
    # variant_id 缺省=default）。之前「任一 None 直接枪毙探测」把这类 SQL
    # 一起挡死了——产物明明在库里（core-element 的 sheet_url），复用探测却
    # 永远返回「缺」，画布/执行链每次都重新生成一遍。
    got = await pool.fetchval(skip["sql"], *args)
    return (bool(got), skip.get("reason") or "产物已存在，跳过", got) if got else (False, "", None)


async def _await_task(pool: asyncpg.Pool, task_id: int | None) -> tuple[str, str, dict[str, Any]]:
    """轮询等一个 task_queue 行到终态。worker 重启导致的自动重排对这里透明——
    任务会回到 pending 继续跑，状态不会停在中间态。

    第三项是**任务自己的产物**（task_queue.result）：没配 skip_if 的自由节点
    （画布上拖出来的那些）探不出 url，只能从这里拿。"""
    if not task_id:
        return "failed", "入队未返回 task_id", {}
    for _ in range(_TASK_TIMEOUT_S // _POLL_S):
        row = await pool.fetchrow(
            "SELECT status, coalesce(error,'') AS error, result FROM task_queue WHERE id=$1",
            task_id)
        if not row:
            return "failed", f"任务 {task_id} 不存在", {}
        if row["status"] in ("done", "failed", "canceled"):
            return row["status"], row["error"], _j(row["result"])
        await asyncio.sleep(_POLL_S)
    return "failed", f"等待任务 {task_id} 超时", {}


def _produced_url(result: dict[str, Any], existing: Any) -> Any:
    """跑完一个节点后，对外报哪个 url。**本次任务的产物优先**，探库只作兜底。

    唯一实现（gen / task 节点共用）。顺序不能反：探库返回的是「此刻库里最新的那条」，
    而本次产物要等 _record_artifact_provenance 才落库——先探库，强制重跑时报出去的
    就是**上一版**（实测 run 376：图确实重出了，节点产物与 artifacts 记的却是旧图，
    画布上看着像"点了没反应"）。探库兜底仍要留着：画布上拖出来的自由节点没有 skip_if
    也没有资产槽位，只能从任务结果拿；反过来，有些 Step 不在 result 里回 url。
    """
    return _result_url(result) or existing


def _result_url(result: dict[str, Any]) -> str | None:
    """任务产物里的地址（url / sheet_url / image_url / video_url，按 _URL_KEYS 序）。"""
    return next((result[k] for k in _URL_KEYS
                 if isinstance(result.get(k), str) and result[k]), None)


async def _run_subflow_node(pool: asyncpg.Pool, node: dict[str, Any], *, ctx: dict[str, Any],
                            run_id: int, project_id: int | None, node_id: int | None,
                            depth: int, iteration: int = 0,
                            force: frozenset[str] | set[str] = frozenset()) -> Any:
    """subflow 节点 = 调另一个工作流（扣子的子工作流）。当前置条件用时同样是「缺才跑」。"""
    cfg = node.get("config") or {}
    slug = cfg.get("slug")
    if not slug:
        raise WorkflowError(f"subflow 节点 {node['id']} 缺 config.slug")
    inputs = _resolve_all(cfg.get("inputs") or {}, ctx)
    nr = await _node_run_row(pool, run_id, node["id"], iteration, inputs, ctx=ctx)

    if not cfg.get("force") and not _forced(node["id"], force):
        done, why, val = await _already_done(pool, cfg, ctx)
        if done:
            # 跳过也要把**探到的产物**带出去：画布靠它把已有内容显示回卡上，
            # 否则卡上一个对勾、内容却是占位符，看着像这轮真跑过（task/gen 节点同理）
            out = {"skipped": True, "reason": why, "value": val}
            await _finish_node(pool, nr, "skipped", out, skip_reason=why)
            return out

    target_node = _resolve(cfg.get("node_id"), ctx) or node_id
    # 本节点被点名重跑 → 子图**整体**重跑。只按 id 下传是对不上号的：内外层节点
    # 天然不同名（外层 `brief` / 内层 `write`），于是「点这个节点让它重跑」在引用型
    # 节点上完全失效——实测点了没反应，内层照样按「缺才跑」跳过。
    # 生成条里给这个节点的指令同样挂到通配键上，子图里的 llm 节点才取得到。
    sub_force = frozenset({FORCE_ALL}) if _forced(node["id"], force) else force
    sub_overrides = dict(ctx.get("__overrides__") or {})
    # 通配键兜底与 gen/llm 节点一致：本节点自己在**更外层**的子图里跑时，外层给的是
    # 引用节点的 id，内层名字对不上，那份指令只挂在通配键上。取不到就等于用户那句话
    # 传到第二层就断了——智能调用是逐层规划的，指令必须跟着往下走。
    mine = sub_overrides.get(node["id"]) or sub_overrides.get(FORCE_ALL)
    if mine:
        sub_overrides[FORCE_ALL] = mine
    # 先精确创建本轮子 run，再交给解释器执行。不能执行后按“parent 下最新一条”反查：
    # loop 并发时另一轮可能更晚插入，subrun_id 会串到别的要素上。
    child = await load_workflow(pool, slug, cfg.get("version"))
    # ── 智能调用：被点名重跑 + 子流程声明了 smart_call → 不再「整图重跑」这一档粗，
    # 而是让模型按用户这句话逐节点判「复用 / 重生成」。规划不出来就退回整图重跑。
    plan: dict[str, Any] | None = None
    if _forced(node["id"], force) and child.get("smart_call"):
        # instruction 与 prompt 两个键都收：画布把引用节点画成 gen 卡时（如九宫格里那张
        # 「Multi-element smart generation」），生成条按媒体节点的口径发的是 prompt。
        # 引用节点自己不出图、没有"最终提示词"这回事，那段文字对它就是一句调用指令。
        said = (mine or {}).get("instruction") or (mine or {}).get("prompt") or ""
        plan = await _plan_smart_call(pool, child=child, node_key=node["id"],
                                      instruction=str(said),
                                      inputs=inputs, project_id=project_id, ctx=ctx)
        if plan and not plan.get("degraded"):
            sub_force = frozenset(plan["force"])
            for nid, patch in (plan.get("overrides") or {}).items():
                sub_overrides[nid] = {**(sub_overrides.get(nid) or {}), **patch}
    sub = await pool.fetchval(
        "INSERT INTO workflow_runs(workflow_id,project_id,node_id,parent_run_id,depth,inputs) "
        "VALUES ($1,$2,$3,$4,$5,$6::jsonb) RETURNING id",
        child["id"], project_id, target_node, run_id, depth + 1,
        json.dumps(inputs, ensure_ascii=False))
    # Bind the exact child run as soon as it exists. The canvas polls this row while
    # the child is still running; writing subrun_id only after run_workflow returns
    # makes live child-node projection impossible and is ambiguous under concurrency.
    await pool.execute("UPDATE workflow_node_runs SET subrun_id=$2 WHERE id=$1", nr, sub)
    out = await run_workflow(
        pool, slug=slug, version=cfg.get("version"), project_id=project_id,
        node_id=target_node, inputs=inputs, run_id=sub, parent_run_id=run_id, depth=depth + 1,
        force=sub_force, overrides=sub_overrides)
    # 规划结论随产物一起回给画布：这次重跑了子图里的哪几步、为什么，必须看得见——
    # 「点了生成，到底生成了什么」正是这个功能要解决的问题，藏在日志里等于没解决。
    if plan:
        out = {**out, "smart_plan": {k: plan.get(k) for k in
                                     ("force", "reason", "degraded") if plan.get(k) is not None}}
    await _finish_node(pool, nr, "done", out)
    return out


async def _plan_smart_call(pool: asyncpg.Pool, *, child: dict[str, Any], node_key: str,
                           instruction: str, inputs: dict[str, Any],
                           project_id: int | None, ctx: dict[str, Any]) -> dict[str, Any] | None:
    """把「一句提示词 → 子图逐节点重跑计划」外包给 workflow_planner。

    规划本身可能失败（模型不通、返回不可解析），那不该把这次运行判死：如实降级回
    「整图重跑」的老语义并把原因带回去。轨迹当历史对话一起送过去——用户上一步刚生成了
    什么，直接决定这一步该不该重来。"""
    from . import workflow_planner

    try:
        return await workflow_planner.plan(
            pool, slug=child["slug"], version=child["version"], prompt=instruction,
            inputs=inputs, project_id=project_id, history=ctx.get("__trace__") or [])
    except Exception as e:  # noqa: BLE001
        log.warning("subflow 节点 %s 智能调用规划失败，退回整图重跑：%s", node_key, e)
        return {"degraded": f"规划失败：{e}"}


async def _run_loop_node(pool: asyncpg.Pool, node: dict[str, Any], *, ctx: dict[str, Any],
                         run_id: int, wf: dict[str, Any], project_id: int | None,
                         node_id: int | None, depth: int,
                         force: frozenset[str] | set[str] = frozenset()) -> Any:
    """loop 节点：运行时把 body 展开成 N 份（ComfyUI 的节点展开思路）。

    body 是一个子图节点列表（引用同一张 graph 里的节点 id），每轮迭代把当前元素
    绑到 ctx['__item__'] 后重跑一遍 body。循环体里可以放 subflow —— 这正是
    「批量生成所有分镜，每镜调一次单镜出图工作流」的形状。"""
    cfg = node.get("config") or {}
    items = _resolve(cfg.get("source"), ctx)
    if items is None:
        items = cfg.get("items") or []
    if not isinstance(items, list):
        raise WorkflowError(f"loop 节点 {node['id']} 的 source 不是列表: {type(items).__name__}")
    body_ids = cfg.get("body") or []
    by_id = {n["id"]: n for n in (wf["graph"].get("nodes") or [])}
    results: list[Any] = [None] * len(items)
    concurrency = max(1, min(int(cfg.get("concurrency") or 1), 8))
    semaphore = asyncio.Semaphore(concurrency)

    async def run_one(i: int, item: Any) -> None:
        async with semaphore:
            inner = dict(ctx)
            inner["__item__"] = item
            nr = await _node_run_row(pool, run_id, node["id"], i, {"item": item}, ctx=ctx)
            try:
                for bid in body_ids:
                    bnode = by_id.get(bid)
                    if not bnode:
                        raise WorkflowError(f"loop body 引用了不存在的节点 {bid}")
                    inner[bid] = await _run_node(
                        pool, bnode, ctx=inner, run_id=run_id, wf=wf,
                        project_id=project_id, node_id=node_id, depth=depth, iteration=i,
                        force=force)
                out = {bid: inner.get(bid) for bid in body_ids}
                await _finish_node(pool, nr, "done", out)
                results[i] = out
            except Exception as e:
                # 单轮失败不炸整个循环（批量出图里一镜挂掉不该拖垮其余）——记下继续
                await _finish_node(pool, nr, "failed", {}, error=str(e))
                log.warning("loop %s 第 %s 轮失败: %s", node["id"], i, e)
                results[i] = {"error": str(e)[:300]}

    await asyncio.gather(*(run_one(i, item) for i, item in enumerate(items)))
    return {"count": len(items), "results": results,
            "failed": sum(1 for x in results if isinstance(x, dict) and "error" in x)}


# ═══════════ 运行预检（画布打开时的「自动带出已有内容」）═══════════

async def preview_workflow(pool: asyncpg.Pool, *, slug: str, version: int | None,
                           inputs: dict[str, Any]) -> dict[str, Any]:
    """按拓扑序做一次**零副作用**预演，返回逐节点结果——画布运行态打开时靠它
    回显已有产物、预填提示词（对标现有 InfiniteMediaCanvas「点进去全带出」）。

    规则：value/start 正常求值进 ctx；action 只执行只读的（writes=False），写库
    action 若配了 config.preview={name,args} 就换执行那个只读替身（如 element.upsert
    → element.find），否则跳过；task/subflow 只探 skip_if（返回 exists + 探到的值，
    如 sheet_url）。不建 run 行、不入队、不写任何库。"""
    from . import workflow_actions
    from .resource_refs import ResourceRefError, normalize_inputs

    wf = await load_workflow(pool, slug, version)
    try:
        inputs = await normalize_inputs(pool, inputs, inputs.get("project_id"))
    except ResourceRefError as e:
        raise WorkflowError(str(e)) from e
    inputs = _apply_asset_type_contract(wf, inputs)
    inputs = await _resolve_asset_target(pool, inputs)
    ctx: dict[str, Any] = {"__inputs__": dict(inputs), "__overrides__": {}}
    report: dict[str, Any] = {}
    body_ids = {b for n in (wf["graph"].get("nodes") or [])
                if n.get("type") == "loop"
                for b in ((n.get("config") or {}).get("body") or [])}
    for node in topo_order(wf["graph"]):
        key = node["id"]
        if key in body_ids:
            continue
        ntype = node.get("type")
        cfg = node.get("config") or {}
        ctx["__in__"] = _inbound(wf, key)
        ctx["__graph__"] = _graph_index(wf)   # 上文回溯的目录
        try:
            if not _condition_edge_is_active(wf, key, ctx):
                ctx[key] = {"skipped": True, "reason": "condition branch does not match"}
                report[key] = {"skipped": True, "reason": "condition branch does not match"}
                continue
            if ntype == "start":
                ctx[key] = dict(inputs)
                report[key] = {"outputs": ctx[key]}
            elif ntype == "value":
                ctx[key] = _resolve_all(cfg.get("value") or {}, ctx)
                report[key] = {"outputs": ctx[key]}
            elif ntype == "condition":
                ctx[key] = {"matched_branch": _condition_branch(cfg, ctx)}
                report[key] = {"outputs": ctx[key]}
            elif ntype == "loop":
                # Preview must expose the same collection that the runtime loop
                # will expand.  Body nodes are intentionally not executed here,
                # but the resolved items are needed by the canvas to render all
                # transient iterations before the user starts a run.
                items = _resolve(cfg.get("source"), ctx)
                if items is None:
                    items = cfg.get("items") or []
                if not isinstance(items, list):
                    raise WorkflowError(
                        f"loop 节点 {key} 的 source 不是列表: {type(items).__name__}")
                ctx[key] = {"count": len(items), "items": items, "results": items}
                report[key] = {
                    "outputs": {"count": len(items), "items": items, "results": items},
                    "preview_items": items,
                }
            elif ntype == "action":
                name = cfg.get("name") or ""
                spec = workflow_actions.spec(name) or {}
                pv = cfg.get("preview")
                if spec.get("writes") and pv and pv.get("name"):
                    fn = workflow_actions.get(pv["name"])
                    if not fn:
                        raise WorkflowError(f"preview 替身动作未注册: {pv['name']}")
                    out = await fn(pool, **_resolve_all(pv.get("args") or {}, ctx))
                elif not spec.get("writes"):
                    args = _resolve_all(cfg.get("args") or {}, ctx)
                    if ((cfg.get("ui") or {}).get("tap") == "tool"):
                        # Preview uses the same registry boundary as a real run;
                        # this keeps tool validation/audit and visual tools consistent.
                        from . import tools as tool_registry
                        out = await tool_registry.invoke(
                            pool, name, args, caller="workflow_preview",
                            source="workflow_preview", project_id=inputs.get("project_id"))
                    else:
                        fn = workflow_actions.get(name)
                        if not fn:
                            raise WorkflowError(f"未注册的动作 {name!r}")
                        # 规划类动作（wants_ctx）与真实运行对齐：预检也要把整份 ctx
                        # 传过去，否则 prepare_context 在预演里永远拿不到 __in__，
                        # 打开画布时参考素材一栏永远是 0（真实运行却是 N）。
                        out = await fn(pool, **args,
                                       **({"_ctx": ctx} if spec.get("wants_ctx") else {}))
                else:
                    report[key] = {"skipped_write": True}
                    continue
                ctx[key] = out
                report[key] = {"outputs": out}
            elif ntype == "gen":
                # 装配器（element.layers）是零副作用的纯取数，所以预检能算出**真实提示词**
                # 与参考图，画布参数一填、还没跑，生成条里就是即将提交的那一份
                layers, refs = await _assemble_layers(pool, cfg, ctx)
                _, up_refs = _upstream_media(ctx)
                done, why, val = await _already_done(pool, cfg, ctx)
                ctx[key] = {"url": val} if val else {}
                # 入参里声明的参考图（如封面画布的 ref_url）也要进预检回显——
                # 否则画布生成条看不见它，用户以为参考没生效（真实运行在 _apply_refs 里并）。
                seeded = _resolve_all(cfg.get("payload") or {}, ctx).get("reference_images") or []
                if isinstance(seeded, str):
                    seeded = [seeded]      # 单个 url 也合法；不包一层会被逐字符展开成假参考
                seeded_refs = [{"url": v, "name": "输入参考图"} if isinstance(v, str) else v
                               for v in seeded if isinstance(v, (str, dict))]
                report[key] = {
                    "exists": done, "value": val, "reason": why,
                    # 输入框回显的只是**用户需求层**：生成条留给用户写自己的需求
                    #（如「一直小猫在等待空气炸锅产出的鸡腿」）。上文/实体叙事是系统
                    # 隐式挂载，实跑时才进大模型规划，不回显、不占输入框。
                    "outputs": {"prompt": str(_instruction(cfg, ctx) or ""),
                                "reference_images": _dedupe_refs([*seeded_refs, *refs, *up_refs])},
                }
            elif ntype == "llm":
                # 不跑模型（要花钱），但**要探 skip_if**——那只是一条 SELECT，零副作用。
                # 只报 pending 的话，入参选好了卡上还是占位符，看着像"库里什么都没有"，
                # 实际早有内容（实测：选了「废弃仓库」，描述卡仍显示占位）。
                # 探到就把值按 text 回显，与 ui.show 对上；同时进 ctx 供下游取用。
                done, why, val = await _already_done(pool, cfg, ctx)
                ctx[key] = {"text": val} if val else {}
                report[key] = {
                    "exists": done, "value": val, "reason": why,
                    "pending_llm": not done,
                    **({"outputs": {"text": val}} if val else {}),
                }
            elif ntype == "subflow" and cfg.get("slug"):
                child_inputs = _resolve_all(cfg.get("inputs") or {}, ctx)
                child_inputs.setdefault("project_id", inputs.get("project_id"))
                child_preview = await preview_workflow(
                    pool, slug=str(cfg["slug"]), version=cfg.get("version"), inputs=child_inputs)
                # A multi-child child canvas publishes its preview collection through
                # end.outputs; the caller receives it as this subflow's outputs.
                child_end = child_preview.get("end") or {}
                out = child_end.get("outputs") or {}
                ctx[key] = out
                # 子画布探到的已有产物提升为 exists/value：画布回显按 gen 类节点的
                # exists/value 通道取数，subflow 不提升的话「首帧（缺才跑）」这类
                # subflow 节点明明探到了库里的关键帧，打开画布却永远空占位。
                promoted = next((v for k in ("url", "keyframe_url", "video_url",
                                             "sheet_url", "image_url")
                                 if isinstance((v := out.get(k)), str) and v), None)
                report[key] = {"outputs": out, "child_preview": child_preview,
                               **({"exists": True, "value": promoted} if promoted else {})}
            elif ntype in ("task", "subflow"):
                done, why, val = await _already_done(pool, cfg, ctx)
                report[key] = {"exists": done, "value": val, "reason": why}
            elif ntype == "end":
                report[key] = {"outputs": _resolve_all(cfg.get("outputs") or {}, ctx)}
            else:
                report[key] = {}
        except Exception as e:   # 预检是尽力而为：单节点探不出来不拖垮整张图
            report[key] = {"error": str(e)[:300]}
    return report


# ═══════════ 启动对账 ═══════════

async def reconcile_runs(pool: asyncpg.Pool) -> int:
    """重启后收尸：进程死掉时在跑的 run（同步的随请求死、异步的随协程死）全部
    标 failed——子任务不受影响（task_queue 自己会 reconcile 重排跑完，Step.next
    照常落库），所以只是这次运行记录中断，重跑会因「缺才跑」秒过。"""
    rows = await pool.fetch(
        "UPDATE workflow_runs SET status='failed', error='服务重启，运行中断', "
        "finished_at=now() WHERE status='running' RETURNING id")
    if rows:
        ids = [r["id"] for r in rows]
        await pool.execute(
            "UPDATE workflow_node_runs SET status='failed', error='服务重启，运行中断', "
            "finished_at=now() WHERE status IN ('running','pending') AND run_id=ANY($1)", ids)
        log.warning("workflow 对账：%d 个中断的 run 已标 failed: %s", len(ids), ids)
    return len(rows)
