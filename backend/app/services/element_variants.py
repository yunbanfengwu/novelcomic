"""核心要素多形态（身份/阶段/形态）：一个要素可有多张设定图，每张带标签(tag)与触发剧情(desc)。
生成图/视频时按镜头剧情自动选对应形态的图（蜘蛛侠平时/变身后；乞丐→皇后…）。

设计要点（用户 2026-07-15 定稿）：
- **惰性兼容**：无 `variants` 的老要素 = 单一默认形态，行为与今天完全一致，不迁移存量数据。
  下游统一走 `variants_of()`：无形态时合成一个"默认"形态，读点无需分叉。
- **主形态镜像**：主/默认形态的 sheet_url / 外貌提示词 同步镜像回 meta 顶层，老读点
  （图库 projects.py / 缩略图 / 火山 ark 名匹配）零改动仍读 meta.sheet_url。
- **指纹按形态独立**：每形态各自 sheet_fingerprint，改某形态外貌只重画那一张。

用户 2026-07-15 二次简化：不再要求先命名「形态」+ 写「触发剧情」——直接加图，每张图只带一句可选
描述(desc，仍供弱匹配自动选图，人工可覆盖)；tag 退为可选/自动。新增 inherit_ref（默认 True）：
生成该图时把「上一张图」当参考喂给出图模型 + 提示词加「相貌/风格沿用参考图」，关掉用于整容/变身/换景。

数据形状 content_elements.meta.variants:
  [{"id":slug, "tag":"乞丐"(可选), "desc":"一句描述，供弱匹配自动选图", "inherit_ref":true,
    "外貌提示词":"english…", "sheet_url":url|None, "sheet_fingerprint":fp,
    "sheet_prompt":..., "sheet_negative":...}]
"""
import re
from typing import Any

# 形态可携带的、与"该形态那张图"绑定的字段（写回/镜像时统一处理）
SHEET_FIELDS = ("外貌提示词", "sheet_url", "sheet_fingerprint", "sheet_prompt", "sheet_negative",
                "sheet_prompt_user", "sheet_prompt_anchor")

# 折叠回单图时，把这张图的描述镜像到顶层 meta.sheet_desc，使单图也能保留「图下描述」
DESC_MIRROR = "sheet_desc"

_SLUG_RE = re.compile(r"[^0-9a-z一-鿿]+")


def _meta(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def has_variants(meta: dict[str, Any]) -> bool:
    """要素是否显式定义了多形态（≥1 条 variants）。"""
    vs = meta.get("variants")
    return isinstance(vs, list) and len(vs) > 0


def default_variant(meta: dict[str, Any]) -> dict[str, Any]:
    """把"无形态"的老要素合成成单一默认形态：字段全部取 meta 顶层镜像值。
    desc 取顶层镜像 meta.sheet_desc（单图也能保留图下描述）。"""
    return {"id": "default", "tag": "", "desc": meta.get(DESC_MIRROR) or "",
            **{k: meta.get(k) for k in SHEET_FIELDS}}


def variants_of(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """统一形态列表：显式 variants 原样返回；无则合成一个默认形态（惰性兼容）。"""
    vs = meta.get("variants")
    if isinstance(vs, list) and vs:
        return [v for v in vs if isinstance(v, dict)]
    return [default_variant(meta)]


def primary_variant(meta: dict[str, Any]) -> dict[str, Any]:
    """主/默认形态：首个有图的形态，否则第一条。镜像回顶层的就是它。"""
    vs = variants_of(meta)
    return next((v for v in vs if v.get("sheet_url")), vs[0])


def find_variant(meta: dict[str, Any], vid: str | None) -> dict[str, Any] | None:
    if not vid:
        return None
    return next((v for v in variants_of(meta) if v.get("id") == vid), None)


def _bigrams(s: str) -> set[str]:
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _match_score(v: dict[str, Any], corpus: str) -> int:
    """某形态与本镜剧本文本的贴合度：标签整词/二连字命中权重最高，触发剧情二连字重叠次之。
    用中文二连字重叠而非整词匹配——触发剧情多为无标点长句，整词切分会漏。"""
    tag = (v.get("tag") or "").strip()
    score = 6 if tag and tag in corpus else 0
    score += 3 * sum(1 for g in _bigrams(tag) if g in corpus)
    score += sum(1 for g in _bigrams((v.get("desc") or "").strip()) if g in corpus)
    return score


def pick_variant(
    meta: dict[str, Any], corpus: str = "", chosen_id: str | None = None
) -> dict[str, Any]:
    """选形态：①显式 chosen_id 命中→它（镜级预检 LLM 的权威选择）；
    ②按 tag/触发剧情与本镜剧本关键词打分，最高者（确定性兜底，零 LLM）；③主形态。"""
    vs = variants_of(meta)
    if len(vs) == 1:
        return vs[0]
    chosen = find_variant(meta, chosen_id)
    if chosen:
        return chosen
    if corpus:
        scored = max(vs, key=lambda v: _match_score(v, corpus))
        if _match_score(scored, corpus) > 0:
            return scored
    return primary_variant(meta)


def slugify_tag(tag: str, existing: list[str]) -> str:
    """标签→稳定 id（形态标识）。同名去重加序号；空标签退化为 v{n}。"""
    base = _SLUG_RE.sub("-", (tag or "").strip().lower()).strip("-") or "v"
    vid, n = base, 2
    while vid in existing:
        vid, n = f"{base}-{n}", n + 1
    return vid


def new_variant(tag: str, desc: str = "", appearance: str = "", existing: list[str] | None = None,
                inherit_ref: bool = True) -> dict[str, Any]:
    return {
        "id": slugify_tag(tag or "img", existing or []),
        "tag": (tag or "").strip(),
        "desc": (desc or "").strip(),
        "inherit_ref": inherit_ref,
        "外貌提示词": (appearance or "").strip(),
        "sheet_url": None,
        "sheet_fingerprint": None,
    }


def inherit_enabled(variant: dict[str, Any]) -> bool:
    """该图是否「沿用上一张」（默认开；仅显式 False 才关，用于整容/变身/换景）。"""
    return variant.get("inherit_ref", True) is not False


def inherit_source_url(meta: dict[str, Any], variant_id: str | None) -> str | None:
    """目标图要「沿用」的那张图的 URL：列表中它前面最近一张有图的形态；找不到则退主形态。
    目标即主形态/首图（前面无图）时返回 None——首图无可继承源。"""
    vs = variants_of(meta)
    idx = next((i for i, v in enumerate(vs) if v.get("id") == variant_id), 0)
    for j in range(idx - 1, -1, -1):
        if vs[j].get("sheet_url"):
            return vs[j]["sheet_url"]
    prim = primary_variant(meta)
    if prim.get("id") != vs[idx].get("id") and prim.get("sheet_url"):
        return prim["sheet_url"]
    return None


def normalize_variants(raw: Any) -> list[dict[str, Any]]:
    """把模型/前端给的 variants 规整成合法结构（补 id、去空、字段收敛）。"""
    out: list[dict[str, Any]] = []
    ids: list[str] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        tag = (item.get("tag") or "").strip()
        if not tag and not item.get("外貌提示词"):
            continue
        vid = (item.get("id") or "").strip() or slugify_tag(tag, ids)
        if vid in ids:
            vid = slugify_tag(tag or vid, ids)
        ids.append(vid)
        v = {
            "id": vid, "tag": tag, "desc": (item.get("desc") or "").strip(),
            "inherit_ref": item.get("inherit_ref", True) is not False,
            "外貌提示词": (item.get("外貌提示词") or "").strip(),
            "sheet_url": item.get("sheet_url"), "sheet_fingerprint": item.get("sheet_fingerprint"),
        }
        for k in ("sheet_prompt", "sheet_negative", "profile"):
            if item.get(k) is not None:
                v[k] = item[k]
        out.append(v)
    return out


def mirror_patch(variants: list[dict[str, Any]]) -> dict[str, Any]:
    """给 UPDATE ... meta || $patch 用：写全量 variants + 把主形态镜像回顶层字段，
    使老读点（meta.sheet_url / 外貌提示词）始终指向主形态。"""
    patch: dict[str, Any] = {"variants": variants}
    if variants:
        primary = next((v for v in variants if v.get("sheet_url")), variants[0])
        for k in SHEET_FIELDS:
            patch[k] = primary.get(k)
        patch[DESC_MIRROR] = primary.get("desc") or ""
    return patch


def set_variant_sheet(
    meta: dict[str, Any], variant_id: str | None, url: str, fingerprint: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把一张图写回指定形态（无 variants 时退化为写主形态 = 顶层镜像），返回 meta|| 的 patch。
    variant_id 为空或未命中 → 落到主形态。"""
    if not has_variants(meta):
        patch = {"sheet_url": url, "sheet_fingerprint": fingerprint, **(extra or {})}
        return patch
    variants = [dict(v) for v in variants_of(meta)]
    target = next((v for v in variants if v.get("id") == variant_id), None) or variants[0]
    target["sheet_url"] = url
    target["sheet_fingerprint"] = fingerprint
    for k, val in (extra or {}).items():
        target[k] = val
    return mirror_patch(variants)


def sheet_source(variant: dict[str, Any], brief: str | None) -> str:
    """该形态设定图的指纹源（外貌提示词 + 简介）。"""
    return (variant.get("外貌提示词") or "") + "|" + (brief or "")


def effective_meta(
    meta: dict[str, Any], corpus: str = "", chosen_id: str | None = None
) -> dict[str, Any]:
    """取设定图/外貌的唯一正确入口：按剧情语料选中形态后影子覆盖回 meta
    （sheet_url/外貌提示词），下游 meta.get("sheet_url") 无需分叉即取到对应形态。
    单形态/无形态要素原样返回（行为与顶层镜像一致）。
    收敛原则（2026-07-31）：禁止再在任何取图点顶层直读 sheet_url 绕过形态选择——
    那会让多形态角色在宫格/组图/站位图里恒拿主形态图，与逐镜首帧不一致。"""
    if not has_variants(meta):
        return meta
    v = pick_variant(meta, corpus, chosen_id)
    return {**meta, "sheet_url": v.get("sheet_url"),
            "外貌提示词": v.get("外貌提示词") or meta.get("外貌提示词")}
