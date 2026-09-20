"""人物特征库（kind=prompt_block, category=persona）：年龄段多维画像的渐进式检索。

条目正文按维度分行（「维度名：内容」，一行一维），检索时**按需取维度**——
配音链路只取 声音特征+言语风格，外貌档案只取 体态特征+发量特征，分镜动作只取 动作特征。
渐进式披露（Anthropic 检索纪律）：只把本任务用得上的维度拼进提示词，绝不整表整条目全量吞；
命中不了的维度行为空即跳过，条目可在管理页自由增删维度行，代码零改动。

向量库：条目走 kb_entries.embedding 统一回填（/kb/embed-backfill），供语义召回兜底；
但年龄段是有限枚举，主链路用 meta.age 精确匹配（确定性零 token），向量只服务自由文本检索场景。
"""
import json
from typing import Iterable

import asyncpg

# 维度全集（正文行前缀）；新维度直接在条目正文加行即可，这里只是文档性列举
DIMS = ("声音特征", "言语风格", "体态特征", "发量特征", "动作特征")
# 各消费链路的维度组合（渐进式：一条链路只拿自己那几维）
VOICE_DIMS = ("声音特征", "言语风格")
APPEARANCE_DIMS = ("体态特征", "发量特征")
MOTION_DIMS = ("动作特征",)


def pick_dims(content: str, dims: Iterable[str]) -> str:
    """从多维正文里只挑出指定维度的行（按「维度名：」前缀匹配），保持原顺序。"""
    wanted = tuple(dims)
    lines = [ln.strip() for ln in (content or "").splitlines()]
    return "\n".join(ln for ln in lines if any(ln.startswith(f"{d}：") for d in wanted))


async def trait_for(
    conn: asyncpg.Connection, age: str | None, gender: str | None, dims: Iterable[str],
) -> str | None:
    """按年龄（+性别细分，如少年/少女）精确召回一条，只回指定维度。"""
    if not age:
        return None
    row = await conn.fetchrow(
        "SELECT content FROM kb_entries WHERE kind='prompt_block' AND category='persona' AND enabled "
        "AND meta->>'age'=$1 ORDER BY (meta->>'gender' IS NOT NULL AND meta->>'gender'=$2) DESC, id LIMIT 1",
        age, gender or "",
    )
    return (pick_dims(row["content"], dims) or None) if row else None


async def entry_for_years(
    conn: asyncpg.Connection, years: int, gender: str | None
) -> asyncpg.Record | None:
    """按具体年龄数字命中年龄段条目（meta.age_range=[lo,hi] 闭区间；少年/少女按 gender 细分）。"""
    return await conn.fetchrow(
        "SELECT name, content, meta FROM kb_entries "
        "WHERE kind='prompt_block' AND category='persona' AND enabled "
        "AND (meta->'age_range'->>0)::int <= $1 AND $1 <= (meta->'age_range'->>1)::int "
        "ORDER BY (meta->>'gender' IS NOT NULL AND meta->>'gender'=$2) DESC, id LIMIT 1",
        years, gender or "",
    )


async def trait_for_years(
    conn: asyncpg.Connection, years: int, gender: str | None, dims: Iterable[str],
) -> str | None:
    """数字年龄版 trait_for：按 age_range 命中年龄段，只回指定维度。"""
    row = await entry_for_years(conn, years, gender)
    return (pick_dims(row["content"], dims) or None) if row else None


async def age_class_for_years(conn: asyncpg.Connection, years: int, gender: str | None) -> str | None:
    """数字年龄 → 年龄档位（child/young/adult/middle/elder），来源=命中条目的 meta.age。"""
    row = await entry_for_years(conn, years, gender)
    meta = row["meta"] if row else None
    if isinstance(meta, str):
        meta = json.loads(meta)
    return (meta or {}).get("age")


async def traits_table(conn: asyncpg.Connection, dims: Iterable[str]) -> str:
    """全年龄段表（每条只带指定维度）——供 LLM 尚未定年龄时自行对号（如捏音色/外貌补档）。"""
    rows = await conn.fetch(
        "SELECT name, content FROM kb_entries WHERE kind='prompt_block' AND category='persona' "
        "AND enabled ORDER BY id"
    )
    out = []
    for r in rows:
        body = pick_dims(r["content"], dims).replace("\n", "；")
        if body:
            out.append(f"- {r['name']}：{body}")
    return "\n".join(out)
