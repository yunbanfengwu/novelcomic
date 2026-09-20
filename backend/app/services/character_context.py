"""角色上下文单一来源（2026-07-31 收敛）。

原则：凡"角色是谁"的认知——年龄/性别、身份称谓、招牌表演、面部/发型词表、
年代锚、名册行、身份层描述——全站只允许这一份实现。
设定图装配（element_sheet）、档案生成（element_profile）、分镜装配（storyboard）、
场景站位（scene_blocking）等一律从这里引用，禁止在各自文件里另写拷贝。

词表按用途组合而非粗暴合并：真人造型卡要同时剔面部与发型（发型由独立小卡承担），
远景身份层只剔面部（发色/发长远距可见）。
"""
import json
import re
from typing import Any

import asyncpg

# 面部级特征词：真人卡剔脸、远景镜身份层过滤共用这一份
FACE_TERMS = (
    "脸", "颊", "面容", "面部", "五官", "眼", "眉", "睫", "鼻", "嘴", "唇", "牙",
    "耳", "额", "颧骨", "下巴", "胡须", "表情", "神态", "眸", "瞳", "疤", "痣", "雀斑",
)
# 发型词单列：真人无头造型卡要剔（发型走独立小卡），远景镜不剔（发色/发长远距可见）
HAIR_TERMS = ("头发", "发型", "短发", "长发", "卷发", "直发", "刘海")
# 英文外貌片段同样要过滤面部级词（ch16镜460 实锤："bright eyes/curious look"混进远景镜）
FACE_TERMS_EN = ("eye", "face", "facial", "brow", "lip", "mouth", "nose", "scar",
                 "cheek", "chin", "freckle", "gaze", "expression", "look", "smile",
                 "pupil", "iris")


def non_face_segments(text: str, include_hair: bool = False, en: bool = False) -> list[str]:
    """外貌文本按逗顿分段后剔除面部级片段。include_hair=真人卡（发型另卡）；en=兼剔英文片段。"""
    terms = FACE_TERMS + (HAIR_TERMS if include_hair else ())
    segs = [x.strip() for x in re.split(r"[，、,；;。]", text or "") if x.strip()]
    return [x for x in segs
            if not any(t in x for t in terms)
            and not (en and any(t in x.lower() for t in FACE_TERMS_EN))]


def _cfg(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else json.loads(v or "{}")


def era_anchor(project: asyncpg.Record | dict[str, Any]) -> str:
    """年代锚：优先项目 config.era（用户手填，须严格照此）；未填则据梗概/主线/画风自行推断。"""
    era = (_cfg(project["config"]).get("era") or "").strip()
    if era:
        return f"（本项目已明确设定年代/世界观，须严格照此定妆造）{era}"
    return (
        "（未显式设定年代，请依据以下信息自行判断所处时代/世界观并据此定妆造）\n"
        f"梗概：{project['synopsis'] or ''}\n主线：{project['storyline'] or ''}\n画风：{project['art_style'] or ''}"
    )


def world_clause(project: asyncpg.Record | dict[str, Any]) -> str:
    """场景/道具设定图的世界观/年代约束句（与 era_anchor 同源取 config.era，仅措辞面向生图）。
    画风块只给视觉质感，不含地域/年代/文化——缺了它场景会跑偏（中国古代出美国现代马车）。"""
    era = (_cfg(project["config"]).get("era") or "").strip()
    if era:
        return f"须严格贴合本项目设定的年代与世界观：{era}；绝不出现与之冲突的现代物或异域文化元素。"
    hint = (project["synopsis"] or project["storyline"] or "")[:60]
    return (f"须贴合本项目世界观（画风：{project['art_style'] or ''}"
            + (f"；梗概：{hint}" if hint else "") + "）；绝不穿越年代或替换文化背景。")


def character_age_gender(meta: dict, brief: str = "", character_name: str = "") -> tuple[str, str]:
    """从结构化档案优先取年龄/性别，并兼容年龄滑块与少量存量文本。"""
    profile = meta.get("profile") if isinstance(meta.get("profile"), dict) else {}
    age = str(profile.get("年龄段") or "").strip()
    if meta.get("age_years"):
        age = f"{meta['age_years']}岁"
    gender = str(profile.get("性别") or "").strip()
    if gender in ("女", "女性", "女生", "女孩", "女人", "姑娘", "female", "Female"):
        gender = "女"
    elif gender in ("男", "男性", "男生", "男孩", "男人", "男子", "male", "Male"):
        gender = "男"

    source = "、".join(
        str(x or "") for x in (character_name, meta.get("外貌提示词"), brief)
    )
    if not age:
        match = re.search(r"([一二三四五六七八九十百两\d]{1,4}\s*岁(?:左右|上下)?)", source)
        if match:
            age = match.group(1).replace(" ", "")
        else:
            for term in ("婴儿", "幼儿", "儿童", "少年", "少女", "青年", "中年", "老年", "年迈", "老者", "老人"):
                if term in source:
                    age = "老年" if term in ("年迈", "老者", "老人") else term
                    break
    if not gender:
        if any(term in source for term in (
            "婆婆", "奶奶", "祖母", "外婆", "姥姥", "母亲", "妈妈", "阿姨", "婶婶",
            "女性", "女生", "女孩", "少女", "女人", "姑娘", "女童",
        )):
            gender = "女"
        elif any(term in source for term in (
            "爷爷", "祖父", "外公", "姥爷", "父亲", "爸爸", "叔叔", "伯伯",
            "男性", "男生", "男孩", "少年", "男人", "男子", "男童",
        )):
            gender = "男"
    return age or "未设定", gender or "未设定"


def character_action_gaze(meta: dict, brief: str = "") -> tuple[str, str]:
    profile = meta.get("profile") if isinstance(meta.get("profile"), dict) else {}
    identity = "；".join(
        str(x or "").strip()
        for x in (profile.get("身份"), brief)
        if str(x or "").strip()
    ) or "该角色的身份与性格"
    action = str(profile.get("招牌动作") or "").strip()
    gaze = str(profile.get("招牌眼神") or "").strip()
    return (
        action or f"以收放幅度、重心和手部姿态明确体现「{identity}」的专属代表动作",
        gaze or f"以视线方向、眼睑张力和注视强度明确体现「{identity}」的专属眼神",
    )


def character_appellations(name: str, profile: dict | None = None, brief: str = "") -> list[str]:
    """使用大模型档案抽取的开放称谓；旧档案无该字段时保留完整名称和身份原文。"""
    profile = profile if isinstance(profile, dict) else {}
    extracted = str(profile.get("身份称谓") or "").strip()
    if extracted and extracted != "无":
        return list(dict.fromkeys(x.strip() for x in re.split(r"[、,，;/；]+", extracted) if x.strip()))
    # 不猜测、不枚举：原样保留最完整的现有文本，让生图模型仍能理解作品自创称谓。
    return list(dict.fromkeys(x for x in (name.strip(), str(profile.get("身份") or "").strip()) if x))


def identity_desc(name: str, brief: str, meta: dict) -> str:
    """分镜/首帧身份层的角色描述单一来源：档案身份要点（年龄性别/称谓）+ 简介 +（外貌提示词）。

    此前分镜链路只拼 brief+外貌，档案（PROFILE_SYS 产出）里调好的年龄/性别/身份称谓
    完全进不了分镜提示词——角色生成与分镜引用"前置不一致"的病根。招牌动作/眼神
    不在此注入：逐镜动作由剧本决定，织入会与镜头表演打架。"""
    profile = meta.get("profile") if isinstance(meta.get("profile"), dict) else {}
    bits: list[str] = []
    age, gender = character_age_gender(meta, brief, name)
    ag = "".join(x for x in (age if age != "未设定" else "",
                             {"女": "女性", "男": "男性"}.get(gender, "")) if x)
    if ag:
        bits.append(ag)
    extra = [a for a in character_appellations(name, profile, brief) if a and a != name]
    if extra:
        bits.append("、".join(extra[:3]))
    head = "，".join(bits)
    desc = brief or ""
    if meta.get("外貌提示词"):
        desc = f"{desc}（{meta['外貌提示词']}）" if desc else meta["外貌提示词"]
    if head and desc:
        return f"{head}，{desc}"
    return head or desc


def roster_line(name: str, brief: str | None, brief_len: int = 40) -> str:
    """角色名册行单一格式：`- 名：brief 截断`。拆镜/站位等喂 LLM 清单共用。"""
    return f"- {name}：{(brief or '')[:brief_len]}"


def roster_inline(name: str, brief: str | None, brief_len: int = 40) -> str:
    """角色内联格式：`名（brief 截断）`。封面关键视觉/预告片蒸馏共用。"""
    return f"{name}（{(brief or '').strip()[:brief_len]}）"


async def character_rows(
    conn: asyncpg.Connection | asyncpg.Pool, project_id: int,
    names: list[str] | None = None, limit: int | None = None,
) -> list[asyncpg.Record]:
    """取项目角色列表的单一 SQL（id/kind/name/brief/meta，按 id 序）。"""
    sql = ("SELECT id, kind, name, brief, meta FROM content_elements "
           "WHERE project_id=$1 AND kind='character'")
    args: list[Any] = [project_id]
    if names is not None:
        sql += " AND name = ANY($2::text[])"
        args.append(names)
    sql += " ORDER BY id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return await conn.fetch(sql, *args)
