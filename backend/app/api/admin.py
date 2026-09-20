"""系统管理 API：知识库（专业提示词块/知识）与技能的 CRUD。"""
import json
import base64
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import dashscope, embeddings
from ..db import get_pool
from ..settings import settings

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _jsonb(v: Any) -> Any:
    return v if isinstance(v, (dict, list)) else (json.loads(v) if v else {})


class SkillInstallIn(BaseModel):
    source_url: str = Field(min_length=8)


class AgentTemplateIn(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=80)
    description: str = ""
    charter: str = ""
    model: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    skill_ids: list[int] = Field(default_factory=list)


class TestRunIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    project_id: int | None = None
    summary: str = ""


class TestStepIn(BaseModel):
    project_id: int | None = None
    test_item: str = Field(min_length=1, max_length=200)
    status: str = "running"
    employee_codes: list[str] = Field(default_factory=list)
    skill_slugs: list[str] = Field(default_factory=list)
    knowledge_refs: list[str] = Field(default_factory=list)
    sop_code: str | None = None
    planner_snapshot: dict[str, Any] = Field(default_factory=dict)
    request: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    task_id: int | None = None
    provider: str | None = None
    model: str | None = None
    duration_ms: int | None = None


class TestStepPatch(BaseModel):
    status: str | None = None
    employee_codes: list[str] | None = None
    skill_slugs: list[str] | None = None
    knowledge_refs: list[str] | None = None
    sop_code: str | None = None
    planner_snapshot: dict[str, Any] | None = None
    request: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    task_id: int | None = None
    provider: str | None = None
    model: str | None = None
    duration_ms: int | None = None


def _test_log(row: Any) -> dict[str, Any]:
    item = dict(row)
    for key, fallback in (
        ("request", {}), ("result", {}), ("employee_codes", []),
        ("skill_slugs", []), ("knowledge_refs", []), ("planner_snapshot", {}),
    ):
        value = item.get(key)
        if isinstance(value, str):
            try:
                item[key] = json.loads(value)
            except json.JSONDecodeError:
                item[key] = fallback
        elif value is None:
            item[key] = fallback
    return item


@router.get("/skill-packages")
async def list_skill_packages():
    from ..services.skill_packages import list_packages
    return await list_packages(get_pool())


@router.post("/skill-packages/install")
async def install_skill_package(body: SkillInstallIn):
    from ..services.skill_packages import install
    try:
        return await install(get_pool(), body.source_url)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # 网络或 GitHub 下载错误
        raise HTTPException(502, f"Skill 安装失败：{str(e)[:300]}")


@router.get("/agent-templates")
async def list_agent_templates():
    from ..services.skill_packages import list_agents
    return await list_agents(get_pool())


@router.post("/agent-templates")
async def create_agent_template(body: AgentTemplateIn):
    from ..services.skill_packages import list_agents, set_agent_skills
    try:
        row = await get_pool().fetchrow(
            "INSERT INTO agent_templates(code,name,role,description,charter,model,config,enabled) "
            "VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8) RETURNING *",
            body.code, body.name, body.role, body.description, body.charter, body.model,
            json.dumps(body.config, ensure_ascii=False), body.enabled)
        await set_agent_skills(get_pool(), row["id"], body.skill_ids)
        return next(x for x in await list_agents(get_pool()) if x["id"] == row["id"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        if "unique" in str(e).lower():
            raise HTTPException(409, "数字员工 code 已存在")
        raise


@router.put("/agent-templates/{agent_id}")
async def update_agent_template(agent_id: int, body: AgentTemplateIn):
    from ..services.skill_packages import list_agents, set_agent_skills
    row = await get_pool().fetchrow(
        "UPDATE agent_templates SET code=$2,name=$3,role=$4,description=$5,charter=$6,"
        "model=$7,config=$8::jsonb,enabled=$9,updated_at=now() WHERE id=$1 RETURNING id",
        agent_id, body.code, body.name, body.role, body.description, body.charter,
        body.model, json.dumps(body.config, ensure_ascii=False), body.enabled)
    if not row:
        raise HTTPException(404, "数字员工不存在")
    await set_agent_skills(get_pool(), agent_id, body.skill_ids)
    return next(x for x in await list_agents(get_pool()) if x["id"] == agent_id)


@router.get("/expert-teams")
async def list_expert_teams():
    rows = await get_pool().fetch(
        "SELECT t.*,coalesce(jsonb_agg(jsonb_build_object('id',a.id,'code',a.code,"
        "'name',a.name,'role_in_team',m.role_in_team,'seq',m.seq) ORDER BY m.seq) "
        "FILTER(WHERE a.id IS NOT NULL),'[]'::jsonb) AS members "
        "FROM expert_teams t LEFT JOIN expert_team_members m ON m.team_id=t.id "
        "LEFT JOIN agent_templates a ON a.id=m.agent_template_id "
        "GROUP BY t.id ORDER BY t.name")
    result = []
    for row in rows:
        item = dict(row)
        for key, fallback in (("members", []), ("planner_config", {})):
            value = item.get(key)
            if isinstance(value, str):
                try:
                    item[key] = json.loads(value)
                except json.JSONDecodeError:
                    item[key] = fallback
            elif value is None:
                item[key] = fallback
        result.append(item)
    return result


@router.get("/test-runs")
async def list_test_runs():
    rows = await get_pool().fetch(
        "SELECT test_run_id,"
        "max(project_id) FILTER(WHERE project_id IS NOT NULL) AS project_id,"
        "max(test_item) FILTER(WHERE kind='qa_test_run') AS title,"
        "min(created_at) AS started_at,max(finished_at) AS finished_at,"
        "count(*) FILTER(WHERE kind='qa_test') AS step_count,"
        "count(*) FILTER(WHERE kind='qa_test' AND status='done') AS passed,"
        "count(*) FILTER(WHERE kind='qa_test' AND status='failed') AS failed,"
        "count(*) FILTER(WHERE kind='qa_test' AND status='running') AS running "
        "FROM gen_logs WHERE test_run_id IS NOT NULL GROUP BY test_run_id "
        "ORDER BY min(created_at) DESC")
    return [dict(row) for row in rows]


@router.post("/test-runs")
async def create_test_run(body: TestRunIn):
    run_id = uuid.uuid4().hex
    row = await get_pool().fetchrow(
        "INSERT INTO gen_logs(project_id,kind,source,status,test_run_id,test_item,"
        "request,result,finished_at) "
        "VALUES($1,'qa_test_run',$2,'running',$3,$4,$5::jsonb,$6::jsonb,NULL) "
        "RETURNING *",
        body.project_id, f"test:{run_id}", run_id, body.title,
        json.dumps({"summary": body.summary}, ensure_ascii=False),
        json.dumps({}, ensure_ascii=False))
    return _test_log(row)


@router.get("/test-runs/{run_id}")
async def get_test_run(run_id: str):
    rows = await get_pool().fetch(
        "SELECT * FROM gen_logs WHERE test_run_id=$1 ORDER BY created_at,id", run_id)
    if not rows:
        raise HTTPException(404, "测试批次不存在")
    return [_test_log(row) for row in rows]


@router.post("/test-runs/{run_id}/steps")
async def create_test_step(run_id: str, body: TestStepIn):
    exists = await get_pool().fetchval(
        "SELECT 1 FROM gen_logs WHERE test_run_id=$1 AND kind='qa_test_run'", run_id)
    if not exists:
        raise HTTPException(404, "测试批次不存在")
    terminal = body.status in {"done", "failed", "cancelled"}
    row = await get_pool().fetchrow(
        "INSERT INTO gen_logs(project_id,task_id,kind,source,provider,model,status,error,"
        "request,result,finished_at,test_run_id,test_item,employee_codes,skill_slugs,"
        "knowledge_refs,sop_code,planner_snapshot,duration_ms) "
        "VALUES($1,$2,'qa_test',$3,$4,$5,$6,$7,$8::jsonb,$9::jsonb,"
        "CASE WHEN $10 THEN now() ELSE NULL END,$11,$12,$13::jsonb,$14::jsonb,"
        "$15::jsonb,$16,$17::jsonb,$18) RETURNING *",
        body.project_id, body.task_id, f"test:{run_id}:{body.test_item}",
        body.provider, body.model, body.status, body.error,
        json.dumps(body.request, ensure_ascii=False),
        json.dumps(body.result, ensure_ascii=False), terminal, run_id, body.test_item,
        json.dumps(body.employee_codes, ensure_ascii=False),
        json.dumps(body.skill_slugs, ensure_ascii=False),
        json.dumps(body.knowledge_refs, ensure_ascii=False), body.sop_code,
        json.dumps(body.planner_snapshot, ensure_ascii=False), body.duration_ms)
    return _test_log(row)


@router.patch("/test-steps/{step_id}")
async def update_test_step(step_id: int, body: TestStepPatch):
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        row = await get_pool().fetchrow(
            "SELECT * FROM gen_logs WHERE id=$1 AND kind='qa_test'", step_id)
        if not row:
            raise HTTPException(404, "测试步骤不存在")
        return _test_log(row)
    json_fields = {
        "request", "result", "employee_codes", "skill_slugs",
        "knowledge_refs", "planner_snapshot",
    }
    assignments: list[str] = []
    values: list[Any] = [step_id]
    for key, value in fields.items():
        values.append(json.dumps(value, ensure_ascii=False) if key in json_fields else value)
        cast = "::jsonb" if key in json_fields else ""
        assignments.append(f"{key}=${len(values)}{cast}")
    if fields.get("status") in {"done", "failed", "cancelled"}:
        assignments.append("finished_at=now()")
        if "duration_ms" not in fields:
            assignments.append(
                "duration_ms=greatest(0,(extract(epoch FROM (now()-created_at))*1000)::int)")
    row = await get_pool().fetchrow(
        f"UPDATE gen_logs SET {','.join(assignments)} "
        "WHERE id=$1 AND kind='qa_test' RETURNING *", *values)
    if not row:
        raise HTTPException(404, "测试步骤不存在")
    return _test_log(row)


@router.post("/test-runs/{run_id}/finish")
async def finish_test_run(run_id: str):
    counts = await get_pool().fetchrow(
        "SELECT count(*) FILTER(WHERE kind='qa_test') AS total,"
        "count(*) FILTER(WHERE kind='qa_test' AND status='done') AS passed,"
        "count(*) FILTER(WHERE kind='qa_test' AND status='failed') AS failed,"
        "count(*) FILTER(WHERE kind='qa_test' AND status='running') AS running "
        "FROM gen_logs WHERE test_run_id=$1", run_id)
    if not counts or not counts["total"]:
        raise HTTPException(400, "测试批次还没有步骤")
    status = "failed" if counts["failed"] else ("running" if counts["running"] else "done")
    row = await get_pool().fetchrow(
        "UPDATE gen_logs SET status=$2,result=$3::jsonb,"
        "finished_at=CASE WHEN $2='running' THEN NULL ELSE now() END "
        "WHERE test_run_id=$1 AND kind='qa_test_run' RETURNING *",
        run_id, status, json.dumps(dict(counts), ensure_ascii=False))
    if not row:
        raise HTTPException(404, "测试批次不存在")
    return _test_log(row)


# ═══════════ 音色库（kind=voice，见 docs/arch/voice-timbre-design.md）═══════════

# CosyVoice2（硅基流动托管）预置音色轮换表：按性别绑定占位试听音色；定妆期换克隆音色
_COSY = "FunAudioLLM/CosyVoice2-0.5B"
_PRESETS = {
    "male": [f"{_COSY}:alex", f"{_COSY}:benjamin", f"{_COSY}:charles", f"{_COSY}:david"],
    "female": [f"{_COSY}:anna", f"{_COSY}:bella", f"{_COSY}:claire", f"{_COSY}:diana"],
    "child": [f"{_COSY}:claire", f"{_COSY}:anna"],
    "creature": [f"{_COSY}:charles", f"{_COSY}:david", f"{_COSY}:benjamin"],
    "neutral": [f"{_COSY}:david"],
}
_SAMPLE_TEXT = "山高路远，江湖再见。此去经年，愿君平安。"


@router.get("/voices")
async def list_voices():
    rows = await get_pool().fetch(
        "SELECT * FROM kb_entries WHERE kind='voice' AND enabled ORDER BY weight DESC, id"
    )
    return [{**dict(r), "meta": _jsonb(r["meta"]), "tags": list(r["tags"])} for r in rows]


@router.post("/voices/bind-presets")
async def bind_voice_presets():
    """给未绑定的音色按性别轮换绑定 CosyVoice2 预置音色（占位试听用；定妆期换克隆音色）。"""
    rows = await get_pool().fetch("SELECT id, meta FROM kb_entries WHERE kind='voice' ORDER BY id")
    counters: dict[str, int] = {}
    bound = 0
    for r in rows:
        meta = _jsonb(r["meta"])
        if meta.get("voice_type"):
            continue
        g = meta.get("gender") or "neutral"
        pool = _PRESETS.get(g) or _PRESETS["neutral"]
        i = counters.get(g, 0)
        meta.update({"provider": "openai_compat", "voice_type": pool[i % len(pool)]})
        counters[g] = i + 1
        await get_pool().execute(
            "UPDATE kb_entries SET meta=$2::jsonb, updated_at=now() WHERE id=$1",
            r["id"], json.dumps(meta, ensure_ascii=False),
        )
        bound += 1
    return {"bound": bound}


@router.post("/voices/samples")
async def gen_voice_samples():
    """批量生成缺失的试听样本（统一管线任务，worker 逐条 TTS→OSS→sample_audio_url 回写）。"""
    from ..services import flow

    return await flow.enqueue(get_pool(), kind="gen_voice_samples")


@router.get("/voices/{voice_id}")
async def get_voice(voice_id: int):
    row = await get_pool().fetchrow("SELECT * FROM kb_entries WHERE id=$1 AND kind='voice'", voice_id)
    if not row:
        raise HTTPException(404, "音色不存在")
    return {**dict(row), "meta": _jsonb(row["meta"]), "tags": list(row["tags"])}


class VoiceAgeIn(BaseModel):
    age_years: int  # 具体年龄数字（1-120）


@router.patch("/voices/{voice_id}/age")
async def set_voice_age(voice_id: int, body: VoiceAgeIn):
    """音色年龄滑块：存 meta.age_years（数字），并按人物特征库 age_range 重推年龄档位
    （meta.age→韵律基线/情绪小样换段依据）+ 同步规范年龄标签（换掉旧的）。"""
    from ..services.persona_traits import age_class_for_years
    from ..services.voice_casting import _AGE_TAGS, _age_tag

    if not 1 <= body.age_years <= 120:
        raise HTTPException(400, "年龄须在 1-120 之间")
    row = await get_pool().fetchrow(
        "SELECT meta, tags FROM kb_entries WHERE id=$1 AND kind='voice'", voice_id)
    if not row:
        raise HTTPException(404, "音色不存在")
    meta = _jsonb(row["meta"])
    meta["age_years"] = body.age_years
    async with get_pool().acquire() as conn:
        cls = await age_class_for_years(conn, body.age_years, meta.get("gender"))
        if cls:
            meta["age"] = cls
        # 换规范年龄标签：移除旧档位标签，追加新档位的
        canonical = set(_AGE_TAGS.values()) | {"少年", "少女"}
        tags = [t for t in list(row["tags"] or []) if t not in canonical]
        atag = _age_tag(meta.get("age"), meta.get("gender"))
        if atag:
            tags.append(atag)
        await conn.execute(
            "UPDATE kb_entries SET meta=$2::jsonb, tags=$3, updated_at=now() WHERE id=$1",
            voice_id, json.dumps(meta, ensure_ascii=False), tags,
        )
    return {"ok": True, "age_years": body.age_years, "age": meta.get("age"), "tags": tags}


class PreviewIn(BaseModel):
    text: str | None = None
    mood: str | None = None  # 可选场景气氛（如"恐惧铺垫/对话交锋"）→ 韵律调制试听


@router.post("/voices/{voice_id}/sample")
async def gen_voice_sample(voice_id: int, body: PreviewIn | None = None):
    """生成试听样本并保存到 meta.sample_audio_url（覆盖旧样本）；试听直接播已存 URL，不再每次合成。

    默认用角色基线语速（音色 params.speed 三档）；传 mood 则叠加场景调制（语速倍率+语气指令），
    与真实配音逐句走的是同一条 resolve_prosody 链路（见 services/prosody.py）。"""
    from .. import media
    from ..oss import store_bytes
    from ..services.prosody import resolve_prosody

    row = await get_pool().fetchrow("SELECT meta FROM kb_entries WHERE id=$1 AND kind='voice'", voice_id)
    if not row:
        raise HTTPException(404, "音色不存在")
    meta = _jsonb(row["meta"])
    if not meta.get("voice_type"):
        raise HTTPException(400, "该音色未绑定 voice_type，请先执行 bind-presets 或手动绑定")
    text = (body.text if body and body.text else None) or _SAMPLE_TEXT
    pr = resolve_prosody(meta, body.mood if body else None, text)
    try:
        audio = await media.generate_tts(text[:120], meta["voice_type"], speed=pr["speed"], instruct=pr["instruct"])
    except Exception as e:  # noqa: BLE001 — 供应商错误透传给前端（欠费/限流等）
        msg = str(e)
        # 欠费只认 media 层结构化标记（按 error code 判定），真实错误原样透传不再被覆盖
        if "TTS_INSUFFICIENT_BALANCE" in msg:
            msg = "硅基流动账户余额不足，请充值后再生成试听样本"
        raise HTTPException(502, msg[:300])
    url = await store_bytes(audio, "voice_sample", ".mp3")
    if not url:
        raise HTTPException(500, "OSS 未配置，无法保存试听样本")
    meta["sample_audio_url"] = url
    await get_pool().execute(
        "UPDATE kb_entries SET meta=$2::jsonb, updated_at=now() WHERE id=$1",
        voice_id, json.dumps(meta, ensure_ascii=False),
    )
    return {"url": url}


@router.post("/voices/{voice_id}/emotion-samples")
async def gen_voice_emotion_samples(voice_id: int):
    """生成 5 情绪试听小样（喜怒哀乐+平，按角色定制）并存 meta.samples。
    人声先大模型出词→逐句 TTS；非人声退回单条拟声小样。见 services/voice_casting.py。"""
    from ..services import voice_casting

    try:
        return await voice_casting.generate_emotion_samples(get_pool(), voice_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001 — 供应商错误透传（欠费/限流等）
        msg = str(e)
        if "TTS_INSUFFICIENT_BALANCE" in msg:
            msg = "硅基流动账户余额不足，请充值后再生成试听样本"
        raise HTTPException(502, msg[:300])


@router.get("/kb")
async def list_kb(kind: str | None = None, category: str | None = None, scope: str | None = None,
                  folder_id: int | None = None):
    conds: list[str] = []
    args: list[Any] = []
    if folder_id:
        from .kb_library import folder_condition, list_folder_rows

        folders = await list_folder_rows()
        folder = next((f for f in folders if f["id"] == folder_id), None)
        if not folder:
            raise HTTPException(404, "文件夹不存在")
        conds.append(folder_condition(folder, folders, args))
    for col, val in (("kind", kind), ("category", category), ("scope", scope)):
        if val:
            args.append(val)
            conds.append(f"{col}=${len(args)}")
    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    rows = await get_pool().fetch(
        f"SELECT * FROM kb_entries {where} ORDER BY weight DESC, kind, category, id", *args
    )
    return [{**dict(r), "meta": _jsonb(r["meta"]), "tags": list(r["tags"])} for r in rows]


class KbIn(BaseModel):
    scope: str = "global"
    project_id: int | None = None
    agent_code: str | None = None
    kind: str = Field(description="prompt_block=提示词块 / knowledge=知识 / skill=技能 / role / voice")
    category: str | None = None
    name: str
    title: str | None = None
    description: str = ""
    content: str = ""
    tags: list[str] = []
    meta: dict = {}
    thumbnail_url: str | None = None
    folder_id: int | None = None  # 自定义文件夹归属；空=按 (kind,category) 落系统文件夹
    weight: int = 0  # 搜索召回与页面展示排序权重，越大越靠前
    enabled: bool = True


@router.post("/kb")
async def create_kb(body: KbIn):
    r = await get_pool().fetchrow(
        """INSERT INTO kb_entries (scope, project_id, agent_code, kind, category, name, title,
                                   description, content, tags, meta, thumbnail_url, folder_id, weight, enabled)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12,$13,$14,$15) RETURNING *""",
        body.scope, body.project_id, body.agent_code, body.kind, body.category, body.name,
        body.title, body.description, body.content, body.tags,
        json.dumps(body.meta, ensure_ascii=False), body.thumbnail_url, body.folder_id,
        body.weight, body.enabled,
    )
    return {**dict(r), "meta": _jsonb(r["meta"]), "tags": list(r["tags"])}


@router.put("/kb/{kb_id}")
async def update_kb(kb_id: int, body: KbIn):
    # 知识双版本（用户 2026-07-13 定稿）：content/正负词变化时把上一版存进 meta.prev_version，
    # 永远只留最近一个历史版本（再次变化即滚动覆盖）——防误改，可随时人工回滚
    old = await get_pool().fetchrow("SELECT description, content, meta FROM kb_entries WHERE id=$1", kb_id)
    if not old:
        raise HTTPException(404, "条目不存在")
    meta = dict(body.meta)
    old_meta = _jsonb(old["meta"])
    changed = (old["content"] != body.content
               or old_meta.get("positive") != meta.get("positive")
               or old_meta.get("negative") != meta.get("negative"))
    if changed:
        meta["prev_version"] = {
            "description": old["description"], "content": old["content"],
            "positive": old_meta.get("positive"), "negative": old_meta.get("negative"),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
    elif "prev_version" not in meta and old_meta.get("prev_version"):
        meta["prev_version"] = old_meta["prev_version"]  # 内容未变时保住已有历史版本
    r = await get_pool().fetchrow(
        """UPDATE kb_entries SET scope=$2, project_id=$3, agent_code=$4, kind=$5, category=$6,
                  name=$7, title=$8, description=$9, content=$10, tags=$11, meta=$12::jsonb,
                  thumbnail_url=$13, folder_id=$14, weight=$15, enabled=$16, updated_at=now()
           WHERE id=$1 RETURNING *""",
        kb_id, body.scope, body.project_id, body.agent_code, body.kind, body.category,
        body.name, body.title, body.description, body.content, body.tags,
        json.dumps(meta, ensure_ascii=False), body.thumbnail_url, body.folder_id,
        body.weight, body.enabled,
    )
    if not r:
        raise HTTPException(404, "条目不存在")
    return {**dict(r), "meta": _jsonb(r["meta"]), "tags": list(r["tags"])}


@router.delete("/kb/{kb_id}")
async def delete_kb(kb_id: int):
    n = await get_pool().execute("DELETE FROM kb_entries WHERE id=$1", kb_id)
    if n == "DELETE 0":
        raise HTTPException(404, "条目不存在")
    return {"ok": True}


class WeightIn(BaseModel):
    weight: int = 0  # 越大越靠前


@router.put("/kb/{kb_id}/weight")
async def set_kb_weight(kb_id: int, body: WeightIn):
    """只改排序权重（任意 kind 通用）：画风/音色/角色等库内卡片直接调它，免走整条更新。"""
    r = await get_pool().fetchrow(
        "UPDATE kb_entries SET weight=$2, updated_at=now() WHERE id=$1 RETURNING id, weight",
        kb_id, body.weight,
    )
    if not r:
        raise HTTPException(404, "条目不存在")
    return {"id": r["id"], "weight": r["weight"]}


@router.get("/kb/categories")
async def kb_categories():
    rows = await get_pool().fetch(
        "SELECT kind, category, count(*) AS n FROM kb_entries GROUP BY kind, category ORDER BY kind, category"
    )
    return [dict(r) for r in rows]


# ═══════════ 模型配置（参考 cocc-work model_profiles，api_key 掩码）═══════════

from .. import models_registry  # noqa: E402


def _mask_key(k: str) -> str:
    if not k or len(k) <= 6:
        return "***" if k else ""
    return f"{k[:3]}***{k[-4:]}"


def _profile_out(r: Any) -> dict:
    d = dict(r)
    d["api_key_masked"] = _mask_key(d.pop("api_key", ""))
    d["extra"] = _jsonb(d.get("extra"))
    return d


@router.get("/models")
async def list_models():
    rows = await get_pool().fetch(
        "SELECT * FROM model_profiles ORDER BY purpose, is_active DESC, id"
    )
    return [_profile_out(r) for r in rows]


# ── 厂商 key 预设：供模型配置下拉选择，只下发掩码 + ref，绝不下发明文 ──
# 内置来源自 settings(.env)；ref 稳定，解析时才回查明文（见 _resolve_key_ref）。
_ENV_KEY_SOURCES = [
    ("settings:ark", "火山 ARK", "ark", lambda: (settings.ARK_API_KEY, settings.ARK_BASE_URL)),
    ("settings:llm", "硅基流动 / OpenAI 兼容", "openai_compat", lambda: (settings.LLM_API_KEY, settings.LLM_BASE_URL)),
    ("settings:grsai", "GRSAI", "grsai", lambda: (settings.GRSAI_API_KEY, settings.GRSAI_BASE_URL)),
    ("settings:dashscope", "阿里云百炼 DashScope", "dashscope",
     lambda: (settings.DASHSCOPE_API_KEY, settings.DASHSCOPE_BASE_URL)),
    ("settings:minimax", "MiniMax", "minimax",
     lambda: (settings.MINIMAX_API_KEY, settings.MINIMAX_BASE_URL)),
]


async def _provider_key_presets() -> list[dict]:
    """可选厂商 key：①模型厂商页登记的 ②.env 配置的 ③已有模型档里独有的 key
    （都掩码、按 key 值去重）。线上 .env 清空时，③ 让已配好 key 的模型档仍可被新档沿用。"""
    seen: set[str] = set()
    out: list[dict] = []
    vendors = await get_pool().fetch(
        "SELECT id, label, provider, base_url, api_key FROM model_vendors "
        "WHERE api_key <> '' ORDER BY id")
    for v in vendors:
        if v["api_key"] in seen:
            continue
        seen.add(v["api_key"])
        out.append({"ref": f"vendor:{v['id']}", "label": v["label"], "provider": v["provider"],
                    "base_url": v["base_url"], "masked": _mask_key(v["api_key"])})
    for ref, label, provider, get in _ENV_KEY_SOURCES:
        key, base = get()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"ref": ref, "label": label, "provider": provider,
                    "base_url": base, "masked": _mask_key(key)})
    rows = await get_pool().fetch(
        "SELECT id, name, provider, base_url, api_key FROM model_profiles "
        "WHERE api_key <> '' ORDER BY id"
    )
    for r in rows:
        key = r["api_key"]
        if key in seen:
            continue
        seen.add(key)
        out.append({"ref": f"profile:{r['id']}", "label": f"沿用：{r['name']}",
                    "provider": r["provider"], "base_url": r["base_url"],
                    "masked": _mask_key(key)})
    return out


async def _resolve_key_ref(ref: str) -> str | None:
    """把预设 ref 解析成明文 key（仅服务端使用；解析不到返回 None）。"""
    for r, _label, _prov, get in _ENV_KEY_SOURCES:
        if r == ref:
            return get()[0] or None
    if ref.startswith("profile:"):
        try:
            pid = int(ref.split(":", 1)[1])
        except ValueError:
            return None
        return await get_pool().fetchval(
            "SELECT api_key FROM model_profiles WHERE id=$1", pid
        ) or None
    if ref.startswith("vendor:"):
        try:
            vid = int(ref.split(":", 1)[1])
        except ValueError:
            return None
        return await get_pool().fetchval(
            "SELECT api_key FROM model_vendors WHERE id=$1", vid
        ) or None
    return None


@router.get("/provider-keys")
async def list_provider_keys():
    """列出可选的厂商 key 预设（掩码）：模型配置下拉用，免手动粘贴。"""
    return await _provider_key_presets()


# ═══════════ 模型厂商（模型管理→模型厂商）═══════════
# 登记厂商凭据；登记后以 ref=vendor:{id} 出现在模型配置的「API Key 来源」下拉。

def _vendor_out(r: Any) -> dict:
    d = dict(r)
    d["api_key_masked"] = _mask_key(d.pop("api_key", ""))
    return d


class VendorIn(BaseModel):
    label: str = Field(min_length=1, description="厂商显示名，如「公司百炼主账号」")
    provider: str = Field(description="接口类型：ark / dashscope / minimax / grsai / openai_compat")
    base_url: str = ""
    api_key: str = Field(default="", description="留空=保持原 key 不变（编辑时）")


@router.get("/vendors")
async def list_vendors():
    rows = await get_pool().fetch(
        "SELECT id, label, provider, base_url, api_key, created_at, updated_at "
        "FROM model_vendors ORDER BY id")
    return [_vendor_out(r) for r in rows]


@router.post("/vendors")
async def create_vendor(body: VendorIn):
    r = await get_pool().fetchrow(
        "INSERT INTO model_vendors (label, provider, base_url, api_key) "
        "VALUES ($1,$2,$3,$4) RETURNING *",
        body.label, body.provider, body.base_url, body.api_key)
    return _vendor_out(r)


@router.put("/vendors/{vendor_id}")
async def update_vendor(vendor_id: int, body: VendorIn):
    # api_key 留空 = 保持原值（前端只显示掩码，避免误覆盖）
    r = await get_pool().fetchrow(
        """UPDATE model_vendors SET label=$2, provider=$3, base_url=$4,
                  api_key = CASE WHEN $5 = '' THEN api_key ELSE $5 END, updated_at=now()
           WHERE id=$1 RETURNING *""",
        vendor_id, body.label, body.provider, body.base_url, body.api_key)
    if not r:
        raise HTTPException(404, "厂商不存在")
    return _vendor_out(r)


@router.delete("/vendors/{vendor_id}")
async def delete_vendor(vendor_id: int):
    """删除厂商登记。已保存的模型档在保存时就把 key 明文拷进档里，不受影响。"""
    n = await get_pool().execute("DELETE FROM model_vendors WHERE id=$1", vendor_id)
    if n == "DELETE 0":
        raise HTTPException(404, "厂商不存在")
    return {"ok": True}


class ModelIn(BaseModel):
    purpose: str = Field(
        description="生成链路：text / image / video / tts / embedding；"
                    "专用挂档（不参与生成）：math / code / rerank / ocr / translate / other")
    provider: str = Field(description="openai_compat / grsai / ark / dashscope / minimax")
    name: str
    base_url: str
    api_key: str = Field(default="", description="留空=保持原 key 不变（编辑时）")
    key_ref: str = Field(default="", description="选预设厂商 key（如 settings:ark / profile:12）；填了则覆盖 api_key")
    model_name: str
    max_refs: int | None = Field(default=None, description="参考图/附件数量上限；空/0=用 provider 默认，生成时超出自动截断")
    extra: dict = {}


class ModelTestIn(ModelIn):
    id: int | None = None
    prompt: str = Field(min_length=1, max_length=4000)
    # 图像编辑族（qwen-image-edit 等）必须带 1~3 张底图才能测——弹窗里填可公开访问的图片 URL
    reference_images: list[str] | None = None


async def _effective_key(body: "ModelIn") -> str:
    """算出本次要写入的 api_key：选了预设 ref 就解析明文，否则用手填的 api_key（编辑时空=不改）。"""
    if body.key_ref:
        resolved = await _resolve_key_ref(body.key_ref)
        if not resolved:
            raise HTTPException(400, "所选厂商 key 不可用（未配置或已失效）")
        return resolved
    return body.api_key


async def _test_key(body: "ModelTestIn") -> str:
    key = await _effective_key(body)
    if not key and body.id:
        key = await get_pool().fetchval(
            "SELECT api_key FROM model_profiles WHERE id=$1", body.id
        ) or ""
    if not key:
        raise HTTPException(400, "请先选择或输入可用的 API Key")
    return key


def _embedding_request(base: str, model: str, text: str) -> tuple[str, dict[str, Any]]:
    """按模型能力拼正确的向量 API。

    方舟 doubao-embedding-vision 是多模态模型，普通资源包走
    /api/v3/embeddings/multimodal；Coding Plan 的 /api/coding/v3 则保持
    OpenAI 兼容 /embeddings。Base URL 也兼容用户已填写完整 endpoint 的情况。
    """
    clean = base.rstrip("/")
    is_vision = "doubao-embedding-vision" in model.lower()
    if clean.endswith("/embeddings/multimodal"):
        return clean, {
            "model": model, "input": [{"type": "text", "text": text}],
            "encoding_format": "float",
        }
    if is_vision and "/api/coding/v3" not in clean:
        return f"{clean}/embeddings/multimodal", {
            "model": model, "input": [{"type": "text", "text": text}],
            "encoding_format": "float",
        }
    endpoint = clean if clean.endswith("/embeddings") else f"{clean}/embeddings"
    return endpoint, {"model": model, "input": text, "encoding_format": "float"}


def _embedding_vector(payload: dict[str, Any]) -> list[float]:
    """兼容 OpenAI data=[{embedding}] 与方舟多模态 data={embedding:[[...]]}。"""
    data = payload.get("data")
    item = data[0] if isinstance(data, list) else data
    vector = item.get("embedding") if isinstance(item, dict) else None
    while isinstance(vector, list) and len(vector) == 1 and isinstance(vector[0], list):
        vector = vector[0]
    if not isinstance(vector, list) or not vector:
        raise ValueError("向量响应中没有 embedding")
    return vector


async def run_model_test(purpose: str, provider: str, base_url: str, key: str,
                         model_name: str, prompt: str, extra: dict[str, Any] | None = None,
                         reference_images: list[str] | None = None) -> dict:
    """按模态做一次真实调用，返回可直接预览的结果。**模型测试的唯一实现**——
    模型配置弹框与资源包行的「测试」按钮都走它，判据/回显只此一份。"""
    base = base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    # 180s：带思维链的推理模型（如 GLM）单次调用可达 60~150s，120s 会把还在思考的请求掐断
    timeout = httpx.Timeout(180.0, connect=15.0)
    extra = extra or {}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # chat 形接口的用途：文本/质检 + 数学/代码/翻译/其它专用挂档（同走 /chat/completions，
            # 测一下正好能看出"这模型到底会说人话还是只会解题"）
            if purpose in ("text", "review", "math", "code", "translate", "other"):
                # max_tokens 2048：推理模型的 reasoning_content 同样计入 completion，
                # 512 会在思维链阶段被截断 → message.content 为空，测试看似"无响应"
                r = await client.post(
                    f"{base}/chat/completions", headers=headers,
                    json={"model": model_name,
                          "messages": [{"role": "user", "content": prompt}],
                          "max_tokens": 2048},
                )
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"]
                return {"kind": "text", "text": text}
            if purpose == "embedding":
                endpoint, payload = _embedding_request(base, model_name, prompt)
                # 知识库固定为 vector(1024)；Qwen3 支持显式锁维，其他模型忽略此参数更稳。
                if "Qwen3-Embedding" in model_name:
                    payload["dimensions"] = 1024
                r = await client.post(endpoint, headers=headers, json=payload)
                r.raise_for_status()
                vector = _embedding_vector(r.json())
                return {
                    "kind": "vector", "vector": vector, "dimensions": len(vector),
                    "endpoint": endpoint,
                    "storage_compatible": len(vector) == embeddings.EMBED_DIM,
                    "storage_dimensions": embeddings.EMBED_DIM,
                }
            if purpose == "image":
                # 百炼生图不在兼容模式里（/images/generations 实测 404），走原生接口；
                # 协议（同步多模态/异步任务）按模型族在 dashscope 层路由，extra 原样传入
                if provider == "dashscope":
                    url = await dashscope.image_synthesis(
                        base, key, model_name, prompt, None,
                        reference_images=reference_images, extra=extra or {})
                    return {"kind": "image", "url": url}
                if provider == "minimax":
                    r = await client.post(
                        f"{base}/image_generation", headers=headers,
                        json={"model": model_name, "prompt": prompt, "aspect_ratio": "1:1"},
                    )
                    r.raise_for_status()
                    urls = (r.json().get("data") or {}).get("image_urls") or []
                    if not urls:
                        raise ValueError("MiniMax 图片响应中没有 image_urls")
                    return {"kind": "image", "url": str(urls[0])}
                payload = {"model": model_name, "prompt": prompt}
                if provider == "ark":
                    payload["watermark"] = False
                    payload["size"] = "1024x1024"
                r = await client.post(
                    f"{base}/images/generations", headers=headers, json=payload
                )
                r.raise_for_status()
                item = (r.json().get("data") or [{}])[0]
                url = item.get("url")
                if not url and item.get("b64_json"):
                    url = f"data:image/png;base64,{item['b64_json']}"
                if not url:
                    raise ValueError("图片响应中没有 url 或 b64_json")
                return {"kind": "image", "url": url}
            if purpose == "tts":
                r = await client.post(
                    f"{base}/audio/speech", headers=headers,
                    json={"model": model_name, "input": prompt,
                          "voice": str(extra.get("voice") or "alex"),
                          "response_format": "mp3"},
                )
                r.raise_for_status()
                audio = base64.b64encode(r.content).decode()
                return {"kind": "audio", "url": f"data:audio/mpeg;base64,{audio}"}
            if purpose == "video":
                raise HTTPException(400, "视频模型测试会产生长任务，请在视频生成工作台验证")
            raise HTTPException(400, f"「{purpose}」类模型没有通用测试口，请到厂商控制台验证")
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        raise HTTPException(exc.response.status_code, f"模型调用失败：{detail}") from exc
    except (httpx.HTTPError, KeyError, IndexError, ValueError,
            RuntimeError, TimeoutError) as exc:
        raise HTTPException(502, f"模型响应异常：{str(exc)[:500]}") from exc


@router.post("/models/test")
async def test_model(body: ModelTestIn):
    """使用弹框中尚未保存的配置做一次真实调用，并按模态返回可直接预览的结果。"""
    key = await _test_key(body)
    return await run_model_test(body.purpose, body.provider, body.base_url, key,
                                body.model_name, body.prompt, body.extra,
                                reference_images=body.reference_images)


def _guard_purpose(body: "ModelIn") -> None:
    """写入前拦下"模型能力对不上用途"的档（**唯一实现**，新增/编辑共用）。

    根治 2026-08-01 事故：qwen-math-turbo 被挂成 text 并激活，整条质检/预检链路
    静默降级空转数小时。判据同源于 resource_map（资源包模态派生用的是同一份），
    extra.force_purpose=true 是判据误伤时的逃生阀。"""
    if body.extra.get("force_purpose"):
        return
    why = resource_map.purpose_conflict(body.purpose, body.model_name)
    if why:
        raise HTTPException(400, why)


@router.post("/models")
async def create_model(body: ModelIn):
    _guard_purpose(body)
    api_key = await _effective_key(body)
    r = await get_pool().fetchrow(
        """INSERT INTO model_profiles (purpose, provider, name, base_url, api_key, model_name, max_refs, extra)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb) RETURNING *""",
        body.purpose, body.provider, body.name, body.base_url, api_key,
        body.model_name, body.max_refs or None, json.dumps(body.extra, ensure_ascii=False),
    )
    models_registry.invalidate()
    return _profile_out(r)


@router.put("/models/{model_id}")
async def update_model(model_id: int, body: ModelIn):
    _guard_purpose(body)
    # api_key 留空 = 保持原值（前端只显示掩码，避免误覆盖）；选了预设 ref 则解析明文覆盖
    api_key = await _effective_key(body)
    r = await get_pool().fetchrow(
        """UPDATE model_profiles SET purpose=$2, provider=$3, name=$4, base_url=$5,
                  api_key = CASE WHEN $6 = '' THEN api_key ELSE $6 END,
                  model_name=$7, max_refs=$8, extra=$9::jsonb, updated_at=now()
           WHERE id=$1 RETURNING *""",
        model_id, body.purpose, body.provider, body.name, body.base_url,
        api_key, body.model_name, body.max_refs or None, json.dumps(body.extra, ensure_ascii=False),
    )
    if not r:
        raise HTTPException(404, "profile 不存在")
    models_registry.invalidate()
    return _profile_out(r)


@router.post("/models/{model_id}/activate")
async def activate_model(model_id: int):
    """激活此档为该 purpose 的当前模型（压掉同 purpose 其它 active）。"""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT purpose FROM model_profiles WHERE id=$1", model_id)
            if not row:
                raise HTTPException(404, "profile 不存在")
            await conn.execute(
                "UPDATE model_profiles SET is_active=FALSE WHERE purpose=$1", row["purpose"]
            )
            await conn.execute(
                "UPDATE model_profiles SET is_active=TRUE, updated_at=now() WHERE id=$1", model_id
            )
    models_registry.invalidate()
    return {"ok": True}


@router.delete("/models/{model_id}")
async def delete_model(model_id: int):
    n = await get_pool().execute("DELETE FROM model_profiles WHERE id=$1", model_id)
    if n == "DELETE 0":
        raise HTTPException(404, "profile 不存在")
    # 顺带清掉功能配置里挂着这个档的行，避免孤儿引用
    await get_pool().execute(
        "DELETE FROM feature_model_prefs WHERE model_profile_id=$1", model_id)
    models_registry.invalidate()
    return {"ok": True}


# ═══════════ 功能配置（模型管理→功能配置）═══════════
# 功能清单后端写死（feature_registry.py 唯一权威）；这里只维护"每个功能挂哪些模型、什么顺序"。
from .. import feature_registry  # noqa: E402


@router.get("/model-features")
async def list_model_features():
    """全部功能 + 各自已配置的有序模型列表（seq 升序，第一个即默认）。"""
    rows = await get_pool().fetch(
        """SELECT f.feature_code, m.id, m.name, m.provider, m.model_name, m.purpose
           FROM feature_model_prefs f JOIN model_profiles m ON m.id=f.model_profile_id
           ORDER BY f.feature_code, f.seq, f.model_profile_id"""
    )
    by_code: dict[str, list[dict]] = {}
    for r in rows:
        by_code.setdefault(r["feature_code"], []).append(
            {"id": r["id"], "name": r["name"], "provider": r["provider"],
             "model_name": r["model_name"], "purpose": r["purpose"]})
    return [{"code": f.code, "label": f.label, "purpose": f.purpose, "hint": f.hint,
             "models": by_code.get(f.code, [])} for f in feature_registry.all_features()]


class FeatureModelsIn(BaseModel):
    model_profile_ids: list[int] = Field(
        description="该功能的完整有序模型档 id 列表（第一个=默认）；空列表=清空回退 active 档")


@router.put("/model-features/{code}")
async def save_model_feature(code: str, body: FeatureModelsIn):
    """整表替换该功能的模型顺序。校验：功能 code 必须在注册表里，模型档 purpose 必须匹配功能。"""
    try:
        feat = feature_registry.get(code)
    except ValueError:
        raise HTTPException(404, f"未知功能 code：{code}") from None
    ids = list(dict.fromkeys(body.model_profile_ids))  # 去重保序
    if ids:
        rows = await get_pool().fetch(
            "SELECT id, purpose, name FROM model_profiles WHERE id = ANY($1::bigint[])", ids)
        found = {r["id"]: r for r in rows}
        for pid in ids:
            r = found.get(pid)
            if not r:
                raise HTTPException(400, f"模型档 {pid} 不存在")
            if r["purpose"] != feat.purpose:
                raise HTTPException(
                    400, f"「{r['name']}」是 {r['purpose']} 模型，"
                         f"「{feat.label}」只能挂 {feat.purpose} 模型")
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM feature_model_prefs WHERE feature_code=$1", code)
            for seq, pid in enumerate(ids):
                await conn.execute(
                    "INSERT INTO feature_model_prefs (feature_code, model_profile_id, seq) "
                    "VALUES ($1,$2,$3)", code, pid, seq)
    models_registry.invalidate()
    return {"ok": True}


# ═══════════ 向量嵌入回填（pgvector；需已装 pgvector 且 kb_entries.embedding 存在）═══════════

@router.post("/kb/embed-backfill")
async def kb_embed_backfill(only_missing: bool = True, limit: int = 500):
    """给 kb_entries(scope=global) 回填向量嵌入：文本取 name+description+content，
    用 embedding 档（硅基流动 bge-m3, 1024 维）批量转向量写回 embedding 列。
    默认只补空的行；pgvector 未就绪时明确报错而非静默。"""
    pool = get_pool()
    has_col = await pool.fetchval(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name='kb_entries' AND column_name='embedding'")
    if not has_col:
        raise HTTPException(400, "kb_entries 无 embedding 列：pgvector 未就绪（换 pgvector 镜像后重启自动建）")
    where = "embedding IS NULL AND " if only_missing else ""
    rows = await pool.fetch(
        f"SELECT id, name, COALESCE(description,'') d, COALESCE(content,'') c "
        f"FROM kb_entries WHERE {where}scope='global' AND enabled ORDER BY id LIMIT $1",
        limit)
    if not rows:
        return {"ok": True, "embedded": 0, "note": "无待补行"}
    texts = [f"{r['name']}。{r['d']}。{r['c']}" for r in rows]
    vecs = await embeddings.embed(texts)
    n = 0
    async with pool.acquire() as conn:
        for r, v in zip(rows, vecs):
            await conn.execute(
                "UPDATE kb_entries SET embedding=$2::vector WHERE id=$1",
                r["id"], embeddings.to_pgvector(v))
            n += 1
    return {"ok": True, "embedded": n}


# ═══════════ 生成日志（2026-07-12 视频；2026-07-14 扩展到图片+来源标记）═══════════

_ASSET_PREFIX = "asset://"


def _asset_uris_in(req: Any) -> set[str]:
    """一条日志 request 里引用到的 asset://<ark_asset_id>（参考图/图片入参两处）。"""
    uris: set[str] = set()
    if not isinstance(req, dict):
        return uris
    for c in req.get("content") or []:
        u = (c.get("image_url") or {}).get("url") if isinstance(c, dict) else None
        if isinstance(u, str) and u.startswith(_ASSET_PREFIX):
            uris.add(u)
    for u in req.get("image") or []:
        if isinstance(u, str) and u.startswith(_ASSET_PREFIX):
            uris.add(u)
    return uris


async def _attach_asset_refs(logs: list[dict[str, Any]]) -> None:
    """把日志里引用的火山备案素材 asset://<ark_asset_id> 解析成真实形象图地址+角色名。

    存库的审计原文保持不动（asset:// 是提交给火山的真实入参，不能改）；仅在读取时给每条日志
    补一个 assets 映射 {asset_uri: {url, name}}，供前端把「备案角色」参考图显示成真图+角标。
    """
    all_uris: set[str] = set()
    for g in logs:
        all_uris |= _asset_uris_in(g.get("request"))
    if not all_uris:
        return
    ids = [u[len(_ASSET_PREFIX):] for u in all_uris]
    rows = await get_pool().fetch(
        "SELECT ark_asset_id, image_url, name FROM ark_characters "
        "WHERE ark_asset_id = ANY($1) AND image_url <> ''", ids)
    by_id = {r["ark_asset_id"]: {"url": r["image_url"], "name": r["name"]} for r in rows}
    for g in logs:
        m = {u: by_id[u[len(_ASSET_PREFIX):]]
             for u in _asset_uris_in(g.get("request"))
             if u[len(_ASSET_PREFIX):] in by_id}
        if m:
            g["assets"] = m


@router.get("/gen-logs")
async def list_gen_logs(project_id: int | None = None, node_id: int | None = None,
                        status: str | None = None, media: str | None = None,
                        source: str | None = None, task_id: int | None = None,
                        page: int = 1, page_size: int = 20):
    """生成审计日志：每次真实提交一行（含完整 content 入参、降级序号、模态摘要），
    视频异步结果按 task_id 回写同行；联 task_queue 带出任务终态便于对照。倒序分页。
    media=video/image 按大类筛；source 前缀筛（project_10_2_21 命中该分镜的图+视频全部记录，
    kb_style_35 命中该风格库条目的全部生成记录）。"""
    conds, args = [], []
    if project_id:
        args.append(project_id)
        conds.append(f"g.project_id=${len(args)}")
    if node_id:
        args.append(node_id)
        conds.append(f"g.node_id=${len(args)}")
    if status:
        args.append(status)
        conds.append(f"g.status=${len(args)}")
    if media == "video":
        conds.append("g.kind='gen_video'")
    elif media == "image":
        conds.append("g.kind<>'gen_video'")
    if source:
        args.append(source)
        conds.append(f"g.source LIKE ${len(args)} || '%'")
    if task_id:
        args.append(task_id)
        conds.append(f"g.task_id=${len(args)}")
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    where_sql = " WHERE " + " AND ".join(conds) if conds else ""
    total = await get_pool().fetchval(
        "SELECT COUNT(*) FROM gen_logs g" + where_sql,
        *args,
    )
    args.extend((page_size, (page - 1) * page_size))
    rows = await get_pool().fetch(
        "SELECT g.*, t.status AS task_status, t.error AS task_error "
        "FROM gen_logs g LEFT JOIN task_queue t ON t.id=g.task_id"
        + where_sql
        + f" ORDER BY g.id DESC LIMIT ${len(args) - 1} OFFSET ${len(args)}",
        *args,
    )
    logs = []
    for row in rows:
        item = dict(row)
        item["request"] = _jsonb(row["request"])
        item["result"] = _jsonb(row["result"]) if row["result"] else None
        for key, fallback in (
            ("employee_codes", []), ("skill_slugs", []),
            ("knowledge_refs", []), ("planner_snapshot", {}),
        ):
            value = item.get(key)
            item[key] = _jsonb(value) if value else fallback
        logs.append(item)
    await _attach_asset_refs(logs)
    return {
        "items": logs,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ═══════════ 资源包剩余（火山导出的有余量模型包→浏览+一键插入模型管理，见 resource_map）═══════════

from .. import resource_map  # noqa: E402


@router.get("/resource-packages")
async def list_resource_packages(search: str | None = None, modality: str | None = None,
                                 vendor: str | None = None, only_remaining: bool = False):
    """模型类资源包：每行补 vendor（火山方舟/阿里百炼）+ modality + 真实模型名；支持拍寻/模态/厂商过滤。
    默认含已用完的（前端标红+可删）；only_remaining=true 仅留有余量的。"""
    rows = await get_pool().fetch(
        "SELECT * FROM resource_packages ORDER BY remaining DESC, config_name"
    )
    out = [resource_map.enrich(dict(r)) for r in rows]
    if only_remaining:
        out = [r for r in out if r["remaining"] > 0]
    if vendor:
        out = [r for r in out if r["vendor"] == vendor]
    if modality:
        out = [r for r in out if r["modality"] == modality]
    if search:
        s = search.lower()
        out = [r for r in out if s in r["config_name"].lower()
               or s in r["real_model_name"].lower() or s in r["product"].lower()]
    return out


@router.post("/resource-packages/import")
async def import_resource_packages(file: UploadFile = File(...),
                                   vendor: str = Form(resource_map.DEFAULT_VENDOR)):
    """重传厂商控制台导出的 CSV，刷新该厂商的资源包余量（另一家的行不受影响）。

    volc=火山方舟「资源包总览」，bailian=阿里百炼「免费额度 / Token Plan」。"""
    if vendor not in resource_map.VENDOR_LABEL:
        raise HTTPException(400, "未知厂商")
    raw = await file.read()
    text = raw.decode("utf-8-sig", errors="replace")
    rows = resource_map.parse_csv(text, vendor)
    n = await resource_map.replace_all(get_pool(), rows, vendor)
    return {"count": n}


class ResourcePackageIn(BaseModel):
    """手动登记一条资源包/免费额度（百炼控制台没有 CSV 导出时用）。"""
    vendor: str = "bailian"
    config_name: str = Field(min_length=1, max_length=200, description="模型 Code / 配置名称")
    instance_id: str = ""
    product: str = ""
    spec: str = ""
    spec_unit: str = "tokens"
    total: float = 0
    remaining: float = 0
    status: str = ""
    purchased_at: str = ""
    effective_at: str = ""
    expires_at: str = ""
    provider_entity: str = ""


@router.post("/resource-packages")
async def create_resource_package(body: ResourcePackageIn):
    """手动新增/更新一条资源包；instance_id 留空时按厂商+模型名自动生成主键。"""
    if body.vendor not in resource_map.VENDOR_LABEL:
        raise HTTPException(400, "未知厂商")
    row = body.model_dump()
    row["config_name"] = row["config_name"].strip()
    row["instance_id"] = row["instance_id"].strip() or f"{body.vendor}:{row['config_name']}"
    if not row["product"]:
        row["product"] = resource_map.VENDOR_LABEL[body.vendor]
    return await resource_map.upsert_one(get_pool(), row)


@router.delete("/resource-packages/{instance_id}")
async def delete_resource_package(instance_id: str):
    """删除一条资源包记录（仅本地展示表，不影响火山账户）。"""
    n = await get_pool().execute(
        "DELETE FROM resource_packages WHERE instance_id=$1", instance_id
    )
    if n == "DELETE 0":
        raise HTTPException(404, "资源包不存在")
    return {"ok": True}


class ToModelIn(BaseModel):
    activate: bool = False  # True=顺带设为该 purpose 的当前模型


# 凭据来源 → (base_url, api_key, 该凭据在 provider-keys 里的 provider 名)
_CRED_SOURCE = {
    "ark": lambda: (settings.ARK_BASE_URL, settings.ARK_API_KEY, "ark"),
    "llm": lambda: (settings.LLM_BASE_URL, settings.LLM_API_KEY, "openai_compat"),
    "dashscope": lambda: (settings.DASHSCOPE_BASE_URL, settings.DASHSCOPE_API_KEY, "dashscope"),
}


async def _get_package(instance_id: str) -> dict:
    row = await get_pool().fetchrow(
        "SELECT * FROM resource_packages WHERE instance_id=$1", instance_id
    )
    if not row:
        raise HTTPException(404, "资源包不存在")
    return resource_map.enrich(dict(row))


async def _package_model_target(pkg: dict) -> tuple[str, str, str, str]:
    """资源包 → (purpose, provider, base_url, 系统内置厂商 key)。**唯一实现**：
    「插入模型管理」与行内「测试」共用，两处凭据来源必须同源。

    .env 里没配该厂商 key（线上常态）时，回退到该厂商唯一可用的预设 key。
    按 cred 匹配（火山 text 走兼容口但需 ARK key，故 provider≠凭据来源）。"""
    purpose, provider, cred = resource_map.profile_target(pkg["modality"], pkg["vendor"])
    base_url, api_key, cred_provider = _CRED_SOURCE.get(cred, _CRED_SOURCE["llm"])()
    if not api_key:
        mine = [p for p in await _provider_key_presets() if p["provider"] == cred_provider]
        if len(mine) == 1:
            api_key = await _resolve_key_ref(mine[0]["ref"]) or ""
    return purpose, provider, base_url, api_key


class PackageTestIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)


@router.post("/resource-packages/{instance_id}/test")
async def test_resource_package(instance_id: str, body: PackageTestIn):
    """用系统内置的厂商 Key 直接试这个资源包里的模型，不必先插入模型管理。
    purpose/provider/凭据与「插入模型管理」同源（_package_model_target）。"""
    pkg = await _get_package(instance_id)
    purpose, provider, base_url, api_key = await _package_model_target(pkg)
    if not api_key:
        raise HTTPException(400, f"没有可用的{pkg['vendor_label']} API Key："
                                 "请先在 backend/.env 或模型配置里补该厂商 Key")
    return await run_model_test(purpose, provider, base_url, api_key,
                                pkg["real_model_name"], body.prompt)


@router.post("/resource-packages/{instance_id}/to-model")
async def resource_package_to_model(instance_id: str, body: ToModelIn):
    """把资源包一键插入模型管理（按模态映射 purpose/provider，凭据自 settings 补全）；activate=设为默认。"""
    pkg = await _get_package(instance_id)
    purpose, provider, base_url, api_key = await _package_model_target(pkg)
    name = resource_map.display_name(pkg["config_name"], pkg["vendor"])
    model_name = pkg["real_model_name"]
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow(
                "SELECT id FROM model_profiles WHERE purpose=$1 AND (name=$2 OR model_name=$3)",
                purpose, name, model_name,
            )
            if existing:
                pid = existing["id"]
                await conn.execute(
                    "UPDATE model_profiles SET provider=$2, base_url=$3, "
                    "api_key=CASE WHEN $4='' THEN api_key ELSE $4 END, "
                    "model_name=$5, updated_at=now() WHERE id=$1",
                    pid, provider, base_url, api_key, model_name,
                )
            else:
                pid = await conn.fetchval(
                    "INSERT INTO model_profiles (purpose, provider, name, base_url, api_key, model_name) "
                    "VALUES ($1,$2,$3,$4,$5,$6) RETURNING id",
                    purpose, provider, name, base_url, api_key, model_name,
                )
            if body.activate:
                await conn.execute(
                    "UPDATE model_profiles SET is_active=FALSE WHERE purpose=$1", purpose
                )
                await conn.execute(
                    "UPDATE model_profiles SET is_active=TRUE, updated_at=now() WHERE id=$1", pid
                )
    models_registry.invalidate()
    return {"id": pid, "purpose": purpose, "provider": provider, "name": name,
            "model_name": model_name, "activated": body.activate,
            "reused": bool(existing)}
