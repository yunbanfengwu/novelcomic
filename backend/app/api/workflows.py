"""工作流引擎 API（2026-07-29 新增，纯增量）。

刻意与现有生成链路**完全解耦**：本模块不改任何既有接口的行为，工作流跑与不跑，
老流程一模一样。等工作流版稳定了，再把入口按钮切过来、最后废弃硬编码链路。
"""
import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import get_pool
from ..services import tapflow_ai, workflow as wf
from ..services.canonical_inputs import (
    CanonicalInputError, SmartInputSelection, resolve_canonical_inputs,
)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class WorkflowIn(BaseModel):
    slug: str
    name: str
    description: str = ""
    input_schema: dict[str, Any] = {}
    output_schema: dict[str, Any] = {}
    graph: dict[str, Any] = {"nodes": [], "edges": []}
    # 排序（需求优先级，小者在前）。不传则保留库里已有值——保存图不应该动排序
    seq: int | None = None
    # 标签（多值；第一个兼当列表页分组名）。不传同样保留库里已有值
    tags: list[str] | None = None
    # 画布保存用：目标版本已 published 时，另存成新的草稿版本而不是原地覆盖。
    # 已发布的图可能正被别的流程按 slug+version 引用，原地改会立刻影响在跑的运行。
    draft_from_published: bool = False


class RunIn(BaseModel):
    project_id: int | None = None
    node_id: int | None = None
    version: int | None = None
    inputs: dict[str, Any] = {}
    # async = 画布模式：立返 run_id，后台跑，前端轮询 /runs/{id}/nodes 点亮节点
    mode: str = "sync"
    # 节点级强制重跑：命中的 task/subflow 跳过「缺才跑」（如 ["gen"]）
    force: list[str] = []
    # 节点级覆盖 {节点id: {instruction: "…"}}：画布生成条里改的提示词当**指令层**送进来，
    # 改得动 user 段，改不动 anchor 段（版式/画风/质量词仍由绑定的最小集锁死）
    node_overrides: dict[str, Any] = {}
    # 跑到这个节点为止（画布的「结束节点」）。没有对应的「从哪开始」——整图永远从头走，
    # 起点之前靠「缺才跑」自然只查不生成，画布的「开始节点」是用 force 表达的
    stop_after: str | None = None
    # 下面两个只为「下次打开画布回填」而收：引擎不读它们（引擎只认 force/stop_after）。
    # force 是 range 折算后的结果（range.from 可能是非花钱节点，折算不可逆），所以
    # 要回填运行范围就得把 range 原样存一份
    force_all: bool = False
    run_range: dict[str, Any] | None = None

    def run_options(self) -> dict[str, Any]:
        """整份「怎么跑」→ workflow_runs.run_options（见 sql/59）。"""
        return {
            "force": self.force, "stop_after": self.stop_after,
            "force_all": self.force_all, "range": self.run_range,
            "node_overrides": self.node_overrides,
        }


class SmartInputsIn(BaseModel):
    version: int | None = None
    project_id: int | None = None
    asset_type: str | None = None
    volume_id: int | None = None
    chapter_id: int | None = None
    shot_id: int | None = None
    material_kind: str | None = None
    material_ref: str | None = None


@router.get("")
async def list_workflows(include_instances: bool = False):
    """编排列表。**默认不含画布实例**（subject_id 非空的那些）：每个场景/要素在生产态
    改一次画布就会 fork 出一份，全列出来会把编排台淹掉。它们的入口在各自的业务页
    （素材库点那个场景就打开它自己的画布）。

    每条带 bindings：end 节点声明的存储目标清单（如 ["project_cover"]）——
    业务页据此决定「生成封面」这类按钮是否直接打开这张画布（2026-09-17）。"""
    # seq=0 是「未分配」（新建的编排），排到已排序的后面，再按 slug 兜底
    rows = await get_pool().fetch(
        "SELECT id,slug,name,description,version,status,seq,tags,updated_at,smart_call,"
        "origin_slug,subject_kind,subject_id,graph FROM workflows "
        "WHERE ($1 OR subject_id IS NULL) "
        "ORDER BY NULLIF(seq,0) NULLS LAST, slug, version DESC", include_instances)
    out = []
    for r in rows:
        d = dict(r)
        graph = d.pop("graph") or {}
        if isinstance(graph, str):
            graph = json.loads(graph)
        binds = sorted({str(n["config"]["store"]["target"])
                        for n in (graph.get("nodes") or [])
                        if n.get("type") == "end"
                        and isinstance(n.get("config"), dict)
                        and isinstance(n["config"].get("store"), dict)
                        and n["config"]["store"].get("target")})
        d["bindings"] = binds
        out.append(d)
    return out


@router.get("/{slug}")
async def get_workflow(slug: str, version: int | None = None):
    try:
        d = await wf.load_workflow(get_pool(), slug, version)
    except wf.WorkflowError as e:
        raise HTTPException(404, str(e)) from e
    return d


@router.post("")
async def save_workflow(body: WorkflowIn):
    """保存草稿。**保存时就查环与签名**，不等跑起来才炸。

    版本语义：默认写在当前最高版本上（原地覆盖）。带 `draft_from_published` 时，
    若那个版本已 published 则**版本号 +1 存成草稿**——画布编辑走这条，改完要
    显式发布才对运行生效，不会把正在被引用的已发布版本改掉。"""
    errors = wf.validate_graph(body.graph)
    if errors:
        raise HTTPException(422, "；".join(errors))
    import json
    pool = get_pool()
    top = await pool.fetchrow(
        "SELECT version,status,seq,tags,origin_slug,subject_kind,subject_id,smart_call "
        "FROM workflows WHERE slug=$1 ORDER BY version DESC LIMIT 1", body.slug)
    ver = int(top["version"]) if top else 0
    if body.draft_from_published and top and top["status"] == "published":
        ver += 1
    # 存**新版本**时，调用方没带的 tags/seq 从上一版继承。
    # 原来只在 ON CONFLICT UPDATE 分支写了 `coalesce($9, workflows.tags)`，
    # 而新版本走 INSERT 分支 → coalesce(null,'{}') → 标签被清空。后果是画布存一次
    # 新版本就掉一次 canvas 标签，列表按标签筛，于是"发布了却还是看到旧版本"
    # （实测：v9 存出来 tags=[]，列表里最新 canvas 流程仍是 v8）。
    tags = body.tags if body.tags is not None else (list(top["tags"]) if top else None)
    seq = body.seq if body.seq is not None else (top["seq"] if top else None)
    # 画布实例的归属（origin_slug/subject_kind/subject_id）跟着 slug 走，存新版本时必须带上：
    # 漏了它，实例存出第二个版本就查不回「这是谁的画布」，下次打开又回到模板
    row = await pool.fetchrow(
        "INSERT INTO workflows(slug,name,description,version,status,input_schema,"
        "output_schema,graph,seq,tags,origin_slug,subject_kind,subject_id,smart_call) "
        "VALUES ($1,$2,$3,$4,$10,$5::jsonb,$6::jsonb,"
        "$7::jsonb,coalesce($8,0),coalesce($9,'{}'::text[]),$11,$12,$13,coalesce($14,false)) "
        "ON CONFLICT (slug,version) DO UPDATE SET name=excluded.name,"
        "description=excluded.description,input_schema=excluded.input_schema,"
        "output_schema=excluded.output_schema,graph=excluded.graph,"
        "seq=coalesce($8,workflows.seq),tags=coalesce($9,workflows.tags),"
        "updated_at=now() "
        "RETURNING id,slug,version,status,seq,tags",
        body.slug, body.name, body.description, max(ver, 1),
        json.dumps(body.input_schema, ensure_ascii=False),
        json.dumps(body.output_schema, ensure_ascii=False),
        json.dumps(body.graph, ensure_ascii=False), seq, tags,
        # 实例是「一个人的画布」，没有别的流程按 slug+version 引用它 → 存即生效，
        # 不走草稿/发布两态（否则生产态用户每改一次都得再点一次发布才跑得到新图）
        "published" if (top and top["subject_id"] is not None) else "draft",
        top["origin_slug"] if top else None,
        top["subject_kind"] if top else None,
        top["subject_id"] if top else None,
        # 智能调用是「这张流程能不能被当智能节点引用」的属性，跟着 slug 走。
        # 存新版本时不带上，改一次图就掉一次开关（tags 早先正是这么掉的）。
        top["smart_call"] if top else False)
    return dict(row)


class SmartCallIn(BaseModel):
    smart_call: bool


@router.patch("/{slug}/smart-call")
async def set_smart_call(slug: str, body: SmartCallIn):
    """标记「支持智能调用」。与 tags 同理按 slug 全版本一起改：这是流程的能力声明，
    不是某一版的图内容——版本之间半开半关只会让引用方行为随版本漂移。"""
    pool = get_pool()
    n = await pool.execute(
        "UPDATE workflows SET smart_call=$2, updated_at=now() WHERE slug=$1", slug, body.smart_call)
    if n.endswith(" 0"):
        raise HTTPException(404, f"{slug} 不存在")
    # 同时记进能力表：sql/60 每次启动会把种子流程整行删掉重建，只写行上那份的话
    # 用户的设置在下次重启后就没了（见 sql/92 的注释）。启动时由 sql/92 还原。
    await pool.execute(
        "INSERT INTO workflow_capabilities(slug,smart_call) VALUES ($1,$2) "
        "ON CONFLICT (slug) DO UPDATE SET smart_call=excluded.smart_call, updated_at=now()",
        slug, body.smart_call)
    return {"ok": True, "slug": slug, "smart_call": body.smart_call}


class TagsIn(BaseModel):
    tags: list[str] = []


@router.patch("/{slug}/tags")
async def set_tags(slug: str, body: TagsIn):
    """只改标签（列表页标色用）。不走 save_workflow——那条路要带整张图，
    列表页手里只有摘要；标签也不是版本化内容，按 slug 全版本一起改。"""
    n = await get_pool().execute(
        "UPDATE workflows SET tags=$2::text[], updated_at=now() WHERE slug=$1",
        slug, body.tags)
    if n.endswith(" 0"):
        raise HTTPException(404, f"{slug} 不存在")
    return {"ok": True, "slug": slug, "tags": body.tags}


@router.post("/{slug}/publish")
async def publish_workflow(slug: str, version: int):
    """发布一个版本。子工作流引用固定到已发布版本——否则改一下被引用的工作流，
    所有调用方行为当场全变。"""
    n = await get_pool().execute(
        "UPDATE workflows SET status='published', updated_at=now() "
        "WHERE slug=$1 AND version=$2", slug, version)
    if n.endswith(" 0"):
        raise HTTPException(404, f"{slug} v{version} 不存在")
    return {"ok": True, "slug": slug, "version": version}


@router.post("/{slug}/smart-inputs/resolve")
async def resolve_smart_inputs(slug: str, body: SmartInputsIn):
    """Resolve fixed smart selectors and match them to this workflow's real inputs."""
    pool = get_pool()
    try:
        workflow = await wf.load_workflow(pool, slug, body.version)
        canonical = await resolve_canonical_inputs(pool, SmartInputSelection(
            project_id=body.project_id, asset_type=body.asset_type,
            volume_id=body.volume_id, chapter_id=body.chapter_id,
            shot_id=body.shot_id, material_kind=body.material_kind,
            material_ref=body.material_ref,
        ))
    except wf.WorkflowError as exc:
        raise HTTPException(404, str(exc)) from exc
    except CanonicalInputError as exc:
        raise HTTPException(422, str(exc)) from exc
    input_schema = workflow.get("input_schema") or {}
    return {
        "inputs": canonical.match(input_schema),
        "labels": canonical.labels(input_schema),
    }


class InstanceIn(BaseModel):
    """画布实例绑定的业务对象：这份副本是「谁的画布」。

    ⚠ subject 而非 owner：`workflows.owner_id` 是用户所有权（谁建的这张图），
    与「这张画布属于哪个场景」完全是两回事，同名会把两种归属搅在一起。"""

    subject_kind: str          # element | project | …（业务对象类型）
    subject_id: int            # 该对象主键
    name: str = ""             # 实例显示名，不传按「模板名 · 对象名」兜底
    subject_name: str = ""
    canvas_role: str = ""


def _instance_slug(origin: str, kind: str, sid: int, role: str = "") -> str:
    """确定性 slug：同一个对象永远只会 fork 出这一个 slug，find-or-create 才幂等。"""
    import re
    suffix = re.sub(r"[^a-zA-Z0-9_-]+", "-", role).strip("-")
    return f"{origin}@{kind}-{sid}" + (f"@{suffix}" if suffix else "")


async def _find_instance(origin: str, kind: str, sid: int, role: str = "") -> dict[str, Any] | None:
    row = await get_pool().fetchrow(
        "SELECT slug FROM workflows WHERE origin_slug=$1 AND subject_kind=$2 AND subject_id=$3 AND COALESCE(canvas_role,'')=$4 "
        "ORDER BY version DESC LIMIT 1", origin, kind, sid, role)
    if not row:
        return None
    return await wf.load_workflow(get_pool(), row["slug"])


@router.get("/{slug}/instance")
async def get_instance(slug: str, subject_kind: str, subject_id: int, canvas_role: str = ""):
    """这个对象有没有自己的画布？有就返回它（形状同 GET /{slug}），没有返回 null。

    没有**不是错误**：绝大多数对象只是把模板跑一遍，从不改结构，也就永远没有实例。"""
    return await _find_instance(slug, subject_kind, subject_id, canvas_role)


@router.post("/{slug}/instance")
async def fork_instance(slug: str, body: InstanceIn):
    """从模板 fork 出这个对象的专属画布（已存在就直接返回，幂等）。

    生产态画布上第一次做结构改动时调用：此后该对象的编辑都落进这份副本，
    模板保持干净。图/签名原样照抄模板当时的**最新已发布版**。"""
    import json

    have = await _find_instance(slug, body.subject_kind, body.subject_id, body.canvas_role)
    if have:
        return have
    try:
        tpl = await wf.load_workflow(get_pool(), slug)
    except wf.WorkflowError as e:
        raise HTTPException(404, str(e)) from e
    new_slug = _instance_slug(slug, body.subject_kind, body.subject_id, body.canvas_role)
    # 标签去掉 canvas：那是「编排台画布列表」的筛选位，实例不该出现在那张列表里
    tags = [t for t in (list(tpl.get("tags") or [])) if t != "canvas"] + ["instance"]
    subject = body.subject_name or f"{body.subject_kind}{body.subject_id}"
    name = body.name or f"{tpl['name']} · {subject}"
    await get_pool().execute(
        "INSERT INTO workflows(slug,name,description,version,status,input_schema,"
        "output_schema,graph,seq,tags,origin_slug,subject_kind,subject_id,canvas_role) "
        "VALUES ($1,$2,$3,1,'published',$4::jsonb,$5::jsonb,$6::jsonb,0,$7::text[],$8,$9,$10,$11) "
        "ON CONFLICT (slug,version) DO NOTHING",
        new_slug, name,
        f"由「{tpl['name']}」v{tpl['version']} fork 的专属画布",
        json.dumps(tpl.get("input_schema") or {}, ensure_ascii=False),
        json.dumps(tpl.get("output_schema") or {}, ensure_ascii=False),
        json.dumps(tpl.get("graph") or {}, ensure_ascii=False),
        tags, slug, body.subject_kind, body.subject_id, body.canvas_role or None)
    return await wf.load_workflow(get_pool(), new_slug)


class MountStoreIn(BaseModel):
    project_id: int | None = None
    target: str
    subject: dict[str, Any] | None = None
    url: str
    prompt: str = ""
    variant: str | None = None


@router.post("/{slug}/mount-store")
async def mount_store(slug: str, body: MountStoreIn):
    '''连线即挂载（2026-09-18）：画布上把图连到挂载点时**立即落库**，不等一次运行。
    与挂载点执行体/run 收尾走同一条 apply_mount_binding——project_cover 写
    content_projects.config.cover_url，资产类型码写 workflow_artifacts。
    落库时机从「运行后」提前到「连线后」，是因为用户连的常常是**现有的图**
    （素材/上传/历史产物），为存一张图白跑一遍模型说不通。'''
    if not body.url:
        return {"stored": "skipped", "reason": "no url"}
    if not body.project_id:
        return {"stored": "skipped", "reason": "没有项目上下文"}
    return await tapflow_ai.apply_mount_binding(
        get_pool(), project_id=body.project_id,
        outputs={"url": body.url, "prompt": body.prompt},
        target=body.target, subject=body.subject, variant=body.variant)


# 在飞的异步运行（run_id → task）。仅作并发闸门与强引用（防协程被 GC），
# 真实状态在 workflow_runs 表里——重启后由 wf.reconcile_runs 收尸，不依赖本内存表。
_ASYNC_RUNS: dict[int, asyncio.Task] = {}
_ASYNC_LIMIT = 10


@router.post("/{slug}/run")
async def run_workflow(slug: str, body: RunIn):
    """统一生成接口：带参数（slug + inputs + force）跑一个工作流。
    mode=sync 同步返回 outputs；mode=async 立返 run_id 供画布轮询。"""
    pool = get_pool()
    force = frozenset(body.force or [])
    if body.mode == "async":
        if len(_ASYNC_RUNS) >= _ASYNC_LIMIT:
            raise HTTPException(429, f"并发运行已达上限 {_ASYNC_LIMIT}，稍后再试")
        try:
            run_id = await wf.start_run(
                pool, slug=slug, version=body.version, project_id=body.project_id,
                node_id=body.node_id, inputs=body.inputs, options=body.run_options())
        except wf.WorkflowError as e:
            raise HTTPException(400, str(e)) from e

        async def _bg() -> None:
            try:
                # run_workflow 内部已把异常落到 run 行（status='failed' + error）
                await wf.run_workflow(
                    pool, slug=slug, version=body.version, project_id=body.project_id,
                    node_id=body.node_id, inputs=body.inputs, run_id=run_id, force=force,
                    overrides=body.node_overrides, stop_after=body.stop_after)
            except Exception:
                pass
            finally:
                _ASYNC_RUNS.pop(run_id, None)

        _ASYNC_RUNS[run_id] = asyncio.create_task(_bg())
        return {"ok": True, "run_id": run_id}
    try:
        out = await wf.run_workflow(
            get_pool(), slug=slug, version=body.version, project_id=body.project_id,
            node_id=body.node_id, inputs=body.inputs, force=force,
            overrides=body.node_overrides, stop_after=body.stop_after,
            options=body.run_options())
        return {"ok": True, "outputs": out}
    except wf.WorkflowError as e:
        raise HTTPException(400, str(e)) from e


class QcRewriteIn(BaseModel):
    """手动重写：生成条里的**当前全文** + 质检原因 + 关联要素 → 修订版提示词。

    刻意不复用自动重试那条路（质检技能自己返回的「重构提示词」）——判据一严就会
    「判不过又给不出可用重写」，实测轮轮 0 分。这条是独立的一次模型调用。"""
    # 输入框里的内容（用户可能已经手改过，要尊重他改的那份）
    prompt: str
    # 质检给出的问题清单
    issues: list[str] = []
    # 关联要素：重写要知道这张图画的是什么
    element_id: int | None = None
    project_id: int | None = None
    extra: str = ""
    # 复判用：给了技能就重写后再判一次，把新分数带回画布；不给就只重写
    skill: str = ""
    threshold: int = 0


@router.post("/qc/rewrite")
async def qc_rewrite(body: QcRewriteIn):
    """质检未通过后的「重新生成」：重写 → （给了技能就）复判一次。"""
    from ..services import prompt_rewrite
    pool = get_pool()
    if not body.prompt.strip():
        raise HTTPException(400, "提示词为空，没有可重写的内容")
    try:
        prompt = await prompt_rewrite.rewrite_by_issues(
            pool, prompt=body.prompt, issues=body.issues,
            element_id=body.element_id, extra=body.extra)
        qc: dict[str, Any] = {}
        if body.skill:
            # 复判走**唯一那份判据**（storyboard.review_by_skill，与引擎自动质检同一个），
            # 只是这次判的是重写后的全文
            from ..services.storyboard import review_by_skill
            rv = await review_by_skill(pool, body.project_id, skill=body.skill, text=prompt)
            score = int(rv.get("得分") or 0)
            qc = {
                "passed": bool(rv.get("合格")) and score >= body.threshold,
                "score": score,
                "issues": [str(x) for x in (rv.get("问题") or [])],
                "rounds": 1,
            }
    except HTTPException:
        raise
    except Exception as e:  # 模型/质检侧的可预期失败，如实回给画布
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "prompt": prompt, "qc": qc}


@router.post("/{slug}/preview")
async def preview_workflow(slug: str, body: RunIn):
    """运行预检（零副作用）：画布运行态打开时回显已有产物/预填内容。
    只读 action 真执行、写库 action 走 config.preview 替身、task/subflow 只探 skip_if。"""
    try:
        nodes = await wf.preview_workflow(
            get_pool(), slug=slug, version=body.version, inputs=body.inputs)
        return {"ok": True, "nodes": nodes}
    except wf.WorkflowError as e:
        raise HTTPException(400, str(e)) from e


class SmartPlanIn(BaseModel):
    version: int | None = None
    project_id: int | None = None
    inputs: dict[str, Any] = {}
    """炸开的生成条里输入的那句话。"""
    prompt: str = ""


@router.post("/{slug}/smart-plan")
async def smart_plan(slug: str, body: SmartPlanIn):
    """一句提示词 → 这张流程里哪几个节点会重生成（**只规划不执行**）。

    真正运行时引擎会自己再规划一次（唯一实现在 workflow_planner），这个接口是给画布
    「点生成之前先看看要重跑什么」用的，两边同一份函数、同一个结论。"""
    from ..services import workflow_planner
    try:
        return {"ok": True, **await workflow_planner.plan(
            get_pool(), slug=slug, version=body.version, prompt=body.prompt,
            inputs=body.inputs, project_id=body.project_id)}
    except wf.WorkflowError as e:
        raise HTTPException(400, str(e)) from e


class SmartCapabilitiesIn(BaseModel):
    """节点提示词（charter）+ 当前已选能力 → 模型挑补充项，宁缺毋滥。"""
    charter: str = ""
    prompt: str = ""
    skills: list[str] = []
    kb: list[str] = []
    tools: list[str] = []


@router.post("/smart-capabilities")
async def smart_capabilities(body: SmartCapabilitiesIn):
    """专业能力「智能添加」：按节点提示词从已有能力里挑（有就选、没有别硬选）。

    与属性面板同一目录源（skill_packages / kb_folders / tool registry），
    返回的 value 就是引擎认的 slug / folder_id / 工具名，前端拿到直接并进 bind。"""
    try:
        out = await tapflow_ai.smart_capabilities(
            get_pool(), charter=body.charter or body.prompt,
            current={"skills": body.skills, "kb": body.kb, "tools": body.tools})
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"智能添加失败：{e}") from e
    return {"ok": True, **out}


@router.get("/runs/{run_id}/context")
async def run_context(run_id: int):
    """整轮运行的上下文轨迹：逐节点的入参/出参，按真实执行序。

    画布回看与 AI 规划读的是同一份（workflow_runs.context），不另算一遍。"""
    row = await get_pool().fetchrow(
        "SELECT id,status,inputs,outputs,context FROM workflow_runs WHERE id=$1", run_id)
    if not row:
        raise HTTPException(404, f"run {run_id} 不存在")
    out = dict(row)
    # 连接池没装 jsonb 编解码器，jsonb 列回来是字符串。别的接口保持原样（前端已按
    # 字符串处理），但轨迹这一列的消费方是「喂给模型的历史对话」，解一次省得每个
    # 调用方各自 JSON.parse 一遍——那就又是一份重复实现。
    out["context"] = wf._j(out["context"]) if out["context"] else []
    return out


@router.get("/{slug}/runs/last")
async def last_run(slug: str):
    """这条编排最近一次运行的入参与执行选项——画布打开时回填，免得每次重选项目/场景。

    口径（2026-08-01 定）：
    - 按 **slug** 取全局最近一次，不分版本、不分项目：项目本身就是要回填的入参之一，
      按项目分组反而回填不出项目。
    - **失败的也算**：跑挂了回来多半就是改一改重跑，那时候最需要预填。
    - 只看顶层运行（parent_run_id IS NULL）：子工作流的 inputs 是子图的签名，
      不是画布开始节点填的那份，回填过去全是错位。
    """
    row = await get_pool().fetchrow(
        "SELECT r.id,r.status,r.inputs,r.run_options,r.project_id,r.node_id,r.created_at "
        "FROM workflow_runs r JOIN workflows w ON w.id=r.workflow_id "
        "WHERE w.slug=$1 AND r.parent_run_id IS NULL ORDER BY r.id DESC LIMIT 1", slug)
    # 没跑过不是错误：画布照常打开，只是没得回填
    return dict(row) if row else None


@router.get("/artifacts/{attachment_id}/source")
async def artifact_source(attachment_id: int):
    """Resolve the production canvas/node that created an asset without mutating canvases."""
    row = await get_pool().fetchrow(
        "SELECT a.target_kind,a.target_id,a.role,a.url,p.workflow_id,p.workflow_run_id,"
        "p.workflow_node_run_id,p.node_key,p.iteration,p.operation,w.slug,w.version,w.origin_slug "
        "FROM workflow_artifacts a JOIN workflow_artifact_provenance p ON p.artifact_id=a.id "
        "JOIN workflows w ON w.id=p.workflow_id WHERE a.attachment_id=$1 "
        "ORDER BY p.id DESC LIMIT 1", attachment_id)
    return dict(row) if row else None


@router.get("/{slug}/nodes/latest")
async def latest_node_outputs(slug: str, version: int | None = None):
    """每个节点最近一次落定的产物，供画布重开时恢复。

    不能只读“最近一次 run”：用户可能先单独生成图片 A，再单独生成文本 B；后一轮
    根本不含 A。按 node_key 各取最后一条，才能把分支画布完整拼回来。"""
    rows = await get_pool().fetch(
        "SELECT DISTINCT ON (nr.node_key) nr.node_key,nr.iteration,nr.status,nr.task_id,"
        "nr.subrun_id,nr.skip_reason,nr.error,nr.outputs,nr.created_at,nr.finished_at "
        "FROM workflow_node_runs nr "
        "JOIN workflow_runs r ON r.id=nr.run_id "
        "JOIN workflows w ON w.id=r.workflow_id "
        "WHERE w.slug=$1 AND ($2::int IS NULL OR w.version=$2) "
        "AND nr.status IN ('done','skipped','failed') "
        "ORDER BY nr.node_key,nr.id DESC", slug, version)
    return [dict(r) for r in rows]


@router.get("/runs/recent")
async def recent_runs(project_id: int | None = None, limit: int = 30):
    """运行记录（画布上回放用）。"""
    rows = await get_pool().fetch(
        "SELECT r.id,r.status,r.depth,r.created_at,r.finished_at,r.error,"
        "w.slug,w.name,w.version FROM workflow_runs r JOIN workflows w ON w.id=r.workflow_id "
        "WHERE ($1::bigint IS NULL OR r.project_id=$1) ORDER BY r.id DESC LIMIT $2",
        project_id, min(limit, 100))
    return [dict(r) for r in rows]


@router.get("/runs/{run_id}")
async def get_run(run_id: int):
    """run 本体：整体状态 + outputs + error（画布轮询的终态判据）。"""
    row = await get_pool().fetchrow(
        "SELECT r.id,r.status,r.inputs,r.outputs,r.error,r.created_at,r.finished_at,"
        "w.slug,w.name,w.version FROM workflow_runs r "
        "JOIN workflows w ON w.id=r.workflow_id WHERE r.id=$1", run_id)
    if not row:
        raise HTTPException(404, f"run {run_id} 不存在")
    return dict(row)


@router.get("/runs/{run_id}/nodes")
async def run_nodes(run_id: int):
    """节点级明细：哪个节点跑了、跳过没有、为什么跳过、错在哪。"""
    rows = await get_pool().fetch(
        "SELECT node_key,iteration,status,task_id,subrun_id,skip_reason,error,"
        "inputs,outputs,created_at,finished_at FROM workflow_node_runs "
        "WHERE run_id=$1 ORDER BY id", run_id)
    return [dict(r) for r in rows]
