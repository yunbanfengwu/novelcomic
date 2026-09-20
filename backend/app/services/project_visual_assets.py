"""项目级三类视觉技能：技能×知识库文件夹×版本化资产。"""
from __future__ import annotations

import json
from typing import Any

import asyncpg

from .. import llm, media

ROLES = {
    "project_environment_style_anchor": {
        "skill": "场景画风定位图",
        "folder": "visual_environment_style",
        "prefix": "project_environment_style",
    },
    "project_character_ensemble_style_anchor": {
        "skill": "主要角色汇总风格定位图",
        "folder": "visual_character_ensemble",
        "prefix": "project_character_ensemble",
    },
    "project_cover_poster": {
        "skill": "封面海报",
        "folder": "visual_cover_poster",
        "prefix": "project_cover_poster",
    },
}


def _json(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else json.loads(v or "{}")


async def _automatic_references(
    conn: asyncpg.Connection, project_id: int, role: str,
) -> list[str]:
    """按技能依赖自动收集参考图；只读既有资产，不修改或覆盖实验数据。"""
    if role == "project_environment_style_anchor":
        return []
    character_rows = await conn.fetch(
        "SELECT meta->>'sheet_url' AS url FROM content_elements "
        "WHERE project_id=$1 AND kind='character' "
        "AND coalesce(meta->>'sheet_url','')<>'' ORDER BY id LIMIT 6",
        project_id,
    )
    characters = [r["url"] for r in character_rows]
    if role == "project_character_ensemble_style_anchor":
        if not characters:
            raise ValueError("请先生成至少一张主要角色设定图，再生成角色风格定位图")
        return characters
    anchors = await conn.fetch(
        "SELECT DISTINCT ON (asset_role) url FROM project_visual_assets "
        "WHERE project_id=$1 AND asset_role IN "
        "('project_environment_style_anchor','project_character_ensemble_style_anchor') "
        "ORDER BY asset_role,version DESC",
        project_id,
    )
    if len(anchors) < 2:
        raise ValueError("请先生成场景画风定位图和主要角色风格定位图，再生成封面海报")
    return [r["url"] for r in anchors] + characters[:4]


async def _context(
    conn: asyncpg.Connection, project_id: int, role: str, folder_name: str | None = None,
) -> dict[str, Any]:
    spec = ROLES[role]
    project = await conn.fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
    if not project:
        raise ValueError("项目不存在")
    skill = await conn.fetchrow(
        "SELECT * FROM kb_entries WHERE scope='global' AND kind='skill' "
        "AND agent_code='artist' AND name=$1 AND enabled ORDER BY id DESC LIMIT 1",
        spec["skill"])
    folder = await conn.fetchrow(
        "SELECT * FROM kb_folders WHERE name=$1", folder_name or spec["folder"])
    knowledge = await conn.fetch(
        "SELECT name,description,content,meta FROM kb_entries WHERE folder_id=$1 AND enabled "
        "ORDER BY weight DESC,id", folder["id"]) if folder else []
    return {"project": project, "skill": skill, "folder": folder, "knowledge": knowledge}


async def _plan_cover_prompt(
    ctx: dict[str, Any], base_prompt: str, planner: dict[str, Any] | None = None,
) -> dict[str, str]:
    """先由海报美术指导模型选择知识库版式，再产出最终生图提示词。"""
    candidates = "\n\n".join(
        f"[{row['name']}]\n适用：{row['description']}\n规则：{row['content']}"
        for row in ctx["knowledge"]
    )
    system = (
        "你是电影发行海报的资深美术指导。先从候选版式知识中选择最适合本项目的一种，"
        "参考案例只允许借鉴抽象的构图、层级、留白和视线流向，严禁借用其剧情、角色、"
        "服装、场景、标志、标题或具体画面。最终提示词必须只使用用户给出的项目事实，"
        "不得擅自补剧情。海报图像内不生成文字，明确保留标题安全区。"
        "只输出 JSON："
        '{"layout_id":"知识条目名称","reference_layout":"参考案例及只借鉴的布局特征",'
        '"selection_reason":"与本项目匹配原因","prompt":"可直接提交给图像模型的完整中文提示词"}'
    )
    user = (
        f"项目事实与基础视觉约束：\n{base_prompt}\n\n"
        f"可选专业海报版式知识：\n{candidates}\n\n"
        "选择一个主版式；不要混搭多个导致画面拥挤。prompt 要写清主体数量、大小层级、"
        "前中后景、视线方向、负空间、光色、镜头感及禁止项。"
    )
    planner = planner or {}
    plan = await llm.chat_json(
        system, user, temperature=float(planner.get("temperature", 0.35)),
        max_tokens=int(planner.get("max_tokens", 2200)))
    required = ("layout_id", "reference_layout", "selection_reason", "prompt")
    if not isinstance(plan, dict) or any(not str(plan.get(k, "")).strip() for k in required):
        raise ValueError("海报美术指导模型未返回完整的版式选择与提示词")
    return {key: str(plan[key]).strip() for key in required}


async def _review_prompt(prompt: str, gate: dict[str, Any]) -> dict[str, Any]:
    if not gate.get("enabled", False):
        return {"status": "skipped", "prompt": prompt}
    requirements = gate.get("requirements") or []
    system = (
        "你是视觉生成提示词质检员。按要求逐项检查，发现缺失时直接给出修订后的完整提示词。"
        "只输出JSON："
        '{"score":0,"passed":false,"issues":[],"revised_prompt":"完整提示词"}'
    )
    current = prompt
    attempts: list[dict[str, Any]] = []
    for _ in range(2):
        result = await llm.chat_json(
            system, f"质检要求：{json.dumps(requirements,ensure_ascii=False)}\n提示词：\n{current}",
            temperature=0.1, max_tokens=2200, purpose="review")
        score = int(result.get("score") or 0)
        passed = bool(result.get("passed")) and score >= int(gate.get("min_score", 80))
        current = str(result.get("revised_prompt") or current).strip()
        attempts.append({**result, "score": score, "passed": passed})
        if passed:
            break
    return {**attempts[-1], "prompt": current, "attempts": attempts}


async def _review_image(url: str, gate: dict[str, Any]) -> dict[str, Any]:
    if not gate.get("enabled", False):
        return {"status": "skipped", "passed": True}
    requirements = gate.get("requirements") or []
    system = (
        "你是电影视觉资产质检员，只根据图片可见证据逐项评分。"
        "只输出JSON："
        '{"score":0,"passed":false,"issues":[],"requirement_results":[]}'
    )
    result = await llm.chat_vision_json(
        system,
        f"质检要求：{json.dumps(requirements,ensure_ascii=False)}。"
        f"最低分：{int(gate.get('min_score',80))}。",
        url)
    score = int(result.get("score") or 0)
    return {**result, "score": score,
            "passed": bool(result.get("passed")) and score >= int(gate.get("min_score", 80))}


async def build_prompt(conn: asyncpg.Connection, project_id: int, role: str) -> str:
    ctx = await _context(conn, project_id, role)
    p, skill = ctx["project"], ctx["skill"]
    methods = "\n".join(f"- {r['name']}：{r['content']}" for r in ctx["knowledge"])
    base = (
        f"项目《{p['title']}》。故事：{p['synopsis'] or ''}。主线：{p['storyline'] or ''}。\n"
        f"项目画风方向：{p['art_style'] or ''}。\n"
        f"技能规则：{skill['content'] if skill else ''}\n"
        f"知识库方法：\n{methods}\n"
    )
    if role == "project_environment_style_anchor":
        return base + (
            "生成一张16:9项目级场景画风定位图：从故事与主线提炼最能代表本项目世界的标志性"
            "环境、生态、建筑与交通方式；真实体积光、大气透视、天气、地貌和风化材质，生态"
            "尺度可信；电影级高端3D动画长片质感，环境接近真实摄影，角色若出现只能是远处"
            "小比例风格化动画剪影。使用项目画风指定的受控冷暖对比。完整单幅，"
            "不是宫格或海报拼贴；no text, no logo, no watermark。"
        )
    if role == "project_character_ensemble_style_anchor":
        return base + (
            "【最高优先级画布规则】直接在纯黑摄影棚画布上原生渲染最终成片，背景从生成开始就是"
            "均匀绝对黑色（#000000）；不是白底抠图、不是透明素材合成、不是贴纸拼贴。"
            "生成一张16:9主要角色汇总风格定位图。依据所提供角色设定图只提取角色身份和服装，"
            "完全忽略参考图原有的白色背景、排版、边框和轮廓光。"
            "采用高品质奇幻动画电影的角色动作群像：主角居中最大，伙伴、巨型幻想生物和重要"
            "对立人物分层排布，各自展示代表身份的主要动作；角色全身或至少四分之三身，轮廓"
            "彼此清晰分离，使用来自画面正前上方的柔和摄影棚主光，不使用逆光或轮廓光；人物"
            "边缘自然融入黑底，严禁白边、亮边、描边、描光、贴纸边缘或剪贴蒙版痕迹。人物明确"
            "为精致风格化动漫/3D动画"
            "角色而非真人。背景必须是均匀、纯净、无纹理的绝对黑色（#000000），禁止任何"
            "场景、地面、天空、云、建筑、山水、天气、环境光斑、烟雾、道具布景或叙事环境；"
            "黑色只作为角色展示底板。不新增未提供角色，不复制角色，不出现文字、标题、姓名、"
            "logo、边框或水印。"
        )
    return base + (
        "生成一张16:9商业奇幻动画电影封面海报：从故事主线选择主角、关键伙伴或生物与标志性"
        "环境形成核心视觉，准确表达本项目核心冲突，但不添加剧本外角色或事件。电影级高端"
        "3D动画长片质感，环境真实、角色风格化，构图有明确中心，"
        "上方保留标题安全空间但画面中不生成任何文字、logo或水印。"
    )


async def generate(
    pool: asyncpg.Pool, project_id: int, role: str, prompt: str | None = None,
    reference_urls: list[str] | None = None,
) -> dict[str, Any]:
    if role not in ROLES:
        raise ValueError("未知视觉资产类型")
    from .visual_sops import get_published
    sop = await get_published(pool, role)
    sop_spec = (sop or {}).get("spec") or {}
    sop_snapshot = ({
        "id": sop["id"], "code": sop["code"], "title": sop["title"],
        "asset_role": sop["asset_role"], "version": sop["version"],
        "status": sop["status"], "spec": sop_spec,
    } if sop else None)
    async with pool.acquire() as conn:
        ctx = await _context(
            conn, project_id, role, sop_spec.get("knowledge_folder"))
        supplied_prompt = (prompt or "").strip()
        base_prompt = supplied_prompt or await build_prompt(conn, project_id, role)
        poster_plan = None
        planner = sop_spec.get("planner") or {}
        if role == "project_cover_poster" and not supplied_prompt and planner.get("enabled", True):
            poster_plan = await _plan_cover_prompt(ctx, base_prompt, planner)
            final_prompt = poster_plan["prompt"]
        else:
            final_prompt = base_prompt
        quality_gates = sop_spec.get("quality_gates") or {}
        prompt_review = await _review_prompt(
            final_prompt, quality_gates.get("prompt") or {})
        final_prompt = prompt_review.get("prompt") or final_prompt
        prompt_gate = quality_gates.get("prompt") or {}
        if (prompt_gate.get("enabled") and prompt_gate.get("mode") == "blocking"
                and not prompt_review.get("passed")):
            issues = "；".join(str(x) for x in (prompt_review.get("issues") or []))
            raise ValueError(f"提示词质检未通过：{issues or '未达到最低分'}")
        resolved_references = (
            reference_urls if reference_urls is not None
            else await _automatic_references(conn, project_id, role)
        )
        cfg = _json(ctx["project"]["config"])
        size = "1440x2560" if cfg.get("aspect_ratio") == "9:16" else "2560x1440"
    employee_by_role = {
        "project_environment_style_anchor": "scene-designer",
        "project_character_ensemble_style_anchor": "character-designer",
        "project_cover_poster": "poster-art-director",
    }
    skill_slug = None
    if ctx["skill"]:
        skill_slug = await pool.fetchval(
            "SELECT slug FROM skill_packages WHERE legacy_kb_id=$1",
            ctx["skill"]["id"])
    token = media.GEN_AUDIT.set({
        "project_id": project_id, "kind": "gen_project_visual",
        "source": f"project_{project_id}_{role}",
        "employee_codes": [employee_by_role[role]],
        "skill_slugs": [skill_slug] if skill_slug else [],
        "knowledge_refs": [
            f"kb_folder:{ctx['folder']['id']}:{ctx['folder']['name']}"
        ] + [f"kb:{row['name']}" for row in ctx["knowledge"]] if ctx["folder"] else [],
        "sop_code": sop["code"] if sop else None,
        "planner_snapshot": {
            "engine": "before-run-next",
            "sop_version": sop["version"] if sop else None,
            "before": sop_spec.get("before") or sop_spec.get("nodes") or [],
            "planner": planner,
            "poster_plan": poster_plan,
            "quality_gates": quality_gates,
        },
    })
    try:
        url = await media.generate_image(
            final_prompt, size=size, reference_images=resolved_references or None,
            store_prefix=ROLES[role]["prefix"])
    finally:
        media.GEN_AUDIT.reset(token)
    try:
        image_review = await _review_image(
            url, (sop_spec.get("quality_gates") or {}).get("image") or {})
    except Exception as exc:  # 评审模型不支持视觉时保留明确审计，不伪装成已通过
        image_review = {"status": "unavailable", "passed": False, "error": str(exc)[:300]}
    image_gate = (sop_spec.get("quality_gates") or {}).get("image") or {}
    asset_status = (
        "rejected" if image_gate.get("mode") == "blocking"
        and image_gate.get("enabled") and not image_review.get("passed")
        else "generated"
    )
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock($1,$2)", int(project_id),
                list(ROLES).index(role) + 1)
            version = await conn.fetchval(
                "SELECT COALESCE(max(version),0)+1 FROM project_visual_assets "
                "WHERE project_id=$1 AND asset_role=$2", project_id, role)
            attachment_id = await conn.fetchval(
                "INSERT INTO content_attachments(project_id,kind,url,meta) "
                "VALUES($1,'image',$2,$3::jsonb) RETURNING id",
                project_id, url, json.dumps({
                    "type": "project_visual_asset", "asset_role": role,
                    "version": version, "preserved": True,
                }, ensure_ascii=False))
            row = await conn.fetchrow(
                "INSERT INTO project_visual_assets "
                "(project_id,asset_role,version,skill_entry_id,knowledge_folder_id,"
                "prompt,attachment_id,url,status,meta) "
                "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb) RETURNING *",
                project_id, role, version,
                ctx["skill"]["id"] if ctx["skill"] else None,
                ctx["folder"]["id"] if ctx["folder"] else None,
                final_prompt, attachment_id, url, asset_status,
                json.dumps({
                    "reference_urls": resolved_references,
                    **({"poster_plan": poster_plan} if poster_plan else {}),
                    "sop_snapshot": sop_snapshot,
                    "prompt_review": prompt_review,
                    "image_review": image_review,
                }, ensure_ascii=False, default=str))
    return {**dict(row), "meta": _json(row["meta"])}


async def list_assets(pool: asyncpg.Pool, project_id: int) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        "SELECT * FROM project_visual_assets WHERE project_id=$1 "
        "ORDER BY asset_role,version DESC", project_id)
    return [{**dict(r), "meta": _json(r["meta"])} for r in rows]
