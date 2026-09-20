"""捏音色（voice design/casting）：为角色设计并绑定专属音色。

流程（见 docs/arch/voice-timbre-design.md）：
角色资料 + 可选用户指令 → 配音员工（章程+捏音色技能）设计音色规格
→ 库中已有契合条目则复用，否则新建项目级音色条目（kind=voice, scope=project）
→ 绑定到 character.meta.voice → 尽力生成试听样本（TTS 不可用不阻塞）。
"""
import json
import logging
import re
from typing import Any

import asyncpg

from .. import llm, media
from ..oss import store_bytes
from .persona_traits import VOICE_DIMS, age_class_for_years, trait_for, trait_for_years, traits_table

log = logging.getLogger("voice_casting")

_SAY = re.compile(r"说：?[“\"](.+?)[”\"]")  # 与 storyboard._SAY 同构；本地定义避免循环依赖

# 捏音色技能（方法论，可被 kb_entries kind=skill agent_code=voice name=捏音色 覆盖）
VOICE_DESIGN_RULES = """你是选角与音色设计师（捏音色）。给定角色资料与可选的用户指令，为角色设计专属音色。
规则：
1. 优先级：用户指令 > 角色性格/身份 > 性别年龄形态；指令简单时（如"再冷一点"）在角色底色上微调
2. 先判定发声模式 vocal_mode，依据分三级（高优先级与低级矛盾时以事实证据校正设定意图）：
   ① 角色卡「发声设定 voice_profile」＝生成期设定意图，最优先采信；
   ② 「对白证据」＝该角色在分镜里的真实台词记录（事实校验：若设定为 call 但证据显示有文字台词，升级为 hybrid/speech 并在 description 注明）；
   ③ 两者皆缺时按形态/物种兜底——注意拟人化动物照样 speech（如疯狂动物城）。
   - speech＝人声对白（说人话的角色，含拟人化动物）
   - call＝兽鸣/非语言（真动物或巨兽，证据显示零台词，只有吼、鸣、嘶、低频震动）
   - hybrid＝以鸣声为主但偶有拟人语/灵性传意（如通过共鸣直达心灵的古兽）
   - silent＝不发声（如纯背景生物、器物）
   同时判定 language：speech/hybrid 填其说的语言（如 通用语/汉语/古语/自创语言），call/silent 填 无 或叫声描述
3. 音色库中已有高度契合的条目（气质与性别/年龄/形态、发声模式都吻合）就直接复用——match_existing 填其名称，不重复造轮子
4. 新设计的音色描述必须三层：气质（选角依据）／音质与韵律（听感标准：共鸣位置、语速、尾音习惯；call 模式写鸣叫的音域、气息长度、震动感）／适用角色
5. 机关傀儡/AI 用合成质感（speech 模式）
6. 参数化三档（为参数捏音色引擎预留）：pitch=low/mid/high，speed=slow/mid/fast，energy=soft/mid/strong"""

_VOICE_DESIGN_FORMAT = """严格输出 JSON：
{"name":"音色名（风格式命名，如'孤星剑客'，禁止真人名）","description":"气质；音质与韵律；适用角色（60-100字）",
 "tags":["3-6个标签"],"gender":"male|female|child|creature|neutral","age":"child|young|adult|middle|elder|none",
 "age_years":具体年龄数字（依据角色资料推定，如 24；生物按拟人化心智年龄给，器物/AI 填 0）,
 "vocal_mode":"speech|call|hybrid|silent","language":"该角色说的语言，call/silent 填'无'",
 "emotions":["该音色应支持的情绪，如 neutral/gentle/angry/sad/cold/excited/roar"],
 "params":{"pitch":"low|mid|high","speed":"slow|mid|fast","energy":"soft|mid|strong"},
 "match_existing":"若库中已有高度契合条目则填其准确名称，否则空字符串"}"""

# 试听文案按发声模式区分：call/hybrid 用拟声长音（TTS 占位听感；真实成片的兽吼走音效素材层）
SAMPLE_TEXTS = {
    "speech": "山高路远，江湖再见。此去经年，愿君平安。",
    "call": "呜……呜——嗷唔——！……呜……",
    "hybrid": "呜——……嗡……呜——",
    "silent": "……",
}
SAMPLE_INSTRUCTS = {
    "call": "模拟巨大生物的低沉鸣叫与吼声，气息悠长，带胸腔震动感，不要读成文字",
    "hybrid": "模拟古老生物的低频鸣响，悠远空灵，像从深处传来的共鸣，不要读成文字",
}


def sample_plan(meta: dict[str, Any]) -> tuple[str, str | None]:
    """按音色的发声模式选试听文案与语气指令；未标注时 creature 兜底为 call。"""
    mode = meta.get("vocal_mode") or ("call" if meta.get("gender") == "creature" else "speech")
    return SAMPLE_TEXTS.get(mode, SAMPLE_TEXTS["speech"]), SAMPLE_INSTRUCTS.get(mode)


def estimate_tts_duration(text: str, speed: float = 1.0) -> float:
    """估算 TTS 成品时长（秒）：有效字数÷4（与字幕打轴同一惯例）÷ 语速；免解析 mp3 依赖。"""
    chars = len(re.sub(r"[^\w一-鿿]", "", text))
    return round(max(chars, 4) / 4 / max(speed or 1.0, 0.25), 1)


# ═══════════ 情绪试听小样（喜怒哀乐+日常，按角色定制）═══════════
# 每条音色的试听不再是一句全库通用的固定文案，而是"这个角色"在 5 种情绪下各说一句独有的话，
# 内容先由大模型按角色身份/时代/语域生成（皇帝有皇帝的口吻），再逐句 TTS。
# 语速=角色基线×情绪因子，语气指令=角色声线 persona + 情绪 tone（复用 prosody 的合成规则）。

# (情绪, 语速因子, 语气指令片段)；平=中性基线不加语气
# speed 是本端点唯一有效的情绪通道（instruct 被 CosyVoice2 读出来已关闭），倍率务必保持区分度，
# 别为了"不卡通"收窄——不卡通靠的是关掉 instruct，不是抹平语速。
EMOTIONS: list[tuple[str, float, str | None]] = [
    ("喜", 1.08, "语气愉快、略带笑意"),
    ("怒", 1.12, "语气强硬、有分量"),
    ("哀", 0.82, "低沉放缓、略带哽咽"),
    ("乐", 1.00, "轻松自在"),
    ("平", 1.00, None),
]
_EMO_ORDER = {e: i for i, (e, _, _) in enumerate(EMOTIONS)}

_EMOTION_LINES_SYS = """你是配音台词设计。给定一条音色（角色声线）的设定，为它写 5 句"情绪试听小样"台词。
5 句分别对应：喜（欣喜/振奋）、怒（愤怒/质问）、哀（悲伤/失落）、乐（轻松/打趣）、平（平常叙事）。
硬要求：
1. 台词必须贴合该角色的身份、时代与语域——皇帝有皇帝的口吻，谋士有谋士的口吻，少女有少女的口吻；5 句是"同一个人"在不同情绪下说的话；
2. 每句第一人称、10-22 字（标点不计），只写说出口的话，不写动作/旁白/引号/情绪标注；
3. 抑扬顿挫靠标点写出来（TTS 会把标点转成真实停顿与语调）：按情绪的呼吸节奏断句——
   怒用短句急停加叹号（"够了！你，给我出去！"）、哀用省略号拖住（"罢了……终究是，留不住……"）、
   喜用上扬叹句、平用普通逗号句号；忌一逗到底的匀速长句；疑问句务必用问号；
4. 5 句内容互不相同，各自鲜明体现对应情绪；
5. 不得出现真实明星/影视角色的名字。
严格输出 JSON：{"lines":[{"emotion":"喜","text":"…"},{"emotion":"怒","text":"…"},{"emotion":"哀","text":"…"},{"emotion":"乐","text":"…"},{"emotion":"平","text":"…"}]}"""


async def _emotion_lines(
    name: str, description: str, tags: list[str], designed_for: str | None,
    persona_trait: str | None = None, age_years: int | None = None,
) -> dict[str, str]:
    """让大模型按角色设定产出 5 情绪台词，返回 {情绪: 台词}。"""
    user = (
        f"# 音色设定\n名称：{name}\n描述：{description or '（无）'}\n"
        f"标签：{'、'.join(tags) if tags else '（无）'}\n"
        + (f"年龄：{age_years}岁（台词的心智与语域须贴合此年龄）\n" if age_years else "")
        + f"典型角色：{designed_for or '（无特定角色，请依据以上描述气质设定一个具体人物）'}"
    )
    if persona_trait:  # 人物特征库（按音色年龄召回）：锚定台词的语域与断句节奏
        user += f"\n\n# 年龄特征参考（言语风格与断句节奏以此为锚）\n{persona_trait}"
    data = await llm.chat_json(_EMOTION_LINES_SYS, user, max_tokens=600)
    out: dict[str, str] = {}
    for it in data.get("lines") or []:
        emo, txt = (it.get("emotion") or "").strip(), (it.get("text") or "").strip()
        if emo in _EMO_ORDER and txt:
            out[emo] = txt
    return out


async def _save_samples(
    pool: asyncpg.Pool, voice_id: int, meta: dict[str, Any], samples: list[dict[str, Any]]
) -> None:
    """写回 meta.samples；同时保留 sample_audio_url/时长（取"平"，无则首条）供旧前端与音频预检零改动读取。"""
    meta["samples"] = sorted(samples, key=lambda s: _EMO_ORDER.get(s["emotion"], 99))
    primary = next((s for s in samples if s["emotion"] == "平"), None) or (samples[0] if samples else None)
    if primary:
        meta["sample_audio_url"] = primary["url"]
        meta["sample_duration_s_est"] = primary.get("duration_s")
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE kb_entries SET meta=$2::jsonb, updated_at=now() WHERE id=$1",
            voice_id, json.dumps(meta, ensure_ascii=False),
        )


async def generate_emotion_samples(pool: asyncpg.Pool, voice_id: int) -> dict[str, Any]:
    """为人声音色生成 5 情绪试听小样（喜怒哀乐+日常）：先大模型出词→逐句 TTS→OSS→存 meta.samples。

    非人声（call/hybrid/silent）无"情绪台词"一说，退回单条拟声小样（sample_plan）。
    单条情绪 TTS 失败跳过不阻塞；全失败才报错（多半是 TTS 欠费/限流）。"""
    from .prosody import age_base_speed, build_persona, _compose_instruct, resolve_prosody, SPEED_MIN, SPEED_MAX

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT name, description, tags, meta FROM kb_entries WHERE id=$1 AND kind='voice'", voice_id
        )
    if not row:
        raise ValueError("音色不存在")
    meta = row["meta"] if isinstance(row["meta"], dict) else json.loads(row["meta"] or "{}")
    if not meta.get("voice_type"):
        raise ValueError("该音色未绑定 voice_type，请先执行 bind-presets 或捏音色")

    mode = meta.get("vocal_mode") or ("call" if meta.get("gender") == "creature" else "speech")
    if mode != "speech":  # 兽鸣/非语言：单条拟声小样
        text, instruct = sample_plan(meta)
        pr = resolve_prosody(meta)
        audio = await media.generate_tts(
            text, meta["voice_type"], speed=pr["speed"], instruct=instruct or pr.get("instruct")
        )
        url = await store_bytes(audio, "voice_sample", ".mp3")
        samples = [{"emotion": "日常", "text": text, "url": url,
                    "duration_s": estimate_tts_duration(text, pr["speed"])}] if url else []
        if not samples:
            raise RuntimeError("拟声小样生成失败（OSS 未配置或 TTS 失败）")
        await _save_samples(pool, voice_id, meta, samples)
        return {"samples": samples, "mode": mode}

    age_years = meta.get("age_years") if isinstance(meta.get("age_years"), int) else None
    async with pool.acquire() as conn:  # 渐进式：情绪台词只取 声音+言语 两维；有数字年龄按数字换段
        if age_years:
            trait = await trait_for_years(conn, age_years, meta.get("gender"), VOICE_DIMS)
        else:
            trait = await trait_for(conn, meta.get("age"), meta.get("gender"), VOICE_DIMS)
    lines = await _emotion_lines(
        row["name"], row["description"] or "", list(row["tags"] or []),
        meta.get("designed_for"), trait, age_years,
    )
    persona = build_persona(meta)
    base = age_base_speed(meta)
    samples: list[dict[str, Any]] = []
    for emo, factor, tone in EMOTIONS:
        text = lines.get(emo)
        if not text:
            continue
        speed = round(min(max(base * factor, SPEED_MIN), SPEED_MAX), 2)
        try:
            audio = await media.generate_tts(
                text[:60], meta["voice_type"], speed=speed, instruct=_compose_instruct(persona, tone)
            )
            url = await store_bytes(audio, "voice_sample", ".mp3")
            if url:
                samples.append({"emotion": emo, "text": text, "url": url,
                                "duration_s": estimate_tts_duration(text, speed)})
        except Exception as e:  # noqa: BLE001 — 单条失败不阻塞其余情绪
            log.warning("情绪小样失败 %s/%s: %s", row["name"], emo, e)
    if not samples:
        raise RuntimeError("全部情绪小样生成失败（TTS 欠费/限流？）")
    await _save_samples(pool, voice_id, meta, samples)
    return {"samples": samples, "mode": mode}


async def _vocal_evidence(conn: asyncpg.Connection, project_id: int, name: str) -> dict[str, Any]:
    """对白证据（确定性，零 token）：扫全项目分镜，统计该角色的真实台词。

    两处来源：cuts[].subject==角色 且 action 含 说：“…”；dialogue 字段 "角色：台词" 行。
    这是发声模式判定的事实依据——动物有没有"说过话"以剧本实际为准，不靠想象。
    """
    rows = await conn.fetch(
        "SELECT meta FROM content_nodes WHERE project_id=$1 AND kind='shot' AND deleted_at IS NULL",
        project_id
    )
    lines: list[str] = []
    for r in rows:
        m = r["meta"] if isinstance(r["meta"], dict) else json.loads(r["meta"] or "{}")
        for c in m.get("cuts") or []:
            if name in (c.get("subject") or ""):
                say = _SAY.search(c.get("action") or "")
                if say:
                    lines.append(say.group(1))
        for part in re.split(r"[/\n]", m.get("dialogue") or ""):  # / 与换行两种分隔并存
            part = part.strip()
            if part.startswith(f"{name}：") or part.startswith(f"{name}:"):
                lines.append(part.split("：", 1)[-1].split(":", 1)[-1])
    return {"count": len(lines), "examples": lines[:3]}

# 规范年龄标签（与库中存量标签用语一致），供筛选/展示；none（AI/虫群等）无年龄不标
_AGE_TAGS = {"child": "幼童", "adult": "青年", "middle": "中年", "elder": "老年"}


def _age_tag(age: str | None, gender: str | None) -> str | None:
    if age == "young":
        return "少女" if gender == "female" else "少年"
    return _AGE_TAGS.get(age or "")


_COSY = "FunAudioLLM/CosyVoice2-0.5B"
_PRESETS = {
    "male": [f"{_COSY}:alex", f"{_COSY}:benjamin", f"{_COSY}:charles", f"{_COSY}:david"],
    "female": [f"{_COSY}:anna", f"{_COSY}:bella", f"{_COSY}:claire", f"{_COSY}:diana"],
    "child": [f"{_COSY}:claire", f"{_COSY}:anna"],
    "creature": [f"{_COSY}:charles", f"{_COSY}:david", f"{_COSY}:benjamin"],
    "neutral": [f"{_COSY}:david"],
}


async def _voice_system(conn: asyncpg.Connection, project_id: int) -> str:
    emp = await conn.fetchrow(
        "SELECT charter FROM agents WHERE project_id=$1 AND code='voice'", project_id
    )
    skill = await conn.fetchrow(
        "SELECT content FROM kb_entries WHERE kind='skill' AND agent_code='voice' AND name='捏音色' "
        "AND enabled AND (scope='global' OR (scope='project' AND project_id=$1)) "
        "AND ((SELECT project_type FROM content_projects WHERE id=$1)='novel_comic' "
        "     OR cardinality(tags)=0 OR (SELECT project_type FROM content_projects WHERE id=$1)=ANY(tags)) "
        "ORDER BY scope DESC LIMIT 1", project_id,
    )
    parts = []
    if emp and emp["charter"]:
        parts.append(emp["charter"])
    parts.append(skill["content"] if skill and skill["content"] else VOICE_DESIGN_RULES)
    parts.append(_VOICE_DESIGN_FORMAT)
    return "\n\n".join(parts)


async def design_voice(
    pool: asyncpg.Pool, project_id: int, element_id: int, instruction: str | None = None
) -> dict[str, Any]:
    """为角色捏音色并绑定：复用契合条目或新建项目级音色；尽力生成试听样本。"""
    async with pool.acquire() as conn:
        elem = await conn.fetchrow(
            "SELECT * FROM content_elements WHERE id=$1 AND project_id=$2", element_id, project_id
        )
        if not elem:
            raise ValueError("要素不存在")
        emeta = elem["meta"] if isinstance(elem["meta"], dict) else json.loads(elem["meta"])
        system = await _voice_system(conn, project_id)
        evidence = await _vocal_evidence(conn, project_id, elem["name"])
        traits = await traits_table(conn, VOICE_DIMS)  # 渐进式：选角参考只取 声音+言语 两维
        lib = await conn.fetch(
            "SELECT id, name, description, tags, meta FROM kb_entries WHERE kind='voice' AND enabled "
            "AND (scope='global' OR (scope='project' AND project_id=$1)) ORDER BY id", project_id,
        )
    lib_rows = []
    for r in lib:
        m = r["meta"] if isinstance(r["meta"], dict) else json.loads(r["meta"])
        lib_rows.append(f"「{r['name']}」{'/'.join(r['tags'])}｜{m.get('gender')}/{m.get('age')}")
    vp0 = emeta.get("voice_profile") if isinstance(emeta.get("voice_profile"), dict) else {}
    el_years = emeta.get("age_years")  # 角色卡数字年龄（滑块手设，最优先）
    user = (
        f"# 角色资料\n名称：{elem['name']}\n简介：{elem['brief'] or ''}\n"
        f"年龄：{f'{el_years}岁（用户手设，age/age_years 须照此）' if el_years else '（未标注，依据简介推定）'}\n"
        f"外貌：{emeta.get('外貌提示词', '')}\n形态：{emeta.get('形态', '人形')}\n"
        f"当前状态：{json.dumps(elem['state'] if isinstance(elem['state'], dict) else json.loads(elem['state'] or '{}'), ensure_ascii=False)}\n"
        f"发声设定（角色卡 voice_profile，最优先采信）：{json.dumps(vp0, ensure_ascii=False) if vp0 else '（未标注）'}\n"
        f"对白证据（分镜真实台词统计，事实校验用）：{json.dumps(evidence, ensure_ascii=False)}\n\n"
        f"# 用户指令\n{instruction or '（无——完全依据角色性格自主设计）'}\n\n"
        + (f"# 年龄段声线画像（人物特征库——age/params/描述须与角色年龄段对齐）\n{traits}\n\n" if traits else "")
        + f"# 现有音色库（可复用则填 match_existing）\n" + "\n".join(lib_rows)
    )
    spec = await llm.chat_json(system, user, max_tokens=1200)

    # ── 复用或新建 ──
    matched = None
    if (spec.get("match_existing") or "").strip():
        matched = next((r for r in lib if r["name"] == spec["match_existing"].strip()), None)
    async with pool.acquire() as conn:
        if matched:
            voice_id, voice_name = matched["id"], matched["name"]
            vmeta = matched["meta"] if isinstance(matched["meta"], dict) else json.loads(matched["meta"])
        else:
            gender = spec.get("gender") or "neutral"
            pool_ = _PRESETS.get(gender) or _PRESETS["neutral"]
            n_same = await conn.fetchval(
                "SELECT count(*) FROM kb_entries WHERE kind='voice' AND meta->>'gender'=$1", gender
            )
            # 数字年龄：角色卡手设 > LLM 推定；有数字时年龄档位以特征库 age_range 命中为准
            try:
                age_years = int(el_years or spec.get("age_years") or 0) or None
            except (TypeError, ValueError):
                age_years = None
            age_cls = spec.get("age") or "adult"
            if age_years:
                age_cls = await age_class_for_years(conn, age_years, gender) or age_cls
            vmeta = {
                "provider": "openai_compat", "voice_type": pool_[int(n_same or 0) % len(pool_)],
                "ref_audio_url": None, "sample_audio_url": None, "image_url": None,
                "gender": gender, "age": age_cls, "age_years": age_years,
                "vocal_mode": spec.get("vocal_mode") or "speech",
                "language": spec.get("language") or "",
                "emotions": spec.get("emotions") or ["neutral"], "params": spec.get("params") or {},
                "designed_for": elem["name"],
            }
            tags = list(spec.get("tags") or [])
            atag = _age_tag(vmeta["age"], gender)  # 年龄标签兜底（LLM 常漏标，筛选靠它）
            if atag and atag not in tags:
                tags.append(atag)
            row = await conn.fetchrow(
                "INSERT INTO kb_entries (scope, project_id, kind, category, name, description, content, tags, meta) "
                "VALUES ('project', $1, 'voice', 'timbre', $2, $3, $3, $4, $5::jsonb) RETURNING id, name",
                project_id, spec.get("name") or f"{elem['name']}·专属音色",
                spec.get("description") or "", tags,
                json.dumps(vmeta, ensure_ascii=False),
            )
            voice_id, voice_name = row["id"], row["name"]
        # 绑定到角色（binding 冗余 vocal_mode/language 供音频预检零 join 读取）
        # + 回写 voice_profile（LLM 选角终判为准，覆盖生成期/补标注的旧值）
        final_mode = spec.get("vocal_mode") or vmeta.get("vocal_mode") or "speech"
        final_lang = spec.get("language") or vmeta.get("language") or ""
        binding = {"kb_voice_id": voice_id, "name": voice_name,
                   "provider": vmeta.get("provider"), "voice_type": vmeta.get("voice_type"),
                   "vocal_mode": final_mode, "language": final_lang}
        voice_profile = {**vp0, "vocal_mode": final_mode, "language": final_lang,
                         "timbre_brief": (spec.get("description") or "")[:60] or vp0.get("timbre_brief", ""),
                         "source": "voice_casting"}
        await conn.execute(
            "UPDATE content_elements SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
            element_id,
            json.dumps({"voice": binding, "voice_profile": voice_profile}, ensure_ascii=False),
        )
    # ── 尽力生成试听样本（TTS 余额不足等不阻塞捏音色本身；用角色基线语速，见 prosody.py）──
    if not matched and vmeta.get("voice_type"):
        try:
            from .prosody import resolve_prosody

            pr = resolve_prosody(vmeta)
            text, instruct = sample_plan(vmeta)  # 按发声模式选文案（call/hybrid 用拟声长音）
            # speech：sample_plan 无 instruct，回落 persona+真实感锚（与 audio_precheck 同链路，预览≈本番）
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
                        voice_id, json.dumps(vmeta, ensure_ascii=False),
                    )
                binding["sample_audio_url"] = url
        except Exception as e:  # noqa: BLE001
            log.warning("试听样本生成失败（不阻塞）: %s", e)
    return {"binding": binding, "spec": spec, "reused": bool(matched)}


# ═══════════ 存量角色批量补标注发声形态 ═══════════

_VOICE_PROFILE_SYS = """你是选角导演。为下列角色批量判定发声形态（存量角色卡补标注）。
判定依据是角色在故事中的实际呈现形态而非物种——拟人化动物照样 speech（如疯狂动物城）；
「对白证据」是分镜里的真实台词统计，证据显示有文字台词的角色不能判 call/silent。
- vocal_mode: speech(说人话)/call(真动物只发叫声)/hybrid(鸣叫为主偶有传意)/silent(不发声)
- language: 如"中文人声"/"动物叫声(狼嚎)"/"自创语言(小黄人式叽喳)"，call/silent 填"无"或叫声描述
- timbre_brief: 音色气质一句话（如"低哑沧桑的中年男声"/"清脆急促的鸟鸣"）
严格输出 JSON：
{"profiles": [{"name":"角色名（与输入完全一致）","vocal_mode":"speech","language":"","timbre_brief":""}]}"""


async def annotate_voice_profiles(pool: asyncpg.Pool, project_id: int) -> dict[str, Any]:
    """为缺 voice_profile 的存量角色一次 LLM 批量判定发声形态并合并落库。幂等、只增不改已标注。"""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, brief, meta FROM content_elements "
            "WHERE project_id=$1 AND kind='character' ORDER BY id", project_id,
        )
        pending = []
        for r in rows:
            m = r["meta"] if isinstance(r["meta"], dict) else json.loads(r["meta"] or "{}")
            if isinstance(m.get("voice_profile"), dict) and m["voice_profile"].get("vocal_mode"):
                continue
            ev = await _vocal_evidence(conn, project_id, r["name"])
            pending.append({"id": r["id"], "name": r["name"], "brief": r["brief"] or "",
                            "外貌": m.get("外貌提示词", ""), "evidence": ev})
    if not pending:
        return {"annotated": [], "skipped": len(rows)}
    user = "# 待标注角色\n" + "\n".join(
        f"- {p['name']}：{p['brief']}｜外貌：{p['外貌'][:80]}｜对白证据：{json.dumps(p['evidence'], ensure_ascii=False)}"
        for p in pending
    )
    data = await llm.chat_json(_VOICE_PROFILE_SYS, user, max_tokens=1600)
    by_name = {(p.get("name") or "").strip(): p for p in data.get("profiles") or []}
    annotated = []
    async with pool.acquire() as conn:
        for p in pending:
            prof = by_name.get(p["name"])
            if not prof or prof.get("vocal_mode") not in ("speech", "call", "hybrid", "silent"):
                continue
            vp = {"vocal_mode": prof["vocal_mode"], "language": prof.get("language") or "",
                  "timbre_brief": prof.get("timbre_brief") or "", "source": "backfill"}
            await conn.execute(
                "UPDATE content_elements SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
                p["id"], json.dumps({"voice_profile": vp}, ensure_ascii=False),
            )
            annotated.append({"name": p["name"], **vp})
    return {"annotated": annotated, "skipped": len(rows) - len(pending)}
