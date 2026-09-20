"""音频预检（audio precheck）：视频生成前的"对白×音色"前置质量检查。

与提示词质检（storyboard.review_video_prompt）同一范式的音频版：
确定性 gate（零 token）→ best-effort 补音频小样（TTS 欠费降级不阻塞）→ LLM 评审（无重构环节，
音色的"重构"=重新捏音色，只给建议）→ 结果落 shot.meta.audio_precheck。

铁律：预检永不阻断视频生成——不合格只降级为"不传 reference_audio"，与
"质检失败按原提示词生成"（worker）同一哲学；顺手产出 audio_refs 供音画闭环
（仅 speech/hybrid 角色的样本作 ARK reference_audio；call 兽鸣是 TTS 拟声占位，
不适合驱动口型，走音效素材层——见 docs/arch/voice-timbre-design.md 五b）。
"""
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import asyncpg
import httpx

from .. import llm, media
from ..oss import store_bytes
from .flow import AUDIO_PRECHECK_TTL_H, stamp_validity
from .prosody import resolve_prosody
from .voice_casting import estimate_tts_duration, sample_plan

log = logging.getLogger("audio_precheck")

_SAY = re.compile(r"说：?[“\"](.+?)[”\"]")  # 与 storyboard._SAY 同构
_SPEAKER_LINE = re.compile(r"^([^：:]{1,12})[：:](.+)$")
# call（兽鸣）角色允许的拟声字——台词里出现这之外的汉字超过 4 个即视为"文字台词"
_ONOMATOPOEIA = set("呜嗷吼嘶嗡哞汪喵吱咕嘎啾唧嗥嚎哮呦咆呼哧噗嘤")

# ARK Seedance 2.0 音频参考硬约束：wav/mp3、单段 2-15s、≤3 段、总时长 ≤15s（留 1s 余量）
_AUDIO_MAX_REFS = 3
_AUDIO_TOTAL_BUDGET_S = 14.0
_AUDIO_SEG_MIN_S, _AUDIO_SEG_MAX_S = 2.0, 15.0
_FALLBACK_DURATION_S = 5.0  # 存量样本无时长估算时的保守值


def parse_dialogue(meta: dict[str, Any]) -> list[dict[str, str]]:
    """从分镜 meta 解析对白 → [{speaker, text}]（确定性，零 token）。

    来源①：meta.dialogue "角色：台词" 行（"无"=无对白，多句 / 分隔）；
    来源②：cuts[].action 内嵌 说："…"（speaker=cut.subject）。
    """
    out: list[dict[str, str]] = []
    dlg = (meta.get("dialogue") or "").strip()
    if dlg and dlg != "无":
        for part in re.split(r"[/\n]", dlg):  # 实际数据两种分隔并存：/ 与换行
            part = part.strip()
            if not part:
                continue
            m = _SPEAKER_LINE.match(part)
            if m:
                out.append({"speaker": m.group(1).strip(), "text": m.group(2).strip()})
            else:
                out.append({"speaker": "", "text": part})
    for c in meta.get("cuts") or []:
        say = _SAY.search(c.get("action") or "")
        if say:
            out.append({"speaker": (c.get("subject") or "").strip(), "text": say.group(1)})
    return out


def _is_textual_line(text: str) -> bool:
    """call（兽鸣）矛盾判定：剥掉拟声字与标点后仍有 >4 个汉字 → 是文字台词。"""
    hanzi = [ch for ch in text if "一" <= ch <= "鿿" and ch not in _ONOMATOPOEIA]
    return len(hanzi) > 4


_AUDIO_REVIEW_SYS = """你是配音导演，对一个分镜的「对白×音色」匹配做生成前预检评审。四个维度：
1. 音色气质与台词内容匹配：音色描述的气质（如软萌少女音）与台词气场（如狠辣威胁）是否冲突
2. 发声形态与台词形态匹配：call（兽鸣）角色不应有成句人话；speech 角色台词正常即合格
3. 语言一致：音色/角色标注的 language 与台词实际语言是否一致
4. 情绪支持：音色 emotions 列表能否覆盖本镜气氛（mood）所需的情绪
只报确定存在的问题，不吹毛求疵；轻微风格差异不扣大分。
严格输出 JSON：
{"合格": true, "得分": 0到100, "问题": ["维度N：具体问题"], "修改建议": ["可执行建议，如'为角色X重新捏音色，指令：更低沉'"]}
得分≥80 视为合格。"""


def _source_text(lines: list[dict[str, str]], char_by_name: dict[str, dict[str, Any]]) -> str:
    """预检缓存指纹源：对白文本 + 各角色音色绑定（任一变化 → 缓存失效重检）。"""
    if not lines:
        return "no-dialogue"
    parts = [f"{ln['speaker']}:{ln['text']}" for ln in lines]
    binds = []
    for name in sorted(char_by_name):
        m = char_by_name[name].get("meta") or {}
        voice = m.get("voice") if isinstance(m.get("voice"), dict) else {}
        binds.append(f"{name}={voice.get('kb_voice_id') or ''}")
    return "|".join(parts) + "||" + ",".join(binds)


async def precheck_source(pool: asyncpg.Pool, project_id: int, meta: dict[str, Any]) -> str:
    """供视频生成前置做缓存有效性判断（flow.cache_valid），与落库时的指纹同源。"""
    lines = parse_dialogue(meta)
    if not lines:
        return "no-dialogue"
    chars = await pool.fetch(
        "SELECT name, meta FROM content_elements WHERE project_id=$1 AND kind='character'",
        project_id,
    )
    char_by_name = {
        r["name"]: {"meta": r["meta"] if isinstance(r["meta"], dict) else json.loads(r["meta"] or "{}")}
        for r in chars
    }
    return _source_text(lines, char_by_name)


async def _head_ok(url: str) -> bool | None:
    """样本 URL 可达性：True/False=确定结果，None=网络异常（记 warn 不记 error）。"""
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            r = await client.head(url)
            return r.status_code < 400
    except Exception:  # noqa: BLE001
        return None


async def precheck_shot_audio(pool: asyncpg.Pool, project_id: int, shot_id: int) -> dict[str, Any]:
    """音频预检编排：gate → best-effort 小样 → LLM 评审 → audio_refs → 落 meta.audio_precheck。"""
    async with pool.acquire() as conn:
        shot = await conn.fetchrow(
            "SELECT * FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id
        )
        if not shot:
            raise ValueError("分镜不存在")
        meta = shot["meta"] if isinstance(shot["meta"], dict) else json.loads(shot["meta"])
        lines = parse_dialogue(meta)
        result: dict[str, Any] = {
            "required": bool(lines), "合格": True, "得分": None,
            "degraded": False, "tts_error": None,
            "errors": [], "warns": [], "speakers": [], "llm": None, "audio_refs": [],
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if not lines:
            # 无对白：预检直接通过，闭环不传音频（有对白才传）
            stamp_validity(result, "no-dialogue", AUDIO_PRECHECK_TTL_H)
            await _save(conn, shot_id, result)
            return result
        chars = await conn.fetch(
            "SELECT id, name, meta FROM content_elements WHERE project_id=$1 AND kind='character'",
            project_id,
        )

    # ── speaker → 角色要素解析（精确名优先，其次名字包含于 subject，如"阿澈(惊)"）──
    char_by_name: dict[str, dict[str, Any]] = {}
    for r in chars:
        m = r["meta"] if isinstance(r["meta"], dict) else json.loads(r["meta"] or "{}")
        char_by_name[r["name"]] = {"id": r["id"], "name": r["name"], "meta": m}

    def _resolve(speaker: str) -> dict[str, Any] | None:
        if speaker in char_by_name:
            return char_by_name[speaker]
        return next((c for n, c in char_by_name.items() if n and n in speaker), None)

    errors, warns = result["errors"], result["warns"]
    seen: set[str] = set()
    speakers: list[dict[str, Any]] = result["speakers"]  # 明细直接挂 result（曾漏回填）
    unnamed = False
    for ln in lines:
        sp = ln["speaker"]
        if not sp:
            unnamed = True
            continue
        c = _resolve(sp)
        key = c["name"] if c else sp
        if key in seen:
            # A4 的逐句矛盾检查仍要覆盖同一角色的后续台词
            entry = next(e for e in speakers if e["speaker"] == key)
        else:
            seen.add(key)
            entry = {"speaker": key, "element_id": c["id"] if c else None,
                     "voice_name": None, "vocal_mode": None, "sample_audio_url": None,
                     "duration_s_est": None, "sample_reachable": None, "issues": []}
            speakers.append(entry)
            if not c:
                warns.append(f"speaker「{sp}」不在角色要素中（可能是路人，不传参考音频）")  # A1
                continue
            emeta = c["meta"]
            voice = emeta.get("voice") if isinstance(emeta.get("voice"), dict) else {}
            vp = emeta.get("voice_profile") if isinstance(emeta.get("voice_profile"), dict) else {}
            entry["voice_name"] = voice.get("name")
            entry["vocal_mode"] = voice.get("vocal_mode") or vp.get("vocal_mode")
            entry["kb_voice_id"] = voice.get("kb_voice_id")
            entry["language"] = voice.get("language") or vp.get("language") or ""
            if not voice:
                errors.append(f"「{key}」未捏音色——先执行捏音色或批量选角")  # A2
            if not vp:
                warns.append(f"「{key}」发声形态未标注（可执行 elements/annotate-voices 补标注）")  # A3
        # A4 矛盾检测（逐句）
        mode = entry.get("vocal_mode")
        if mode == "silent":
            msg = f"「{key}」标注为 silent（不发声）却有台词「{ln['text'][:20]}」——请改标注或删台词"
            if msg not in errors:
                errors.append(msg)
        elif mode == "call" and _is_textual_line(ln["text"]):
            msg = f"「{key}」标注为 call（兽鸣）却有文字台词「{ln['text'][:20]}」——确认是否应改 hybrid/speech"
            if msg not in warns:
                warns.append(msg)
    if unnamed:
        warns.append("存在未署名对白（无'角色：'前缀），无法关联音色")

    # ── A5 样本检查 + best-effort 补小样（TTS 欠费降级不阻塞）──
    kb_ids = [e["kb_voice_id"] for e in speakers if e.get("kb_voice_id")]
    kb_meta: dict[int, dict[str, Any]] = {}
    if kb_ids:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, meta FROM kb_entries WHERE id = ANY($1::bigint[])", kb_ids
            )
        for r in rows:
            kb_meta[r["id"]] = r["meta"] if isinstance(r["meta"], dict) else json.loads(r["meta"] or "{}")
    for e in speakers:
        vid = e.get("kb_voice_id")
        if not vid:
            continue
        vmeta = kb_meta.get(vid) or {}
        e["sample_audio_url"] = vmeta.get("sample_audio_url")
        e["duration_s_est"] = vmeta.get("sample_duration_s_est")
        if not e["sample_audio_url"] and (e.get("vocal_mode") or "speech") in ("speech", "hybrid") \
                and vmeta.get("voice_type") and not result["degraded"]:
            try:
                text, instruct = sample_plan(vmeta)
                pr = resolve_prosody(vmeta, None, text)
                audio = await media.generate_tts(
                    text, vmeta["voice_type"], speed=pr["speed"], instruct=instruct or pr.get("instruct")
                )
                url = await store_bytes(audio, "voice_sample", ".mp3")
                if url:
                    vmeta["sample_audio_url"] = url
                    vmeta["sample_duration_s_est"] = estimate_tts_duration(text, pr["speed"])
                    async with pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE kb_entries SET meta=$2::jsonb, updated_at=now() WHERE id=$1",
                            vid, json.dumps(vmeta, ensure_ascii=False),
                        )
                    e["sample_audio_url"] = url
                    e["duration_s_est"] = vmeta["sample_duration_s_est"]
            except Exception as ex:  # noqa: BLE001 — 欠费/限流等降级，不影响合格判定
                result["degraded"] = True
                result["tts_error"] = str(ex)[:120]
                warns.append(f"「{e['speaker']}」小样待生成（TTS 暂不可用：{str(ex)[:60]}）")
        if e["sample_audio_url"]:
            e["sample_reachable"] = await _head_ok(e["sample_audio_url"])
            if e["sample_reachable"] is False:
                warns.append(f"「{e['speaker']}」样本 URL 不可达（HTTP ≥400），不传参考音频")
            elif e["sample_reachable"] is None:
                warns.append(f"「{e['speaker']}」样本可达性检查网络异常（不视为失败）")
        elif not result["degraded"] and (e.get("vocal_mode") or "speech") in ("speech", "hybrid") \
                and e.get("kb_voice_id"):
            warns.append(f"「{e['speaker']}」音色缺试听样本且未能补生成")

    result["合格"] = not errors

    # ── LLM 评审（gate 无 error 且未降级才评；降级=信息不全，评了也是空谈）──
    if result["合格"] and not result["degraded"]:
        try:
            reviewable = [e for e in speakers if e.get("voice_name")]
            voice_lines = []
            for e in reviewable:
                vmeta = kb_meta.get(e.get("kb_voice_id") or -1) or {}
                voice_lines.append(
                    f"- {e['speaker']}：音色「{e['voice_name']}」｜形态={e.get('vocal_mode')}"
                    f"｜语言={e.get('language')}｜情绪支持={vmeta.get('emotions')}"
                )
            if reviewable:
                user = (
                    f"# 本镜对白\n" + "\n".join(f"{ln['speaker'] or '(未署名)'}：{ln['text']}" for ln in lines)
                    + f"\n\n# 本镜气氛 mood\n{meta.get('mood') or '（未标注）'}\n\n"
                    + "# 各说话角色音色\n" + "\n".join(voice_lines)
                )
                review = await llm.chat_json(_AUDIO_REVIEW_SYS, user, max_tokens=1200, purpose="review")
                result["llm"] = {"得分": review.get("得分"), "问题": review.get("问题") or [],
                                 "修改建议": review.get("修改建议") or []}
                result["得分"] = review.get("得分")
                # 评审不合格只降口——列入 warns，不阻断（音频预检永不阻断视频生成）
                if not review.get("合格"):
                    warns.append(f"LLM 评审未达 80 分（{review.get('得分')}），建议先按修改建议调整音色")
        except Exception as ex:  # noqa: BLE001 — 评审失败不阻塞（与提示词质检同哲学）
            log.warning("镜 %s 音频 LLM 评审异常（跳过）: %s", shot_id, ex)

    # ── audio_refs 组装（音画闭环入参：仅 speech/hybrid + 有可用样本；有对白才有本环节）──
    total = 0.0
    for e in speakers:
        if (e.get("vocal_mode") or "speech") not in ("speech", "hybrid"):
            continue
        url = e.get("sample_audio_url")
        if not url or e.get("sample_reachable") is False:
            continue
        d = float(e.get("duration_s_est") or _FALLBACK_DURATION_S)
        if d < _AUDIO_SEG_MIN_S or d > _AUDIO_SEG_MAX_S:
            warns.append(f"「{e['speaker']}」样本时长估算 {d}s 超出 ARK 单段 2-15s 范围，剔除")
            continue
        if len(result["audio_refs"]) >= _AUDIO_MAX_REFS or total + d > _AUDIO_TOTAL_BUDGET_S:
            warns.append(f"参考音频超限（≤{_AUDIO_MAX_REFS}段/总时长≤{_AUDIO_TOTAL_BUDGET_S}s），"
                         f"「{e['speaker']}」及之后按出场顺序截断")
            break
        result["audio_refs"].append({"speaker": e["speaker"], "url": url, "duration_s_est": d})
        total += d

    # 缓存有效性戳：指纹=对白+音色绑定，TTL 24h（音色可能重捏）——命中免重跑预检
    stamp_validity(result, _source_text(lines, char_by_name), AUDIO_PRECHECK_TTL_H)
    async with pool.acquire() as conn:
        await _save(conn, shot_id, result)
    return result


async def _save(conn: asyncpg.Connection, shot_id: int, result: dict[str, Any]) -> None:
    await conn.execute(
        "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
        shot_id, json.dumps({"audio_precheck": result}, ensure_ascii=False),
    )
