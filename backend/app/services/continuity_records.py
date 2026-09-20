"""把现有章节/场景组/分镜映射为 Phase 1 连续性版本，并提供生成前硬闸。"""
from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any

import asyncpg

from .continuity import validate_shot

log = logging.getLogger(__name__)

# 会让画面自相矛盾、必须拦下的连续性错误：场景硬锁被违反（同场景时间/天气/封闭性漂移），
# 以及室内动作掀掉屋顶。其余错误码属于叙事台账问题，记录但不阻断出图。
_BLOCKING_CODES = frozenset({
    "scene_hard_lock_before", "scene_hard_lock_after", "indoor_action_breaks_enclosure",
})


def _json(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else json.loads(value or "{}")


def _detect_time(text: str) -> str | None:
    pairs = (
        ("黎明", "dawn"), ("清晨", "morning"), ("早晨", "morning"),
        ("正午", "noon"), ("午后", "afternoon"), ("黄昏", "dusk"),
        ("傍晚", "dusk"), ("午夜", "midnight"), ("夜", "night"),
        ("dawn", "dawn"), ("morning", "morning"), ("noon", "noon"),
        ("afternoon", "afternoon"), ("dusk", "dusk"), ("night", "night"),
    )
    low = text.lower()
    return next((value for key, value in pairs if key in low), None)


def _detect_weather(text: str) -> str | None:
    pairs = (
        ("雷暴", "thunderstorm"), ("暴雨", "heavy_rain"), ("雨", "rain"),
        ("雪", "snow"), ("雾", "fog"), ("晴", "clear"),
        ("storm", "storm"), ("rain", "rain"), ("snow", "snow"),
        ("fog", "fog"), ("clear", "clear"),
    )
    low = text.lower()
    return next((value for key, value in pairs if key in low), None)


def _detect_enclosure(text: str) -> str | None:
    low = text.lower()
    interior = (
        "议事厅", "大厅内", "室内", "房间", "殿内", "舱内", "洞内",
        "interior", "inside", "hall interior",
    )
    exterior = (
        "露天", "室外", "户外", "广场", "码头", "云海", "天空", "街道",
        "exterior", "outdoor", "open-air",
    )
    if any(token in low for token in interior):
        return "interior"
    if any(token in low for token in exterior):
        return "exterior"
    return None


def _detect_color_temperature(text: str) -> str | None:
    low = text.lower()
    if any(token in low for token in ("暖色", "暖光", "火光", "烛光", "warm", "amber")):
        return "warm"
    if any(token in low for token in ("冷色", "冷光", "蓝光", "cool", "cold")):
        return "cool"
    return None


def _detect_primary_light(text: str) -> str | None:
    low = text.lower()
    pairs = (
        (("火光", "火把", "壁炉", "烛光", "firelight", "torch"), "firelight"),
        (("日光", "阳光", "天光", "daylight", "sunlight"), "daylight"),
        (("雷光", "闪电", "lightning"), "lightning"),
        (("月光", "moonlight"), "moonlight"),
    )
    return next((value for keys, value in pairs if any(key in low for key in keys)), None)


_ANCHOR_SYS = """你是影视连续性总监。给你一整集的全部场景（按剧情顺序），为每个场景钉死它的视觉硬锁。

铁律：
1. **整集一次性判断，时间线必须连贯推进**——不是逐场景孤立猜。若剧情跨越一段时间，
   time_of_day 要有合理演进（如 afternoon→dusk→night），不得来回跳。
2. **天气必须跟着剧情走**：本场剧情里出现"雷暴逼近/乌云压境"就是 overcast，
   出现"雷声轰鸣/闪电/暴雨倾盆"就必须升级为 thunderstorm，且此后不得倒退回 clear。
   逐场景读剧情文本判断，**严禁整集一个天气值照抄到底**。
3. **室内与室外必须分别判断光线**：室外用天光方位（如"左后侧逆光，海面反光补亮"）；
   室内必须依据该空间的门窗方位与人工光源来写（如"西向门洞侧逆光射入，工作台顶灯补亮"），
   **严禁把室外光向照抄进室内场景**。primary_light_source 同理——
   室内若无天光直射，应为 lamplight/firelight，雷暴夜可为 lightning。
4. **同一 location_id 再次出现时，architectural_topology 与 palette 保持一致**，
   只有光线可随时间与天气推进变化。
5. palette 要贴合本场景的实际环境与情绪，不同空间应有差异（工坊金属冷灰 vs 海边风暴墨蓝），
   **不得所有场景同一句**。
6. lighting_direction 与 palette 写具体可执行的中文短语；
   architectural_topology 用中文描述空间结构与关键陈设方位，供作画锚定。

自检：输出前逐项检查——weather、lighting_direction、palette 三项若在所有场景里完全相同，
说明你在照抄而不是在判断，必须重新逐场景推导。

严格输出 JSON：
{"scenes":[{"seg":1,
 "location_id":"该场景的地点名（中文，简短且稳定，同一地点复现须同名）",
 "time_of_day":"dawn|morning|noon|afternoon|dusk|night|midnight",
 "weather":"clear|overcast|rain|heavy_rain|thunderstorm|snow|fog",
 "primary_light_source":"daylight|firelight|lightning|moonlight|lamplight",
 "lighting_direction":"中文光向短语",
 "color_temperature":"warm|cool|neutral",
 "palette":"中文色板短语",
 "enclosure":"interior|exterior",
 "architectural_topology":"中文空间结构描述"}]}"""


async def _llm_scene_anchors(
    project: Any, chapter: Any, groups: dict[int, list[Any]], group_meta: dict[int, Any],
) -> dict[int, dict[str, Any]]:
    """整集一次 LLM 推理，为每个场景补全视觉硬锁（时间/天气/光线/色板/空间）。

    取代逐场景关键词正则：正则扫不中就留空，实测一集 9 个场景里 color_temperature /
    primary_light_source / enclosure 全空、time_of_day 9 个全是同一个值，
    lighting_direction 与 palette 更是从未产出过——组图因此没有任何光线判据。
    失败不阻塞，调用方回落正则探测。"""
    from .. import llm
    from .character_context import era_anchor

    lines = []
    for seg in sorted(groups):
        grp = group_meta.get(seg) or {}
        first = _json(groups[seg][0]["meta"])
        beats = "；".join(
            str(_json(r["meta"]).get("action") or r["summary"] or "")[:40]
            for r in groups[seg][:4])
        lines.append(
            f"- 场景{seg}：{grp.get('scene') or first.get('scene') or '未标注'}"
            f"｜空间：{str(grp.get('space') or '')[:90]}"
            f"｜本场剧情：{beats[:200]}")
    user = (
        f"【项目世界观/年代背景】{era_anchor(project) if project else '（无）'}\n"
        f"【画风】{(project['art_style'] if project else '') or '（未设定）'}\n"
        f"【本集标题】{(chapter['title'] if chapter else '') or ''}\n\n"
        f"【本集全部场景（按剧情顺序）】\n" + "\n".join(lines)
    )
    data = await llm.chat_json(_ANCHOR_SYS, user, max_tokens=4000)
    out: dict[int, dict[str, Any]] = {}
    for item in (data or {}).get("scenes") or []:
        try:
            seg = int(item.get("seg"))
        except (TypeError, ValueError):
            continue
        if seg in groups:
            out[seg] = {k: v for k, v in item.items() if k != "seg" and v not in (None, "", [])}
    return out


def _safe_code(value: Any, fallback: str) -> str:
    text = re.sub(r"[^0-9A-Za-z_-]+", "_", str(value or "")).strip("_")
    return text[:40] or fallback


def _location_zone(value: Any) -> str:
    """从 blocking 的自然语言站位中提取稳定的空间位置。

    blocking 为了指导画面会同时写入朝向、姿态和当前动作，例如
    ``站在石碑前，面朝石碑，手指轻触``。这些视觉细节可以逐镜变化，但不能被当成
    location_zone，否则角色原地转头也会触发 adjacent_state_mismatch。
    """
    text = str(value or "").strip()
    if not text:
        return "unknown"
    return re.split(r"[，,；;。]", text, maxsplit=1)[0].strip() or "unknown"


def _character_seed(
    anchors: dict[str, Any],
    element_states: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    chars: dict[str, Any] = {}
    for name, position in anchors.items():
        state = element_states.get(name) or {}
        chars[str(name)] = {
            "location_zone": _location_zone(position),
            "costume_version": state.get("服装") or state.get("costume_version") or "unknown",
            "injury": state.get("伤势") or state.get("injury") or "none",
            "held_props": state.get("持有道具") or state.get("held_props") or {},
        }
    return chars


async def materialize_chapter(
    pool: asyncpg.Pool,
    project_id: int,
    chapter_id: int,
) -> dict[str, Any]:
    """为当前存活分镜生成新的 Contract/ShotState 版本；旧版本全部保留。"""
    chapter = await pool.fetchrow(
        "SELECT id,seq,title,summary,meta FROM content_nodes "
        "WHERE id=$1 AND project_id=$2 AND kind='chapter'",
        chapter_id, project_id)
    if not chapter:
        raise ValueError("章节不存在")
    shots = await pool.fetch(
        "SELECT id,seq,title,summary,meta FROM content_nodes "
        "WHERE parent_id=$1 AND kind='shot' AND deleted_at IS NULL ORDER BY seq,id",
        chapter_id)
    if not shots:
        raise ValueError("本章尚无分镜")
    element_rows = await pool.fetch(
        "SELECT name,brief,state FROM content_elements WHERE project_id=$1 AND kind='character'",
        project_id)
    element_states = {r["name"]: _json(r["state"]) for r in element_rows}
    # 能力判断只看角色身份简介；state 中“目标=寻找龙巢”等剧情词不能被误当成自身是龙。
    element_profiles = {r["name"]: str(r["brief"] or "") for r in element_rows}
    chapter_meta = _json(chapter["meta"])
    group_meta = {
        int(g.get("seg") or 0): g
        for g in ((chapter_meta.get("scene_blocking") or {}).get("groups") or [])
    }
    groups: dict[int, list[Any]] = {}
    for shot in shots:
        seg = int(_json(shot["meta"]).get("scene_seg") or 1)
        groups.setdefault(seg, []).append(shot)

    # 跨场景边界与场内合同是两条独立轴：换场重置视觉合同，但同一角色的能力、
    # 骑乘/载具与状态仍须有可解释的转场。不同角色/空景直切不会产生错误。
    from .scene_transitions import analyze_boundary

    boundary_errors: dict[int, list[dict[str, Any]]] = {}
    normalized: list[dict[str, Any]] = []
    for shot in shots:
        meta = _json(shot["meta"])
        normalized.append({
            **meta,
            "shot_no": meta.get("shot_no") or shot["seq"],
            "summary": shot["summary"] or "",
            "description": shot["summary"] or "",
            "_character_profiles": element_profiles,
        })
    for previous, current, row in zip(normalized, normalized[1:], shots[1:]):
        audit = analyze_boundary(previous, current)
        if audit["errors"]:
            boundary_errors[row["id"]] = audit["errors"]

    # 整集视觉锚定：一次推理覆盖全部场景，保证时间/天气跨场景连贯推进。
    # 失败或缺项时逐项回落到关键词探测，绝不因此挡住连续性台账的建立。
    project = await pool.fetchrow(
        "SELECT * FROM content_projects WHERE id=$1", project_id)
    try:
        anchors_by_seg = await _llm_scene_anchors(project, chapter, groups, group_meta)
    except Exception as e:  # noqa: BLE001
        log.warning("章 %s 整集场景锚定失败，回落关键词探测: %s", chapter_id, e)
        anchors_by_seg = {}

    total_states = 0
    blocked = 0
    contract_ids: list[int] = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            for seg, rows in groups.items():
                first_meta = _json(rows[0]["meta"])
                grp = group_meta.get(seg) or {}
                scene_text = str(grp.get("scene") or first_meta.get("scene") or f"场景组{seg}")
                scene_code = f"SC_{seg:03d}"
                narrative = await conn.fetchrow(
                    "INSERT INTO narrative_scenes"
                    "(project_id,chapter_id,scene_code,title,seq,source_meta) "
                    "VALUES($1,$2,$3,$4,$5,$6::jsonb) "
                    "ON CONFLICT(chapter_id,scene_code) DO UPDATE SET "
                    "title=EXCLUDED.title,source_meta=EXCLUDED.source_meta RETURNING id",
                    project_id, chapter_id, scene_code, scene_text[:160], seg,
                    json.dumps({
                        "source": "scene_blocking",
                        "shot_ids": [r["id"] for r in rows],
                        "scene_seg": seg,
                    }, ensure_ascii=False))
                narrative_id = narrative["id"]
                version = int(await conn.fetchval(
                    "SELECT COALESCE(max(version),0)+1 FROM scene_continuity_contracts "
                    "WHERE narrative_scene_id=$1", narrative_id))
                parent_id = await conn.fetchval(
                    "SELECT id FROM scene_continuity_contracts "
                    "WHERE narrative_scene_id=$1 ORDER BY version DESC LIMIT 1", narrative_id)
                corpus = " ".join(
                    [scene_text, str(grp.get("space") or "")]
                    + [str(_json(r["meta"]).get("lighting") or "") for r in rows])
                # 整集锚定优先，缺项才回落关键词探测（探测命中率低，只当兜底）
                anchor = anchors_by_seg.get(seg) or {}
                time_of_day = anchor.get("time_of_day") or _detect_time(corpus)
                weather = anchor.get("weather") or _detect_weather(corpus)
                enclosure = anchor.get("enclosure") or _detect_enclosure(
                    " ".join((scene_text, str(grp.get("space") or ""))))
                color_temperature = (anchor.get("color_temperature")
                                     or _detect_color_temperature(corpus))
                primary_light_source = (anchor.get("primary_light_source")
                                        or _detect_primary_light(corpus))
                # 空间拓扑此前只在 enclosure 探测命中时才写，导致多数场景为空；
                # 站位规划的 space 一直都在，无条件用它兜底
                topology = (anchor.get("architectural_topology")
                            or str(grp.get("space") or "") or scene_text)
                location = (anchor.get("location_id")
                            or first_meta.get("scene_element") or scene_text)
                hard_locks = {
                    "location_id": location,
                    "scene_version": _safe_code(
                        first_meta.get("scene_element") or location, f"scene_{seg}"),
                    "story_day": f"CHAPTER_{int(chapter['seq'] or 1):03d}",
                    "camera_axis": f"AXIS_{seg:03d}",
                    "architectural_topology": topology,
                    **({"time_of_day": time_of_day} if time_of_day else {}),
                    **({"weather": weather} if weather else {}),
                    **({"environment_type": enclosure} if enclosure else {}),
                    **({"enclosure": enclosure} if enclosure else {}),
                    **({"ceiling_state": "roofed"} if enclosure == "interior" else {}),
                    **({"color_temperature": color_temperature} if color_temperature else {}),
                    **({"primary_light_source": primary_light_source}
                       if primary_light_source else {}),
                    **({"lighting_direction": anchor["lighting_direction"]}
                       if anchor.get("lighting_direction") else {}),
                    **({"palette": anchor["palette"]} if anchor.get("palette") else {}),
                }
                anchors = grp.get("anchors") or {}
                initial = {
                    **hard_locks,
                    "characters": _character_seed(anchors, element_states),
                    "blocking_space": grp.get("space") or "",
                }
                contract = await conn.fetchrow(
                    "INSERT INTO scene_continuity_contracts"
                    "(narrative_scene_id,version,hard_locks,initial_state,status,parent_version_id) "
                    "VALUES($1,$2,$3::jsonb,$4::jsonb,'locked',$5) RETURNING id",
                    narrative_id, version,
                    json.dumps(hard_locks, ensure_ascii=False),
                    json.dumps(initial, ensure_ascii=False), parent_id)
                contract_id = contract["id"]
                contract_ids.append(contract_id)

                carry = copy.deepcopy(initial)
                previous_after: dict[str, Any] | None = None
                for index, shot in enumerate(rows):
                    meta = _json(shot["meta"])
                    blocking = meta.get("blocking") or {}
                    before = copy.deepcopy(carry)
                    before.setdefault("characters", {})
                    for name, pos in (blocking.get("chars") or {}).items():
                        char = before["characters"].setdefault(
                            str(name), _character_seed(
                                {str(name): pos}, element_states).get(str(name), {}))
                        char["location_zone"] = _location_zone(pos)
                    after = copy.deepcopy(before)
                    changes: dict[str, Any] = {}
                    moves = str(blocking.get("moves") or "").strip()
                    if moves and index + 1 < len(rows):
                        next_chars = (_json(rows[index + 1]["meta"]).get("blocking") or {}).get("chars") or {}
                        for name, pos in next_chars.items():
                            current = (after["characters"].get(str(name)) or {}).get("location_zone")
                            next_zone = _location_zone(pos)
                            if current is not None and next_zone != current:
                                after["characters"][str(name)]["location_zone"] = next_zone
                                path = f"characters.{name}.location_zone"
                                changes[path] = {"from": current, "to": next_zone}
                    quote = "；".join(x for x in (
                        str(meta.get("action") or "").strip(),
                        moves,
                        str(meta.get("dialogue") or "").strip()
                    ) if x and x != "无") or str(shot["summary"] or "").strip()
                    shot_no = meta.get("shot_no") or shot["seq"]
                    evidence = {
                        "source": "chapter_script",
                        "source_node_id": chapter_id,
                        "event_ids": [f"CH{chapter['seq']}_SH{shot_no}"],
                        "quote": quote,
                        "derived_from_shot_plan": True,
                    }
                    transition = {
                        "type": "explicit_script_action",
                        "evidence": quote,
                        "visual_action": meta.get("action") or moves,
                        "changes": changes,
                    }
                    errors = validate_shot(
                        hard_locks, before, transition, after, evidence, previous_after)
                    errors.extend(boundary_errors.get(shot["id"], []))
                    beat = await conn.fetchrow(
                        "INSERT INTO story_beats"
                        "(narrative_scene_id,beat_code,seq,description,script_evidence) "
                        "VALUES($1,$2,$3,$4,$5::jsonb) RETURNING id",
                        narrative_id, f"B_{shot['id']}_V{version}", index + 1,
                        quote, json.dumps(evidence, ensure_ascii=False))
                    state_version = int(await conn.fetchval(
                        "SELECT COALESCE(max(version),0)+1 FROM shot_continuity_states "
                        "WHERE shot_id=$1", shot["id"]))
                    state_parent = await conn.fetchval(
                        "SELECT id FROM shot_continuity_states WHERE shot_id=$1 "
                        "ORDER BY version DESC LIMIT 1", shot["id"])
                    state = await conn.fetchrow(
                        "INSERT INTO shot_continuity_states"
                        "(shot_id,version,scene_contract_id,beat_ids,script_evidence,"
                        "before_state,action_transition,after_state,status,parent_version_id) "
                        "VALUES($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb,$8::jsonb,$9,$10) "
                        "RETURNING id",
                        shot["id"], state_version, contract_id, [beat["id"]],
                        json.dumps(evidence, ensure_ascii=False),
                        json.dumps(before, ensure_ascii=False),
                        json.dumps(transition, ensure_ascii=False),
                        json.dumps(after, ensure_ascii=False),
                        "approved" if not errors else "blocked", state_parent)
                    await conn.execute(
                        "INSERT INTO continuity_checks"
                        "(project_id,chapter_id,shot_state_id,check_type,passed,errors) "
                        "VALUES($1,$2,$3,'pre_generation',$4,$5::jsonb)",
                        project_id, chapter_id, state["id"], not errors,
                        json.dumps(errors, ensure_ascii=False))
                    await conn.execute(
                        "UPDATE content_nodes SET meta=meta || $2::jsonb,updated_at=now() "
                        "WHERE id=$1",
                        shot["id"], json.dumps({"continuity": {
                            "scene_contract_id": contract_id,
                            "shot_state_id": state["id"],
                            "version": state_version,
                            "status": "approved" if not errors else "blocked",
                            "errors": errors,
                        }}, ensure_ascii=False))
                    total_states += 1
                    blocked += int(bool(errors))
                    carry = copy.deepcopy(after)
                    previous_after = copy.deepcopy(after)
    return {
        "contracts": len(contract_ids),
        "contract_ids": contract_ids,
        "shot_states": total_states,
        "approved": total_states - blocked,
        "blocked": blocked,
    }


async def assert_shot_generation_ready(pool: asyncpg.Pool, shot_id: int) -> None:
    """加载最新版本重跑确定性校验；缺记录或失败时阻止提示词/图像/视频生成。"""
    row = await pool.fetchrow(
        "SELECT s.id,s.script_evidence,s.before_state,s.action_transition,s.after_state,"
        "c.hard_locks,n.parent_id,n.project_id "
        "FROM shot_continuity_states s "
        "JOIN scene_continuity_contracts c ON c.id=s.scene_contract_id "
        "JOIN content_nodes n ON n.id=s.shot_id "
        "WHERE s.shot_id=$1 ORDER BY s.version DESC LIMIT 1", shot_id)
    if not row:
        raise ValueError("分镜缺少连续性状态，请先完成场景空间规划")
    previous = await pool.fetchrow(
        "SELECT ps.after_state FROM content_nodes cur "
        "JOIN content_nodes prev ON prev.parent_id=cur.parent_id "
        " AND prev.kind='shot' AND prev.deleted_at IS NULL AND prev.seq<cur.seq "
        "JOIN LATERAL (SELECT after_state,scene_contract_id FROM shot_continuity_states "
        " WHERE shot_id=prev.id ORDER BY version DESC LIMIT 1) ps ON true "
        "WHERE cur.id=$1 AND ps.scene_contract_id=("
        " SELECT scene_contract_id FROM shot_continuity_states WHERE shot_id=$1 "
        " ORDER BY version DESC LIMIT 1) ORDER BY prev.seq DESC LIMIT 1", shot_id)
    errors = validate_shot(
        _json(row["hard_locks"]), _json(row["before_state"]),
        _json(row["action_transition"]), _json(row["after_state"]),
        _json(row["script_evidence"]),
        _json(previous["after_state"]) if previous else None)
    await pool.execute(
        "INSERT INTO continuity_checks"
        "(project_id,chapter_id,shot_state_id,check_type,passed,errors) "
        "VALUES($1,$2,$3,'generation_gate',$4,$5::jsonb)",
        row["project_id"], row["parent_id"], row["id"], not errors,
        json.dumps(errors, ensure_ascii=False))
    # 出图门禁只拦"画面自相矛盾"这一类：场景硬锁被违反、室内动作掀掉屋顶——
    # 这些画出来必错。其余（相邻镜状态对不上、状态变更未声明、缺剧情证据等）是叙事台账
    # 层面的记账问题，依赖 DAG 补不出来、重跑也不会变，却会把整镜的出图永久卡死
    # （实测一集 24 镜里两镜因 adjacent_state_mismatch 全程无法生成）。
    # 它们照常入库 continuity_checks 供追溯，但不阻断生成。
    blocking = [e for e in errors if str(e.get("code")) in _BLOCKING_CODES]
    if blocking:
        codes = ", ".join(str(e["code"]) for e in blocking)
        raise ValueError(f"连续性校验未通过，禁止生成：{codes}")
    if errors:
        log.warning("镜 %s 连续性告警（不阻断生成）：%s", shot_id,
                    ", ".join(str(e.get("code")) for e in errors))
