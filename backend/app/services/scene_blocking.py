"""场景组空间规划（blocking，用户 2026-07-16 定稿）：治跨镜空间断裂。

此前跨镜连贯只有 link_prev 承接句 + 接缝帧两条通道，同场景「跳切」镜之间零空间
信息传递——上一镜女主在马车外卖花、下一镜直接站上马车（实锤）。本模块补上第三条
结构化通道：

1. 确定性场景归组：同章内 scene 连续段聚成「场景组」，组号落每镜 meta.scene_seg
   （空 scene 的手动插镜继承前组；同场景中途离开再回来算新组，符合剪辑口径）；
2. 组级 LLM 空间规划：看全组剧本产出 空间布局 + 组开场各角色占位 + 逐镜站位链
   （上一镜结尾位置=下一镜开场位置）+ 镜内移动，落每镜 meta.blocking；
3. 组级汇总（含「场景多景别参考图」提示词，自动产出、人工确认后点击生成）落章
   meta.scene_blocking.groups，指纹缓存：组内剧本没改不重烧 LLM。

装配期由 storyboard.assemble_shot_prompts 把站位锚织入首帧/视频提示词，
场景多景别图作为组内全部镜头的空间参考图传入生成。
"""
import asyncio
import json
import logging
from typing import Any

import asyncpg

from .. import llm
from . import element_variants as ev
from . import flow, volumes

log = logging.getLogger("scene_blocking")

_BLOCKING_TTL_H = 168  # 指纹不变即命中，TTL 只是兜底刷新
_BLOCKING_PROMPT_VERSION = "scene-anchor-two-stage-v6-marker-only"

# 场景光影站位锚定技能（标准 Skill，sql/29 安装并绑定 scene-designer）：两阶段口径、
# 跨图一致性纪律与光影字段都在技能正文里，管理页可编辑。此处只留代码兜底——生产镜像与
# 数据迁移的启动顺序不该影响核心纪律。
#
# 2026-07-28 定稿：放弃"一张多宫格"，改两阶段。实测（章1026 场景1）证明单次调用画多宫格
# 治不了漂移——空场景格里照样站着人、俯视格画成了场景设定图的翻版、同一条龙在两格里完全
# 两个样。根因是格与格之间除了文字没有任何硬锚。改成先出无人空场景图、再把它**当参考图**
# 出站位图后，空间与光线有了实物锚，模型只需在给定空间里摆人。
ANCHOR_SKILL_SLUG = "scene-light-blocking-anchor"
ANCHOR_SKILL_FALLBACK = """# 场景光影站位锚定（两阶段）

一个场景组出两张单幅图，组内每个镜头都以它们为空间与光影真值：

**第一阶段·空场景基准图（empty_desc）**：画面里**不得出现任何人物或生物**。一个机位、
一种景别的完整画面，交代空间轮廓、关键结构物方位、家具陈设、材质，以及时间段、天气、
主光方向、光质、环境光色、明暗层次与阴影落向。这是整个场景组的几何与光的真值——
被人物挡住的空间就不再是真值，所以这一张必须先出、必须无人。

**第二阶段·角色站位图（sheet_desc）**：以第一阶段的成图为参考图生成。空间结构、陈设、
机位、景别与光线**严格照搬基准图，一律不得改动**；唯一的新增内容是按站位锚把角色放进去。
写明各角色在画面中的位置与相互距离，不写朝向以外的表演细节。

共同纪律：
1. 两张是同一场景、同一时刻、同一天气、同一主光方向下的同一个机位，不是两个场景、
   不是两个时刻、不是两个机位。
2. 角色造型以其设定图为准，不得增减人数、不得换脸换装；没有设定图的角色按文字描述，
   并在描述里写清体型与关键特征。
3. 角色面部不是表现重点，避免五官正面特写与直视镜头（此图作参考图提交视频模型，
   写实正面人脸会触发"疑似真人"审核拒收）。
4. 两张都是满幅单幅画面。禁止：宫格、拼图、分镜板、接触表、分割线、画中画、相框白边、
   同一画面的重复变体；画面内任何文字、字幕、编号、标注与水印。"""

_INDOOR_HINT = (
    "室内", "屋内", "房间", "卧室", "客厅", "厨房", "书房", "工坊", "作坊", "车间", "仓库",
    "地下室", "走廊", "楼梯", "大厅", "船舱", "舱", "车厢", "店内", "酒馆", "教室", "办公室",
    "洞穴", "洞内", "帐篷", "塔内", "殿内", "庙内", "阁楼", "阁内",
)

def is_indoor(scene: str, space: str = "") -> bool:
    """命中室内词表即按室内处理（默认景别与封闭性描述要分室内外）。"""
    return any(k in f"{scene}｜{space}" for k in _INDOOR_HINT)


# 两阶段的共同纪律句：单幅满幅、禁宫格、禁文字（空场景图与站位图都要，措辞保持一份）
SINGLE_FRAME_RULE = (
    "满幅完整连续的单幅电影画面，画面铺满整个图幅；"
    "严禁宫格、拼图、分镜板、接触表、分割线、画中画、相框白边或同一画面的重复变体；"
    "画面中禁止出现任何文字、字幕、标注、编号与水印, no text, no captions, no watermark"
)
# 站位图对基准图的硬引用句：空间/机位/光线一律照搬，唯一新增的是人。
# 这句是两阶段方案的全部意义所在——空间不再靠文字自证，而是有一张实物图当锚。
EMPTY_ANCHOR_RULE = (
    "图片1是本场景的**空场景基准图**：画面的空间结构、建筑与家具陈设、材质、机位角度、"
    "景别、镜头朝向、时间天气、主光方向与明暗层次**全部严格照搬图片1，一律不得改动、"
    "不得换机位、不得增删结构物**；本次唯一新增的内容是按站位把角色放进这个空间里"
)


# 站位锚里混进来的朝向/姿态/动作（旧版技能允许"位置+朝向+姿态"，存量数据里到处都是）。
# 它们对生图是表演指令，会让模型改构图、给角色加道具——站位图只该说"人在哪"。
_POSE_CUT = ("，面朝", "，朝", "，正在", "，手里", "，手中", "，看向", "，低头", "，抬头",
             "，转身", "，背对", "，蹲", "，坐", "，站", "，卧", "、面朝", "、正在")


def position_only(pos: str) -> str:
    """把站位锚裁到只剩空间位置：切掉第一个朝向/姿态/动作从句及其后全部内容。"""
    s = (pos or "").strip()
    cut = min((i for i in (s.find(k) for k in _POSE_CUT) if i > 0), default=-1)
    return (s[:cut] if cut > 0 else s).rstrip("，、。 ")


def default_empty_desc(scene: str, space: str) -> str:
    """LLM 没给空场景描述时的兜底。"""
    wide = "平视全景" if is_indoor(scene, space) else "大远景"
    return (f"{wide}，画面中没有任何人物与生物；交代空间轮廓、关键结构物方位、"
            f"家具陈设与材质，以及时间段、天气、主光方向与明暗层次。{space}")

# 场景空间规划技能（可被 kb_entries kind=skill agent_code=director 覆盖——项目级可改）
BLOCKING_RULES = """你是电影场景调度师（blocking）。给定同一场景内连续的一组分镜脚本，产出该场景的空间布局与每一镜的角色站位，用于锚定跨镜头的空间连贯——后续每个镜头独立生成视频，全靠你的站位链保证「上一镜角色在哪、下一镜还在哪」。
规则：
1. space：一句**机位无关**的空间布局描述（60字内）：场景的关键结构物及其相对方位（如"青石街道，马车停在街心、车头朝东，右侧街边是花摊，远处是城门"）
2. anchors：组开场时各角色的初始**空间位置**（如"男主：马车车厢内靠窗处"）；只写组内出场过的角色，位置必须与剧本一致。禁止把朝向、表情、姿态、动作或速度混入位置
3. shots[]：逐镜给出该镜**开场瞬间**各角色所处的空间位置（chars）。chars 的值只能是可复用的位置区域，如"马车车厢内靠窗处"、"花摊右侧"；禁止写"面朝、转头、点头、挥翼、加速、看向、触摸"等朝向、姿态和动作。必须按前面镜头的移动链好：上一镜没有移动时，下一镜同一角色的 chars 值必须逐字复制上一镜；上一镜发生移动时，下一镜 chars 必须等于该移动的终点。若该镜内角色发生位置移动，用 moves 一句写明（谁从哪移动到哪，如"女主从花摊走近车窗"），无移动 moves 填空串
4. 严禁把角色凭空搬到别处：剧本没写移动的角色位置全程不变（在马车里的一直在马车里，在车外的一直在车外）；每镜 chars 只写该镜剧本中实际出场的角色
5. empty_desc（第一阶段·空场景基准图）：这一张先出，**画面里不得出现任何人物或生物**。一个机位、一种景别的完整单幅画面，写明：景别、机位角度、镜头朝向、前中后景、空间轮廓与关键结构物方位、家具陈设与材质，以及时间段、天气、主光方向、光质、环境光色、明暗层次与阴影落向。它是本场景组的几何与光的真值——被人物挡住的空间就不再是真值，所以必须无人
6. sheet_desc（第二阶段·角色站位图）：这一张会**拿第一阶段的成图当参考图**来生成。所以只写"在这个已定的空间与光线里，各角色站在哪、相互距离多远、朝向何方"，按 anchors 落位；**不要重新描述空间、机位、景别或光线**（那些一律照搬基准图）。**这是空间参考图不是角色设定图：角色面部不是表现重点，避免五官正面特写与角色直视镜头**（此图会作为参考图提交给视频模型，写实正面人脸可能触发平台"疑似真人"审核拒收）
7. 两张都是满幅单幅画面：严禁宫格、拼图、分镜板、接触表、分割线、画中画、相框白边或同一画面的重复变体，画面内不得出现文字、标注或编号
严格输出 JSON：
{"space":"空间布局一句","anchors":{"角色名":"初始位置+朝向"},"shots":[{"shot_no":1,"chars":{"角色名":"该镜开场位置"},"moves":""}],"empty_desc":"无人空场景：景别/机位/朝向/前中后景/空间结构/陈设材质/时间天气/主光方向/明暗层次","sheet_desc":"在基准图给定的空间与光线里，各角色的站位与相互距离"}"""


def _meta_of(row: Any) -> dict[str, Any]:
    m = row["meta"]
    return m if isinstance(m, dict) else json.loads(m or "{}")


async def backfill_sheet_urls(pool: asyncpg.Pool, chapter_id: int) -> int:
    """自愈：用章级附件里最新的 scene_sheet 补回组条目上缺失的 sheet_url，返回补回的组数。

    出图产物落两处——附件表（逐次留档，只 INSERT 不覆盖）与组条目 sheet_url（当前指针）。
    2026-07-28 前的丢更新缺陷会让后者丢失（并发批量出图 / 规划整数组写回覆盖），
    表现为「图生成了但场景卡还是空的」。附件表是完整的，据其补回即可，不必重烧。"""
    rows = await pool.fetch(
        "SELECT DISTINCT ON (meta->>'type', (meta->>'seg')::int) "
        "meta->>'type' AS type, (meta->>'seg')::int AS seg, url "
        "FROM content_attachments WHERE node_id=$1 AND kind='image' "
        "AND meta->>'type' IN ('scene_sheet','scene_empty') AND meta->>'seg' ~ '^[0-9]+$' "
        "ORDER BY meta->>'type', (meta->>'seg')::int, id DESC", chapter_id)
    if not rows:
        return 0
    # 两阶段各有自己的附件类型与指针：scene_empty→empty_url、scene_sheet→sheet_url
    by_key = {(r["type"], int(r["seg"])): r["url"] for r in rows if r["url"]}
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "SELECT meta FROM content_nodes WHERE id=$1 FOR UPDATE", chapter_id)
        if not row:
            return 0
        sb = _meta_of(row).get("scene_blocking") or {}
        fixed = 0
        for g in sb.get("groups") or []:
            seg = int(g.get("seg") or 0)
            for att_type, field in (("scene_empty", "empty_url"), ("scene_sheet", "sheet_url")):
                url = by_key.get((att_type, seg))
                if url and not g.get(field):
                    g[field] = url
                    fixed += 1
        if fixed:
            await conn.execute(
                "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
                chapter_id, json.dumps({"scene_blocking": sb}, ensure_ascii=False))
            log.info("章 %s 场景图指针自愈：补回 %d 组 sheet_url", chapter_id, fixed)
    return fixed


def norm_scene(scene: str) -> str:
    """归组键：scene（"场景名/时间/地点"）剔除占位段后的整串。惰性导入防循环依赖。"""
    from .storyboard import _clean_location

    return _clean_location(scene or "")


def assign_scene_segments(shots: list[dict[str, Any]]) -> None:
    """纯函数：按 scene 连续段给拆镜结果标场景组号（1-based，原地写 scene_seg）。
    空 scene 继承前组（手动插镜/占位地点不该自成一组）；A→B→A 算三组（剪辑口径）。"""
    seg, prev = 0, None
    for s in shots:
        key = norm_scene(s.get("scene") or "")
        if key and key != prev:
            seg += 1
            prev = key
        elif seg == 0:  # 首镜 scene 为空的兜底
            seg = 1
        s["scene_seg"] = seg


async def recompute_scene_segments(
    pool: asyncpg.Pool, chapter_id: int,
) -> list[dict[str, Any]]:
    """对一章存活分镜重算场景组号并落库（幂等；手动插镜/老数据兜底）。
    返回分组清单：[{seg, scene, rows:[镜行], shot_nos}]，rows 按 seq 有序。"""
    rows = await pool.fetch(
        "SELECT id, seq, summary, meta FROM content_nodes "
        "WHERE parent_id=$1 AND kind='shot' AND deleted_at IS NULL ORDER BY seq", chapter_id)
    groups: list[dict[str, Any]] = []
    seg, prev = 0, None
    for r in rows:
        m = _meta_of(r)
        key = norm_scene(m.get("scene") or "")
        if (key and key != prev) or seg == 0:
            seg += 1
            prev = key or prev
            groups.append({"seg": seg, "scene": m.get("scene") or "", "rows": [], "shot_nos": []})
        groups[-1]["rows"].append(r)
        groups[-1]["shot_nos"].append(m.get("shot_no"))
        if m.get("scene_seg") != seg:
            await pool.execute(
                "UPDATE content_nodes SET meta = meta || $2::jsonb WHERE id=$1",
                r["id"], json.dumps({"scene_seg": seg}))
    return groups


def _group_source(g: dict[str, Any]) -> str:
    """组内剧本指纹源：镜号/地点/出场/动作/对白/画面——变了才重跑空间规划。"""
    lines = []
    for r in g["rows"]:
        m = _meta_of(r)
        lines.append(f"{m.get('shot_no')}|{m.get('scene', '')}|{'、'.join(m.get('characters') or [])}"
                     f"|{m.get('action', '')}|{m.get('dialogue', '')}|{r['summary'] or ''}")
    return "\n".join(lines)


def _group_script(g: dict[str, Any]) -> str:
    """喂给调度师 LLM 的组内分镜脚本。"""
    lines = []
    for r in g["rows"]:
        m = _meta_of(r)
        cuts = "；".join(f"{c.get('subject', '')}:{c.get('action', '')}"
                        for c in (m.get("cuts") or []) if c.get("action"))
        lines.append(
            f"镜{m.get('shot_no')}｜{m.get('scale', '')}｜出场:{'、'.join(m.get('characters') or []) or '无'}"
            f"｜动作:{m.get('action', '')}｜对白:{m.get('dialogue', '无')}"
            f"｜画面:{(r['summary'] or '')[:80]}" + (f"｜组内切:{cuts[:120]}" if cuts else ""))
    return "\n".join(lines)


def _validate_blocking(data: dict[str, Any], g: dict[str, Any]) -> list[str]:
    """零 token 校验：必填在场 + 逐镜覆盖（缺镜=站位链断裂，必须打回）。"""
    errs: list[str] = []
    if not (data.get("space") or "").strip():
        errs.append("缺 space 空间布局")
    got = {int(x.get("shot_no") or 0) for x in (data.get("shots") or []) if isinstance(x, dict)}
    for r in g["rows"]:
        no = _meta_of(r).get("shot_no")
        try:
            if int(no) not in got:
                errs.append(f"shots 缺镜{no}的站位")
        except (TypeError, ValueError):
            pass  # 手动插镜的小数号：LLM 按字符串回带时下方合并按字符串匹配，此处不强校
    # 两阶段：空场景描述必须在场且真的无人——它是站位图的空间锚，混进角色就白搭了。
    empty = (data.get("empty_desc") or "").strip()
    if not empty:
        errs.append("缺 empty_desc（第一阶段无人空场景基准图的描述）")
    else:
        for name in (data.get("anchors") or {}):
            if name and name in empty:
                errs.append(f"empty_desc 里出现了角色「{name}」——基准图必须无人")
                break
    if not (data.get("sheet_desc") or "").strip():
        errs.append("缺 sheet_desc（第二阶段角色站位描述）")
    return errs


async def _plan_group(
    conn: asyncpg.Connection, project_id: int, project: Any, g: dict[str, Any],
) -> dict[str, Any]:
    """单组 LLM 空间规划（含一次校验重试）。抛异常由上层记日志跳过（不阻塞其它组）。"""
    from .character_context import era_anchor, roster_line
    from .scene_transitions import SKILL_RULES_FALLBACK
    from .storyboard import _director_skill, _standard_skill_context

    system = await _director_skill(conn, project_id, "场景空间规划", BLOCKING_RULES)
    # 版式纪律不再写死在代码里：走标准 Skill「场景光影站位锚定」（scene-designer 员工绑定，
    # 管理页可编辑），未安装时回退代码常量。旧版 kb 技能里的"只分两块"由本段覆盖。
    system += "\n\n【场景光影站位锚定技能】\n" + await _standard_skill_context(
        conn, project_id, ANCHOR_SKILL_SLUG, ANCHOR_SKILL_FALLBACK, agent_code="scene-designer")
    system += "\n\n" + await _standard_skill_context(
        conn, project_id, "subject-aware-scene-transitions", SKILL_RULES_FALLBACK)
    chars = list(dict.fromkeys(c for r in g["rows"] for c in (_meta_of(r).get("characters") or [])))
    briefs = await conn.fetch(
        "SELECT name, brief FROM content_elements WHERE project_id=$1 AND kind='character' "
        "AND name = ANY($2::text[])", project_id, chars) if chars else []
    roster = "\n".join(roster_line(b["name"], b["brief"]) for b in briefs) or "（本组无具名角色）"
    user = (
        f"【项目世界观/年代背景】{era_anchor(project) if project else '（无）'}\n\n"
        f"【场景】{g['scene'] or '（未标注）'}\n\n【组内角色】\n{roster}\n\n"
        f"【本组分镜脚本（同一场景内连续镜头，按序）】\n{_group_script(g)}"
    )
    data = await llm.chat_json(system, user, max_tokens=6000)
    errs = _validate_blocking(data, g)
    if errs:
        data = await llm.chat_json(
            system, user + "\n\n【上一版违反以下要求，请修正后重新输出完整 JSON】\n" + "\n".join(errs[:8]),
            max_tokens=6000)
    return data


async def _stage_prompts(
    conn: asyncpg.Connection, project_id: int, project: Any, g: dict[str, Any],
    space: str, anchors: dict[str, str], empty_desc: str, sheet_desc: str,
) -> dict[str, Any]:
    """装配两阶段提示词与各自参考池。返回 {empty_user, empty_anchor, empty_refs,
    sheet_user, sheet_anchor, sheet_refs}，均落组条目供人工确认/编辑后点击生成。

    参考池分家是两阶段的关键：
    - 空场景图 = 项目环境锚点 + 场景设定图（**不带任何角色图**，带了就会画出人）；
    - 站位图  = 角色设定图（空场景基准图在出图时由 before 动态插到首位——规划期它还没生成）。
    """
    from ..knowledge import get_block, recall_blocks
    from .storyboard import _at, _names_match

    env_refs: list[dict[str, Any]] = []
    # 项目级环境锚点是所有章节场景的媒介/材质/世界观基线。此前场景组图只在
    # 恰好命中具体 scene element 时才有环境参考，未命中便只上传角色图，模型很容易
    # 把“港口”等泛化词画成现代写实码头。固定把最新环境锚点放在参考池首位。
    environment_anchor = await conn.fetchrow(
        "SELECT url FROM project_visual_assets "
        "WHERE project_id=$1 AND asset_role='project_environment_style_anchor' "
        "AND status='generated' AND coalesce(url,'')<>'' "
        "ORDER BY version DESC LIMIT 1",
        project_id,
    )
    if environment_anchor:
        env_refs.append({
            "name": "项目场景画风锚点",
            "kind": "style",
            "url": environment_anchor["url"],
        })
    scene_text = ""
    scene_names = list(dict.fromkeys(
        n for r in g["rows"] for n in [_meta_of(r).get("scene_element")] if n and n != "无"))
    if scene_names:
        se = await conn.fetchrow(
            "SELECT id, name, brief, meta FROM content_elements WHERE project_id=$1 "
            "AND kind='scene' AND name = ANY($2::text[]) LIMIT 1", project_id, scene_names)
        if se:
            em = _meta_of(se)
            scene_text = em.get("场景提示词") or se["brief"] or ""
            if em.get("sheet_url"):
                env_refs.append({"name": se["name"], "kind": "scene", "element_id": se["id"],
                                 "url": em["sheet_url"]})
    char_refs: list[dict[str, Any]] = []
    char_bits: list[str] = []
    if anchors:
        crows = await conn.fetch(
            "SELECT id, name, brief, meta FROM content_elements WHERE project_id=$1 AND kind='character'",
            project_id)
        _corpus = _group_script(g)
        for name, pos in anchors.items():
            hit = next((c for c in crows if _names_match(name, c["name"])), None)
            # 取图统一走 effective_meta：多形态按本组剧本语料选形态（与逐镜首帧同口径）
            em = ev.effective_meta(_meta_of(hit), _corpus) if hit else {}
            where = _at(position_only(pos))
            if hit and em.get("sheet_url"):
                char_refs.append({"name": hit["name"], "kind": "character", "element_id": hit["id"],
                                  "url": em["sheet_url"]})
                # 造型全权交给参考图标记（装配期会解析成 @图片N）：写文字描述只会跟设定图打架
                char_bits.append(f"「{name}」{where}，形象完全以 @设定图[{hit['name']}] 为准")
            else:
                look = (em.get("外貌提示词") or (hit["brief"] if hit else "") or "")[:40]
                char_bits.append(f"「{name}」{where}" + (f"（{look}）" if look else ""))
    style_blocks = await recall_blocks(conn, project["art_style"] or "日漫", ["style"], project_id, top_k=1)
    quality = await get_block(conn, "quality", "通用质量词")
    tail = ", ".join(x for x in (
        (style_blocks[0].get("positive") if style_blocks else ""),
        (quality.get("positive") if quality else "")) if x)
    scene_name = norm_scene(g["scene"]) or g["scene"]
    art = f"项目固定画风与媒介：{project['art_style']}" if project["art_style"] else ""

    def _join(bits: list[str], with_tail: bool = False) -> str:
        s = "。".join(b.rstrip("。") for b in bits if b)
        return s + (f", {tail}" if with_tail and tail else "")

    # ── 第一阶段：无人空场景基准图 ──
    empty_user = _join([
        empty_desc or default_empty_desc(g["scene"], space),
        f"空间布局: {space}",
        f"场景外观参考: {scene_text}" if scene_text else "",
    ])
    empty_anchor = _join([
        f"场景「{scene_name}」的空场景基准图（本场景组全部镜头的空间与光影真值）",
        "**画面中不得出现任何人物、动物或生物**，只有空间本身",
        SINGLE_FRAME_RULE,
        art,
        "必须明确前景、中景、后景与镜头朝向；光线必须明确时间段/天气、主光方向、光质、"
        "环境光色、明暗层次与阴影落向",
    ], with_tail=True)

    # ── 第二阶段：角色站位图（出图时 before 会把基准图插到参考池首位）──
    # 叙事段只留「站位 + 参考图标记」，**一句画面描述都不带**（用户 2026-07-28 定稿）：
    # 空间、机位、景别与光线全部由基准图承担，再写一遍画面描述模型就会重画一遍场景——
    # 实测 sheet_desc 里的"局部格：展示工作台上的风帆翼"让模型把风帆翼画到了角色背上。
    # sheet_desc 仍落库供人读，只是不进提示词；无角色的场景组才退回用它。
    sheet_user = _join([
        f"在图片1这个已定的空间与光线中放入以下角色，除此之外不改动画面任何内容: "
        f"{'；'.join(char_bits)}" if char_bits else sheet_desc,
    ])
    sheet_anchor = _join([
        f"场景「{scene_name}」的角色站位图",
        EMPTY_ANCHOR_RULE,
        "每个角色的形象**完全依据其设定图**还原：不得增减人数、不得换脸换装，"
        "**不得给角色添加设定图里没有的翅膀、尾巴、道具或服饰**，"
        "也不得把场景内的物件挂到角色身上；角色面部不是表现重点，避免五官正面特写和直视镜头",
        SINGLE_FRAME_RULE,
        art,
    ], with_tail=True)
    return {
        "empty_user": empty_user, "empty_anchor": empty_anchor, "empty_refs": env_refs[:4],
        "sheet_user": sheet_user, "sheet_anchor": sheet_anchor, "sheet_refs": char_refs[:3],
    }


# 同章空间规划锁（进程内）：多镜并发生成（worker 6 协程）同时发现缺站位锚时，
# 只有第一个真的规划，其余在锁内复查指纹后直接命中缓存——防同章重复烧 LLM
_CHAPTER_LOCKS: dict[int, asyncio.Lock] = {}


async def ensure_scene_blocking(
    pool: asyncpg.Pool, project_id: int, chapter_id: int,
    only_seg: int | None = None, force: bool = False,
) -> dict[str, Any]:
    """章级场景空间规划主入口（幂等，指纹缓存）：重算分组 → 逐组规划 → 落库。
    only_seg：只保证某一组（镜级生成前置的兜底路径，缓存命中即零成本）。
    返回 {groups: N, planned: [seg...], skipped: [seg...]}。"""
    async with _CHAPTER_LOCKS.setdefault(int(chapter_id), asyncio.Lock()):
        return await _ensure_scene_blocking_locked(pool, project_id, chapter_id, only_seg, force)


async def _ensure_scene_blocking_locked(
    pool: asyncpg.Pool, project_id: int, chapter_id: int,
    only_seg: int | None, force: bool,
) -> dict[str, Any]:
    groups = await recompute_scene_segments(pool, chapter_id)
    if not groups:
        return {"groups": 0, "planned": [], "skipped": []}
    async with pool.acquire() as conn:
        chapter = await conn.fetchrow(
            "SELECT meta FROM content_nodes WHERE id=$1 AND kind='chapter'", chapter_id)
        project = await conn.fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
        project = await volumes.effective_for_chapter(conn, project, chapter_id)
    if not chapter:
        raise ValueError("章节不存在")
    old = {int(e.get("seg") or 0): e
           for e in ((_meta_of(chapter).get("scene_blocking") or {}).get("groups") or [])}
    entries: list[dict[str, Any]] = []
    planned, skipped = [], []
    for g in groups:
        if only_seg is not None and g["seg"] != only_seg:
            entries.append(old.get(g["seg"]) or {"seg": g["seg"], "scene": g["scene"],
                                                 "shot_nos": g["shot_nos"]})
            continue
        # 提示词策略升级也必须使旧缓存失效，否则历史四宫格提示词会永久命中。
        src = f"{_BLOCKING_PROMPT_VERSION}\n{_group_source(g)}"
        prev = old.get(g["seg"])
        if prev and not force and flow.cache_valid(prev, src) and prev.get("space"):
            entries.append({**prev, "shot_nos": g["shot_nos"]})
            skipped.append(g["seg"])
            continue
        try:
            async with pool.acquire() as conn:
                data = await _plan_group(conn, project_id, project, g)
                space = (data.get("space") or "").strip()
                anchors = {str(k): str(v) for k, v in (data.get("anchors") or {}).items() if v}
                sheet_desc = (data.get("sheet_desc") or "").strip()
                empty_desc = (data.get("empty_desc") or "").strip()
                stages = await _stage_prompts(
                    conn, project_id, project, g, space, anchors, empty_desc, sheet_desc)
        except Exception as e:  # noqa: BLE001 — 单组失败不阻塞其它组（尽力而为）
            log.warning("章 %s 场景组 %s 空间规划失败: %s", chapter_id, g["seg"], e)
            entries.append(prev or {"seg": g["seg"], "scene": g["scene"], "shot_nos": g["shot_nos"]})
            continue
        # 逐镜站位落库（按 shot_no 匹配，字符串小数号兼容）
        by_no = {str(x.get("shot_no")): x for x in (data.get("shots") or []) if isinstance(x, dict)}
        for r in g["rows"]:
            m = _meta_of(r)
            s = by_no.get(str(m.get("shot_no"))) or {}
            blocking = {"space": space, "chars": {str(k): str(v) for k, v in (s.get("chars") or {}).items()},
                        "moves": (s.get("moves") or "").strip(), "seg": g["seg"]}
            await pool.execute(
                "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
                r["id"], json.dumps({"blocking": blocking}, ensure_ascii=False))
        # 双字段分段冻结（2026-07-17）：用户改过的段沿用，未冻结段随重规划刷新，重拼全文
        from .prompt_fields import compose

        _p = prev or {}
        entry: dict[str, Any] = {
            "seg": g["seg"], "scene": g["scene"], "shot_nos": g["shot_nos"],
            "space": space, "anchors": anchors,
            "empty_desc": empty_desc, "sheet_desc": sheet_desc,
            "empty_refs": stages["empty_refs"], "sheet_refs": stages["sheet_refs"],
            # 场景没变则沿用已生成的图（重规划不作废人工确认过的图）
            "empty_url": _p.get("empty_url"), "sheet_url": _p.get("sheet_url"),
        }
        for stage in ("empty", "sheet"):  # 两阶段的双字段冻结逻辑同构
            u, a = stages[f"{stage}_user"], stages[f"{stage}_anchor"]
            if _p.get(f"{stage}_prompt_user_edited") and _p.get(f"{stage}_prompt_user"):
                u = _p[f"{stage}_prompt_user"]
            if _p.get(f"{stage}_prompt_anchor_edited") and _p.get(f"{stage}_prompt_anchor"):
                a = _p[f"{stage}_prompt_anchor"]
            entry[f"{stage}_prompt"] = compose(u, a)
            entry[f"{stage}_prompt_user"], entry[f"{stage}_prompt_anchor"] = u, a
            entry[f"{stage}_prompt_user_edited"] = bool(_p.get(f"{stage}_prompt_user_edited"))
            entry[f"{stage}_prompt_anchor_edited"] = bool(_p.get(f"{stage}_prompt_anchor_edited"))
        flow.stamp_validity(entry, src, _BLOCKING_TTL_H)
        entries.append(entry)
        planned.append(g["seg"])
    # 落库前按最新库内值补回场景图产物：上面的 old 是本次规划开始时的快照，逐组 LLM 规划
    # 要跑好几分钟，期间落地的场景图（gen_scene_sheet / gen_scene_sheets_group 回写的
    # sheet_url）不在快照里，直接整数组写回会把它们抹掉——用户表现为"图明明生成了，
    # 场景卡还是空的"。规划本身从不产出 sheet_url，live 值恒优先。
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "SELECT meta FROM content_nodes WHERE id=$1 FOR UPDATE", chapter_id)
        live = {int(e.get("seg") or 0): e
                for e in ((_meta_of(row).get("scene_blocking") or {}).get("groups") or [])} \
            if row else {}
        for e in entries:
            cur = live.get(int(e.get("seg") or 0)) or {}
            for k in ("empty_url", "sheet_url", "empty_versions", "sheet_versions"):
                if cur.get(k):
                    e[k] = cur[k]
        await conn.execute(
            "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
            chapter_id, json.dumps({"scene_blocking": {"groups": entries, "at": flow.now_iso()}},
                                   ensure_ascii=False))
    if planned:
        log.info("章 %s 场景空间规划: %d 组（规划 %s / 缓存命中 %s）",
                 chapter_id, len(groups), planned, skipped or "无")
    return {"groups": len(groups), "planned": planned, "skipped": skipped}
