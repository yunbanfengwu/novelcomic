"""Episode story -> variable beat count -> one integer-duration supercut.

This is the chapter-15 experiment: unlike ``episode_adaptive`` it never splits
the story into groups.  The model chooses the useful key pictures and the
service converts that count to a Seedance-supported integer duration at the
measured density of fifteen cuts per five seconds.
"""
import math
from typing import Any

import asyncpg

from .. import llm
from .episode_flash import (_clock, _identity_anchor, _jsonb, _validate_beats,
                            default_refs, prompt_context)

MODE_ADAPTIVE_DURATION = "adaptive_duration"
# This mode is specifically the control experiment for crossing the measured
# 15-cuts/5s threshold.  Requiring at least 16 makes the duration formula
# observable instead of accidentally producing another fixed five-second run.
MIN_BEATS = 16
MAX_BEATS = 45
MIN_DURATION_S = 4
MAX_DURATION_S = 15
CUTS_PER_5_SECONDS = 15


def duration_for_beats(count: int) -> int:
    """Return the integer duration that keeps density at <=15 cuts per 5s."""
    if not MIN_BEATS <= count <= MAX_BEATS:
        raise RuntimeError(
            f"单条母带关键切换必须为{MIN_BEATS}至{MAX_BEATS}次，实际为{count}次")
    duration_s = max(
        MIN_DURATION_S, math.ceil(count * 5 / CUTS_PER_5_SECONDS))
    if duration_s > MAX_DURATION_S:
        raise RuntimeError(
            f"{count}次关键切换需要{duration_s}秒，超过单条视频{MAX_DURATION_S}秒上限")
    return duration_s


def validate_beats(raw: Any, source: str,
                   allowed_characters: set[str]) -> list[dict[str, Any]]:
    """Validate a model-selected beat list without forcing a preset count."""
    beats = _validate_beats(
        raw, source, allowed_characters, expected_count=None)
    if not MIN_BEATS <= len(beats) <= MAX_BEATS:
        raise RuntimeError(
            f"模型选择了{len(beats)}次关键切换；单条实验应在{MIN_BEATS}至{MAX_BEATS}次之间")
    return beats


def _prompt_context(project: asyncpg.Record,
                    refs: list[dict[str, Any]]) -> str:
    """单一实现在 episode_flash.prompt_context（整条视频模式）。"""
    return prompt_context(project, refs, cross_group=False)


def _build_prompt(project: asyncpg.Record, chapter: asyncpg.Record,
                  beats: list[dict[str, Any]], refs: list[dict[str, Any]],
                  source_minutes: int, duration_s: int) -> str:
    ref_token = {r["name"]: f"@图片{i}" for i, r in enumerate(refs, 1)}
    lines: list[str] = []
    for beat in beats:
        cast = "、".join(
            f"{name}{ref_token[name]}" for name in beat.get("characters", [])
            if name in ref_token)
        scene_ref = next((
            f"{r['name']}{ref_token[r['name']]}" for r in refs
            if r["kind"] == "scene"
            and (r["name"] in str(beat.get("scene") or "")
                 or r["name"] in str(beat.get("picture") or ""))), "")
        anchors = "、".join(part for part in (cast, scene_ref) if part)
        marker = (
            f"【原片{_clock(float(beat['source_start_s']))}-"
            f"{_clock(float(beat['source_end_s']))}｜"
            f"成片{float(beat['output_start_s']):.2f}-"
            f"{float(beat['output_end_s']):.2f}秒｜"
            f"关键画面{beat['no']}｜{beat.get('shot_size') or '中景'}】")
        lines.append(
            marker + ((anchors + "，") if anchors else "") + str(beat["picture"]))

    intro = (
        f"《{project['title']}》第{chapter['seq']}集《{chapter['title']}》。"
        f"这是约{source_minutes}分钟剧情压缩成的同一条、不可拆组的超级加速视频，"
        f"共{len(beats)}次关键画面切换，成片时长严格为整数{duration_s}秒，输出480p。"
        f"时长按每15次切换需要5秒的稳定容量计算；本次不得仍强制压成5秒，也不得拆成多条视频。"
        "请按下列原片与成片时间标记，从开场到结局依次展示全部关键画面。"
        "每个画面清晰成立后立即硬切，形成高速翻动连环画的感觉；"
        "不要求动作实时连拍，不使用变形、叠化或补间伪装切换。"
        "不得漏画面、调序、重复，不得添加本章摘要与正文之外的新主线、目标、势力、信号源或具名核心角色。")
    return intro + _prompt_context(project, refs) + "\n" + "\n".join(lines)


async def distill(pool: asyncpg.Pool, project: asyncpg.Record,
                  chapter: asyncpg.Record, *, source_minutes: int = 6) -> dict[str, Any]:
    """Build one variable-duration prompt for the chapter-15 experiment."""
    body = await pool.fetchval(
        "SELECT content FROM content_bodies WHERE node_id=$1 ORDER BY version DESC LIMIT 1",
        chapter["id"],
    ) or ""
    source = f"{chapter['summary'] or ''}\n{body}".strip()
    all_elements = await pool.fetch(
        "SELECT name,kind,brief,meta FROM content_elements "
        "WHERE project_id=$1 ORDER BY id LIMIT 100",
        project["id"])
    elements = [r for r in all_elements if r["name"] and r["name"] in source]
    allowed_characters = {
        r["name"] for r in elements if r["kind"] == "character"}
    element_text = "；".join(_identity_anchor(r) for r in elements)

    system = f"""你是影视预演剪辑导演。请先阅读完整本集，再自行判断真正需要多少个可辨认的关键画面。
规则：
1. 不预设15个或20个，不为凑数拆动作，也不因5秒而删掉必要事件。根据实际剧情输出{MIN_BEATS}至{MAX_BEATS}个关键画面；允许超过15个。
2. 全部关键画面将生成同一条视频，不分组。必须按本章因果顺序覆盖建立、升级、转折、高潮和结果。
3. 每个beat是一张单帧就能读懂的关键场景、动作峰值或动作结果。相邻画面应有明确变化，但角色身份、服装/伤势/武器状态、场景方向和破坏状态必须可接续。
4. picture写清谁、在哪里、做什么和可见结果；不写对白、字幕、旁白、抽象心理、运镜或转场。
5. 主要角色、场景、世界观与画风只服从本章摘要、正文和核心要素。不得新增主线、核心目标、势力、信号源或具名核心角色，不得改写结局。
6. characters只列核心要素中真实出镜的角色全名。未绑定的敌人、盟友、守卫、首领和路人不列入characters，只能是远景、背影或剪影。
7. evidence从摘要或正文原样复制4至40个连续字符。只输出JSON：
{{"beats":[{{"stage":"建立","scene":"地点/时段","shot_size":"全景","picture":"关键画面","characters":["角色"],"evidence":"原文"}}]}}"""
    user = (
        f"【项目】{project['title']}\n【本集】第{chapter['seq']}集《{chapter['title']}》\n"
        f"【目标原片时长】约{source_minutes}分钟\n【本集摘要】{chapter['summary'] or ''}\n"
        f"【本集正文】{body[:14000] or '（暂无正文，以摘要为唯一剧情依据）'}\n"
        f"【正文命中的核心要素】{element_text or '（无）'}")

    last_error = ""
    for attempt in range(3):
        retry = (
            f"\n\n上一版未通过硬校验：{last_error}。请重新阅读剧情并输出完整JSON；"
            f"关键画面数必须在{MIN_BEATS}至{MAX_BEATS}之间，但不要固定成15或20。"
            if last_error else "")
        data = await llm.chat_json(
            system, user + retry, temperature=0.25, max_tokens=9000)
        try:
            beats = validate_beats(
                data.get("beats") if isinstance(data, dict) else data,
                source, allowed_characters)
            break
        except RuntimeError as exc:
            last_error = str(exc)
            if attempt == 2:
                raise

    duration_s = duration_for_beats(len(beats))
    source_total_s = source_minutes * 60
    for index, beat in enumerate(beats):
        beat.update({
            "source_start_s": round(index * source_total_s / len(beats), 2),
            "source_end_s": round((index + 1) * source_total_s / len(beats), 2),
            "output_start_s": round(index * duration_s / len(beats), 3),
            "output_end_s": round((index + 1) * duration_s / len(beats), 3),
        })

    appearing_characters = {
        name for beat in beats for name in beat.get("characters", [])}
    # Keep @图片 numbering stable between chapters and retries.
    required_characters = [
        r["name"] for r in elements
        if r["kind"] == "character" and r["name"] in appearing_characters]
    allowed_scenes = [r["name"] for r in elements if r["kind"] == "scene"]
    required_scenes = list(dict.fromkeys(
        name for beat in beats for name in allowed_scenes
        if name in str(beat.get("scene") or "")
        or name in str(beat.get("picture") or "")))
    refs = await default_refs(
        pool, project["id"], source, required_characters, required_scenes)
    if not refs:
        raise RuntimeError("本章未命中已生成的角色或场景设定图，请先生成至少一张核心要素图")

    prompt = _build_prompt(
        project, chapter, beats, refs, source_minutes, duration_s)
    return {
        "mode": MODE_ADAPTIVE_DURATION,
        "prompt": prompt,
        "beats": beats,
        "refs": refs,
        "source_minutes": source_minutes,
        "duration_s": duration_s,
        "shot_count": len(beats),
        "resolution": "480p",
    }
