"""百炼生图双协议：同步多模态（qwen-image-edit 族） vs 异步任务（wanx/qwen-image）。

2026-09-17 事故回归：qwen-image-edit-plus 被按异步任务协议提交 →
403 AccessDenied "current user api does not support asynchronous calls"。
这族模型走同步 multimodal-generation，且不认 size——在这里钉死契约。
"""
import asyncio
import json

import httpx
import pytest

from app import dashscope


def test_route_sync_for_image_edit_family():
    """图像编辑族走同步；文生图族走异步；extra.transport 可显式覆盖。"""
    assert dashscope._wants_sync("qwen-image-edit-plus")
    assert dashscope._wants_sync("qwen-image-edit-plus-2025-10-30")
    assert dashscope._wants_sync("qwen-image-edit")
    # 文生图族仍走异步任务
    assert not dashscope._wants_sync("qwen-image")
    assert not dashscope._wants_sync("wanx-v1")
    assert not dashscope._wants_sync("wan2.6-image")
    # 模型档显式覆盖优先于名字推断
    assert dashscope._wants_sync("wanx-v1", {"transport": "sync"})
    assert not dashscope._wants_sync("qwen-image-edit-plus", {"transport": "async"})


class _FakeResp:
    status_code = 200
    text = "{}"

    def json(self):
        return {"output": {"choices": [{"message": {"content": [
            {"image": "https://oss/out.png"}]}}]}}


def test_sync_request_shape_and_response_parse(monkeypatch):
    """同步请求：正确端点、无异步头、messages 结构（image 项在前 text 在后）、不传 size。"""
    seen = {}

    async def fake_post(self, url, headers=None, json=None, **kw):
        seen["url"] = url
        seen["headers"] = headers
        seen["json"] = json
        return _FakeResp()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    out = asyncio.run(dashscope._multimodal_generation(
        "https://dashscope.aliyuncs.com", "sk-x", "qwen-image-edit-plus",
        "把小猫放到空气炸锅旁边", ["https://oss/ref.png"], 300.0))
    assert out == "https://oss/out.png"
    assert seen["url"] == ("https://dashscope.aliyuncs.com"
                           "/api/v1/services/aigc/multimodal-generation/generation")
    assert "X-DashScope-Async" not in (seen["headers"] or {})
    content = seen["json"]["input"]["messages"][0]["content"]
    assert content[0] == {"image": "https://oss/ref.png"}
    assert content[-1] == {"text": "把小猫放到空气炸锅旁边"}
    assert "size" not in json.dumps(seen["json"])  # 这族不吃 size


def test_sync_caps_reference_images_at_three(monkeypatch):
    """qwen-image-edit 族参考图上限 3 张，超了在 provider 层裁掉。"""
    seen = {}

    async def fake_post(self, url, headers=None, json=None, **kw):
        seen["json"] = json
        return _FakeResp()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    out = asyncio.run(dashscope._multimodal_generation(
        "https://x", "k", "qwen-image-edit-plus", "p",
        [f"https://oss/{i}.png" for i in range(5)], 10.0))
    assert out == "https://oss/out.png"
    content = seen["json"]["input"]["messages"][0]["content"]
    images = [c for c in content if "image" in c]
    assert len(images) == 3


def test_sync_error_surfaces_provider_message(monkeypatch):
    """同步提交失败：供应商报错原样浮出（403 的 AccessDenied 不能被吞成'缺 task_id'）。"""
    class R403:
        status_code = 403
        text = '{"code":"AccessDenied","message":"boom"}'

        def json(self):
            return {}

    async def fake_post(self, url, headers=None, json=None, **kw):
        return R403()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(RuntimeError, match="HTTP 403"):
        asyncio.run(dashscope._multimodal_generation(
            "https://x", "k", "qwen-image-edit-plus", "p", ["https://r/1.png"], 10.0))


def test_sync_without_refs_fails_fast_in_chinese():
    """图像编辑族不带参考图：用可执行的中文提示拒在本地，而不是甩供应商 400。"""
    with pytest.raises(RuntimeError, match="参考图"):
        asyncio.run(dashscope._multimodal_generation(
            "https://x", "k", "qwen-image-edit-plus", "p", None, 10.0))


def test_image_synthesis_dispatch(monkeypatch):
    """image_synthesis 按模型族分派：edit 走同步直返；文生图走异步任务提交。"""
    routed = {}

    async def fake_sync(host, api_key, model, prompt, refs, timeout_s):
        routed["sync"] = (model, refs)
        return "https://oss/sync.png"

    async def fake_poll(host, api_key, path, body, kind, pick, timeout_s):
        routed["async"] = (body["model"], path)
        return "https://oss/async.png"

    monkeypatch.setattr(dashscope, "_multimodal_generation", fake_sync)
    monkeypatch.setattr(dashscope, "_submit_and_poll", fake_poll)
    assert asyncio.run(dashscope.image_synthesis(
        "https://x", "k", "qwen-image-edit-plus", "p", "1024*1024",
        ["https://r/1.png"])) == "https://oss/sync.png"
    assert routed["sync"] == ("qwen-image-edit-plus", ["https://r/1.png"])
    assert asyncio.run(dashscope.image_synthesis(
        "https://x", "k", "qwen-image", "p")) == "https://oss/async.png"
    assert routed["async"][1] == dashscope._SUBMIT
