import asyncio
from unittest.mock import patch

from app.assets import all_types, get, legacy_type, read_latest
from app.assets.reader import _legacy_value
from app.services.canonical_inputs import (
    CanonicalInputError, SmartInputSelection, resolve_canonical_inputs,
)
from app.services.workflow import (
    WorkflowError, _apply_asset_input_contract, _apply_asset_type_contract,
    _already_done, _artifact_inputs, _record_artifact_provenance, _resolve_asset_target,
    _run_gen_node, _run_if_matches, _run_subflow_node, output_cardinality,
)


def test_registry_uses_exact_codes_not_code_segment_count():
    # The registry must not infer behaviour by splitting a code on dots.
    assert get("com.image").media_kind == "image"
    assert get("pro.scene.sheet").subject_kind == "element"
    assert get("pro.shot.keyframe").subject_kind == "content_node"


def test_registry_rejects_unregistered_codes():
    try:
        get("pro.scene.sheet.extra")
    except ValueError as exc:
        assert "Unknown asset type" in str(exc)
    else:
        raise AssertionError("An unregistered code must not be inferred from its prefix")


def test_legacy_output_roles_map_to_asset_types():
    assert legacy_type("scene.sheet", "element") == "pro.scene.sheet"
    assert legacy_type("shot.keyframe", "content_node") == "pro.shot.keyframe"
    assert legacy_type("not-a-type", "element") is None


def test_all_registered_types_have_unique_nonempty_codes():
    codes = [item.code for item in all_types()]
    assert all(codes)
    assert len(codes) == len(set(codes))


def test_media_kind_and_business_tags_are_independent():
    scene_sheet = get("pro.scene.sheet")
    assert scene_sheet.media_kind == "image"
    assert scene_sheet.tags == ("project", "scene", "sheet", "design")
    assert scene_sheet.tags[0] != scene_sheet.media_kind


def test_fixed_canvas_type_is_injected_and_cannot_be_overridden():
    workflow = {"slug": "scene-sheet-canvas", "graph": {"nodes": [
        {"id": "gen", "type": "gen", "config": {"asset_type": "pro.scene.sheet"}},
    ]}}
    assert _apply_asset_type_contract(workflow, {"project_id": 25})["asset_type"] == "pro.scene.sheet"
    try:
        _apply_asset_type_contract(workflow, {"asset_type": "com.image"})
    except WorkflowError as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("a canvas contract must not be changed by run inputs")


def test_multi_output_canvas_does_not_have_a_ambiguous_top_level_type():
    workflow = {"slug": "multi", "graph": {"asset_types": ["pro.scene.sheet", "com.image"], "nodes": [
        {"id": "scene", "type": "subflow", "config": {"asset_type": "pro.scene.sheet"}},
        {"id": "common", "type": "gen", "config": {"asset_type": "com.image"}},
    ]}}
    assert "asset_type" not in _apply_asset_type_contract(workflow, {"asset_type": "com.image"})


def test_asset_contract_projects_smart_parameters_into_canvas_schema():
    workflow = {"slug": "scene", "input_schema": {"project_id": {"required": True}},
                "graph": {"nodes": [{"id": "gen", "type": "gen",
                                      "config": {"asset_type": "pro.scene.sheet"}}]}}
    _apply_asset_input_contract(workflow)
    assert workflow["input_schema"]["asset_type"]["allowed_values"] == ["pro.scene.sheet"]
    assert workflow["input_schema"]["target_ref"]["resource_kinds"] == ["element:scene"]
    assert workflow["input_schema"]["target_ref"]["required"] is True
    assert get("pro.shot.keyframe").target_scope_levels == (
        ("volume", "卷", False), ("chapter", "章", False))


class _TargetPool:
    async def fetchrow(self, sql, target_id):
        if "content_elements" in sql and target_id == 265:
            return {"id": 265, "kind": "scene", "parent_id": None,
                    "project_id": 25, "name": "废弃仓库"}
        if "content_nodes" in sql and target_id == 819:
            return {"id": 819, "kind": "shot", "parent_id": 777,
                    "project_id": 25, "name": "分镜 1"}
        return None


def test_asset_target_resolves_legacy_context_from_contract():
    scene = asyncio.run(_resolve_asset_target(
        _TargetPool(), {"project_id": 25, "asset_type": "pro.scene.sheet",
                        "target_ref": "element:265"}))
    assert (scene["element_id"], scene["scene_name"]) == (265, "废弃仓库")
    shot = asyncio.run(_resolve_asset_target(
        _TargetPool(), {"project_id": 25, "asset_type": "pro.shot.keyframe",
                        "target_ref": "content_node:819"}))
    assert (shot["shot_id"], shot["chapter_id"]) == (819, 777)


class _CanonicalPool:
    nodes = {
        791: {"id": 791, "project_id": 25, "parent_id": None,
              "kind": "chapter", "title": "雷云层中的考验"},
        1146: {"id": 1146, "project_id": 25, "parent_id": 791,
               "kind": "shot", "title": "镜头13"},
    }

    async def fetchrow(self, sql, ident):
        if "FROM content_nodes" in sql:
            return self.nodes.get(ident)
        if "FROM content_elements" in sql and ident == 266:
            return {"id": 266, "project_id": 25, "kind": "scene", "name": "浮空灯塔",
                    "meta": {"sheet_url": "https://cdn/scene.png"}}
        if "FROM content_projects" in sql and ident == 25:
            return {"id": 25, "title": "北境灯塔"}
        return None


def test_canonical_inputs_reverse_resolve_and_match_workflow_schema():
    canonical = asyncio.run(resolve_canonical_inputs(_CanonicalPool(), SmartInputSelection(
        asset_type="pro.scene.sheet", chapter_id=791, material_ref="element:266")))
    matched = canonical.match({
        "project_id": {"type": "int"}, "asset_type": {"type": "asset_type"},
        "chapter_id": {"type": "int"}, "target_ref": {"type": "resource"},
        "material_kind": {"type": "string"},
        "scene_name": {"type": "string"}, "variant_id": {"type": "string"},
    })
    assert matched == {
        "project_id": "25 · 北境灯塔",
        "asset_type": "pro.scene.sheet",
        "chapter_id": "791 · 雷云层中的考验",
        "target_ref": "element:266 · 浮空灯塔",
        "material_kind": "scene",
        "scene_name": "浮空灯塔",
    }
    assert canonical.labels({
        "project_id": {}, "target_ref": {}, "variant_id": {},
        "scene_name": {}, "hidden": {"ui": {"hide": True}},
    }) == {
        "project_id": "项目", "target_ref": "关联对象", "scene_name": "场景名称",
    }
    parameters = {item["key"]: item for item in canonical.parameters()}
    assert parameters["project_id"]["label_zh"] == "项目"
    assert parameters["target_ref"]["label_zh"] == "关联对象"


def test_canonical_inputs_accept_material_kind_before_material_is_selected():
    canonical = asyncio.run(resolve_canonical_inputs(_CanonicalPool(), SmartInputSelection(
        project_id=25, material_kind="scene")))
    assert canonical.match({"material_kind": {"type": "string"}}) == {
        "material_kind": "scene",
    }


def test_canonical_inputs_reject_material_kind_ref_mismatch():
    try:
        asyncio.run(resolve_canonical_inputs(_CanonicalPool(), SmartInputSelection(
            material_kind="character", material_ref="element:266")))
    except CanonicalInputError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("material_kind must describe the selected material_ref")


def test_canonical_inputs_infer_project_and_chapter_from_shot():
    canonical = asyncio.run(resolve_canonical_inputs(_CanonicalPool(), SmartInputSelection(
        asset_type="pro.shot.keyframe", shot_id=1146)))
    matched = canonical.match({
        "project_id": {}, "asset_type": {}, "chapter_id": {},
        "shot_id": {}, "target_ref": {}, "source_type": {}, "source_ref": {},
    })
    assert matched == {
        "project_id": "25 · 北境灯塔",
        "asset_type": "pro.shot.keyframe",
        "chapter_id": "791 · 雷云层中的考验",
        "shot_id": "1146 · 镜头13",
        "target_ref": "content_node:1146 · 镜头13",
        "source_type": "shot.dynamic_elements",
        "source_ref": "content_node:1146",
    }


def test_loop_artifact_uses_descriptor_target_not_outer_target():
    ctx = {"__inputs__": {"project_id": 25, "target_ref": "content_node:819"},
           "__item__": {"asset_type": "com.image", "target_ref": "element:166"}}
    assert _artifact_inputs(ctx)["target_ref"] == "element:166"


class _ExistingLoopAssetPool:
    def __init__(self):
        self.slot_target = None

    async def fetch(self, *_args):
        return []

    async def fetchrow(self, sql, *args):
        if "FROM workflow_artifacts" in sql:
            self.slot_target = args[1:3]
            return None
        if "FROM content_elements" in sql:
            return {"meta": {"sheet_url": "https://cdn/existing-element.png"}}
        return None


def test_loop_generation_reuses_descriptor_asset_instead_of_outer_target():
    pool = _ExistingLoopAssetPool()
    done, reason, value = asyncio.run(_already_done(
        pool,
        {"asset_type": "com.image", "output_slot": {"role": "com.image"}},
        {"__inputs__": {"project_id": 25, "target_ref": "content_node:1146"},
         "__item__": {"target_ref": "element:161"}},
    ))
    assert pool.slot_target == ("element", 161)
    assert done and "兼容资产" in reason
    assert value == "https://cdn/existing-element.png"


def test_existing_gen_asset_skips_before_prompt_assembly():
    events = []

    async def fake_node_row(*_args, **_kwargs):
        return 601

    async def fake_already_done(*_args, **_kwargs):
        events.append("reuse-checked")
        return True, "existing", "https://cdn/existing.png"

    async def fake_finish(*_args, **_kwargs):
        events.append("finished")

    async def fake_provenance(*_args, **_kwargs):
        events.append("provenance")

    async def prompt_assembly_must_not_run(*_args, **_kwargs):
        raise AssertionError("prompt assembly ran before an existing asset was reused")

    with patch("app.services.workflow._node_run_row", new=fake_node_row), \
         patch("app.services.workflow._already_done", new=fake_already_done), \
         patch("app.services.workflow._finish_node", new=fake_finish), \
         patch("app.services.workflow._record_artifact_provenance", new=fake_provenance), \
         patch("app.services.workflow._assemble_layers", new=prompt_assembly_must_not_run):
        out = asyncio.run(_run_gen_node(
            object(),
            {"id": "gen", "config": {"step": "gen_element_sheet"}},
            ctx={"__inputs__": {"project_id": 25, "target_ref": "element:172"}},
            run_id=501, project_id=25, node_id=172,
        ))

    assert out == {
        "skipped": True, "reason": "existing", "url": "https://cdn/existing.png",
    }
    assert events == ["reuse-checked", "finished", "provenance"]


def test_reused_assembled_gen_exposes_prompt_and_references_for_loop_cards():
    async def fake_node_row(*_args, **_kwargs):
        return 602

    async def fake_already_done(*_args, **_kwargs):
        return True, "existing", "https://cdn/existing-scene.png"

    async def fake_assemble(*_args, **_kwargs):
        return {
            "user": "灯塔顶层信号室",
            "anchor": "纯场景多景别版式",
            "refs": [{"name": "旧设定", "kind": "scene", "url": "https://cdn/ref.png"}],
        }, [{"name": "旧设定", "kind": "scene", "url": "https://cdn/ref.png"}]

    async def fake_finish(*_args, **_kwargs):
        return None

    async def fake_provenance(*_args, **_kwargs):
        return None

    with patch("app.services.workflow._node_run_row", new=fake_node_row), \
         patch("app.services.workflow._already_done", new=fake_already_done), \
         patch("app.services.workflow._assemble_layers", new=fake_assemble), \
         patch("app.services.workflow._finish_node", new=fake_finish), \
         patch("app.services.workflow._record_artifact_provenance", new=fake_provenance):
        out = asyncio.run(_run_gen_node(
            object(),
            {"id": "gen", "config": {
                "step": "gen_element_sheet",
                "assemble": {"name": "element.layers"},
            }},
            ctx={"__inputs__": {"project_id": 25, "target_ref": "element:172"}},
            run_id=501, project_id=25, node_id=172,
        ))

    assert out["url"] == "https://cdn/existing-scene.png"
    # 回显只放**用户需求层**（2026-09-17 定稿）：没有用户输入就不回填拼装文本——
    # 完整实跑提示词（含装配叙事/画布上文）是系统层，不进生成条输入框
    assert out["prompt"] == ""
    assert out["reference_images"] == [{
        "name": "旧设定", "kind": "scene", "url": "https://cdn/ref.png",
    }]


class _ArtifactPool:
    def __init__(self):
        self.artifact_args = None
        self.provenance_args = None

    async def fetchval(self, sql, *args):
        if "SELECT id FROM content_attachments" in sql:
            return 701
        if "INSERT INTO workflow_artifacts" in sql:
            self.artifact_args = args
            return 901
        if "SELECT workflow_id FROM workflow_runs" in sql:
            return 801
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        assert "workflow_artifact_provenance" in sql
        self.provenance_args = args


def test_iteration_artifact_writes_typed_target_attachment_slot_and_provenance():
    pool = _ArtifactPool()
    asyncio.run(_record_artifact_provenance(
        pool, run_id=501, node_run_id=601, node_key="common_image", iteration=3,
        project_id=25, node_id=819,
        inputs={"project_id": 25, "target_ref": "element:166"},
        cfg={"asset_type": "com.image", "operation": "generate",
             "output_slot": {"role": "com.image", "variant": "primary"}},
        url="https://cdn/element-166.png"))

    assert pool.artifact_args == (
        25, 701, "element", 166, "com.image", "primary",
        "https://cdn/element-166.png", "com.image", "none", None,
    )
    assert pool.provenance_args == (
        901, 801, 501, 601, "common_image", 3, "generate",
    )


class _SubflowPool:
    def __init__(self):
        self.events = []

    async def fetchval(self, sql, *_args):
        assert "INSERT INTO workflow_runs" in sql
        self.events.append("child-created")
        return 777

    async def execute(self, sql, *_args):
        if "SET subrun_id" in sql:
            self.events.append("subrun-bound")


def test_subrun_is_bound_before_child_execution_starts():
    pool = _SubflowPool()

    async def fake_run(*_args, **_kwargs):
        pool.events.append("child-running")
        return {"sheet_url": "https://cdn/scene.png"}

    async def fake_node_row(*_args, **_kwargs):
        return 601

    async def fake_finish(*_args, **_kwargs):
        pool.events.append("parent-finished")

    with patch("app.services.workflow.load_workflow",
               return_value={"id": 91}), \
         patch("app.services.workflow.run_workflow", new=fake_run), \
         patch("app.services.workflow._node_run_row", new=fake_node_row), \
         patch("app.services.workflow._finish_node", new=fake_finish):
        asyncio.run(_run_subflow_node(
            pool, {"id": "dynamic_assets", "config": {
                "slug": "multi-element-smart-generation", "force": True,
                "inputs": {"project_id": "{{input.project_id}}"},
            }}, ctx={"__inputs__": {"project_id": 25}}, run_id=501,
            project_id=25, node_id=819, depth=0))

    assert pool.events == [
        "child-created", "subrun-bound", "child-running", "parent-finished",
    ]


def test_router_loop_body_runs_only_the_matching_asset_type_branch():
    scene_context = {"__item__": {"asset_type": "pro.scene.sheet"}}
    common_context = {"__item__": {"asset_type": "com.image"}}
    scene_only = {"run_if": {"value": "{{__item__.asset_type}}", "equals": "pro.scene.sheet"}}
    common_only = {"run_if": {"value": "{{__item__.asset_type}}", "equals": "com.image"}}

    assert _run_if_matches(scene_only, scene_context)
    assert not _run_if_matches(common_only, scene_context)
    assert not _run_if_matches(scene_only, common_context)
    assert _run_if_matches(common_only, common_context)


def test_output_cardinality_is_derived_from_terminal_aggregation_not_ui_hint():
    many = {"nodes": [{"id": "loop", "type": "loop"}, {"id": "end", "type": "end"}],
            "edges": [{"from": "loop", "to": "end"}]}
    one = {"nodes": [{"id": "gen", "type": "gen"}, {"id": "end", "type": "end"}],
           "edges": [{"from": "gen", "to": "end"}]}
    fan_in = {"nodes": [{"id": "a", "type": "gen"}, {"id": "b", "type": "gen"}, {"id": "end", "type": "end"}],
              "edges": [{"from": "a", "to": "end"}, {"from": "b", "to": "end"}]}
    assert output_cardinality(many) == "many"
    assert output_cardinality(fan_in) == "many"
    assert output_cardinality(one) == "one"


def test_asset_reader_understands_primary_and_variant_legacy_media():
    assert _legacy_value({"sheet_url": "https://cdn/primary.png"}, "image") == \
        "https://cdn/primary.png"
    assert _legacy_value({"variants": [{"sheet_url": "https://cdn/variant.png"}]}, "image") == \
        "https://cdn/variant.png"
    assert _legacy_value({"extra_refs": ["https://cdn/reference.png"]}, "image") is None


class _LegacyAssetPool:
    async def fetch(self, *_args):
        return []

    async def fetchrow(self, sql, *_args):
        if "content_elements" in sql:
            return {"meta": {"sheet_url": "https://cdn/character-sheet.png"}}
        return None


def test_common_image_can_read_existing_element_image_through_asset_contract():
    found = asyncio.run(read_latest(
        _LegacyAssetPool(), project_id=25, asset_type="com.image", target_ref="element:161"))
    assert found == {
        "url": "https://cdn/character-sheet.png",
        "asset_type": "com.image",
        "source": "content_elements.meta",
    }
