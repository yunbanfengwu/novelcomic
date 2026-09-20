"""画布技能执行与画布 Agent：让 Skill 成为画布上的可执行算子，并让 Agent 操作画布。

- run_skill：取 skill_packages 的 SKILL.md（+ references 渐进披露）作为系统提示，
  带画布上下文调 LLM，返回结构化结果（供技能节点展示与下游引用）。
- plan_canvas：把画布状态序列化给 LLM，返回一串可执行操作指令（前端按指令改画布）。
  Agent 不直接碰数据库——生成/重跑仍走既有 API，画布只负责按指令编排与触发。
"""
from __future__ import annotations

import json
from typing import Any

import asyncpg

from .. import llm

MAX_REF_CHARS = 6000


async def load_skill(pool: asyncpg.Pool, slug: str) -> dict[str, Any]:
    row = await pool.fetchrow(
        "SELECT id,slug,name,description,skill_md,status FROM skill_packages WHERE slug=$1", slug)
    if not row:
        raise ValueError(f"技能不存在：{slug}")
    if row["status"] != "installed":
        raise ValueError(f"技能未启用：{slug}")
    files = await pool.fetch(
        "SELECT path,content FROM skill_package_files WHERE skill_id=$1 ORDER BY path", row["id"])
    return {**dict(row), "files": [dict(f) for f in files]}


def _references(files: list[dict[str, Any]], budget: int = MAX_REF_CHARS) -> str:
    """渐进披露：SKILL.md 之外的 references 拼接到系统提示，超预算截断。"""
    parts: list[str] = []
    used = 0
    for item in files:
        if item["path"] == "SKILL.md":
            continue
        content = (item["content"] or "").strip()
        if not content:
            continue
        chunk = f"\n\n--- {item['path']} ---\n{content}"
        if used + len(chunk) > budget:
            parts.append(f"\n\n--- {item['path']} ---\n（内容过长已省略）")
            continue
        parts.append(chunk)
        used += len(chunk)
    return "".join(parts)


async def run_skill(
    pool: asyncpg.Pool, slug: str, instruction: str,
    context: dict[str, Any] | None = None, temperature: float = 0.4,
) -> dict[str, Any]:
    """按技能包执行一次：返回 {text, data, skill}。data 为技能自定义结构（可空）。"""
    skill = await load_skill(pool, slug)
    system = (
        f"{skill['skill_md']}{_references(skill['files'])}\n\n"
        "以上是你必须遵循的技能说明。请据此完成用户任务。"
        '只输出 JSON：{"text":"给人看的结果正文（可直接用作提示词或说明）",'
        '"data":{"技能自定义的结构化结果，没有就给空对象"},'
        '"notes":["执行要点或风险提示"]}'
    )
    user = (
        f"任务：\n{instruction.strip() or '按技能说明处理下列上下文。'}\n\n"
        f"画布上下文（JSON）：\n{json.dumps(context or {}, ensure_ascii=False)[:12000]}"
    )
    result = await llm.chat_json(system, user, temperature=temperature, max_tokens=3000)
    if not isinstance(result, dict):
        raise ValueError("技能未返回有效 JSON 结果")
    return {
        "skill": {"slug": skill["slug"], "name": skill["name"]},
        "text": str(result.get("text") or "").strip(),
        "data": result.get("data") if isinstance(result.get("data"), dict) else {},
        "notes": [str(x) for x in (result.get("notes") or []) if str(x).strip()],
    }


# 画布 Agent 可下达的操作（前端按此执行；每条都对应既有能力，不新造执行通道）
CANVAS_ACTIONS = """
- set_prompt: 改写生成节点的提示词。参数 {"text":"新提示词全文"}
- run_skill: 调用一个技能并把结果写入新节点。参数 {"slug":"技能 slug","instruction":"给技能的任务"}
- add_node: 新增画布节点。参数 {"kind":"text|image|video","title":"标题","text":"文本节点内容"}
- connect: 连接两个节点。参数 {"from":"节点 id","to":"节点 id"}
- toggle_ref: 启停某个参考素材。参数 {"name":"参考名","enabled":true}
- run_stage: 触发某个环节重跑。参数 {"stage":"basic|scene_fetch|roles_fetch|prompt_assemble"}
- generate: 触发本次生成（出图/出视频）。参数 {}
"""


async def plan_canvas(
    pool: asyncpg.Pool, instruction: str, canvas: dict[str, Any],
) -> dict[str, Any]:
    """画布 Agent：读画布全局状态 + 用户指令 → 返回操作序列（前端执行）。"""
    rows = await pool.fetch(
        "SELECT slug,name,description FROM skill_packages WHERE status='installed' ORDER BY name")
    catalog = "\n".join(f"- {r['slug']}：{r['name']}——{r['description']}" for r in rows)
    system = (
        "你是影视AI生产无限画布上的执行 Agent。你能看到画布全部状态（三区节点、参考分组、"
        "提示词、产物、各环节状态），根据用户指令规划一串画布操作。\n"
        "原则：只做用户要求的事；能用改提示词解决就不要重跑上游；调用技能前先确认技能确实匹配；"
        "缺素材时提示用户而不是编造。\n\n"
        f"可用操作：{CANVAS_ACTIONS}\n"
        f"可用技能：\n{catalog or '（无）'}\n\n"
        '只输出 JSON：{"reply":"给用户的中文说明（做了什么、为什么）",'
        '"actions":[{"type":"操作名","params":{...},"reason":"这一步的目的"}]}'
        "actions 可以为空数组（当只需回答问题时）。"
    )
    user = (
        f"用户指令：\n{instruction.strip()}\n\n"
        f"画布当前状态（JSON）：\n{json.dumps(canvas, ensure_ascii=False)[:16000]}"
    )
    result = await llm.chat_json(system, user, temperature=0.3, max_tokens=3000)
    if not isinstance(result, dict):
        raise ValueError("Agent 未返回有效 JSON")
    actions = [
        a for a in (result.get("actions") or [])
        if isinstance(a, dict) and isinstance(a.get("type"), str)
    ]
    return {"reply": str(result.get("reply") or "").strip(), "actions": actions}
