"""韵律解析：语速/情绪 = 角色基线 × 场景调制，在 TTS 生成时逐句判定。

行业共识（见 docs/arch/voice-timbre-design.md 五e 节）：
- 音色(timbre)=谁在说，是角色资产，永不随场景变；
- 韵律(prosody)=怎么说（语速/停顿/情绪），按"这一句所在的镜头气氛"逐句决定；
- 若把每句当独立单元合成会得到均匀节奏（业内主要痛点），因此调制依据取
  分镜 mood（本镜情绪功能）——它在拆分镜时就编码了场景气氛，零额外 token。

两条控制通道（CosyVoice2 / 火山 doubao TTS 均支持同构能力）：
1. 数值通道 speed（API 参数，0.25-4.0）：确定性时间缩放，保证时长可预算；
2. 语义通道 instruct（自然语言指令 + <|endofprompt|> 前缀）：驱动模型改变
   停顿/重音/气口，比均匀缩放自然，但时长不可精确预算。
两者叠加：speed 管"多快"，instruct 管"什么气"。
"""
from __future__ import annotations

import re
from typing import Any

# 角色基线：音色条目 params.speed 三档 → 基线语速（"平时正常说话的样子"）
_BASE_SPEED = {"slow": 0.88, "mid": 1.0, "fast": 1.12}
# 年龄兜底档：音色未标 params.speed 时按 meta.age 取（与人物特征库 PERSONA_TRAITS 的默认 params 同源）——
# 全局预置音色 seed 时不带 params，靠这层让"老者慢、少年快"真正落到 speed 数值通道上
_AGE_SPEED_CLASS = {"child": "slow", "young": "fast", "adult": "mid", "middle": "mid", "elder": "slow"}


def age_base_speed(voice_meta: dict[str, Any] | None) -> float:
    """基线语速：params.speed 显式档优先，缺省按 age 兜底，再缺省 mid。"""
    meta = voice_meta or {}
    cls = (meta.get("params") or {}).get("speed") or _AGE_SPEED_CLASS.get(meta.get("age") or "") or "mid"
    return _BASE_SPEED.get(cls, 1.0)

# 角色声线（persona）：把音色资产的"谁在说"翻成一句自然语言发声指令，作为 instruct 常量前缀。
# CosyVoice2 预置音色只有寥寥数条、基础音质接近，靠 <|endofprompt|> 指令让同一底座按角色
# 的年龄/性别/音高/力度差异化发声——这是不切火山/克隆时让"音色贴合角色"的主要抓手。
# 零 token、确定性：全部由音色 meta（gender/age/params）推导，试听与本番配音走同一条链路。
_GENDER_CN = {"male": "男性", "female": "女性", "child": "孩童", "neutral": "中性"}
_AGE_CN = {"child": "孩童", "young": "年轻", "adult": "成年", "middle": "中年", "elder": "苍老"}
_PITCH_CN = {"low": "低沉", "high": "清亮"}
_ENERGY_CN = {"soft": "柔和", "strong": "有力"}


def build_persona(voice_meta: dict[str, Any] | None) -> str | None:
    """由音色 meta 推导一句角色声线指令（如"苍老男性的嗓音，低沉、有力"）。

    仅对人声（speech）生效：call/hybrid/silent 的兽鸣/非语言由 sample_plan 的拟声指令主导，
    不叠加人声 persona。缺字段时逐项跳过，最少也能给出"XX的嗓音"。"""
    meta = voice_meta or {}
    if (meta.get("vocal_mode") or "speech") not in ("speech",):
        return None
    core = "".join(p for p in (_AGE_CN.get(meta.get("age") or ""),
                               _GENDER_CN.get(meta.get("gender") or "")) if p)
    if not core:
        return None
    params = meta.get("params") or {}
    qual = "、".join(q for q in (_PITCH_CN.get(params.get("pitch") or ""),
                                 _ENERGY_CN.get(params.get("energy") or "")) if q)
    return f"{core}的嗓音，{qual}" if qual else f"{core}的嗓音"


def _compose_instruct(persona: str | None, tone: str | None) -> str | None:
    """把角色声线（persona，谁在说）与场景语气（tone，怎么说）合成单条 CosyVoice 指令。
    只有一个 <|endofprompt|> 前缀槽，故两者拼进同一句自然语言指令。

    ⚠️ 注意：当前唯一在线的 TTS 端点（硅基流动 CosyVoice2-0.5B）实测**不消费**该指令而是读出来，
    media.generate_tts 已按 _INSTRUCT_CAPABLE 白名单关闭注入。此处仍照常返回，供未来支持 instruct
    的端点（如火山 doubao）启用；在那之前它只是被 generate_tts 忽略，不会进入音频。"""
    if persona and tone:
        return f"用{persona}，{tone}的语气说这句话"
    if persona:
        return f"用{persona}说这句话"
    if tone:
        return f"用{tone}的语气说这句话"
    return None

# 场景调制表：mood 关键词 → (语速倍率, 语气指令片段)
# 顺序即优先级，命中即止；关键词覆盖拆分镜实际产出的 mood 用语（恐惧铺垫/动作爆点/对话交锋/情绪支点/释放…）
# speed 是本端点唯一有效的韵律通道（instruct 已因 CosyVoice2 读指令而关闭），倍率保持区分度。
_MOOD_RULES: list[tuple[tuple[str, ...], float, str]] = [
    (("爆点", "追逐", "打斗", "搏斗", "危机", "逃"), 1.18, "语气略急、干脆利落"),
    (("质问", "交锋", "对峙", "争执", "愤怒", "怒"), 1.10, "语气强硬、有分量"),
    (("恐惧", "惊", "紧张", "不安", "悬疑"), 1.08, "略微收紧、带一丝不安"),
    (("悲", "哭", "伤感", "离别", "哀"), 0.85, "低沉放缓、略带哽咽"),
    (("庄重", "威严", "仪式", "宣告", "肃穆"), 0.90, "沉稳、字句清晰"),
    (("温柔", "治愈", "安宁", "平静", "释放", "舒缓"), 0.94, "温和平缓"),
    (("回忆", "怀念", "呢喃", "梦"), 0.90, "轻声、像在回忆"),
]

# 句内标点微调：省略号=迟疑放慢；连续叹问=情绪上扬略加速
_HESITATE = re.compile(r"(……|\.{3,}|—+)")
_EXCLAIM = re.compile(r"[！!？?]{2,}|[！!]$")

SPEED_MIN, SPEED_MAX = 0.7, 1.4


def resolve_prosody(
    voice_meta: dict[str, Any] | None, mood: str | None = None, text: str | None = None,
) -> dict[str, Any]:
    """基线(音色 params.speed) × 场景调制(mood 关键词) × 句内标点微调 → {speed, instruct}。

    - 无 mood（如音色库试听样本）→ 基线语速 + 角色声线 persona，即"平时这个角色的说话样子"；
    - 有 mood（真实配音逐句调用）→ persona 叠加场景语气调制，即"这个角色按气氛变速变气"。
    确定性零 token：persona 由音色 meta 推导，mood 在拆分镜时已由 LLM 编码，这里只做规则映射。
    """
    speed = age_base_speed(voice_meta)
    persona = build_persona(voice_meta)
    tone = None

    if mood:
        for keys, factor, t in _MOOD_RULES:
            if any(k in mood for k in keys):
                speed *= factor
                tone = t
                break

    if text:
        if _HESITATE.search(text):
            speed *= 0.95
        elif _EXCLAIM.search(text):
            speed *= 1.04

    return {
        "speed": round(min(max(speed, SPEED_MIN), SPEED_MAX), 2),
        "instruct": _compose_instruct(persona, tone),
    }
