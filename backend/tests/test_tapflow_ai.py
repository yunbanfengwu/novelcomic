"""Tapflow 智能化测试（2026-09-17）：智能添加挑选纪律 + 产物存储分发（2026-09-17）。"""
import asyncio
from unittest.mock import patch

import pytest

from backend.app.services import tapflow_ai


# ── 智能添加：宁缺毋滥 ────────────────────────────────────────────────────

class _FakePool:
    """只喂 smart_capabilities 要的两张表。"""

    def __init__(self, skills, folders):
        self._skills, self._folders = skills, folders

    async def fetch(self, sql, *args):
        if "skill_packages" in sql:
            return self._skills
        return self._folders


_S = [{"slug": "cover-poster", "name": "封面海报", "description": "海报构图方法"},
      {"slug": "storyboard", "name": "分镜", "description": "分镜规程"}]
_F = [{"id": 7, "title": "画风知识库"}]


def test_smart_capabilities_picks_and_filters():
    """模型返回的 value 全部做白名单校验：编造的 slug/工具名一律丢弃。"""
    async def fake_chat_json(system, user, **kw):
        assert "封面" in user  # charter 进了提示词
        return {"skills": ["cover-poster", "不存在的技能"], "kb": ["7", "99"],
                "tools": ["project.info", "瞎写的工具"], "reason": "封面需要项目信息"}
    with patch.object(tapflow_ai.llm, "chat_json", fake_chat_json):
        out = asyncio_run(tapflow_ai.smart_capabilities(
            _FakePool(_S, _F), charter="根据项目的基本信息和画风，生成封面图",
            current={"skills": [], "kb": [], "tools": []}))
    assert out["skills"] == ["cover-poster"]      # 编造的被滤掉
    assert out["kb"] == ["7"]
    assert out["tools"] == ["project.info"]       # 真实存在的工具名
    assert out["reason"] == "封面需要项目信息"


def test_smart_capabilities_none_is_fine():
    """没有合适能力 → 空清单也是合法结论，不报错不硬选。"""
    async def fake_chat_json(system, user, **kw):
        assert "宁缺毋滥" in system
        return {"skills": [], "kb": [], "tools": [], "reason": "没有合适的"}
    with patch.object(tapflow_ai.llm, "chat_json", fake_chat_json):
        out = asyncio_run(tapflow_ai.smart_capabilities(_FakePool(_S, _F), charter="画个图"))
    assert out == {"skills": [], "kb": [], "tools": [], "reason": "没有合适的"}


def test_smart_capabilities_model_down_returns_empty():
    """模型挂了 → 空清单 + 原因，绝不能把配置搞坏。"""
    async def boom(*a, **kw):
        raise RuntimeError("网关超时")
    with patch.object(tapflow_ai.llm, "chat_json", boom):
        out = asyncio_run(tapflow_ai.smart_capabilities(_FakePool(_S, _F), charter="x"))
    assert out["skills"] == [] and "网关超时" in out["reason"]


def test_readonly_tool_names_excludes_writers():
    names = tapflow_ai.readonly_tool_names()
    from backend.app.services import tools
    writers = {s["name"] for s in tools.specs() if s.get("writes")}
    assert names and not (set(names) & writers)


# ── 产物存储分发：绑定优先 / AI 规划兜底 / 失败不炸 ───────────────────────

class _StorePool:
    def __init__(self, config=None):
        self.config = config or {}
        self.saved = None

    async def fetchval(self, sql, *args):
        assert "config" in sql
        import json
        return json.dumps(self.config)

    async def execute(self, sql, *args):
        self.saved = args  # (config_json, project_id)


def test_apply_binding_target_cover():
    """end 声明 store.target=project_cover → 直接落 config.cover_url，不问模型。"""
    pool = _StorePool()
    out = asyncio_run(tapflow_ai.apply_end_binding(
        pool, project_id=5, outputs={"url": "https://oss/x.png", "prompt": "海报"},
        binding={"target": "project_cover"}))
    assert out["stored"] == "project_cover"
    import json
    conf = json.loads(pool.saved[0])
    assert conf["cover_url"] == "https://oss/x.png"
    assert conf["cover_prompt"] == "海报"
    assert pool.saved[1] == 5


def test_apply_binding_no_url_skips():
    out = asyncio_run(tapflow_ai.apply_end_binding(
        _StorePool(), project_id=5, outputs={"text": "没有图"},
        binding={"target": "project_cover"}))
    assert out["stored"] == "skipped"


def test_apply_ai_store_plans_save():
    """没绑定但 aiStore 开启：模型规划 save_project_cover → 落库。"""
    pool = _StorePool()

    async def fake_chat_json(system, user, **kw):
        assert "白名单" in system
        return {"action": "save_project_cover", "url": "https://oss/x.png"}
    with patch.object(tapflow_ai.llm, "chat_json", fake_chat_json):
        out = asyncio_run(tapflow_ai.apply_end_binding(
            pool, project_id=5, outputs={"url": "https://oss/x.png"}, auto_store=True))
    assert out["stored"] == "project_cover"


def test_apply_ai_store_plans_none():
    """模型判中间产物 → none，不落库。"""
    async def fake_chat_json(system, user, **kw):
        return {"action": "none", "reason": "中间产物"}
    with patch.object(tapflow_ai.llm, "chat_json", fake_chat_json):
        out = asyncio_run(tapflow_ai.apply_end_binding(
            _StorePool(), project_id=5, outputs={"url": "https://oss/tmp.png"},
            auto_store=True))
    assert out["stored"] == "none"


def test_apply_binding_never_raises():
    """存储链路炸了也只回 skipped——不能把一次成功的生成判成失败。"""
    class Bad:
        async def fetchval(self, *a):
            raise RuntimeError("db down")
    out = asyncio_run(tapflow_ai.apply_end_binding(
        Bad(), project_id=5, outputs={"url": "https://x/a.png"},
        binding={"target": "project_cover"}))
    assert out["stored"] == "skipped"


def test_pick_url_prefers_conventional_keys():
    assert tapflow_ai._pick_url({"image_url": "https://a/1.png", "x": "https://b/2.png"}) \
        == "https://a/1.png"
    assert tapflow_ai._pick_url({"whatever": "https://c/3.png"}) == "https://c/3.png"
    assert tapflow_ai._pick_url({"text": "没有"}) == ""


# ── run 收尾产物落库补漏：区间试跑没跑到 end，画布绑定照样生效 ──────────────

from app.services import workflow as _wf


def test_auto_store_saves_latest_gen_when_end_not_ranged():
    """单节点试跑（end 不在范围）+ 画布声明 store.target → 本次新产物按绑定落库。"""
    pool = _StorePool()
    ctx = {"__trace__": [
        {"node": "start", "type": "start", "outputs": {"project_id": 5}},
        {"node": "cover", "type": "gen", "outputs": {"url": "https://oss/old.png", "prompt": "旧"}},
        {"node": "try1", "type": "gen", "outputs": {"url": "https://oss/new.png", "prompt": "新"}},
    ]}
    wf = {"graph": {"nodes": [
        {"id": "start", "type": "start", "config": {}},
        {"id": "try1", "type": "gen", "config": {}},
        {"id": "store", "type": "end", "config": {"store": {"target": "project_cover"}}},
    ], "edges": [{"from": "try1", "to": "store"}]}}
    asyncio_run(_wf._auto_store_on_finish(pool, wf=wf, ctx=ctx, project_id=5, depth=0))
    assert pool.saved, "应该按绑定落库"
    import json
    assert json.loads(pool.saved[0])["cover_url"] == "https://oss/new.png"


def test_auto_store_skips_gen_not_reaching_end():
    """孤岛/支线节点产物不落库（2026-09-17 用户定稿）：store.target 是**最终产物**
    的归宿——只有沿连线能走到 end 的节点产物才配落库。随手拖出来的孤岛 gen
    （「一只小猫」）试跑出的图不连 end，只留在画布上，不许顶掉项目封面。"""
    pool = _StorePool()
    # 孤岛：产物节点没有任何出边
    wf = {"graph": {"nodes": [
        {"id": "cat", "type": "gen", "config": {}},
        {"id": "store", "type": "end", "config": {"store": {"target": "project_cover"}}},
    ], "edges": []}}
    ctx = {"__trace__": [{"node": "cat", "type": "gen",
                          "outputs": {"url": "https://oss/cat.png", "prompt": "一只小猫"}}]}
    asyncio_run(_wf._auto_store_on_finish(pool, wf=wf, ctx=ctx, project_id=5, depth=0))
    assert pool.saved is None, "孤岛节点产物不该落库"
    # 支线：产物只连到另一个中间节点，不连 end
    wf2 = {"graph": {"nodes": [
        {"id": "a", "type": "gen", "config": {}},
        {"id": "mid", "type": "llm", "config": {}},
        {"id": "store", "type": "end", "config": {"store": {"target": "project_cover"}}},
    ], "edges": [{"from": "a", "to": "mid"}]}}
    ctx2 = {"__trace__": [{"node": "a", "type": "gen", "outputs": {"url": "https://oss/y.png"}}]}
    asyncio_run(_wf._auto_store_on_finish(pool, wf=wf2, ctx=ctx2, project_id=5, depth=0))
    assert pool.saved is None, "不连通 end 的支线产物也不该落库"


def test_auto_store_skips_when_end_already_ran():
    """整图运行 end 已执行（end 分派里落过）→ 收尾不重复落。"""
    pool = _StorePool()
    ctx = {"__trace__": [{"node": "try1", "type": "gen", "outputs": {"url": "https://oss/x.png"}}],
           "store": {"url": "https://oss/x.png"}}
    wf = {"graph": {"nodes": [
        {"id": "store", "type": "end", "config": {"store": {"target": "project_cover"}}},
    ], "edges": []}}
    asyncio_run(_wf._auto_store_on_finish(pool, wf=wf, ctx=ctx, project_id=5, depth=0))
    assert pool.saved is None


def test_auto_store_ignores_skipped_and_subruns():
    """skip 命中的历史产物回显不是新生成；子运行（depth>0）不重复落。"""
    wf = {"graph": {"nodes": [
        {"id": "store", "type": "end", "config": {"store": {"target": "project_cover"}}},
    ], "edges": []}}
    pool = _StorePool()
    ctx = {"__trace__": [{"node": "cover", "type": "gen",
                          "outputs": {"url": "https://oss/old.png", "skipped": True}}]}
    asyncio_run(_wf._auto_store_on_finish(pool, wf=wf, ctx=ctx, project_id=5, depth=0))
    assert pool.saved is None
    ctx2 = {"__trace__": [{"node": "cover", "type": "gen", "outputs": {"url": "https://oss/x.png"}}]}
    asyncio_run(_wf._auto_store_on_finish(pool, wf=wf, ctx=ctx2, project_id=5, depth=1))
    assert pool.saved is None


def test_auto_store_requires_binding():
    """画布没声明 store.target → 收尾不落（自由画布产物就留在画布）。"""
    pool = _StorePool()
    wf = {"graph": {"nodes": [{"id": "end", "type": "end", "config": {}}], "edges": []}}
    ctx = {"__trace__": [{"node": "g", "type": "gen", "outputs": {"url": "https://oss/x.png"}}]}
    asyncio_run(_wf._auto_store_on_finish(pool, wf=wf, ctx=ctx, project_id=5, depth=0))
    assert pool.saved is None


# ── autoContext：写提示词的智能体默认带全量只读工具 + ctx 探索 ────────────

def test_write_prompt_auto_context_mounts_readonly_tools():
    """autoContext 开 → agent_runtime.run 收到只读工具全集与 flow_ctx；关 → 保持原样。"""
    from backend.app.services import workflow as wf

    captured = {}

    class _Pool:
        async def fetchval(self, sql, *args):
            return "novel_comic"  # art_style 查询

        async def fetchrow(self, sql, *args):
            return None  # knowledge.style_anchor 等查询：无风格行

        async def fetch(self, sql, *args):
            return []

    async def fake_run(pool, *, charter, task, skills, folder_ids, tool_names,
                       project_id, flow_ctx=None, caller="x", **kw):
        captured.update(tool_names=tool_names, flow_ctx=flow_ctx)
        return {"output": "一张封面", "steps": []}

    async def scenario():
        import backend.app.services.agent_runtime as ar_mod
        cfg_on = {"charter": "生成封面图", "autoContext": True, "tools": ["skill.read"]}
        with patch.object(ar_mod, "run", fake_run):
            await wf._write_prompt_by_charter(
                _Pool(), cfg_on, material="m", project_id=1, node_key="n1",
                flow_ctx={"n1": {"url": "x"}})
        assert "project.info" in captured["tool_names"]  # 只读全集已并入
        assert "skill.read" in captured["tool_names"]    # 手选工具保留
        assert captured["flow_ctx"] == {"n1": {"url": "x"}}
        # 关掉 autoContext：不带只读全集、不挂 ctx 探索（旧画布行为不变）
        captured.clear()
        cfg_off = {"charter": "生成封面图", "tools": ["skill.read"]}
        with patch.object(ar_mod, "run", fake_run):
            await wf._write_prompt_by_charter(
                _Pool(), cfg_off, material="m", project_id=1, node_key="n1")
        assert "project.info" not in captured["tool_names"]
        assert captured["flow_ctx"] is None

    asyncio_run(scenario())


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)
