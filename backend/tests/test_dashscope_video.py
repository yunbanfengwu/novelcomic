"""百炼生视频：端点/请求体契约 + 分支穷举。

2026-08-01 事故回归测试：百炼视频档掉进 media._grsai_video 的 Sora 风格 fallthrough，
POST 到 `compatible-mode/v1/videos`（不存在）→ 404，请求还没到参数校验就被拒。
这里把「打哪个地址、发什么体」钉死，改坏立刻红。
"""
import asyncio

import pytest

from app import dashscope


def test_native_host_strips_compatible_mode():
    """模型档存的是兼容模式地址，必须还原成同域 DashScope 根地址（工作空间专属域名）。"""
    ws = "https://ws-1x1osnl9woaeuy5g.cn-beijing.maas.aliyuncs.com"
    assert dashscope.native_host(f"{ws}/compatible-mode/v1") == ws
    assert dashscope.native_host(ws) == ws


def test_video_submit_path_is_not_compatible_mode():
    """事故本体：生视频绝不能落在 compatible-mode/v1/videos。"""
    assert dashscope._VIDEO_SUBMIT == "/api/v1/services/aigc/video-generation/video-synthesis"
    assert "compatible-mode" not in dashscope._VIDEO_SUBMIT
    assert "videos" != dashscope._VIDEO_SUBMIT.rsplit("/", 1)[-1]


def test_i2v_models_require_first_frame():
    """i2v 族缺首帧要给出可执行的中文提示，而不是把含混的供应商 400 甩给用户。"""
    for model in ["happyhorse-1.1-i2v", "wan2.7-i2v", "wan2.5-s2v", "wan2.7-videoedit"]:
        assert dashscope._needs_image(model), model
    for model in ["wan2.2-t2v-plus", "wan2.7-t2v"]:
        assert not dashscope._needs_image(model), model


def _capture(monkeypatch):
    seen = {}

    async def fake_submit(host, api_key, path, body, kind, pick, timeout_s):
        seen.update(host=host, path=path, body=body, kind=kind)
        return "https://cdn.example/v.mp4"

    monkeypatch.setattr(dashscope, "_submit_and_poll", fake_submit)
    return seen


def test_img_field_contract_split_at_wan27():
    """百炼在 wan2.7 换了图输入契约，两代并存；认不出版本的按新契约走。"""
    for legacy in ["wanx2.1-i2v-turbo", "wan2.2-i2v-plus", "wan2.5-i2v-preview",
                   "wan2.6-i2v-flash"]:
        assert dashscope._legacy_img_field(legacy), legacy
    for modern in ["wan2.7-i2v", "wan2.7-i2v-2026-04-25", "happyhorse-1.1-i2v", "wan3.0-i2v"]:
        assert not dashscope._legacy_img_field(modern), modern


def test_video_body_modern_media_array(monkeypatch):
    """新契约：input.media 数组（first_frame/last_frame）。实测 happyhorse 发 img_url
    会被拒——`InvalidParameter: Field required: input.media`。"""
    seen = _capture(monkeypatch)
    url = asyncio.run(dashscope.video_synthesis(
        "https://ws-x.cn-beijing.maas.aliyuncs.com/compatible-mode/v1", "sk-1",
        "happyhorse-1.1-i2v", "雨夜霓虹街道，镜头缓推", img_url="https://oss/k.jpg",
        last_frame_url="https://oss/tail.jpg", duration=5, resolution="720P"))

    assert url == "https://cdn.example/v.mp4"
    assert seen["host"] == "https://ws-x.cn-beijing.maas.aliyuncs.com"
    assert seen["path"] == "/api/v1/services/aigc/video-generation/video-synthesis"
    assert seen["body"]["input"] == {
        "prompt": "雨夜霓虹街道，镜头缓推",
        "media": [{"type": "first_frame", "url": "https://oss/k.jpg"},
                  {"type": "last_frame", "url": "https://oss/tail.jpg"}],
    }
    assert "img_url" not in seen["body"]["input"]
    # prompt_extend 默认 true，必须显式关掉，否则百炼会重写我们装配好的提示词
    assert seen["body"]["parameters"]["prompt_extend"] is False
    assert seen["body"]["parameters"]["duration"] == 5
    assert seen["body"]["parameters"]["resolution"] == "720P"


def test_video_body_legacy_img_url(monkeypatch):
    """旧契约：input.img_url 字符串，且没有尾帧通道（静默忽略，不能塞进 img_url）。"""
    seen = _capture(monkeypatch)
    asyncio.run(dashscope.video_synthesis(
        "https://x/compatible-mode/v1", "sk-1", "wan2.6-i2v-flash", "提示词",
        img_url="https://oss/k.jpg", last_frame_url="https://oss/tail.jpg"))
    assert seen["body"]["input"] == {"prompt": "提示词", "img_url": "https://oss/k.jpg"}
    assert "media" not in seen["body"]["input"]


def _profile(provider, model="m", extra=None):
    return {"provider": provider, "model_name": model, "base_url": "https://x/compatible-mode/v1",
            "api_key": "sk-1", "extra": extra or {}}


def test_generate_video_routes_dashscope_not_grsai(monkeypatch):
    """根因回归：百炼档必须走 DashScope 原生任务，不能掉进 GRSAI 的 Sora 风格 /videos。"""
    from app import media

    async def prof():
        return _profile("dashscope", "happyhorse-1.1-i2v", {"resolution": "720P"})

    async def no_grsai(*a, **k):
        raise AssertionError("百炼档绝不能走 GRSAI 路径")

    called = {}

    async def fake_video(base, key, model, prompt, img_url=None, last_frame_url=None,
                         duration=None, resolution=None, timeout_s=900.0):
        called.update(model=model, img_url=img_url, last_frame_url=last_frame_url,
                      resolution=resolution)
        return "https://cdn/v.mp4"

    async def no_audit(**k):
        return None

    monkeypatch.setattr(media, "_video_profile", prof)
    monkeypatch.setattr(media, "_grsai_video", no_grsai)
    monkeypatch.setattr(media, "_audit_log", no_audit)
    monkeypatch.setattr(dashscope, "video_synthesis", fake_video)

    res = asyncio.run(media.generate_video("提示词", image_url="https://oss/k.jpg",
                                           last_frame_url="https://oss/tail.jpg", duration=5))
    assert res == {"url": "https://cdn/v.mp4", "provider": "dashscope:happyhorse-1.1-i2v"}
    # 尾帧必须一路传到底：接缝帧（下一镜首帧当本镜尾帧）在百炼这条路上同样生效
    assert called == {"model": "happyhorse-1.1-i2v", "img_url": "https://oss/k.jpg",
                      "last_frame_url": "https://oss/tail.jpg", "resolution": "720P"}


def test_generate_video_unknown_provider_raises(monkeypatch):
    """认不出的接口类型必须报错，不能再 fallthrough 到某一家——那正是 404 的成因。"""
    from app import media

    async def prof():
        return _profile("openai_compat")

    monkeypatch.setattr(media, "_video_profile", prof)
    with pytest.raises(RuntimeError, match="没有对应的生视频实现"):
        asyncio.run(media.generate_video("提示词"))


def test_video_synthesis_rejects_i2v_without_image(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("缺首帧就不该提交")

    monkeypatch.setattr(dashscope, "_submit_and_poll", boom)
    with pytest.raises(RuntimeError, match="图生视频"):
        asyncio.run(dashscope.video_synthesis("https://x/compatible-mode/v1", "sk-1",
                                              "happyhorse-1.1-i2v", "提示词"))
