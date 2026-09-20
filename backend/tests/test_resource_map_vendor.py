"""资源包厂商维度：百炼 CSV 解析 + 模态/模型名派生，且不影响火山原路径。"""
from app import resource_map as rm

BAILIAN_CSV = (
    "模型Code,免费额度剩余量,过期时间,状态\n"
    'qwen3.7-plus,"剩1,000,000/共1,000,000",2026/10/31,未开启\n'
    'wan2.2-t2i-flash,"剩500/共1,000",2026/12/01,未开启\n'
    'text-embedding-v4,"剩100/共100",2026/10/31,未开启\n'
    'qwen3-tts-flash,"剩10/共10",2026/10/31,未开启\n'
)

VOLC_CSV = (
    "产品,实例ID,配置名称,规格,规格单位,总量,余量,状态,"
    "购买时间(UTC+8),生效时间(UTC+8),失效时间(UTC+8),服务主体\n"
    "豆包大模型,Ark_1,Doubao-Seedream-4.0-在线推理资源包-100万tokens,1000,千tokens,"
    "1000,800,生效中,2026-07-09,2026-07-09,2026-10-06,火山\n"
)


def test_bailian_csv_quota_and_key():
    rows = {r["config_name"]: r for r in rm.parse_csv(BAILIAN_CSV, "bailian")}
    assert set(rows) == {"qwen3.7-plus", "wan2.2-t2i-flash", "text-embedding-v4", "qwen3-tts-flash"}
    plus = rows["qwen3.7-plus"]
    assert plus["vendor"] == "bailian"
    assert plus["instance_id"] == "bailian:qwen3.7-plus"   # 百炼无实例ID，用模型 Code 当主键
    assert (plus["remaining"], plus["total"]) == (1000000.0, 1000000.0)
    assert rows["wan2.2-t2i-flash"]["remaining"] == 500.0
    assert plus["expires_at"] == "2026/10/31"


def test_bailian_modality_and_model_name():
    got = {r["config_name"]: rm.enrich(r) for r in rm.parse_csv(BAILIAN_CSV, "bailian")}
    assert got["qwen3.7-plus"]["modality"] == "text"
    assert got["wan2.2-t2i-flash"]["modality"] == "image"
    assert got["text-embedding-v4"]["modality"] == "embedding"
    assert got["qwen3-tts-flash"]["modality"] == "audio"
    # 模型 Code 即 API 可调用模型名，不做任何改写
    assert got["qwen3.7-plus"]["real_model_name"] == "qwen3.7-plus"
    assert got["qwen3.7-plus"]["vendor_label"] == "阿里百炼"


def test_bailian_vision_models_split_image_vs_video():
    """控制台「视觉模型」页把生图/生视频混在一起，按 Code 拆开（样本取自百炼免费额度页）。"""
    image = ["wanx-v1", "wan2.6-image", "qwen-image", "qwen-image-edit-plus",
             "qwen-image-edit-plus-2025-10-30", "wanx-sketch-to-image-lite",
             "wan2.2-t2i-flash", "wanx-background-generation-v2"]
    video = ["wan2.7-i2v", "wan2.7-videoedit", "happyhorse-1.1-i2v", "emo-detect-v1",
             "liveportrait-detect", "wan2.2-t2v-plus", "wan2.5-s2v", "videoretalk"]
    for code in image:
        assert rm._bailian_modality(code) == "image", code
    for code in video:
        assert rm._bailian_modality(code) == "video", code
    # 视觉理解类仍是文本输出，别被 vl/omni 带偏
    for code in ["qwen-vl-max", "qwen3-vl-32b-thinking", "qwen-omni-turbo"]:
        assert rm._bailian_modality(code) == "text", code


def test_bailian_profile_target_uses_dashscope():
    assert rm.profile_target("text", "bailian") == ("text", "dashscope", "dashscope")
    assert rm.profile_target("audio", "bailian") == ("tts", "dashscope", "dashscope")
    assert rm.display_name("qwen-plus", "bailian") == "百炼 qwen-plus"


def test_specialized_models_never_fall_into_text():
    """数学/代码/重排/OCR/翻译模型必须独立成模态——落进 text 就会出现在
    「文本 LLM」候选里被选成生成链路主模型（2026-08-01 qwen-math-turbo 事故）。"""
    cases = {
        "qwen-math-turbo": "math", "qwen-math-plus": "math", "Qwen/Qwen2.5-Math-72B": "math",
        "qwen3-coder-plus": "code", "deepseek-coder": "code", "codestral-latest": "code",
        "gte-rerank-v2": "rerank", "qwen-vl-ocr": "ocr", "qwen-mt-turbo": "translate",
    }
    for code, modality in cases.items():
        assert rm._bailian_modality(code) == modality, code
        assert rm.modality_of("", code, "volc") == modality, code
    # 通用对话模型不能被专用判据误伤（"qwen-max" 不含 "-math"，"encoder" 不含 "-coder"）
    for code in ["qwen-plus", "qwen-max", "qwen-turbo", "qwen-long", "text-encoder-v1"]:
        assert rm.specialized_modality(code) is None, code


def test_specialized_modality_maps_to_own_purpose():
    """专用模态挂到同名 purpose，绝不并进 text；认不出的模态兜底落 other 而非 text。"""
    assert rm.profile_target("math", "bailian") == ("math", "dashscope", "dashscope")
    assert rm.profile_target("code", "volc") == ("code", "openai_compat", "ark")
    assert rm.profile_target("不认识的模态", "bailian")[0] == "other"
    assert rm.profile_target("不认识的模态", "volc")[0] == "other"
    for purpose, _, _ in (rm.profile_target(m, "bailian") for m in
                          ("math", "code", "rerank", "ocr", "translate", "other")):
        assert purpose not in rm.GENERATIVE_PURPOSES, purpose


def test_purpose_conflict_guard():
    """写入护栏：判出另一个明确模态才拦，判不出（落 text 兜底）一律放行。"""
    assert rm.purpose_conflict("text", "qwen-math-turbo")          # 事故本体，必须拦
    assert rm.purpose_conflict("text", "doubao-seedream-4-0")      # 生图模型挂文本也拦
    assert rm.purpose_conflict("math", "qwen-plus") is None        # text 兜底=没把握，放行
    assert rm.purpose_conflict("video", "happyhorse-1.1-i2v") is None
    assert rm.purpose_conflict("image", "qwen-image") is None
    assert rm.purpose_conflict("image", "doubao-seedream-4-0") is None
    assert rm.purpose_conflict("embedding", "BAAI/bge-m3") is None  # 名里无 embedding，不误伤
    assert rm.purpose_conflict("tts", "FunAudioLLM/CosyVoice2-0.5B") is None
    assert rm.purpose_conflict("math", "qwen-math-turbo") is None   # 归到数学就正确
    assert "数学" in rm.purpose_conflict("text", "qwen-math-turbo")


def test_volc_path_unchanged():
    row = rm.enrich(rm.parse_csv(VOLC_CSV)[0])
    assert row["vendor"] == "volc" and row["vendor_label"] == "火山方舟"
    assert row["real_model_name"] == "doubao-seedream-4-0"   # 剥营销尾巴 + 无日期后缀
    assert row["modality"] == "image"
    assert rm.profile_target(row["modality"], row["vendor"]) == ("image", "ark", "ark")
    assert rm.display_name(row["config_name"], row["vendor"]) == "Doubao-Seedream-4.0"
