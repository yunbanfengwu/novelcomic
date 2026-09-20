"""单镜生产链的统一装配与投影（2026-07-30 建立，「编排 ↔ 实际执行」对齐）。

同一个 step 无论从哪里触发，入队 payload 必须是同一份——此前多个触发方各写各的：
画布带上 meta 里的提示词与手编标记（prompt_overridden），另一边只带 ctx 剩余字段，
结果是「一边尊重手编提示词、另一边把它冲掉」这类行为漂移。装配收敛到这里之后，
api/shots.py 的画布节点执行只调这一份，永远不再各写各的。

另一半是投影：镜级生产画布要展示 step 内置守卫链（_shot_gen_before 那串），来源必须是
STEPS 注册表的声明式元数据（dep_kinds / soft_deps / before_notes / next_notes），
不能在别处手写近似——手写的那份已经漂移过一次，这也是本次对齐的起因。
"""
from __future__ import annotations

import json
from typing import Any

import asyncpg

from . import flow, volumes


class CanvasError(Exception):
    """画布装配失败（对调用方可预期：分镜不存在 / step 不归本装配管）。"""


# 生产画布固定节点 → (step kind, gen_prompts 的 only 侧)。
# qc 节点与对应提示词节点同链：质检就在 gen_prompts 的 next 里跑，重跑质检=重跑装配。
NODE_STEPS: dict[str, tuple[str, str | None]] = {
    "cuts": ("gen_shot_storyboard", None),
    "storyboard_script": ("gen_shot_storyboard", None),
    "image_prompt": ("gen_prompts", "image"),
    "image_qc": ("gen_prompts", "image"),
    "video_prompt": ("gen_prompts", "video"),
    "video_qc": ("gen_prompts", "video"),
    "keyframe": ("gen_keyframe", None),
    "video": ("gen_video", None),
}

# 按 step kind 反查是否归本装配管（画布节点执行走这里取 payload）。
_PAYLOAD_KINDS = {kind for kind, _ in NODE_STEPS.values()}


def covers(kind: str) -> bool:
    return kind in _PAYLOAD_KINDS


def _meta(row: Any) -> dict[str, Any]:
    m = row["meta"]
    return m if isinstance(m, dict) else (json.loads(m) if m else {})


async def step_payload(pool: asyncpg.Pool, kind: str, project_id: int | None,
                       shot_id: int | None, only: str | None = None) -> dict[str, Any]:
    """镜级 step 的入队 payload——与生产画布点「重跑」完全同一份。"""
    if kind == "gen_shot_storyboard":
        return {}
    if kind == "gen_prompts":
        return {"only": only} if only else {}
    shot = await pool.fetchrow(
        "SELECT parent_id, meta FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id)
    if not shot:
        raise CanvasError("选中的不是镜头（章/卷跑不了单镜步骤）——请在运行上下文里选到具体镜")
    meta = _meta(shot)
    if kind == "gen_keyframe":
        from . import references
        return {
            "prompt": meta.get("image_prompt"),
            "prompt_overridden": bool(meta.get("image_prompt_edited")),
            "reference_images": await references.resolved_images(
                pool, project_id=project_id, subject_kind="shot", subject_id=shot_id,
                purpose="image"),
        }
    if kind == "gen_video":
        from . import references
        proj = await pool.fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
        eff = await volumes.effective_for_chapter(pool, proj, shot["parent_id"]) if proj else {}
        ratio = (eff.get("config") or {}).get("aspect_ratio") or "16:9"
        prompt = meta.get("video_prompt")
        return {
            "prompt": prompt,
            "prompt_overridden": bool(meta.get("video_prompt_edited")),
            "prompt_textonly": meta.get("video_prompt_textonly") or prompt,
            "duration_s": meta.get("duration_s", 5),
            "ratio": ratio,
            "reference_images": await references.resolved_images(
                pool, project_id=project_id, subject_kind="shot", subject_id=shot_id,
                purpose="video"),
        }
    raise CanvasError(f"step {kind!r} 不归镜级生产画布装配")


# step_chain 条目 ↔ 生产画布固定节点：运行态用画布节点的真实状态点亮编排骨架，
# 两张图共用同一份状态源。guard:i 按 before_notes 下标对应，改 notes 时必须同步这里
# （都在本仓库后端，同一次提交内改）。
_CHAIN_NODES: dict[str, dict[str, str]] = {
    "gen_keyframe": {
        "dep:gen_shot_storyboard": "cuts",  # 嵌套依赖（gen_prompts 的前置）
        "dep:gen_prompts": "image_prompt",
        "soft:gen_element_sheet": "references",
        "guard:0": "image_prompt",   # 缺首帧提示词 → 派 gen_prompts
        "guard:1": "continuity",     # 连续性守卫
        "guard:2": "references",     # 取本镜出场要素（预检：缺则模型补建）
        "guard:3": "continuity",     # 场景站位兜底
        "guard:4": "references",     # 补要素设定图
        "guard:5": "references",     # 重装配参考图 + 短引用
        "guard:6": "image_qc",       # 提示词九维质检
        "guard:7": "keyframe",       # wide 软化 + 角色硬闸（生图前最后一道）
        "write:0": "keyframe",       # 落附件 + 回写 keyframe_url
        "write:1": "keyframe",       # 接缝回填
    },
}

# 编排画布的展示顺序（生产画布逻辑：备料要素/设定图 → 连续性/站位 → 分镜剧本 →
# 组合提示词 → 质检 → 出图守卫）。执行顺序仍以 Step 代码为准，这里只管画得跟
# 生产画布一一对应。没列到的条目（write/notify 等）按原相对顺序排在后面。
_CHAIN_ORDER: dict[str, list[str]] = {
    "gen_keyframe": [
        "guard:2",                   # 取本镜出场要素
        "soft:gen_element_sheet",
        "guard:4",                   # 补要素设定图
        "guard:1",                   # 连续性守卫
        "guard:3",                   # 场景站位兜底
        "dep:gen_shot_storyboard",   # 生成分镜剧本
        "dep:gen_prompts",           # 组合提示词（a.shot-prompt 吸收到此）
        "guard:0",
        "guard:5",
        "guard:6",
        "guard:7",
    ],
}

# 依赖 step 的中文名（对齐生产画布节点文案）
_STEP_CN = {
    "gen_shot_storyboard": "生成分镜剧本", "gen_prompts": "组合提示词",
    "gen_keyframe": "分镜首图", "gen_last_keyframe": "尾帧", "gen_video": "成品视频",
    "gen_element_sheet": "要素设定图", "scene_blocking": "场景空间规划",
    "gen_scene_empty": "空场景基准图", "gen_scene_sheet": "场景站位图",
}


def _dep_label(kind: str) -> str:
    cn = _STEP_CN.get(kind)
    return f"依赖 {cn}（{kind}）" if cn else f"依赖 {kind}"


def step_chain(kind: str, notify: list[str] | None = None) -> list[dict[str, Any]]:
    """step 内置执行链投影：编排画布只读节点的数据源（与前端约定的格式）。

    条目直接取自 Step 注册表的声明式元数据，不手写、不近似——步骤代码里的
    before_notes/next_notes 改了，这里自动跟着变。格式：
    [{id, label, kind: 'guard'|'dep'|'write'|'notify', node?}]；
    node = 生产画布固定节点 id，运行态按它取真实状态（状态不在本响应里）。
    """
    from . import steps  # noqa: F401 — 确保 STEPS 注册表已装载（api 进程惰性首触时）

    step = flow.STEPS.get(kind)
    if not step:
        return []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def dep(d: str) -> None:
        if f"dep:{d}" in seen:
            return
        seen.add(f"dep:{d}")
        items.append({"id": f"dep:{d}", "label": _dep_label(d), "kind": "dep"})

    for d in step.dep_kinds:
        # 展开一层嵌套依赖（gen_prompts → gen_shot_storyboard）：生产画布把
        # 「生成分镜剧本」画成独立节点，编排也要能一一对上
        sub = flow.STEPS.get(d)
        for dd in (sub.dep_kinds if sub else []):
            dep(dd)
        dep(d)
    for d in step.soft_deps:
        items.append({"id": f"soft:{d}",
                      "label": f"{d}（before 就地补，不建独立任务）", "kind": "dep"})
    items.extend({"id": f"guard:{i}", "label": note, "kind": "guard"}
                 for i, note in enumerate(step.before_notes))
    items.extend({"id": f"write:{i}", "label": note, "kind": "write"}
                 for i, note in enumerate(step.next_notes))
    items.extend({"id": f"notify:{t}", "label": t, "kind": "notify"}
                 for t in (notify if notify is not None else ["frontend.refresh"]))
    nodes = _CHAIN_NODES.get(kind, {})
    for it in items:
        n = nodes.get(it["id"])
        if n:
            it["node"] = n
    order = _CHAIN_ORDER.get(kind)
    if order:
        pos = {v: i for i, v in enumerate(order)}
        items = [it for _, it in sorted(
            enumerate(items), key=lambda t: pos.get(t[1]["id"], len(order) + t[0]))]
    return items
