"""ctx.* 四把只读工具：分页、定位、内部键屏蔽。

这几条盯的是「上下文很长时不会一次性全量返回」这个唯一目的——回归掉了，规划节点
就会在真实数据上直接撑爆上下文，而且不报错，只是产出变差。
"""
import asyncio

import pytest

from backend.app.services import ctx_tools as C


def ctx():
    return {
        "__inputs__": {"project_id": 25, "chapter_id": 769},
        "__overrides__": {"plan": {"instruction": "别读到我"}},
        "__node_inputs__": {"plan": {"goal": "别读到我"}},
        "__in__": ["start"],
        "__trace__": [{"node": "start", "type": "start", "outputs": {"project_id": 25}},
                      {"node": "script", "type": "llm", "outputs": {"text": "…"}}],
        "script": {"text": "甲" * 10_000, "shots": [{"i": n} for n in range(50)]},
        "style": {"anchor": "赛博朋克 霓虹"},
    }


def run(coro):
    return asyncio.run(coro)


def test_outline_has_no_bodies():
    """目录只给字段名/类型/大小/开头，正文一律不带——否则 outline 自己就是全量输出。"""
    out = run(C.ctx_outline(_ctx=ctx()))
    text = next(f for n in out["nodes"] if n["node"] == "script"
                for f in n["fields"] if f["field"] == "text")
    assert text["size"] == 10_000
    assert len(text["preview"]) <= C.PREVIEW


def test_outline_hides_engine_bookkeeping():
    """__overrides__ / __node_inputs__ / __in__ 是引擎簿记，暴露了模型会当业务数据读。"""
    nodes = {n["node"] for n in run(C.ctx_outline(_ctx=ctx()))["nodes"]}
    assert nodes == {"script", "style", "__inputs__"}


def test_get_pages_long_text():
    first = run(C.ctx_get(node="script", field="text", limit=100, _ctx=ctx()))
    assert first["value"] == "甲" * 100
    assert first["total"] == 10_000 and first["has_more"] is True
    tail = run(C.ctx_get(node="script", field="text", offset=9_950, _ctx=ctx()))
    assert len(tail["value"]) == 50 and tail["has_more"] is False


def test_get_clamps_limit_to_ceiling():
    """模型给个 limit=999999 也不能真返回 —— 上限由引擎定，不由模型定。"""
    out = run(C.ctx_get(node="script", field="text", limit=10 ** 9, _ctx=ctx()))
    assert len(out["value"]) == C.MAX_CHARS


def test_get_pages_arrays_by_item():
    out = run(C.ctx_get(node="script", field="shots", offset=45, _ctx=ctx()))
    assert out["value"] == [{"i": n} for n in range(45, 50)]
    assert out["total"] == 50 and out["has_more"] is False


def test_get_without_field_folds_long_text():
    """不指名字段就把整个对象铺开，等于绕过分页；长文本必须折叠成摘要。"""
    out = run(C.ctx_get(node="script", _ctx=ctx()))
    assert out["value"]["text"]["_folded"] is True
    assert out["value"]["shots"] == [{"i": n} for n in range(50)]


def test_unknown_node_and_field_list_alternatives():
    """报错要带可用清单，模型才能下一轮自我修正而不是反复瞎猜。"""
    with pytest.raises(KeyError, match="script"):
        run(C.ctx_get(node="nope", _ctx=ctx()))
    with pytest.raises(KeyError, match="shots"):
        run(C.ctx_get(node="script", field="nope", _ctx=ctx()))


def test_search_locates_field_and_offset():
    out = run(C.ctx_search(query="霓虹", _ctx=ctx()))
    assert out["hit_count"] == 1
    hit = out["hits"][0]
    assert (hit["node"], hit["field"]) == ("style", "anchor")
    assert hit["offset"] == len("赛博朋克 ")


def test_search_scoped_and_empty_query():
    assert run(C.ctx_search(query="霓虹", nodes=["script"], _ctx=ctx()))["hit_count"] == 0
    with pytest.raises(ValueError):
        run(C.ctx_search(query="  ", _ctx=ctx()))


def test_trace_returns_tail():
    out = run(C.ctx_trace(limit=1, _ctx=ctx()))
    assert out["total"] == 2 and [e["node"] for e in out["entries"]] == ["script"]


def test_tools_survive_empty_ctx():
    """节点挂在图最前面时 ctx 里除了入参什么都没有，这几把不能炸。"""
    assert run(C.ctx_outline(_ctx={}))["node_count"] == 0
    assert run(C.ctx_search(query="x", _ctx={}))["hit_count"] == 0
    assert run(C.ctx_trace(_ctx={}))["total"] == 0
