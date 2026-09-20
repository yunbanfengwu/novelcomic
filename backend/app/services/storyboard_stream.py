"""流式粗拆（2026-07-13）：LLM 按固定 Markdown 逐镜输出（流式逐 token 接收），
增量解析——识别到完整一镜块立即回调（落库+SSE 广播：一镜存一镜、前端实时显示一镜）。

为什么定死 MD 而不是 JSON：JSON 必须收到闭合括号才能解析（天然反流式），
截断=整包作废；MD 以「## 镜N」为块边界，每块独立可解析，截断只损失最后半镜。
解析器按下方模板契约容错（全/半角冒号、加粗星号、字段别名、续行并入上一字段）。
"""
import logging
import re
from typing import Any, Awaitable, Callable

from .. import llm

log = logging.getLogger("storyboard_stream")

# 固定 MD 输出模板（骨架字段与 JSON 版同构；解析容错但模板必须唯一——这是流式契约）
COARSE_MD_FORMAT = """严格按以下 Markdown 模板逐镜输出：从「## 镜1」开始，每镜一个区块、每字段独占一行；
不得输出 JSON、代码围栏、前言、总结或任何模板之外的文本。
## 镜1
- 场景: 场景名/时间/地点
- 场景要素: 与本镜地点一致的场景要素名（清单中没有一致项必须填 无）
- 景别: 只能取枚举之一
- 时长: 4
- 出场: 角色甲、角色乙（只能取「项目角色要素」清单原名，顿号分隔；无出场角色填 无）
- 动作: 主体单动作一句话（带速度感，如"猛地转身"）
- 对白: 说话人：台词（多句用 / 分隔；无对白填 无）
- 衔接: 连贯 或 跳切（本镜开场画面是否与上一镜结尾在同场景同时刻连续承接——上一镜收尾即本镜开场、动作/走位连续为 连贯；换场景/时间跳跃/换叙事视角为 跳切；镜1恒为 跳切；拿不准填 跳切）
- 画面: 画面梗概一段（60-100字：忠实原文的动作/体位/神态/环境与关键道具细节，宁可照抄原文具体描写，不要笼统概括）"""

_HEAD = re.compile(r"^#{1,4}\s*镜\s*(\d+)\D*$", re.M)
_FIELD = re.compile(r"^\s*[-*]?\s*\*{0,2}([^:：*\s][^:：*]{0,11}?)\*{0,2}\s*[:：]\s*(.*)$")
_KEYMAP = {
    "场景": "scene", "场景要素": "scene_element", "景别": "scale", "时长": "duration_s",
    "出场": "characters", "出场角色": "characters", "角色": "characters",
    "动作": "action", "对白": "dialogue", "台词": "dialogue",
    "衔接": "link_prev", "承接": "link_prev",
    "画面": "description", "画面梗概": "description", "描述": "description",
}
_APPEND_KEYS = ("description", "dialogue", "action")  # 换行续写并入上一字段


def _clean(v: str) -> str:
    return v.strip().strip("*").strip()


def parse_md_shot(block: str) -> dict[str, Any] | None:
    """一镜的 MD 区块 → 骨架字典。块首行须是「## 镜N」；缺关键字段返回 None（丢弃碎块）。"""
    lines = block.strip().splitlines()
    if not lines:
        return None
    head = _HEAD.match(lines[0].strip())
    if not head:
        return None
    shot: dict[str, Any] = {"shot_no": int(head.group(1))}
    last_key: str | None = None
    for raw in lines[1:]:
        m = _FIELD.match(raw)
        key = _KEYMAP.get(_clean(m.group(1))) if m else None
        if key:
            shot[key] = _clean(m.group(2))
            last_key = key
        elif raw.strip() and last_key in _APPEND_KEYS:
            shot[last_key] = f"{shot[last_key]}{raw.strip()}"
    # 类型归一：与 JSON 版粗拆同构（时长整数、出场列表、"无"语义）
    d = re.search(r"\d+", str(shot.get("duration_s") or ""))
    shot["duration_s"] = int(d.group()) if d else 4
    chars = _clean(str(shot.get("characters") or ""))
    shot["characters"] = ([] if chars in ("", "无") else
                          [c.strip() for c in re.split(r"[、，,/]", chars) if c.strip()])
    shot.setdefault("dialogue", "无")
    shot.setdefault("scene_element", "无")
    # 衔接标记归一：LLM 输出「连贯/跳切」→ bool（缺失/异样值一律按跳切，宁断勿错接）
    shot["link_prev"] = "连贯" in str(shot.get("link_prev") or "")
    if not (shot.get("scene") or shot.get("action") or shot.get("description")):
        return None  # 只有标题没有正文的碎块（截断尾巴）不算一镜
    return shot


async def stream_coarse_md(
    system: str, user: str,
    on_shot: Callable[[dict[str, Any], int], Awaitable[None]],
) -> list[dict[str, Any]]:
    """流式接收 MD 粗拆：出现下一个「## 镜N」标题即判定上一块完整 → 解析并回调
    on_shot(shot, 已解析镜数)；流结束后冲洗最后一块。返回全部解析成功的镜。"""
    buf = ""
    shots: list[dict[str, Any]] = []

    async def emit(block: str) -> None:
        s = parse_md_shot(block)
        if s:
            shots.append(s)
            await on_shot(s, len(shots))

    async for delta in llm.chat_stream(system, user, temperature=0.4, max_tokens=6000):
        buf += delta
        while True:  # 单个 delta 可能带出多个完整块（提供商大颗粒转发）
            heads = list(_HEAD.finditer(buf))
            if len(heads) < 2:
                break
            await emit(buf[heads[0].start():heads[1].start()])
            buf = buf[heads[1].start():]
    heads = list(_HEAD.finditer(buf))
    if heads:
        await emit(buf[heads[0].start():])
    log.info("流式粗拆解析 %d 镜", len(shots))
    return shots
