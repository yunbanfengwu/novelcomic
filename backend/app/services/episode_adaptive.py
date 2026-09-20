"""Episode story -> LLM-sized groups (<=15 beats each) -> variable-duration prompts.

This is deliberately a separate experiment from the three fixed 5-second modes in
``episode_flash``.  The model chooses both the number of visual beats and the
narrative boundaries.  The service then applies hard capacity checks and derives
an integer Seedance duration for every group.
"""
import math
from itertools import combinations
from typing import Any

import asyncpg

from .. import llm
from .episode_flash import (_clock, _identity_anchor, _jsonb, _validate_beats,
                            default_refs, prompt_context)

MODE_ADAPTIVE_GROUPS = "adaptive_groups"
MAX_GROUP_BEATS = 15
MIN_TOTAL_BEATS = 8
MAX_TOTAL_BEATS = 45
MIN_GROUP_DURATION_S = 4
CUTS_PER_SECOND = 3


def duration_for_beats(count: int) -> int:
    """Keep the measured stable density at no more than three cuts per second."""
    if not 1 <= count <= MAX_GROUP_BEATS:
        raise RuntimeError(f"单组关键切换必须为1至{MAX_GROUP_BEATS}次，实际为{count}次")
    return max(MIN_GROUP_DURATION_S, math.ceil(count / CUTS_PER_SECOND))


def validate_groups(raw: Any, source: str, allowed_characters: set[str]) -> list[dict[str, Any]]:
    """Validate beats and retain the best LLM-proposed boundaries under the hard cap.

    The planner sometimes treats every narrative stage as a separate 2-beat
    group.  For unattended operation we keep its beat order, stage labels and
    candidate boundaries, but deterministically coalesce/rebalance them to the
    minimum number of groups required by the 15-beat provider capacity.
    """
    if not isinstance(raw, list) or not raw:
        raise RuntimeError("模型没有返回有效的剧情分组")
    if len(raw) > 6:
        raise RuntimeError(f"模型返回的候选剧情段过多：最多6段，实际{len(raw)}段")

    candidate_groups: list[dict[str, Any]] = []
    flat_beats: list[dict[str, Any]] = []
    raw_boundaries: set[int] = set()
    for group_no, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise RuntimeError(f"第{group_no}组格式错误")
        title = str(item.get("title") or "").strip()
        if not title:
            raise RuntimeError(f"第{group_no}组缺少剧情标题")
        raw_beats = item.get("beats")
        count = len(raw_beats) if isinstance(raw_beats, list) else 0
        if not 1 <= count <= MAX_TOTAL_BEATS:
            raise RuntimeError(f"第{group_no}个候选剧情段没有有效关键画面")
        beats = _validate_beats(raw_beats, source, allowed_characters, expected_count=None)
        for beat in beats:
            beat["_candidate_group_no"] = group_no
            flat_beats.append(beat)
        raw_boundaries.add(len(flat_beats))
        candidate_groups.append({
            "no": group_no,
            "title": title,
            "continuity_in": str(item.get("continuity_in") or "").strip(),
            "continuity_out": str(item.get("continuity_out") or "").strip(),
            "beats": beats,
        })

    total = len(flat_beats)
    raw_boundaries.discard(total)
    if not MIN_TOTAL_BEATS <= total <= MAX_TOTAL_BEATS:
        raise RuntimeError(
            f"整集实际关键切换为{total}次；6至10分钟剧情应在{MIN_TOTAL_BEATS}至{MAX_TOTAL_BEATS}次之间")

    expected_groups = math.ceil(total / MAX_GROUP_BEATS)
    stage_boundaries = {
        index for index in range(1, total)
        if (flat_beats[index - 1].get("stage") != flat_beats[index].get("stage")
            or flat_beats[index - 1].get("scene") != flat_beats[index].get("scene"))}
    if expected_groups == 1:
        cuts: tuple[int, ...] = ()
    else:
        valid_positions = range(5, total - 4)
        target = total / expected_groups
        best: tuple[float, tuple[int, ...]] | None = None
        for proposed in combinations(valid_positions, expected_groups - 1):
            sizes = [b - a for a, b in zip((0, *proposed), (*proposed, total))]
            if max(sizes) > MAX_GROUP_BEATS or min(sizes) < 5:
                continue
            score = sum(abs(size - target) * 10 for size in sizes)
            # Prefer boundaries explicitly proposed by the LLM, then its stage/
            # scene changes.  Balance only wins when a candidate would violate
            # stable capacity or create a tiny tail group.
            score += sum(0 if cut in raw_boundaries else 2 if cut in stage_boundaries else 6
                         for cut in proposed)
            if best is None or score < best[0]:
                best = (score, proposed)
        if best is None:
            raise RuntimeError(f"{total}次切换无法在每组最多{MAX_GROUP_BEATS}次的条件下稳定分组")
        cuts = best[1]

    groups: list[dict[str, Any]] = []
    for group_no, (start, end) in enumerate(zip((0, *cuts), (*cuts, total)), 1):
        beats = flat_beats[start:end]
        candidate_nos = list(dict.fromkeys(
            int(beat["_candidate_group_no"]) for beat in beats))
        source_groups = [candidate_groups[no - 1] for no in candidate_nos]
        titles = list(dict.fromkeys(str(group["title"]) for group in source_groups))
        for group_beat_no, beat in enumerate(beats, 1):
            beat.pop("_candidate_group_no", None)
            beat.update({"no": start + group_beat_no, "group_no": group_no,
                         "group_beat_no": group_beat_no})
        groups.append({
            "no": group_no,
            "title": " / ".join(titles[:2]),
            "continuity_in": source_groups[0].get("continuity_in") or "",
            "continuity_out": source_groups[-1].get("continuity_out") or "",
            "boundary_reason": (
                "保留模型建议的剧情边界" if not cuts or all(cut in raw_boundaries for cut in cuts)
                else "在模型阶段/场景边界中按15次容量均衡"),
            "beats": beats,
        })
    return groups


def _prompt_context(project: asyncpg.Record, refs: list[dict[str, Any]]) -> str:
    """单一实现在 episode_flash.prompt_context（分组模式：连续性一句强调跨组一致）。"""
    return prompt_context(project, refs, cross_group=True)


def _build_group_prompt(project: asyncpg.Record, chapter: asyncpg.Record,
                        group: dict[str, Any], refs: list[dict[str, Any]],
                        source_minutes: int, group_count: int) -> str:
    beats = group["beats"]
    duration_s = int(group["duration_s"])
    ref_token = {r["name"]: f"@图片{i}" for i, r in enumerate(refs, 1)}
    lines: list[str] = []
    for beat in beats:
        cast = "、".join(
            f"{name}{ref_token[name]}" for name in beat.get("characters", [])
            if name in ref_token)
        scene_ref = next((
            f"{r['name']}{ref_token[r['name']]}" for r in refs if r["kind"] == "scene"
            and (r["name"] in str(beat.get("scene") or "")
                 or r["name"] in str(beat.get("picture") or ""))), "")
        anchors = "、".join(part for part in (cast, scene_ref) if part)
        local_start = float(beat["group_output_start_s"])
        local_end = float(beat["group_output_end_s"])
        marker = (
            f"【原片{_clock(float(beat['source_start_s']))}-{_clock(float(beat['source_end_s']))}｜"
            f"本组{local_start:.2f}-{local_end:.2f}秒｜关键画面{beat['group_beat_no']}｜"
            f"{beat.get('shot_size') or '中景'}】")
        lines.append(marker + ((anchors + "，") if anchors else "") + str(beat["picture"]))

    intro = (
        f"《{project['title']}》第{chapter['seq']}集，第{group['no']}/{group_count}组“{group['title']}”。"
        f"整集约{source_minutes}分钟，本组包含{len(beats)}次关键画面切换，输出{duration_s}秒。"
        f"请把以下关键画面按标记顺序做成超级加速、连环画翻页式视频：每个画面清晰成立后立即硬切，"
        "不要求动作实时连拍，不使用变形、叠化或补间来伪装切换；不得漏画面、调序或添加正文以外的新主线。"
        f"本组入口连续性：{group.get('continuity_in') or '承接上一组或本集开场状态'}。"
        f"本组出口连续性：{group.get('continuity_out') or '保持最后画面的角色、场景和事件状态'}。")
    return intro + _prompt_context(project, refs) + "\n" + "\n".join(lines)


async def distill(pool: asyncpg.Pool, project: asyncpg.Record,
                  chapter: asyncpg.Record, *, source_minutes: int = 6) -> dict[str, Any]:
    body = await pool.fetchval(
        "SELECT content FROM content_bodies WHERE node_id=$1 ORDER BY version DESC LIMIT 1",
        chapter["id"],
    ) or ""
    source = f"{chapter['summary'] or ''}\n{body}".strip()
    all_elements = await pool.fetch(
        "SELECT name,kind,brief,meta FROM content_elements WHERE project_id=$1 ORDER BY id LIMIT 100",
        project["id"])
    elements = [r for r in all_elements if r["name"] and r["name"] in source]
    allowed_characters = {r["name"] for r in elements if r["kind"] == "character"}
    element_text = "；".join(_identity_anchor(r) for r in elements)

    system = f"""你是影视预演剪辑导演。请先判断本集真正需要多少个可辨认的关键画面，再按自然剧情转折分组。
规则：
1. 不预设20个，不为凑数拆同一个动作；6至10分钟剧情应按正文中不同的场景、行动峰值和结果保留{MIN_TOTAL_BEATS}至30个决定性画面，不得把多个独立可见事件粗暴合并。
2. 只有总画面超过{MAX_GROUP_BEATS}个时才拆组：1至{MAX_GROUP_BEATS}个必须为1组，16至30个必须为2组，31至45个必须为3组。每组绝对不得超过{MAX_GROUP_BEATS}个，并尽量均衡，禁止15+1式尾组。
3. 在上述最少必要组数内，由你根据最自然的剧情转折选择边界，而不是平均切字；全片覆盖建立、升级、转折、结果，顺序不得改变。
4. 每组写continuity_in与continuity_out，明确人物服装/伤势/道具/位置、场景破坏、水流方向、时段和光线，以便下一组接续。
5. 每个beat是一张单帧就能读懂的关键场景或动作结果，picture写谁、在哪里、做什么及可见结果；不写运镜、对白、字幕、旁白或抽象心理。
6. 主要角色、场景、世界观和风格服从本章摘要、正文与核心要素；可以补充无名背景动作，不新增具名核心角色，不改主线结局。
7. characters只列核心要素中真实出镜的角色全名。未绑定的敌人、盟友和路人不列入characters。
8. evidence从摘要或正文原样复制4至40个连续字符。只输出JSON：
{{"groups":[{{"title":"剧情阶段","continuity_in":"入口连续性","continuity_out":"出口连续性","beats":[{{"stage":"建立","scene":"地点/时段","shot_size":"全景","picture":"关键画面","characters":["角色"],"evidence":"原文"}}]}}]}}"""
    user = (
        f"【项目】{project['title']}\n【本集】第{chapter['seq']}集《{chapter['title']}》\n"
        f"【目标原片时长】约{source_minutes}分钟\n【本集摘要】{chapter['summary'] or ''}\n"
        f"【本集正文】{body[:14000] or '（暂无正文，以摘要为唯一剧情依据）'}\n"
        f"【正文命中的核心要素】{element_text or '（无）'}")

    last_error = ""
    for attempt in range(3):
        retry = (f"\n\n上一版未通过硬校验：{last_error}。请重新判断并输出完整JSON；"
                 f"任何一组都不得超过{MAX_GROUP_BEATS}个。" if last_error else "")
        data = await llm.chat_json(system, user + retry, temperature=0.25, max_tokens=8000)
        try:
            groups = validate_groups(
                data.get("groups") if isinstance(data, dict) else data,
                source, allowed_characters)
            break
        except RuntimeError as exc:
            last_error = str(exc)
            if attempt == 2:
                raise

    flat_beats = [beat for group in groups for beat in group["beats"]]
    source_total_s = source_minutes * 60
    output_cursor = 0.0
    flat_cursor = 0
    for group in groups:
        count = len(group["beats"])
        duration_s = duration_for_beats(count)
        group["beat_count"] = count
        group["duration_s"] = duration_s
        group["output_start_s"] = output_cursor
        group["output_end_s"] = output_cursor + duration_s
        for local_index, beat in enumerate(group["beats"]):
            source_start = flat_cursor * source_total_s / len(flat_beats)
            source_end = (flat_cursor + 1) * source_total_s / len(flat_beats)
            local_start = local_index * duration_s / count
            local_end = (local_index + 1) * duration_s / count
            beat.update({
                "source_start_s": round(source_start, 2),
                "source_end_s": round(source_end, 2),
                "group_output_start_s": round(local_start, 3),
                "group_output_end_s": round(local_end, 3),
                "output_start_s": round(output_cursor + local_start, 3),
                "output_end_s": round(output_cursor + local_end, 3),
            })
            flat_cursor += 1
        output_cursor += duration_s

    appearing_characters = {
        name for beat in flat_beats for name in beat.get("characters", [])}
    # Element order is stable across every experiment/group, so @图片 numbering
    # cannot drift merely because the planner mentions a character earlier.
    required_characters = [
        r["name"] for r in elements
        if r["kind"] == "character" and r["name"] in appearing_characters]
    allowed_scenes = [r["name"] for r in elements if r["kind"] == "scene"]
    required_scenes = list(dict.fromkeys(
        name for beat in flat_beats for name in allowed_scenes
        if name in str(beat.get("scene") or "") or name in str(beat.get("picture") or "")))
    refs = await default_refs(
        pool, project["id"], source, required_characters, required_scenes)
    if not refs:
        raise RuntimeError("本章未命中已生成的角色或场景设定图，请先生成至少一张核心要素图")

    for group in groups:
        group["prompt"] = _build_group_prompt(
            project, chapter, group, refs, source_minutes, len(groups))
    overall_prompt = (
        f"《{project['title']}》第{chapter['seq']}集自适应分组母带计划："
        f"模型按实际剧情选择{len(flat_beats)}次关键切换，自动分成{len(groups)}组；"
        f"每组硬上限{MAX_GROUP_BEATS}次，按每秒最多{CUTS_PER_SECOND}次计算，"
        f"最终总时长{int(output_cursor)}秒。各组使用完全相同的@图片编号与画风锚点，"
        "先分别生成并永久保留，再按顺序无缝拼接。\n\n" +
        "\n\n".join(group["prompt"] for group in groups))
    return {
        "mode": MODE_ADAPTIVE_GROUPS,
        "prompt": overall_prompt,
        "beats": flat_beats,
        "groups": groups,
        "refs": refs,
        "source_minutes": source_minutes,
        "duration_s": int(output_cursor),
        "shot_count": len(flat_beats),
        "resolution": "480p",
        "max_group_beats": MAX_GROUP_BEATS,
    }
