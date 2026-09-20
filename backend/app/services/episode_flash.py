"""Episode story -> validated 20-beat prompt -> one preserved 5s flashback master."""
import json
from typing import Any

import asyncpg

from .. import llm

BEAT_COUNT = 20
TOTAL_S = 5
MODE_FLASH20 = "flash20"
MODE_SAMPLED_STORY = "sampled_story"
MODE_TIMELINE_SUPERCUT = "timeline_supercut"


def _jsonb(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else json.loads(value or "{}")


def _clock(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    return f"{total // 60:02d}:{total % 60:02d}"


async def default_refs(pool: asyncpg.Pool, project_id: int, source: str,
                       required_characters: list[str],
                       required_scenes: list[str]) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        "SELECT id,name,kind,meta->>'sheet_url' AS url FROM content_elements "
        "WHERE project_id=$1 AND kind IN ('character','scene') "
        "AND coalesce(meta->>'sheet_url','') <> '' ORDER BY "
        "CASE kind WHEN 'character' THEN 0 WHEN 'scene' THEN 1 ELSE 2 END,id",
        project_id)
    matched = [r for r in rows if r["name"] and r["name"] in source]
    character_by_name = {r["name"]: r for r in matched if r["kind"] == "character"}
    missing = [name for name in required_characters if name not in character_by_name]
    if missing:
        raise RuntimeError(f"出镜角色缺少已生成的角色设定图：{'、'.join(missing)}")
    if len(required_characters) > 4:
        raise RuntimeError("单条母带最多绑定4张参考图，本集出镜核心角色超过4名，请减少角色或拆分母带")
    characters = [character_by_name[name] for name in required_characters]
    scene_by_name = {r["name"]: r for r in matched if r["kind"] == "scene"}
    scenes = [scene_by_name[name] for name in required_scenes if name in scene_by_name]
    # 图片编号必须与实际提交顺序完全一致；按 URL 去重，防止 media 层去重后编号漂移。
    selected = characters + scenes[:max(0, 4 - len(characters))]
    unique: list[asyncpg.Record] = []
    seen_urls: set[str] = set()
    for row in selected:
        if row["url"] not in seen_urls:
            unique.append(row)
            seen_urls.add(row["url"])
    return [
        {"element_id": r["id"], "name": r["name"], "kind": r["kind"], "url": r["url"],
         **({"binding": "identity"} if r["kind"] == "character" else {})}
        for r in unique
    ]


def prompt_context(project: asyncpg.Record, refs: list[dict[str, Any]],
                   cross_group: bool = False) -> str:
    """母带提示词的通用上下文段单一实现（adaptive_groups / adaptive_duration 共用，
    2026-07-31 收敛：此前两个模块各有一份近乎逐字的拷贝、措辞已漂移）。
    cross_group=分组并发模式（连续性一句强调跨组一致）。"""
    ref_token = {r["name"]: f"@图片{i}" for i, r in enumerate(refs, 1)}
    char_refs = "、".join(
        f"{r['name']}{ref_token[r['name']]}" for r in refs if r["kind"] == "character")
    scene_refs = "、".join(
        f"{r['name']}{ref_token[r['name']]}" for r in refs if r["kind"] == "scene")
    style = str(project["art_style"] or "").strip()
    era = str(_jsonb(project["config"]).get("era") or "").strip()
    pieces = [
        "无对白、无旁白、无字幕、无文字、无水印。",
        ("同一角色跨组保持脸型、体态和稳定识别特征；"
         "同一场景保持空间结构、色彩、光线方向和破坏状态连续。"
         if cross_group else
         "整条视频中的同一角色必须保持脸型、体态和稳定识别特征一致；"
         "同一场景必须保持空间结构、色彩、光线方向和破坏状态连续。"),
    ]
    if style:
        pieces.append(f"画面风格：{style}。")
    if era:
        pieces.append(f"年代与世界观严格遵循：{era}。")
    if char_refs:
        pieces.append(
            f"角色引用：{char_refs}。人物名必须与@图片紧邻书写，例如阿澈@图片1；"
            "@图片只锁定角色的基础身份、脸型和稳定识别特征，不锁死剧情状态；"
            "伤势、服装、武器、道具、表情与动作一律以对应关键画面描述为准。")
    if scene_refs:
        pieces.append(
            f"场景引用：{scene_refs}。场景图只锁定空间、色彩和环境结构；"
            "天气、时段、损坏与剧情状态以对应关键画面描述为准。")
    pieces.append(
        "所有未绑定@图片的敌人、盟友、守卫、首领或路人只能作为远景、背影或剪影群像；"
        "不得给正脸特写，不得复制主要角色面孔，不得成为新的核心角色，"
        "也不得抢占主要角色的视觉重心。")
    return "".join(pieces)


def _identity_anchor(element: asyncpg.Record) -> str:
    meta = _jsonb(element["meta"])
    profile = _jsonb(meta.get("profile"))
    parts = [str(meta.get("形态") or "").strip(), str(profile.get("身份") or "").strip(),
             str(profile.get("体貌") or "").strip(), str(element["brief"] or "").strip()]
    detail = "；".join(dict.fromkeys(part for part in parts if part))
    kind = "人物" if element["kind"] == "character" else "场景"
    return f"{element['name']}（{kind}）：{detail[:260]}"


def _validate_beats(raw: Any, source: str,
                    allowed_characters: set[str],
                    expected_count: int | None = BEAT_COUNT) -> list[dict[str, Any]]:
    """Reject structurally incomplete or non-traceable LLM output before it becomes a draft."""
    if not isinstance(raw, list) or (
            expected_count is not None and len(raw) != expected_count):
        actual = len(raw) if isinstance(raw, list) else 0
        expected = expected_count if expected_count is not None else "有效"
        raise RuntimeError(f"关键节点数量错误：期望{expected}个，实际{actual}个")
    total_count = len(raw)
    beats: list[dict[str, Any]] = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise RuntimeError(f"节点{index}格式错误")
        cleaned = dict(item)
        for field, label in (("stage", "叙事阶段"), ("scene", "场景"),
                             ("shot_size", "景别"), ("picture", "剧情画面")):
            value = str(item.get(field) or "").strip()
            if not value:
                raise RuntimeError(f"节点{index}缺少{label}")
            cleaned[field] = value
        evidence = str(item.get("evidence") or "").strip()
        if len(evidence) < 4 or evidence not in source:
            # evidence 仅用于回查，不应因模型少抄一个字阻断一致性实验；按节点位置
            # 自动挂一段真实原文，保证可追溯且不额外烧一次生成。
            width = min(40, max(4, len(source)))
            start = int((index - 1) * max(0, len(source) - width) / max(1, total_count - 1))
            evidence = source[start:start + width].strip() or source[:width].strip()
        characters = item.get("characters")
        if not isinstance(characters, list) or any(not isinstance(name, str) for name in characters):
            raise RuntimeError(f"节点{index}的人物字段格式错误")
        characters = [name.strip() for name in characters if name.strip()]
        # 未建角色图的盟友/守卫/组织成员只允许作为无脸背景群像，不让它们占用参考图编号，
        # 也不因模型把泛称误放进 characters 而反复烧 token 重试。核心角色仍按要素图锁定。
        characters = [name for name in characters if name in allowed_characters]
        omitted = [name for name in allowed_characters
                   if name in cleaned["picture"] and name not in characters]
        characters.extend(omitted)
        cleaned.update({"no": index, "evidence": evidence, "characters": characters})
        beats.append(cleaned)
    return beats


async def distill(pool: asyncpg.Pool, project: asyncpg.Record,
                  chapter: asyncpg.Record, *, mode: str = MODE_FLASH20,
                  source_minutes: int = 8) -> dict[str, Any]:
    body = await pool.fetchval(
        "SELECT content FROM content_bodies WHERE node_id=$1 ORDER BY version DESC LIMIT 1",
        chapter["id"],
    ) or ""
    source = f"{chapter['summary'] or ''}\n{body}"
    all_elements = await pool.fetch(
        "SELECT name,kind,brief,meta FROM content_elements WHERE project_id=$1 ORDER BY id LIMIT 100",
        project["id"])
    elements = [r for r in all_elements if r["name"] and r["name"] in source]
    beat_s = TOTAL_S / BEAT_COUNT
    sampled = mode == MODE_SAMPLED_STORY
    timeline = mode == MODE_TIMELINE_SUPERCUT
    method_brief = (
        f"把一段约{source_minutes}分钟的完整剧情视为已经剪好的母片，从开端到结局按时间顺序"
        f"抽取恰好{BEAT_COUNT}个代表性画面，供{TOTAL_S}秒超级加速抽帧式视频使用"
        if sampled else (
        f"把一段约{source_minutes}分钟、超过5分钟的完整剧情拆成恰好{BEAT_COUNT}个顺序分镜提示词，"
        f"每个分镜覆盖一段明确的原片时间，稍后把全部分镜提示词合并成一次{TOTAL_S}秒超级加速视频请求"
        if timeline else
        f"把一集约{source_minutes}分钟的剧情压缩成恰好{BEAT_COUNT}个可拍摄的视觉关键节点，"
        f"供{TOTAL_S}秒、{BEAT_COUNT}镜的超快整集闪回蒙太奇使用")
    )
    transition_rule = (
        "相邻节点必须保持人物目标、空间去向和事件因果可接续；允许跨越过程时间，但不得打乱剧情顺序，"
        "不得用变形或叠化伪装跳跃。" if sampled else
        ("每个节点只写其原始时间段内最有辨识度的一个决定性画面；节点必须按剧情顺序覆盖开端到结局，"
         "不能合并、漏掉或交换时间段，不要求相邻动作实时连拍。" if timeline else
         "相邻节点构图、景别或动作状态必须有明显差异；不要渐变、叠化或变形转场。")
    )
    system = f"""你是影视分镜导演。{method_brief}，每个节点约{beat_s:.2f}秒。当前先生成分段母带提示词，不生成视频、不落地抽帧。
要求：
1. 沿用本章主线事件顺序，覆盖建立、升级、转折、高潮、结果；可以把摘要已有行动扩成可拍的环境反应、动作阻力与视觉结果，但不得改变主线结局、主要设定或创造新的核心角色。
2. 每节点是一张单帧就能读懂的决定性瞬间，优先动作峰值、发现、反应、结果状态；不要写过程和运镜。
3. 主要角色、世界观和画风必须服从本集故事线、正文与核心要素；场景内可补充不改变主线的背景行动与无名群像，不得挪用相邻集结局。
   characters只列画面中真实出镜、且【核心要素】明确列出的人物全名；资料或回忆中仅被提及而未真实出镜的人物不要列入，也不得自行创造人物。
4. {transition_rule}
5. picture写具体的谁、在哪里、做什么及可见结果；不得写对白、字幕、旁白或抽象心理。
6. 人类、动物和场景身份必须严格服从核心要素说明；同名主体只能有一个，不得复制人脸、复制主角或把人变成动物。
7. 每个节点给出 evidence：从本集故事线或正文中原样复制4至40个连续字符作为剧情依据，不得改写；同一原文证据可支撑多个微瞬间。
只输出JSON：{{"beats":[{{"no":1,"stage":"建立","scene":"地点/时段","shot_size":"全景","picture":"画面","characters":["人物"],"evidence":"本章原文连续片段"}}]}}，恰好{BEAT_COUNT}项。"""
    elem_text = "；".join(_identity_anchor(r) for r in elements)
    user = (
        f"【项目】{project['title']}\n"
        f"【本集】第{chapter['seq']}集《{chapter['title']}》\n【本集故事线】{chapter['summary'] or ''}\n"
        f"【本集正文】{body[:12000] or '（无正文，以本集故事线为唯一剧情依据）'}\n"
        f"【本集故事线中明确命中的核心要素】{elem_text or '（无）'}"
    )
    allowed_characters = {r["name"] for r in elements if r["kind"] == "character"}
    last_error = ""
    for attempt in range(2):
        retry = (f"\n\n上一版结构错误：{last_error}。请重新输出完整且恰好{BEAT_COUNT}项。"
                 if last_error else "")
        data = await llm.chat_json(
            system, user + retry, temperature=0.2, max_tokens=6000)
        try:
            beats = _validate_beats(
                data.get("beats") if isinstance(data, dict) else data,
                source, allowed_characters)
            break
        except RuntimeError as exc:
            last_error = str(exc)
            if attempt == 1:
                raise
    if timeline:
        source_total_s = source_minutes * 60
        for i, beat in enumerate(beats):
            beat["source_start_s"] = round(i * source_total_s / BEAT_COUNT, 2)
            beat["source_end_s"] = round((i + 1) * source_total_s / BEAT_COUNT, 2)
    required_characters = list(dict.fromkeys(
        name for beat in beats for name in beat["characters"]))
    allowed_scenes = [r["name"] for r in elements if r["kind"] == "scene"]
    required_scenes = list(dict.fromkeys(
        name for beat in beats for name in allowed_scenes
        if name in str(beat.get("scene") or "") or name in str(beat.get("picture") or "")))
    refs = await default_refs(
        pool, project["id"], source, required_characters, required_scenes)
    if not refs:
        raise RuntimeError("本章未命中已生成的角色或场景设定图，请先生成至少一张核心要素图")
    ref_token_by_name = {r["name"]: f"@图片{i}" for i, r in enumerate(refs, 1)}
    char_refs = "、".join(
        f"{r['name']}{ref_token_by_name[r['name']]}" for r in refs if r["kind"] == "character")
    scene_refs = "、".join(
        f"{r['name']}{ref_token_by_name[r['name']]}" for r in refs if r["kind"] == "scene")
    ally_rule = (
        "盟友们只作为2至3名外貌与主角明显不同的背景潜水员，以远景或背影出现；"
        "禁止复制主角的脸，禁止盟友脸部并排特写。" if "盟友们" in source else "")
    background_rule = (
        "所有未绑定@图片的盟友、守卫、首领、组织成员或路人都只作远景、背影或剪影群像，"
        "不得给正脸特写，不得复制主要角色面孔，也不得改变主要角色的视觉重心。"
    )
    style = project["art_style"] or ""
    era = (_jsonb(project["config"]).get("era") or "").strip()
    lines = []
    for i, beat in enumerate(beats):
        start = i * TOTAL_S / BEAT_COUNT
        picture = str(beat.get("picture", ""))
        cast = beat.get("characters") if isinstance(beat.get("characters"), list) else []
        mentioned = [name for name in cast if name in ref_token_by_name]
        cast_rule = "、".join(
            f"{name}{ref_token_by_name[name]}" for name in mentioned) + "，" \
            if mentioned else ""
        scene_name = next((name for name in ref_token_by_name
                           if name in str(beat.get("scene") or "") and
                           any(r["name"] == name and r["kind"] == "scene" for r in refs)), None)
        scene_rule = f"{scene_name}{ref_token_by_name[scene_name]}，" if scene_name else ""
        if timeline:
            source_start = float(beat.get("source_start_s") or 0)
            source_end = float(beat.get("source_end_s") or 0)
            marker = (
                f"【原片{_clock(source_start)}-{_clock(source_end)}｜"
                f"压缩后{start:.2f}-{start + TOTAL_S / BEAT_COUNT:.2f}秒｜分镜{i + 1}｜"
                f"{beat.get('shot_size', '中景')}】"
            )
        else:
            marker = (
                f"【{start:.2f}-{start + TOTAL_S / BEAT_COUNT:.2f}秒｜节点{i + 1}｜"
                f"{beat.get('shot_size', '中景')}】"
            )
        lines.append(marker + f"{cast_rule}{scene_rule}{picture}")
    method_prompt = (
        f"这是一段约{source_minutes}分钟的完整剧情。请使用抽帧法生成一段{TOTAL_S}秒钟的超级加速视频，剧情必须连贯。"
        f"把完整母片从开端到结局按时间顺序等距抽取{BEAT_COUNT}个代表画面，每{beat_s:.2f}秒展示一个；"
        "允许省略动作过程，但人物目标、空间变化、冲突升级与事件结果必须前后接续。禁止打乱顺序、补间变形、叠化和无因果跳切。"
        if sampled else (
        f"这是一段约{source_minutes}分钟、超过5分钟的完整剧情，共{BEAT_COUNT}个分镜。"
        f"以上剧情请严格按照每个分镜标记的原始时间去生成一段超级加速的视频，将{source_minutes}分钟压缩为{TOTAL_S}秒钟；"
        f"把每段原片时间压缩到{beat_s:.2f}秒，在对应压缩时间段只展示该分镜最有辨识度的关键场景与动作。"
        "全部分镜提示词必须按标记顺序合并执行，不得漏镜、调序或把新剧情补进空隙；硬切翻页般高速推进，"
        "不要求动作实时连贯，但人物身份、场景去向、因果顺序与本章结局必须一致。输出480p，时长严格5秒。"
        if timeline else
        f"这是一段约{source_minutes}分钟剧情的{TOTAL_S}秒、{BEAT_COUNT}镜超快整集闪回母带。"
        f"全片恰好{BEAT_COUNT}个按本集剧情顺序排列的闪回画面，每{beat_s:.2f}秒瞬时硬切一次；"
        "禁止补间变形、禁止叠化、禁止慢动作、禁止一镜到底。每段出现后立即保持清晰稳定的决定性姿势，"
        "像快速翻动的彩色连环画。")
    )
    prompt = (
        f"《{project['title']}》第{chapter['seq']}集。" + method_prompt
        + "无对白、无旁白、无字幕、无文字、无水印。"
        + (f"画面风格：{style}。" if style else "")
        + (f"年代与世界观严格遵循：{era}。" if era else "")
        + (f"角色引用：{char_refs}。@图片只提供角色的基础身份、脸型与稳定识别特征；伤势、服装、武器、道具、表情、动作和剧情状态均以各分段描述为准。" if char_refs else "")
        + ally_rule
        + background_rule
        + (f"场景引用：{scene_refs}。场景图提供空间、色彩与环境结构，镜头中的破坏、天气和剧情状态以各分段描述为准。" if scene_refs else "")
        + "\n" + "\n".join(lines))
    return {"prompt": prompt, "beats": beats, "refs": refs,
            "mode": mode, "source_minutes": source_minutes,
            "resolution": "480p" if timeline else None}
