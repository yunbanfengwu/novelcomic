"""挂载点节点（2026-09-17 通用标准方案）测试。

画布上的独立挂载节点声明产物归宿：连到它的产物就落进该归宿。
- 项目封面 → content_projects.config.cover_url
- 资产类型码 → workflow_artifacts（asset_type + subject + version）
- 多张候选取「最近生成」的那张；同一产物重复跑不刷版本
- 同一画布同一归宿只能有一个挂载点（validate_graph）
- 收尾补漏：挂载点不在本次范围内也照落
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.services import tapflow_ai, workflow as W


class FakePool:
    """够用的假池：只认挂载点落库会碰到的几条 SQL。"""

    def __init__(self, *, cover_url: str | None = None,
                 existing: dict[str, Any] | None = None,
                 attachment_id: int = 77):
        self.cover_url = cover_url
        self.existing = existing or {}
        self.attachment_id = attachment_id
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.projects: dict[str, Any] = {
            "cover_url": cover_url, "cover_prompt": "old",
        }

    async def fetchval(self, sql: str, *args: Any) -> Any:
        flat = " ".join(sql.split())
        if "SELECT config FROM content_projects" in flat:
            return json.dumps(self.projects)
        if "SELECT id FROM content_attachments" in flat:
            return self.attachment_id
        if "SELECT COALESCE(MAX(version),0)+1" in flat:
            return self.existing.get("next_version", 1)
        if "INSERT INTO workflow_artifacts" in flat:
            return 901
        return None

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        flat = " ".join(sql.split())
        if "SELECT url, version FROM workflow_artifacts" in flat:
            return self.existing.get("row")
        return None

    async def execute(self, sql: str, *args: Any) -> None:
        self.executed.append((" ".join(sql.split()), args))
        if "UPDATE content_projects SET config" in " ".join(sql.split()):
            self.projects = json.loads(args[0])


def _wf(nodes: list[tuple[str, str]], edges: list[tuple[str, str]],
        configs: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    cfg = configs or {}
    return {"graph": {
        "nodes": [{"id": i, "type": t, "config": cfg.get(i, {})} for i, t in nodes],
        "edges": [{"from": a, "to": b} for a, b in edges],
    }}


def _ctx(wf: dict[str, Any], inputs: dict[str, Any], urls: dict[str, str]) -> dict[str, Any]:
    """按执行顺序造 trace：urls 的插入序就是「生成先后」。"""
    ctx: dict[str, Any] = {"__inputs__": inputs, "__trace__": []}
    for node, url in urls.items():
        out = {"url": url, "prompt": f"{node} 的提示词"}
        ctx["__trace__"].append({"node": node, "type": "gen", "outputs": out})
        ctx[node] = out
    return ctx


# ── 上游产物选择 ──────────────────────────────────────────────

def test_mount_upstream_picks_latest_generated():
    """多张候选取最近生成的——重跑上游，挂载点就指向新的那张。"""
    wf = _wf([("a", "gen"), ("b", "gen"), ("m", "mount")],
             [("a", "m"), ("b", "m")])
    ctx = _ctx(wf, {}, {"a": "https://oss/a.png", "b": "https://oss/b.png"})
    url, prompt, src = W._mount_upstream(wf, "m", ctx)
    assert url == "https://oss/b.png" and src == "b"
    assert prompt == "b 的提示词"


def test_mount_upstream_ignores_island_and_side_branch():
    """孤岛与支线不是挂载点的上游——「只有连接了才存入」。"""
    wf = _wf([("a", "gen"), ("m", "mount"), ("island", "gen"), ("side", "gen"), ("mid", "gen")],
             [("a", "m"), ("side", "mid")])
    ctx = _ctx(wf, {}, {"island": "https://oss/island.png",
                        "side": "https://oss/side.png", "a": "https://oss/a.png"})
    url, _, src = W._mount_upstream(wf, "m", ctx)
    assert url == "https://oss/a.png" and src == "a"


def test_mount_upstream_walks_through_intermediate_nodes():
    """中间节点（非 gen）也不该断链：沿入边 BFS 要穿透过去。"""
    wf = _wf([("a", "gen"), ("qc", "action"), ("m", "mount")],
             [("a", "qc"), ("qc", "m")])
    ctx = _ctx(wf, {}, {"a": "https://oss/a.png"})
    url, _, src = W._mount_upstream(wf, "m", ctx)
    assert url == "https://oss/a.png" and src == "a"


def test_mount_upstream_accepts_uploaded_asset_node():
    """上传/素材（value）节点连到挂载点也是真产物——只认 gen 会让它报
    「上游没有可用产物」，而「把现有这张图存成封面」是最常见的用法。"""
    wf = _wf([("up", "value"), ("m", "mount")], [("up", "m")])
    ctx: dict[str, Any] = {"__inputs__": {}, "__trace__": [
        {"node": "up", "type": "value", "outputs": {"url": "https://oss/uploaded.png"}},
    ]}
    url, _, src = W._mount_upstream(wf, "m", ctx)
    assert url == "https://oss/uploaded.png" and src == "up"


def test_mount_upstream_ignores_non_media_outputs():
    """上游是纯文本节点（输出里没有 url）时不算产物。"""
    wf = _wf([("t", "text"), ("m", "mount")], [("t", "m")])
    ctx: dict[str, Any] = {"__inputs__": {}, "__trace__": [
        {"node": "t", "type": "text", "outputs": {"text": "一段文案"}},
    ]}
    assert W._mount_upstream(wf, "m", ctx) == (None, "", "")


# ── 落库 ─────────────────────────────────────────────────────

def test_mount_binding_saves_project_cover():
    pool = FakePool()
    out = asyncio.run(tapflow_ai.apply_mount_binding(
        pool, project_id=26, outputs={"url": "https://oss/new.png", "prompt": "封面"},
        target="project_cover"))
    assert out["stored"] == "project_cover"
    assert pool.projects["cover_url"] == "https://oss/new.png"


def test_mount_binding_project_cover_idempotent():
    """同一个 url 再落一次不算改动，也不刷 updated_at。"""
    pool = FakePool(cover_url="https://oss/same.png")
    out = asyncio.run(tapflow_ai.apply_mount_binding(
        pool, project_id=26, outputs={"url": "https://oss/same.png"},
        target="project_cover"))
    assert out.get("unchanged") is True
    assert not pool.executed


def test_mount_binding_writes_artifact_with_subject():
    """资产类型归宿：写 workflow_artifacts，subject 按契约校验。"""
    pool = FakePool()
    out = asyncio.run(tapflow_ai.apply_mount_binding(
        pool, project_id=26, outputs={"url": "https://oss/role.png"},
        target="pro.character.sheet", subject={"kind": "element", "id": 188}))
    assert out["stored"] == "pro.character.sheet" and out["version"] == 1
    sql, args = pool.executed[-1] if pool.executed else ("", ())
    # 假池把 INSERT 交给 fetchval，这里直接校验返回足够；args 在 fetchval 里没记
    assert out["artifact_id"] == 901


def test_mount_binding_rejects_wrong_subject_kind():
    pool = FakePool()
    out = asyncio.run(tapflow_ai.apply_mount_binding(
        pool, project_id=26, outputs={"url": "https://oss/x.png"},
        target="pro.character.sheet", subject={"kind": "content_node", "id": 5}))
    assert out["stored"] == "skipped" and "element" in out["reason"]


def test_mount_binding_skips_when_subject_missing():
    pool = FakePool()
    out = asyncio.run(tapflow_ai.apply_mount_binding(
        pool, project_id=26, outputs={"url": "https://oss/x.png"},
        target="pro.scene.sheet"))
    assert out["stored"] == "skipped" and "业务对象" in out["reason"]


def test_mount_binding_artifact_idempotent():
    pool = FakePool(existing={"row": {"url": "https://oss/same.png", "version": 3}})
    out = asyncio.run(tapflow_ai.apply_mount_binding(
        pool, project_id=26, outputs={"url": "https://oss/same.png"},
        target="pro.character.sheet", subject={"kind": "element", "id": 188}))
    assert out.get("unchanged") is True and out["version"] == 3


def test_mount_binding_unknown_target_skipped():
    pool = FakePool()
    out = asyncio.run(tapflow_ai.apply_mount_binding(
        pool, project_id=26, outputs={"url": "https://oss/x.png"},
        target="not.a.type"))
    assert out["stored"] == "skipped" and "unknown target" in out["reason"]


def test_mount_binding_no_url_skipped():
    pool = FakePool()
    out = asyncio.run(tapflow_ai.apply_mount_binding(
        pool, project_id=26, outputs={}, target="project_cover"))
    assert out["stored"] == "skipped" and out["reason"] == "no url"


# ── subject 解析 ─────────────────────────────────────────────

def test_mount_subject_prefers_declared():
    """入口默认挂载点把业务对象钉在节点上，运行入参改不了它。"""
    ctx = {"__inputs__": {"target_ref": "element:5"}}
    assert W._mount_subject({"subject": {"kind": "element", "id": 188}}, ctx) == \
        {"kind": "element", "id": 188}


def test_mount_subject_falls_back_to_inputs():
    ctx = {"__inputs__": {"target_ref": "element:188", "project_id": 26}}
    assert W._mount_subject({}, ctx) == {"kind": "element", "id": 188}


def test_mount_subject_none_without_context():
    assert W._mount_subject({}, {"__inputs__": {}}) is None


# ── 图校验：同一归宿唯一 ──────────────────────────────────────

def test_validate_graph_rejects_duplicate_mount_target():
    wf = _wf([("m1", "mount"), ("m2", "mount")], [],
             {"m1": {"target": "project_cover"}, "m2": {"target": "project_cover"}})
    errs = W.validate_graph(wf["graph"])
    assert any("挂载点重复" in e for e in errs), errs


def test_validate_graph_allows_distinct_mount_targets():
    wf = _wf([("m1", "mount"), ("m2", "mount")], [],
             {"m1": {"target": "project_cover"},
              "m2": {"target": "pro.character.sheet", "subject": {"kind": "element", "id": 1}}})
    assert W.validate_graph(wf["graph"]) == []


def test_validate_graph_same_target_different_subject_ok():
    wf = _wf([("m1", "mount"), ("m2", "mount")], [],
             {"m1": {"target": "pro.character.sheet", "subject": {"kind": "element", "id": 1}},
              "m2": {"target": "pro.character.sheet", "subject": {"kind": "element", "id": 2}}})
    assert W.validate_graph(wf["graph"]) == []


# ── 收尾补漏 ─────────────────────────────────────────────────

def test_auto_store_finish_lands_mount_not_in_range():
    """挂载点不在本次运行范围（比如只跑上游单节点）时，收尾也要落库。"""
    wf = _wf([("a", "gen"), ("m", "mount")], [("a", "m")],
             {"m": {"target": "project_cover"}})
    ctx = _ctx(wf, {"project_id": 26}, {"a": "https://oss/a.png"})
    pool = FakePool()
    asyncio.run(W._auto_store_on_finish(pool, wf=wf, ctx=ctx, project_id=26, depth=0))
    assert pool.projects["cover_url"] == "https://oss/a.png"


def test_auto_store_finish_skips_mount_without_upstream_product():
    wf = _wf([("a", "gen"), ("m", "mount")], [("a", "m")],
             {"m": {"target": "project_cover"}})
    ctx = {"__inputs__": {"project_id": 26}, "__trace__": [], "a": {}}
    pool = FakePool()
    asyncio.run(W._auto_store_on_finish(pool, wf=wf, ctx=ctx, project_id=26, depth=0))
    assert pool.projects.get("cover_url") is None


# ── 连线即挂载端点（2026-09-18）──────────────────────────────

def test_mount_store_endpoint_writes_cover(monkeypatch):
    """POST /{slug}/mount-store：连线时立即把那张图落库，不等一次运行。"""
    from app.api import workflows as A
    pool = FakePool()
    monkeypatch.setattr(A, "get_pool", lambda: pool)
    body = A.MountStoreIn(project_id=7, target="project_cover", url="https://oss/new.png")
    out = asyncio.run(A.mount_store("cover-poster", body))
    assert out["stored"] == "project_cover"
    assert pool.projects["cover_url"] == "https://oss/new.png"


def test_mount_store_endpoint_unchanged_when_same_url(monkeypatch):
    """连的还是当前封面：不刷版本、不重写，标记 unchanged。"""
    from app.api import workflows as A
    pool = FakePool(cover_url="https://oss/same.png")
    monkeypatch.setattr(A, "get_pool", lambda: pool)
    body = A.MountStoreIn(project_id=7, target="project_cover", url="https://oss/same.png")
    out = asyncio.run(A.mount_store("cover-poster", body))
    assert out.get("unchanged") is True


def test_mount_store_endpoint_skips_without_project(monkeypatch):
    from app.api import workflows as A
    pool = FakePool()
    monkeypatch.setattr(A, "get_pool", lambda: pool)
    body = A.MountStoreIn(target="project_cover", url="https://oss/new.png")
    out = asyncio.run(A.mount_store("cover-poster", body))
    assert out == {"stored": "skipped", "reason": "没有项目上下文"}
    assert pool.projects.get("cover_url") is None
