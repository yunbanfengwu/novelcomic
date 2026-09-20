"""数字员工：新建项目按全局模板 seed，每位员工可挂多个标准 Skills。"""
import json

import asyncpg

# (code, name, role, charter)
DEFAULT_EMPLOYEES: list[tuple[str, str, str, str]] = [
    ("writer", "写作员工", "writer",
     "你是本项目的影视漫剧编剧。职责：按目录故事线把每章写成对白与画面驱动的分集正文（非小说散文）；"
     "写作前必须使用检索到的「最近章节流水账 + 本章相关要素当前状态」保持剧情连贯不飘；"
     "遵循进场晚退场早、每场必有价值转变、对白驱动、展示而非叙述、环境极简的剧集写法；"
     "写完输出本章流水账与要素状态变化。严格遵守项目级写作偏好（文风指令优先级最高）。"),
    ("director", "导演员工", "director",
     "你是本项目的分镜导演。职责：把章节正文拆解为可拍摄的分镜序列（镜号/景别/运镜/时长/"
     "画面/对白/音效）；视觉化优先，抽象情感必须翻译成镜头可拍的具体动作；景别穿插避免"
     "连续三个同景别；每镜画面描述具体到首尾帧可独立绘制。"),
    ("artist", "绘画员工", "artist",
     "你是本项目的分镜画师。职责：为每个分镜装配专业生图提示词（组合画风/景别/运镜/动作"
     "知识块与角色外貌），产出黑白故事板与彩色关键帧。严格保持角色外貌与项目画风一致，"
     "遵守项目级画风偏好。"),
    ("voice", "配音员工", "voice",
     "你是本项目的配音导演。职责：为角色分配声线、为分镜台词与旁白生成配音方案。"),
]


async def seed_employees(conn: asyncpg.Connection, project_id: int) -> None:
    exists = await conn.fetchval(
        "SELECT to_regclass('public.agent_templates') IS NOT NULL")
    templates = await conn.fetch(
        "SELECT code,name,role,charter,model,config FROM agent_templates "
        "WHERE enabled ORDER BY id") if exists else []
    source = templates or [
        {"code": code, "name": name, "role": role, "charter": charter,
         "model": None, "config": {}} for code, name, role, charter in DEFAULT_EMPLOYEES
    ]
    for item in source:
        await conn.execute(
            "INSERT INTO agents (project_id, code, name, role, charter,model,config) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb) ON CONFLICT (project_id, code) DO NOTHING",
            project_id, item["code"], item["name"], item["role"], item["charter"],
            item["model"], json.dumps(item["config"] or {}, ensure_ascii=False),
        )
    if exists:
        await conn.execute(
            "INSERT INTO agent_skill_bindings(agent_id,skill_id) "
            "SELECT a.id,b.skill_id FROM agents a JOIN agent_templates t ON t.code=a.code "
            "JOIN agent_template_skills b ON b.agent_template_id=t.id AND b.enabled "
            "WHERE a.project_id=$1 ON CONFLICT DO NOTHING", project_id)


async def get_employee(conn: asyncpg.Connection, project_id: int, code: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT * FROM agents WHERE project_id=$1 AND code=$2", project_id, code
    )
