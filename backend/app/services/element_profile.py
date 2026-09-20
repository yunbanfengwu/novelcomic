"""角色档案后置补档：据项目年代背景 + 角色设定，生成结构化档案
（年龄段/性别/身份/时代服饰/体貌）与派生的中文外貌提示词（标签短语式，精炼）。

设计要点：
- 批量抽取（pipeline/pipeline_stream）不再产外貌——避免单次输出膨胀，且抽取时无年代锚易生"古装现代脸"；
  外貌改由此后置逐角色生成，一次一调用、上下文聚焦、可贴合年代。
- 年代锚优先取项目 config.era（用户手填，最强开关）；未填则据梗概/主线/画风自行推断。
- 外貌提示词=中文标签短语（用户 2026-07-16 定稿）：内容外貌用中文、只有真正的专业术语才夹英文；
  画风/版式/质量锚词是独立英文块（style/sheet/quality），不在此。_norm_prompt 仅兜底夹用英文时的连字符。
"""
import json
import re
from typing import Any

import asyncpg

from .. import llm
from . import element_variants as ev
from .character_context import era_anchor
from .persona_traits import APPEARANCE_DIMS, traits_table

__all__ = ["era_anchor"]  # 单一实现在 character_context，此处再导出兼容旧 import 路径

# 经真实项目（古典奇幻/中世纪史诗/科幻/民国注入）三轮验证定稿：标签短语式、年龄前置、
# 年代贴合、生物免服饰、禁情绪词。残留的空格连字符由 _norm_prompt 兜底归一。
PROFILE_SYS = """你是资深角色设定师兼生图提示词工程师。为给定角色补全一张"结构化角色档案"，供后续出设定图使用。
硬约束：
① 事实边界：严格依据【角色设定】（名称/简介/处境目标关系）与【项目年代背景】，不虚构与其身份冲突的信息；简介未写明处可合理补全，但年龄/性别/身份须贴合简介与剧情。
② 年代贴合（最重要）：服饰、发型、配饰、妆造必须契合【项目年代背景】的时代/世界观，且用该年代的说法——古代或古典奇幻绝不出现现代物（拉链/眼镜/手表/运动鞋/腰包 fanny pack/夹克 等），改用同功能的年代物（束带布囊/长袍/靴）；中世纪西式奇幻用该时代的束腰长袍/斗篷/皮甲；科幻/未来按其设定材质。宁可朴素，不可穿越。非人角色（生物/器物）时代服饰填"无"。
   ——【现有外貌提示词】只作面部/发色/体型/伤疤/信物等**身份特征**的参考；其服饰与年代若与【项目年代背景】冲突（如现有写 1920s 而项目是古典奇幻），一律以项目年代背景为准，重写服饰妆造，绝不沿用旧的错年代穿着。
③ 外貌提示词：中文，标签短语式（顿号「、」分隔的名词短语，精炼，不要整句、不要"他/她是…"），顺序为【年龄+性别】→【贴合年代的服饰妆造】→【发型发色/眼睛/脸型体型】→【标志性特征/随身信物】。要求：
   - 只写可见的静态外形，禁止情绪/气质/氛围/性格词（如 洒脱、严肃神情、神秘气场、坚定、勇敢 之类一律不要）；
   - 不写动作、表情、场景、镜头、画风；
   - 内容外貌一律用中文；仅当某专业术语确无贴切中文（少数）时才夹用英文原词，绝不整句英文。
④ 身份称谓（开放识别，不得枚举套模板）：结合角色完整名称、简介、关系和剧情语境，提取对塑造形象有意义的原始称谓，如亲属称谓、江湖称号、职业尊称、阶级/族群称谓等。必须保留作品中的原词，可有多个，用“、”分隔；没有则填“无”。不得仅将“婆婆”压缩为“老人”，也不得受示例限制，任何作品自创称谓都应自行理解并接纳。
⑤ 表演身份锚点：必须分别给出该角色独有的【招牌动作】与【招牌眼神】，二者须综合身份称谓、身份、性格与处境设计成可直接画出的具体视觉描述，不得写“符合性格的动作/眼神”等空话。含蓄害羞者应是收敛姿态、回避或偷看的视线；侠女应是有武器控制感的警戒站姿与稳定锐利目光，二者绝不能套用同一种表演。招牌动作不写场景、镜头和光线。
⑥ 形象原创性（红线，绝不可破）：严禁直接使用或复刻任何真实存在的公众人物（明星/演员/歌手/名人/政要/网红等）的专属长相——不得照搬其可被辨认为某个具体真人的五官组合或整体面孔，中英文提示词里都不得出现任何真人姓名或"长得像XX""XX同款脸""某某即视感"之类指向特定真人的表述。只允许借鉴其大致气质路线，或采用大众化、不专属于某一个人的单点特征（如 大嘴、瓜子脸、浓眉、高鼻梁、丹凤眼 等谁都可能有的普通特征），把这些普通特征重新组合成一个**原创、认不出是哪个真人**的虚拟角色。
⑦ 多形态（重要）：判断该角色是否存在身份/阶段/形态的**显著外形变化**——如变身（平民↔英雄/超级英雄战衣）、境遇剧变（乞丐↔皇后）、大跨度年龄（少年↔暮年）、易容伪装等，凡"看起来明显不同、需各自一张设定图"的形态各出一条；只有单一稳定形象则只出一条。给出【已有形态】时，须为每个已有形态各出一条、沿用其标签与触发剧情，不擅自增删形态。列表首条为最主要/最常见形态。③④⑤⑥的规则对每个形态都要满足。
⑧ 严格只输出 JSON，字段齐全，中文值：
{"variants":[{"标签":"该形态简短名，如 乞丐/皇后/变身后；单一形象填 默认", "触发":"何时呈现此形态的一句话剧情条件（供按剧情自动选图匹配）", "年龄段":"尽量具体，如 十六岁少年 / 二十岁上下 / 七旬老者", "性别":"男/女/其他/未知", "身份称谓":"从原作语境提取并原样保留的称谓，多个用顿号分隔，无则填 无", "身份":"职业或社会身份", "时代服饰":"贴合年代的服饰妆造一句话（非人填 无）", "体貌":"发型发色/眼睛/体型/标志物 一句话", "招牌动作":"符合称谓、身份和性格、可直接绘制的具体代表动作", "招牌眼神":"符合称谓、身份和性格、可直接绘制的具体视线与眼部状态", "外貌提示词":"中文标签短语式外貌描述（顿号分隔，精炼）"}]}"""

# 结构化档案字段（外貌提示词单独落 meta.外貌提示词，与既有生图链路复用）
PROFILE_FIELDS = (
    "年龄段", "性别", "身份称谓", "身份", "时代服饰", "体貌", "招牌动作", "招牌眼神",
)

_HYPHEN = re.compile(r"(?<=\w) - (?=\w)")


def _norm_prompt(s: str) -> str:
    """英文外貌提示词连字符归一：'sixteen - year - old' → 'sixteen-year-old'（doubao 顽固癖好，代码侧兜底）。"""
    return _HYPHEN.sub("-", (s or "").strip())


def _user(project: asyncpg.Record, elem: asyncpg.Record, hints: str, existing: list[dict] | None,
          traits: str = "") -> str:
    state = elem["state"] if isinstance(elem["state"], dict) else json.loads(elem["state"] or "{}")
    st = "；".join(f"{k}:{v}" for k, v in state.items()) or "（无）"
    meta = elem["meta"] if isinstance(elem["meta"], dict) else json.loads(elem["meta"] or "{}")
    forms = ""
    if existing:
        forms = "\n【已有形态】" + "；".join(
            f"{v.get('tag') or '默认'}（{v.get('desc') or '无触发说明'}）" for v in existing)
    trait_block = (
        f"【年龄段体貌参考】（按角色年龄段对号采用，体型/发量/发际线须与之相符，勿逆龄）\n{traits}\n"
        if traits else "")
    age_line = (f"【角色年龄】{meta['age_years']}岁（用户手设，年龄段/体貌须照此，勿逆龄勿老化）\n"
                if meta.get("age_years") else "")
    return (
        f"【项目】{project['title']}\n【项目年代背景】{era_anchor(project)}\n\n"
        f"【角色】{elem['name']}\n【简介】{elem['brief'] or '（无）'}\n{age_line}【处境/目标/关系】{st}\n"
        f"【现有外貌提示词】{meta.get('外貌提示词') or '（无）'}{forms}\n"
        f"{trait_block}"
        f"【补充要点】{(hints or '').strip() or '（无）'}\n\n"
        "请补全该角色的结构化档案（如有多形态则逐形态给出）。"
    )


async def gen_element_profile(
    pool: asyncpg.Pool, project_id: int, element_id: int, hints: str = "", save: bool = True
) -> dict[str, Any]:
    """生成角色结构化档案 + 派生英文外貌提示词，并识别多形态（身份/阶段/变身）。
    - 单一形象：写回 meta.profile 与 meta.外貌提示词（与旧行为一致，不产生 variants）。
    - 多形态：写回 meta.variants（每形态各带 profile/外貌提示词/触发剧情），主形态镜像回顶层，
      供生成图/视频时按剧情自动选图。外貌变更令设定图指纹失配，下次自动重画（补档后重画）。"""
    async with pool.acquire() as conn:
        elem = await conn.fetchrow(
            "SELECT * FROM content_elements WHERE id=$1 AND project_id=$2", element_id, project_id
        )
        if not elem:
            raise ValueError("要素不存在")
        if elem["kind"] not in ("character", "item"):
            raise ValueError("仅角色与关键道具支持档案补全")
        project = await conn.fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
        # 人物特征库（渐进式）：外貌档案只取 体态+发量 两维，声音/言语维不进此提示词
        traits = await traits_table(conn, APPEARANCE_DIMS) if elem["kind"] == "character" else ""

    # 关键道具（法宝/信物/器物）走物件档案：材质/形制/纹样/年代贴合 + 中文外貌标签（无多形态）
    if elem["kind"] == "item":
        return await gen_prop_profile(pool, project_id, element_id, hints, save)

    meta = elem["meta"] if isinstance(elem["meta"], dict) else json.loads(elem["meta"] or "{}")
    existing = ev.variants_of(meta) if ev.has_variants(meta) else []
    data = await llm.chat_json(
        PROFILE_SYS, _user(project, elem, hints, existing, traits), temperature=0.5, max_tokens=1600)

    raw = [x for x in (data.get("variants") or []) if isinstance(x, dict)]
    if not raw:  # 模型未按新格式给 variants → 兼容旧单档案格式兜底
        raw = [data] if data.get("外貌提示词") or data.get("年龄段") else []
    variants: list[dict[str, Any]] = []
    ids: list[str] = []
    for item in raw:
        tag = (item.get("标签") or "").strip()
        tag = "" if tag == "默认" else tag
        prof = {k: (str(item.get(k) or "")).strip() for k in PROFILE_FIELDS}
        appearance = _norm_prompt(item.get("外貌提示词") or "")
        prev = next((v for v in existing if (v.get("tag") or "").strip() == tag), None)
        vid = (prev or {}).get("id") or ev.slugify_tag(tag or "default", ids)
        ids.append(vid)
        variants.append({
            "id": vid, "tag": tag, "desc": (item.get("触发") or "").strip(),
            "profile": prof, "外貌提示词": appearance,
            "sheet_url": (prev or {}).get("sheet_url"),
            "sheet_fingerprint": (prev or {}).get("sheet_fingerprint"),
        })
    if not variants:
        raise ValueError("档案生成为空，请重试")

    multi = len(variants) >= 2 or bool(existing)
    # 由单图老要素首次拆出多形态：把原顶层图并入主形态，避免图库瞬间空掉（外貌已变→仍会自动重画）
    if multi and not existing and not variants[0].get("sheet_url"):
        variants[0]["sheet_url"] = meta.get("sheet_url")
        variants[0]["sheet_fingerprint"] = meta.get("sheet_fingerprint")
    primary = variants[0]

    if save:
        if multi:
            patch = ev.mirror_patch(variants)
            patch["profile"] = primary["profile"]
        else:
            patch = {"profile": primary["profile"], "外貌提示词": primary["外貌提示词"]}
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE content_elements SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
                element_id, json.dumps(patch, ensure_ascii=False),
            )
    return {"profile": primary["profile"], "外貌提示词": primary["外貌提示词"],
            "variants": variants if multi else []}


# ═══════════ 关键道具（item）物件档案补全 ═══════════
# 道具此前无档案补全，设定图只吃抽取时的 brief（薄则泛化、易穿越年代）。补一张结构化物件档案，
# 与角色档案同源：年代锚驱动材质/形制/纹样，产出中文外貌标签落 meta.外貌提示词，复用既有出图链路。
PROP_PROFILE_SYS = """你是资深道具/器物设定师兼生图提示词工程师。为给定关键道具补全一张"结构化物件档案"，供后续出单体设定图使用。
硬约束：
① 事实边界：严格依据【道具设定】（名称/简介/剧情作用）与【项目年代背景】，不虚构与其身份/功能冲突的信息；简介未写明处可据世界观合理补全。
② 年代/世界观贴合（最重要）：材质、形制、纹样、工艺必须契合【项目年代背景】的时代/世界观——古代或古典奇幻绝不出现现代工业件（螺丝/塑料/电镀/喷漆/二维码/合成材料）与异域文化元素，改用同世界观的材质工艺（青铜/玉石/大漆/锻铁/皮革/符纹）；科幻/未来按其设定材质（合金/能量/全息）。宁可朴素，不可穿越。
③ 外貌提示词：中文，标签短语式（顿号「、」分隔的名词短语，精炼，不要整句、不要"它是…"），顺序为【物件类别】→【材质与工艺】→【形制结构】→【纹样/装饰/铭文】→【标志性细节/使用痕迹】。要求：
   - 只写可见的静态外形，禁止功能/剧情/氛围/情绪/威力词（如 强大、传说级、魔法光环、上古凶器 之类一律不要）；
   - 不写人物、场景、镜头、画风；单体物件本身；
   - 内容外貌一律用中文；仅当某专业术语确无贴切中文时才夹用英文原词，绝不整句英文。
④ 严格只输出 JSON，字段齐全，中文值：
{"材质":"主体材质", "形制":"一句话结构造型", "纹样工艺":"表面纹样/装饰/工艺", "年代贴合":"如何契合项目年代/世界观的一句话", "外貌提示词":"中文标签短语式物件外貌（顿号分隔，精炼）"}"""

PROP_PROFILE_FIELDS = ("材质", "形制", "纹样工艺", "年代贴合")


def _prop_user(project: asyncpg.Record, elem: asyncpg.Record, hints: str) -> str:
    state = elem["state"] if isinstance(elem["state"], dict) else json.loads(elem["state"] or "{}")
    st = "；".join(f"{k}:{v}" for k, v in state.items()) or "（无）"
    meta = elem["meta"] if isinstance(elem["meta"], dict) else json.loads(elem["meta"] or "{}")
    return (
        f"【项目】{project['title']}\n【项目年代背景】{era_anchor(project)}\n\n"
        f"【道具】{elem['name']}\n【简介】{elem['brief'] or '（无）'}\n【处境/剧情作用/关系】{st}\n"
        f"【现有外貌提示词】{meta.get('外貌提示词') or '（无）'}\n"
        f"【补充要点】{(hints or '').strip() or '（无）'}\n\n"
        "请补全该道具的结构化物件档案。"
    )


async def gen_prop_profile(
    pool: asyncpg.Pool, project_id: int, element_id: int, hints: str = "", save: bool = True
) -> dict[str, Any]:
    """生成关键道具的结构化物件档案 + 派生英文外貌提示词（单形态，落 meta.profile / meta.外貌提示词）。"""
    async with pool.acquire() as conn:
        elem = await conn.fetchrow(
            "SELECT * FROM content_elements WHERE id=$1 AND project_id=$2", element_id, project_id
        )
        if not elem:
            raise ValueError("要素不存在")
        if elem["kind"] != "item":
            raise ValueError("gen_prop_profile 仅处理关键道具（item）")
        project = await conn.fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)

    data = await llm.chat_json(
        PROP_PROFILE_SYS, _prop_user(project, elem, hints), temperature=0.4, max_tokens=800)
    appearance = _norm_prompt(data.get("外貌提示词") or "")
    if not appearance:
        raise ValueError("档案生成为空，请重试")
    prof = {k: (str(data.get(k) or "")).strip() for k in PROP_PROFILE_FIELDS}

    if save:
        patch = {"profile": prof, "外貌提示词": appearance}
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE content_elements SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
                element_id, json.dumps(patch, ensure_ascii=False),
            )
    return {"profile": prof, "外貌提示词": appearance, "variants": []}
