"""知识召回 + 提示词装配（核心原则2：prompt 是编译产物）。"""
import json
from typing import Any

import asyncpg

from . import embeddings

# kb_entries 是否有 embedding 列（无 pgvector 环境如本地原生 PG 为 False）——查一次缓存
_HAS_EMBED_COL: bool | None = None


async def _embed_col_exists(conn: asyncpg.Connection) -> bool:
    global _HAS_EMBED_COL
    if _HAS_EMBED_COL is None:
        _HAS_EMBED_COL = bool(await conn.fetchval(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='kb_entries' AND column_name='embedding'"))
    return _HAS_EMBED_COL


async def recall_blocks(
    conn: asyncpg.Connection,
    query_text: str,
    categories: list[str],
    project_id: int | None = None,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """按内容召回专业提示词块：向量语义 + pg_trgm 混合排序。

    - 有 pgvector 且能取到 query 向量：score = 0.6*余弦 + 0.4*trgm，地板 vec≥0.35 或 trgm≥0.12
    - 无 pgvector（本地）/嵌入服务异常：自动降级为纯 trgm（地板 0.12），绝不阻断生成
    公共知识(scope=global) 全项目可用；项目知识(scope=project) 限本项目。
    """
    qvec: str | None = None
    if await _embed_col_exists(conn):
        try:
            v = await embeddings.embed_one(query_text)
            qvec = embeddings.to_pgvector(v) if v else None
        except Exception:  # noqa: BLE001 — 嵌入服务异常时降级 trgm，绝不阻断生成
            qvec = None

    if qvec is not None:
        # 混合：无 embedding 的行（如项目级新块）vec_sim 记 0，仍靠 trgm 参与
        rows = await conn.fetch(
            """
            WITH scored AS (
              SELECT id, category, name, description, content, meta, weight,
                     similarity(name || ' ' || description, $1) AS trgm_sim,
                     CASE WHEN embedding IS NOT NULL
                          THEN 1 - (embedding <=> $5::vector) ELSE 0 END AS vec_sim
              FROM kb_entries
              WHERE kind='prompt_block' AND enabled
                AND category = ANY($2::text[])
                AND (scope='global' OR (scope='project' AND project_id=$3))
            )
            SELECT id, category, name, description, content, meta,
                   (0.6*vec_sim + 0.4*trgm_sim) AS sim
            FROM scored
            WHERE vec_sim >= 0.35 OR trgm_sim >= 0.12
            ORDER BY sim DESC, weight DESC
            LIMIT $4
            """,
            query_text, categories, project_id, top_k * len(categories), qvec,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id, category, name, description, content, meta,
                   similarity(name || ' ' || description, $1) AS sim
            FROM kb_entries
            WHERE kind='prompt_block' AND enabled
              AND category = ANY($2::text[])
              AND (scope='global' OR (scope='project' AND project_id=$3))
              AND similarity(name || ' ' || description, $1) > 0.12
            ORDER BY sim DESC, weight DESC
            LIMIT $4
            """,
            query_text, categories, project_id, top_k * len(categories),
        )
    # 相似度地板：不相关时宁可不召回（如"练字"误配"武打"），画风类兜底由调用方处理
    # 每 category 取 top_k
    picked: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        cat = r["category"]
        bucket = picked.setdefault(cat, [])
        if len(bucket) < top_k:
            meta = r["meta"] if isinstance(r["meta"], dict) else json.loads(r["meta"])
            bucket.append({
                "category": cat, "name": r["name"], "content": r["content"],
                "positive": meta.get("positive", ""), "negative": meta.get("negative", ""),
            })
    return [b for bs in picked.values() for b in bs]


async def get_block(conn: asyncpg.Connection, category: str, name: str) -> dict[str, Any] | None:
    """精确取一块（如按分镜标注的景别/运镜名直取）。"""
    r = await conn.fetchrow(
        "SELECT name, category, content, meta FROM kb_entries "
        "WHERE kind='prompt_block' AND category=$1 AND name=$2 AND enabled LIMIT 1",
        category, name,
    )
    if not r:
        return None
    meta = r["meta"] if isinstance(r["meta"], dict) else json.loads(r["meta"])
    return {
        "category": r["category"], "name": r["name"], "content": r["content"],
        "positive": meta.get("positive", ""), "negative": meta.get("negative", ""),
    }


async def style_anchor_named(conn: asyncpg.Connection | asyncpg.Pool,
                             art_style: str) -> tuple[str, str]:
    """画风锚词单一实现（带条目名）：art_style 存「名称——内容」，按名称前缀匹配画风库取
    positive（场景中性，不含铁道/便利店等烤死场景的内容词）；无库条目退回画风原文。
    封面 / 关键视觉 / 预告片共用，禁止再各写一份 SQL。

    返回 (锚词, 画风库条目名)。条目名给调用方做「这段文案体现画风了没」的校验用——
    匹配谓词只此一处，调用方不许自己再写一遍 LIKE。"""
    style = art_style or ""
    r = await conn.fetchrow(
        "SELECT name, meta, content FROM kb_entries WHERE kind='prompt_block' AND category='style' "
        "AND enabled AND $1 LIKE name || '%' ORDER BY length(name) DESC LIMIT 1", style)
    if not r:
        return style, ""
    meta = r["meta"] if isinstance(r["meta"], dict) else json.loads(r["meta"] or "{}")
    return (meta.get("positive") or r["content"] or style), (r["name"] or "")


async def style_anchor(conn: asyncpg.Connection | asyncpg.Pool, art_style: str) -> str:
    """画风锚词（只要锚词本身）。薄封装，实现在 style_anchor_named。"""
    anchor, _ = await style_anchor_named(conn, art_style)
    return anchor


async def project_preferences(
    conn: asyncpg.Connection, project_id: int, agent_code: str | None = None
) -> list[str]:
    """项目级用户偏好（soft）：项目全员 + 指定员工的，级联注入。"""
    rows = await conn.fetch(
        """
        SELECT content FROM project_memories
        WHERE project_id=$1 AND kind='soft' AND enabled
          AND (agent_code IS NULL OR agent_code=$2)
        ORDER BY agent_code NULLS FIRST, weight DESC
        """,
        project_id, agent_code,
    )
    return [r["content"] for r in rows]


def assemble_image_prompt(
    blocks: list[dict[str, Any]],
    scene_desc: str,
    extra_positive: str = "",
) -> tuple[str, str]:
    """装配最终生图提示词：场景描述 + 各知识块 positive，负面词合并。"""
    positives = [scene_desc]
    negatives: list[str] = []
    for b in blocks:
        if b.get("positive"):
            positives.append(b["positive"])
        if b.get("negative"):
            negatives.append(b["negative"])
    if extra_positive:
        positives.append(extra_positive)
    # 逗号级去重：多个知识块携带同一锚词（如 shallow depth of field 出现3次）会被质检判冗余
    joined = ", ".join(p for p in positives if p)
    deduped = ", ".join(dict.fromkeys(t.strip() for t in joined.split(",") if t.strip()))
    return deduped, ", ".join(n for n in negatives if n)
