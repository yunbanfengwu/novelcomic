"""模型能力档案归一化：显式声明 > 模型族推断 > 兜底。三层取值钉死。

背景（2026-09-17）：qwen-image-edit-plus 走同步多模态接口、1~3 张底图、不吃 size；
wanx/qwen-image 走异步任务——差异必须变成数据，服务端裁剪、前端渲染共用一份。
"""
import pytest

from app.services import model_caps


def test_dashscope_edit_family_infers_sync_and_three_refs():
    caps = model_caps.capabilities({"provider": "dashscope", "model_name": "qwen-image-edit-plus"})
    assert caps["transport"] == "sync"
    assert caps["refs"] == {"max": 3, "kind": "edit_base"}
    assert caps["aspects"] is None  # 比例跟随参考图


def test_dashscope_t2i_family_infers_async_no_refs():
    caps = model_caps.capabilities({"provider": "dashscope", "model_name": "qwen-image"})
    assert caps["transport"] == "async"
    assert caps["refs"]["max"] == 0


def test_explicit_overrides_inference():
    """档内声明永远优先：max_refs 列 > capabilities.refs.max > 推断。"""
    caps = model_caps.capabilities({"provider": "dashscope", "model_name": "wanx-v1",
                                    "max_refs": 2,
                                    "extra": {"capabilities": {"transport": "sync"}}})
    assert caps["refs"]["max"] == 2
    assert caps["transport"] == "sync"
    # capabilities.refs.max 也认（未配 max_refs 列时）
    caps2 = model_caps.capabilities({"provider": "dashscope", "model_name": "qwen-image",
                                     "extra": {"capabilities": {"refs": {"max": 2, "kind": "reference"}}}})
    assert caps2["refs"]["max"] == 2
    assert caps2["refs"]["kind"] == "reference"


def test_minimax_single_subject_slot():
    caps = model_caps.capabilities({"provider": "minimax", "model_name": "image-01"})
    assert caps["refs"]["max"] == 1
    assert caps["refs"]["kind"] == "subject"
    assert "16:9" in caps["aspects"]


def test_ark_seedream4_multi_reference():
    caps = model_caps.capabilities({"provider": "ark", "model_name": "doubao-seedream-4-0-250828"})
    assert caps["refs"] == {"max": 4, "kind": "reference"}


def test_unknown_provider_falls_back_to_default_cap():
    """认不出的模型不猜：ref_cap 交给调用方的 provider 默认值。"""
    p = {"provider": "new_vendor", "model_name": "mystery-1"}
    assert model_caps.ref_cap(p, 4) == 4
    assert model_caps.ref_kind(p) == "none"


def test_ref_cap_matches_legacy_behaviour():
    """_ref_cap 的旧语义兼容：max_refs>0 用它，否则 provider 默认。"""
    assert model_caps.ref_cap({"max_refs": 2}, 4) == 2
    assert model_caps.ref_cap({"max_refs": None, "provider": "minimax",
                               "model_name": "image-01"}, 4) == 1


def test_ref_cap_zero_means_no_refs():
    """capabilities.refs.max=0（纯文生图）也能压过 default——不该把图硬塞给不吃图的模型。"""
    caps = model_caps.capabilities({"provider": "dashscope", "model_name": "qwen-image",
                                    "extra": {"capabilities": {"refs": {"max": 0}}}})
    assert caps["refs"]["max"] == 0
