"""先导预告片（2026-07-17）：LLM 蒸馏全剧 5 个关键节点（开端→结局）→ 装配 15s 硬切
蒙太奇提示词 → Seedance 一条预告片（每镜约 3 秒、镜间硬切、无对白无字幕）。

范式即调研定稿的 previz（动态分镜预演）/ recap montage（概要蒙太奇）：
「15 秒内切 3-6 个镜头」正是 Seedance 2.0 多镜头叙事引擎的量级；主角一致性不指望
模型自己记脸——靠 @设定图[主角] 双锚（reference_image + 引用句织入正文，media 层解析）。
每镜标景别+时长、通篇硬切禁叠化禁一镜到底：切点可预测，后续抽帧才有干净的镜头边界。
"""
import json
from typing import Any

import asyncpg

from .. import llm
from ..api.app_config import get_gen_config
from ..knowledge import style_anchor
from .character_context import roster_inline

# 每镜时长与镜数固定（15s / 5 镜 / 每镜 3s）：Seedance 2.0 duration 上限恰为 15
SHOTS = 5
TOTAL_S = 15


def _cfg(project: asyncpg.Record) -> dict[str, Any]:
    c = project["config"]
    return c if isinstance(c, dict) else json.loads(c or "{}")


async def _virtual_clause(project: asyncpg.Record) -> str:
    """虚拟角色约束（预告片全片版）：项目三态覆盖优先，follow 才跟随系统开关。
    与设定图同一原则（见 element_sheet）：只压“别像真人”，媒介 2D/3D 交给画风锚词。"""
    ov = _cfg(project).get("realistic_character") or "follow"
    realistic = ov == "enable" if ov in ("enable", "disable") else \
        bool((await get_gen_config()).get("realistic_character", True))
    if realistic:
        return ""
    return ("全片角色均为原创虚拟拟人形象，绝非任何真实人物：五官经艺术化、理想化设计，"
            "一眼可辨为虚构角色；画面媒介与质感严格由画面风格决定，绝不呈现为真人实拍。")


def _world_guard(project: asyncpg.Record) -> str:
    """预告片版世界观锚：era 手填值最强；缺省用通用守则——不引用画风原文
    （画风 content 常含具体场景词，如新海诚的“都市铁道便利店”，会污染古装/异世界剧）。"""
    era = (_cfg(project).get("era") or "").strip()
    if era:
        return f"须严格贴合本剧设定的年代与世界观：{era}；绝不出现与之冲突的现代物或异域文化元素。"
    return "全片须贴合原著的年代与世界观，绝不出现与故事背景冲突的现代物品、服饰或建筑。"


async def default_character_refs(pool: asyncpg.Pool, project_id: int) -> list[dict[str, str]]:
    """默认参考图 = 前几位已有设定图的角色（主角优先=按 id 序）。
    ≤3 张：Seedance 参考图上限 4，留一槽给用户手加场景/道具。
    与 episode_flash.default_refs 同名不同义（那边硬校验缺图报错、绑定备案身份），
    2026-07-31 改名消歧，勿再合并。"""
    rows = await pool.fetch(
        "SELECT name, meta->>'sheet_url' AS url FROM content_elements "
        "WHERE project_id=$1 AND kind='character' AND meta->>'sheet_url' IS NOT NULL "
        "ORDER BY id LIMIT 3", project_id)
    return [{"name": r["name"], "kind": "character", "url": r["url"]} for r in rows]


def _assemble(project: asyncpg.Record, beats: list[dict[str, Any]],
              style: str, world: str, virtual: str, ref_names: list[str]) -> str:
    """固定骨架 + LLM 节点：硬约束（硬切/无对白/禁一镜到底）由代码钉死，不交给 LLM 复述。"""
    head = f"《{project['title']}》先导预告片：概要蒙太奇，按时间顺序呈现主角从开端到结局的命运变化。"
    anchor = f"画面风格：{style}。" if style else ""
    ref = ""
    if ref_names:
        marks = "、".join(f"@设定图[{n}]" for n in ref_names)
        ref = f"角色造型与外貌全片以 {marks} 为准（同一人物贯穿全片，服装可随剧情阶段变化，脸不变）。"
    rules = (
        "全片无对白、无旁白、无字幕、无任何文字与水印；纯视觉动作叙事。"
        f"共 {SHOTS} 个镜头、总长 {TOTAL_S} 秒，每镜约 3 秒；"
        "镜头之间一律硬切（直切），禁止叠化、淡入淡出、慢动作，禁止一镜到底。")
    lines = "\n".join(
        f"【镜头{b.get('no', i + 1)}｜{b.get('shot_size', '全景')}｜3秒】"
        f"（{b.get('stage', '')}）{b.get('picture', '')}"
        for i, b in enumerate(beats))
    return f"{head}{anchor}{world}{virtual}{rules}{ref}\n{lines}"


async def distill_prompt(pool: asyncpg.Pool, project: asyncpg.Record) -> dict[str, Any]:
    """蒸馏预告片提示词：LLM 出 5 个跨全剧节点（首尾强对比），代码装配硬约束骨架。
    不落库——前端回填编辑框，保存/生成时才持久化。返回 {prompt, refs}。"""
    pid = project["id"]
    chars = await pool.fetch(
        "SELECT name, brief FROM content_elements WHERE project_id=$1 AND kind='character' "
        "ORDER BY id LIMIT 6", pid)
    char_lines = "；".join(roster_inline(c["name"], c["brief"]) for c in chars) or "（未建）"
    system = (
        f"你是短剧预告片导演。据小说【梗概】【主线】【大纲】【主要角色】，提炼 {SHOTS} 个跨越全剧的"
        "关键画面节点（开端→发展→转折→高潮→结局），用于一条 15 秒先导预告片（每镜约 3 秒、镜间硬切）。要求：\n"
        "① 5 镜连起来讲清主角的命运弧光——首镜与尾镜必须形成强烈的处境对比"
        "（如开端落魄潦倒/结局身居高位），观众不靠台词就能看懂“从哪来、到哪去”；\n"
        "② 每镜只写画面：谁+在哪+做什么+氛围光色，25-50 字；具体可拍，"
        "禁止“命运”“成长”等不可拍的抽象概念；\n"
        "③ 全片无对白无字幕：不写任何文字/旁白/台词；不写镜头运动与相机术语；\n"
        "④ 主角每镜都以全名指代；只用给出的角色，不得虚构新角色；配角可少量出现；\n"
        "⑤ 景别从「远景/全景/中景/近景/特写」中选，5 镜景别要有变化；\n"
        '只输出 JSON：{"beats":[{"no":1,"stage":"开端","shot_size":"全景","picture":"…"}]}，恰好 5 项。'
    )
    user = (
        f"【标题】{project['title']}\n【梗概】{project['synopsis'] or '（无）'}\n"
        f"【主线】{project['storyline'] or '（无）'}\n"
        f"【大纲】{(project['outline_md'] or '（无）')[:1500]}\n【主要角色】{char_lines}"
    )
    data = await llm.chat_json(system, user, temperature=0.6, max_tokens=2000)
    beats = (data.get("beats") if isinstance(data, dict) else data) or []
    if not isinstance(beats, list) or not beats:
        raise RuntimeError("预告片节点蒸馏失败：LLM 未返回 beats 列表")
    beats = beats[:SHOTS]
    refs = await default_character_refs(pool, pid)
    prompt = _assemble(project, beats, await style_anchor(pool, project["art_style"] or ""),
                       _world_guard(project), await _virtual_clause(project),
                       [r["name"] for r in refs])
    return {"prompt": prompt, "refs": refs}


async def rewrite_prompt(project: asyncpg.Record, instruction: str, current: str) -> str:
    """AI 按修改要求改写预告片提示词（同步返回，不落库）。硬约束随系统提示钉死。"""
    system = (
        "你是短剧预告片提示词工程师。修改一条 15 秒先导预告片的生视频提示词，"
        "只输出最终提示词本身，不要任何解释或前后缀。硬约束：\n"
        f"① 保持 {SHOTS} 镜结构与【镜头N｜景别｜3秒】行格式，总长 {TOTAL_S} 秒；\n"
        "② 保留“镜间硬切、禁止叠化/慢动作/一镜到底、无对白无旁白无字幕无文字”的规则句；\n"
        "③ 保留画面风格锚词与 @设定图[名] 引用（一字不改地保留这些引用标记）；\n"
        "④ 以下方小说事实为依据改写，中文为主。"
    )
    user = (
        f"【标题】{project['title']}\n【梗概】{project['synopsis'] or '（无）'}\n"
        f"【主线】{project['storyline'] or '（无）'}\n\n"
        f"【当前提示词】\n{current or '（尚无）'}\n\n【修改要求】\n{instruction}"
    )
    out = (await llm.chat_text(system, user, temperature=0.5)).strip()
    if not out:
        raise RuntimeError("AI 返回为空，请重试")
    return out
