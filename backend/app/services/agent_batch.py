"""批量遍历与「缺才跑」（2026-07-29 新增）。

**批量是节点的属性，不是另一种节点**——「批量角色生成」就是同一个智能体节点把遍历对象
选成「全项目角色」，不需要再拖一个循环节点把它包起来。

「缺才跑」是这里最贵的一个开关：关掉它，一次批量会把已经生成好的产物**全部重跑并覆盖**。
2026-07-28 批量首帧就踩过这个坑，所以默认是开的，且每个遍历源都必须声明「产物存在」怎么判。
"""
from __future__ import annotations

from typing import Any

import asyncpg


class BatchError(Exception):
    """遍历对象解析失败（对调用方可预期）。"""


# 每个遍历源声明三件事：怎么列条目、产物存在怎么判、条目进上下文时叫什么。
# has_artifact 那一列决定 only_missing 过滤谁——写错了会导致「跳过了其实没有产物的对象」。
# 判据与回显 url 由 **同一个字段声明**（_artifact_cols）生成，两列永远一致；
# writes 列=该判据对应的回写落点（agent_next 白名单键），供 run-unit 校验
# 「unit 配的 writes 与批量判据是否对得上」——对不上时下次批量会把已生成的重跑一遍。


def _artifact_cols(expr: str, key: str) -> str:
    """产物判据 + 回显 URL 两列由同一个字段声明派生（缺才跑判据单一来源）。"""
    return f"({expr}->>'{key}') IS NOT NULL AS has_artifact, {expr}->>'{key}' AS url"


SOURCES: dict[str, dict[str, Any]] = {
    "project.characters": {
        "label": "全项目角色", "ctx_key": "element_id", "needs": ("project_id",),
        "writes": "content_elements.meta.sheet_url",
        "sql": f"SELECT id, name AS label, {_artifact_cols('meta', 'sheet_url')} "
               "FROM content_elements WHERE project_id=$1 AND kind='character' ORDER BY id",
    },
    "project.scenes": {
        "label": "全项目场景", "ctx_key": "element_id", "needs": ("project_id",),
        "writes": "content_elements.meta.sheet_url",
        "sql": f"SELECT id, name AS label, {_artifact_cols('meta', 'sheet_url')} "
               "FROM content_elements WHERE project_id=$1 AND kind='scene' ORDER BY id",
    },
    "ctx.characters": {
        "label": "本集出场角色", "ctx_key": "element_id", "needs": ("project_id", "node_id"),
        "writes": "content_elements.meta.sheet_url",
        "sql": "SELECT DISTINCT e.id, e.name AS label, "
               f"  {_artifact_cols('e.meta', 'sheet_url')} "
               "FROM content_elements e JOIN element_appearances a ON a.element_id=e.id "
               "WHERE e.project_id=$1 AND e.kind='character' "
               "  AND (a.node_id=$2 OR a.node_id IN "
               "       (SELECT id FROM content_nodes WHERE parent_id=$2)) ORDER BY e.id",
    },
    "ctx.scenes": {
        "label": "本集出场场景", "ctx_key": "element_id", "needs": ("project_id", "node_id"),
        "writes": "content_elements.meta.sheet_url",
        "sql": "SELECT DISTINCT e.id, e.name AS label, "
               f"  {_artifact_cols('e.meta', 'sheet_url')} "
               "FROM content_elements e JOIN element_appearances a ON a.element_id=e.id "
               "WHERE e.project_id=$1 AND e.kind='scene' "
               "  AND (a.node_id=$2 OR a.node_id IN "
               "       (SELECT id FROM content_nodes WHERE parent_id=$2)) ORDER BY e.id",
    },
    # 场景两件套（空场景基准图/站位图）是**按场景组**的：payload 要 seg，
    # 组号从 1 开始（seg=0 不存在，实测任务 873 就是拿默认 0 去查直接 blocked）。
    # 缺才跑判的是组条目里的 url，不是章 meta 顶层的键；seg 不在回写定位键里，
    # 这两个源永远没有对应 writes（unit 也不能配）。
    "ctx.scene_groups_empty": {
        "label": "本章场景组（空场景图）", "ctx_key": "seg",
        "needs": ("project_id", "node_id"), "writes": "",
        "sql": "SELECT (g->>'seg')::int AS id, "
               "  coalesce(nullif(g->>'name',''), '场景组 '||(g->>'seg')) AS label, "
               f"  {_artifact_cols('g', 'empty_url')} "
               "FROM content_nodes n "
               "CROSS JOIN LATERAL jsonb_array_elements("
               "  n.meta->'scene_blocking'->'groups') g "
               "WHERE n.project_id=$1 AND n.id=$2 ORDER BY 1",
    },
    "ctx.scene_groups_sheet": {
        "label": "本章场景组（站位图）", "ctx_key": "seg",
        "needs": ("project_id", "node_id"), "writes": "",
        "sql": "SELECT (g->>'seg')::int AS id, "
               "  coalesce(nullif(g->>'name',''), '场景组 '||(g->>'seg')) AS label, "
               f"  {_artifact_cols('g', 'sheet_url')} "
               "FROM content_nodes n "
               "CROSS JOIN LATERAL jsonb_array_elements("
               "  n.meta->'scene_blocking'->'groups') g "
               "WHERE n.project_id=$1 AND n.id=$2 ORDER BY 1",
    },
    "ctx.shots": {
        "label": "本集所有镜头", "ctx_key": "node_id", "needs": ("project_id", "node_id"),
        "writes": "content_nodes.meta.keyframe_url",
        "sql": "SELECT id, coalesce(meta->>'shot_no', seq::text) AS label, "
               f"  {_artifact_cols('meta', 'keyframe_url')} "
               "FROM content_nodes WHERE project_id=$1 AND parent_id=$2 AND kind='shot' "
               "  AND deleted_at IS NULL ORDER BY seq, id",
    },
}


def writes_mismatch(over: str, writes: str) -> str:
    """unit 同时配了 batch 与 writes 时，校验两边判据是否同源。
    返回告警文案（空串=一致或无法判）。不硬报错：writes 还承担回写职责，
    历史配置可能有意写别的键，只提醒不拦截。"""
    src = SOURCES.get(over)
    expect = (src or {}).get("writes") or ""
    if not src or not writes:
        return ""
    if not expect:
        return (f"遍历源「{src['label']}」按组条目判缺才跑，不支持 writes 回写"
                if writes else "")
    if writes != expect:
        return (f"writes={writes} 与遍历源「{src['label']}」的缺才跑判据（{expect}）"
                "不一致：回写后批量仍会视为缺产物重跑")
    return ""


def source_label(over: str) -> str:
    return SOURCES.get(over, {}).get("label", over)


async def resolve(pool: asyncpg.Pool, over: str, *, project_id: int | None,
                  node_id: int | None, only_missing: bool = True) -> dict[str, Any]:
    """把遍历对象展开成条目表。返回 items（要跑的）与 skipped（已有产物被跳过的）。"""
    src = SOURCES.get(over)
    if not src:
        raise BatchError(f"未知的遍历对象 {over!r}")
    ctx = {"project_id": project_id, "node_id": node_id}
    missing = [k for k in src["needs"] if not ctx.get(k)]
    if missing:
        need = "、".join({"project_id": "项目", "node_id": "卷/章"}[k] for k in missing)
        raise BatchError(f"「{src['label']}」需要先在运行上下文里选择{need}")

    args = [ctx[k] for k in src["needs"]]
    rows = await pool.fetch(src["sql"], *args)
    items, skipped = [], []
    for r in rows:
        one = {"id": r["id"], "label": r["label"], "ctx_key": src["ctx_key"],
               "has_artifact": bool(r["has_artifact"]), "url": r["url"]}
        (skipped if (only_missing and one["has_artifact"]) else items).append(one)
    return {"source": over, "label": src["label"], "items": items, "skipped": skipped,
            "total": len(rows)}


def specs() -> list[dict[str, str]]:
    """遍历源清单（给前端下拉用，避免前后端各维护一份枚举）。"""
    return [{"value": k, "label": v["label"]} for k, v in SOURCES.items()]
