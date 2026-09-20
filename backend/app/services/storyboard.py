"""分镜链：章节→分镜序列（景别/角度/运镜/焦段感/光效）→专业提示词装配→首帧/视频任务。

专业颗粒度规范见 docs/arch/storyboard-prompt-spec.md（金标准样例 docs/samples/storyboard-golden-sample.md）；
提示词装配遵循核心原则2：景别/角度/焦段/光效/运镜/动作/画风知识块动态召回 + 项目偏好级联。
"""
import json
import logging
import re
from difflib import SequenceMatcher
from typing import Any

import asyncpg

from .. import llm
from ..knowledge import get_block, project_preferences, recall_blocks
from . import element_variants, volumes
from .character_context import identity_desc, non_face_segments, roster_line
from .flow import PROMPT_REVIEW_TTL_H, stamp_validity

log = logging.getLogger("storyboard")

# 枚举白名单（校验 Gate 与系统提示词共用，规范见 docs/arch/storyboard-prompt-spec.md）
SCALES = ["大远景", "远景", "全景", "中景", "近景", "特写", "大特写"]
ANGLES = ["平视", "仰拍", "俯拍", "鸟瞰", "过肩", "主观POV", "荷兰角"]
CAMERA_MOVES = ["固定", "推镜", "拉镜", "摇镜", "移镜", "跟拍", "升降镜头", "手持晃动", "环绕镜头"]
LENS_FEELS = ["16mm超广角", "24mm广角", "35mm标准", "50mm标准", "85mm长焦", "100mm微距"]

# 导演技能（方法论，可被 kb_entries kind=skill agent_code=director 覆盖——项目级可改）
DIRECTOR_RULES = """你是资深电影分镜导演，遵循罗杰·狄金斯式的克制原则。把给定章节内容拆解为可拍摄的专业分镜序列。
每镜必含齐：镜号/场景/景别/角度/运镜/运动线/焦段感/光效/色调/情绪功能/主体动作/时长/画面/对白/音效。
创作铁律：
1. 每镜只回答一个问题（他在哪/他看到什么/他什么反应）——回答两个问题就拆成两镜；关键信息独占一镜，哪怕只有2秒的大特写
2. 一镜只有**一个相机动作 + 一个主体动作**，禁止复合运镜（"先推后摇"必须拆镜）
3. 剪辑节奏=ASL 3-4s 是**剪辑口径**（靠镜头组内 cuts 硬切 + 成片剪辑达成，不是靠生成短视频）：紧张打斗每切1.5-3s、叙事铺垫3-5s、情绪释放5-8s。**但每个生成单元（单镜/镜头组）的 duration_s 硬下限4s**（视频模型计费下限，<4s会被夹成4s、白付费）——想要更快节奏就把单元切成多个 cut（4s单元切成2个2s节拍），别生成2-3s的独立单元；固定镜也按4s起，用画面微动态+cuts撑住
4. 场景内硬切交替：同一场景至少拆3个镜头，远近景别交替硬切（特写↔全景来回跳），对话用正反打，关键情绪插入反应镜/插入镜——观众的注意力靠切换喂养，单镜停留超过4秒即疲劳
5. 景别穿插：避免连续3个同景别；全段情绪支点给最小景别（特写/大特写）
6. 角度=情绪：特写+俯拍=脆弱、特写+仰拍=威压、远景+鸟瞰=渺小、俯仰对切=情绪反转（坠落→翱翔）
7. 焦段克制：默认35mm标准，只在有明确理由时偏离——大空间感→16/24mm、压背景拍情绪脸→85mm、接触瞬间微小物→100mm微距（《1917》全片只用三个焦段）
8. 光效写画面效果不写灯具：如"晨昏侧逆光勾出发丝轮廓""生物荧光为唯一光源"，禁止出现灯具参数
9. 视觉化优先：抽象情感翻译成可拍的具体动作与光色变化；画面描述具体到首帧可独立绘制；action 必须带速度感（"猛地转身"而非"转身"）——AI 视频默认动作缓慢，速度必须显式写出
10. 运镜克制但不僵死：固定镜头不超过全片一半；动作爆点用移镜/跟拍/手持，情绪释放段必须用运动镜头（升降/环绕/推拉），高潮大景配 16mm 超广角；景运安全组合参考（Seedance 官方）：近景+慢推、中景+跟拍、全景+慢拉——拿不准时优先取这三组
11. 禁止相邻镜头重复同一信息（同一画面/同一动作变体只拍一次）；每镜必须推进新信息
12. 镜头组=同场连续切换：同一场景同一批角色的对话/正反打/连续反应，**不要拆成多个独立镜头**——合并为一个"镜头组"（duration_s 5-10s），用 cuts 数组表达组内切换（景别远近交替，标注主体角色）；组内人物占位与光线由同一次生成保证一致。只有场景或时间跳变才另起新镜。**切的节奏按内容分级：打斗/追逐等动作场面才每切1-3s快切；常规对话按台词自然切换（每条台词一切，含说完的呼吸）；情绪铺垫/释放每切3-5s、宁少切勿碎**——给抒情段配碎切与给打斗配长镜同样是剪辑事故
13. 固定镜头的 camera_path 必须填"无"（运动线只属于运动镜头，矛盾指令会让模型自行发明无意义滑镜）；静止/建立镜的 action 必须写画面内的**微动态**（烛光明灭/影子拉长/衣角微动/呼吸起伏），禁止纯静态陈述（"X坐着"不可拍）
14. 对白节奏=字数÷4秒（中文语速约240字/分）：13字对白≈3秒、一字答句1-2秒——这是**每条对白占的时长**，用于定组内 cut 的 seconds，不是让你生成2-3s的独立对白镜。短对白/短答句一律并进同场镜头组当一个 cut（见铁律12），保证生成单元 duration_s≥4s；仅当整场只一句对白、且无同场镜可并时才允许单镜，此时 floor 到4-5s、用画面微动态填满。**长短取舍是建议、按内容需要来，但下限4s是硬约束（计费下限），别生成注定被夹的短镜**"""

# 输出格式与枚举（代码强制，不入技能库——枚举是校验 Gate 的单一来源）
_STORYBOARD_FORMAT = f"""枚举（只能取）：
- scale: {'/'.join(SCALES)}
- angle: {'/'.join(ANGLES)}
- camera_move: {'/'.join(CAMERA_MOVES)}（单选，禁止组合）
- lens_feel: {'/'.join(LENS_FEELS)}
- lighting: 一句画面光效（参考词汇：晨昏侧逆光/丁达尔光柱/生物荧光/剪影逆光/硬光高对比/柔光漫射/水下焦散/流动环绕光，可按场景自拟）
scene_element 只在清单中存在与本镜实际地点一致的要素时才选（用于关联场景设定图作生成参考）；地点不一致时必须填"无"——错误绑定的场景设定图会把画面拉到别的地点（宁缺勿错）。
总镜头数 8-20 个生成单元（含镜头组；按剪辑口径折算 ASL 3-4s，宁切勿长）。严格输出 JSON：
{{"shots": [{{"shot_no":1,"scene":"场景名/时间/地点","scene_element":"关联的场景要素名","scale":"景别","angle":"角度","camera_move":"运镜(单选)","camera_path":"镜头运动线(箭头语言,如'从左下人物面部 → 推向右上远处城门')","lens_feel":"焦段感","lighting":"画面光效一句","palette":"主色调+冷暖(如'冷蓝主调,一点淡金')","mood":"本镜情绪功能(如 恐惧铺垫/动作爆点/情绪支点/释放)","action":"主体单动作一句话","duration_s":4,"description":"画面(具体可拍,首帧可独立绘制,40-80字)","dialogue":"对白或无","sfx":"音效或无","motion_hint":"动作关键词(如 武打近身格斗/奔跑追逐/哭泣崩溃/回眸,无动作填 无)","characters":["出场角色名"],"cuts":[{{"seconds":2,"scale":"特写","subject":"角色A","action":"猛地抬头质问"}},{{"seconds":2,"scale":"全景","subject":"大殿全景","action":"群臣噤声"}}]}}]}}
说明：cuts 表达镜头内的景别切换，两类场景必须使用——
①同场快切对话/正反打（铁律12，duration_s 5-10s）；
②单镜含多个视觉节拍时（duration_s≥4s 建议 2-3 切）：如"(远景)阿澈站在跳台边缘→(推近景)潜衣贴紧皮肤→(特写)呼吸核亮起第一格"，用景别推进喂养注意力。
生成单元 duration_s 硬下限4s（视频模型计费下限，<4s白付费）；只有恰好4s的单一动作镜才省略 cuts，4s以上都建议2-3切。镜头组的 scale/angle/camera_move 填首切的值，duration_s=各切之和。"""

# （_STORYBOARD_SYS 已废弃移除：系统提示词一律经 _director_system 装配——技能与格式段均库化可覆盖）

# ── 两阶段拆镜（用户 2026-07-12 定稿）：粗拆只出骨架（小 JSON 不截断），详细分镜按板≤16镜补 ──
# 粗拆格式：只要 骨架+景别+时长，禁止输出镜头语言细节（角度/运镜/焦段/光效/色调/情绪/cuts）
_STORYBOARD_COARSE_FORMAT = f"""【本轮只拆「分镜脚本骨架」，不写镜头语言细节——细节留到详细分镜阶段按板补】
枚举（scale 只能取）：{'/'.join(SCALES)}
scene_element 只在清单中存在与本镜实际地点一致的要素时才选（用于关联场景设定图）；地点不一致时必须填"无"——错误绑定会把画面拉到别的地点（宁缺勿错）。
characters **只能取「项目角色要素」清单中的原名**（角色名是关联设定图与外貌的钥匙，写"长老/黑衣人"等泛称会导致该角色无设定图、跨镜必漂）；清单外的临时路人不要写进 characters，只在 description 里描述。原文用泛称指代清单角色时（如"长老"实为"三长老"），必须还原为清单原名。
总镜头数 8-20 个生成单元（按剪辑口径 ASL 3-4s，宁切勿长；同场快切/正反打属同一镜头组单元，不要拆成多个独立镜）。
**每个生成单元 duration_s 硬下限4s**（视频模型计费下限，<4s白付费）：短对白/短反应并进同场镜头组，别出2-3s独立镜。
link_prev 标记镜间衔接（跨镜连贯的钥匙）：本镜开场画面与上一镜结尾在同场景同时刻连续承接（上一镜收尾即本镜开场、动作/走位连续）填"连贯"；换场景/时间跳跃/换叙事视角填"跳切"；镜1恒为"跳切"；拿不准填"跳切"。
严格输出 JSON（**只含以下字段**，禁止输出 angle/camera_move/camera_path/lens_feel/lighting/palette/mood/motion_hint/cuts 等——那些是详细分镜阶段的活）：
{{"shots":[{{"shot_no":1,"scene":"场景名/时间/地点","scene_element":"关联的场景要素名","scale":"景别","duration_s":4,"characters":["出场角色名"],"link_prev":"连贯|跳切","action":"主体单动作一句话（带速度感，如'猛地转身'）","dialogue":"对白或无","description":"画面梗概（60-100字：忠实原文的动作/体位/神态/环境与关键道具细节，够画一张构图草图；宁可照抄原文具体描写，不要笼统概括）"}}]}}"""

# 详细分镜格式：喂入已定的粗镜列表，逐镜补齐镜头语言，严禁改动/重编号/增删镜
_STORYBOARD_DETAIL_FORMAT = f"""【本轮把给定的「分镜脚本骨架」逐镜展开为可拍摄的详细分镜——只补镜头语言，不改叙事】
铁律：**严格保持每镜的 shot_no / scene / scale / duration_s / characters / dialogue / action 原样不变，不得重新编号、不得增删或合并镜头**；只为每镜补齐镜头语言细节。
枚举（只能取）：
- angle: {'/'.join(ANGLES)}
- camera_move: {'/'.join(CAMERA_MOVES)}（单选，禁止组合）
- lens_feel: {'/'.join(LENS_FEELS)}
- lighting: 一句画面光效（参考：晨昏侧逆光/丁达尔光柱/生物荧光/剪影逆光/硬光高对比/柔光漫射/水下焦散/流动环绕光，可自拟）
遵循创作铁律 3/4/12/13：固定镜 camera_path 填"无"且 action 写画面内微动态；同场对话/多视觉节拍镜用 cuts 表达组内硬切（景别交替、各切之和=duration_s；**节奏分级：打斗/追逐才每切1-3s快切，常规叙事与对话每切2-4s，情绪铺垫/释放每切3-5s宁少勿碎**）。
cuts 的 action 必须是**可拍的视觉叙事**：画面里看得见的动作/光影/物件变化，带速度感与氛围细节（风掀衣摆/汗珠滑落/尘土溅起/光斑移动），禁止剧情结论式写法（"表明身份决定同行"不可拍——要写"抱拳沉声自报名号，风掀动黑袍下摆"）。多切镜的运镜内嵌在 action 里（镜级 camera_move 只对无切/单切镜生效）——运镜词汇参考：慢推/慢拉/横摇/竖摇/环绕/跟拍/微距推近/手持微抖；高潮与情绪支点可用专业运镜：希区柯克变焦/高速螺旋环绕/俯冲/快速拉升/焦外虚化缓移/一镜到底感。纪律：单切最多1种镜头运动；开场建立切、动作爆点切与情绪支点切应写明运镜，普通对话切可默认固定。
严格输出 JSON（每镜回带原 shot_no）：
{{"shots":[{{"shot_no":1,"angle":"角度","camera_move":"运镜(单选)","camera_path":"镜头运动线(箭头语言,固定镜填'无')","lens_feel":"焦段感","lighting":"画面光效一句","palette":"主色调+冷暖(如'冷蓝主调,一点淡金')","mood":"本镜情绪功能(如 恐惧铺垫/动作爆点/情绪支点/释放)","motion_hint":"动作关键词(如 武打近身格斗/奔跑追逐/哭泣崩溃/回眸,无动作填 无)","description":"画面(忠实骨架与原文的具体细节:动作/体位/神态/环境/道具,精修到首帧可独立绘制,60-100字;可细化润色,不得臆造或删减骨架已有信息)","cuts":[{{"seconds":2,"scale":"特写","subject":"角色A","action":"猛地抬头质问"}},{{"seconds":2,"scale":"全景","subject":"大殿全景","action":"群臣噤声"}}]}}]}}
说明：生成单元 duration_s 硬下限4s；只有恰好4s的单一动作镜可省略 cuts，≥4s 或同场快切/正反打必须给 cuts。"""


# 格式段库化（用户 2026-07-13 定稿）：kb 技能名 → 代码常量兜底。
# 库里存的是渲染后的文本（含枚举与 JSON schema）——枚举与 JSON 字段是校验 Gate 的依据，管理页改动需谨慎
_FMT_FALLBACKS = {
    "分镜输出格式": lambda: _STORYBOARD_FORMAT,
    "粗拆骨架输出格式": lambda: _STORYBOARD_COARSE_FORMAT,
    "详细分镜输出格式": lambda: _STORYBOARD_DETAIL_FORMAT,
}


async def _director_skill(conn: asyncpg.Connection, project_id: int,
                          name: str, fallback: str) -> str:
    """按名取 director 技能条目（项目覆盖全局，缺失回退代码常量）。"""
    row = await conn.fetchrow(
        "SELECT content FROM kb_entries WHERE kind='skill' AND agent_code='director' AND name=$2 "
        "AND enabled AND (scope='global' OR (scope='project' AND project_id=$1)) "
        "AND ((SELECT project_type FROM content_projects WHERE id=$1)='novel_comic' "
        "     OR cardinality(tags)=0 OR (SELECT project_type FROM content_projects WHERE id=$1)=ANY(tags)) "
        "ORDER BY scope DESC LIMIT 1", project_id, name,
    )
    return row["content"] if row and (row["content"] or "").strip() else fallback


async def _standard_skill_context(
    conn: asyncpg.Connection, project_id: int, slug: str, fallback: str,
    agent_code: str = "director",
) -> str:
    """装配已安装的 agentskills.io Skill 及其一级 references。

    只读取挂在本项目指定员工上的已安装 Skill（默认导演；场景类技能挂 scene-designer）；
    缺失时用代码常量兜底，使生产镜像与数据迁移启动顺序不影响核心门禁。
    """
    row = await conn.fetchrow(
        "SELECT s.id,s.skill_md FROM agents a "
        "JOIN agent_skill_bindings b ON b.agent_id=a.id AND b.enabled "
        "JOIN skill_packages s ON s.id=b.skill_id AND s.status='installed' "
        "WHERE a.project_id=$1 AND a.code=$3 AND s.slug=$2 LIMIT 1",
        project_id, slug, agent_code,
    )
    if not row:
        return fallback
    refs = await conn.fetch(
        "SELECT path,content FROM skill_package_files WHERE skill_id=$1 "
        "AND path LIKE 'references/%' ORDER BY path",
        row["id"],
    )
    parts = [str(row["skill_md"] or "").strip()]
    parts.extend(f"【{r['path']}】\n{r['content']}" for r in refs if (r["content"] or "").strip())
    return "\n\n".join(x for x in parts if x) or fallback


async def _director_system(
    conn: asyncpg.Connection, project_id: int, fmt_name: str = "分镜输出格式",
    fmt_override: str | None = None,
) -> str:
    """装配导演系统提示词（prompt=编译产物）：员工章程 + 拆解技能(kb) + 输出格式段(kb，均项目覆盖全局)。
    fmt_name 决定输出阶段：分镜输出格式 / 粗拆骨架输出格式 / 详细分镜输出格式；
    fmt_override 直接传格式文本（流式 MD 变体等派生格式用）。"""
    emp = await conn.fetchrow(
        "SELECT charter FROM agents WHERE project_id=$1 AND code='director'", project_id
    )
    rules = await _director_skill(conn, project_id, "专业分镜拆解", DIRECTOR_RULES)
    from .scene_transitions import SKILL_RULES_FALLBACK

    transition_rules = await _standard_skill_context(
        conn, project_id, "subject-aware-scene-transitions", SKILL_RULES_FALLBACK)
    if fmt_override is not None:
        fmt = fmt_override
    else:
        fmt = await _director_skill(conn, project_id, fmt_name,
                                    _FMT_FALLBACKS[fmt_name]())
    parts = []
    if emp and emp["charter"]:
        parts.append(emp["charter"])
    parts.append(rules)
    parts.append(transition_rules)
    parts.append(fmt)
    return "\n\n".join(parts)


_COMPOUND_MOVE = ("+", "、", "，", "然后", "先", "再", "接着", "并")
_COMPOUND_ACTION = ("然后", "接着", "，再", ",再", "之后又")


def validate_shot_list(shots: list[dict[str, Any]], known_chars: set[str]) -> dict[str, Any]:
    """零 token 校验 Gate（规范 G1-G8）：errors 打回重拆，warns 落 meta.validation。"""
    errors: list[str] = []
    per_shot: dict[int, list[str]] = {}

    def warn(i: int, msg: str):
        per_shot.setdefault(i, []).append(msg)

    for i, s in enumerate(shots):
        no = s.get("shot_no", i + 1)
        # G1 必填
        for f in ("scale", "angle", "camera_move", "lens_feel", "lighting", "action", "duration_s", "description"):
            if not s.get(f):
                errors.append(f"镜{no}: 缺必填字段 {f}")
        # G2 枚举
        if s.get("scale") and s["scale"] not in SCALES:
            errors.append(f"镜{no}: scale「{s['scale']}」不在枚举 {SCALES}")
        if s.get("angle") and s["angle"] not in ANGLES:
            errors.append(f"镜{no}: angle「{s['angle']}」不在枚举 {ANGLES}")
        if s.get("camera_move") and s["camera_move"] not in CAMERA_MOVES:
            errors.append(f"镜{no}: camera_move「{s['camera_move']}」不在枚举 {CAMERA_MOVES}（单选，禁止组合）")
        if s.get("lens_feel") and s["lens_feel"] not in LENS_FEELS:
            errors.append(f"镜{no}: lens_feel「{s['lens_feel']}」不在枚举 {LENS_FEELS}")
        # G3 时长界（镜头组放宽到10s；落库时自动夹紧，此处只警示）
        cuts = s.get("cuts") or []
        try:
            d = int(s.get("duration_s") or 0)
            cap = 10 if cuts else 8
            if not 2 <= d <= cap:
                warn(i, f"G3 时长 {d}s 超界(2-{cap})，已夹紧")
            # G11 静止镜头 ≤4s：超长静止镜是视觉疲劳的头号来源（铁律3）；镜头组内部有切换，豁免
            if s.get("camera_move") == "固定" and d > 4 and not cuts:
                errors.append(f"镜{no}: 固定镜头 {d}s 超过4s——切成多镜硬切交替、改运动镜头，或按铁律12合并为镜头组(cuts)")
            # G14 多镜头覆盖体检：切数2-5，相邻剪辑镜头必须改变视点
            if cuts:
                if not 2 <= len(cuts) <= 5:
                    warn(i, f"G14 镜头组切数 {len(cuts)} 不在2-5")
                if any(cuts[j].get("scale") == cuts[j - 1].get("scale")
                       for j in range(1, len(cuts))):
                    errors.append(
                        f"镜{no}: G14 相邻剪辑镜头景别相同——需改变视点，按建立镜/正反打/"
                        "反应镜设计覆盖，禁止同景别机械换人")
                for j, cut in enumerate(cuts, 1):
                    cut_move = cut.get("camera_move") or "固定"
                    if cut_move not in CAMERA_MOVES:
                        errors.append(
                            f"镜{no}切{j}: camera_move「{cut_move}」不在枚举 {CAMERA_MOVES}")
        except (TypeError, ValueError):
            errors.append(f"镜{no}: duration_s 非数字")
        # G4 复合运镜
        mv = s.get("camera_move") or ""
        if any(t in mv for t in _COMPOUND_MOVE):
            errors.append(f"镜{no}: 运镜「{mv}」疑似复合动作，一镜只许一个相机动作")
        # G15 固定镜带运动线=矛盾指令（模型会执行运动线，产出无意义滑镜）
        path = (s.get("camera_path") or "").strip()
        if mv == "固定" and path and path != "无":
            errors.append(f"镜{no}: 固定镜头却带运动线「{path}」——矛盾指令；改运动镜头或运动线填'无'（铁律13）")
        # G6 角色存在性
        for c in s.get("characters") or []:
            if known_chars and c not in known_chars:
                warn(i, f"G6 角色「{c}」不在项目角色要素中")
        # G7 单动作启发式
        act = s.get("action") or ""
        if any(t in act for t in _COMPOUND_ACTION):
            warn(i, "G7 action 疑似多个动作，建议拆镜")
    # G5 连续同景别 ≤ 2
    run = 1
    for i in range(1, len(shots)):
        run = run + 1 if shots[i].get("scale") == shots[i - 1].get("scale") else 1
        if run == 3:
            warn(i, f"G5 连续3镜同景别「{shots[i].get('scale')}」")
    # G9 固定镜头 ≤ 50%（超限打回：全片静止缺电影感；镜头组内含切换不计入静止）
    if shots:
        static_n = sum(1 for s in shots if s.get("camera_move") == "固定" and not s.get("cuts"))
        if static_n * 2 > len(shots):
            errors.append(f"固定镜头 {static_n}/{len(shots)} 超过一半，动作与释放段用运动镜头，同场快切合并为镜头组（铁律10/12）")
    # G10 相邻镜信息重复
    for i in range(1, len(shots)):
        a, b = shots[i - 1].get("action") or "", shots[i].get("action") or ""
        if a and b and SequenceMatcher(None, a, b).ratio() > 0.7:
            warn(i, f"G10 与上一镜动作高度重复「{b}」")
    # G8 总数与时长曲线（剪辑口径：镜头组按内切数折算）
    if shots:
        n_edit = sum(max(1, len(s.get("cuts") or [])) for s in shots)
        if not 12 <= n_edit <= 32:
            warn(0, f"G8 剪辑口径镜头数 {n_edit} 不在 12-32（生成单元 {len(shots)} 个）")
    if len({int(s.get("duration_s") or 4) for s in shots}) < 2 and len(shots) > 3:
        warn(0, "G8 全片时长恒定，缺节奏曲线")
    # G12 平均镜长（ASL）> 4.5s：整体节奏拖沓，打回要求加切（剪辑口径：镜头组按切数折算）
    if shots:
        total_d = sum(int(s.get("duration_s") or 4) for s in shots)
        effective_cuts = sum(max(1, len(s.get("cuts") or [])) for s in shots)
        asl = total_d / effective_cuts
        if asl > 4.5:
            errors.append(f"平均镜长 {asl:.1f}s 超过 4.5s——按 ASL 3-4s 拆更多短镜，或同场快切合并为镜头组（铁律3/4/12）")
    # G13 场景内至少 3 镜（按 scene 字段连续段统计）
    seg_start = 0
    for i in range(1, len(shots) + 1):
        if i == len(shots) or (shots[i].get("scene") or "") != (shots[seg_start].get("scene") or ""):
            if i - seg_start < 3 and len(shots) > 6:
                warn(seg_start, f"G13 场景「{shots[seg_start].get('scene','')}」仅 {i - seg_start} 镜，建议拆3镜以上交替")
            seg_start = i
    return {"errors": errors, "per_shot": per_shot}


def _node_meta(row: Any) -> dict[str, Any]:
    """content_nodes 行 meta → dict（jsonb 可能已解析或是字符串）。"""
    m = row["meta"]
    return m if isinstance(m, dict) else json.loads(m or "{}")


def validate_coarse(shots: list[dict[str, Any]]) -> dict[str, Any]:
    """粗拆零 token 校验：只查骨架字段（景别枚举/时长界/必填/总数）。
    详细字段（camera_move/lens_feel/lighting…）粗镜本就没有，留到详细展开阶段用
    validate_shot_list 校验——此处若强校验详细字段会满屏误报。"""
    errors: list[str] = []
    for i, s in enumerate(shots):
        no = s.get("shot_no", i + 1)
        for f in ("scene", "scale", "action", "description"):
            if not s.get(f):
                errors.append(f"镜{no}: 缺必填字段 {f}")
        if s.get("scale") and s["scale"] not in SCALES:
            errors.append(f"镜{no}: scale「{s['scale']}」不在枚举 {SCALES}")
        try:
            d = int(s.get("duration_s") or 0)
            if not 2 <= d <= 10:
                errors.append(f"镜{no}: duration_s {d}s 超界(2-10)")
        except (TypeError, ValueError):
            errors.append(f"镜{no}: duration_s 非数字")
    n = len(shots)
    if n and not 8 <= n <= 24:
        errors.append(f"总镜头数 {n} 不在 8-24（生成单元口径，宁切勿长）")
    from .scene_transitions import validate_scene_boundaries

    errors.extend(validate_scene_boundaries(shots))
    return {"errors": errors}


_CUTS_SYS = f"""你是电影分镜师与剪辑师。给每个**视频生成单元**设计专业的多镜头覆盖（cuts）：每个 cut 都是两次硬切之间的剪辑镜头；无硬切的推拉摇移属于连续镜头，不能伪装成 cuts。把确有视点变化的叙事拆成2-4个连续剪辑镜头，但节奏必须与内容匹配，**只有打斗等动作场面才快切，大部分切镜要平缓**。
规则：
1. 各切 seconds 之和 = 该镜 duration_s
2. **节奏分级（看每镜的情绪标注）**：打斗/追逐/爆点等动作场面单切1-3秒快切；常规叙事与对话单切2-4秒；情绪铺垫/释放单切3-5秒、宁少切勿碎（2切即可）——非动作内容出现1-2秒碎切是剪辑事故
3. 先设计 coverage 再填词。双人对话优先采用“中景/双人建立 → 过肩或中近景正打 → 近景反打 → 必要时情绪特写/反应镜”；多人对话先交代空间关系，再按说话者切换，并在关键台词后给听者反应镜。不要把所有说话者都写成同景别特写
4. 相邻剪辑镜头必须改变视点，景别禁止相同；常用远近节奏为“全景/中景 ↔ 近景/特写”。同一人物再次出现时可进一步推近，形成情绪递进
5. camera_move 是**该 cut 内**唯一的连续运镜，只能取 {'/'.join(CAMERA_MOVES)}；普通正反打默认“固定”，建立镜可慢推/慢拉，动作镜可跟拍/横移。一个 cut 禁止复合运镜
6. subject=该切的视觉主体（角色名/物件/环境局部），action=该切内的单一可见动作；动作场面的 action 带速度感（"猛地/骤然/疾"），平缓段用沉稳措辞（"缓缓/静静/凝视"）
7. 忠实于原镜头的画面、对白与动作，只做视点切分，不新增剧情；有对白的切把原台词完整并入 action（说：“…”）
景别只能取：{'/'.join(SCALES)}
严格输出 JSON：{{"shots":[{{"shot_no":1,"cuts":[{{"seconds":2,"scale":"特写","camera_move":"固定","subject":"阿澈的手","action":"猛地抓向翼缘"}}]}}]}}"""


def professionalize_cut_coverage(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """零 token 的 coverage 兜底。

    模型偶尔会输出“特写→特写→特写”，名义上有 cuts、实际只有换人没有镜头层次。
    保留主体、动作、时长与切序，仅修正相邻同景别，并给每切补单一运镜。艺术设计
    优先由详细分镜模型完成；本函数只保证最终落库不违反最基本的剪辑覆盖语法。
    """
    alternates = {
        "大远景": "近景", "远景": "近景", "全景": "近景",
        "中景": "特写", "近景": "特写", "特写": "近景", "大特写": "中景",
    }
    for shot in shots:
        cuts = shot.get("cuts") or []
        if len(cuts) < 2:
            continue
        previous = ""
        for cut in cuts:
            scale = cut.get("scale") or shot.get("scale") or "中景"
            if scale == previous:
                scale = alternates.get(scale, "近景")
                cut["scale"] = scale
            if not cut.get("camera_move"):
                cut["camera_move"] = "固定"
            previous = scale
    return shots


def _needs_enriched_cuts(s: dict[str, Any]) -> bool:
    """是否值得补切（用户 2026-07-12：信任模型的单机位意图，只给确实需要切换的镜补切，
    别对每个 ≥4s 镜都机械切碎）：有对白（正反打）/长镜 ≥6s（单机位易疲劳）/
    有明确动作（motion_hint 非无，需按节拍切分）三者之一才补。
    单元素 cuts 视同无切（2026-07-14 实锤：详细展开模型爱给普通镜包一层单切数组，
    旧判断见 cuts 非空就跳过 → 全片一镜到底；真正的组内切至少 2 切）。"""
    if len(s.get("cuts") or []) >= 2:
        return False
    dlg = (s.get("dialogue") or "").strip()
    if dlg and dlg != "无":
        return True
    if int(s.get("duration_s") or 0) >= 6:
        return True
    mh = (s.get("motion_hint") or "").strip()
    return bool(mh and mh != "无")


async def enrich_cuts(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """确定性补切环节（模型在主拆镜里持续无视 cuts 指引——单独小任务强制执行）：
    只对**确实需要切换**的无切镜（对白/长镜/明确动作，见 _needs_enriched_cuts）批量设计组内硬切，
    不再对每个 ≥4s 镜一律切碎（信任模型单机位意图）。失败不阻塞（保持无切原样）。"""
    todo = [s for s in shots if _needs_enriched_cuts(s)]
    if not todo:
        return shots
    desc = "\n".join(
        f"镜{s.get('shot_no')}｜{s.get('duration_s')}s｜{s.get('scale')}｜情绪:{s.get('mood') or '常规'}"
        f"｜动感:{s.get('motion_hint') or '无'}｜动作:{s.get('action', '')}"
        f"｜画面:{(s.get('description') or '')[:60]}｜对白:{s.get('dialogue', '无')}"
        for s in todo
    )
    try:
        data = await llm.chat_json(_CUTS_SYS, f"为以下镜头设计组内硬切：\n{desc}", max_tokens=6000)
    except Exception:  # noqa: BLE001 — 补切失败不阻塞拆镜主流程
        return shots
    by_no = {int(x.get("shot_no", 0)): x.get("cuts") or [] for x in (data.get("shots") or [])}
    for s in shots:
        cuts = by_no.get(int(s.get("shot_no") or 0))
        # 单元素旧切允许被真组内切（≥2）替换——单切与无切等价，不是模型的单机位意图
        if cuts and 2 <= len(cuts) <= 5 and len(s.get("cuts") or []) < 2:
            s["cuts"] = cuts
    return shots


async def redesign_shot_coverage(pool: asyncpg.Pool, shot_id: int) -> dict[str, Any]:
    """显式重做一个视频生成单元的剪辑覆盖并落库；失败时保留旧设计。"""
    row = await pool.fetchrow(
        "SELECT summary,meta FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id)
    if not row:
        raise ValueError("分镜不存在")
    original = _node_meta(row)
    candidate = {**original, "description": row["summary"] or "", "cuts": []}
    redesigned = (await enrich_cuts([candidate]))[0]
    cuts = redesigned.get("cuts") or []
    if len(cuts) < 2:
        return original
    professionalize_cut_coverage([redesigned])
    duration = clamp_shot_seconds(sum(max(1, int(c.get("seconds") or 1)) for c in cuts))
    await pool.execute(
        "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
        shot_id, json.dumps({"cuts": cuts, "duration_s": duration}, ensure_ascii=False),
    )
    return {**original, "cuts": cuts, "duration_s": duration}


_CLOSE_SCALES = ("特写", "大特写")
# 面部级特征词过滤（wide 镜身份层用）单一来源在 character_context.non_face_segments

_PAREN_NOTE = re.compile(r"[（(][^（）()]*[）)]")


def _base_name(name: str) -> str:
    """角色名去括号备注："沉默老船长（黑衣人）"→"沉默老船长"。用于展示与匹配。"""
    name = (name or "").strip()
    return _PAREN_NOTE.sub("", name).strip() or name


def _names_match(a: str, b: str) -> bool:
    """角色名模糊同一性：基名（去括号）互相包含即视为同一角色——
    脚本常用短名"老船长"指代要素原名"沉默老船长（黑衣人）"。"""
    a2, b2 = _base_name(a), _base_name(b)
    return bool(a2 and b2 and (a2 in b2 or b2 in a2))


_LOC_PLACEHOLDERS = ("未知", "无", "不明", "待定", "未定", "不详")


def _clean_location(scene: str) -> str:
    """scene 字段（"场景名/时间/地点"）剔除占位段——"旅途/白天/未知"里的"未知"
    被拼进"必须发生在此地点"强约束句纯属误导（ch16镜460 实锤）。"""
    parts = [t.strip() for t in re.split(r"[/／]", scene or "")
             if t.strip() and t.strip() not in _LOC_PLACEHOLDERS]
    return "/".join(parts)


_POS_HEADS = ("在", "坐", "站", "骑", "位于", "躺", "跪", "立", "悬", "浮", "趴", "从")


def _at(pos: str) -> str:
    """站位值拼接（blocking 产物）：值常自带"在/坐在/骑在"等开头——没带才补"在"，
    防"巡夜在在环礁城边缘"式双字（冒烟实锤）。"""
    pos = (pos or "").strip()
    return pos if pos.startswith(_POS_HEADS) else f"在{pos}"


def _name_in_text(name: str, text: str) -> bool:
    """角色名是否出现在剧本文字里（全名/基名/括号别名/尾段兜底）——用于判定
    「该角色是否真的出现在这段画面」，决定要不要织外貌、传设定图。
    括号别名："会驭风少女（灵悦）"在剧本里常直接写"灵悦"（shot451 实锤）；
    尾段兜底：原文常用"清沅"指"苏清沅"、"老船长"指"沉默老船长（黑衣人）"。"""
    if not name or not text:
        return False
    aliases = {name, _base_name(name), *re.findall(r"[（(]([^（）()]+)[）)]", name)}
    return any(a and (a in text or any(len(a) > n and a[-n:] in text for n in (3, 2)))
               for a in aliases)


# 指人字眼（角色在场复核的代词兜底）：剧本用"她/他/众人"指代而不点名时无法逐名判定
_PERSON_WORDS = ("她", "他", "两人", "二人", "三人", "众人", "人们", "人群", "人影", "身影",
                 "少女", "少年", "女子", "男子", "老者", "孩童", "青年", "妇人")


def _chars_present(names: list[str], corpus: str) -> list[str]:
    """按剧本文字复核出场角色（2026-07-14 用户实锤：纯空景镜被织入主角外貌+三视图）：
    - 名字（含基名/尾段）被点到 → 只保留被点到的角色
    - 无一点名但文字用代词/泛称指人 → 无法逐名判定，保留全部声明角色（宁全勿漏）
    - 通篇不见任何指人字眼（纯景物/空景） → 全部剔除"""
    if not names:
        return []
    if not corpus:
        return list(names)
    hits = [n for n in names if _name_in_text(n, corpus)]
    if hits:
        return hits
    return list(names) if any(w in corpus for w in _PERSON_WORDS) else []


def validate_shot_links(shots: list[dict[str, Any]]) -> None:
    """镜间衔接标记确定性校验（原地归一为 bool）：LLM 的 link_prev 只是意图，
    落库前用骨架事实复核——场景不同或出场角色完全不搭的「连贯」一律降级为跳切。
    错误的接缝帧比没有更糟：会把下一场的画面焊死到上一场结尾。镜1恒为跳切。"""
    prev: dict[str, Any] | None = None
    for s in shots:
        v = s.get("link_prev")
        want = ("连贯" in v) if isinstance(v, str) else bool(v)  # MD 流式已归一 bool，JSON 路径在此归一
        ok = want and prev is not None
        if ok:
            a, b = _clean_location(prev.get("scene") or ""), _clean_location(s.get("scene") or "")
            same_loc = bool(a and b and (a in b or b in a or any(b[j:j + 2] in a for j in range(len(b) - 1))))
            ca, cb = prev.get("characters") or [], s.get("characters") or []
            # 双方都有出场角色时须有交集（空景承接/入画允许单边为空）
            overlap = not ca or not cb or any(_names_match(x, y) for x in ca for y in cb)
            if not (same_loc and overlap):
                ok = False
                log.info("镜%s link_prev「连贯」被降级为跳切：地点或出场角色与上一镜不连续（%s → %s）",
                         s.get("shot_no"), a or "?", b or "?")
        s["link_prev"] = ok
        prev = s


_HAN = re.compile(r"[一-鿿]")
_SAY = re.compile(r"说：?[“\"](.+?)[”\"]")
_SEG_SPAN = re.compile(r"[（(]\s*(\d+)\s*[-–~]\s*(\d+)\s*秒")


def timeline_end_seconds(text: str) -> int | None:
    """从时间轴提示词解析总时长 = 最大的秒区间终点（如"（7-9秒·切近景）"→9）。
    质检重构可能加长时间轴——提交给模型的 duration 必须跟随重构版，否则视频被掐一半。"""
    ends = [int(m.group(2)) for m in _SEG_SPAN.finditer(text or "")]
    return max(ends) if ends else None


def _speech_seconds(text: str) -> int:
    """中文对白时长估算：语速约 4 字/秒（240字/分），1-6s 封顶。"""
    n = len(_HAN.findall(text or ""))
    return max(1, min(6, round(n / 4) or 1))


# ── 专业时长评估（用户 2026-07-12 定稿）：单镜时长由**本镜实际内容**推导，
# 不沿用粗拆阶段给的预估总时长（那个不够精细）。唯一硬约束=单镜≥4s（视频模型计费下限），
# 上限=视频模型单次上限（media 层同口径夹紧）。生成视频/装配视频提示词时以此为权威时长。
_PROVIDER_MAX_S = 15  # Seedance 2.0 单次 4-15s（见 media._post_ark_task）
# ── 单镜时长夹紧单一声明（2026-07-31 收敛：此前 max(4,min(...)) 散落 8 处、上限各写各的）。
# 各上限差异是有语义的，不粗暴统一：
SHOT_MIN_S = 4            # 视频模型计费/时间轴下限，所有路径共用
SHOT_DECLARED_MAX_S = 10  # LLM 直接声明的时长上限（粗拆/详细/重设计声明值不可信到 15）
SHOT_NO_CUTS_MAX_S = 8    # 无 cuts 单元镜上限（要更长的多节拍必须走 cuts 路径）
SHOT_DIALOGUE_MAX_S = 6   # 纯对白重排上限（对白 4字/秒+呼吸，超 6s 应拆镜）
# 时间轴/cuts 推导路径上限 = _PROVIDER_MAX_S（实际内容推导出的时长可信，跟模型能力）


def clamp_shot_seconds(value: Any, cap: int = SHOT_DECLARED_MAX_S) -> int:
    """单镜时长夹紧唯一实现：所有落库/回写 duration_s 的路径必须走这里。"""
    try:
        v = int(value or 0)
    except (TypeError, ValueError):
        v = 0
    return max(SHOT_MIN_S, min(cap, v))
# 切镜节奏分级（用户 2026-07-12 定稿）：**打斗等动作场面才快切，大部分切镜要平缓**。
# 对话交锋/冲突属言语对抗，不算视觉动作场面，走常规节奏
_FAST_PACE_WORDS = ("爆点", "搏斗", "打斗", "武打", "格斗", "追逐", "奔跑", "激战", "袭击", "逃亡", "坠落", "爆炸")
_SLOW_PACE_WORDS = ("释放", "铺垫", "建立", "抒情", "情绪支点", "凝滞", "余韵", "对视", "沉思", "告别")
_ACTION_MOODS = _FAST_PACE_WORDS
_SLOW_MOODS = _SLOW_PACE_WORDS


def cut_pace_bounds(meta: dict[str, Any]) -> tuple[int, int]:
    """按情绪功能/动作提示定组内**无对白切**的秒界：
    打斗/追逐等动作场面 1-3s 快切；常规叙事与对话 2-4s；情绪铺垫/释放 3-5s 宁少切勿碎。"""
    hint = f"{meta.get('mood') or ''} {meta.get('motion_hint') or ''}"
    if any(w in hint for w in _FAST_PACE_WORDS):
        return 1, 3
    if any(w in hint for w in _SLOW_PACE_WORDS):
        return 3, 5
    return 2, 4


def estimate_shot_duration(meta: dict[str, Any], desc: str = "") -> int:
    """按内容专业评估单镜时长（秒），**忽略粗拆预估的 duration_s**：
    - 有 cuts：各切秒数之和（切秒已由 retime_dialogue 按对白字数/动作节拍精算，权威、最细粒度）；
    - 无 cuts：单一生成单元（单机位+单动作），时长 = max(对白时长, 镜头类型基准)——
      对白按 4字/秒 + 1s 呼吸；无切镜不按画面描述的分句去乘（那是空间细节不是时间节拍），
      只给合理的单元基准（动作干脆 4s、铺垫/建立/静止留白 5s、情绪释放一镜到底 6s）。
      需要更细的多节拍时长就交给 cuts 路径。
    结果夹到 [4, 模型单次上限]。"""
    cuts = meta.get("cuts") or []
    if cuts:
        return clamp_shot_seconds(sum(max(1, int(c.get("seconds") or 2)) for c in cuts),
                                  cap=_PROVIDER_MAX_S)
    dlg = (meta.get("dialogue") or "").strip()
    speech = _speech_seconds(dlg) + 1 if dlg and dlg != "无" else 0
    mood, move = meta.get("mood") or "", meta.get("motion_hint") or ""
    if "释放" in mood:
        base = 6           # 情绪释放：一镜到底可留长
    elif any(k in mood for k in _ACTION_MOODS) or (move and move != "无"):
        base = 4           # 动作单元：干脆利落（复杂动作应给 cuts，走上面的路径）
    elif any(k in mood for k in _SLOW_MOODS) or meta.get("camera_move") == "固定":
        base = 5           # 铺垫/建立/静止：留白
    else:
        base = 4
    return clamp_shot_seconds(max(speech, base), cap=_PROVIDER_MAX_S)


_LISTENER_ACTION = "静静听着，眼神随话语微微变化"


def retime_dialogue(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """确定性时长校准（零 token，2026-07-12 修订）：
    对白切=字数÷4秒 **+1s 演出余量**（实测恰好念完的时长毫无表演空间，是"切给的时间太少"
    的机制根源）；动作切 1-3s；长台词=说话人 5s + 听者反应切（正反打）。
    幂等：紧跟长台词后已有无对白反应切时不再插听者切（装配期会重跑本函数，重复插会越跑越长）；
    切总和 <4s 时拉伸末切补足（时间轴终点必须=提交时长，差 1s 视频就掐尾）。
    无对白切按 cut_pace_bounds 分级钳制：打斗才 1-3s 快切，常规 2-4s，铺垫/释放 3-5s。"""
    for s in shots:
        cuts = s.get("cuts") or []
        if cuts:
            lo, hi = cut_pace_bounds(s)
            new_cuts: list[dict[str, Any]] = []
            for idx, c in enumerate(cuts):
                m = _SAY.search(c.get("action") or "")
                if m:
                    perform = min(7, _speech_seconds(m.group(1)) + 1)  # 念词+演出余量
                    if perform > 5:
                        # 长台词正反打：说话人≤5s + 听者反应切——消灭"7s 盯脸镜"。
                        # 幂等：下一切已是无对白反应切 → 只定说话人时长，不重复插听者
                        c["seconds"] = 5
                        new_cuts.append(c)
                        nxt = cuts[idx + 1] if idx + 1 < len(cuts) else None
                        if nxt is None or _SAY.search(nxt.get("action") or ""):
                            listener = next(
                                (n for n in (s.get("characters") or [])
                                 if not _names_match(n, c.get("subject") or "")), "")
                            new_cuts.append({
                                "seconds": max(1, min(2, perform - 5)),
                                "scale": "近景" if c.get("scale") != "近景" else "中景",
                                "subject": _base_name(listener) or "听者",
                                "action": _LISTENER_ACTION,
                            })
                        continue
                    c["seconds"] = perform
                else:
                    c["seconds"] = max(lo, min(hi, int(c.get("seconds") or 2)))
                new_cuts.append(c)
            total = sum(x["seconds"] for x in new_cuts)
            if total < 4:  # 时间轴与计费下限对齐：拉伸末切而非只抬 duration_s
                new_cuts[-1]["seconds"] += 4 - total
                total = 4
            s["cuts"] = new_cuts
            # 总时长=各切之和（上限跟模型 15s，不再压到 10s——压缩=剧情演一半）
            s["duration_s"] = clamp_shot_seconds(total, cap=_PROVIDER_MAX_S)
        else:
            dlg = (s.get("dialogue") or "").strip()
            if dlg and dlg != "无":
                s["duration_s"] = clamp_shot_seconds(_speech_seconds(dlg) + 1,
                                                     cap=SHOT_DIALOGUE_MAX_S)
    return shots


def _dialogue_lines(dlg: str) -> list[tuple[str, str]]:
    """meta.dialogue → [(说话人, 台词)]。支持 "A：… / B：…"、空格分隔的多说话人段、无说话人纯台词。"""
    out: list[tuple[str, str]] = []
    for part in re.split(r"\s*/\s*", dlg or ""):
        part = part.strip()
        if not part or part == "无":
            continue
        # 同段里混多个 "说话人：" 标记（粗拆常见）→ 按标记再切。
        # 说话人上限 12 字且允许括号备注（ch16镜453 实锤："沉默老船长（黑衣人）"10字，
        # 旧上限6字解析失败 → 名字混进台词被念出来 + 台词兜底塞给错误角色）
        for seg in re.split(r"\s+(?=[^：:\s，。？！“”\"]{1,12}[：:])", part):
            seg = seg.strip()
            if not seg:
                continue
            m = re.match(r"^([^：:“”\"，。？！\s]{1,12})[：:]\s*(.+)$", seg, re.S)
            speaker, text = (m.group(1), m.group(2)) if m else ("", seg)
            text = text.strip().strip("“”\"")
            # "阿澈：无"=该角色没台词的舞台指示，不是对白，注入会生成人念"无"（实锤 bug）
            if text in ("无", "沉默", "不回答", "沉默不语", "不语", "无对白"):
                continue
            out.append((speaker, text))
    return out


def fit_cuts_for_prompt(meta: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """装配期确定性保真（零 token，不落库；用户 2026-07-12 实测定稿）——治两类实锤事故：
    ①对白丢失：脚本 dialogue 有台词但 cuts 里没有（ch6镜14 成片变哑剧）→ 注入到主体匹配的切，
      找不到宿主则按台词顺序追加新切；
    ②切时长不足/时间轴≠提交时长：重跑 retime（念词+演出余量+末切补足下限）；
      总和超模型上限 15s 时按 听者反应→无对白切→丢弃填充反应切 的顺序压缩（保对白完整），
      仍超则记"内容超载建议拆镜"。只在已有 cuts 的镜上做（无切镜走叙事节拍路径+对白保底句）。"""
    cuts = [dict(c) for c in (meta.get("cuts") or [])]
    notes: list[str] = []
    if not cuts:
        return [], notes
    chars = meta.get("characters") or []
    # ① 对白注入：脚本每条台词都必须能在切里找到（取前6字匹配，避免标点差异误判）
    for speaker, text in _dialogue_lines((meta.get("dialogue") or "").strip()):
        key = text[:6]
        if not key or any(key in (c.get("action") or "") for c in cuts):
            continue
        # 宿主匹配用基名模糊同一性（"沉默老船长（黑衣人）"↔切主体"老船长"）
        host = next((c for c in cuts
                     if speaker and _names_match(speaker, c.get("subject") or "")
                     and not _SAY.search(c.get("action") or "")), None)
        if host is not None:
            host["action"] = (host.get("action") or "").rstrip("。") + f"，说：“{text}”"
        else:
            cuts.append({
                "seconds": _speech_seconds(text) + 1,
                "scale": "近景" if (cuts[-1].get("scale") != "近景") else "中景",
                "subject": _base_name(speaker) or (chars[0] if chars else ""),
                "action": f"说：“{text}”",
            })
        notes.append(f"对白注入: {speaker or '?'}「{text[:12]}」")
    # ② 时长精算（幂等 retime：演出余量+听者切+下限末切补足；节奏界随 mood/motion_hint）
    pseudo: dict[str, Any] = {"cuts": cuts, "characters": chars, "dialogue": meta.get("dialogue"),
                              "mood": meta.get("mood"), "motion_hint": meta.get("motion_hint")}
    retime_dialogue([pseudo])
    cuts = pseudo["cuts"]
    # ③ 超上限压缩（保对白完整）：听者反应切→1s → 其余无对白切→1s → 丢弃填充反应切
    total = sum(max(1, int(c.get("seconds") or 1)) for c in cuts)
    if total > _PROVIDER_MAX_S:
        for c in cuts:
            if total <= _PROVIDER_MAX_S:
                break
            if not _SAY.search(c.get("action") or ""):
                give = min(int(c.get("seconds") or 1) - 1, total - _PROVIDER_MAX_S)
                if give > 0:
                    c["seconds"] = int(c["seconds"]) - give
                    total -= give
        if total > _PROVIDER_MAX_S:
            kept = []
            for c in cuts:
                if total > _PROVIDER_MAX_S and (c.get("action") or "") == _LISTENER_ACTION:
                    total -= int(c.get("seconds") or 1)
                    continue
                kept.append(c)
            cuts = kept
        if total > _PROVIDER_MAX_S:
            notes.append(f"内容超载: 精算需{total}s > 上限{_PROVIDER_MAX_S}s，建议拆镜")
    return cuts, notes


def reorder_dialogue_cuts(shots: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    """确定性顺序修复（零 token）：镜头组内对白切按原文出现顺序重排，
    反应切跟随其前一条对白切。实测模型对问答顺序有顽固幻觉，重拆两轮都摆不对——只能机械重排。"""
    for s in shots:
        cuts = s.get("cuts") or []
        if len(cuts) < 2:
            continue
        groups: list[dict[str, Any]] = []
        cur: dict[str, Any] | None = None
        for c in cuts:
            m = _SAY.search(c.get("action") or "")
            if m:
                snip = m.group(1)[:10]
                idx = source.find(snip) if len(snip) >= 4 else -1
                cur = {"idx": idx, "cuts": [c]}
                groups.append(cur)
            elif cur is None:
                cur = {"idx": -1, "cuts": [c]}
                groups.append(cur)
            else:
                cur["cuts"].append(c)
        idxs = [g["idx"] for g in groups if g["idx"] >= 0]
        if len(idxs) < 2 or idxs == sorted(idxs):
            continue
        ordered = sorted(enumerate(groups), key=lambda t: (t[1]["idx"] if t[1]["idx"] >= 0 else t[0] - 100))
        s["cuts"] = [c for _, g in ordered for c in g["cuts"]]
    return shots


def calm_env_cuts(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """确定性收敛（零 token）：无对白的纯环境/氛围镜切数 ≤3——4×1s 的碎切破坏情绪连贯（总审实证）。"""
    for s in shots:
        cuts = s.get("cuts") or []
        if len(cuts) > 3 and not any(_SAY.search(c.get("action") or "") for c in cuts):
            total = sum(int(c.get("seconds") or 1) for c in cuts)
            kept = cuts[:3]
            base = max(1, total // 3)
            for c in kept:
                c["seconds"] = base
            kept[-1]["seconds"] = max(1, total - base * 2)
            s["cuts"] = kept
    return shots


def dialogue_order_violations(shots: list[dict[str, Any]], source: str) -> list[str]:
    """确定性对白顺序校验（零 token）：cuts/镜的对白必须按原文出现顺序排列——
    实测模型会把问答顺序打乱（先"要。"后"仍要下去？"），总审也抓不住。"""
    out: list[str] = []
    last_idx, last_no = -1, None
    for s in shots:
        snippets: list[str] = []
        for c in s.get("cuts") or []:
            m = _SAY.search(c.get("action") or "")
            if m:
                snippets.append(m.group(1)[:10])
        if not snippets:
            d = (s.get("dialogue") or "").strip()
            if d and d != "无":
                snippets.append(d.split("/")[0].strip()[:10])
        for snip in snippets:
            if len(snip) < 4:
                continue  # 太短的片段（"要。"）在原文中不唯一，跳过
            i = source.find(snip)
            if i == -1:
                continue
            if i < last_idx:
                out.append(f"镜{s.get('shot_no')}: 对白「{snip}…」顺序与原文不符（应在镜{last_no}的台词之前）")
            else:
                last_idx, last_no = i, s.get("shot_no")
    return out


def safe_first_cut(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """确定性重排（零 token）：首切避开人物面部特写——写实首帧的面部特写会触发
    ARK 真人隐私审核（实测 I2V 拒收），且质检安全维度会永久硬阻断。
    电影语言上从中/远景切入再切进特写同样专业。"""
    for s in shots:
        cuts = s.get("cuts") or []
        if len(cuts) < 2 or (cuts[0].get("scale") or "") not in _CLOSE_SCALES:
            continue
        for j in range(1, len(cuts)):
            if (cuts[j].get("scale") or "") not in _CLOSE_SCALES:
                cuts[0], cuts[j] = cuts[j], cuts[0]
                break
    return shots


def _make_group(batch: list[dict[str, Any]]) -> dict[str, Any]:
    """把连续同场短镜打包成一个镜头组（生成单元）：首切定首帧构图，各镜降为 cuts。"""
    cuts, chars, dlgs = [], [], []
    for b in batch:
        subj = "、".join(b.get("characters") or []) or b.get("scene", "")
        act = b.get("action") or (b.get("description") or "")[:24]
        dlg = (b.get("dialogue") or "").strip()
        if dlg and dlg != "无":
            # 只把台词正文并入 action（剥掉"说话人："前缀——否则名字会被当台词念出来）
            _texts = [t for _, t in _dialogue_lines(dlg)]
            if _texts:
                act = f"{act}，说：“{'；'.join(_texts)}”"
                dlgs.append(dlg)
        cuts.append({
            "seconds": int(b.get("duration_s") or 3),
            "scale": b.get("scale", ""), "subject": subj, "action": act,
        })
        for c in b.get("characters") or []:
            if c not in chars:
                chars.append(c)
    g = dict(batch[0])  # 首切的构图/光效/色调即首帧
    g.update({
        "cuts": cuts,
        "duration_s": sum(c["seconds"] for c in cuts),
        "characters": chars,
        "dialogue": " / ".join(dlgs) or "无",
        "mood": "对话交锋" if dlgs else (batch[0].get("mood") or ""),
    })
    return g


def merge_dialogue_groups(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """确定性镜头组合并（零 token，铁律12 的代码兜底——不靠模型自觉）：
    同一场景内连续的对话/反应短镜 ≥2 个 → 合并为 5-10s 镜头组（≤5切/≤10s 分批）。
    模型已自带 cuts 的镜原样保留；建立/释放等无对白镜不合并。"""

    def groupable(s: dict[str, Any]) -> bool:
        if s.get("cuts"):
            return False
        dlg = (s.get("dialogue") or "").strip()
        return bool(dlg and dlg != "无") or "反应" in (s.get("mood") or "")

    out: list[dict[str, Any]] = []
    i = 0
    while i < len(shots):
        run = []
        j = i
        while (j < len(shots) and groupable(shots[j])
               and shots[j].get("scene_element") == shots[i].get("scene_element")):
            run.append(shots[j])
            j += 1
        if len(run) >= 2:
            batch: list[dict[str, Any]] = []
            dur = 0
            for r in run:
                d = int(r.get("duration_s") or 3)
                if batch and (dur + d > 10 or len(batch) >= 5):
                    out.append(_make_group(batch) if len(batch) > 1 else batch[0])
                    batch, dur = [], 0
                batch.append(r)
                dur += d
            if batch:
                out.append(_make_group(batch) if len(batch) > 1 else batch[0])
            i = j
        else:
            out.append(shots[i])
            i += 1
    for idx, s in enumerate(out, 1):
        s["shot_no"] = idx
    return out


_STORYBOARD_COARSE_QC_SYS = """你是分镜表总审导演。这是**分镜脚本骨架**（尚无镜头语言细节，只有景别/时长/动作/对白），按四个维度审查，输出 JSON。
维度：
1 叙事覆盖：分镜忠实覆盖章节内容，关键情节无遗漏、无凭空新增
2 场景与动作连贯：相邻镜头空间/时间/动作衔接自然无跳跃；同场景镜头聚簇，无来回穿越；**对白出现顺序必须与原文一致**
3 分镜划分：每镜只回答一个问题；相邻镜头信息不重复；对话密集处应合并为镜头组/正反打（而非拆成多个独立单镜）
4 节奏：景别远近交替（避免连续3镜同景别）；时长有起伏、剪辑口径平均镜长3-4s（宁短勿长）
注意：本轮只审骨架，**不要**对角度/运镜/焦段/光效/cuts 等尚未生成的细节提问题。
每条问题必须指明镜号，并配一条可执行的修改建议。评分0-100，≥80才可判合格。
严格输出 JSON：
{"合格": true, "得分": 0, "问题": ["镜N: 维度M 具体问题"], "修改建议": ["镜N: 具体改法"]}"""


async def _storyboard_coarse_qc(shots: list[dict[str, Any]], source: str) -> dict[str, Any]:
    """章级粗拆总审（用户 2026-07-12 两阶段定稿）：只审骨架四维（覆盖/连贯/划分/节奏），
    问题+建议供重拆。失败不阻塞。详细分镜的镜头语言质量在按板详细展开阶段用零 token Gate 把关。"""
    rows = []
    for s in shots:
        cuts = s.get("cuts") or []
        rows.append(
            f"镜{s.get('shot_no')}｜{s.get('duration_s')}s｜{s.get('scale')}"
            f"｜对白:{(s.get('dialogue') or '无')[:40]}｜动作:{(s.get('action') or '')[:30]}"
            + (f"｜组内{len(cuts)}切" if cuts else "")
        )
    user = f"章节内容（节选）：\n{source[:2500]}\n\n分镜脚本骨架：\n" + "\n".join(rows)
    try:
        qc = await llm.chat_json(_STORYBOARD_COARSE_QC_SYS, user, max_tokens=3000, purpose="review")
        return {
            "合格": bool(qc.get("合格")), "得分": qc.get("得分"),
            "问题": qc.get("问题") or [], "修改建议": qc.get("修改建议") or [],
        }
    except Exception:  # noqa: BLE001 — 总审失败不阻塞拆镜
        return {"合格": True, "得分": None, "问题": [], "修改建议": [], "跳过": True}


async def breakdown_chapter(
    pool: asyncpg.Pool, project_id: int, node_id: int, task_id: int | None = None,
) -> list[dict[str, Any]]:
    """章节→**粗拆分镜脚本骨架**（两阶段拆镜第一阶段；2026-07-13 改流式 MD）：
    LLM 按固定 Markdown 逐镜流式输出（storyboard_stream），解析到完整一镜立即
    落库+SSE 广播（一镜存一镜，前端实时逐镜显示）；流式失败自动回退一次性 JSON。
    仅首轮清场+逐镜可见；校验/总审重拆为静默轮（不动库不广播，时间轴保持上一版），
    全部质检收敛后做终局权威落库一次性替换（镜头组合并/重编号后的最终列表）。
    detail_pending=true 交由 expand_shot_details 任务按板(≤16镜)补详细镜头语言。"""
    from . import events, flow
    from .storyboard_stream import COARSE_MD_FORMAT, stream_coarse_md

    async with pool.acquire() as conn:
        project = await conn.fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
        node = await conn.fetchrow("SELECT * FROM content_nodes WHERE id=$1", node_id)
        project = await volumes.effective_for_chapter(conn, project, node_id)  # 画风跟随本章所属卷
        body = await conn.fetchrow(
            "SELECT content FROM content_bodies WHERE node_id=$1 ORDER BY version DESC LIMIT 1",
            node_id,
        )
        prefs = await project_preferences(conn, project_id, "director")
        system = await _director_system(conn, project_id, "粗拆骨架输出格式")
        # 流式 MD 版系统提示词：铁律同源，仅输出格式一段不同（约束正文取库化粗拆格式段的前半，
        # 两版都要——MD 版把 JSON 输出契约替换为 MD 模板）
        _coarse_fmt = await _director_skill(conn, project_id, "粗拆骨架输出格式",
                                            _STORYBOARD_COARSE_FORMAT)
        system_md = await _director_system(
            conn, project_id,
            fmt_override=_coarse_fmt.split("严格输出 JSON")[0] + COARSE_MD_FORMAT,
        )
        scenes = await conn.fetch(
            "SELECT name, brief FROM content_elements WHERE project_id=$1 AND kind='scene'",
            project_id,
        )
        # 角色清单进拆镜提示词（真实验证实锤：不给清单，模型写"长老/黑衣人"泛称
        # → 关联不上设定图与外貌 → 该角色跨镜必漂）
        char_rows = await conn.fetch(
            "SELECT name, brief FROM content_elements WHERE project_id=$1 AND kind='character'",
            project_id,
        )
        # 要素名→id 映射：分镜级要素关联（每镜挂 element_ids + element_appearances，参考图按镜召回）
        elem_map = {
            r["name"]: r["id"] for r in await conn.fetch(
                "SELECT id, name FROM content_elements WHERE project_id=$1 AND kind IN ('character','scene')",
                project_id,
            )
        }
    # 无正文时用目录故事线拆镜（支持"直接生成第一章视频"的动态路径）
    source = body["content"] if body else f"（本章尚无正文，按故事线拆镜）{node['summary']}"
    pref_text = "\n".join(f"- {p}" for p in prefs)
    scene_text = "\n".join(f"- {s['name']}：{s['brief']}" for s in scenes) or "（无，scene_element 填 无）"
    roster = "\n".join(roster_line(c["name"], c["brief"]) for c in char_rows) or "（无）"
    user = (
        f"项目画风：{project['art_style']}\n"
        + (f"导演偏好：\n{pref_text}\n" if pref_text else "")
        + f"\n项目场景要素（scene_element 从中选）：\n{scene_text}\n"
        + f"\n项目角色要素（characters 只能取此清单原名，泛称必须还原）：\n{roster}\n"
        + f"\n第{node['seq']}章《{node['title']}》内容：\n{source[:5000]}"
    )
    # ── 流式一轮：清场 → MD 逐镜流出 → 每镜立即落库+广播；失败回退一次性 JSON ──
    async def persist_stream_shot(s: dict[str, Any], n: int) -> None:
        """流式临时镜落库（provisional：终局权威落库会整体替换）+ SSE 逐镜推送。"""
        linked = list(s.get("characters") or [])
        if s.get("scene_element") and s["scene_element"] != "无":
            linked.append(s["scene_element"])
        meta = {
            "shot_no": s.get("shot_no"), "scene": s.get("scene", ""),
            "scene_element": s.get("scene_element", ""), "scale": s.get("scale", "中景"),
            "duration_s": clamp_shot_seconds(s.get("duration_s")),
            "action": s.get("action", ""), "dialogue": s.get("dialogue", "无"),
            "characters": s.get("characters", []),
            "link_prev": bool(s.get("link_prev")),  # 临时值，终局落库前经 validate_shot_links 复核
            "element_ids": [elem_map[x] for x in dict.fromkeys(linked) if x in elem_map],
            "detail_pending": True, "provisional": True,
        }
        await pool.execute(
            "INSERT INTO content_nodes (project_id, parent_id, kind, seq, title, summary, meta) "
            "VALUES ($1,$2,'shot',$3,$4,$5,$6::jsonb)",
            project_id, node_id, int(s.get("shot_no") or n),
            f"镜头{s.get('shot_no') or n}", s.get("description", ""),
            json.dumps(meta, ensure_ascii=False),
        )
        events.publish(project_id, {"type": "shot", "chapter_id": node_id,
                                    "shot_no": s.get("shot_no"), "count": n})
        if task_id:
            await flow.set_progress(pool, task_id, min(80, 5 + n * 5))

    async def quiet_progress(s: dict[str, Any], n: int) -> None:
        """静默轮（校验/总审重拆）逐镜回调：只推进度，不动库不广播——
        时间轴保持上一版可见，避免"全部消失又逐个重来"的反复闪烁。"""
        if task_id:
            await flow.set_progress(pool, task_id, min(80, 5 + n * 5))

    async def run_round(feedback: str | None, live: bool = False) -> list[dict[str, Any]]:
        """一轮完整粗拆：流式 MD；异常或零产出回退 JSON。
        live=True 仅首轮：把上一版整集分镜整体移入回收站（软删）再逐镜落库+广播（前端实时逐镜显示）；
        重拆轮静默跑，结果只进内存，由终局权威落库一次性替换。"""
        if live:
            # 上一版整集分镜软删入回收站：镜行保留→content_attachments 不级联清理，视频/首帧资料完整留存。
            # 先清这些镜的要素出现索引（派生索引，回收镜不应污染后续要素召回），再置 deleted_at。
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        "DELETE FROM element_appearances ea USING content_nodes n "
                        "WHERE ea.node_id=n.id AND n.parent_id=$1 AND n.kind='shot' "
                        "AND n.deleted_at IS NULL", node_id)
                    await conn.execute(
                        "UPDATE content_nodes SET deleted_at=now(), updated_at=now() "
                        "WHERE parent_id=$1 AND kind='shot' AND deleted_at IS NULL", node_id)
            events.publish(project_id, {"type": "shots_reset", "chapter_id": node_id})
        u = user + (feedback or "")
        try:
            shots_ = await stream_coarse_md(system_md, u, persist_stream_shot if live else quiet_progress)
            if shots_:
                return shots_
            log.warning("章 %s 流式粗拆零产出，回退一次性 JSON", node_id)
        except Exception as e:  # noqa: BLE001 — 提供商不支持流式/格式崩坏均回退，绝不让拆镜挂死
            log.warning("章 %s 流式粗拆失败，回退一次性 JSON: %s", node_id, e)
        data = await llm.chat_json(system, u, max_tokens=4000)
        return data.get("shots") or []

    shots = merge_dialogue_groups(await run_round(None, live=True))  # 零 token，铁律12 兜底 + 定死最终 shot_no

    # 粗拆零 token 校验：骨架级违规 → 带明细重拆一次（重拆同样流式，前端看得到重排过程）
    report = validate_coarse(shots)
    if report["errors"]:
        feedback = "\n".join(report["errors"][:20])
        reshot = merge_dialogue_groups(await run_round(
            f"\n\n【上一版粗拆违反以下要求，请修正后重新输出全部分镜骨架】\n{feedback}"))
        shots = reshot or shots
        report = validate_coarse(shots)

    # 章级粗审（四维：覆盖/连贯/划分/节奏）+ 对白顺序校验：不合格带问题与建议重拆一次
    qc = await _storyboard_coarse_qc(shots, source)
    order_viol = dialogue_order_violations(shots, source)
    if order_viol:
        qc = {**qc, "合格": False, "问题": order_viol + (qc.get("问题") or [])}
    if not qc.get("合格"):
        fb = "\n".join(qc.get("问题", [])[:12] + ["建议：" + x for x in qc.get("修改建议", [])[:12]])
        reshot = merge_dialogue_groups(await run_round(
            f"\n\n【粗拆总审不合格，按以下问题与建议重新输出全部分镜骨架】\n{fb}"))
        if reshot:
            shots = reshot
        qc2 = await _storyboard_coarse_qc(shots, source)
        order2 = dialogue_order_violations(shots, source)
        if order2:
            qc2 = {**qc2, "合格": False, "问题": order2 + (qc2.get("问题") or [])}
        qc = {**qc2, "重拆": True, "初审问题": qc.get("问题", [])}
    report = validate_coarse(shots)
    # 镜间衔接标记复核（跨镜连贯钥匙）：LLM 意图 × 骨架事实（同地点+角色连续）→ bool 落库
    validate_shot_links(shots)
    # 场景归组（2026-07-16 空间锚定）：scene 连续段→scene_seg，详细展开后由
    # SceneBlockingStep 按组产出空间布局+逐镜站位链（治跳切镜之间零空间信息传递）
    from .scene_blocking import assign_scene_segments

    assign_scene_segments(shots)

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 只硬删本轮流式落库的临时镜（存活态）；已软删入回收站的上一版整集分镜（deleted_at 非空）保持不动
            await conn.execute(
                "DELETE FROM content_nodes WHERE parent_id=$1 AND kind='shot' AND deleted_at IS NULL",
                node_id
            )
            out = []
            for s in shots:
                # 分镜级要素关联：出场角色 + 场景要素 → element_ids（粗拆即建，详细阶段沿用）
                linked_names = list(s.get("characters") or [])
                if s.get("scene_element") and s["scene_element"] != "无":
                    linked_names.append(s["scene_element"])
                element_ids = [elem_map[n] for n in dict.fromkeys(linked_names) if n in elem_map]
                # 粗拆 meta：只落骨架字段 + detail_pending 标志；镜头语言细节留详细展开阶段补
                meta = {
                    "shot_no": s.get("shot_no"), "scene": s.get("scene", ""),
                    "scene_element": s.get("scene_element", ""),
                    "scale": s.get("scale", "中景"),
                    "duration_s": clamp_shot_seconds(s.get("duration_s")),
                    "action": s.get("action", ""),
                    "dialogue": s.get("dialogue", "无"),
                    "characters": s.get("characters", []),
                    "link_prev": bool(s.get("link_prev")),  # 已经 validate_shot_links 复核
                    "scene_seg": s.get("scene_seg"),  # 场景组号（空间锚定的归组键）
                    "cuts": s.get("cuts") or [],   # merge 产生的临时切（详细阶段精修/补切）
                    "mood": s.get("mood", ""),      # merge 可能已填"对话交锋"
                    "element_ids": element_ids,
                    "detail_pending": True,         # 详细分镜未补——故事板 step 前置按板展开
                }
                r = await conn.fetchrow(
                    "INSERT INTO content_nodes (project_id, parent_id, kind, seq, title, summary, meta) "
                    "VALUES ($1,$2,'shot',$3,$4,$5,$6::jsonb) RETURNING id",
                    project_id, node_id, int(s.get("shot_no", 0)),
                    f"镜头{s.get('shot_no')}", s.get("description", ""),
                    json.dumps(meta, ensure_ascii=False),
                )
                # 要素×分镜出现索引（shot 也是 content_nodes——检索路④天然支持镜级）
                for eid in element_ids:
                    await conn.execute(
                        "INSERT INTO element_appearances (project_id, element_id, node_id, snapshot) "
                        "VALUES ($1,$2,$3,$4) ON CONFLICT (element_id, node_id) DO UPDATE SET snapshot=EXCLUDED.snapshot",
                        project_id, eid, r["id"], s.get("action") or s.get("description", ""),
                    )
                out.append({"id": r["id"], **meta, "description": s.get("description", "")})
            # 章级粗审报告落盘（前端可展示，不静默吞掉）；旧总览草图随重拆作废（镜序已变），
            # 拆后自动串出详细分镜展开任务（宫格图不再自动出，需手动触发）
            await conn.execute(
                "UPDATE content_nodes SET status='storyboarded', "
                "meta = (meta - 'storyboard_overview') || $2::jsonb, updated_at=now() WHERE id=$1",
                node_id, json.dumps({"storyboard_validation": report["errors"],
                                     "storyboard_qc": qc}, ensure_ascii=False),
            )
    # 终局广播：合并/重编号后的权威列表已替换流式临时镜，前端立即重载
    events.publish(project_id, {"type": "shots_reset", "chapter_id": node_id, "final": True})
    return out


def _apply_deterministic(shots: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    """确定性三连（零 token）：时长按对白字数校准+长台词正反打
    → 对白顺序按原文重排（模型顽固幻觉，重拆治不了）→ 环境镜碎切收敛。
    首切避特写（safe_first_cut）已停用（用户 2026-07-14 放开照片级角色，特写首切是
    正常电影语言——项目10 第1章镜4 的好例子即特写切入；真人审核风险走火山角色备案）。"""
    return professionalize_cut_coverage(
        calm_env_cuts(reorder_dialogue_cuts(retime_dialogue(shots), source)))


_DETAIL_KEYS = ("angle", "camera_move", "camera_path", "lens_feel",
                "lighting", "palette", "mood", "motion_hint")


def _merge_details(
    todo: list[Any], detail_by_no: dict[int, dict[str, Any]], source: str
) -> list[dict[str, Any]]:
    """把 LLM 详细字段合并进粗镜 + 跑确定性链。返回按 todo 顺序的 shot 字典（含临时 description 键）。
    模型漏某镜 → 该镜保留粗值 + 走默认镜头语言，不报错（shot_no 稳定不增删）。"""
    shots: list[dict[str, Any]] = []
    for r in todo:
        m = dict(_node_meta(r))
        d = detail_by_no.get(int(m.get("shot_no") or 0)) or {}
        for k in _DETAIL_KEYS:
            if d.get(k):
                m[k] = d[k]
        if d.get("cuts"):
            m["cuts"] = d["cuts"]  # 详细阶段精修/重给的组内切，覆盖粗拆临时切
        m["description"] = d.get("description") or (r["summary"] or "")
        shots.append(m)
    return _apply_deterministic(shots, source)


async def expand_board_details(
    pool: asyncpg.Pool, project_id: int, node_id: int, system: str,
    user_prefix: str, source: str, known_chars: set[str], shot_rows: list[Any],
) -> int:
    """把一板粗镜（≤16）LLM 展开为详细分镜并落库（两阶段拆镜第二阶段，用户 2026-07-12 定稿）。
    幂等：已展开(detail_pending 非真)的镜跳过；每板一次 LLM 输出仅 ≤16 镜，天然不截断。
    返回本次展开的镜数。"""
    todo = [r for r in shot_rows if _node_meta(r).get("detail_pending")]
    if not todo:
        return 0
    coarse_lines = []
    for r in todo:
        m = _node_meta(r)
        coarse_lines.append(
            f"镜{m.get('shot_no')}｜场景:{m.get('scene', '')}｜景别:{m.get('scale', '')}"
            f"｜时长:{m.get('duration_s')}s｜出场:{'、'.join(m.get('characters') or []) or '无'}"
            f"｜对白:{m.get('dialogue', '无')}｜动作:{m.get('action', '')}"
            f"｜画面梗概:{r['summary'] or ''}"
        )
    user = (
        user_prefix
        + "\n\n以下是已定的分镜脚本骨架，请逐镜补齐镜头语言细节"
        "（**严格保持 shot_no 不变、不增删镜、不合并**）。"
        "画面描述必须忠实上文章节原文的具体细节（动作/体位/神态/环境/道具/光线），"
        "可细化润色使之首帧可独立绘制，但不得臆造原文没有的情节，也不得把骨架梗概里的具体细节概括掉：\n"
        + "\n".join(coarse_lines)
    )
    # 每板只 ≤16 镜，8000 token 绰绰有余
    data = await llm.chat_json(system, user, max_tokens=8000)
    detail_by_no = {int(x.get("shot_no", 0)): x for x in (data.get("shots") or [])}
    # 确定性补切（≥4s 无切镜）→ 确定性四连
    shots = _merge_details(todo, detail_by_no, source)
    shots = _apply_deterministic(await enrich_cuts(shots), source)
    # 零 token Gate（此刻字段已全）：有 error → 带明细重展一次
    report = validate_shot_list(shots, known_chars)
    if report["errors"]:
        fb = "\n".join(report["errors"][:16])
        data = await llm.chat_json(
            system, user + f"\n\n【上一版详细分镜违反以下铁律，请修正后重新输出全部镜头】\n{fb}",
            max_tokens=8000,
        )
        detail_by_no = {int(x.get("shot_no", 0)): x for x in (data.get("shots") or [])}
        reshot = _merge_details(todo, detail_by_no, source)
        if reshot:
            shots = _apply_deterministic(await enrich_cuts(reshot), source)
            report = validate_shot_list(shots, known_chars)

    async with pool.acquire() as conn:
        async with conn.transaction():
            for i, (r, s) in enumerate(zip(todo, shots)):
                cuts = s.get("cuts") or []
                camera_path = s.get("camera_path", "")
                if s.get("camera_move") == "固定":  # 固定镜强制清运动线（防模型自发滑镜，铁律13）
                    camera_path = "无"
                detail_meta = {
                    "cuts": cuts,
                    "scale": s.get("scale", "中景"), "angle": s.get("angle", "平视"),
                    "camera_move": s.get("camera_move", "固定"), "camera_path": camera_path,
                    "lens_feel": s.get("lens_feel", "35mm标准"),
                    "lighting": s.get("lighting", ""), "palette": s.get("palette", ""),
                    "mood": s.get("mood", ""), "action": s.get("action", ""),
                    "duration_s": clamp_shot_seconds(
                        s.get("duration_s"),
                        cap=SHOT_DECLARED_MAX_S if cuts else SHOT_NO_CUTS_MAX_S),
                    "dialogue": s.get("dialogue", "无"), "sfx": s.get("sfx", "无"),
                    "motion_hint": s.get("motion_hint", "无"),
                    "validation": report["per_shot"].get(i) or [],
                    "detail_pending": False,  # 详细分镜已补——解除标志
                }
                # meta || detail_meta：合并保留粗拆的 shot_no/scene/scene_element/characters/element_ids
                await conn.execute(
                    "UPDATE content_nodes SET meta = meta || $2::jsonb, summary=$3, updated_at=now() "
                    "WHERE id=$1",
                    r["id"], json.dumps(detail_meta, ensure_ascii=False),
                    s.get("description") or (r["summary"] or ""),
                )
    return len(todo)


# 质检规则正文（kind=skill/agent_code=reviewer 库化：管理页可编辑、项目级可覆盖；
# 此常量只作首次 seed 与装配兜底）；输出 JSON 契约由 _REVIEW_JSON_TAIL 代码强制，不随库内容变
VIDEO_REVIEW_RULES = """你是视频提示词质检员。合格的视频提示词 = **时间轴镜头脚本**：主体是带秒区间的中文叙事段，镜头语言内嵌于段首标注，随后依次为 运动约束句/角色设定/场景光色/画风锚词(至多一句英文)/一致性约束/时长画质。
十三个判定维度：
1 时间轴叙事：带秒区间的多段事件（≥6s 至少3段，4-5s 至少2段；禁止整镜一段拍到底），秒区间连续且总和=时长，每段推进新信息
2 镜头语言内嵌：景别/切换/运镜在段首标注内（如"（0-2秒·中景）""（2-4秒·切特写）""（0-4秒·远景·慢推）"）；**不得出现孤立参数行**（"镜头：中景，平视，35mm标准"式）；"镜头运动线：…"句（无切/单切镜）合法
3 运动约束在场："禁止慢动作、禁止缓慢漂移"类真实速度约束或"机位完全锁定"任一在场即可；镜头运动作为叙事内容出现在时间轴段内或段首标注里均合法
4 身份一致与必要性：有设定图的角色用"造型与外貌以 @设定图[角色名] 为准"短引用——**@设定图[…] 与 @图片N 是参考图引用占位符，重构时必须原样保留，不得改写、翻译或删除**；无图角色必须有外貌全文；不得引用不存在的图。**必要性双向判定（以【要素清单】为准绳）**：清单列出的"本镜应含角色"必须逐个在身份层在场；清单外或明确标注"不需要"的角色出现外貌/引用即判不合格——重构时删除多余角色、补齐缺失角色
5 一致性约束句在场（"同一角色，面部稳定不变形，服装不变"）
6 内容发展：叙事有增量（光影/距离/情绪的变化弧），不是同一画面复读
7 审核安全：无"未成年+贴身/半透明衣物"等敏感语义组合，无诱发真人隐私判定的表述
8 无冗余矛盾：无重复句段；无与叙事冲突的英文构图块（动作镜出现 conversational distance/steady framing 即违规）
9 收尾规范：画风锚词至多一句英文 + 时长与画质句
10 时长充裕与节奏匹配：**逐段核算**每个秒区间是否足以演完该段的对白与动作——对白按 4字/秒（8字台词至少2秒，长台词3-4秒），带位移/交锋/情绪转变的动作段至少2秒；总时长必须足够演完全部叙事（模型严格按总秒数出片，时长不够=剧情只演一半）。时长不足时解法是**加长秒区间**（单镜上限15秒），绝不允许靠删减剧情凑时长。切换节奏须与内容匹配：打斗/追逐等动作场面才用1-3秒快切，常规叙事与对话每段2-4秒，情绪铺垫/释放每段3-5秒——非动作内容出现连续1-2秒碎切判不合格
11 脚本完整：对照【镜头脚本】逐条核对——脚本中的每条对白、每个动作/切换都必须出现在提示词时间轴中且顺序一致，任何对白遗漏、动作缺失、切换被合并吞掉都判不合格（这是成片只演一半剧情的头号原因）
12 具象化与动作时序（Seedance 官方写法纪律）：叙事段禁止"氛围感拉满/好看/高级/唯美/有感觉"类抽象修饰词——必须替换为具体的光线/色彩/动作描述；动作应写出时序与力度（先后顺序、速度、幅度，如"猛地/缓缓/大步"），孤立的单点动作词（"转身""看"无修饰堆在段里）提示改进但单独不扣合格；同一秒区间段内堆砌两种以上镜头运动指令判不合格（单段最多一种镜头运动）
13 空间与站位连贯：上下文提供【本镜站位锚】时，提示词中各角色的空间位置（谁在哪、相对关系）必须与站位锚一致，且不与【上一镜站位】冲突——角色凭空换位置（上一镜在车外、本镜无移动却在车上）判不合格；提示词的"空间锚定/开场站位"句与时间轴叙事里的位置描述互相矛盾也判不合格。重构时以站位锚为准修正位置描述；无站位锚时本维度跳过

【合格示例】
（0-1秒·特写）阿澈的手：猛地抓向翼缘，指节发白 → （1-2秒·切中景）被涡流抛进乱流，发丝与藤须狂舞 → （2-3秒·切特写）涡流翻滚，气泡炸开 → （3-4秒·切中景）抓住翼缘又被震开。所有切换共享同一空间，角色站位/服装/光线在切换间保持完全一致。动作与运镜为真实速度，干脆利落，禁止慢动作，禁止缓慢漂移。角色设定：「阿澈」造型与外貌以 @设定图[阿澈] 为准。场景：辉渊，深海发光深渊，生物荧光为唯一光源。cinematic realism, film grain, dramatic lighting。同一角色，面部稳定不变形，服装不变。4秒，4K高清

【不合格示例】（违反维度1/2/8）
巡夜驮着阿澈向上。角色设定：…。镜头：中景，平视，跟拍，35mm标准。medium shot, waist-up framing, conversational distance。steady framing with moving background。8秒
→ 问题：无时间轴分段（8秒一句话拍到底）；孤立参数行；动作镜含 conversational distance/steady framing 冲突块

评分刻度：0-100 整数，≥80 才可判合格。
每条问题必须配一条**可执行的修改建议**（具体到改哪句、怎么改）；不合格时必须给出完整重写的"重构提示词"——重构必须逐条落实修改建议（按合格示例的形态重写，保留正确的身份层/场景/画风锚词）。因维度10/11（时长不足/脚本遗漏）重构时：加长秒区间、补齐遗漏的对白与动作，**禁止删减剧情**；重构后须重排秒区间使其连续且总和=新总时长，收尾的"N秒"随之更新。**总时长硬上限15秒**（模型单次上限，超了提交必失败）——若15秒装不下全部内容，先压缩听者反应与环境空镜段保对白完整；仍装不下则在问题里注明"内容超载建议拆镜"。"""


IMAGE_REVIEW_RULES = """你是首帧图提示词质检员。首帧=视频第一帧的静态定格。按十个维度评审，输出 JSON。
维度：
1 画面完整与具象：主体/动作瞬间/环境/光效/色调齐全；主体须精准定义（核心属性+外观特征+状态，如"20岁少女，湿黑短发，深蓝潜行服，紧贴岩壁"，禁止模糊表述）；**出场角色必须处于画面叙事中的动作/姿态（谁在做什么）**，不得是无动作的立绘式/证件照式呈现；光效须具象（光线类型+明暗效果，如"暖黄路灯，地面湿润反光"）；禁止"氛围感拉满/好看/高级/唯美"类抽象词——出现即要求替换为具体描述
2 构图指令：景别/角度/焦段感在场且互不矛盾；**远景/全景/群像镜不得含面部级细节描写**（瞳色/疤痕/睫毛等近景特征）——人物应为小比例身影；群像镜的画面主体必须是人群整体，具名角色不得抢占主体
3 身份完整与必要性：出场角色必须有**外貌描述**——中近景用外貌全文；远景/全景只需远距识别特征（服色/体型/轮廓），此时外貌全文反而违反维度2。有设定图的角色会附带"（面部与服饰造型以 @设定图[角色名] 为准）"——**@设定图[…] 与 @图片N 是参考图引用占位符，重构时必须原样保留，不得改写、翻译或删除**；引用只锚定长相与服饰，不能替代外貌全文与动作描述。**必要性双向判定（以【要素清单】为准绳）**：清单列出的"首帧应含角色"必须逐个在场；清单外或明确标注"不需要"的角色出现外貌描述/@设定图引用即判不合格（首帧是空景/纯环境镜时不得织入任何角色）——重构时删除多余角色、补齐缺失角色
4 画风锚词在场（如 cinematic realism 类风格词）
5 静态定格：不得含运镜/镜头运动指令（推镜/横移属于视频，首帧是动作瞬间的定格）
6 审核安全：无"未成年+贴身/半透明衣物"敏感组合
7 质量词兜底在场；排除类约束以正向表述（生图接口不支持负面词）
8 无冗余重复、无矛盾
9 与镜头叙事一致：定格内容应是该镜第一切/首个动作瞬间
10 站位一致：上下文提供【本镜站位锚】时，画面中各角色所处位置必须与站位锚一致（在马车外的不得画到马车上）；无站位锚时本维度跳过

【合格示例】
阿澈的手猛地抓向巡夜的翼缘的瞬间定格，水中涡流环绕，气泡炸开。动作瞬间: 猛地抓向翼缘。角色外貌: 「阿澈」：17岁少女…（湿黑短发贴颊，右眉骨旧疤，琥珀色眼睛，深蓝潜行服，腕缠银蓝声弦藤须）（面部与服饰造型以 @设定图[阿澈] 为准）。场景: 辉渊，深海发光深渊，生物荧光为唯一光源，悬浮微粒。光效: 生物荧光为唯一光源。色调: 深蓝主调,一点荧光, close-up, extreme detail, 85mm telephoto lens, bioluminescent glow as key light, masterpiece, best quality
【不合格示例】（违反维度1/5）
镜头缓缓推向阿澈，「阿澈」半身特写立于画面中央直视镜头…
→ 问题：维度5 首帧含运镜指令"缓缓推向"；维度1 角色无叙事动作，立绘式特写与镜头内容脱节

评分刻度：0-100 整数，≥80 才可判合格。
每条问题必须配一条**可执行的修改建议**（具体到改哪句、怎么改）；不合格时必须给出完整重写的"重构提示词"——重构必须逐条落实修改建议，且**不得删除角色的外貌描述、@设定图 引用与画风锚词**（远景/全景镜可把外貌全文降级为远距识别特征，不算删除）。"""

def _shot_skeleton(summary: str | None, meta: Any) -> str:
    """单镜脚本骨架（供跨镜衔接参考）：画面 + 动作 + 对白，压成一行短文。"""
    m = meta if isinstance(meta, dict) else json.loads(meta or "{}")
    bits: list[str] = []
    if (summary or "").strip():
        bits.append(summary.strip())
    if m.get("action"):
        bits.append(f"动作：{m['action']}")
    dlg = (m.get("dialogue") or "").strip()
    if dlg and dlg != "无":
        bits.append(f"对白：{dlg}")
    return "；".join(bits)[:200]


async def _continuity_context(conn: asyncpg.Connection, shot: Any) -> str:
    """跨镜衔接参考（重生成本镜提示词时的连贯性锚点）：本章故事线 + 上一镜/下一镜脚本骨架。
    仅供质检/重构时保证**风格统一、故事连贯、镜头衔接**——**本镜提示词不得纳入相邻镜或故事线的内容**，
    评审不得据此把本镜判成"遗漏"或"冗余"。相邻镜缺失（首/末镜）则该行留空。"""
    parent_id, seq = shot["parent_id"], shot["seq"]
    chapter = await conn.fetchrow("SELECT summary FROM content_nodes WHERE id=$1", parent_id)
    prev = await conn.fetchrow(
        "SELECT summary, meta FROM content_nodes WHERE parent_id=$1 AND kind='shot' "
        "AND deleted_at IS NULL AND seq<$2 ORDER BY seq DESC LIMIT 1", parent_id, seq)
    nxt = await conn.fetchrow(
        "SELECT summary, meta FROM content_nodes WHERE parent_id=$1 AND kind='shot' "
        "AND deleted_at IS NULL AND seq>$2 ORDER BY seq ASC LIMIT 1", parent_id, seq)
    storyline = ((chapter["summary"] if chapter else "") or "").strip()

    def _blocking_line(meta: Any) -> str:
        """站位锚一行（场景空间规划产物）：谁在哪+镜内移动——供评审比对空间连贯。"""
        m = meta if isinstance(meta, dict) else json.loads(meta or "{}")
        blk = m.get("blocking") or {}
        pos = "；".join(f"「{k}」{_at(v)}" for k, v in (blk.get("chars") or {}).items())
        return "，".join(x for x in (pos, f"镜内移动：{blk['moves']}" if blk.get("moves") else "") if x)

    lines: list[str] = []
    if storyline:
        lines.append(f"本章故事线：{storyline[:300]}")
    if prev:
        _p = _shot_skeleton(prev["summary"], prev["meta"])
        if _p:
            lines.append(f"上一镜脚本：{_p}")
        _pb = _blocking_line(prev["meta"])
        if _pb:
            lines.append(f"上一镜站位：{_pb}")
    _sb = _blocking_line(shot["meta"])
    if _sb:
        lines.append(f"本镜站位锚（本镜提示词的角色位置必须与此一致）：{_sb}")
    if nxt:
        _n = _shot_skeleton(nxt["summary"], nxt["meta"])
        if _n:
            lines.append(f"下一镜脚本：{_n}")
    if not lines:
        return ""
    return (
        "【跨镜衔接参考——仅用于判定本镜与前后镜的风格统一/故事连贯/镜头衔接；"
        "本镜提示词不得纳入以下相邻镜与故事线的内容，评审不得据此报'遗漏'或'冗余'】\n"
        + "\n".join(lines) + "\n"
    )


def _refs_roster(meta: dict[str, Any], target: str) -> str:
    """要素清单文本（质检"角色必要性"维度的准绳）：本镜该目标（image/video）下
    需要的角色/场景/道具 + 明确不需要的角色。旧数据无 required_refs 时返回空串
    （不给准绳就不判必要性——否则会把合法角色误判成多余）。"""
    if "required_refs" not in meta:
        return ""
    req = meta.get("required_refs") or []
    exc = meta.get("excluded_refs") or []
    chars = [r["name"] for r in req if r.get("kind") == "character" and target in (r.get("targets") or [])]
    scenes = [r["name"] for r in req if r.get("kind") == "scene"]
    props = [r["name"] for r in req if r.get("kind") == "prop"]
    drops = [r["name"] for r in exc if r.get("kind") == "character"]
    bits = [("应含角色：" + "、".join(chars)) if chars
            else "应含角色：无（空景/纯环境画面，不得织入任何角色外貌与 @设定图 引用）"]
    if scenes:
        bits.append(f"场景要素：{'、'.join(scenes)}")
    if props:
        bits.append(f"关键道具：{'、'.join(props)}")
    if drops:
        bits.append(f"明确不需要的角色（其外貌或引用出现即违规）：{'、'.join(drops)}")
    return "；".join(bits)


# 输出 JSON 契约（代码强制，永远追加在质检规则正文之后——库内容改坏也不破解析链路）
_REVIEW_JSON_TAIL = """严格输出 JSON：
{"合格": true, "得分": 0, "问题": ["维度N: 具体问题"], "修改建议": ["针对问题1：具体改法"], "重构提示词": ""}"""


async def _reviewer_system(conn: asyncpg.Connection, project_id: int,
                           name: str, fallback_body: str) -> str:
    """装配质检系统提示词（与 _director_system 同模式）：规则正文从 kb 取
    （kind=skill/agent_code=reviewer，项目覆盖全局，缺失回退代码常量）+ 输出契约代码强制。"""
    row = await conn.fetchrow(
        "SELECT content FROM kb_entries WHERE kind='skill' AND agent_code='reviewer' AND name=$2 "
        "AND enabled AND (scope='global' OR (scope='project' AND project_id=$1)) "
        "AND ((SELECT project_type FROM content_projects WHERE id=$1)='novel_comic' "
        "     OR cardinality(tags)=0 OR (SELECT project_type FROM content_projects WHERE id=$1)=ANY(tags)) "
        "ORDER BY scope DESC LIMIT 1", project_id, name,
    )
    body = row["content"] if row and (row["content"] or "").strip() else fallback_body
    return body + "\n" + _REVIEW_JSON_TAIL


async def review_by_skill(pool: asyncpg.Pool, project_id: int | None, *, skill: str,
                          text: str = "", image_url: str | None = None,
                          prev_feedback: str = "", locked: str = "") -> dict[str, Any]:
    """**通用质检**（画布质检段用）：判法来自技能，输出结构由代码强制。

    与 review_image_prompt 的关系：那个是镜级首帧提示词的专用质检（自带十维规则、
    重构复审、指纹缓存）；这个是画布上「随便哪个节点绑一个质检技能」的通用版——
    共用同一套装配（_reviewer_system 从 kb 取规则 + _REVIEW_JSON_TAIL 强制契约），
    不另写第二份。

    - skill：kb 里 kind='skill' / agent_code='reviewer' 的条目名（项目级覆盖全局）；
    - image_url 给了就走视觉模型判画面，否则判文本；
    - locked：**已由系统锁死、必然随提示词一起下发的硬约束段**（画布 anchor：版式/
      画风/禁令）。判据只判可改的 text 段，但必须知道这些已经生效——否则会出现
      「charter 里明写了『画面无活物』，质检却判『未体现无活物要求』」这种死结：
      要求写进了 anchor、判据看的是 user，越认真写越判不过（实测 run 71）。
      它只作事实告知，**不参与打分**，也不该被要求在 text 里重复一遍。
    - 返回 {合格, 得分, 问题[], 修改建议[]}——**结构固定**，回退逻辑才读得到结论。
    """
    async with pool.acquire() as conn:
        system = await _reviewer_system(conn, project_id or 0, skill, IMAGE_REVIEW_RULES)
    user = (f"【上一轮质检问题（必须针对性解决）】\n{prev_feedback}\n\n" if prev_feedback else "")
    if locked.strip():
        user += ("【已生效的系统硬约束——随提示词一起下发，无需在待检内容里重复；"
                 "凡本段已覆盖的要求，一律不得作为问题扣分】\n"
                 f"{locked.strip()}\n\n")
    user += f"【待检内容】\n{text}" if text else "【待检内容】见图"
    try:
        # 首帧十维规则会同时返回问题、修改建议和完整重构提示词；1200 token 会在
        # JSON 中途截断，表现成“质检不可用且没有重构版”。与专用首帧质检统一 4000。
        out = (await llm.chat_vision_json(system, user, image_url) if image_url
               else await llm.chat_json(system, user, temperature=0.1, max_tokens=4000))
    except Exception as e:  # noqa: BLE001 — 质检失败不该把产物判死，交调用方决定
        log.warning("通用质检调用失败（skill=%s）：%s", skill, e)
        return {"合格": True, "得分": 0, "问题": [], "降级": f"质检不可用：{e}"}
    if not isinstance(out, dict):
        return {"合格": True, "得分": 0, "问题": [], "降级": "质检返回非 JSON"}
    return {
        "合格": bool(out.get("合格")), "得分": out.get("得分") or 0,
        "问题": out.get("问题") or [], "修改建议": out.get("修改建议") or [],
        # 重构提示词是**重跑的唯一正确素材**：把问题清单原样拼回提示词等于对着出图模型
        # 念质检意见（"去掉龙族遗骸描述" 会被当成画面内容画进去），必须用重写后的全文
        "重构提示词": str(out.get("重构提示词") or "").strip(),
    }


async def review_image_prompt(pool: asyncpg.Pool, project_id: int, shot_id: int,
                              prev_feedback: str = "") -> dict[str, Any]:
    """首帧提示词质检：十维评审（含站位一致）→ 不合格自动重构 → 复审；结果落 meta.prompt_review_image。
    prev_feedback：质检回退重试时带入的上一轮问题清单——重构提示词必须针对性解决，
    避免两轮各修各的来回震荡（提示词重生成的唯一实现就在这条重构链上，别处不再写第二份）。"""
    async with pool.acquire() as conn:
        shot = await conn.fetchrow("SELECT * FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id)
        if not shot:
            raise ValueError("分镜不存在")
        meta = shot["meta"] if isinstance(shot["meta"], dict) else json.loads(shot["meta"])
        review_sys = await _reviewer_system(conn, project_id, "首帧提示词质检", IMAGE_REVIEW_RULES)
        cont = await _continuity_context(conn, shot)
    ip = meta.get("image_prompt")
    if not ip:
        raise ValueError("请先装配提示词")

    def _ctx(prompt_text: str) -> str:
        cuts = meta.get("cuts") or []
        # 首帧=首切定格：有 cuts 时"应有构图"以首切为准（拿镜级参数比对首切构图会误报矛盾）
        if cuts and cuts[0].get("scale"):
            expect = f"本首帧的应有构图=首切：({cuts[0].get('scale')}){cuts[0].get('subject')}:{cuts[0].get('action')}"
        else:
            expect = f"本首帧的应有构图={meta.get('scale')}/{meta.get('angle')}/{meta.get('lens_feel')}"
        roster = _refs_roster(meta, "image")
        prev = (f"【上一轮质检未通过的问题——重构提示词必须针对性解决，不要引入新问题】\n"
                f"{prev_feedback.strip()}\n" if (prev_feedback or "").strip() else "")
        return (
            f"【镜头信息——仅供校对，不属于待评审文本，勿对其报问题】{expect}，时长{meta.get('duration_s')}s\n"
            + (f"【要素清单——维度3必要性判定的准绳】{roster}\n" if roster else "")
            + cont + prev
            + f"【待评审首帧提示词开始】\n{prompt_text}\n【待评审首帧提示词结束】\n"
            f"只依据开始/结束标记之间的文本判定；已在场的约束与外貌描述不得误报缺失。"
        )

    review = await llm.chat_json(review_sys, _ctx(ip), max_tokens=4000, purpose="review")
    result: dict[str, Any] = {
        "合格": bool(review.get("合格")), "得分": review.get("得分"),
        "问题": review.get("问题") or [], "修改建议": review.get("修改建议") or [], "重构": False,
    }
    if not result["合格"] and (review.get("重构提示词") or "").strip():
        new_ip = review["重构提示词"].strip()
        second = await llm.chat_json(review_sys, _ctx(new_ip), max_tokens=4000, purpose="review")
        result.update({
            "重构": True, "合格": bool(second.get("合格")), "得分": second.get("得分"),
            "复审问题": second.get("问题") or [], "复审建议": second.get("修改建议") or [],
        })
        # 有保留放行：重构版=评审自己的药方，已采纳后复审仍不合格且无安全问题（维度6）
        # → 判为评审噪声，带保留放行（分数留档）；安全问题永远硬阻断
        if not result["合格"]:
            safety = any(("维度6" in q or "审核" in q or "敏感" in q or "隐私" in q) for q in result["复审问题"])
            if not safety:
                result["合格"] = True
                result["有保留"] = True
        patch = {"image_prompt": new_ip, "image_prompt_raw": ip, "prompt_review_image": result}
    else:
        patch = {"prompt_review_image": result}
    # 缓存有效性戳：指纹=最终提示词（重构后以重构版为准）+ TTL——生成前置命中即免重跑质检
    stamp_validity(result, patch.get("image_prompt", ip), PROMPT_REVIEW_TTL_H)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
            shot_id, json.dumps(patch, ensure_ascii=False),
        )
    result["image_prompt"] = patch.get("image_prompt", ip)
    return result


async def review_video_prompt(pool: asyncpg.Pool, project_id: int, shot_id: int) -> dict[str, Any]:
    """提示词质检环节（用户 2026-07-09 定稿）：LLM 按十三维评审（含站位连贯）→ 不合格自动重构 → 复审。
    结果落 meta.prompt_review；重构后覆盖 video_prompt（原文留 video_prompt_raw）。"""
    async with pool.acquire() as conn:
        shot = await conn.fetchrow("SELECT * FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id)
        if not shot:
            raise ValueError("分镜不存在")
        meta = shot["meta"] if isinstance(shot["meta"], dict) else json.loads(shot["meta"])
        review_sys = await _reviewer_system(conn, project_id, "视频提示词质检", VIDEO_REVIEW_RULES)
        cont = await _continuity_context(conn, shot)
    vp = meta.get("video_prompt")
    if not vp:
        raise ValueError("请先装配提示词")

    def _script_baseline() -> str:
        """本镜脚本事实（维度10/11 的比对基准）：对白/动作/组内切/画面——
        质检员据此核对提示词有没有把脚本内容丢掉、每段时长够不够演。"""
        lines: list[str] = []
        if meta.get("action"):
            lines.append(f"动作：{meta['action']}")
        dlg = (meta.get("dialogue") or "").strip()
        if dlg and dlg != "无":
            lines.append(f"对白（每条都必须在时间轴中在场）：{dlg}")
        for i, c in enumerate(meta.get("cuts") or [], 1):
            lines.append(f"切{i}（{c.get('seconds')}s·{c.get('scale', '')}）"
                         f"{c.get('subject', '')}：{c.get('action', '')}")
        if shot["summary"]:
            lines.append(f"画面：{shot['summary']}")
        return "\n".join(lines) or "（无）"

    def _ctx(prompt_text: str) -> str:
        roster = _refs_roster(meta, "video")
        return (
            f"【镜头参数——仅供校对，不属于待评审文本，勿对其报问题】"
            f"时长{meta.get('duration_s')}s，组内切数={len(meta.get('cuts') or [])}\n"
            + (f"【要素清单——维度4必要性判定的准绳】{roster}\n" if roster else "")
            + cont
            + f"【镜头脚本——维度10/11 的比对基准：核对提示词内容完整性与每段时长充裕度】\n"
            f"{_script_baseline()}\n"
            f"【待评审提示词开始】\n{prompt_text}\n【待评审提示词结束】\n"
            f"只依据开始/结束标记之间的文本判定提示词形态问题；已在场的约束（如'机位完全锁定'）不得误报缺失；"
            f"画风锚词中的摄影质感词（film grain/shallow depth of field）不视为矛盾。"
        )

    review = await llm.chat_json(review_sys, _ctx(vp), max_tokens=4000, purpose="review")
    result: dict[str, Any] = {
        "合格": bool(review.get("合格")), "得分": review.get("得分"),
        "问题": review.get("问题") or [], "修改建议": review.get("修改建议") or [], "重构": False,
    }
    if not result["合格"] and (review.get("重构提示词") or "").strip():
        new_vp = review["重构提示词"].strip()
        second = await llm.chat_json(review_sys, _ctx(new_vp), max_tokens=4000, purpose="review")
        result.update({
            "重构": True, "合格": bool(second.get("合格")), "得分": second.get("得分"),
            "复审问题": second.get("问题") or [], "复审建议": second.get("修改建议") or [],
        })
        # 有保留放行：重构版=评审自己的药方，已采纳后复审仍不合格且无安全问题（维度7）
        # → 判为评审噪声，带保留放行（分数留档）；安全问题永远硬阻断
        if not result["合格"]:
            safety = any(("维度7" in q or "审核" in q or "敏感" in q or "隐私" in q) for q in result["复审问题"])
            if not safety:
                result["合格"] = True
                result["有保留"] = True
        patch = {"video_prompt": new_vp, "video_prompt_raw": vp, "prompt_review": result}
        # 重构可能加长了时间轴（维度10/11：时长不足/补齐遗漏内容）——总时长跟随重构版
        # 回写 duration_s，否则提交给模型的时长仍是旧值，视频照样被掐一半
        new_d = timeline_end_seconds(new_vp)
        if new_d and new_d != int(meta.get("duration_s") or 0):
            patch["duration_s"] = clamp_shot_seconds(new_d, cap=_PROVIDER_MAX_S)
            result["duration_s"] = patch["duration_s"]
    else:
        patch = {"prompt_review": result}
    # 缓存有效性戳（同首帧质检）：指纹=最终提示词 + TTL
    stamp_validity(result, patch.get("video_prompt", vp), PROMPT_REVIEW_TTL_H)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
            shot_id, json.dumps(patch, ensure_ascii=False),
        )
    result["video_prompt"] = patch.get("video_prompt", vp)
    return result


async def assemble_shot_prompts(pool: asyncpg.Pool, project_id: int, shot_id: int) -> dict[str, str]:
    """为单镜装配专业提示词（核心原则2）：
    - image_prompt：彩色关键帧（项目画风块 + 景别块 + 动作块 + 角色外貌）
    - video_prompt：视频（时间轴叙事 + 动作 + 时长节奏；镜级 scale/angle/camera_move 已废弃不进提示词，镜头语言只到切级）
    装配结果写回 shot.meta，前端可见可编辑（点击提示词生成视频）。
    """
    async with pool.acquire() as conn:
        shot = await conn.fetchrow("SELECT * FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id)
        if not shot:
            raise ValueError("分镜不存在")
        project = await conn.fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
        project = await volumes.effective_for_chapter(conn, project, shot["parent_id"])  # 画风跟随本镜所属卷
        meta = shot["meta"] if isinstance(shot["meta"], dict) else json.loads(shot["meta"])
        desc = shot["summary"] or ""
        # 装配期确定性保真（2026-07-12 真实验证实锤）：对白注入 cuts + 时长精算 + 上下限整形。
        # 只改本次编译的内存副本，不落库（cuts 是脚本数据，提示词才是编译产物）
        meta = dict(meta)
        _fitted, _fit_notes = fit_cuts_for_prompt(meta)
        if _fitted:
            meta["cuts"] = _fitted
        for _n in _fit_notes:
            log.info("镜 %s 装配保真: %s", shot_id, _n)

        # ── 知识召回：精确取标注块（景别/角度/焦段/运镜），情境召回光效与动作块，画风按项目 art_style 召回 ──
        scale_block = await get_block(conn, "camera", meta.get("scale", "中景"))
        angle_block = await get_block(conn, "angle", meta.get("angle", "")) if meta.get("angle") else None
        lens_block = await get_block(conn, "lens", meta.get("lens_feel", "")) if meta.get("lens_feel") else None
        # 首帧=视频第一帧=首切的定格：有 cuts 且首切景别≠镜级景别时，
        # 首帧构图三件套（景别/角度/焦段）整体跟随首切——只换景别会残留"特写+鸟瞰+16mm"矛盾（镜22 质检两轮抓出）
        _first_cut = (meta.get("cuts") or [{}])[0]
        img_scale_block, img_angle_block, img_lens_block = scale_block, angle_block, lens_block
        if _first_cut.get("scale") and _first_cut["scale"] != meta.get("scale"):
            _fc_block = await get_block(conn, "camera", _first_cut["scale"])
            if _fc_block:
                _SCALE_LENS = {"大特写": "100mm微距", "特写": "85mm长焦", "近景": "50mm标准",
                               "中景": "35mm标准", "全景": "35mm标准", "远景": "24mm广角", "大远景": "16mm超广角"}
                img_scale_block = _fc_block
                img_angle_block = None  # 镜级角度（鸟瞰等）随镜不随切，弃用防矛盾
                _fc_lens = _SCALE_LENS.get(_first_cut["scale"])
                img_lens_block = await get_block(conn, "lens", _fc_lens) if _fc_lens else None
        lighting_blocks = []
        if meta.get("lighting"):
            lighting_blocks = await recall_blocks(conn, meta["lighting"], ["lighting"], project_id, top_k=1)
        quality = await get_block(conn, "quality", "通用质量词")
        negative = await get_block(conn, "quality", "通用负面词")
        motion_blocks = []
        if meta.get("motion_hint") and meta["motion_hint"] != "无":
            motion_blocks = await recall_blocks(conn, meta["motion_hint"], ["motion"], project_id, top_k=1)
        style_blocks = await recall_blocks(conn, project["art_style"] or "日漫", ["style"], project_id, top_k=1)
        # 本镜关联要素（优先 element_ids 关系链，兼容旧数据按名字兜底）：
        # 角色→身份层提示词，场景→场景描述；设定图→参考图（跨镜一致性锚点，带名字供"图片N"引用句）
        if meta.get("element_ids"):
            elem_rows = await conn.fetch(
                "SELECT id, kind, name, brief, meta FROM content_elements "
                "WHERE project_id=$1 AND id = ANY($2::bigint[])",
                project_id, meta["element_ids"],
            )
        else:
            names = list(meta.get("characters") or [])
            if meta.get("scene_element") and meta["scene_element"] != "无":
                names.append(meta["scene_element"])
            elem_rows = await conn.fetch(
                "SELECT id, kind, name, brief, meta FROM content_elements "
                "WHERE project_id=$1 AND kind IN ('character','scene') AND name = ANY($2::text[])",
                project_id, names,
            ) if names else []
        # 角色要素基名补捞（ch16 实锤：脚本 characters 用短名"老船长"，要素原名
        # "沉默老船长（黑衣人）"——精确匹配落空 → 本镜主体角色零外貌零设定图，跨镜必漂）：
        # 基名互相包含即认定同一角色，补入要素行
        _missing = [c for c in (meta.get("characters") or [])
                    if not any(e["kind"] == "character" and _names_match(c, e["name"]) for e in elem_rows)]
        if _missing:
            _all_chars = await conn.fetch(
                "SELECT id, kind, name, brief, meta FROM content_elements "
                "WHERE project_id=$1 AND kind='character'", project_id)
            _got = {e["name"] for e in elem_rows}
            elem_rows = list(elem_rows)
            for _c in _missing:
                _hit = next((r for r in _all_chars
                             if r["name"] not in _got and _names_match(_c, r["name"])), None)
                if _hit:
                    elem_rows.append(_hit)
                    _got.add(_hit["name"])
                    log.info("镜 %s 角色要素基名补捞: 「%s」→「%s」", shot_id, _c, _hit["name"])
        # ── 角色在场复核（2026-07-14 定稿）：剧本文字里没有的角色一律不关联——
        # 不织外貌、不加 @设定图 引用、不传设定图（纯空景镜被织入主角外貌+三视图实锤）。
        # 视频语料=全镜剧本（画面/动作/对白/各切）；首帧语料=首切定格（无切时=画面+动作）
        _cuts_all = meta.get("cuts") or []
        _video_corpus = " ".join([desc, meta.get("action") or "", meta.get("dialogue") or ""]
                                 + [f"{c.get('subject', '')} {c.get('action', '')}" for c in _cuts_all])
        _frame_corpus = (f"{_cuts_all[0].get('subject', '')} {_cuts_all[0].get('action', '')}"
                         if _cuts_all else f"{desc} {meta.get('action') or ''}")
        _cand_names = list(dict.fromkeys((meta.get("characters") or [])
                                         + [e["name"] for e in elem_rows if e["kind"] == "character"]))
        _video_chars = _chars_present(_cand_names, _video_corpus)
        _frame_chars = _chars_present(_cand_names, _frame_corpus)
        required_refs: list[dict[str, Any]] = []   # 本镜需要的要素清单（结构化，前端渲染+质检输入）
        excluded_refs: list[dict[str, Any]] = []   # 被剔除的要素及原因（明示"不需要的不关联"）
        char_parts: list[str] = []       # 视频用：有设定图→短引用，无→外貌全文
        char_full_parts: list[str] = []  # 视频纯文本兜底用（无参考图路径时）：外貌全文
        img_char_parts: list[str] = []   # 首帧生图用（中近景）：外貌全文 + @设定图 引用双锚定
        # （2026-07-14 回归修复：07-13 的"只留引用"版实测机械拼贴设定图特写，恢复全文织入）
        char_short_parts: list[str] = []  # 首帧生图用（远景/全景/群像）：剪影级识别特征——
        prop_parts: list[str] = []       # 关键实物（武器/法宝/器物等 kind=setting 且 needs_image）：
        # 有设定图→@设定图 引用 + 参考图，无图→外观文字（要素预检补建后自动升级为图引用）
        # 面部级全文在 wide 镜里是喧宾夺主的矛盾信息（第3章镜4实测：人群全景被画成主角特写）
        # 用户逐镜停用的视频参考图：该角色身份层回退外貌全文（引用与附件同生死，避免引用落空）
        video_off = set(((meta.get("ref_off") or {}).get("video")) or [])
        image_off = set(((meta.get("ref_off") or {}).get("image")) or [])
        reference_images: list[dict[str, str]] = []
        scene_text = ""
        # 多形态自动选图：本镜按剧情选定的形态（镜级预检 LLM 写入 meta.element_variants），
        # 缺则按 tag/触发剧情与全镜剧本关键词兜底匹配。统一入口 effective_meta 影子覆盖，
        # 下游 em.get("sheet_url")/em.get("外貌提示词") 无需分叉即取到对应形态。
        _chosen = {str(k): v for k, v in (meta.get("element_variants") or {}).items()}
        for e in elem_rows:
            em = e["meta"] if isinstance(e["meta"], dict) else json.loads(e["meta"])
            em = element_variants.effective_meta(em, _video_corpus, _chosen.get(str(e["id"])))
            if e["kind"] == "character":
                # 在场性 gate（逐目标独立）：pv=全镜剧本有此角色（视频/故事板），pi=首帧画面有（首帧生图）
                pv = any(_names_match(e["name"], c) for c in _video_chars)
                pi = any(_names_match(e["name"], c) for c in _frame_chars)
                if not (pv or pi):
                    excluded_refs.append({"name": e["name"], "kind": "character",
                                          "element_id": e["id"],
                                          "reason": "本镜剧本无此角色出场，不织外貌、不传设定图"})
                    log.info("镜 %s 角色「%s」剧本无出场，剔除关联", shot_id, e["name"])
                    continue
                required_refs.append({
                    "name": e["name"], "kind": "character", "element_id": e["id"],
                    "url": em.get("sheet_url") or None,
                    "targets": [t for t, on in (("image", pi), ("video", pv)) if on],
                })
                # 身份层描述单一来源（character_context）：档案的年龄性别/身份称谓 + 简介 + 外貌。
                # 此前只拼 brief+外貌，角色档案调好的身份要点进不了分镜——两链路"前置不一致"的病根
                desc_cn = identity_desc(e["name"], e["brief"] or "", em)
                if em.get("sheet_url"):
                    # element_id 作"来源字段"：提交时据此按项目精确解析该角色是否已火山备案→换 asset://
                    # （media 层做，且构建 API content 时会去掉该字段，不发给火山）。见 ark_assets.resolve_asset_refs
                    identity_id = em.get("identity_character_id")
                    identity_bound = False
                    if identity_id:
                        identity = await pool.fetchrow(
                            "SELECT name, image_url, ark_asset_id, ark_status "
                            "FROM ark_characters WHERE id=$1", identity_id)
                        if identity and identity["ark_status"] == "active" and identity["ark_asset_id"]:
                            identity_bound = True
                            reference_images.append({
                                "name": f"{e['name']}角色图片", "kind": "character",
                                "binding": "identity", "element_id": e["id"],
                                "identity_character_id": identity_id,
                                "url": f"asset://{identity['ark_asset_id']}",
                            })
                    reference_images.append({
                        "name": f"{e['name']}造型", "kind": "character_style",
                        "element_id": e["id"], "url": em["sheet_url"],
                    })
                    if em.get("hair_sheet_url"):
                        reference_images.append({
                            "name": f"{e['name']}发型发饰", "kind": "character_style",
                            "element_id": e["id"], "url": em["hair_sheet_url"],
                        })
                    # 有角色设定图 → 视频提示词只引用参考图（media 层提交时自动前置"图片N是角色X的设定图"），
                    # 外貌全文不进视频提示词（image_prompt 生首帧时仍需全文，见 char_full_parts）。
                    # 用户停用该角色的视频参考图 → 回退外貌全文（引用会落空）
                    # @设定图[名] 是参考图引用占位符：media 层提交时按实际传图替换为 @图片N
                    # （官方案例范式——引用织入正文使用点，而非只在开头声明一次）；
                    # 未真正传图的路径（GRSAI/1.x/降级）自动清理为普通文字
                    if pv:  # 视频身份层只织全镜剧本在场的角色
                        if e["name"] in video_off and desc_cn:
                            char_parts.append(f"「{e['name']}」：{desc_cn}")
                        else:
                            if identity_bound:
                                char_parts.append(
                                    f"「{e['name']}」使用 @设定图[{e['name']}角色图片] 中的五官，"
                                    f"服化道、发饰与动作参考 @设定图[{e['name']}造型]"
                                )
                            else:
                                char_parts.append(f"「{e['name']}」造型与外貌以 @设定图[{e['name']}] 为准")
                elif desc_cn and pv:
                    char_parts.append(f"「{e['name']}」：{desc_cn}")
                if desc_cn and pv:
                    char_full_parts.append(f"「{e['name']}」：{desc_cn}")
                if desc_cn and pi:
                    # wide 镜远距识别特征：剔除面部级片段（脸/眉/眼/疤…）——
                    # 之前掐前24字必然带脸（外貌全文都是脸开头），远景镜混入面部细节被质检实锤
                    keep = non_face_segments(em.get("外貌提示词") or "", en=True)
                    short = "、".join(keep[:3]) or (e["brief"] or "")[:24]
                    char_short_parts.append(f"「{e['name']}」（{short}）")
                # 首帧身份层（2026-07-14 用户实测回归修复）：外貌全文 + @设定图 引用双锚定。
                # 只留引用（07-13 版）实测会机械拼贴——设定图是半身特写立绘，缺了文字外貌与
                # 动作语境，模型直接把设定图的姿势/景别照搬进场景（多镜首图全是同款半侧面特写）。
                # 项目10 第2章镜21 的好形态即"全文织入 + 参考图"；引用句只负责锚定长相与服饰
                if not pi:
                    pass  # 首帧画面无此角色（如空景建立镜/角色中途才入画）：首帧身份层不织入
                elif em.get("sheet_url") and e["name"] not in image_off:
                    img_char_parts.append(
                        f"「{e['name']}」：{desc_cn}（面部与服饰造型以 @设定图[{e['name']}] 为准）"
                        if desc_cn else
                        f"「{e['name']}」面部与服饰造型以 @设定图[{e['name']}] 为准")
                elif desc_cn:
                    img_char_parts.append(f"「{e['name']}」：{desc_cn}")
            elif e["kind"] == "scene":
                required_refs.append({"name": e["name"], "kind": "scene", "element_id": e["id"],
                                      "url": em.get("sheet_url") or None, "targets": ["image", "video"]})
                if not scene_text:
                    scene_text = f"{e['name']}：{em.get('场景提示词') or e['brief'] or ''}"
                if em.get("sheet_url"):
                    reference_images.append({"name": e["name"], "kind": "scene", "url": em["sheet_url"]})
            elif em.get("needs_image"):
                # 关键实物（武器/法宝/器物等，要素预检关联进 element_ids）：外观一致性锚定
                required_refs.append({"name": e["name"], "kind": "prop", "element_id": e["id"],
                                      "url": em.get("sheet_url") or None, "targets": ["image", "video"]})
                _pdesc = em.get("外貌提示词") or e["brief"] or ""
                if em.get("sheet_url"):
                    reference_images.append({"name": e["name"], "kind": "prop", "url": em["sheet_url"]})
                    prop_parts.append(f"「{e['name']}」外观以 @设定图[{e['name']}] 为准")
                elif _pdesc:
                    prop_parts.append(f"「{e['name']}」：{_pdesc}")
        # 场景参考错绑守卫（ch6镜14 实锤：地点=据点房间内却挂"跳台"设定图，参考图会把画面拉去别处）：
        # 场景要素名与本镜 scene 地点无 ≥2 字连续重叠 → 判错绑，场景设定图与场景描述一并剔除
        # （文字警告拗不过参考图的像素引力，只能不传）；地点句仍在，画面以地点为准。
        _loc_now = _clean_location(meta.get("scene") or "")
        _scene_names = [r["name"] for r in reference_images if r["kind"] == "scene"]
        for _sn in _scene_names:
            if _loc_now and not any(_sn[i:i + 2] in _loc_now for i in range(len(_sn) - 1)):
                reference_images = [r for r in reference_images
                                    if not (r["kind"] == "scene" and r["name"] == _sn)]
                if scene_text.startswith(f"{_sn}："):
                    scene_text = ""
                # 清单同步：错绑场景从"需要"挪到"剔除"（前端与质检都要看到真实口径）
                _hit = next((r for r in required_refs if r["kind"] == "scene" and r["name"] == _sn), None)
                if _hit:
                    required_refs.remove(_hit)
                    excluded_refs.append({**_hit, "reason": f"场景要素与本镜地点「{_loc_now}」不符，错绑剔除"})
                log.info("镜 %s 场景参考错绑剔除: 「%s」与地点「%s」不符", shot_id, _sn, _loc_now)
        # 场景多景别空间参考图（场景组产物 2026-07-16，人工确认后生成）：组内全部镜头
        # 共享同一空间锚，空间布局与角色站位以其为准（steps/media 层带专用引用句，非造型设定图）
        _seg = meta.get("scene_seg") or (meta.get("blocking") or {}).get("seg")
        if _seg:
            _ch_meta = await conn.fetchval(
                "SELECT meta FROM content_nodes WHERE id=$1", shot["parent_id"])
            _ch_meta = _ch_meta if isinstance(_ch_meta, dict) else json.loads(_ch_meta or "{}")
            _grp = next((x for x in ((_ch_meta.get("scene_blocking") or {}).get("groups") or [])
                         if str(x.get("seg")) == str(_seg)), None)
            # 传空场景基准图而非站位图（2026-07-28 两阶段改造）：下游镜头本来就要自己排
            # 角色姿态与构图，传站位图会把那一张的人物构图整组复制进每一镜；无人基准图只锁
            # 环境，也顺带避开视频模型对写实正面人脸的"疑似真人"输入审核。老数据无基准图时
            # 回落站位图，保持行为不退化。
            _anchor_url = (_grp or {}).get("empty_url") or (_grp or {}).get("sheet_url")
            if _anchor_url and all(r["url"] != _anchor_url for r in reference_images):
                reference_images.append({"name": "场景基准图", "kind": "scene_sheet",
                                         "url": _anchor_url})
        # 用户手选的镜级额外参考（资产面板：首帧/故事板/封面等任意项目图片资产）——
        # 启停沿用 ref_off 名单（steps 侧按名过滤），重复 URL 不叠加
        for _er in meta.get("extra_refs") or []:
            if _er.get("url") and all(r["url"] != _er["url"] for r in reference_images):
                reference_images.append({"name": _er.get("name") or "参考",
                                         "kind": _er.get("kind") or "asset", "url": _er["url"]})
        char_text = "；".join(char_parts + prop_parts)  # 视频身份层：角色 + 关键实物
        char_full_text = "；".join(char_full_parts)
        reference_urls = [r["url"] for r in reference_images]
        prefs = await project_preferences(conn, project_id, "artist")
        # 跨镜连贯（2026-07-14）：本镜与上一镜「连贯」相接 → 首帧提示词织入承接句，
        # 让开场画面主动贴合上一镜收尾（配合接缝帧共用：本镜首帧会回填为上一镜尾帧）
        link_prev_note = ""
        if meta.get("link_prev"):
            _prev = await conn.fetchrow(
                "SELECT summary, meta FROM content_nodes WHERE parent_id=$1 AND kind='shot' "
                "AND deleted_at IS NULL AND seq<$2 ORDER BY seq DESC LIMIT 1",
                shot["parent_id"], shot["seq"])
            if _prev:
                _pm = _prev["meta"] if isinstance(_prev["meta"], dict) else json.loads(_prev["meta"])
                _pc = (_pm.get("cuts") or [{}])[-1]
                _tail = (_pc.get("action") or _pm.get("action") or (_prev["summary"] or ""))[:60]
                link_prev_note = (f"本镜与上一镜连贯相接：开场画面直接承接上一镜结尾"
                                  + (f"（上一镜收尾：{_tail}）" if _tail else "")
                                  + "，同场景同时刻，空间布局、光线与人物位置保持连续")

    def _blocks(*bs):
        return [b for b in bs if b]

    # 彩色首帧：画面+动作 + 项目画风 + 景别/角度/焦段/光效 + 场景 + 色调 + 质量
    # （两段式第一段：全部静态信息在此，video_prompt 只写运动增量）
    first_cut = (meta.get("cuts") or [{}])[0]
    # 首帧生效景别（构图三件套已跟随首切）：wide 镜人物是小比例身影，面部级外貌全文属矛盾信息；
    # 群像镜（首帧主体是人群）必须显式钉住"主体=人群"，否则具名角色外貌会把主体抢走
    frame_scale = first_cut.get("scale") or meta.get("scale", "")
    wide_frame = frame_scale in ("全景", "远景", "大远景")
    _subj = f"{first_cut.get('subject', '')} {meta.get('action', '')}"
    crowd_frame = any(w in _subj for w in ("人们", "人群", "众人", "群众", "百姓", "民众"))
    # wide 镜外貌降级：全文→剪影级识别特征（远距辨认服色/体型即可，面部细节反而误导构图）；
    # 中近景：有设定图的角色只留 @设定图 引用，无图角色才织外貌全文
    img_char_text = "；".join(char_short_parts) if wide_frame else "；".join(img_char_parts)
    img_bits = [desc.rstrip("。")]
    # 分镜定格：一个镜头只取一个定格画面。定格瞬间优先用 storyboard_still——那是
    # 由 LLM 通读本镜脚本后选出的、最能突出本镜关键画面或剧情走向的那一瞬，
    # 并标记它是首帧/尾帧/关键帧；缺它才退回"机械地取首切动作"的老口径。
    still = meta.get("storyboard_still") or {}
    _role_cn = {"first": "首帧", "last": "尾帧", "key": "关键帧"}
    # 定格是静态画面：装配期注入宿主切的台词（说：“…”）不进定格提示词
    _strip = lambda s: re.sub(  # noqa: E731
        r"，?\s*说：?[“\"][^”\"]*[”\"]", "", s or "").strip("，。 ")
    _still_act = _strip(still.get("moment"))
    _fc_act = _strip(first_cut.get("action"))
    if _still_act:
        label = _role_cn.get(still.get("role") or "", "关键帧")
        subject = still.get("subject") or first_cut.get("subject", "")
        img_bits.append(f"本镜分镜定格（{label}）: {subject}：{_still_act}")
    elif _fc_act:
        img_bits.append(f"首帧定格瞬间: {first_cut.get('subject', '')}：{_fc_act}")
    elif meta.get("action") and meta["action"].rstrip("。") not in desc:
        img_bits.append(f"动作瞬间: {meta['action']}")
    if link_prev_note:
        img_bits.append(link_prev_note)
    # 主体前置（Seedream 官方范式）：角色外貌紧跟画面与动作，不再挂在质量词之后垫底
    if img_char_text:
        img_bits.append(f"角色外貌: {img_char_text}")
    # 防机械拼贴（2026-07-14 实测回归）：设定图是半身/特写立绘，必须显式限定"只取造型"，
    # 否则模型把设定图的姿势与景别整体照搬进场景（多镜首图全是同款半侧面特写）
    if not wide_frame and "@设定图[" in img_char_text:
        img_bits.append("角色设定图仅提供长相、发型与服饰信息；画面中各角色的姿势、动作、朝向、"
                        "表情与景别必须严格按上文画面描述与动作瞬间重新塑造，"
                        "严禁照搬设定图中的站姿、半身特写或直视镜头的构图")
    # 站位锚（场景空间规划产物，2026-07-16）：首帧画面中各角色必须处在站位链指定位置——
    # 跨镜空间连贯的结构化通道，跳切镜也有兜底（上一镜女主在马车外、下一镜凭空上马车实锤）
    _blk = meta.get("blocking") or {}
    _blk_frame = {k: v for k, v in (_blk.get("chars") or {}).items()
                  if any(_names_match(k, c) for c in _frame_chars)}
    if _blk_frame:
        img_bits.append("站位: " + "；".join(f"「{k}」{_at(v)}" for k, v in _blk_frame.items())
                        + (f"（空间布局：{_blk['space']}）" if _blk.get("space") else ""))
    elif _blk.get("space") and not img_char_text:
        img_bits.append(f"空间布局: {_blk['space']}")
    if prop_parts:
        img_bits.append(f"关键物件: {'；'.join(prop_parts)}")
    if crowd_frame:
        img_bits.append("画面主体是人群整体的群像"
                        + ("，具名角色仅为背景或远处的小身影，不得成为画面主体" if img_char_text else ""))
    # 按首帧在场角色触发（不再看全镜角色）：空景首帧不再挂"人物远距身影"这种自相矛盾的句子
    if wide_frame and img_char_text:
        img_bits.append("人物均为远距离小比例身影，五官不可辨，禁止任何面部特写与近景细节刻画")
    # 防真人红线已放开（用户 2026-07-14）：允许照片级写实角色——后续在火山后台做角色备案
    # 规避"疑似真人"拒收；万一被拒仍有 VideoStep 降级级联（去首帧→参考图→纯文本）兜底。
    # 旧的强制 CG 质感句（07 上旬防拒收方案）会压平所有写实画风的真实感，已删除
    # 地点权威性（第6章镜1实测：scene_element 绑定偏差时，要素场景描述会把画面拉到别处）：
    # 本镜 scene 字段为权威地点，要素场景描述降级为环境外观参考
    loc = _loc_now
    if loc:
        img_bits.append(f"地点: {loc}（本镜画面必须发生在此地点）")
    if scene_text:
        img_bits.append(f"场景环境参考: {scene_text}"
                        + ("（仅供环境外观参考，地点以上文为准）" if loc else ""))
    if meta.get("lighting"):
        img_bits.append(f"光效: {meta['lighting']}")
    if meta.get("palette"):
        img_bits.append(f"色调: {meta['palette']}")
    # ── 双字段拆分（用户 2026-07-17 定稿）：user 段=上述叙事（画面/动作/站位/外貌/地点/光色），
    # anchor 段=结构句（禁文字 + 构图/光效/画风/质量锚词 + 偏好）——编译全文=user⊕anchor，
    # 编辑框按分隔线两段展示，anchor 随装配自动刷新（画风改了跟得上）、user 段手编后不被覆盖
    from . import prompt_fields as pf

    def _dedupe_terms(joined: str) -> str:
        return ", ".join(dict.fromkeys(t.strip() for t in joined.split(",") if t.strip()))

    img_user = "。".join(b.rstrip("。") for b in img_bits if b)
    # 画面禁文字（用户 2026-07-10 定稿）：ARK 无 negative，禁令必须进正向词（结构句归 anchor）
    _img_anchor_bits = ["画面中禁止出现任何文字、字幕、标注与水印, no text, no captions, "
                        "no subtitles, no watermark"]
    _img_anchor_bits += [b["positive"] for b in _blocks(
        *style_blocks, img_scale_block, img_angle_block, img_lens_block,
        *lighting_blocks, *motion_blocks, quality) if b.get("positive")]
    if prefs:
        _img_anchor_bits.append("; ".join(prefs))
    img_anchor = _dedupe_terms(", ".join(x for x in _img_anchor_bits if x))
    img_neg = ", ".join(b["negative"] for b in _blocks(
        *style_blocks, img_scale_block, img_angle_block, img_lens_block,
        *lighting_blocks, *motion_blocks, quality) if b.get("negative"))
    if negative:
        img_neg = ", ".join(x for x in [img_neg, negative["negative"]] if x)
    # 照片级角色负面词已随防真人红线一并放开（用户 2026-07-14）——写实画风需要真实皮肤质感
    img_neg = _dedupe_terms(img_neg)
    # 视频提示词：Seedance 官方范式（主体前置 + 场景 + 镜头 + 风格 + 画质 + 一致性约束）。
    # 中文为主（豆包系对中文语义最稳），模型对前 20-30 词加权最重 → 主体动作放最前。
    # "图片N是角色X的设定图…"引用句在提交时按实际传图动态前置（见 worker/media 层）——
    # 仅 Seedance 2.0 且无首帧时参考图才会真的传上去，1.5 下靠下方文字外貌描述。
    # 视频提示词 = 时间轴镜头脚本（用户 2026-07-09 定稿的形态）：
    # 主体是带秒区间的中文叙事，镜头语言内嵌在标注里；英文锚词只留画风一句。
    # 身份层两版：identity=短引用（有图）/ 外貌全文（纯文本兜底）——引用与附件同生死。
    # 权威时长：按本镜内容专业评估（忽略粗拆预估的 duration_s，见 estimate_shot_duration）——
    # 让「提示词里的 N 秒 / 落库 duration_s / 提交给模型的 duration」三者恒一致。
    real_duration = estimate_shot_duration(meta, desc)

    # 镜级运镜只对无切/单切镜复活（多切镜运镜内嵌在切 action 里，镜级参数会与切冲突）：
    # 官方案例每段都有镜头语言，我们的时间轴此前一句运镜都没有（ch16 端到端实锤）
    _shot_cam = (meta.get("camera_move") or "").strip()
    _shot_cam = "" if _shot_cam in ("", "无", "固定") else _shot_cam

    def _timeline_segments() -> list[str]:
        d = real_duration
        cuts = meta.get("cuts") or []
        segs = []
        # 单元素 cuts 视同无切（2026-07-14 一镜到底修复）：详细展开模型爱给普通镜包一层
        # 单切数组，按切路径走就是整镜一段；降到节拍路径拆多段（其 action 通常比镜级更细，
        # 优先用作节拍源），首帧构图仍按首切景别（装配上方已处理）
        if len(cuts) >= 2:
            t = 0
            for i, c in enumerate(cuts):
                sec = max(1, int(c.get("seconds") or 2))
                # 镜头语言到切级：景别 + 该剪辑镜头内的单一连续运镜
                scale = c.get("scale") or ""
                cut_move = (c.get("camera_move") or "").strip()
                cut_move = "" if cut_move in ("", "无", "固定") else cut_move
                head_parts = [((f"硬切至{scale}" if i else scale) if scale else ""), cut_move]
                head = "·".join(x for x in head_parts if x)
                subj, act = c.get("subject", ""), c.get("action", "")
                body = f"{subj}：{act}" if subj and act else (act or subj)
                segs.append(f"（{t}-{t + sec}秒{('·' + head) if head else ''}）{body}")
                t += sec
            return segs
        # 无切/单切（短镜或连续运动长镜）：按叙事节拍分段——但每拍≥2秒且节拍去重
        # （ch10镜317 实锤：一句话被逗号切成4段1秒碎拍，同一瞬间的表情被排成先后动作）
        act = (cuts[0].get("action") or "").strip("，。 ") if cuts else ""
        act = act or meta.get("action") or ""
        text = desc if (act and desc and SequenceMatcher(None, act, desc).ratio() >= 0.5
                        and len(desc) >= len(act)) else "，".join(x for x in (act, desc) if x)
        # 引号保护：台词（说：“…”）注入切 action 后含句读，拆节拍不得把一句台词拦腰截断
        _quotes: list[str] = []
        _masked = re.sub(r"“[^”]*”", lambda m: (_quotes.append(m.group(0)),
                                                f"\x00{len(_quotes) - 1}\x01")[1], text)

        def _unmask(s: str) -> str:
            return re.sub(r"\x00(\d+)\x01", lambda m: _quotes[int(m.group(1))], s)

        beats = [_unmask(b).strip() for b in re.split(r"[。；;]", _masked) if b.strip()]
        if len(beats) <= 1 and d >= 6:  # 长镜不许一句话拍到底（2026-07-14 从 8s 收紧到 6s）
            beats = [_unmask(b).strip() for b in re.split(r"[，,]", _masked) if b.strip()]
        uniq: list[str] = []
        for b in beats:  # 相似节拍去重：action 与 desc 常复述同一瞬间
            if any(b in u or u in b or SequenceMatcher(None, b, u).ratio() >= 0.6 for u in uniq):
                continue
            uniq.append(b)
        beats = uniq[:max(1, min(4, d // 2))] or [text]
        per = max(1, d // len(beats))
        # 首段标注镜头语言（景别取单切/镜级 + 镜级运镜）：连续长镜的多节拍共享同一机位
        _scale0 = (cuts[0].get("scale") if cuts else "") or meta.get("scale") or ""
        t = 0
        for i, b in enumerate(beats):
            end = d if i == len(beats) - 1 else t + per
            head = "·".join(x for x in ((_scale0, _shot_cam) if i == 0 else ()) if x)
            segs.append(f"（{t}-{end}秒{('·' + head) if head else ''}）{b}")
            t = end
        return segs

    def _video_segments(identity_text: str) -> tuple[str, str]:
        """视频提示词双段：user=叙事（时间轴/运动线/站位锚/对白/身份/场景光色音效），
        anchor=结构句（切换一致/运动约束/画风锚词/全彩/禁字幕/角色稳定/时长画质）。
        编译全文 = user⊕anchor，段内顺序与旧单段版一致（结构句集中到尾部）。"""
        user_parts = [" → ".join(_timeline_segments())]
        # 运动线只对无切/单切镜有效（多切镜的镜级运动线与切冲突，已废弃）
        _cam_path = (meta.get("camera_path") or "").strip()
        if _cam_path and _cam_path != "无" and len(meta.get("cuts") or []) <= 1:
            user_parts.append(f"镜头运动线：{_cam_path}")
        # 空间与站位锚定（场景空间规划产物，2026-07-16）：逐镜站位链已由场景组 LLM
        # 链好（上一镜结尾位置=本镜开场位置），此处按本镜在场角色织入——治跳切镜之间
        # 零空间信息传递（上一镜女主在马车外卖花、下一镜凭空站上马车实锤）
        _blk_v = {k: v for k, v in (_blk.get("chars") or {}).items()
                  if any(_names_match(k, c) for c in _video_chars)}
        if _blk.get("space") or _blk_v:
            _bbits = [
                f"空间锚定：{_blk['space']}" if _blk.get("space") else "",
                ("开场站位：" + "；".join(f"「{k}」{_at(v)}" for k, v in _blk_v.items())) if _blk_v else "",
                f"镜内位置变化：{_blk['moves']}" if _blk.get("moves") else "",
            ]
            user_parts.append(
                "。".join(x for x in _bbits if x)
                + "。除上述变化外各角色所处位置全程不变，与上一镜结尾的空间关系保持连贯，"
                  "严禁凭空改变角色位置")
        # 对白保底（无切镜的台词不经 cuts 嵌入时间轴，装配自叙事节拍可能不含台词原文）：
        # 台词必须作为表演内容显式在场，否则成片变哑剧（ch6镜14 实锤）
        _dlg = (meta.get("dialogue") or "").strip()
        if _dlg and _dlg != "无" and not meta.get("cuts"):
            user_parts.append(f"人物台词（依序完整说出，不显示字幕）：{_dlg}")
        if identity_text:
            user_parts.append(f"角色设定：{identity_text}")
        # 音效层（Seedance 2.0 带音频生成；官方案例的声音设计均显式入词——脚本 sfx 不进提示词=白写）
        _sfx = (meta.get("sfx") or "").strip()
        # 场景设定图引用织入使用点（同角色 @设定图 占位符机制）
        _scene_sheet = next((r["name"] for r in reference_images if r["kind"] == "scene"), "")
        _scene_head = (f"场景环境参考（外观以 @设定图[{_scene_sheet}] 为准）"
                       if _scene_sheet else "场景环境参考")
        scene_bits = [x for x in (
            f"地点：{loc}（画面必须发生在此地点）" if loc else "",
            (f"{_scene_head}：{scene_text}"
             + ("（地点以上文为准）" if loc else "")) if scene_text else "",
            f"光效：{meta['lighting']}" if meta.get("lighting") else "",
            f"色调：{meta['palette']}" if meta.get("palette") else "",
            f"音效：{_sfx}" if _sfx and _sfx != "无" else "",
        ) if x]
        if scene_bits:
            user_parts.append("。".join(scene_bits))
        # ── anchor 段：结构句 ──
        anchor_parts: list[str] = []
        if len(meta.get("cuts") or []) > 1:  # 单切镜没有"切换"，此句白占权重
            anchor_parts.append("所有切换共享同一空间，角色站位/服装/光线在切换间保持完全一致")
        # 运动约束句（AI 视频默认慢漂移，必须显式对抗）
        anchor_parts.append("动作与运镜为真实速度，干脆利落，禁止慢动作，禁止缓慢漂移")
        # 英文锚词只留画风一句（构图/焦段等英文块属于生图，堆进视频会与叙事冲突）
        for b in style_blocks:
            anchor_parts.append(b["positive"])
        anchor_parts.append("全彩画面，电影级调色")
        # 画面禁文字/字幕（Seedance 见到对白会自动烧字幕条——对白只作表演内容，字幕走独立 VTT/SRT）
        anchor_parts.append("画面内禁止渲染任何文字、字幕与水印，对白仅作为人物表演内容，不要生成字幕条")
        if meta.get("characters"):
            # 与设定图一致性由身份层的 @设定图[名] 内联引用钉住（官方案例范式）
            anchor_parts.append("同一角色，面部稳定不变形，服装不变，发型不乱")
        anchor_parts.append(f"画面稳定流畅，细节丰富无噪点，4K高清，{real_duration}秒")
        return ("。".join(p.rstrip("。") for p in user_parts if p),
                "。".join(p.rstrip("。") for p in anchor_parts if p))

    video_user, video_anchor = _video_segments(char_text)
    video_prompt = pf.compose(video_user, video_anchor)
    if char_full_text != char_text:
        _tu, _ta = _video_segments(char_full_text)
        video_prompt_textonly = pf.compose(_tu, _ta)
    else:
        video_prompt_textonly = video_prompt

    prompts = {
        "image_negative": img_neg,
        "duration_s": real_duration,  # 以时间轴回写权威总时长（覆盖分镜阶段的预估）
        "reference_urls": reference_urls,
        "reference_images": reference_images,
        # 本镜所需/被剔除要素清单（2026-07-14）：前端参考区按此渲染（无图=占位可点击生成），
        # 质检以此为准绳——清单外的角色不得织入/引用，清单内的要素必须列全
        "required_refs": required_refs,
        "excluded_refs": excluded_refs,
    }
    # ── 双字段合并落库（2026-07-17）：分段冻结——改过的段保留、未冻结段随装配刷新，重拼全文。
    # 旧整段手编（无分段数据 + {key}_edited）：三字段全部不动、全文回带（历史兼容，显式
    # 「重生成提示词」清标记后进入双段世界）
    for _k, _nu, _na, _sep in (("image_prompt", img_user, img_anchor, "。"),
                               ("video_prompt", video_user, video_anchor, "。")):
        _cu, _ca = meta.get(f"{_k}_user"), meta.get(f"{_k}_anchor")
        if not (_cu or _ca) and meta.get(f"{_k}_edited") and meta.get(_k):
            prompts[_k] = meta[_k]
            continue
        _u = _cu if (meta.get(f"{_k}_user_edited") and _cu) else _nu
        _a = _ca if (meta.get(f"{_k}_anchor_edited") and _ca) else _na
        prompts[f"{_k}_user"], prompts[f"{_k}_anchor"] = _u, _a
        prompts[_k] = pf.compose(_u, _a, _sep)
    # textonly（降级纯文本用，全文单字段不分段）：视频全文被冻结/user 段被冻结时跟随现值——
    # 冻结的时间轴与新评估时长可能不符，duration 一并保留（现状语义）
    if prompts["video_prompt"] == video_prompt:
        prompts["video_prompt_textonly"] = video_prompt_textonly
    else:
        prompts["video_prompt_textonly"] = meta.get("video_prompt_textonly") or video_prompt_textonly
        prompts["duration_s"] = meta.get("duration_s") or real_duration
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
            shot_id, json.dumps(prompts, ensure_ascii=False),
        )
    return prompts
