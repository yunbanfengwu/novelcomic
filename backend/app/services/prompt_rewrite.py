"""按质检问题**手动重写**出图提示词（画布生成条里的「重新生成」）。

与自动重试那条路**刻意不同**，这是新增能力不是复制：
- 自动重试（`workflow._qc_prompt_loop`）用的是质检技能自己返回的「重构提示词」字段。
  那是给引擎内部回退用的——判据一严就会出现「判不过又给不出可用重写」的死循环，
  实测表现为轮轮 0 分（用户 2026-08-01 反馈）。
- 手动重写走这里：输入是**用户在生成条里看到的那段全文** + 关联要素上下文 + 质检原因，
  由一次独立的模型调用产出修订版。用户改过的内容因此能被尊重，而不是被引擎按
  自己那份 user 段重算一遍。

一条硬规矩：**结构段原样保留**。提示词末尾那些画风锚、质量词、禁令（no text /
no protagonist …）是系统锁死的护栏，重写只许动叙事描述。写进 system 里，
不靠调用方自觉。
"""
from __future__ import annotations

from typing import Any

import asyncpg

from .. import llm

SYSTEM = """你是出图提示词修订师。给你一段用于生成图片的完整提示词、它没通过质检的原因，
以及这张图关联的要素设定。请按质检原因逐条修订这段提示词。

硬规则：
1. **只改叙事描述**（空间格局、材质光照、时段氛围、构图这类）。提示词里的画风锚词、
   质量词、以及各种禁令（如 no text / no protagonist / 禁止出现人物 等）**必须原样保留**，
   一个字都不许删改——它们是系统护栏，不是可优化的内容。
2. 逐条落实质检原因，不要引入新问题；质检没提到的正确内容保持不动。
3. 不要把质检原因本身写进提示词——那是说给质检看的话，出图模型会当画面内容画进去。
4. 直接输出修订后的**提示词全文**，不要任何解释、标题、前后缀。"""


async def _element_context(pool: asyncpg.Pool, element_id: int | None) -> str:
    """关联要素的设定：重写要知道这张图画的是什么，否则只能对着文字空转。"""
    if not element_id:
        return ""
    row = await pool.fetchrow(
        "SELECT name, kind, coalesce(brief,'') AS brief, meta FROM content_elements WHERE id=$1",
        element_id)
    if not row:
        return ""
    meta: dict[str, Any] = row["meta"] if isinstance(row["meta"], dict) else {}
    bits = [f"名称：{row['name']}（{row['kind']}）"]
    if row["brief"]:
        bits.append(f"设定：{row['brief']}")
    for k in ("外貌提示词", "sheet_prompt_anchor"):
        if meta.get(k):
            bits.append(f"{k}：{meta[k]}")
    return "\n".join(bits)


async def rewrite_by_issues(pool: asyncpg.Pool, *, prompt: str, issues: list[str],
                            element_id: int | None = None, extra: str = "") -> str:
    """提示词 + 质检原因（+ 关联要素）→ 修订后的提示词全文。

    模型没给出内容时**原样返回旧提示词**，绝不返回空串——生成条被清空比不改更糟。"""
    if not prompt.strip():
        return prompt
    ctx = await _element_context(pool, element_id)
    parts = [f"【当前提示词】\n{prompt.strip()}"]
    if issues:
        parts.append("【质检未通过的原因】\n" + "\n".join(f"- {x}" for x in issues if x))
    if ctx:
        parts.append(f"【关联要素设定】\n{ctx}")
    if extra.strip():
        parts.append(f"【额外要求】\n{extra.strip()}")
    out = await llm.chat_text(SYSTEM, "\n\n".join(parts), temperature=0.4)
    return out.strip() or prompt
