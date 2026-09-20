import asyncio
from unittest.mock import patch

from app.services import tools, workflow_actions
from app.services.workflow import _already_done, _run_loop_node, _run_node


def test_related_element_tools_publish_loop_item_contracts():
    for name in ("asset.route_related_elements", "asset.resolve_generation_source"):
        spec = next(item for item in tools.specs() if item["name"] == name)
        descriptors = spec["outputs"]["descriptors"]
        assert descriptors["type"] == "array"
        assert set(descriptors["items"]["properties"]) >= {
            "asset_type", "target_ref", "element_id", "name", "prompt",
        }
    assert next(item for item in tools.specs() if item["name"] == "asset.resolve_source")["params"]["source"]["type"] == "object"


def test_condition_node_publishes_selected_source_contract():
    async def fake_row(*_args, **_kwargs):
        return 101

    async def fake_finish(*_args, **_kwargs):
        return None

    node = {"id": "source_select", "type": "condition", "config": {
        "when": {"value": "{{input.prompt_text}}", "operator": "truthy"},
        "then": {"kind": "prompt_matches", "prompt_text": "{{input.prompt_text}}"},
        "else": {"kind": "related_elements", "source_ref": "{{input.target_ref}}"},
    }}
    wf = {"graph": {"nodes": [node], "edges": []}}

    with patch("app.services.workflow._node_run_row", new=fake_row), \
         patch("app.services.workflow._finish_node", new=fake_finish):
        matched = asyncio.run(_run_node(object(), node,
            ctx={"__inputs__": {"prompt_text": "A frame", "target_ref": "element:8"}},
            run_id=1, wf=wf, project_id=25, node_id=None, depth=0))
        fallback = asyncio.run(_run_node(object(), node,
            ctx={"__inputs__": {"prompt_text": "", "target_ref": "element:8"}},
            run_id=1, wf=wf, project_id=25, node_id=None, depth=0))

    assert matched == {"matched": True, "value": {"kind": "prompt_matches", "prompt_text": "A frame"}, "actual": "A frame"}
    assert fallback == {"matched": False, "value": {"kind": "related_elements", "source_ref": "element:8"}, "actual": ""}


def test_generation_source_material_kind_limits_descriptor_route():
    seen = {}

    async def fake_route(_pool, **kwargs):
        seen.update(kwargs)
        return {"descriptors": [], "scene_items": [], "common_image_items": []}

    with patch("app.services.workflow_actions.asset_route_related_elements", new=fake_route):
        result = asyncio.run(workflow_actions.asset_resolve_generation_source(
            object(), project_id=25, source_type="explicit.element_ids",
            related_element_ids=[8, 9], material_kind="scene"))

    assert seen["element_ids"] == [8, 9]
    assert seen["kinds"] == ["scene"]
    assert result["filters"] == {"kinds": ["scene"]}


def test_every_system_tool_exposes_input_and_output_contract_maps():
    specs = tools.specs()
    assert specs
    assert all(isinstance(spec["params"], dict) for spec in specs)
    assert all(isinstance(spec["outputs"], dict) for spec in specs)


def test_canvas_prepare_context_collects_prompt_and_typed_upstream_media():
    result = asyncio.run(workflow_actions.canvas_prepare_context(
        object(),
        project_id=25,
        purpose="shot_video",
        _ctx={
            "__inputs__": {
                "prompt": "make the cat scene shorter",
                "ref_url": "https://cdn/input-ref.png",
            },
            "__in__": ["upstream"],
            "upstream": {
                "prompt": "the existing cat eating script",
                "reference_images": [
                    {"kind": "first_frame", "url": "https://cdn/first.png"},
                    {"kind": "last_frame", "url": "https://cdn/last.png"},
                ],
            },
        },
    ))

    assert result["prompt"] == "the existing cat eating script"
    assert result["first_frame_url"] == "https://cdn/first.png"
    assert result["last_frame_url"] == "https://cdn/last.png"
    assert {item["url"] for item in result["reference_images"]} == {
        "https://cdn/first.png", "https://cdn/last.png", "https://cdn/input-ref.png",
    }
    assert result["ready"] is True
    assert workflow_actions.spec("canvas.prepare_context")["wants_ctx"] is True


def test_canvas_prepare_migration_covers_all_production_canvas_entrypoints():
    import re

    migration = (
        __import__("pathlib").Path(__file__).parents[1] / "sql" /
        "106_canvas_prepare_nodes.sql"
    ).read_text(encoding="utf-8")
    for slug in (
        "asset-image-canvas", "asset-video-canvas", "project-trailer-canvas",
        "scene-group-canvas", "shot-keyframe-canvas", "shot-video-canvas",
        "shot-lastframe-canvas", "storyboard-grid-canvas", "batch-keyframe-canvas",
        "scene-sheet-canvas", "core-element-image-generation",
        "nine-grid-keyframe-reference", "project-poster-canvas",
    ):
        assert slug in migration
    assert "canvas.prepare_context" in migration
    assert "project_visual.prepare" in migration
    assert "project_visual.generate" in migration
    calls = dict(re.findall(
        r"SELECT append_canvas_prepare_node\('([^']+)',\s*'([^']+)',",
        migration,
    ))
    assert calls == {
        "asset-image-canvas": "gen",
        "asset-video-canvas": "gen",
        "project-trailer-canvas": "gen",
        "scene-group-canvas": "gen_empty",
        "shot-keyframe-canvas": "context",
        "shot-video-canvas": "ensure_keyframe",
        "shot-lastframe-canvas": "context",
        "storyboard-grid-canvas": "gen",
        "batch-keyframe-canvas": "plan",
        "scene-sheet-canvas": "ensure",
        "core-element-image-generation": "info",
    }
    assert "storyboard_nine_grid" in migration


def test_project_visual_generate_action_normalizes_reference_records():
    async def fake_generate(_pool, project_id, role, prompt, reference_urls):
        assert project_id == 25
        assert role == "project_cover_poster"
        assert prompt == "a poster"
        assert reference_urls == ["https://cdn/anchor.png"]
        return {"url": "https://cdn/poster.png", "prompt": prompt,
                "meta": {"reference_urls": reference_urls}}

    with patch("app.services.project_visual_assets.generate", new=fake_generate):
        result = asyncio.run(workflow_actions.project_visual_generate(
            object(), project_id=25, prompt="a poster",
            reference_urls=[{"kind": "project_anchor", "url": "https://cdn/anchor.png"}],
        ))

    assert result["image_url"] == "https://cdn/poster.png"
    assert result["reference_images"] == ["https://cdn/anchor.png"]


def test_frame_element_tool_returns_only_closed_world_visual_matches():
    class Pool:
        async def fetch(self, _query, *_args):
            return [
                {"id": 8, "kind": "character", "name": "A"},
                {"id": 9, "kind": "scene", "name": "B"},
            ]

        async def fetchrow(self, *_args, **_kwargs):
            return None

    async def fake_vision(_system, user, image_url, **_kwargs):
        assert "id=8" in user and "id=9" in user
        assert image_url == "https://asset/keyframe.png"
        return {"matches": [
            {"element_id": 8, "confidence": 0.92, "evidence": "visible"},
            {"element_id": 999, "confidence": 1.0, "evidence": "invented"},
            {"element_id": 9, "confidence": 0.2, "evidence": "below threshold"},
        ]}

    async def fake_read_latest(*_args, **_kwargs):
        return None

    with patch("app.assets.read_latest", new=fake_read_latest), \
         patch("app.llm.chat_vision_json", new=fake_vision):
        result = asyncio.run(workflow_actions.asset_resolve_frame_elements(
            Pool(), project_id=25, image_url="https://asset/keyframe.png",
            candidate_element_ids=[8, 9], min_confidence=0.55))

    assert result["element_ids"] == [8]
    assert [item["element_id"] for item in result["descriptors"]] == [8]
    assert result["matches"][0]["confidence"] == 0.92
    assert [item["element_id"] for item in result["candidate_items"]] == [8, 9]


def test_prompt_element_tool_returns_only_canonical_names_present_in_prompt():
    async def fake_source(*_args, **_kwargs):
        return {
            "source_ref": "content_node:1146",
            "descriptors": [
                {"element_id": 8, "element_kind": "character", "name": "阿砚",
                 "asset_type": "com.image", "target_ref": "element:8"},
                {"element_id": 9, "element_kind": "scene", "name": "浮空灯塔",
                 "asset_type": "pro.scene.sheet", "target_ref": "element:9"},
                {"element_id": 10, "element_kind": "prop", "name": "龙翼晶纹",
                 "asset_type": "com.image", "target_ref": "element:10"},
            ],
        }

    with patch("app.services.workflow_actions.asset_resolve_generation_source", new=fake_source):
        result = asyncio.run(workflow_actions.asset_resolve_prompt_elements(
            object(), project_id=25,
            prompt_text="阿砚站在浮空灯塔入口，远望雷云。",
            candidate_source_type="shot.dynamic_elements",
            candidate_source_ref="content_node:1146"))

    assert result["element_ids"] == [8, 9]
    assert [item["name"] for item in result["descriptors"]] == ["阿砚", "浮空灯塔"]
    assert [item["name"] for item in result["candidate_items"]] == ["阿砚", "浮空灯塔", "龙翼晶纹"]


def test_prompt_element_tool_passes_candidate_scope_when_prompt_is_absent():
    async def fake_source(*_args, **_kwargs):
        return {
            "source_ref": "content_node:1146",
            "descriptors": [
                {"element_id": 8, "element_kind": "character", "name": "阿砚"},
                {"element_id": 9, "element_kind": "scene", "name": "浮空灯塔"},
            ],
        }

    with patch("app.services.workflow_actions.asset_resolve_generation_source", new=fake_source):
        result = asyncio.run(workflow_actions.asset_resolve_prompt_elements(
            object(), project_id=25, candidate_element_ids=[8, 9]))

    assert result["element_ids"] == [8, 9]
    assert [item["element_id"] for item in result["descriptors"]] == [8, 9]


def test_keyframe_moves_prompt_element_tool_inside_multi_element_subflow():
    from pathlib import Path

    root = Path(__file__).parents[1] / "sql"
    sql = (root / "85_workflow_shot_keyframe_frame_elements.sql") \
        .read_text(encoding="utf-8")
    child_sql = (root / "80_multi_element_smart_generation_canvas.sql").read_text(encoding="utf-8")
    assert '"name":"asset.resolve_prompt_elements"' not in sql
    assert '"name":"asset.resolve_prompt_elements"' in child_sql
    assert '"from":"start","to":"prompt_elements"' in child_sql
    assert '"related_element_ids":"{{prompt_elements.element_ids}}"' in child_sql
    assert '"material_kind":"{{input.material_kind}}"' in child_sql
    assert '"slug":"multi-element-smart-generation"' in sql
    assert '"prompt_text":"{{prompt.text}}"' in sql
    assert '"source_type":"shot.dynamic_elements"' in sql
    assert '"from":"prompt","to":"dynamic_assets"' in sql
    assert '"from":"dynamic_assets","to":"gen","mapping":"collect"' in sql
    assert '"from":"gen","to":"end"' in sql
    assert '"name":"asset.resolve_frame_elements"' not in sql
    assert "meta->>'image_prompt'" in sql


def test_source_condition_binds_the_four_keyframe_nodes_without_legacy_source_fields():
    from pathlib import Path

    root = Path(__file__).parents[1] / "sql"
    sql = (root / "87_workflow_source_condition.sql").read_text(encoding="utf-8")
    assert '"type":"condition"' in sql
    assert '"name":"asset.resolve_source"' in sql
    assert '"source":"{{source_select.value}}"' in sql
    assert "'prompt_text', '{{prompt.text}}'" in sql
    assert "'source_ref', '{{input.target_ref}}'" in sql
    assert "'shot_id', '{{input.shot_id}}'" in sql
    assert '"source":"{{resolve_source.descriptors}}"' in sql


def test_parent_asset_type_does_not_satisfy_intermediate_prompt_node():
    class Pool:
        async def fetchrow(self, *_args, **_kwargs):
            raise AssertionError("intermediate prompt must not query workflow artifacts")

        async def fetchval(self, query, *_args):
            assert "image_prompt" in query
            return "阿砚站在黄昏港口"

    ctx = {"__inputs__": {
        "project_id": 25,
        "asset_type": "pro.shot.keyframe",
        "target_ref": "content_node:819",
        "shot_id": 819,
    }}
    cfg = {"skip_if": {
        "sql": "SELECT meta->>'image_prompt' FROM content_nodes WHERE id=$1",
        "args": ["{{input.shot_id}}"],
        "reason": "reuse prompt",
    }}

    done, reason, value = asyncio.run(_already_done(Pool(), cfg, ctx))

    assert done is True
    assert reason == "reuse prompt"
    assert value == "阿砚站在黄昏港口"


def test_parent_asset_type_does_not_skip_subflow_without_own_asset_contract():
    class Pool:
        async def fetchrow(self, *_args, **_kwargs):
            raise AssertionError("subflow must not inherit the parent's final asset lookup")

        async def fetchval(self, *_args, **_kwargs):
            raise AssertionError("subflow has no explicit skip query")

    ctx = {"__inputs__": {
        "project_id": 25,
        "asset_type": "pro.shot.keyframe",
        "target_ref": "content_node:819",
    }}

    assert asyncio.run(_already_done(Pool(), {"slug": "child"}, ctx)) == (False, "", None)


def test_tapflow_tool_node_uses_central_tool_invocation_and_upstream_mapping():
    calls = []

    async def fake_invoke(_pool, name, args, **meta):
        calls.append((name, args, meta))
        return {"descriptors": [{"target_ref": "element:8"}]}

    async def fake_row(*_args, **_kwargs):
        return 101

    async def fake_finish(*_args, **_kwargs):
        return None

    node = {"id": "route", "type": "action", "config": {
        "name": "asset.route_related_elements",
        "args": {"project_id": "{{input.project_id}}", "element_ids": "{{pick.ids}}"},
        "ui": {"tap": "tool"},
    }}
    ctx = {"__inputs__": {"project_id": 25}, "pick": {"ids": [8]}}
    wf = {"graph": {"nodes": [node], "edges": []}}

    with patch("app.services.tools.invoke", new=fake_invoke), \
         patch("app.services.workflow._node_run_row", new=fake_row), \
         patch("app.services.workflow._finish_node", new=fake_finish):
        result = asyncio.run(_run_node(
            object(), node, ctx=ctx, run_id=1, wf=wf, project_id=25,
            node_id=None, depth=0))

    assert result["descriptors"][0]["target_ref"] == "element:8"
    assert calls == [("asset.route_related_elements", {"project_id": 25, "element_ids": [8]}, {
        "caller": "workflow", "source": "workflow", "project_id": 25,
    })]


def test_loop_body_tool_can_read_current_item_fields():
    seen = []

    async def fake_invoke(_pool, name, args, **_meta):
        seen.append((name, args))
        return {"ok": True, "element_ids": args["element_ids"]}

    async def fake_row(*_args, **_kwargs):
        return 202

    async def fake_finish(*_args, **_kwargs):
        return None

    loop = {"id": "each", "type": "loop", "config": {
        "source": "{{route.descriptors}}", "body": ["consume"], "concurrency": 2,
    }}
    consume = {"id": "consume", "type": "action", "config": {
        "name": "asset.route_related_elements",
        "args": {"project_id": "{{input.project_id}}", "element_ids": ["{{__item__.element_id}}"]},
        "ui": {"tap": "tool"},
    }}
    ctx = {
        "__inputs__": {"project_id": 25},
        "route": {"descriptors": [{"element_id": 8}, {"element_id": 9}]},
    }
    graph = {"nodes": [loop, consume], "edges": [{"from": "loop", "to": "consume", "mapping": "each"}]}

    # Use a registered function name so _run_node's registry guard remains active;
    # execution itself is patched at the centralized tool boundary.
    assert workflow_actions.get("asset.route_related_elements") is not None
    with patch("app.services.tools.invoke", new=fake_invoke), \
         patch("app.services.workflow._node_run_row", new=fake_row), \
         patch("app.services.workflow._finish_node", new=fake_finish):
        result = asyncio.run(_run_loop_node(
            object(), loop, ctx=ctx, run_id=1, wf={"graph": graph},
            project_id=25, node_id=None, depth=0))

    assert result["count"] == 2
    assert result["failed"] == 0
    assert sorted(args["element_ids"][0] for _, args in seen) == [8, 9]
