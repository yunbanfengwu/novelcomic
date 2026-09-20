"""画布上文（_canvas_context，2026-09-17 定稿的通用语义）：

**连线拓扑即对话历史**——gen/llm 节点运行时，沿连线递归回溯全部上游，
产物按「标题：内容」标注成清单交给模型按需引用；start 的入参与项目设定
自动在列。charter 不必再写「请先查询项目信息」，也不必手工配引用标签。

媒体上游不进文本清单（它们按类型进参考图，_upstream_media 负责）；纯跳过
节点（缺才跑命中且无产物回显）不算上文；target_ref 等路由键不是创作内容。
"""
import asyncio

from app.services import workflow as W


class FakePool:
    async def fetchrow(self, sql, pid):
        class Row(dict):
            def __getitem__(self, k):
                return dict.__getitem__(self, k) or ""
        return Row({"title": "北境灯塔", "art_style": "电影级奇幻写实动画",
                    "storyline": "守塔人后裔的冒险", "writing_style": "冷峻克制",
                    "config": "{\"aspect\": \"16:9\"}"})


def _wf(edges, nodes):
    """nodes: [(id, type, title), ...]；edges: [(from, to), ...]"""
    return {"graph": {
        "nodes": [{"id": i, "type": t, "config": {"ui": {"title": ti}}}
                  for i, t, ti in nodes],
        "edges": [{"from": a, "to": b} for a, b in edges],
    }}


def _ctx(wf, inputs=None, in_=()):
    return {
        "__inputs__": dict(inputs or {}),
        "__in__": list(in_),
        "start": dict(inputs or {}),
        "__graph__": W._graph_index(wf),
    }


def test_recursive_ancestors_across_chain():
    """gen 只直连文本节点，文本又只连角色卡——两层上游都要收进上文。"""
    wf = _wf([("start", "card"), ("card", "intro"), ("intro", "gen")],
             [("start", "start", "start"), ("card", "value", "角色卡"),
              ("intro", "llm", "场景介绍"), ("gen", "gen", "封面")])
    ctx = _ctx(wf, {"project_id": 25, "chapter": "第三章"}, ["intro"])
    ctx["card"] = {"text": "姓名：凛；身份：守塔人后裔", "status": "done"}
    ctx["intro"] = {"text": "黄昏的港口，暴雨将至。", "status": "done"}
    out = asyncio.run(W._canvas_context(FakePool(), ctx, project_id=25))
    assert "文本「角色卡」：姓名：凛" in out, out
    assert "文本「场景介绍」：黄昏的港口" in out, out
    assert "项目「北境灯塔」：画风 电影级奇幻写实动画" in out, out
    assert "画幅 16:9" in out, out   # 画幅存 config JSON，不单独占列
    assert "入参：chapter 第三章" in out, out
    # 远→近：start 端（项目/入参）在最前，像对话历史
    assert out.index("项目「北境灯塔」") < out.index("文本「场景介绍」"), out


def test_only_picked_stops_recursion():
    """生成条手选参考节点 = 我明确只要这几个，不向上递归。"""
    wf = _wf([("start", "card"), ("card", "intro"), ("intro", "gen")],
             [("start", "start", "start"), ("card", "value", "角色卡"),
              ("intro", "llm", "场景介绍"), ("gen", "gen", "封面")])
    ctx = _ctx(wf, {"project_id": 25}, ["intro"])
    ctx["card"] = {"text": "角色卡正文"}
    ctx["intro"] = {"text": "场景正文"}
    out = asyncio.run(W._canvas_context(FakePool(), ctx, only=True))
    assert "文本「场景介绍」" in out, out
    assert "角色卡" not in out, out


def test_route_keys_excluded():
    """target_ref 等寻址键不是创作内容，不进上文。"""
    wf = _wf([], [("gen", "gen", "封面")])
    ctx = _ctx(wf, {"project_id": 25, "target_ref": "element:172"}, [])
    out = asyncio.run(W._canvas_context(FakePool(), ctx, project_id=None))
    assert out == "", out


def test_skipped_upstream_not_context():
    """纯跳过（缺才跑命中且没带产物回显）不算上文；带产物回显的跳过算。"""
    wf = _wf([("start", "intro"), ("intro", "gen")],
             [("start", "start", "start"), ("intro", "llm", "场景介绍"),
              ("gen", "gen", "封面")])
    ctx = _ctx(wf, {"project_id": 25}, ["intro"])
    ctx["intro"] = {"skipped": True, "reason": "no change"}
    assert asyncio.run(W._canvas_context(FakePool(), ctx, project_id=None)) == ""
    ctx["intro"] = {"skipped": True, "text": "上次产物回显"}
    assert "场景" in asyncio.run(W._canvas_context(FakePool(), ctx, project_id=None))


def test_skipped_upstream_with_url_still_annotated():
    """skip 回显带图产物照样标进上文（2026-09-17 端到端实测）：上游「缺才跑」命中
    时 ctx 里是 skipped=True + url——旧判定把它当纯跳过扔了，参考图传了、上文却
    不写「图片1」，@图片N 的对应关系断了。带 url 的 skip 是真产物，要标注。"""
    wf = _wf([("start", "img"), ("img", "gen")],
             [("start", "start", "start"), ("img", "value", "参考图"),
              ("gen", "gen", "封面")])
    ctx = _ctx(wf, {"project_id": 25}, ["img"])
    # 缺才跑命中的回显形态：skipped + 上次产物 url
    ctx["img"] = {"skipped": True, "url": "https://oss/cat.png", "prompt": "一只小猫"}
    out = asyncio.run(W._canvas_context(FakePool(), ctx, project_id=None))
    assert "图片1「参考图」：已作为第 1 张参考图传入" in out, out


def test_image_upstream_annotated():
    """上游是图 → 标注「已作为参考图传入」，不把 url 塞进文本上文。"""
    wf = _wf([("start", "img"), ("img", "gen")],
             [("start", "start", "start"), ("img", "value", "参考图"),
              ("gen", "gen", "封面")])
    ctx = _ctx(wf, {"project_id": 25}, ["img"])
    ctx["img"] = {"url": "https://oss/x.jpg", "name": "参考"}
    out = asyncio.run(W._canvas_context(FakePool(), ctx, project_id=None))
    assert "图片1「参考图」：已作为第 1 张参考图传入" in out, out
    assert "https://oss/x.jpg" not in out, out


def test_no_upstream_no_project_empty():
    wf = _wf([], [("gen", "gen", "封面")])
    ctx = _ctx(wf, {}, [])
    assert asyncio.run(W._canvas_context(FakePool(), ctx, project_id=None)) == ""


def test_orphan_node_is_fully_independent():
    """无上游连线的孤岛节点 = 完全独立生成（2026-09-17 用户定稿）：
    入参、项目设定一概不注入——画布上从空白拖出的图片节点写「一只小猫」，
    出的就该是纯小猫，不被项目画风/标题/入参带偏。上下文严格跟连线走。"""
    wf = _wf([], [("gen", "gen", "小猫")])
    ctx = _ctx(wf, {"project_id": 25, "chapter": "第三章"}, [])
    out = asyncio.run(W._canvas_context(FakePool(), ctx, project_id=25))
    assert out == "", out
    # 手选参考但全删光（ref_nodes=[]）同样 = 独立生成
    ctx2 = _ctx(wf, {"project_id": 25}, [])
    assert asyncio.run(W._canvas_context(FakePool(), ctx2, project_id=25, only=True)) == ""
