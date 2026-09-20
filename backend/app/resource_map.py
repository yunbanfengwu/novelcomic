"""资源包 → 真实模型名 / 模态标签 派生 + CSV 解析 + 种子加载。

派生逻辑只此一处：GET 列表时给每行补 vendor + modality + real_model_name（不落库，永远与逻辑一致）；
「插入模型管理」时按 vendor+modality 映射 purpose/provider/凭据来源。

两家厂商：
- volc（火山方舟）：配置名是营销名（"Doubao-Seedream-4.0-在线推理资源包"），需剥尾巴派生模型 slug；
  真实模型名只取**基础 slug（不带版本日期后缀）**——ARK 用不带日期的模型名即路由到最新版；
  个别要钉版本的，插入后在模型编辑框补后缀即可。
- bailian（阿里百炼）：配置名就是控制台的「模型 Code」（qwen-plus / wan2.2-t2i-flash…），
  本身即 API 可调用的模型名，不做任何派生改写。
"""
import csv
import io
import json
import re
from pathlib import Path
from typing import Any

_DATA = Path(__file__).resolve().parent / "data" / "resource_packages_seed.json"

# 非模型产品（对象存储流量/容量、扣子点数）不进资源包剩余
_NON_MODEL = ("对象存储", "扣子")

# 配置名里的营销尾巴，派生 slug 前先剥掉（长的排前面，避免子串先命中）
_STRIP = [
    "免费在线推理资源包", "在线推理资源包", "免费在线推理", "在线推理",
    "免费资源包", "资源包", "-100万tokens", "100万tokens",
    "-文生图", "文生图", "-图像编辑", "图像编辑", "免费",
]

# 模态中文标签（前端标签 + 拍寻过滤）
MODALITY_LABEL = {
    "text": "文本", "image": "图片", "video": "视频",
    "audio": "音频", "embedding": "向量", "3d": "3D",
    "math": "数学", "code": "代码", "rerank": "重排",
    "ocr": "OCR", "translate": "翻译", "other": "其它",
}

# 生成链路真正会 get_active 的 purpose。其余 purpose（数学/代码/重排/OCR/翻译/其它）
# 挂档只为登记额度与手工调用，**没有任何生成步骤会取到**——这是"选错模型"的最后一道保险。
GENERATIVE_PURPOSES = ("text", "image", "video", "tts", "embedding")

# 厂商：一行资源包属于哪家；前端按厂商过滤，插入模型管理时决定 provider/凭据
DEFAULT_VENDOR = "volc"
VENDOR_LABEL = {"volc": "火山方舟", "bailian": "阿里百炼"}


# 百炼视觉模型的模态判据（控制台「视觉模型」页把生图/生视频混在一起，这里按 Code 拆开）
# 视频族：xx2v（i2v/t2v/s2v/kf2v/v2v）、videoedit/videoretalk、数字人/动态肖像/表情驱动
_BAILIAN_VIDEO = ("i2v", "t2v", "s2v", "kf2v", "v2v", "video", "animate", "motion",
                  "liveportrait", "videoretalk", "human-", "avatar")
# 图片族：wan/wanx 系列图片档、qwen-image 系列、图像编辑/线稿上色/背景生成/抠图
_BAILIAN_IMAGE = ("t2i", "wanx", "qwen-image", "image-edit", "image-inpaint", "sketch",
                  "flux", "stable-diffusion", "background-generation", "segmentation",
                  "style-repaint", "virtualmodel", "-image")

# 专用模型族：接口形同 chat（甚至能返回 200），但能力对不上生成链路，必须与 text 彻底分开。
# 2026-08-01 事故：qwen-math-turbo 被当"文本 LLM"激活，提示词质检/要素预检/场景空间规划
# 全线 400，偶尔 200 的也吐 `\boxed{}` 数学腔与无限重复——因为它只会解数学题。
# 关键词一律带连字符锚定，避免子串误伤（"-coder" 不会命中 text-encoder）。
_SPECIALIZED = (
    ("math", ("-math", "math-", "mathstral")),
    ("code", ("-coder", "-code", "code-", "codestral", "codegeex", "starcoder")),
    ("rerank", ("rerank",)),
    ("ocr", ("ocr", "docmind", "table-recognition")),
    ("translate", ("-mt-", "qwen-mt", "translat")),
)


def specialized_modality(code: str) -> str | None:
    """模型名 → 专用模态（math/code/rerank/ocr/translate）；非专用模型返回 None。

    **专用模型判据的唯一实现**：资源包模态派生与模型档写入护栏共用这一份，
    禁止在别处另写一套关键词表。"""
    n = (code or "").lower()
    for modality, keys in _SPECIALIZED:
        if any(k in n for k in keys):
            return modality
    return None


def _bailian_modality(code: str) -> str:
    """百炼模型 Code → 模态。qwen-vl/omni 是「看图/听声说话」的 LLM，输出仍是文本，归 text。"""
    n = code.lower()
    if "embedding" in n:
        return "embedding"
    if "3d" in n:
        return "3d"
    # 视频判据优先：wan2.7-videoedit / wan2.7-i2v / happyhorse-1.1-i2v / emo-detect-v1
    # （emo 只认前缀——避免 emotion 类音频模型被误判成视频）
    if n.startswith("emo") or any(k in n for k in _BAILIAN_VIDEO):
        return "video"
    # 其次图片：wanx-v1 / wan2.6-image / qwen-image-edit-plus / wanx-sketch-to-image-lite
    if any(k in n for k in _BAILIAN_IMAGE) or n.startswith("wan"):
        return "image"
    if any(k in n for k in ("tts", "cosyvoice", "sambert", "voice", "speech",
                            "asr", "paraformer", "audio")):
        return "audio"
    # 专用族先于 text 兜底摘出去：数学/代码/重排/OCR/翻译模型不能落进「文本」，
    # 否则它们会出现在"文本 LLM"候选里被选成生成链路的主模型（2026-08-01 事故）
    return specialized_modality(n) or "text"


def modality_of(product: str, config_name: str, vendor: str = DEFAULT_VENDOR) -> str:
    if vendor == "bailian":
        return _bailian_modality(config_name)
    n = config_name.lower()
    if "embedding" in n or "嵌入" in config_name or "向量" in config_name:
        return "embedding"
    if "seedance" in n:
        return "video"
    if "3d" in n or "hitem3d" in n or "rodin" in n:
        return "3d"
    if ("seedream" in n or "seededit" in n or "文生图" in config_name
            or "图像编辑" in config_name or "图片生成" in product or "图像创作" in product):
        return "image"
    if any(k in n for k in ("cosyvoice", "tts", "voice")) or "语音" in config_name or "音色" in config_name:
        return "audio"
    return specialized_modality(n) or "text"


def real_model_name(config_name: str, vendor: str = DEFAULT_VENDOR) -> str:
    """派生 API 可调用的基础模型名（小写连字符，无版本日期后缀）。

    百炼的配置名就是模型 Code（控制台原样），直接可调，不做任何改写。"""
    if vendor == "bailian":
        return config_name.strip()
    s = config_name
    for w in _STRIP:
        s = s.replace(w, "")
    s = s.strip(" -_").lower().replace(" ", "-").replace("_", "-").replace(".", "-")
    s = re.sub(r"^doubao(\d)", r"doubao-\1", s)          # Doubao1.5 → doubao-1-5
    s = re.sub(r"(seedream|seededit)(\d)", r"\1-\2", s)  # seedream3 → seedream-3
    return re.sub(r"-+", "-", s).strip("-")


def enrich(row: dict) -> dict:
    """给一行资源包补 vendor / vendor_label / modality / modality_label / real_model_name。"""
    vendor = row.get("vendor") or DEFAULT_VENDOR
    config_name = row.get("config_name", "")
    modality = modality_of(row.get("product", ""), config_name, vendor)
    return {**row, "vendor": vendor, "vendor_label": VENDOR_LABEL.get(vendor, vendor),
            "modality": modality, "modality_label": MODALITY_LABEL[modality],
            "real_model_name": real_model_name(config_name, vendor)}


# 专用/未识别模态 → **与模态同名的 purpose**（绝不并进 text）。生成链路只 get_active
# GENERATIVE_PURPOSES 里那几个，所以这些档插进模型管理后永远不可能被质检/预检误取。
_SPECIAL_MODALITIES = ("math", "code", "rerank", "ocr", "translate", "other")

# modality → (purpose, provider, 凭据来源)。凭据来源 ark=用 ARK base/key，llm=用 LLM base/key，
# dashscope=用百炼 base/key
_PROFILE = {
    "video": ("video", "ark", "ark"),
    "image": ("image", "ark", "ark"),
    "3d": ("image", "ark", "ark"),          # 暂无 3d purpose，归 image，可在编辑框改
    "audio": ("tts", "openai_compat", "llm"),
    "embedding": ("embedding", "ark", "ark"),
    "text": ("text", "openai_compat", "ark"),  # ARK chat 走 OpenAI 兼容口，需 ARK key 才消费该资源包
    **{m: (m, "openai_compat", "ark") for m in _SPECIAL_MODALITIES},
}


# 百炼全线走 OpenAI 兼容模式（compatible-mode/v1），凭据统一 dashscope
_PROFILE_BAILIAN = {
    "video": ("video", "dashscope", "dashscope"),
    "image": ("image", "dashscope", "dashscope"),
    "3d": ("image", "dashscope", "dashscope"),
    "audio": ("tts", "dashscope", "dashscope"),
    "embedding": ("embedding", "dashscope", "dashscope"),
    "text": ("text", "dashscope", "dashscope"),
    **{m: (m, "dashscope", "dashscope") for m in _SPECIAL_MODALITIES},
}


def profile_target(modality: str, vendor: str = DEFAULT_VENDOR) -> tuple[str, str, str]:
    """资源包模态 → 插入模型管理时的 (purpose, provider, 凭据来源)。

    兜底落 `other` 而**不是** text：认不出的模型宁可挂成"其它模型"待人工归类，
    也不能悄悄变成生成链路的文本 LLM 候选。"""
    table = _PROFILE_BAILIAN if vendor == "bailian" else _PROFILE
    return table.get(modality, table["other"])


# purpose → 可以承载它的模态。写入模型档时用模型名反查模态做校验。
_PURPOSE_MODALITIES: dict[str, set[str]] = {
    "text": {"text"}, "review": {"text"},
    "image": {"image", "3d"}, "video": {"video"},
    "tts": {"audio"}, "embedding": {"embedding"},
    **{m: {m} for m in _SPECIAL_MODALITIES},
}


def infer_modalities(model_name: str) -> set[str]:
    """模型名可能属于的模态：两家判据各跑一次取并集（火山认 seedream/seedance，
    百炼认 qwen-*/wan*，同一个名字只会被其中一家认出来）。"""
    return {_bailian_modality(model_name), modality_of("", model_name, "volc")}


def purpose_conflict(purpose: str, model_name: str) -> str | None:
    """模型名与所选用途明显冲突时返回中文原因，否则 None。**写入护栏的唯一实现。**

    判据只拦「明确判出了另一个模态」的情况：两家判据都落 text 兜底 = 没把握
    （bge-m3 这种名字里没有 embedding 字样的），一律放行——宁可漏拦，不误伤。
    """
    allowed = _PURPOSE_MODALITIES.get(purpose)
    if not allowed:
        return None
    explicit = infer_modalities(model_name) - {"text"}
    if not explicit or explicit & allowed:
        return None
    got = "/".join(MODALITY_LABEL.get(m, m) for m in sorted(explicit))
    want = "/".join(MODALITY_LABEL.get(m, m) for m in sorted(allowed))
    return (f"模型「{model_name}」看起来是{got}模型，不能挂到「{want}」用途下。"
            f"请改选与之匹配的模型类型；确认判断有误可在 extra 里加 "
            f'{{"force_purpose": true}} 强制保存。')


def display_name(config_name: str, vendor: str = DEFAULT_VENDOR) -> str:
    """插入模型管理时的显示名：剥掉营销尾巴，留干净的模型名。"""
    if vendor == "bailian":
        return f"百炼 {config_name.strip()}"
    s = config_name
    for w in ("免费在线推理资源包", "在线推理资源包", "免费资源包", "资源包", "-100万tokens", "免费"):
        s = s.replace(w, "")
    return s.strip(" -") or config_name


def _num(v: str) -> float:
    try:
        return round(float(str(v).replace(",", "").strip()), 4)
    except (TypeError, ValueError):
        return 0.0


def _pick(d: dict[str, str], *names: str) -> str:
    """按候选列名取值（各家控制台导出列名不统一，取第一个非空的）。"""
    for n in names:
        v = (d.get(n) or "").strip()
        if v:
            return v
    return ""


def _quota_pair(s: str) -> tuple[float, float]:
    """解析百炼额度单元格：'剩1,000,000/共1,000,000' → (余量, 总量)；只有一个数则视为两者相同。"""
    nums = [float(x.replace(",", "")) for x in re.findall(r"[\d,]+(?:\.\d+)?", s or "") if x.strip(",")]
    if len(nums) >= 2:
        return nums[0], nums[1]
    if len(nums) == 1:
        return nums[0], nums[0]
    return 0.0, 0.0


def parse_csv(text: str, vendor: str = DEFAULT_VENDOR) -> list[dict[str, Any]]:
    """解析厂商控制台导出的资源包 CSV（火山=资源包总览，百炼=免费额度/Token Plan）。"""
    if vendor == "bailian":
        return _parse_bailian_csv(text)
    return _parse_volc_csv(text)


def _parse_bailian_csv(text: str) -> list[dict[str, Any]]:
    """百炼免费额度/资源包 CSV：一行 = 一个模型 Code 的额度。

    控制台没有实例ID，用 bailian:<模型Code> 当主键（同模型重传即整行覆盖）；
    列名按控制台可能的几种写法兜底取值。"""
    out: list[dict[str, Any]] = []
    for raw in csv.DictReader(io.StringIO(text)):
        d = {(k or "").strip(): (v or "") for k, v in raw.items()}
        code = _pick(d, "模型Code", "模型 Code", "模型code", "模型名称", "模型", "配置名称")
        if not code:
            continue
        remaining, total = _quota_pair(_pick(d, "免费额度剩余量", "剩余量", "余量", "额度"))
        if _pick(d, "总量"):
            total = _num(_pick(d, "总量"))
        out.append({
            "vendor": "bailian",
            "instance_id": _pick(d, "实例ID") or f"bailian:{code}",
            "product": _pick(d, "产品") or "阿里云百炼",
            "config_name": code,
            "spec": _pick(d, "规格"),
            "spec_unit": _pick(d, "规格单位") or "tokens",
            "total": total,
            "remaining": remaining,
            "status": _pick(d, "状态"),
            "purchased_at": _pick(d, "购买时间(UTC+8)", "购买时间", "开通时间"),
            "effective_at": _pick(d, "生效时间(UTC+8)", "生效时间"),
            "expires_at": _pick(d, "过期时间", "失效时间(UTC+8)", "失效时间", "到期时间"),
            "provider_entity": _pick(d, "服务主体") or "阿里云计算有限公司",
        })
    return out


def _parse_volc_csv(text: str) -> list[dict[str, Any]]:
    """解析火山导出的资源包总览 CSV，只留模型类资源包。"""
    num = _num
    out: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(text))
    for d in reader:
        product = (d.get("产品") or "").strip()
        remaining = num(d.get("余量"))
        # 只排除非模型产品（对象存储/扣子）；已用完的模型包保留（前端标红 + 可删）
        if any(k in product for k in _NON_MODEL):
            continue
        out.append({
            "vendor": "volc",
            "instance_id": (d.get("实例ID") or "").strip(),
            "product": product,
            "config_name": (d.get("配置名称") or "").strip(),
            "spec": (d.get("规格") or "").strip(),
            "spec_unit": (d.get("规格单位") or "").strip(),
            "total": num(d.get("总量")),
            "remaining": remaining,
            "status": (d.get("状态") or "").strip(),
            "purchased_at": (d.get("购买时间(UTC+8)") or "").strip(),
            "effective_at": (d.get("生效时间(UTC+8)") or "").strip(),
            "expires_at": (d.get("失效时间(UTC+8)") or "").strip(),
            "provider_entity": (d.get("服务主体") or "").strip(),
        })
    return out


def seed_rows() -> list[dict[str, Any]]:
    if not _DATA.exists():
        return []
    return json.loads(_DATA.read_text(encoding="utf-8"))


_COLS = ("instance_id", "product", "config_name", "spec", "spec_unit", "total", "remaining",
         "status", "purchased_at", "effective_at", "expires_at", "provider_entity", "vendor")
_VALUES = (
    "INSERT INTO resource_packages "
    "(instance_id, product, config_name, spec, spec_unit, total, remaining, "
    " status, purchased_at, effective_at, expires_at, provider_entity, vendor) "
    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) "
)
_INSERT = _VALUES + "ON CONFLICT (instance_id) DO NOTHING"
# 手动新增/编辑一条（百炼免费额度没有 CSV 可导时用）：同 instance_id 整行覆盖
_UPSERT = _VALUES + (
    "ON CONFLICT (instance_id) DO UPDATE SET "
    "product=EXCLUDED.product, config_name=EXCLUDED.config_name, spec=EXCLUDED.spec, "
    "spec_unit=EXCLUDED.spec_unit, total=EXCLUDED.total, remaining=EXCLUDED.remaining, "
    "status=EXCLUDED.status, purchased_at=EXCLUDED.purchased_at, "
    "effective_at=EXCLUDED.effective_at, expires_at=EXCLUDED.expires_at, "
    "provider_entity=EXCLUDED.provider_entity, vendor=EXCLUDED.vendor, updated_at=now()"
)


def _row_args(r: dict[str, Any], vendor: str = DEFAULT_VENDOR) -> list[Any]:
    return [(r.get("vendor") or vendor) if c == "vendor" else r.get(c) for c in _COLS]


async def seed_if_empty(pool) -> int:
    """种子若表空则从 data/resource_packages_seed.json 补齐；一旦用户重传过 CSV（表非空）就不再补。"""
    rows = seed_rows()
    if not rows:
        return 0
    async with pool.acquire() as conn:
        if await conn.fetchval("SELECT count(*) FROM resource_packages"):
            return 0
        for r in rows:
            await conn.execute(_INSERT, *_row_args(r, "volc"))
    return len(rows)


async def replace_all(pool, rows: list[dict[str, Any]], vendor: str = DEFAULT_VENDOR) -> int:
    """重传 CSV：**只替换该厂商**的行（另一家的资源包不受影响），余量随之刷新。"""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM resource_packages WHERE coalesce(vendor,'volc')=$1", vendor
            )
            for r in rows:
                await conn.execute(_INSERT, *_row_args(r, vendor))
    return len(rows)


async def upsert_one(pool, row: dict[str, Any]) -> dict[str, Any]:
    """手动新增/更新一条资源包（百炼控制台无导出时的兜底入口）。"""
    await pool.execute(_UPSERT, *_row_args(row, row.get("vendor") or DEFAULT_VENDOR))
    saved = await pool.fetchrow(
        "SELECT * FROM resource_packages WHERE instance_id=$1", row["instance_id"]
    )
    return enrich(dict(saved))
