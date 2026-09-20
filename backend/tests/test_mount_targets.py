"""挂载点归宿注册表测试（2026-09-18）：唯一事实来源 + 前后端对齐 + HTTP 端到端。

注册表（app/services/mount_targets.py）是「画布产物能落到哪、怎么落」的唯一权威：
- project_field 形态：写 content_projects.config 的一个字段（cover_url / trailer_url）
- asset 形态：写 workflow_artifacts，合同自动来自 app/assets（新增资产码自动可用）
触发路径（挂载点执行体 / run 收尾补漏 / 连线即落库端点 / 旧 end.store 绑定）
全部经由 apply_mount_binding 按表分派——这里验证三路径落库结果一致。
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import workflows as A
from app.services import tapflow_ai as T
from app.services import workflow as W
from app.services.mount_targets import all_targets, get_target
from tests.test_mount_node import FakePool, _ctx, _wf

FRONTEND_TARGETS = (Path(__file__).resolve().parents[2]
                    / "frontend" / "src" / "lib" / "tapflowData.ts")


# ── 注册表本身 ────────────────────────────────────────────────

def test_registry_shape():
    codes = [t.code for t in all_targets()]
    assert codes[0] == "project_cover" and "project_trailer" in codes
    for expected in ("pro.character.sheet", "pro.scene.sheet", "pro.scene.brief",
                     "pro.shot.keyframe", "pro.shot.video", "com.image", "com.video"):
        assert expected in codes, f"资产归宿 {expected} 未进注册表"
    for t in all_targets():
        if t.kind == "project_field":
            assert t.field and t.subject == "project" and t.media in ("image", "video")
        else:
            assert t.kind == "asset" and t.field is None
    assert get_target(" nope ") is None
    assert get_target("project_cover") is not None


def test_registry_covers_frontend_choices():
    """前端画布可选清单 ⊆ 注册表，且 subject 逐项一致——清单是 UI 措辞，注册表是事实。"""
    src = FRONTEND_TARGETS.read_text(encoding="utf-8")
    rows = re.findall(r"\{ v: '([^']+)', label: '([^']+)', subject: '([^']+)'", src)
    assert rows, "前端 MOUNT_TARGETS 清单没解析到（文件被加密或格式变了？）"
    reg = {t.code: t for t in all_targets()}
    for v, _label, subject in rows:
        t = reg.get(v)
        assert t is not None, f"前端可选归宿 {v} 未在后端注册表注册"
        assert t.subject == subject, f"{v} subject 不一致：前端 {subject} vs 注册表 {t.subject}"


# ── project_field 形态 ────────────────────────────────────────

def test_project_trailer_field_form():
    """预告片归宿：video 产物写 config.trailer_url——注册一行，行为立刻通用。"""
    pool = FakePool()
    out = asyncio.run(T.apply_mount_binding(
        pool, project_id=7, outputs={"url": "https://oss/t.mp4"}, target="project_trailer"))
    assert out["stored"] == "project_trailer"
    assert pool.projects["trailer_url"] == "https://oss/t.mp4"


def test_unknown_target_skipped():
    out = asyncio.run(T.apply_mount_binding(
        FakePool(), project_id=7, outputs={"url": "https://oss/a.png"}, target="nope"))
    assert out == {"stored": "skipped", "reason": "unknown target nope"}


# ── 旧 end.store 绑定并入注册表 ───────────────────────────────

def test_end_binding_routes_through_registry():
    pool = FakePool()
    out = asyncio.run(T.apply_end_binding(
        pool, project_id=7, outputs={"url": "https://oss/c.png"},
        binding={"target": "project_cover"}))
    assert out["stored"] == "project_cover"
    assert pool.projects["cover_url"] == "https://oss/c.png"


def test_end_binding_asset_code_now_supported():
    """历史 end 绑定资产码从 unknown 变为可落（subject=none 走附件约定）。"""
    pool = FakePool(attachment_id=77)
    out = asyncio.run(T.apply_end_binding(
        pool, project_id=7, outputs={"url": "https://oss/i.png"},
        binding={"target": "com.image"}))
    assert out["stored"] == "com.image"


# ── HTTP 端到端：路由 → 注册表 → 落库 ─────────────────────────

def _client(monkeypatch, pool) -> TestClient:
    monkeypatch.setattr(A, "get_pool", lambda: pool)
    app = FastAPI()
    app.include_router(A.router)
    return TestClient(app)


def test_http_mount_store_end_to_end(monkeypatch):
    """端到端：POST /{slug}/mount-store → 路由 → apply_mount_binding → 注册表 → config 落值。"""
    pool = FakePool()
    c = _client(monkeypatch, pool)
    r = c.post("/api/workflows/cover-poster/mount-store",
               json={"project_id": 7, "target": "project_cover", "url": "https://oss/new.png"})
    assert r.status_code == 200
    assert r.json()["stored"] == "project_cover"
    assert pool.projects["cover_url"] == "https://oss/new.png"


def test_http_mount_store_trailer_and_unknown(monkeypatch):
    pool = FakePool()
    c = _client(monkeypatch, pool)
    r = c.post("/api/workflows/x/mount-store",
               json={"project_id": 7, "target": "project_trailer", "url": "https://oss/t.mp4"})
    assert r.status_code == 200 and r.json()["stored"] == "project_trailer"
    assert pool.projects["trailer_url"] == "https://oss/t.mp4"
    r = c.post("/api/workflows/x/mount-store",
               json={"project_id": 7, "target": "nope", "url": "https://oss/a.png"})
    assert r.status_code == 200
    assert r.json()["reason"] == "unknown target nope"


# ── 三条触发路径落库一致 ──────────────────────────────────────

def test_three_trigger_paths_land_identically(monkeypatch):
    """同一归宿同一产物：run 收尾补漏 / 连线即落库端点 / 挂载点执行体分派，
    落库结果一致——都走 apply_mount_binding 这个唯一底座。"""
    wf = _wf([("a", "gen"), ("m", "mount")], [("a", "m")],
             {"m": {"target": "project_cover"}})
    ctx = _ctx(wf, {"project_id": 7}, {"a": "https://oss/x.png"})
    # ① run 收尾补漏（挂载点没在本次范围内也照落）
    p1 = FakePool()
    asyncio.run(W._auto_store_on_finish(p1, wf=wf, ctx=ctx, project_id=7, depth=0))
    # ② 连线即落库端点
    p2 = FakePool()
    c = _client(monkeypatch, p2)
    r = c.post("/api/workflows/x/mount-store",
               json={"project_id": 7, "target": "project_cover", "url": "https://oss/x.png"})
    assert r.status_code == 200
    # ③ 挂载点执行体分派（执行体核心即此调用）
    p3 = FakePool()
    asyncio.run(T.apply_mount_binding(
        p3, project_id=7, outputs={"url": "https://oss/x.png"}, target="project_cover"))
    for p in (p1, p2, p3):
        assert p.projects["cover_url"] == "https://oss/x.png"
