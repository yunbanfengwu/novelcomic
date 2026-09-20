"""编排面板的目录与上下文 API。

只剩两件事，都是**取数**，不执行任何东西：
1. 资产库清单——tapflow 属性面板的技能/知识库/工具多选从这里取（唯一目录源）；
2. 运行上下文——项目 + 卷/章/镜 + 要素，画布入参下拉与运行面板都用它。

执行入口只有一个：`POST /api/workflows/{slug}/run`（工作流解释器）。
2026-08-01 删除「智能体编排」（agent_unit/autoflow）后，本模块不再有执行类端点。
"""
from typing import Any

from fastapi import APIRouter

from ..db import get_pool
from ..services import agent_batch, capabilities, tools as tool_registry

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("/capabilities")
async def list_capabilities() -> dict[str, Any]:
    """能力目录：工具与 tapflow 抹平成同一种条目（见 services/capabilities 模块头）。

    这就是规划节点看到的那一份，不是给人另做的镜像——页面上读起来含糊的描述，
    模型选能力时一样含糊。
    """
    return {"capabilities": await capabilities.entries(get_pool())}


@router.get("/assets")
async def list_assets() -> dict[str, Any]:
    """属性面板的候选项，一次取齐（面板要同时渲染三个多选，分三次请求没必要）。"""
    pool = get_pool()
    skills = await pool.fetch(
        "SELECT slug,name,description,version FROM skill_packages "
        "WHERE status='installed' ORDER BY name")
    folders = await pool.fetch(
        "SELECT f.id,f.name,f.title,f.kind,f.category,f.system,"
        "  (SELECT count(*) FROM kb_entries e WHERE e.enabled AND ("
        "     CASE WHEN f.system THEN e.kind=f.kind AND (f.category IS NULL"
        "            OR e.category=f.category)"
        "          ELSE e.folder_id=f.id END)) AS entry_count "
        "FROM kb_folders f ORDER BY f.seq, f.id")
    # 质检技能**不是** skill_packages：引擎按「kb 条目名」找规则正文
    # （storyboard._reviewer_system：kind='skill' AND agent_code='reviewer'）。
    # 拿 skill_packages 的 slug 去填这个下拉，就是又一个永远匹配不上的假目录。
    qc_skills = await pool.fetch(
        "SELECT DISTINCT name, max(description) AS description FROM kb_entries "
        "WHERE kind='skill' AND agent_code='reviewer' AND enabled GROUP BY name ORDER BY name")
    return {
        "skills": [dict(r) for r in skills],
        "folders": [dict(r) for r in folders],
        "tools": tool_registry.specs(),
        "qc_skills": [dict(r) for r in qc_skills],
        "steps": _step_specs(),
        "batch_sources": agent_batch.specs(),
    }


def _step_specs() -> list[dict[str, Any]]:
    """生成步骤（执行体）目录：gen 节点的 `config.step` 只能是这里面的 kind。

    来源是 flow.STEPS 注册表本身——**不维护第二份清单**。落库/附件/回写焊在各
    Step 的 next 里（2026-08-01 定稿：执行体保留固定），所以画布能做的是
    「从已注册的里挑一个」，不是自己拼一个。"""
    from ..services import flow, steps as _steps  # noqa: F401 — import 触发 @register
    return [
        {"kind": k, "group": s.group or "其它", "note": s.run_note,
         "manual": s.manual}
        for k, s in sorted(flow.STEPS.items(), key=lambda kv: (kv[1].group or "", kv[0]))
    ]


@router.get("/context")
async def list_context(project_id: int | None = None) -> dict[str, Any]:
    """运行上下文候选：不传 project_id 给项目清单；传了给卷/章/镜 + 要素。

    要素这一份是「单个角色生成 / 单个场景生成」用的——卷章镜在 content_nodes，
    角色场景在 content_elements，两张表都要给，否则单个对象根本指不到。
    """
    pool = get_pool()
    if project_id is None:
        rows = await pool.fetch(
            "SELECT id,title FROM content_projects ORDER BY id DESC LIMIT 200")
        return {"projects": [dict(r) for r in rows]}
    nodes = await pool.fetch(
        "SELECT id,parent_id,kind,seq,title FROM content_nodes "
        "WHERE project_id=$1 AND deleted_at IS NULL ORDER BY kind,seq,id", project_id)
    elements = await pool.fetch(
        "SELECT id,kind,name,(meta->>'sheet_url') IS NOT NULL AS has_sheet "
        "FROM content_elements WHERE project_id=$1 ORDER BY kind,name", project_id)
    return {"project_id": project_id, "nodes": [dict(r) for r in nodes],
            "elements": [dict(r) for r in elements]}
