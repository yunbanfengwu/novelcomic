"""_resolve_asset_target 的 target_ref 缺失兜底（2026-09-20）。

背景：shot-video-canvas 的「首帧（缺才跑）」subflow 只透传 shot_id/project_id，
子画布（shot-keyframe-canvas）的资产合约（pro.shot.keyframe）要求 target_ref
必须指向 content_node:shot——调用链拿不到 target_ref 时整个 run 直接失败
（"分镜关键帧必须选择content_node类型的关联对象"），表现为画布执行链断裂。

合约层兜底：分镜类资产（target_content_kind=shot）的关联对象就是该分镜自身，
inputs 里有 shot_id 时按 shot_id 等价推导 target_ref，推导后仍走常规校验
（kind=shot、归属项目匹配）。非分镜资产不受影响。"""
import asyncio

import pytest

from backend.app.services.workflow import _resolve_asset_target


class FakePool:
    """只接 _resolve_asset_target 的一条查询：content_nodes 按 id 取行。"""

    def __init__(self, rows):
        self.rows = rows
        self.calls: list[tuple] = []

    async def fetchrow(self, sql, *args):
        self.calls.append(args)
        for row in self.rows:
            if row["id"] == args[0]:
                return row
        return None


@pytest.fixture
def shot_row():
    return {"id": 1508, "kind": "shot", "parent_id": 1468,
            "project_id": 26, "name": "镜头1"}


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def test_missing_target_ref_derived_from_shot_id(shot_row):
    """subflow 只传 shot_id/project_id：兜底推导 target_ref=content_node:{shot_id}，
    不再抛「必须选择content_node类型的关联对象」，且绑定字段照常解析。"""
    pool = FakePool([shot_row])
    out = run(_resolve_asset_target(pool, {
        "project_id": 26, "shot_id": 1508, "asset_type": "pro.shot.keyframe",
    }))
    assert out["target_ref"] == "content_node:1508"
    # context_bindings：target.id → shot_id、target.parent_id → chapter_id、target.project_id → project_id
    assert out["shot_id"] == 1508
    assert out["chapter_id"] == 1468
    assert out["project_id"] == 26


def test_explicit_target_ref_still_verified(shot_row):
    """显式给了 target_ref 时行为不变：正常解析绑定。"""
    pool = FakePool([shot_row])
    out = run(_resolve_asset_target(pool, {
        "project_id": 26, "target_ref": "content_node:1508",
        "asset_type": "pro.shot.keyframe",
    }))
    assert out["shot_id"] == 1508
    assert out["chapter_id"] == 1468


def test_wrong_kind_target_ref_still_rejected(shot_row):
    """兜底推导后仍走校验：指向的内容 kind 不对照样报错（不放过脏数据）。"""
    bad = {**shot_row, "kind": "scene"}
    pool = FakePool([bad])
    from backend.app.services.workflow import WorkflowError
    with pytest.raises(WorkflowError):
        run(_resolve_asset_target(pool, {
            "project_id": 26, "shot_id": 1508, "asset_type": "pro.shot.keyframe",
        }))


def test_project_mismatch_still_rejected(shot_row):
    """推导后 project_id 不匹配仍报错。"""
    bad = {**shot_row, "project_id": 99}
    pool = FakePool([bad])
    from backend.app.services.workflow import WorkflowError
    with pytest.raises(WorkflowError):
        run(_resolve_asset_target(pool, {
            "project_id": 26, "shot_id": 1508, "asset_type": "pro.shot.keyframe",
        }))


def test_scene_asset_without_target_ref_unaffected():
    """非分镜资产（场景设定图，target=element/scene）没有 shot_id 可借：
    缺 target_ref 照旧报错——兜底不扩大适用面。"""
    from backend.app.assets import get as get_asset_type
    asset = get_asset_type("pro.scene.sheet")
    assert asset.target_content_kind == "scene"
    pool = FakePool([])
    from backend.app.services.workflow import WorkflowError
    with pytest.raises(WorkflowError):
        run(_resolve_asset_target(pool, {
            "project_id": 26, "scene_id": 88, "asset_type": "pro.scene.sheet",
        }))


def test_no_asset_type_noop():
    """没有 asset_type（多产出路由画布）直接原样返回，与历史行为一致。"""
    pool = FakePool([])
    inputs = {"project_id": 26, "shot_id": 1508}
    assert run(_resolve_asset_target(pool, dict(inputs))) is inputs or \
        run(_resolve_asset_target(pool, dict(inputs))) == inputs
