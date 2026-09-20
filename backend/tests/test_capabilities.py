"""能力目录：工具与 tapflow 同构、元能力不进目录、plan_invoke 只校验不执行。

盯的是三条设计约束，回归任何一条都会让规划节点悄悄给出错误计划：
1. 条目形状同构 —— 否则能力从工具迁成流程时，用它的编排要跟着改；
2. 元能力不进目录 —— 否则规划器把「再规划一次」当成能产出内容的能力；
3. plan_invoke 绝不执行 —— 它是给模型随便试的，一旦会跑就等于随便花钱。
"""
import asyncio

import pytest

from backend.app.services import capabilities as C

SHAPE = {"id", "kind", "title", "description", "inputs", "outputs", "writes",
         "cardinality", "group"}


class FakePool:
    """只需要 fetch(workflows 那一条)；capabilities 对库的依赖就这一处。"""

    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, _sql, *_args):
        return self.rows


def flow_row(slug="nine-grid", *, graph=None, name="故事板九宫格"):
    return {
        "slug": slug, "name": name, "description": "从描述生成 3×3 故事板",
        "version": 3,
        "input_schema": {"project_id": {"type": "int", "required": True},
                         "grid_prompt": {"type": "string", "required": True}},
        "output_schema": {"image_url": {"type": "string"}},
        "graph": graph or {"nodes": [{"id": "start", "type": "start"},
                                     {"id": "g", "type": "gen"},
                                     {"id": "end", "type": "end"}],
                           "edges": [{"from": "g", "to": "end"}]},
    }


def run(coro):
    return asyncio.run(coro)


def test_tool_and_flow_entries_share_one_shape():
    """同构是这层的全部价值：两边的键必须一模一样。"""
    tool = C._tool_entry({"name": "shot.info", "title": "镜信息", "description": "d",
                          "params": {}, "outputs": {}, "group": "shot"})
    flow = C._flow_entry(flow_row())
    assert SHAPE <= set(tool) and SHAPE <= set(flow)
    assert tool["id"] == "tool:shot.info" and flow["id"] == "flow:nine-grid"


def test_flow_writes_and_cost_derive_from_graph():
    """副作用/成本是从图里 gen|task 节点数推出来的，不靠人另填一个字段。"""
    assert C._flow_writes({"nodes": [{"type": "gen"}, {"type": "action"}]}) == (True, 1)
    assert C._flow_writes({"nodes": [{"type": "action"}]}) == (False, 0)
    assert C._flow_writes({}) == (False, 0)


def test_meta_capabilities_are_excluded():
    """规划器不该在目录里看到自己——实测它会把「缺分镜脚本」的解法写成再调一次自己。"""
    ids = {e["id"] for e in run(C.entries(FakePool([])))}
    assert not (ids & C.META)
    assert "tool:db.query" in ids   # 普通工具照常在


def test_catalog_filters_and_truncates():
    pool = FakePool([flow_row(), flow_row("scene-desc", name="场景描述",
                                          graph={"nodes": []})])
    hit = run(C.catalog(pool, query="九宫格"))
    assert [c["id"] for c in hit["capabilities"]] == ["flow:nine-grid"]
    assert run(C.catalog(pool, kind="flow"))["total"] == 2
    assert run(C.catalog(pool, kind="flow", writes=False))["total"] == 1
    small = run(C.catalog(pool, kind="flow", limit=1))
    assert small["truncated"] is True and len(small["capabilities"]) == 1


def test_plan_invoke_reports_missing_and_never_executes():
    pool = FakePool([flow_row()])
    out = run(C.plan_invoke(pool, id="flow:nine-grid", inputs={"project_id": 25}))
    assert out["ok"] is False and out["missing"] == ["grid_prompt"]
    assert out["executed"] is False
    assert out["cost"]["costly_nodes"] == 1
    assert out["will_produce"] == {"image_url": {"type": "string"}}


def test_plan_invoke_accepts_double_wrapped_inputs():
    """模型常把 {"inputs": {...}} 再套一层；为一个包装白烧一轮不值得。"""
    pool = FakePool([flow_row()])
    out = run(C.plan_invoke(pool, id="flow:nine-grid",
                            inputs={"inputs": {"project_id": 25, "grid_prompt": "x"}}))
    assert out["ok"] is True and out["missing"] == []


def test_plan_invoke_flags_unknown_params_and_bad_id():
    pool = FakePool([flow_row()])
    out = run(C.plan_invoke(pool, id="flow:nine-grid",
                            inputs={"project_id": 1, "grid_prompt": "x", "nope": 1}))
    assert out["unknown"] == ["nope"]
    with pytest.raises(KeyError):
        run(C.plan_invoke(pool, id="flow:does-not-exist"))


def test_superseded_capability_redirects(monkeypatch):
    """迁移期老 id 要能继续调，否则每迁一个能力就断一批在跑的编排。"""
    monkeypatch.setitem(C.SUPERSEDED, "tool:legacy.grid", "flow:nine-grid")
    pool = FakePool([flow_row()])
    out = run(C.plan_invoke(pool, id="tool:legacy.grid",
                            inputs={"project_id": 1, "grid_prompt": "x"}))
    assert out["id"] == "flow:nine-grid" and out["redirected_from"] == "tool:legacy.grid"
    assert out["ok"] is True
