"""Tapflow 智能化（2026-09-17 新增，纯增量）——三件事，全部零写死：

1. **智能添加**：节点「专业能力」不再全靠人勾——把节点提示词与候选清单
   （技能=方法论 / 知识库=事实库 / 工具=取数器）交给文本模型挑，
   有合适的才选、没有就返回空（宁缺毋滥，绝不硬选）。
2. **上下文自主规划**：gen 节点配 `autoContext` 后，写提示词的智能体默认带上
   全部只读工具 + 画布上游 ctx 探索（ctx.*），查什么、查多深由模型按提示词自己定
   ——所以"根据项目基本信息和画风生成封面"不用人工勾 project_info。
3. **产出存储分发**：end 节点声明 `store.target` 时按绑定落库（如封面画布的产物
   直接进 config.cover_url）；没绑定但开了 `aiStore`，则由模型从白名单动作里规划
   存哪。绑定优先，规划兜底，都没配就只把产物留在 run outputs（现状行为）。

纪律：存储动作是**白名单**，模型只能挑不能发明；全部动作幂等（重复执行=覆盖同字段）。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import asyncpg

from .. import llm
from .mount_targets import MountTarget, get_target

log = logging.getLogger("tapflow.ai")


class TapflowAIError(RuntimeError):
    pass


# ── 工具目录 ──────────────────────────────────────────────────────────────

def readonly_tool_names() -> list[str]:
    """全部只读工具名（writes=False）：autoContext 智能体的默认武器库。
    写类工具不给——写提示词的智能体误调写工具的代价远大于少查一条数据。"""
    from . import tools as tool_registry
    return sorted(s["name"] for s in tool_registry.specs() if not s.get("writes"))


# ── 1. 智能添加：AI 从候选里挑专业能力 ────────────────────────────────────

SELECT_SYSTEM = """你是画布节点的配置助手。用户写好了节点的提示词（描述这个节点要产出什么、
依据什么），你要从候选清单里挑出**真正有助于这个节点**的专业能力。

三类候选的区别：
- skill（技能）：方法论/操作规程文档，教模型"怎么做"；
- kb（知识库文件夹）：事实库，给画面/文案提供设定依据；
- tool（工具）：运行时取数/写库的函数。

纪律：
1. 只挑与提示词**直接相关**的：提示词说要项目信息/画风，就挑能取到它们的工具；
   要画技法，就挑对应技能与知识库。
2. **宁缺毋滥**：没有合适的就返回空数组，绝不为了凑数硬选。拿不准=不选。
3. 工具标注 [写] 的会改库，除非节点职责就是写数据，否则不要挑。
4. 每类最多挑 3 个，按相关度排序。

只输出 JSON，不要解释、不要代码块围栏：
{"skills": ["slug"], "kb": ["folder_id字符串"], "tools": ["工具名"], "reason": "一句话理由"}"""


async def smart_capabilities(pool: asyncpg.Pool, *, charter: str,
                             current: dict[str, list[str]] | None = None,
                             ) -> dict[str, Any]:
    """按节点提示词挑选专业能力。返回 {skills, kb, tools, reason}。

    模型不可用/答非所问 → 全空 + reason 说明（前端展示「没有合适的能力」），
    绝不往已有配置里塞东西——这个按钮坏掉的形态必须是「没加」，而不是「加错」。"""
    current = current or {}
    skills = await pool.fetch(
        "SELECT slug, name, coalesce(description,'') AS description FROM skill_packages "
        "WHERE status='installed' ORDER BY slug")
    folders = await pool.fetch(
        "SELECT id, title FROM kb_folders ORDER BY seq, id")
    from . import tools as tool_registry
    tools = tool_registry.specs()

    def lines(rows, fmt):
        return "\n".join(fmt(r) for r in rows[:60]) or "（无）"

    user = (
        f"## 节点提示词\n{charter.strip() or '（空——请返回空清单）'}\n\n"
        "## 已选能力（无需重复推荐）\n"
        f"skills={current.get('skills') or []} kb={current.get('kb') or []} "
        f"tools={current.get('tools') or []}\n\n"
        "## 候选：技能 skill（value=slug）\n"
        + lines(skills, lambda r: f"- {r['slug']} | {r['name']} | {r['description'][:80]}") + "\n\n"
        "## 候选知识库 kb（value=folder id 字符串）\n"
        + lines(folders, lambda r: f"- {r['id']} | {r['title']}") + "\n\n"
        "## 候选工具 tool（value=name，[写]=会改库）\n"
        + lines(tools, lambda s: f"- {s['name']} | {s.get('title') or s['name']}"
                f" | {str(s.get('description') or '')[:80]}"
                f"{' [写]' if s.get('writes') else ''}"))
    try:
        got = await llm.chat_json(SELECT_SYSTEM, user, temperature=0.2,
                                  max_tokens=800, purpose="tapflow.smart_capabilities")
    except Exception as e:  # noqa: BLE001 — 模型挂了=没加任何东西，而不是配置被破坏
        log.warning("智能添加模型调用失败：%s", e)
        return {"skills": [], "kb": [], "tools": [], "reason": f"模型不可用：{e}"}
    if not isinstance(got, dict):
        return {"skills": [], "kb": [], "tools": [], "reason": "模型返回格式异常"}

    valid_s = {r["slug"] for r in skills}
    valid_k = {str(r["id"]) for r in folders}
    valid_t = {s["name"] for s in tools}

    def pick(v, valid):
        return [x for x in (v or []) if isinstance(x, str) and x in valid] if isinstance(v, list) else []

    out = {
        "skills": pick(got.get("skills"), valid_s),
        "kb": pick(got.get("kb"), valid_k),
        "tools": pick(got.get("tools"), valid_t),
        "reason": str(got.get("reason") or ""),
    }
    log.info("智能添加：%s（charter %d 字）", out, len(charter or ""))
    return out


# ── 3. 产出存储分发（绑定优先，AI 规划兜底）──────────────────────────────

STORE_PLAN_SYSTEM = """你是生成产物的入库规划员。一次画布运行结束，给你各节点的产出与项目上下文，
你要决定这些产物**存到哪里**。只能从白名单动作里选，不能发明动作：

- save_project_cover：产物是一张适合做项目封面的海报/主视觉图 → 存为项目封面
- none：产物是中间素材/与项目无关/不适合落任何位置 → 不落库

只输出 JSON：{"action": "save_project_cover|none", "url": "要存的图片URL，没有就空串",
"reason": "一句话理由"}"""


def _pick_url(outputs: dict[str, Any]) -> str:
    """从 end outputs 里找图片产物 url：约定键优先，其次任何以 http 开头的短字符串值。"""
    for k in ("url", "image_url", "cover_url", "output", "image"):
        v = outputs.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v
    for v in outputs.values():
        if isinstance(v, str) and v.startswith("http") and len(v) < 500:
            return v
    return ""


async def _save_project_field(pool: asyncpg.Pool, project_id: int, target: MountTarget,
                              url: str, prompt: str = "") -> dict[str, Any]:
    """project_field 形态的落库：写 content_projects.config 的归宿字段（幂等，重复执行=覆盖同字段）。
    封面字段顺带把提示词落 config.cover_prompt（与项目页 generate_cover 同一落点）。"""
    cfg = await pool.fetchval("SELECT config FROM content_projects WHERE id=$1", project_id)
    conf = json.loads(cfg) if isinstance(cfg, str) else dict(cfg or {})
    if conf.get(target.field) == url:
        return {"stored": target.code, "url": url, "unchanged": True}
    conf[target.field] = url
    if prompt.strip() and target.field == "cover_url":
        conf["cover_prompt"] = prompt.strip()
    await pool.execute("UPDATE content_projects SET config=$1::jsonb, updated_at=now() "
                       "WHERE id=$2", json.dumps(conf, ensure_ascii=False), project_id)
    return {"stored": target.code, "url": url}


async def apply_end_binding(pool: asyncpg.Pool, *, project_id: int,
                            outputs: dict[str, Any],
                            binding: dict[str, Any] | None = None,
                            auto_store: bool = False) -> dict[str, Any]:
    """end 节点产物落库。绑定优先（人声明了 target 就照办）；
    没绑定且 auto_store 开启时由模型规划；返回 {"stored": target|none|skipped, ...}。
    任何失败只记日志不抛——存储失败不该把一次成功的生成判成 failed。"""
    try:
        if isinstance(binding, dict) and binding.get("target"):
            # 旧 end.store 绑定与挂载点走**同一条注册表分派**（2026-09-18）：
            # 历史 end 只声明过 project_cover，如今资产码绑定同样能落——不再 unknown target
            return await apply_mount_binding(
                pool, project_id=project_id, outputs=outputs,
                target=str(binding["target"]),
                variant=(str(binding["variant"]) if binding.get("variant") else None))

        if not auto_store:
            return {"stored": "skipped", "reason": "no binding"}
        url = _pick_url(outputs)
        if not url:
            return {"stored": "skipped", "reason": "no url"}
        got = await llm.chat_json(
            STORE_PLAN_SYSTEM,
            f"## 节点产物\n{json.dumps(outputs, ensure_ascii=False)[:2000]}\n\n"
            f"## 产物候选 URL\n{url}",
            temperature=0.1, max_tokens=200, purpose="tapflow.store_plan")
        action = str((got or {}).get("action") or "none")
        if action == "save_project_cover":
            return await _save_project_field(
                pool, project_id, get_target("project_cover"),
                str((got or {}).get("url") or url),
                str(outputs.get("prompt") or ""))
        return {"stored": "none", "reason": str((got or {}).get("reason") or "")}
    except Exception as e:  # noqa: BLE001 — 存储失败不影响运行成功
        log.warning("产物存储分发失败（project %s）：%s", project_id, e)
        return {"stored": "skipped", "reason": str(e)}


async def apply_mount_binding(pool: asyncpg.Pool, *, project_id: int,
                              outputs: dict[str, Any], target: str,
                              subject: dict[str, Any] | None = None,
                              variant: str | None = None) -> dict[str, Any]:
    """挂载点落库（2026-09-17 通用标准方案；2026-09-18 收敛到归宿注册表）：
    画布上的独立挂载节点声明产物归宿，连到它的产物就落进该归宿。
    归宿与存储形态统一注册在 mount_targets，这里只按表分派，不写任何码特判：

    - ``project_field`` 形态（project_cover / project_trailer…）：写
      content_projects.config 的对应字段；
    - ``asset`` 形态（pro.character.sheet / pro.scene.sheet / com.image …）：写
      workflow_artifacts，与生成节点自带的节点级落库同一张表、同一套语义
      （asset_type + subject_kind/subject_id + variant + version 自增）。

    subject 缺省时不报错，只跳过——业务对象没绑（比如通用画布直接点了发送）
    不该把一次成功的生成判成失败。"""
    try:
        url = _pick_url(outputs)
        if not url:
            return {"stored": "skipped", "reason": "no url"}
        tgt = str(target or "").strip()
        if not tgt or tgt == "auto":
            return {"stored": "skipped", "reason": "挂载点未声明归宿"}
        mt = get_target(tgt)
        if mt is None:
            return {"stored": "skipped", "reason": f"unknown target {tgt}"}
        if mt.kind == "project_field":
            return await _save_project_field(pool, project_id, mt, url,
                                             str(outputs.get("prompt") or ""))
        from ..assets import get as get_asset_type
        contract = get_asset_type(mt.code)   # 注册表由资产合同生成，必然命中
        sk: str | None = None
        sid: int | None = None
        if contract.subject_kind != "none":
            raw = subject or {}
            kind, ident = raw.get("kind"), raw.get("id")
            if not kind or not ident:
                return {"stored": "skipped", "reason": f"{tgt} 需要绑定业务对象"}
            if str(kind) != contract.subject_kind:
                return {"stored": "skipped",
                        "reason": f"{tgt} 需要 {contract.subject_kind}，收到 {kind}"}
            sk, sid = str(kind), int(ident)
        attachment_id = await pool.fetchval(
            "SELECT id FROM content_attachments WHERE project_id=$1 AND url=$2 ORDER BY id DESC LIMIT 1",
            project_id, url)
        # 通用素材没有业务对象（subject_kind=none），沿用「附件自身当 target」的旧约定
        tk = sk or "attachment"
        tid = int(sid) if sid else int(attachment_id or 0)
        if not tid:
            return {"stored": "skipped", "reason": "产物未进附件库且无业务对象"}
        # 幂等：同一个产物反复跑（比如整图重跑但上游没变）不该刷出一堆同 url 的版本——
        # 挂载点语义是「这个归宿现在指向哪张」，不是每次运行都记一笔流水
        prev = await pool.fetchrow(
            "SELECT url, version FROM workflow_artifacts WHERE project_id=$1 "
            "AND asset_type IS NOT DISTINCT FROM $2 AND subject_kind IS NOT DISTINCT FROM $3 "
            "AND subject_id IS NOT DISTINCT FROM $4 AND variant IS NOT DISTINCT FROM $5 "
            "ORDER BY id DESC LIMIT 1",
            project_id, tgt, sk, sid, variant)
        if prev and prev["url"] == url:
            return {"stored": tgt, "url": url, "version": int(prev["version"]),
                    "unchanged": True}
        version = await pool.fetchval(
            "SELECT COALESCE(MAX(version),0)+1 FROM workflow_artifacts "
            "WHERE project_id=$1 AND asset_type IS NOT DISTINCT FROM $2 "
            "AND subject_kind IS NOT DISTINCT FROM $3 AND subject_id IS NOT DISTINCT FROM $4 "
            "AND variant IS NOT DISTINCT FROM $5",
            project_id, tgt, sk, sid, variant)
        artifact_id = await pool.fetchval(
            "INSERT INTO workflow_artifacts(project_id,attachment_id,target_kind,target_id,role,"
            "variant,url,asset_type,subject_kind,subject_id,version) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id",
            project_id, attachment_id, tk, tid, "primary", variant, url, tgt, sk, sid, version)
        return {"stored": tgt, "url": url, "version": int(version),
                "artifact_id": artifact_id}
    except Exception as e:  # noqa: BLE001 — 存储失败不影响运行成功
        log.warning("挂载点落库失败（project %s target %s）：%s", project_id, target, e)
        return {"stored": "skipped", "reason": str(e)}
