"""卷（volume）分组：卷=content_nodes(kind='volume')，章节 parent_id 指向所属卷。

设计要点——**不建卷就没有卷**：
- 默认项目没有任何卷节点，章节 parent_id 为 NULL，系统视其为隐式「第一卷」，UI 不显示卷头；
- 用户想开新卷（第二部/第二卷）时才显式建卷：此时把既有散章收编为真实的『第一卷』，
  再追加空的新卷。从此该项目进入「分卷」形态，目录按卷分组展示。
- 不做数据迁移：历史项目无卷即隐式卷1，一切照旧。

核心要素（content_elements）始终项目级、跨卷共享；卷只给旗下章节提供一份「可覆盖的生成
设置」——art_style/writing_style（顶层列）与 aspect_ratio/element_kinds（config 内）。
卷未覆盖的字段继承项目原值（浅合并，改项目自动跟随）。覆盖存 content_nodes.meta（扁平、
与项目字段同名）：{"art_style": "...", "writing_style": "...", "aspect_ratio": "9:16", "element_kinds": [...]}
空串/缺省/空数组 = 不覆盖（继承项目）。
"""
import json
from typing import Any

import asyncpg

# 卷可覆盖的字段：顶层列 + config 内键（与 content_projects 的落点对应）
OVERRIDE_COLS = ("art_style", "writing_style")
OVERRIDE_CFG = ("aspect_ratio", "element_kinds")

_CN_NUM = "零一二三四五六七八九十"


def cn_ordinal(n: int) -> str:
    """卷序号中文名：1→第一卷 … 20→第二十卷；超 20 退回「第N卷」。"""
    if n <= 0:
        return f"第{n}卷"
    if n <= 10:
        return f"第{_CN_NUM[n]}卷"
    if n < 20:
        return f"第十{_CN_NUM[n - 10]}卷"
    if n == 20:
        return "第二十卷"
    return f"第{n}卷"


def _jsonb(v: Any) -> Any:
    return v if isinstance(v, (dict, list)) else (json.loads(v) if v else {})


def apply_overrides(project: asyncpg.Record | dict[str, Any], meta: dict[str, Any] | None) -> dict[str, Any]:
    """把卷覆盖叠加到 project 副本：art_style/writing_style 覆盖顶层，
    aspect_ratio/element_kinds 覆盖 config。空覆盖=继承项目。返回全新 dict（不改原行）。"""
    p = dict(project)
    p["config"] = dict(_jsonb(p.get("config")))
    ov = meta or {}
    for f in OVERRIDE_COLS:
        v = ov.get(f)
        if isinstance(v, str) and v.strip():
            p[f] = v.strip()
    for f in OVERRIDE_CFG:
        v = ov.get(f)
        if v not in (None, "", []):
            p["config"][f] = v
    return p


def clean_overrides(meta: dict[str, Any] | None) -> dict[str, Any]:
    """从任意 meta 里提出干净的卷覆盖项（去空、只留可覆盖字段），供 API 回显。"""
    ov = meta or {}
    out: dict[str, Any] = {}
    for f in OVERRIDE_COLS:
        v = ov.get(f)
        if isinstance(v, str) and v.strip():
            out[f] = v.strip()
    for f in OVERRIDE_CFG:
        v = ov.get(f)
        if v not in (None, "", []):
            out[f] = v
    return out


async def last_volume_id(conn: asyncpg.Connection | asyncpg.Pool, project_id: int) -> int | None:
    """项目「最后一卷」id（续写/新章落点）；无卷返回 None（=隐式卷1，章节 parent_id 留空）。"""
    return await conn.fetchval(
        "SELECT id FROM content_nodes WHERE project_id=$1 AND kind='volume' "
        "ORDER BY seq DESC, id DESC LIMIT 1", project_id,
    )


async def effective_for_chapter(
    conn: asyncpg.Connection | asyncpg.Pool,
    project: asyncpg.Record | dict[str, Any],
    chapter_node_id: int,
) -> dict[str, Any]:
    """返回叠加了「章节所属卷覆盖」的 project 副本。无卷（隐式卷1）/无覆盖=项目原值（config 归一为 dict）。"""
    vol = await conn.fetchrow(
        "SELECT v.meta FROM content_nodes ch JOIN content_nodes v ON v.id = ch.parent_id "
        "WHERE ch.id=$1 AND v.kind='volume'", chapter_node_id,
    )
    return apply_overrides(project, _jsonb(vol["meta"]) if vol else {})
