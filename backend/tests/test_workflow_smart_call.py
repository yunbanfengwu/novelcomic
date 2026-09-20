import asyncio
import json
from unittest.mock import patch

from app.services import workflow, workflow_planner
from app.services.workflow import _resolve, _run_node, _run_subflow_node


def _noop_pool():
    return object()


async def _fake_row(*_args, **kwargs):
    ctx = kwargs.get("ctx")
    if ctx is not None:
        # 与真实实现同样把入参写进 ctx——测的是「入参可被下游引用」这条契约
        ctx.setdefault("__node_inputs__", {})[_args[2]] = _args[4]
    return 1


async def _fake_finish(*_args, **_kwargs):
    return None


# ── 运行上下文 ─────────────────────────────────────────────────────────

def test_ctx_exposes_node_inputs_and_whole_trace():
    ctx = {
        "__inputs__": {"project_id": 7},
        "__node_inputs__": {"draft": {"kind": "gen_scene", "payload": {"seed": 3}}},
        "__trace__": [{"node": "draft", "outputs": {"url": "u"}}],
    }
    assert _resolve("{{inputs.draft.payload.seed}}", ctx) == 3
    assert _resolve("{{inputs.draft.kind}}", ctx) == "gen_scene"
    assert _resolve("{{ctx}}", ctx) == ctx["__trace__"]
    # {{ctx.节点.字段}} 与 {{节点.字段}} 必须同解，否则就是第二份取值实现
    ctx["draft"] = {"url": "u"}
    assert _resolve("{{ctx.draft.url}}", ctx) == _resolve("{{draft.url}}", ctx) == "u"


def test_every_node_appends_one_trace_entry_with_inputs_and_outputs():
    node = {"id": "pick", "type": "value",
            "config": {"value": {"text": "{{input.topic}}"}, "ui": {"title": "选题"}}}
    wf = {"graph": {"nodes": [node], "edges": []}}
    ctx = {"__inputs__": {"topic": "雨夜"}, "__trace__": [], "__node_inputs__": {}}
    with patch("app.services.workflow._node_run_row", new=_fake_row), \
         patch("app.services.workflow._finish_node", new=_fake_finish):
        out = asyncio.run(_run_node(_noop_pool(), node, ctx=ctx, run_id=1, wf=wf,
                                    project_id=1, node_id=None, depth=0))
    assert out == {"text": "雨夜"}
    assert len(ctx["__trace__"]) == 1
    entry = ctx["__trace__"][0]
    assert entry["node"] == "pick" and entry["title"] == "选题"
    assert entry["outputs"] == {"text": "雨夜"}


def test_trace_value_truncates_long_text_and_long_lists():
    digest = workflow._trace_value({"prompt": "字" * 900, "refs": [{"url": str(i)} for i in range(40)]})
    assert digest["prompt"].endswith("（共 900 字）")
    assert len(digest["refs"]) == 11 and "另有 30 项" in digest["refs"][-1]
    # 轨迹要能直接落 jsonb / 进模型上下文
    assert json.loads(json.dumps(digest, ensure_ascii=False))


def test_instruction_fills_placeholders_embedded_in_a_sentence():
    """gen 节点的 instruction 是句子，占位符嵌在中间。

    `_resolve` 只认「整串就是一个占位符」，句子里的原样返回——于是 `{{input.grid_prompt}}`
    会一路进到出图提示词里（实测：画布生成条里显示的就是这串字面量）。
    """
    ctx = {"__inputs__": {"grid_prompt": "1 主角推门；2 特写手掌"}}
    filled = workflow._instruction(
        {"instruction": "画一张故事板九宫格：{{input.grid_prompt}}。不要文字水印"}, ctx)
    assert filled == "画一张故事板九宫格：1 主角推门；2 特写手掌。不要文字水印"
    assert "{{" not in filled


def test_whole_string_placeholder_keeps_its_original_value():
    """循环体里 `instruction: "{{__item__.prompt}}"` 要拿到那一项的值，不能被字符串化。"""
    ctx = {"__item__": {"prompt": "为要素「岚音」生成概念图"}}
    assert workflow._instruction({"instruction": "{{__item__.prompt}}"}, ctx) \
        == "为要素「岚音」生成概念图"
    assert workflow._instruction({"instruction": "直白的一句话"}, ctx) == "直白的一句话"
    assert workflow._instruction({}, ctx) is None


# ── 智能调用规划 ───────────────────────────────────────────────────────

NODES = [
    {"id": "brief", "type": "llm", "title": "写简介", "exists": True, "upstream": []},
    {"id": "sheet", "type": "gen", "title": "设定图", "exists": True, "upstream": ["brief"]},
    {"id": "frame", "type": "gen", "title": "关键帧", "exists": False, "upstream": ["sheet"]},
]


def _plan(reply: str, prompt: str = "把关键帧换成雨夜"):
    async def fake_describe(*_a, **_k):
        return NODES

    async def fake_run(*_a, **_k):
        return {"output": reply}

    with patch("app.services.workflow_planner.describe", new=fake_describe), \
         patch("app.services.agent_runtime.run", new=fake_run):
        return asyncio.run(workflow_planner.plan(
            _noop_pool(), slug="child", version=1, prompt=prompt, inputs={"project_id": 1}))


def test_plan_turns_model_verdicts_into_force_and_overrides():
    out = _plan(json.dumps({"nodes": [
        {"id": "brief", "action": "reuse"},
        {"id": "sheet", "action": "reuse"},
        {"id": "frame", "action": "generate", "instruction": "雨夜、湿地面反光"},
    ], "reason": "只有关键帧受影响"}, ensure_ascii=False))
    assert out["force"] == ["frame"]
    assert out["overrides"] == {"frame": {"instruction": "雨夜、湿地面反光"}}
    assert not out.get("degraded")


def test_plan_always_regenerates_nodes_without_products():
    # 模型说 frame 复用，但它根本没有产物——硬规则必须兜住，否则子图跑完还是空的
    out = _plan(json.dumps({"nodes": [{"id": n["id"], "action": "reuse"} for n in NODES]}))
    assert out["force"] == ["frame"]


def test_plan_does_not_treat_unprobeable_loop_body_as_missing():
    """循环体节点探不出产物（exists=None）。把「不确定」当「没有」，等于每次全量重跑。"""
    async def fake_describe(*_a, **_k):
        return [{"id": "scene_sheet", "type": "subflow", "title": "场景设定图",
                 "exists": None, "per_item": True, "upstream": ["route_loop"]},
                {"id": "common_image", "type": "gen", "title": "通用素材图",
                 "exists": None, "per_item": True, "upstream": ["route_loop"]}]

    async def fake_run(*_a, **_k):
        return {"output": json.dumps({"nodes": [
            {"id": "scene_sheet", "action": "generate"},
            {"id": "common_image", "action": "reuse"}]})}

    with patch("app.services.workflow_planner.describe", new=fake_describe), \
         patch("app.services.agent_runtime.run", new=fake_run):
        out = asyncio.run(workflow_planner.plan(
            _noop_pool(), slug="child", version=1, prompt="只重做场景设定图",
            inputs={"project_id": 1}))
    assert out["force"] == ["scene_sheet"]


def test_plan_drops_instructions_that_echo_config_placeholders():
    """模型实测会把节点配置里的 `{{__item__.prompt}}` 当「额外要求」抄回来。
    覆盖层不解析占位符，放行就等于把这串字面量画进图里。"""
    out = _plan(json.dumps({"nodes": [
        {"id": "frame", "action": "generate", "instruction": "{{__item__.prompt}}"},
        {"id": "sheet", "action": "generate", "instruction": "改成雨夜"},
    ]}))
    assert "frame" not in out["overrides"]
    assert out["overrides"]["sheet"] == {"instruction": "改成雨夜"}


def test_plan_tolerates_fenced_json_and_chatter():
    out = _plan('好的：\n```json\n{"nodes":[{"id":"sheet","action":"generate"}]}\n```')
    assert set(out["force"]) == {"sheet", "frame"}


def test_plan_degrades_to_full_rerun_when_model_unusable():
    out = _plan("我不知道该怎么排")
    assert out["degraded"]
    assert out["force"] == [n["id"] for n in NODES]


def test_plan_without_prompt_only_fills_missing_products():
    out = _plan("", prompt="  ")
    assert out["force"] == ["frame"] and not out.get("degraded")


def test_forced_regeneration_reports_this_runs_product_not_the_previous_one():
    """强制重跑时，节点产物必须是**本次**跑出来的那张。

    探库返回「此刻库里最新的一条」，而本次产物要等 provenance 落库才进得去——
    先探库就会报出上一版 url（实测 run 376：图重出了，节点与 artifacts 却记旧图）。
    """
    fresh = "https://cdn/93d65353.png"
    stale = "https://cdn/c3475355.png"
    assert workflow._produced_url({"url": fresh}, stale) == fresh
    # 没有 skip_if / 资产槽位的自由节点探不到东西，只能靠任务结果
    assert workflow._produced_url({"url": fresh}, None) == fresh
    # 反过来，Step 没在 result 里回 url 时，探库那份仍要兜住
    assert workflow._produced_url({}, stale) == stale


# ── 引擎接线 ───────────────────────────────────────────────────────────

def _run_subflow(smart_call: bool, plan_result: dict, forced: bool = True,
                 overrides: dict | None = None):
    node = {"id": "child_ref", "type": "subflow",
            "config": {"slug": "child", "version": 1, "inputs": {"project_id": "{{input.project_id}}"}}}
    ctx = {"__inputs__": {"project_id": 9}, "__trace__": [], "__node_inputs__": {},
           "__overrides__": overrides if overrides is not None
           else {"child_ref": {"instruction": "把关键帧换成雨夜"}}}
    seen: dict = {}

    async def fake_load(_pool, slug, version=None):
        return {"id": 5, "slug": slug, "version": 1, "smart_call": smart_call, "graph": {}}

    async def fake_plan(*_a, **kwargs):
        seen["prompt"] = kwargs.get("prompt")
        return plan_result

    async def fake_run_workflow(*_a, **kwargs):
        seen["force"] = set(kwargs["force"])
        seen["overrides"] = kwargs["overrides"]
        return {"url": "child.png"}

    class _Pool:
        async def fetchval(self, *_a, **_k):
            return 77

        async def execute(self, *_a, **_k):
            return "UPDATE 1"

    with patch("app.services.workflow._node_run_row", new=_fake_row), \
         patch("app.services.workflow._finish_node", new=_fake_finish), \
         patch("app.services.workflow.load_workflow", new=fake_load), \
         patch("app.services.workflow_planner.plan", new=fake_plan), \
         patch("app.services.workflow.run_workflow", new=fake_run_workflow):
        out = asyncio.run(_run_subflow_node(
            _Pool(), node, ctx=ctx, run_id=1, project_id=9, node_id=None, depth=0,
            force=frozenset({"child_ref"} if forced else set())))
    return out, seen


def test_smart_subflow_reruns_only_the_planned_child_nodes():
    out, seen = _run_subflow(True, {"force": ["frame"], "overrides": {"frame": {"instruction": "雨夜"}},
                                    "reason": "只有关键帧受影响"})
    # 关键：不再是 FORCE_ALL（整图重跑），只重跑规划点名的那个节点
    assert seen["force"] == {"frame"}
    assert seen["overrides"]["frame"]["instruction"] == "雨夜"
    assert out["smart_plan"]["force"] == ["frame"]


def test_non_smart_subflow_keeps_the_whole_child_rerun_semantics():
    _out, seen = _run_subflow(False, {"force": ["frame"], "overrides": {}})
    assert seen["force"] == {workflow.FORCE_ALL}


def test_instruction_reaches_a_nested_subflow_through_the_wildcard_key():
    """内外层节点天然不同名，用户那句话在第二层只挂在通配键上——取不到就断了。"""
    _out, seen = _run_subflow(
        True, {"force": ["frame"], "overrides": {}},
        overrides={workflow.FORCE_ALL: {"instruction": "把关键帧换成雨夜"}})
    assert seen["prompt"] == "把关键帧换成雨夜"


def test_prompt_key_also_reaches_the_planner_for_flow_cards_drawn_as_gen():
    """画布把引用节点画成 gen 卡时，生成条发的是 prompt 而不是 instruction。"""
    _out, seen = _run_subflow(
        True, {"force": ["frame"], "overrides": {}},
        overrides={"child_ref": {"prompt": "只重做场景设定图"}})
    assert seen["prompt"] == "只重做场景设定图"


def test_degraded_plan_falls_back_to_whole_child_rerun():
    out, seen = _run_subflow(True, {"force": [], "overrides": {}, "degraded": "模型不可用"})
    assert seen["force"] == {workflow.FORCE_ALL}
    assert out["smart_plan"]["degraded"] == "模型不可用"
