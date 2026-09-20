"""生成溯源：把 before→run→next 任务关联到数字员工、Skills、知识与 SOP。"""
from __future__ import annotations

import json
from typing import Any

import asyncpg


_AGENTS_BY_KIND = {
    "gen_project_info": ["writer"],
    "gen_outline_md": ["writer", "content-reviewer"],
    "gen_element_kinds": ["director"],
    "breakdown_chapter": ["director", "continuity-supervisor"],
    "expand_shot_details": ["director", "continuity-supervisor"],
    "gen_prompts": ["artist", "continuity-supervisor"],
    "scene_blocking": ["continuity-supervisor"],
    "gen_scene_empty": ["scene-designer"],
    "gen_scene_sheet": ["scene-designer", "continuity-supervisor"],
    "gen_scene_sheets_group": ["scene-designer", "continuity-supervisor"],
    "gen_element_sheet": ["artist"],
    "gen_keyframe": ["artist", "continuity-supervisor"],
    "gen_keyframes_group": ["artist", "continuity-supervisor"],
    "gen_last_keyframe": ["artist", "continuity-supervisor"],
    "gen_overview_grid": ["director", "continuity-supervisor"],
    "gen_video": ["director", "continuity-supervisor"],
    "gen_voice_samples": ["voice"],
}

_SKILLS_BY_KIND = {
    "breakdown_chapter": ["subject-aware-scene-transitions"],
    "expand_shot_details": ["subject-aware-scene-transitions"],
    "scene_blocking": ["subject-aware-scene-transitions", "scene-light-blocking-anchor"],
    "gen_scene_empty": ["scene-light-blocking-anchor"],
    "gen_scene_sheet": ["scene-light-blocking-anchor"],
    "gen_scene_sheets_group": ["scene-light-blocking-anchor"],
    "gen_prompts": ["subject-aware-scene-transitions"],
    "gen_keyframe": ["subject-aware-scene-transitions"],
    "gen_keyframes_group": ["subject-aware-scene-transitions"],
    "gen_video": ["subject-aware-scene-transitions"],
}

_SOP_BY_KIND = {
    "gen_outline_md": "project_outline_sop",
    "breakdown_chapter": "storyboard_split_sop",
    "expand_shot_details": "storyboard_script_sop",
    "scene_blocking": "scene_card_sop",
    "gen_scene_empty": "scene_card_sop",
    "gen_scene_sheet": "scene_card_sop",
    "gen_scene_sheets_group": "scene_card_sop",
    "gen_overview_grid": "storyboard_script_sop",
    "gen_keyframe": "shot_keyframe_sop",
    "gen_video": "shot_video_sop",
}

_STAGE_BY_KIND = {
    "gen_project_info": "development",
    "gen_outline_md": "development",
    "gen_element_kinds": "development",
    "breakdown_chapter": "production_planning",
    "expand_shot_details": "production_planning",
    "scene_blocking": "production",
    "gen_scene_empty": "production",
    "gen_scene_sheet": "production",
    "gen_scene_sheets_group": "production",
    "gen_prompts": "production",
    "gen_keyframe": "production",
    "gen_keyframes_group": "production",
    "gen_last_keyframe": "production",
    "gen_video": "production",
}


async def resolve_task(
    pool: asyncpg.Pool, task: Any, payload: dict[str, Any],
) -> dict[str, Any]:
    kind = str(task["kind"])
    employees = _AGENTS_BY_KIND.get(kind, [])
    skills: list[str] = []
    knowledge: list[str] = []
    if employees:
        rows = await pool.fetch(
            "SELECT DISTINCT s.slug,s.name,s.legacy_kb_id "
            "FROM agents a JOIN agent_skill_bindings b ON b.agent_id=a.id AND b.enabled "
            "JOIN skill_packages s ON s.id=b.skill_id AND s.status='installed' "
            "WHERE a.project_id=$1 AND a.code = ANY($2::text[]) ORDER BY s.name",
            task["project_id"], employees)
        skills = [row["slug"] for row in rows]
        knowledge = [
            f"kb:{row['legacy_kb_id']}:{row['name']}"
            for row in rows if row["legacy_kb_id"] is not None
        ]
    for slug in _SKILLS_BY_KIND.get(kind, []):
        if slug not in skills and await pool.fetchval(
            "SELECT 1 FROM skill_packages WHERE slug=$1 AND status='installed'", slug
        ):
            skills.append(slug)
    deps = await pool.fetch(
        "SELECT c.id,c.kind,c.status FROM task_deps d "
        "JOIN task_queue c ON c.id=d.child_task_id WHERE d.parent_task_id=$1 ORDER BY c.id",
        task["id"])
    return {
        "employee_codes": employees,
        "skill_slugs": skills,
        "knowledge_refs": knowledge,
        "sop_code": _SOP_BY_KIND.get(kind),
        "planner_snapshot": {
            "engine": "before-run-next",
            "content_stage": _STAGE_BY_KIND.get(kind, "production"),
            "stage": "run",
            "task_kind": kind,
            "task_id": task["id"],
            "attempt": int(task["attempt"] or 0),
            "dependencies": [dict(row) for row in deps],
            "payload_keys": sorted(payload.keys()),
        },
    }


async def start_task_log(
    pool: asyncpg.Pool, task: Any, payload: dict[str, Any],
) -> int | None:
    try:
        p = await resolve_task(pool, task, payload)
        row = await pool.fetchrow(
            "INSERT INTO gen_logs(project_id,node_id,task_id,kind,source,attempt_no,status,"
            "request,employee_codes,skill_slugs,knowledge_refs,sop_code,planner_snapshot) "
            "VALUES($1,$2,$3,$4,$5,$6,'running',$7::jsonb,$8::jsonb,$9::jsonb,$10::jsonb,"
            "$11,$12::jsonb) RETURNING id",
            task["project_id"], task["node_id"], task["id"], task["kind"],
            f"flow_task_{task['id']}", int(task["attempt"] or 0) + 1,
            json.dumps(payload, ensure_ascii=False),
            json.dumps(p["employee_codes"], ensure_ascii=False),
            json.dumps(p["skill_slugs"], ensure_ascii=False),
            json.dumps(p["knowledge_refs"], ensure_ascii=False),
            p["sop_code"], json.dumps(p["planner_snapshot"], ensure_ascii=False))
        return row["id"]
    except Exception:
        return None


async def finish_task_log(
    pool: asyncpg.Pool, log_id: int | None, status: str,
    result: dict[str, Any] | None = None, error: str | None = None,
) -> None:
    if not log_id:
        return
    try:
        await pool.execute(
            "UPDATE gen_logs SET status=$2,result=$3::jsonb,error=$4,finished_at=now(),"
            "duration_ms=greatest(0,(extract(epoch FROM (now()-created_at))*1000)::int) "
            "WHERE id=$1",
            log_id, status, json.dumps(result or {}, ensure_ascii=False), error)
    except Exception:
        pass


async def finish_latest_task_log(
    pool: asyncpg.Pool, task_id: int, status: str,
    result: dict[str, Any] | None = None, error: str | None = None,
) -> None:
    log_id = await pool.fetchval(
        "SELECT id FROM gen_logs WHERE task_id=$1 AND source=$2 AND status='running' "
        "ORDER BY id DESC LIMIT 1", task_id, f"flow_task_{task_id}")
    await finish_task_log(pool, log_id, status, result, error)
