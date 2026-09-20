"""智能体规划引擎（2026-07-29 新增，纯增量）。

最小单元固定是三样：**技能 + 知识 + 工具**。本模块只做一件事——把它们喂给模型，
跑 tool-calling 循环，直到模型不再要工具为止。

三样各自怎么进上下文：

- **技能**：渐进披露。系统提示词里只列 `name + description`（SKILL.md frontmatter 那两行），
  模型自己判断要用哪个，再调 `skill.read` 读全文。技能多起来之后全量塞进上下文根本放不下，
  而 description 本来就是写来给模型做触发判断的。
- **知识**：按选中的文件夹圈定范围，模型调 `kb.search` 检索。不预先全塞。
- **工具**：直接复用 `services/tools.py` 的统一注册表（含 `db.query` 只读 SQL），
  调用走 `tools.invoke`，全量落 `tool_calls` 审计。本模块不另起第二套注册表。

为什么不用 Claude Agent SDK / Google ADK：本项目模型层是 OpenAI 兼容的（`models_registry`
配 base_url/api_key/model），那两家都要求规划引擎单独走自家 API，等于跟出图出视频的模型分家。
而工具已经是本地 Python 函数，循环本身不到百行。
"""
from __future__ import annotations

import json
import re
from typing import Any

import asyncpg

from .. import llm
from . import agent_batch, ctx_tools, kb_ingest, tools as tool_registry

MAX_STEPS = 12
KB_SNIPPET = 1200

# 运行上下文 → 工具入参的别名。工具各自按业务命名（shot_id / element_id），
# 上下文只有 project_id / node_id / element_id 三个。**模型调工具时也要补**——
# 否则模型只会传它在任务描述里看到的那个 id，漏掉 project_id，工具就查空
# （实测：element.get 只给 element_id 返回空，模型接着回「要素 id 无效」）。
CTX_ALIAS: dict[str, tuple[str, ...]] = {
    "project_id": ("project_id",),
    "node_id": ("node_id", "shot_id", "chapter_id"),
    "element_id": ("element_id",),
    # 质检回退重试（agent_unit）：把上一轮问题清单递给声明了对应参数的工具
    # （reassemble 留档用 qc_feedback，质检复评用 prev_feedback）
    "qc_feedback": ("qc_feedback", "prev_feedback"),
}


def inject_ctx(spec: dict[str, Any], args: dict[str, Any],
               ctx: dict[str, Any]) -> dict[str, Any]:
    """按工具声明的参数补运行上下文。

    **上下文强制覆盖模型给的值**，不是「空了才填」。运行上下文是用户在界面上选定的事实，
    模型没资格猜自己在哪个项目/哪一集上干活——实测它会直接编一个 `project_id: 23`
    （真实上下文是 25），然后一路查空、回「要素不存在」，而表面上工具调用是成功的。
    """
    out = dict(args)
    declared = set(spec.get("params") or {})
    for key, names in CTX_ALIAS.items():
        if ctx.get(key) is None:
            continue
        for n in names:
            if n in declared:
                out[n] = ctx[key]
                break
    return out


class AgentError(Exception):
    """智能体运行失败（对调用方可预期，不是 500）。"""


# ── 本地工具：只服务于「技能/知识」两个最小单元，不进 workflow_actions 注册表 ──

async def skill_read(pool: asyncpg.Pool, *, slug: str, path: str | None = None,
                     **_: Any) -> dict[str, Any]:
    """读一个技能的全文（SKILL.md），或它携带的某个附件。"""
    row = await pool.fetchrow(
        "SELECT id,slug,name,description,skill_md FROM skill_packages "
        "WHERE slug=$1 AND status='installed'", slug)
    if not row:
        raise tool_registry.ToolError(f"技能 {slug!r} 不存在或未启用")
    if not path:
        files = await pool.fetch(
            "SELECT path FROM skill_package_files WHERE skill_id=$1 ORDER BY path", row["id"])
        return {"slug": row["slug"], "name": row["name"], "skill_md": row["skill_md"],
                "files": [f["path"] for f in files]}
    content = await pool.fetchval(
        "SELECT content FROM skill_package_files WHERE skill_id=$1 AND path=$2",
        row["id"], path)
    if content is None:
        raise tool_registry.ToolError(f"技能 {slug!r} 没有文件 {path!r}")
    return {"slug": slug, "path": path, "content": content}


def _folder_clause(folder: asyncpg.Record, idx: int) -> tuple[str, list[Any]]:
    """系统文件夹按 (kind,category) 规则圈定；自定义文件夹按 folder_id 归属。"""
    if not folder["system"]:
        return f"e.folder_id = ${idx}", [folder["id"]]
    if folder["category"]:
        return f"(e.kind = ${idx} AND e.category = ${idx + 1})", [
            folder["kind"], folder["category"]]
    return f"e.kind = ${idx}", [folder["kind"]]


async def kb_search(pool: asyncpg.Pool, *, query: str, folder_ids: list[int] | None = None,
                    top_k: int = 5, project_id: int | None = None,
                    content_type: str | None = None,
                    **_: Any) -> dict[str, Any]:
    """在选中的知识库文件夹里检索条目。

    2026-09-17 升级：走 kb_ingest.search_entries 混合检索（向量+trgm+ILIKE 三级融合，
    任一级缺席自动降级），返回条目带 score/source_name/chunk_seq 供引用回溯。"""
    folders = await pool.fetch(
        "SELECT id,name,title,kind,category,system FROM kb_folders WHERE id = ANY($1::bigint[])",
        list(folder_ids or []))
    if not folders:
        raise tool_registry.ToolError("本节点没有绑定知识库文件夹，无法检索")

    where, args = [], [f"%{(query or '').strip()}%", project_id, content_type]
    for f in folders:
        clause, extra = _folder_clause(f, len(args) + 1)
        where.append(clause)
        args += extra
    hits = await kb_ingest.search_entries(
        pool, query, folder_ids=list(folder_ids or []), project_id=project_id,
        content_type=content_type, top_k=max(1, min(int(top_k or 5), 20)))
    return {"query": query, "hits": hits, "hit_count": len(hits)}


LOCAL: dict[str, dict[str, Any]] = {
    "skill.read": {
        "name": "skill.read", "title": "读技能全文", "writes": False,
        "description": "读取一个技能的 SKILL.md 全文；带 path 则读该技能的附件文件。"
                       "先按系统提示词里的技能描述判断该用哪个，再读全文。",
        "params": {"slug": {"type": "string", "required": True, "desc": "技能 slug"},
                   "path": {"type": "string", "required": False, "desc": "附件相对路径"}},
        "fn": skill_read,
    },
    "kb.search": {
        "name": "kb.search", "title": "检索知识库", "writes": False,
        "description": "在本节点绑定的知识库文件夹里按关键词检索条目，返回正文片段。",
        "params": {"query": {"type": "string", "required": True, "desc": "检索关键词"},
                   "top_k": {"type": "int", "required": False, "desc": "返回条数，默认 5"}},
        "fn": kb_search,
    },
}

_JSON_TYPE = {"int": "integer", "number": "number", "bool": "boolean",
              "array": "array", "object": "object"}


def openai_schema(spec: dict[str, Any]) -> dict[str, Any]:
    """工具注册表的 spec → OpenAI function calling 的 tool schema。"""
    props, required = {}, []
    for key, p in (spec.get("params") or {}).items():
        props[key] = {"type": _JSON_TYPE.get(p.get("type", "string"), "string"),
                      "description": p.get("desc", "")}
        if props[key]["type"] == "array":
            props[key]["items"] = {}
        if p.get("required"):
            required.append(key)
    return {"type": "function", "function": {
        "name": spec["name"].replace(".", "__"),  # 部分供应商不接受函数名里的点
        "description": (spec.get("description") or spec.get("title") or "")[:1024],
        "parameters": {"type": "object", "properties": props, "required": required},
    }}


# ── 装配：把技能/知识/工具三样变成系统提示词 + tool schema ──

async def assemble(pool: asyncpg.Pool, *, charter: str, skills: list[str],
                   folder_ids: list[int], tool_names: list[str],
                   content_type: str | None = None,
                   has_flow_ctx: bool = False,
                   ) -> tuple[str, list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """返回 (system_prompt, tool_schemas, 可调工具表)。"""
    parts = [charter.strip() or "你是本项目的智能体。"]

    if skills:
        rows = await pool.fetch(
            "SELECT s.slug,s.name,s.description FROM skill_packages s "
            "LEFT JOIN kb_entries e ON e.id=s.legacy_kb_id "
            "WHERE s.slug = ANY($1::text[]) AND s.status='installed' "
            "AND ($2::text IS NULL OR $2='novel_comic' "
            "     OR $2 = ANY(COALESCE(NULLIF(s.tags,'{}'), e.tags, '{}'))) "
            "ORDER BY s.slug", skills, content_type)
        if rows:
            parts.append("## 可用技能\n" + "\n".join(
                f"- `{r['slug']}` {r['name']}：{r['description']}" for r in rows)
                + "\n\n判断哪个技能适用后，用 skill.read 读它的全文再动手；不要凭描述臆断做法。")

    if folder_ids:
        rows = await pool.fetch(
            "SELECT title FROM kb_folders WHERE id = ANY($1::bigint[]) ORDER BY seq,id",
            folder_ids)
        if rows:
            parts.append("## 可检索的知识库\n"
                         + "、".join(r["title"] for r in rows)
                         + "\n需要事实依据时用 kb.search 检索，别编。")

    if has_flow_ctx:
        parts.append(
            "## 运行上下文（ctx）\n你挂在一条 Tapflow 里，上游各节点的产出都在 ctx 中。"
            "**不要假设自己已经看到了全部上下文**——它可能有几十万字，一次性读不下。"
            "标准做法：先 `ctx.outline` 看目录（只有字段名/大小/开头，很便宜），"
            "判断需要哪几段；不确定在哪就 `ctx.search` 定位；再 `ctx.get` 按 offset 分页精读。"
            "想知道上一步为什么是空的就看 `ctx.trace`。分多轮取数是预期行为，不是失败。")

    # 工具：本地几把（技能/知识/上下文）按条件挂，业务工具按节点勾选
    usable: dict[str, dict[str, Any]] = {}
    if skills:
        usable["skill.read"] = LOCAL["skill.read"]
    if folder_ids:
        usable["kb.search"] = LOCAL["kb.search"]
    if has_flow_ctx:
        usable.update(ctx_tools.LOCAL)
    by_name = {s["name"]: s for s in tool_registry.specs()}
    for name in tool_names or []:
        if name in by_name:
            usable[name] = by_name[name]

    parts.append("## 工作方式\n先取事实再下结论：需要项目数据就查，需要做法就读技能。"
                 "拿到足够信息就直接给结果，不要复述过程，也不要罗列你没有采纳的方案。")
    return "\n\n".join(parts), [openai_schema(s) for s in usable.values()], usable


async def run(pool: asyncpg.Pool, *, charter: str, task: str,
              skills: list[str] | None = None, folder_ids: list[int] | None = None,
              tool_names: list[str] | None = None, project_id: int | None = None,
              ctx: dict[str, Any] | None = None, flow_ctx: dict[str, Any] | None = None,
              max_steps: int = MAX_STEPS, caller: str = "sys_dev",
              content_type: str | None = None) -> dict[str, Any]:
    """跑一个智能体：模型不再要工具时，它那条 content 就是产物。

    返回 steps 是完整调用轨迹，画布拿它回放到节点上（跟工作流的 node_runs 一个用法）。

    `ctx` 与 `flow_ctx` 是两样东西，别混：前者是**扁平别名表**（project_id/node_id/
    element_id），只用来覆盖工具入参（见 inject_ctx）；后者是 Tapflow 运行期**整份 ctx**
    （节点名 → 产出），非空时挂上 ctx.* 四把只读工具让模型自己分页探索。
    """
    if content_type is None:
        project_id = (ctx or {}).get("project_id") or project_id
    if content_type is None and project_id:
        content_type = await pool.fetchval(
            "SELECT project_type FROM content_projects WHERE id=$1", project_id)
    system, schemas, usable = await assemble(
        pool, charter=charter, skills=skills or [], folder_ids=folder_ids or [],
        tool_names=tool_names or [], has_flow_ctx=flow_ctx is not None,
        content_type=content_type)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": task},
    ]
    steps: list[dict[str, Any]] = []

    for _ in range(max(1, max_steps)):
        msg = await llm.chat_tools(messages, schemas or None)
        calls = msg.get("tool_calls") or []
        if not calls:
            return {"output": msg.get("content") or "", "steps": steps,
                    "system": system, "tools": list(usable)}
        # 助手轮必须原样回填，否则下一轮模型看不到自己刚发起的调用
        messages.append({"role": "assistant", "content": msg.get("content"),
                         "tool_calls": calls})
        for call in calls:
            fn = call.get("function") or {}
            name = (fn.get("name") or "").replace("__", ".")
            # 能力目录里的 id 是 `tool:xxx`，模型看完目录常照抄成工具名（实测必踩）。
            # 剥前缀后仍要过授权检查，安全语义不变，只是不再为一个前缀白烧一轮。
            if name.startswith("tool:"):
                name = name[len("tool:"):]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            step = {"tool": name, "args": args}
            try:
                if name not in usable:
                    raise tool_registry.ToolError(f"本节点未授权工具 {name!r}")
                if name in LOCAL or name in ctx_tools.LOCAL:
                    # 引擎自带的几把（技能/知识/上下文）：project_id、知识库范围、运行期
                    # ctx 都由节点补，模型不用传——它也不该有能力指定自己读哪份上下文。
                    local = LOCAL.get(name) or ctx_tools.LOCAL[name]
                    out = await local["fn"](
                        pool, project_id=project_id, folder_ids=folder_ids,
                        content_type=content_type, _ctx=flow_ctx, **args)
                else:
                    full = inject_ctx(usable[name], args,
                                      {"project_id": project_id, **(ctx or {})})
                    step["args"] = full
                    out = await tool_registry.invoke(
                        pool, name, full, caller=caller, source="agent",
                        project_id=project_id, flow_ctx=flow_ctx)
                step["ok"], step["result"] = True, out
            except Exception as e:  # noqa: BLE001 — 工具失败要回喂给模型自我修正，不是中断
                step["ok"], step["error"] = False, f"{type(e).__name__}: {e}"
                out = {"error": step["error"]}
            steps.append(step)
            messages.append({"role": "tool", "tool_call_id": call.get("id"),
                             "content": json.dumps(out, ensure_ascii=False, default=str)})

    raise AgentError(f"超过 {max_steps} 步仍未收敛；检查技能描述是否含糊或工具是否总失败")


_VARS = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def fill(text: str, ctx: dict[str, Any]) -> str:
    """把 {{ctx.project_id}} / {{item.name}} 这类占位符换成实际值；认不出的原样留着。"""
    def sub(m: re.Match[str]) -> str:
        v = ctx.get(m.group(1))
        return m.group(0) if v is None else str(v)
    return _VARS.sub(sub, text or "")


async def run_batch(pool: asyncpg.Pool, *, charter: str, task: str,
                    skills: list[str] | None = None, folder_ids: list[int] | None = None,
                    tool_names: list[str] | None = None, project_id: int | None = None,
                    node_id: int | None = None, batch: str = "",
                    only_missing: bool = True, element_id: int | None = None,
                    limit: int = 20, caller: str = "admin_ui",
                    content_type: str | None = None) -> dict[str, Any]:
    """跑一个智能体节点：`batch` 为空就跑一次，否则对每个条目各跑一次。

    limit 是**保护性上限**——一集几十个镜头，手滑点一次批量就是几十次真实模型调用。
    """
    base = {"ctx.project_id": project_id, "ctx.node_id": node_id,
            "ctx.element_id": element_id}

    if not batch:
        one = await run(pool, charter=charter, task=fill(task, base), skills=skills,
                        folder_ids=folder_ids, tool_names=tool_names,
                        project_id=project_id, caller=caller, content_type=content_type)
        return {"batch": None, "ran": 1, "skipped": 0, "results": [{**one, "label": "单个"}]}

    plan = await agent_batch.resolve(pool, batch, project_id=project_id, node_id=node_id,
                                     only_missing=only_missing)
    todo = plan["items"][:max(1, limit)]
    results = []
    for item in todo:
        ctx = {**base, "item.id": item["id"], "item.name": item["label"],
               f"ctx.{item['ctx_key']}": item["id"]}
        try:
            out = await run(pool, charter=charter, task=fill(task, ctx), skills=skills,
                            folder_ids=folder_ids, tool_names=tool_names,
                            project_id=project_id, caller=caller, content_type=content_type)
            results.append({**out, "label": item["label"], "item_id": item["id"]})
        except Exception as e:  # noqa: BLE001 — 一个对象失败不该让整批停下
            results.append({"label": item["label"], "item_id": item["id"],
                            "output": "", "steps": [], "error": f"{type(e).__name__}: {e}"})
    return {"batch": plan["label"], "ran": len(results),
            "skipped": len(plan["skipped"]), "total": plan["total"],
            "truncated": len(plan["items"]) > len(todo),
            "skipped_labels": [s["label"] for s in plan["skipped"]][:20],
            "results": results}
