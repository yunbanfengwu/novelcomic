"""要素设定图：角色身份版（三视图/特写/动作/色板）与场景概念图的提示词装配。"""
import json
import re
from typing import Any

import asyncpg

from ..api.app_config import get_gen_config
from ..knowledge import get_block, project_preferences, recall_blocks
from . import element_variants as ev
from .character_context import (
    character_action_gaze as _character_action_gaze,
    character_age_gender as _character_age_gender,
    character_appellations as _character_appellations,
    non_face_segments,
    world_clause as _world_clause,
)


def _is_real_character_project(config: dict, legacy_default: bool) -> bool:
    """项目角色类型优先；realistic_character 仅兼容尚无 character_mode 的老项目。"""
    mode = config.get("character_mode")
    if mode in ("real", "virtual"):
        return mode == "real"
    override = config.get("realistic_character") or "follow"
    if override in ("enable", "disable"):
        return override == "enable"
    return legacy_default


def _project_medium_clause(art_style: str, style_blocks: list[dict] | None = None) -> str:
    """把项目明确指定的 2D/3D 媒介提升为不可被设定表模板覆盖的硬约束。"""
    style_text = " ".join([
        str(art_style or ""),
        *(str(b.get("positive") or "") for b in (style_blocks or [])),
    ]).lower()
    if re.search(r"3\s*d|三维|3维|三次元|cg动画|立体动画", style_text):
        return (
            "项目媒介硬锁：这是统一的3D/三维动画项目。角色的全身三视图、面部特写、表情和动作"
            "必须全部采用与项目其他角色完全一致的风格化3D动画电影渲染，具有明确立体体积、"
            "三维材质、统一灯光与一致的角色建模语言；禁止2D、二维手绘、平面插画、线稿、"
            "赛璐璐、漫画、日漫截图、二维与三维混用。"
            "strictly consistent stylized 3D animated feature rendering across every panel, "
            "volumetric form and 3D materials, no 2D illustration, no line art, no cel shading"
        )
    if re.search(r"2\s*d|二维|2维|平面动画|手绘动画|赛璐璐", style_text):
        return (
            "项目媒介硬锁：这是统一的2D/二维动画项目。所有角色面板必须采用与项目其他角色"
            "完全一致的二维绘制语言、线条和上色方式；禁止3D、三维建模、CG塑料质感、"
            "黏土或定格动画质感。strictly consistent 2D animation rendering across every panel, "
            "no 3D render, no CGI model, no clay render"
        )
    return ""


def _non_face_appearance(text: str) -> str:
    """真人造型卡只保留服化道/体型片段（面部+发型都剔；发型由独立小卡承担）。"""
    return "、".join(non_face_segments(text, include_hair=True))


async def element_prompt_layers(
    pool: asyncpg.Pool, project_id: int, element_id: int, variant_id: str | None = None
) -> dict[str, str]:
    """要素设定图提示词的**分层产物**（user / anchor / negative / hair），不合成不落库。

    角色 = 角色设定图版式块（三视图+特写+表情+动作+色板）+ 项目画风块 + 外貌提示词
    场景 = 场景设定图版式块 + 项目画风块 + 场景描述
    variant_id：多形态要素指定为哪个身份/阶段装配（用该形态的外貌提示词）；空=主/默认形态。

    2026-08-01 从 assemble_element_sheet_prompt 原样抽出（逻辑零改动，有对拍脚本护着）：
    tapflow 画布的通用生成节点要**分层**取用——user 段可以再拼上游文本与用户指令，
    anchor 段必须锁死。抽层是为了让画布拿到层，不是另起一份装配：
    assemble_element_sheet_prompt 自己也调这里，全站仍只有这一份实现。
    """
    async with pool.acquire() as conn:
        elem = await conn.fetchrow(
            "SELECT * FROM content_elements WHERE id=$1 AND project_id=$2", element_id, project_id
        )
        if not elem:
            raise ValueError("要素不存在")
        project = await conn.fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
        meta = elem["meta"] if isinstance(elem["meta"], dict) else json.loads(elem["meta"])
        # 选中形态：其外貌提示词/profile 覆盖顶层镜像值，其余装配逻辑不变
        variant = ev.find_variant(meta, variant_id) or ev.primary_variant(meta)
        meta = {**meta, "外貌提示词": variant.get("外貌提示词") or meta.get("外貌提示词")}
        if isinstance(variant.get("profile"), dict):
            meta["profile"] = variant["profile"]

        # 非人形生物走专用版式（人形三视图/表情表词汇会诱发拟人化身乱入——巡夜事故）
        if elem["kind"] == "character" and meta.get("形态") in ("生物", "creature"):
            sheet_name = "生物设定图"
        elif elem["kind"] == "character":
            sheet_name = "角色设定图"
        elif elem["kind"] == "scene":
            sheet_name = "场景设定图"
        else:
            sheet_name = "道具设定图"  # 实物设定（武器/法宝/器物）；kb 无此块时自动跳过版式
        sheet_block = await get_block(conn, "sheet", sheet_name)
        quality = await get_block(conn, "quality", "通用质量词")
        negative = await get_block(conn, "quality", "通用负面词")
        style_blocks = await recall_blocks(conn, project["art_style"] or "日漫", ["style"], project_id, top_k=1)
        prefs = await project_preferences(conn, project_id, "artist")

    # 「沿用上一张」：该图 inherit_ref 开着且前面有图 → 提示词加相貌/风格沿用参考图子句
    # （参考图本身在 gen_element_sheet 端注入到 reference_images 首位）。首图无源→不加。
    inherit_clause = ""
    if ev.inherit_enabled(variant) and ev.inherit_source_url(meta, variant.get("id")):
        inherit_clause = (
            "。面部五官与相貌须与参考图完全一致（同一人物，仅情境/服饰/阶段不同），不得改脸"
            if elem["kind"] == "character"
            else "。整体外观、造型与风格须与参考图保持一致，仅按本图设定微调")

    subject = elem["brief"] or elem["name"]
    human_char = elem["kind"] == "character" and meta.get("形态") not in ("生物", "creature")
    if elem["kind"] not in ("character", "scene"):
        # 实物单体设定图：纯色底多角度展示，禁人物禁场景（否则参考图会把镜头画面带偏）
        subject = (
            f"{elem['name']}：{meta.get('外貌提示词') or elem['brief'] or ''}。{_world_clause(project)}"
            "单体物件设定图：纯色浅灰背景，多角度展示（整体+关键细节特写），"
            "画面中只有该物件本身，无人物、无场景环境"
        )
    if elem["kind"] == "scene":
        # **场景名必须领头**。原来是 `subject = brief or name`，brief 非空时名字被 or 短路丢掉——
        # 而 brief 常常是纯剧情（「可疑年轻人徘徊的地方…」），一个字都没描述这地方长什么样。
        # 结果模型手里只剩世界观里的「江南小镇」，给「废弃仓库」画出了水乡河道（实测）。
        # 角色/道具分支本来就是 `名字：内容`，场景漏了这一笔。
        subject = f"{elem['name']}：{subject.rstrip('。 ')}" if subject != elem["name"] else elem["name"]
        subject = f"{subject.rstrip('。 ')}。{_world_clause(project)}"
        # 场景轻量特征（人群密度/时段/氛围）织入设定图：一张概念图内体现人流密度 + 大远景与中景两级取景
        prof = meta.get("profile") if isinstance(meta.get("profile"), dict) else {}
        feats = "；".join(f"{k}：{prof[k]}" for k in ("人群密度", "时段", "氛围") if prof.get(k))
        if feats:
            subject = f"{subject.rstrip('。 ')}。场景特征——{feats}"
    if elem["kind"] == "character" and meta.get("外貌提示词"):
        subject = f"{elem['name']}: {meta['外貌提示词']}. {elem['brief'] or ''}"
        # 表情面板必须贴合人物性格（反"图库摆拍脸"：冷峻者的喜=极淡的嘴角弧度，不是灿烂大笑）
        if human_char and elem["brief"]:
            subject += (
                f"。表情面板必须符合该角色的性格与身份（{elem['brief'][:40]}）——"
                "喜怒哀惊全部克制、含蓄、不对称，像被抓拍到的情绪瞬间，绝非摆拍"
            )
    if elem["kind"] == "character":
        age, gender = _character_age_gender(meta, elem["brief"] or "", elem["name"])
        action, gaze = _character_action_gaze(meta, elem["brief"] or "")
        profile = meta.get("profile") if isinstance(meta.get("profile"), dict) else {}
        appellations = _character_appellations(elem["name"], profile, elem["brief"] or "")
        appellation_text = "、".join(appellations) or str(profile.get("身份") or "未设定")
        character_basis = "；".join(
            x for x in (
                f"身份称谓={appellation_text}",
                f"角色身份={profile.get('身份')}" if profile.get("身份") else "",
                f"角色简介={elem['brief']}" if elem["brief"] else "",
            ) if x
        )
        gender_label = {"女": "女性", "男": "男性"}.get(gender, gender)
        subject = (
            f"角色身份硬约束：角色完整名称=「{elem['name']}」，必须保留并遵守名称中的身份与性别语义；"
            f"原始身份称谓={appellation_text}，提示词与画面表演不得省略、替换或弱化这些称谓的语义；"
            f"年龄={age}，性别={gender_label}。所有三视图、特写、表情和动作面板"
            f"必须始终是同一个{age}{gender_label}角色，年龄与性别不得改变、不得模糊、不得生成异性。"
            f"角色表演硬约束：招牌动作={action}；招牌眼神={gaze}。至少一个完整动作面板必须准确展示"
            "该招牌动作，主面部特写必须准确展示该招牌眼神；其他表情也必须保持相同身份性格，"
            f"神态、视线、嘴角、眉眼张力、头部姿态和身体重心必须共同表达「{character_basis}」所对应的"
            "独特性格与阅历，不能只画年龄和服装；禁止套用与角色无关的通用英雄姿势、"
            "通用害羞姿势、无性格站姿或图库式表情。"
            f"{subject}"
        )
    # 角色卡版式必须由项目的 character_mode 决定。realistic_character 是旧的生成策略开关，
    # 不能把明确选择了 virtual 的项目误判成真人项目，否则会整块移除三视图模板。
    # 仅对尚无 character_mode 的存量项目保留旧开关/系统默认值兼容。
    proj_cfg = project["config"] if isinstance(project["config"], dict) else json.loads(project["config"] or "{}")
    legacy_default = bool((await get_gen_config()).get("realistic_character", True))
    real_project = _is_real_character_project(proj_cfg, legacy_default)
    subject += inherit_clause

    # ── 双字段拆分（用户 2026-07-17 定稿）：user 段=外貌/世界观/表情面板等叙事（源数据是
    # 外貌提示词/brief，改动走各自入口）；anchor 段=版式块+画风锚词+质量词+偏好+防真人句
    # ——anchor 随装配自动刷新，用户改过（sheet_prompt_anchor_edited）则冻结沿用
    from .prompt_fields import compose

    # 普通角色沿用系统角色设定图模板；真人项目不能再带入其中的三视图头像、
    # 五官特写和表情面板，否则会与“不要五官”冲突并诱发真人脸/儿童脸/马赛克脸。
    blocks = [b for b in ([*style_blocks, quality] if human_char and real_project
                          else [sheet_block, *style_blocks, quality]) if b]
    anchor_bits = [b["positive"] for b in blocks if b.get("positive")]
    if prefs:
        anchor_bits.append("; ".join(prefs))
    if human_char and not real_project:
        # 虚拟形象使用独立身份模板：可以生成完整头部，但五官比例必须明显风格化，
        # 禁止用“真人五官 + 照片皮肤”伪装成虚拟角色。具体 2D/3D 媒介仍交给项目画风。
        anchor_bits.append(
            "原创虚拟角色完整设定图，允许完整头部、五官、表情与动作面板。"
            "面部结构必须采用明显的非真人艺术比例：眼睛、眉眼间距、鼻口形制、脸型轮廓中至少三项"
            "具有清晰可辨的夸张或简化设计，严禁照搬现实人类标准五官比例。"
            "皮肤必须使用与项目画风一致的绘制、赛璐璐、插画、黏土或风格化渲染质感，"
            "不得出现照片级毛孔、真实皮肤纹理、写真布光或真人摄影观感。"
            "角色必须一眼可辨为虚构设计，不得像演员、模特、明星、证件照或真人照片。"
            "具体采用 2D 或 3D 严格服从项目画风，不擅自改换媒介。"
            "original fictional character, unmistakably stylized non-human facial proportions, "
            "exaggerated or simplified eyes nose mouth and face shape, non-photographic skin, "
            "clearly designed character, never realistic human facial anatomy"
        )
    hair_prompt = ""
    if human_char and real_project:
        prof = meta.get("profile") if isinstance(meta.get("profile"), dict) else {}
        styling = "、".join(x for x in [
            str(prof.get("时代服饰") or "").strip(),
            str(prof.get("身份") or "").strip(),
            _non_face_appearance(str(meta.get("外貌提示词") or "")),
        ] if x)
        subject = (
            f"「{elem['name']}」真人项目服化道造型设计。"
            f"{styling or elem['brief'] or '按角色身份设计服饰与装备'}。"
            "这不是人物身份照，不展示头部或脸部。"
        )
        anchor_bits.append(
            "真人项目无头服化道造型板，干净纯白背景，专业服装设计图排版。"
            "左侧展示三套从颈部以下完整入镜的穿着效果：正面、侧面、背面，"
            "画面在下颌以下硬裁切，头部完全位于画框之外，不出现脖子以上区域。"
            "右侧展示服装分层、鞋靴、腰带、包具、武器和随身道具的静物平铺细节。"
            "本图不承担发型与发饰展示；发型和头饰由另一张独立小卡生成。"
            "可以展示两到四个无头躯干动作姿态，只表达服装受力与动作轮廓。"
            "所有格子都不得出现头、脸、五官、头像、儿童、面部特写、表情面板、"
            "马赛克脸、模糊脸、肤色空白脸、假人脸或任何脸部占位形状。"
            "headless outfit design sheet, crop every worn outfit below the chin, "
            "head completely outside frame, no face panel, no portrait, no facial placeholder"
        )
        hair_prompt = (
            f"「{elem['name']}」真人项目独立发型与发饰小卡，纯白背景，横向三格。"
            f"造型依据：{styling or elem['brief'] or '符合角色身份的发型与头饰'}。"
            "第一格只显示双眼、眉毛、额头、发际线、头发与发饰，下边缘紧贴眼睛下方并在鼻梁上方硬裁切；"
            "第二格为侧上方局部，只显示一只眼睛及以上区域；第三格为纯后脑发型与头饰结构。"
            "另附无人佩戴的帽子、发簪、发带等静物。严禁完整鼻子、鼻孔、脸颊、嘴巴、嘴唇、"
            "下巴、下颌、脖子、胸像、完整脸、肖像、儿童、马赛克或模糊脸。"
            "eyes and above only, crop above nose bridge, no nose, no mouth, no lower face, no text"
        )
    joined = ", ".join(x for x in anchor_bits if x)
    anchor = ", ".join(dict.fromkeys(t.strip() for t in joined.split(",") if t.strip()))
    if meta.get("sheet_prompt_anchor_edited") and meta.get("sheet_prompt_anchor"):
        anchor = meta["sheet_prompt_anchor"]  # 用户手编的锚定段：冻结沿用
    # 人物类型安全约束不可被旧的手编锚定段覆盖；否则存量提示词会继续生成真人脸。
    if human_char and real_project:
        anchor = (
            f"{anchor}, 强制无头版式：所有穿着效果从颈部以下裁切，头部完全在画框外；"
            "本图不生成发型发饰小块；禁止任何头部、脸、五官、儿童、马赛克脸、模糊脸、空白脸"
        )
    elif human_char:
        medium_clause = _project_medium_clause(project["art_style"] or "", style_blocks)
        anchor = (
            f"{anchor}, 强制角色设定表版式：纯白背景上的多面板角色设计图，必须同时包含"
            "同一角色同一服装的正面、侧面、背面全身三视图，面部特写、表情组、"
            "至少两个动作姿势和角落色板；禁止单张全景、单一动作照、环境场景、"
            "摄影棚背景、摄影灯、灯架、无缝背景纸或幕后拍摄设备；"
            "强制原创虚拟面孔：显著非真人五官比例与风格化皮肤；"
            "禁止真人五官比例、照片级人脸、真实毛孔、演员或模特写真感；"
            f"{medium_clause}"
        )
    elif elem["kind"] == "scene":
        # 运行时硬约束，不依赖只在首次启动写入的知识 seed；存量数据库和手编冻结锚点也立即生效。
        anchor = (
            f"{anchor}, 强制纯场景多景别版式：同一地点必须同时包含一幅大远景全貌和一幅中景细部，"
            "地点与空间关系是唯一主体。仅当场景设定确实需要表现客流或尺度时，才允许出现"
            "无姓名、不可识别、远距离小比例的普通路人、背景群像或不具角色身份的普通动物，"
            "例如人山人海的街道；"
            "除此之外画面必须无人、无动物、无生物。无论场景名称或描述是否提到某个角色、"
            "种族或兽类，都禁止出现任何主要人物、具名人物、可识别人物、主要兽类、坐骑、"
            "怪兽或其他核心生物，也禁止用剪影、影子、倒影、雕像、壁画或远处轮廓变相表现它们。"
            "no protagonist, no named character, no recognizable character, no main creature, "
            "no dragon, no mount, no monster, no character silhouette"
        )
    positive = compose(subject, anchor)
    neg = ", ".join(b["negative"] for b in blocks if b.get("negative"))
    if negative:
        neg = ", ".join(x for x in [neg, negative["negative"]] if x)
    if human_char and not real_project:
        neg = ", ".join(x for x in [neg,
            "real person, realistic human facial proportions, anatomically realistic human face, "
            "photorealistic face, photographic portrait, photo skin, realistic pores, skin pores, "
            "live-action actor, model photo, celebrity, deepfake, id photo, passport photo, "
            "真人五官比例, 真人脸, 照片级人脸, 写真, 真实皮肤, 毛孔, 演员脸, 模特脸, 明星脸"
        ] if x)
    if human_char and real_project:
        neg = ", ".join(x for x in [neg,
            "complete face, full facial features, portrait, close-up full face, nose, nostrils, "
            "cheeks, mouth, lips, chin, jaw, "
            "expression sheet, child, boy, girl, mosaic face, pixelated face, blurred face, "
            "blank skin face, featureless face, mannequin head, mannequin face, mask over a face, "
            "完整头像, 完整人脸, 鼻子, 鼻孔, 脸颊, 嘴巴, 嘴唇, 下巴, 下颌, 表情图, 完整面部特写, "
            "儿童, 男孩, 女孩, 马赛克脸, 模糊脸, 空白脸, 假人头, 戴口罩的人脸"
        ] if x)

    # name 也回给调用方：画布那条链要在模型写完后校验「名字在不在」，兜底补一笔
    return {"user": subject, "anchor": anchor, "negative": neg, "hair": hair_prompt,
            "name": elem["name"]}


async def assemble_element_sheet_prompt(
    pool: asyncpg.Pool, project_id: int, element_id: int, variant_id: str | None = None
) -> dict[str, str]:
    """装配要素设定图提示词并写回 element.meta.sheet_prompt（多形态时写回该形态）。

    分层取数在 element_prompt_layers；这里只做 user ⊕ anchor 合成与落库——
    项目页按钮、工作流 action、画布通用生成节点走的都是同一条路。
    """
    layers = await element_prompt_layers(pool, project_id, element_id, variant_id)
    subject, anchor = layers["user"], layers["anchor"]
    from .prompt_fields import compose

    prompts = {"sheet_prompt": compose(subject, anchor), "sheet_prompt_user": subject,
               "sheet_prompt_anchor": anchor, "sheet_negative": layers["negative"],
               "hair_sheet_prompt": layers["hair"]}
    async with pool.acquire() as conn:
        elem_meta = await conn.fetchval(
            "SELECT meta FROM content_elements WHERE id=$1 AND project_id=$2",
            element_id, project_id)
    meta = elem_meta if isinstance(elem_meta, dict) else json.loads(elem_meta or "{}")
    # 多形态：提示词写回该形态（同时镜像回顶层）；单形态老要素：直接写顶层
    if ev.has_variants(meta):
        variant = ev.find_variant(meta, variant_id) or ev.primary_variant(meta)
        variants = [dict(v) for v in ev.variants_of(meta)]
        tgt = next((v for v in variants if v.get("id") == variant.get("id")), variants[0])
        tgt.update(prompts)
        patch = ev.mirror_patch(variants)
    else:
        patch = dict(prompts)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE content_elements SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
            element_id, json.dumps(patch, ensure_ascii=False),
        )
    return prompts


async def element_refs(pool: asyncpg.Pool, project_id: int, element_id: int,
                       variant_id: str | None = None,
                       row: asyncpg.Record | None = None) -> list[dict[str, Any]]:
    """要素设定图的参考图**唯一实现**：手选参考图（extra_refs 去掉 sheet_ref_off 停用项）
    + 「沿用上一张」注入首位。

    2026-08-01 收敛：此前 api/projects.gen_element_sheet 端点与
    workflow_actions.element_sheet_prepare 各写了一份一模一样的筛选，属于典型漂移源
    （真人项目禁沿用这条规则要是只改一处，另一处就会继续把带脸的旧卡喂回去）。
    """
    if row is None:
        row = await pool.fetchrow(
            "SELECT e.meta, p.config AS project_config FROM content_elements e "
            "JOIN content_projects p ON p.id=e.project_id WHERE e.id=$1 AND e.project_id=$2",
            element_id, project_id)
    if not row:
        raise ValueError(f"要素 {element_id} 不在项目 {project_id} 下")
    emeta = row["meta"] if isinstance(row["meta"], dict) else json.loads(row["meta"] or "{}")
    pconf = (row["project_config"] if isinstance(row["project_config"], dict)
             else json.loads(row["project_config"] or "{}"))
    legacy_default = bool((await get_gen_config()).get("realistic_character", True))
    is_real = _is_real_character_project(pconf, legacy_default)
    off = set(emeta.get("sheet_ref_off") or [])
    refs = [r for r in (emeta.get("extra_refs") or [])
            if r.get("url") and r.get("name") not in off]
    # 真人造型卡严禁沿用上一张（旧卡可能带脸，像素影响压过无头文字约束）
    tgt = ev.find_variant(emeta, variant_id) or ev.primary_variant(emeta)
    if not is_real and ev.inherit_enabled(tgt):
        src = ev.inherit_source_url(emeta, tgt.get("id"))
        if src and all(r.get("url") != src for r in refs):
            refs = [{"name": "沿用上一张", "kind": "inherit", "url": src}, *refs]
    return refs
