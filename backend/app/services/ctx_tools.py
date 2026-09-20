"""把 Tapflow 运行期 ctx 变成「可分页探索的环境」的四把只读工具。

为什么需要这一层：现有 llm/action 节点拿上下文的方式是**作者预先在图上写死占位符**
（`{{分镜.script}}`），等于人来规划、模型只执行。规划类节点要反过来——模型自己判断
该看上游的哪一部分。那 ctx 就不能再是「预填进提示词的字符串」，得是模型能查询的环境。

分页是刚性要求，不是优化：一集几十镜、每镜提示词几千字，整份 ctx 序列化出来轻松几 MB，
一次性塞进上下文直接超限；而模型真正需要的往往只是其中两三个字段。所以：
`ctx.outline` 先看目录（恒定小、**不含正文**）→ `ctx.search` 定位 → `ctx.get` 精读那一段。

这四把不进 workflow_actions 注册表：它们操作的是内存态 ctx，不是库，也不该能被当成
画布节点拖出来用（脱离运行期没有意义）。挂载方式跟 skill.read / kb.search 同源——
见 agent_runtime.LOCAL / assemble。
"""
from __future__ import annotations

import json
from typing import Any

PREVIEW = 80          # outline 里每个字段的开头预览，够判断「是不是我要的」就行
MAX_CHARS = 4000      # ctx.get 单次返回的正文上限
MAX_ITEMS = 20        # ctx.get 单次返回的列表条数上限
SNIPPET = 200         # ctx.search 命中片段
INTERNAL = "__inputs__"   # 唯一对模型可见的内部键（工作流入参 = 开始节点签名）


def _flat(value: Any) -> str:
    """任意值 → 可搜索/可预览的扁平文本。"""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _kind(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "null" if value is None else type(value).__name__


def _size(value: Any) -> int:
    """给模型判断「这个字段要不要分页读」的量纲：文本按字数，容器按条数。"""
    if isinstance(value, str):
        return len(value)
    if isinstance(value, (list, dict)):
        return len(value)
    return 0


def _nodes(ctx: dict[str, Any]) -> dict[str, Any]:
    """对模型可见的节点集合：各节点产出 + 工作流入参，屏蔽其余内部键。

    `__overrides__` / `__node_inputs__` / `__in__` 是引擎自己的簿记，暴露出去只会让
    模型把它们当业务数据读。`__trace__` 单独由 ctx.trace 提供（它是时序而非节点视图）。
    """
    out = {k: v for k, v in ctx.items() if not k.startswith("__")}
    if isinstance(ctx.get(INTERNAL), dict):
        out[INTERNAL] = ctx[INTERNAL]
    return out


async def ctx_outline(_pool: Any = None, *, _ctx: dict[str, Any] | None = None,
                      **__: Any) -> dict[str, Any]:
    """列出上游各节点的产出目录：节点 → 字段名/类型/大小/开头预览，**不含正文**。

    先调这个再决定读哪一段。它的开销与上下文规模无关，可以随时重调。
    """
    ctx = _ctx or {}
    nodes = []
    for key, val in _nodes(ctx).items():
        fields = []
        if isinstance(val, dict):
            for fk, fv in val.items():
                fields.append({"field": fk, "type": _kind(fv), "size": _size(fv),
                               "preview": _flat(fv)[:PREVIEW]})
        else:
            fields.append({"field": None, "type": _kind(val), "size": _size(val),
                           "preview": _flat(val)[:PREVIEW]})
        nodes.append({"node": key, "fields": fields})
    return {"nodes": nodes, "node_count": len(nodes),
            "note": "用 ctx.get(node, field) 读正文；字段很大就带 offset/limit 分页；"
                    "不确定在哪个字段就先 ctx.search。"}


async def ctx_get(_pool: Any = None, *, node: str = "", field: str | None = None,
                  offset: int = 0, limit: int | None = None,
                  _ctx: dict[str, Any] | None = None, **__: Any) -> dict[str, Any]:
    """读某个节点产出的正文，支持分页。

    文本按字符切片（limit 默认 4000 字），数组按条切片（默认 20 条）。返回 has_more
    表示还有后续，用 offset 继续读。不传 field = 返回该节点的字段清单（长文本折叠成
    摘要，需要正文再指名 field）。
    """
    ctx = _ctx or {}
    nodes = _nodes(ctx)
    if node not in nodes:
        raise KeyError(f"ctx 里没有节点 {node!r}；可用：{', '.join(nodes) or '（空）'}")
    val = nodes[node]

    if field is not None:
        if not isinstance(val, dict):
            raise KeyError(f"节点 {node!r} 的产出不是对象，不能取字段 {field!r}")
        if field not in val:
            raise KeyError(f"节点 {node!r} 没有字段 {field!r}；"
                           f"可用：{', '.join(map(str, val)) or '（空）'}")
        val = val[field]

    start = max(0, int(offset or 0))
    if isinstance(val, str):
        n = max(1, min(int(limit or MAX_CHARS), MAX_CHARS))
        chunk = val[start:start + n]
        return {"node": node, "field": field, "type": "string", "offset": start,
                "total": len(val), "value": chunk,
                "has_more": start + len(chunk) < len(val)}
    if isinstance(val, list):
        n = max(1, min(int(limit or MAX_ITEMS), MAX_ITEMS))
        chunk = val[start:start + n]
        return {"node": node, "field": field, "type": "array", "offset": start,
                "total": len(val), "value": chunk,
                "has_more": start + len(chunk) < len(val)}
    if isinstance(val, dict) and field is None:
        # 不指名字段就别把整个对象的长文本全铺开——那正是要避免的一次性全量
        folded = {k: (v if _size(v) <= PREVIEW * 2 or not isinstance(v, str)
                      else {"_folded": True, "type": _kind(v), "size": _size(v),
                            "preview": _flat(v)[:PREVIEW]})
                  for k, v in val.items()}
        return {"node": node, "field": None, "type": "object", "value": folded,
                "has_more": False,
                "note": "带 _folded 的字段是长文本，用 ctx.get(node, field) 读全文"}
    return {"node": node, "field": field, "type": _kind(val), "value": val,
            "has_more": False}


async def ctx_search(_pool: Any = None, *, query: str = "", nodes: list[str] | None = None,
                     top_k: int = 8, _ctx: dict[str, Any] | None = None,
                     **__: Any) -> dict[str, Any]:
    """在 ctx 里按关键词定位（大小写不敏感的子串匹配），返回 节点/字段/位置/片段。

    命中后用 ctx.get(node, field, offset) 精读。这是「上下文很长、但我只要其中一处」
    的正路——比把整份 ctx 读一遍再自己找便宜几个数量级。
    """
    ctx = _ctx or {}
    q = (query or "").strip()
    if not q:
        raise ValueError("query 不能为空")
    ql = q.lower()
    only = set(nodes or [])
    hits = []
    for key, val in _nodes(ctx).items():
        if only and key not in only:
            continue
        pairs = val.items() if isinstance(val, dict) else [(None, val)]
        for fk, fv in pairs:
            text = _flat(fv)
            pos = text.lower().find(ql)
            if pos < 0:
                continue
            lo = max(0, pos - SNIPPET // 2)
            hits.append({"node": key, "field": fk, "offset": pos, "size": _size(fv),
                         "snippet": text[lo:lo + SNIPPET]})
            if len(hits) >= max(1, min(int(top_k or 8), 50)):
                return {"query": q, "hits": hits, "hit_count": len(hits),
                        "truncated": True}
    return {"query": q, "hits": hits, "hit_count": len(hits), "truncated": False}


async def ctx_trace(_pool: Any = None, *, limit: int = 12,
                    _ctx: dict[str, Any] | None = None, **__: Any) -> dict[str, Any]:
    """读执行轨迹（按真实执行序的 节点/类型/标题/入参/出参摘要），默认最近 12 条。

    outline 是「现在有什么」的空间视图，trace 是「刚才发生了什么」的时间视图——
    上一步为什么产出是空的、哪个节点被跳过了，只有轨迹里有。
    """
    trace = (_ctx or {}).get("__trace__")
    items = trace if isinstance(trace, list) else []
    n = max(1, min(int(limit or 12), 50))
    return {"total": len(items), "entries": items[-n:]}


# 挂载表：形状与 agent_runtime.LOCAL 一致（name/title/description/params/writes/fn），
# 由 agent_runtime.assemble 在 flow_ctx 非空时整体挂上。
LOCAL: dict[str, dict[str, Any]] = {
    "ctx.outline": {
        "name": "ctx.outline", "title": "上下文目录", "writes": False,
        "description": (ctx_outline.__doc__ or "").strip(),
        "params": {}, "fn": ctx_outline,
    },
    "ctx.get": {
        "name": "ctx.get", "title": "读上下文字段", "writes": False,
        "description": (ctx_get.__doc__ or "").strip(),
        "params": {
            "node": {"type": "string", "required": True, "desc": "节点名（ctx.outline 里的 node）"},
            "field": {"type": "string", "required": False, "desc": "字段名；不传返回字段清单"},
            "offset": {"type": "int", "required": False, "desc": "起始位置，分页续读用"},
            "limit": {"type": "int", "required": False,
                      "desc": f"文本最多 {MAX_CHARS} 字 / 数组最多 {MAX_ITEMS} 条"},
        },
        "fn": ctx_get,
    },
    "ctx.search": {
        "name": "ctx.search", "title": "检索上下文", "writes": False,
        "description": (ctx_search.__doc__ or "").strip(),
        "params": {
            "query": {"type": "string", "required": True, "desc": "关键词"},
            "nodes": {"type": "array", "required": False, "desc": "限定节点名，留空搜全部"},
            "top_k": {"type": "int", "required": False, "desc": "命中上限，默认 8"},
        },
        "fn": ctx_search,
    },
    "ctx.trace": {
        "name": "ctx.trace", "title": "读执行轨迹", "writes": False,
        "description": (ctx_trace.__doc__ or "").strip(),
        "params": {"limit": {"type": "int", "required": False, "desc": "最近几条，默认 12"}},
        "fn": ctx_trace,
    },
}
