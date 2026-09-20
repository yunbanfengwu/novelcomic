"""生成链：草稿→基本信息（评估文风/画风）→目录（带故事线流水账）→核心要素（含出现索引预填）。"""
import json
import re
from typing import Any

import asyncpg

from .. import llm
from ..knowledge import project_preferences
from . import volumes

# ═══════════ 1. 草稿 → 基本信息 ═══════════

_PROJECT_INFO_SYS = """你是资深小说策划编辑 + 视觉总监。用户给你一段小说草稿/构思，你要产出项目基本信息。
【事实边界】只能提炼用户草稿中明确存在的人物、地点、势力、道具、事件和关系；禁止新增命名角色、反派、组织、世界规则、历史事件或结局。信息不足时保持概括，不得用常见类型片套路补齐剧情。
严格输出 JSON（不要多余文字）：
{
  "title": "书名（吸引人，8字内）",
  "synopsis": "故事梗概（150-300字：主角、核心冲突、世界观钩子）",
  "writing_style": "文风评估与指令（50-100字：判断草稿最适合的文风流派并给出可执行的写作风格指令，如'莫言式乡土魔幻，长句铺排，感官轰炸'）",
  "art_style": "画风评估（30-60字：判断改编漫剧最适合的画风，如'日漫赛璐璐/国漫水墨/美漫厚涂/电影感写实'之一并说明理由）",
  "storyline": "主线故事线（100-200字：起点→关键转折→终局的一句话主线 + 2-4个卷级走向）",
  "genre": "题材标签（如 玄幻/悬疑/都市/科幻）",
  "suggested_chapters": 建议章节数(整数)
}"""


_PROJECT_INFO_PROMO_SYS = """你是资深品牌短视频企划总监 + 视觉总监。用户给你一段品牌宣传需求/构思，你要产出项目基本信息。
【事实边界】只能围绕用户草稿中明确给出的产品、卖点、周期与调性做企划；不得虚构产品没有的功能卖点。
严格输出 JSON（不要多余文字）：
{
  "title": "企划名（品牌/产品 + 传播主题，10字内）",
  "synopsis": "企划概述（150-300字：产品、核心卖点方向、目标人群、整体调性与传播目标）",
  "writing_style": "短视频文案语言风格指令（50-100字：口吻、句式、每集结尾记忆点设计）",
  "art_style": "画面风格评估（30-60字：如'食欲感暖调/高级感极简/科技感冷调'之一并说明理由）",
  "storyline": "节奏主线（100-200字：按天/阶段的传播节奏安排，如预热期→爆发期→延续期，不写连续剧情）",
  "genre": "宣传类型标签（如 品牌广告/商品广告/地理宣传）",
  "suggested_chapters": 建议集数(整数，30天每日一播=30)
}"""


async def gen_project_info(
    draft: str,
    project_type: str = "novel_comic",
    material_context: str = "",
) -> dict[str, Any]:
    sys_prompt = _PROJECT_INFO_PROMO_SYS if _is_promo_type(project_type) else _PROJECT_INFO_SYS
    material_block = ""
    if material_context.strip():
        material_block = (
            "\n\n参考资料（来自分段读取摘要；只能提取其中明确事实，不能擅自补写）：\n"
            + material_context[:12000]
        )
    return await llm.chat_json(sys_prompt, f"草稿如下：\n\n{draft[:6000]}{material_block}")


# ═══════════ 1b. 长篇架构大纲（Markdown 全文）═══════════

_OUTLINE_MD_SYS = """你是顶级网文架构师。基于项目信息，产出一份**长篇故事架构大纲**，用于指导整部作品的写作。
【当前阶段：项目开发前期，可进行创意扩展】
- 允许为丰富内容新增配角、势力、阴谋、地点、道具、历史背景和支线，但每项新增都必须直接服务既有主线与核心冲突，具有清晰因果作用。
- 不得替换或削弱已确定的主角、核心关系、核心目标、世界基调和用户明确给出的关键事件；不得让新增角色喧宾夺主。
- 新增内容应具体、原创、与既有设定相容，避免套用“神秘商会/幕后黑手”等空泛模板凑篇幅。
- 对重大新增设定在大纲中标注“新增提案”，说明它解决的剧情需要，供后续确认后进入锁定设定。
- 质检标准不是“原稿未出现即错误”，而是新增内容是否合理、必要、连贯且不偏离项目方向。
- “建议章节数”指全书总章节数，不是每卷章节数；分卷后的章节总和应接近该数值。
- 新增势力和主要配角宁精勿多：若一个势力不能制造独特而不可替代的压力，就合并或删除；不得用多个同质化反派稀释人与龙建立信任的情感主线。
直接输出 **Markdown 全文**（不要代码块包裹、不要任何解释性开场白），结构参考：

# 《书名》长篇架构（X卷×每卷章节数）
——一句话副标题
---
## 【世界观设定】
（核心设定、能量/力量体系、关键道具起源等，分小节 ### 展开）
### 势力分布
用 Markdown 表格列出各方势力/目标/代表角色/暗面
---
## 【主线架构：分卷核心冲突】
### 第一卷：卷名
- 地形/场景：
- 核心事件：（分点）
- 伏笔与回收：
（逐卷展开，每卷聚焦一个核心冲突与一条势力线）
---
## 【关键串联设计】
（跨卷伏笔机制、角色暗线回收、冲突升级路径，可含 > 引用金句）
---
## 【角色深度设计】
（主要角色的表面/真相/结局反转）

要求：
- 合理利用 Markdown 语法：# ## ### 标题、- 列表、| | 表格、> 引用、**加粗**、--- 分隔线
- 卷数与每卷章节数依据题材与建议章节数合理推算（如 200 章→约 5-8 卷）
- 首尾因果闭环，卷与卷之间冲突层层升级，伏笔均匀铺设并回收
- 篇幅充实（2000-4000 字），但不要空话套话，每一条都要具体可落地"""


_OUTLINE_MD_PROMO_SYS = """你是顶级品牌短视频内容架构师。基于项目信息，产出一份**品牌宣传短视频企划架构大纲**，用于指导逐集创作。
【当前阶段：企划开发前期，可进行创意扩展】
- 每一集围绕一个产品功能/卖点展开，单集独立成篇；不要求集与集之间剧情连贯，严禁使用“伏笔/回收/承上集”等连续剧结构。
- 单集结构：场景设定 → 微型故事 → 卖点演示 → 结尾品牌记忆点。
- 卖点呈现必须具体可拍（可视化演示、前后对比、使用瞬间），不得空喊口号。
直接输出 **Markdown 全文**（不要代码块包裹、不要解释性开场白），结构：

# 《企划名》品牌宣传短视频架构（共N集 × 每集约30-60秒）
——一句话定位
---
## 【产品与卖点总览】
（产品定位一句话；核心卖点表格：| 卖点 | 一句话说明 | 可视化演示方式 |）
---
## 【排期总览】
（按天/阶段排期表格：| 阶段 | 天数 | 主题 | 传播目标 |；总天数须等于建议集数）
---
## 【分集创意】
### 第1集：《单集标题》（功能卖点：xxx）
- 场景：
- 故事：
- 卖点呈现：
- 结尾记忆点：
（逐集列出到建议集数；每集场景与故事彼此独立）
---
## 【视觉与传播设计】
（画面风格、统一包装元素、结尾品牌记忆点规范、每集传播钩子）

要求：
- 合理利用 Markdown 语法：# ## ### 标题、- 列表、| | 表格、--- 分隔线
- 分集创意覆盖全部建议集数，功能卖点不重复、场景不重样
- 篇幅充实（2000-4000 字），每一条具体可落地，不写空话套话"""


def _outline_md_user(project: dict[str, Any] | asyncpg.Record) -> str:
    cfg = project["config"] if isinstance(project["config"], dict) else json.loads(project["config"] or "{}")
    draft_text = (project.get("draft_text") if isinstance(project, dict) else project["draft_text"]) or ""
    material_context = (project.get("_material_context") if isinstance(project, dict) else "") or ""
    material_block = ("\n\n�ο�����ժҪ���ɷֶζ�ȡ���������Դ���ݣ���\n" + material_context[:18000]) if material_context.strip() else ""
    if _is_promo(project):
        return (
            f"企划名：{project['title']}\n宣传类型：{cfg.get('genre', '')}\n"
            f"建议集数：{cfg.get('suggested_chapters', '')}\n"
            f"企划概述：{project['synopsis']}\n文案风格：{project['writing_style']}\n"
            f"节奏主线：{project['storyline']}\n"
            f"原始需求（不可偏离项）：\n{draft_text}{material_block}\n\n"
            "请围绕产品功能逐集展开企划架构；每集独立成篇，卖点与场景不重复。"
        )
    return (
        f"书名：{project['title']}\n题材：{cfg.get('genre', '')}\n"
        f"建议章节数：{cfg.get('suggested_chapters', '')}\n"
        f"梗概：{project['synopsis']}\n文风：{project['writing_style']}\n"
        f"主线故事线：{project['storyline']}\n"
        f"原始草稿（核心设定基线）：\n{draft_text}{material_block}\n\n"
        "请在不偏离核心设定的前提下合理扩展；重大新增内容标注“新增提案”及其剧情作用。"
    )


def clean_outline_md(md: str) -> str:
    """模型偶将换行输出成字面量 \\n（Markdown 无法断行）→ 规整为真实换行；去掉误加的代码块围栏。"""
    md = md.strip().replace("\\n", "\n").strip()
    if md.startswith("```"):
        md = md.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return md


async def archive_outline_version(
    pool: asyncpg.Pool,
    project_id: int,
    old_markdown: str | None,
    *,
    task_id: int | None = None,
    reason: str = "regenerate",
) -> int | None:
    """替换大纲前把旧稿保存为项目资料；相同内容只归档一次。"""
    old = (old_markdown or "").strip()
    if not old:
        return None
    row = await pool.fetchrow(
        "INSERT INTO project_materials(project_id,title,source,content,meta) "
        "SELECT $1,$2,'generated_version',$3,$4::jsonb "
        "WHERE NOT EXISTS ("
        " SELECT 1 FROM project_materials WHERE project_id=$1 AND content=$3 "
        " AND meta->>'type'='outline_version'"
        ") RETURNING id",
        project_id,
        f"项目大纲历史版本{f'·任务{task_id}' if task_id else ''}",
        old,
        json.dumps({
            "type": "outline_version",
            "task_id": task_id,
            "reason": reason,
        }, ensure_ascii=False),
    )
    return row["id"] if row else None


async def _review_outline_promo(
    project: dict[str, Any] | asyncpg.Record, md: str,
) -> dict[str, Any]:
    """宣传企划分版质检：不执行小说向设定裁决/语义复核（它们的规则面向长篇小说）。
    仅做结构完整性检查，未通过时按企划提示词单轮自修复。"""
    revised = clean_outline_md(md)
    issues = outline_integrity_issues_promo(revised)
    if issues:
        revised = clean_outline_md(await llm.chat_text(
            _OUTLINE_MD_PROMO_SYS,
            _outline_md_user(project)
            + "\n\n【上一版未通过结构检查，必须逐项修复后输出完整大纲】\n"
            + "\n".join(f"- {x}" for x in issues),
            temperature=0.05))
        issues = outline_integrity_issues_promo(revised)
    if issues:
        raise ValueError("宣传企划大纲未通过结构检查：" + "；".join(issues))
    return {
        "content_stage": "development",
        "issues": [],
        "accepted_additions": [],
        "rejected_additions": [],
        "setting_assessments": [],
        "decision_summary": "品牌宣传企划分版：结构完整性检查通过；小说向设定裁决与语义复核不适用，已跳过。",
        "integrity_issues": [],
        "policy_issues": [],
        "semantic_review": {
            "passed": True, "unresolved_issues": [], "reasonable_settings": [],
            "settings_requiring_revision": [],
            "summary": "宣传企划分版：跳过小说语义复核",
        },
        "revised_markdown": revised,
    }


async def review_outline_development(
    project: dict[str, Any] | asyncpg.Record, md: str,
) -> dict[str, Any]:
    """项目开发前期质检：允许扩展，但逐项判断既有与新增设定是否合理。"""
    if _is_promo(project):
        return await _review_outline_promo(project, md)
    draft = (project.get("draft_text") if isinstance(project, dict)
             else project["draft_text"]) or ""
    cfg = project["config"] if isinstance(project["config"], dict) else json.loads(project["config"] or "{}")
    system = """你是影视项目开发阶段的内容主编。此时允许大纲新增配角、势力、阴谋、地点、道具、历史和支线，不能因为原稿未出现就判错。
你要判断的是：
1. 新增内容是否直接服务既有主线、人物成长或核心冲突；
2. 是否与原始设定、项目梗概、主角关系和世界基调相容；
3. 是否喧宾夺主、改变核心目标、制造因果矛盾或使用空泛类型片套路凑篇幅；
4. 重大新增是否标注为“新增提案”并说明剧情作用；
5. 整体是否足够丰富、可持续展开。
6. 分卷章节总数是否与建议章节总数一致，不能误写成“每卷都等于全书建议章节数”；
7. 新增人物、势力和阴谋是否彼此有独特功能；同质化的商会、教团、幕后黑手应合并，家族秘史或身世反转若不服务主角成长则删除。
8. 必须审查“之前已经写进待审大纲的设定”是否合理，不能因为它已存在就默认正确；逐项检查年龄、时间、身份、因果和结局是否自洽。
9. 对约30章的项目，原则上最多保留1个新增主要对立势力、1至2名新增重要配角；更多内容只有在功能不可合并时才保留。
10. 不得给每个主角机械套用“失踪父母、家族传承、隐藏血统、恢复记忆”等同质身世；只保留最能服务核心情感主线的一条。
11. 新增暴力程度必须符合项目基调；若核心是少女与幼龙建立信任，不要无依据升级为暗杀、灭族或黑暗力量。
12. 检查时间年龄矛盾与结果矛盾，例如“幼龙亲历十年前事件”、同一批龙既被写成峡谷遗骸又在结局获救。
13. 原稿已命名角色的职责也是核心基线：除非有充分因果必要，不要把“隐瞒秘密的守塔人”直接改成幕后凶手或最终反派。
14. 不得把“风暴之神”等抽象自然力量列为新势力，除非原始世界观明确存在神祇体系。
15. accepted_additions/rejected_additions 必须覆盖所有新增主要势力、重要配角、核心世界规则与重大身世，不能只挑一部分。
16. 质检对象不只包括本轮新增内容，还包括原始草稿和之前版本已经存在的设定。不得把“之前就这样写了”当作合理性的证据；需要判断该设定是否必要、独特、因果自洽、符合人物年龄身份及项目基调。
17. setting_assessments 必须列出关键既有设定和重大新增设定，逐项给出来源、保留/修订/删除结论与理由。
本轮只做设定裁决，不重写大纲。
严格输出 JSON：
{"issues":["具体内容问题"],"accepted_additions":[{"name":"","reason":""}],
"rejected_additions":[{"name":"","reason":""}],
"setting_assessments":[{"name":"","origin":"原始草稿|既有大纲|新增提案","verdict":"保留|修订|删除","reason":""}],
"decision_summary":"质检结论"}"""
    result = await llm.chat_json(
        system,
        f"项目梗概：\n{project['synopsis'] or ''}\n\n"
        f"项目主线：\n{project['storyline'] or ''}\n\n"
        f"建议全书总章节数：{cfg.get('suggested_chapters') or '未指定'}\n\n"
        f"原始草稿核心设定：\n{draft[:6000]}\n\n待审大纲：\n{md}",
        temperature=0.05, max_tokens=3000, purpose="review")
    accepted, rejected, decision_conflicts = normalize_outline_decisions(
        result.get("accepted_additions"), result.get("rejected_additions"))
    review = {
        "content_stage": "development",
        "issues": [str(x) for x in (result.get("issues") or []) if str(x).strip()],
        "accepted_additions": accepted,
        "rejected_additions": rejected,
        "setting_assessments": normalize_setting_assessments(
            result.get("setting_assessments")),
        "decision_summary": str(result.get("decision_summary") or "").strip(),
    }
    if decision_conflicts:
        review["issues"].append(
            "设定裁决出现接受/拒绝冲突，系统已按“拒绝优先”归一："
            + "、".join(decision_conflicts))
    revision_system = """你是长篇故事架构主编。根据“设定裁决”修订待审大纲，只改不合理项并保留已接受的丰富内容。
硬要求：
1. 输出完整 Markdown，不要 JSON、代码块或解释；
2. 2500-4000 个中文字符，禁止再附逐章流水账；章节目录由后续独立步骤生成；
3. 建议章节数是全书总数，标题写清各卷合计如何接近总数；
4. 顾临保留“隐瞒关键秘密的守塔人”灰度，不无依据改成幕后凶手；
5. 不新增神祇势力；龙群失踪与龙骨遗骸不能互相矛盾，若保留峡谷遗骸必须明确是更古老年代、不是十年前失踪龙群；
6. 幼龙不得被写成十年前事件亲历幸存者，除非明确合理的龙族年龄规则；
7. 不给所有主角叠加失踪亲人、隐藏血统或家族传承；
8. 末尾必须以完整句结束。"""
    revision_user = (
        f"【原始草稿核心设定】\n{draft[:6000]}\n\n"
        f"【项目梗概】\n{project['synopsis'] or ''}\n\n"
        f"【项目主线】\n{project['storyline'] or ''}\n\n"
        f"【设定裁决】\n{json.dumps(review, ensure_ascii=False)}\n\n"
        f"【待审大纲】\n{md}"
    )
    revised = clean_outline_md(await llm.chat_text(
        revision_system, revision_user, temperature=0.12))
    validation_issues = (
        outline_integrity_issues(revised)
        + outline_policy_issues(revised, review)
        + outline_redundant_origin_issues(revised)
    )
    if validation_issues:
        revised = clean_outline_md(await llm.chat_text(
            revision_system,
            revision_user + "\n\n【上一版未通过硬质检，必须逐项修复】\n"
            + "\n".join(f"- {issue}" for issue in validation_issues),
            temperature=0.05))
        validation_issues = (
            outline_integrity_issues(revised)
            + outline_policy_issues(revised, review)
            + outline_redundant_origin_issues(revised)
        )
    if validation_issues:
        raise ValueError("大纲质检修订稿未执行设定裁决：" + "；".join(validation_issues))
    semantic_review = await review_outline_revision_compliance(
        project, revised, review)
    if not semantic_review["passed"]:
        revised = clean_outline_md(await llm.chat_text(
            revision_system,
            revision_user
            + "\n\n【上一版语义复核未通过，必须逐项修复】\n"
            + "\n".join(
                f"- {issue}" for issue in semantic_review["unresolved_issues"])
            + "\n\n【上一版修订稿】\n" + revised,
            temperature=0.05))
        validation_issues = (
            outline_integrity_issues(revised)
            + outline_policy_issues(revised, review)
            + outline_redundant_origin_issues(revised)
        )
        if validation_issues:
            raise ValueError(
                "大纲二次修订仍未通过硬质检：" + "；".join(validation_issues))
        semantic_review = await review_outline_revision_compliance(
            project, revised, review)
    if not semantic_review["passed"]:
        raise ValueError(
            "大纲二次修订仍未通过设定合理性复核："
            + "；".join(semantic_review["unresolved_issues"]))
    return {
        **review,
        "integrity_issues": [],
        "policy_issues": [],
        "semantic_review": semantic_review,
        "revised_markdown": revised,
    }


def _decision_name(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return re.sub(r"[\s“”‘’\"'《》【】（）()]+", "", str(value.get("name") or "")).casefold()


def _normalize_decision_items(value: Any) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        key = _decision_name(raw)
        if not name or not key or key in seen:
            continue
        seen.add(key)
        items.append({"name": name, "reason": str(raw.get("reason") or "").strip()})
    return items


def normalize_outline_decisions(
    accepted_value: Any, rejected_value: Any,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    """裁决不能同时接受和拒绝同一设定；冲突时以更安全的拒绝/合并决定为准。"""
    accepted = _normalize_decision_items(accepted_value)
    rejected = _normalize_decision_items(rejected_value)
    rejected_keys = {_decision_name(item) for item in rejected}
    conflicts = [item["name"] for item in accepted if _decision_name(item) in rejected_keys]
    accepted = [item for item in accepted if _decision_name(item) not in rejected_keys]
    return accepted, rejected, conflicts


def normalize_setting_assessments(value: Any) -> list[dict[str, str]]:
    """保留可展示、可追溯的既有设定合理性裁决。"""
    items: list[dict[str, str]] = []
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
            continue
        verdict = str(raw.get("verdict") or "").strip()
        if verdict not in {"保留", "修订", "删除"}:
            verdict = "修订"
        items.append({
            "name": str(raw.get("name") or "").strip(),
            "origin": str(raw.get("origin") or "既有大纲").strip(),
            "verdict": verdict,
            "reason": str(raw.get("reason") or "").strip(),
        })
    return items


def outline_policy_issues(md: str, review: dict[str, Any]) -> list[str]:
    """零 token 裁决执行检查：模型说要删的设定不能继续留在修订稿里。"""
    text = clean_outline_md(md)
    issues: list[str] = []
    for item in review.get("rejected_additions") or []:
        name = str(item.get("name") or "").strip() if isinstance(item, dict) else ""
        if name and name in text:
            issues.append(f"已拒绝或要求合并的设定仍出现在正文：{name}")
    for item in review.get("setting_assessments") or []:
        if not isinstance(item, dict) or item.get("verdict") != "删除":
            continue
        name = str(item.get("name") or "").strip()
        if name and name in text:
            issues.append(f"判定删除的既有设定仍出现在正文：{name}")
    if re.search(r"砾光[^。\n]{0,100}(?:十年前|十年以前)[^。\n]{0,80}(?:见证|幸存|亲历)", text):
        issues.append("幼龙砾光仍被设定为十年前事件的见证者/幸存者，年龄时间关系不成立")
    return list(dict.fromkeys(issues))


def outline_redundant_origin_issues(md: str) -> list[str]:
    """检查短篇幅项目是否给多个核心角色机械叠加家族/血统秘密。"""
    text = clean_outline_md(md)
    role_start = text.find("## 【角色深度设计】")
    if role_start < 0:
        return []
    role_text = text[role_start:]
    if "\n## " in role_text[len("## 【角色深度设计】"):]:
        split_at = role_text.find("\n## ", len("## 【角色深度设计】"))
        role_text = role_text[:split_at]
    hooks: list[str] = []
    sections = re.split(r"(?m)^###\s+", role_text)[1:]
    for section in sections:
        lines = section.splitlines()
        if not lines:
            continue
        name = lines[0].strip()
        body = "\n".join(lines[1:])
        has_origin = re.search(
            r"(家族|父亲|母亲|血统|身世|长老的后代|守护者的后代)", body)
        has_secret_hook = re.search(
            r"(失踪|秘密|传承|遗物|荣耀|后代|特殊身份|双重身份)", body)
        if has_origin and has_secret_hook:
            hooks.append(name)
    if len(hooks) >= 3:
        return [
            "多个核心角色机械叠加家族、血统或失踪亲人秘密，需只保留最服务主线的"
            f"一至两条：{'、'.join(hooks)}"
        ]
    return []


async def review_outline_revision_compliance(
    project: dict[str, Any] | asyncpg.Record,
    md: str,
    setting_review: dict[str, Any],
) -> dict[str, Any]:
    """独立复核修订成稿；避免裁决 JSON 正确、正文却以改写方式绕过裁决。"""
    draft = (project.get("draft_text") if isinstance(project, dict)
             else project["draft_text"]) or ""
    result = await llm.chat_json(
        """你是独立的影视开发总编，负责复核一份已经过修订的大纲。
不能因为某个设定来自原稿、旧大纲或上一轮质检就默认合理，必须重新判断其必要性、独特性、因果、年龄时间、身份、基调和篇幅承载能力。
项目开发期允许新增人物、势力、阴谋、地点、道具与历史；“原稿未出现”不是问题。真正的问题是新增是否抢走核心主线、功能重复、类型套路堆叠、改写核心角色、造成时间年龄矛盾，或让30章项目承担过多主势力和身世秘密。
逐项检查：
1. 原始草稿的核心人物、目标和世界基调是否仍是中心；
2. 设定裁决是否真正落实，不能换名字保留已拒绝的同类设定；
3. 不得同时给多个核心角色堆叠失踪父母、家族传承、长老后代、隐藏血统或双重身份；
4. 幼年角色不能亲历不符合年龄的旧事件；
5. 新增反派和阴谋必须有不可替代的因果功能，且不能把温暖冒险无依据升级为暗杀、灭族或黑暗神力；
6. 角色名、社会组织、技术与世界风格应相容；
7. 结局必须回收主线，但不能用突然觉醒的血统或万能机关替代人物选择和行动。
只要仍有会改变故事质量、逻辑或主线的未解决问题，passed 必须为 false。
严格输出 JSON：
{"passed":true,"unresolved_issues":[],"reasonable_settings":[{"name":"","reason":""}],
"settings_requiring_revision":[{"name":"","reason":""}],"summary":""}""",
        f"【原始草稿核心设定】\n{draft[:6000]}\n\n"
        f"【上一阶段设定裁决】\n{json.dumps(setting_review, ensure_ascii=False)}\n\n"
        f"【待复核修订大纲】\n{md}",
        temperature=0.03,
        max_tokens=3000,
        purpose="review",
    )
    unresolved = [
        str(x).strip() for x in (result.get("unresolved_issues") or [])
        if str(x).strip()
    ]
    requiring = [
        x for x in (result.get("settings_requiring_revision") or [])
        if isinstance(x, dict) and str(x.get("name") or "").strip()
    ]
    passed = bool(result.get("passed")) and not unresolved and not requiring
    return {
        "passed": passed,
        "unresolved_issues": unresolved or [
            str(x.get("reason") or x.get("name") or "").strip()
            for x in requiring if str(x.get("reason") or x.get("name") or "").strip()
        ],
        "reasonable_settings": [
            x for x in (result.get("reasonable_settings") or [])
            if isinstance(x, dict) and str(x.get("name") or "").strip()
        ],
        "settings_requiring_revision": requiring,
        "summary": str(result.get("summary") or "").strip(),
    }


def _is_promo_type(project_type: str | None) -> bool:
    """视频类型项目（brand_ad/product_ad/geo_promo/film_drama/big_screen 等）走宣传企划分版。
    novel_comic 与空值维持小说向流程。"""
    return str(project_type or "").strip() not in ("", "novel_comic")


def _is_promo(project: dict[str, Any] | asyncpg.Record) -> bool:
    pt = project.get("project_type") if isinstance(project, dict) else project["project_type"]
    return _is_promo_type(pt)


def outline_integrity_issues_promo(md: str) -> list[str]:
    """宣传企划大纲的结构完整性硬检查（与 _OUTLINE_MD_PROMO_SYS 约定结构对应）。"""
    text = clean_outline_md(md)
    issues: list[str] = []
    for heading in ("## 【产品与卖点总览】", "## 【排期总览】", "## 【分集创意】", "## 【视觉与传播设计】"):
        if heading not in text:
            issues.append(f"缺少结构：{heading}")
    if len(text) < 1500:
        issues.append("篇幅不足1500字")
    if len(text) > 9000:
        issues.append("篇幅超过9000字，疑似把逐集分镜写进了架构大纲")
    if not text.rstrip().endswith(("。", "！", "？", "---")):
        issues.append("末尾不是完整句，疑似截断")
    if len(re.findall(r"^### 第.{1,4}集", text, flags=re.MULTILINE)) < 5:
        issues.append("分集创意不足（应逐集列出，每集一个小节）")
    return issues


def outline_integrity_issues(md: str) -> list[str]:
    """零 token 完整性硬检查：结构缺失或明显截断的修订稿不得落库。"""
    text = clean_outline_md(md)
    issues: list[str] = []
    for heading in ("## 【世界观设定】", "## 【主线架构", "## 【角色深度设计】"):
        if heading not in text:
            issues.append(f"缺少结构：{heading}")
    if len(text) < 1800:
        issues.append("篇幅不足1800字")
    if len(text) > 6500:
        issues.append("篇幅超过6500字，疑似包含不应出现的逐章流水账")
    if not text.rstrip().endswith(("。", "！", "？", "---")):
        issues.append("末尾不是完整句，疑似截断")
    if len(re.findall(r"^### 第[一二三四五六七八九十]+卷", text, flags=re.MULTILINE)) < 2:
        issues.append("分卷结构不足")
    return issues


async def _review_outline_development(
    project: dict[str, Any] | asyncpg.Record, md: str,
) -> str:
    """兼容旧调用点：仅返回质检后的完整 Markdown。"""
    return (await review_outline_development(project, md))["revised_markdown"]


async def gen_outline_md_with_review(
    project: dict[str, Any] | asyncpg.Record,
) -> dict[str, Any]:
    draft_md = await llm.chat_text(_OUTLINE_MD_SYS, _outline_md_user(project), temperature=0.25)
    return await review_outline_development(project, clean_outline_md(draft_md))


async def gen_outline_md(project: dict[str, Any] | asyncpg.Record) -> str:
    return (await gen_outline_md_with_review(project))["revised_markdown"]


def gen_outline_md_stream(project: dict[str, Any] | asyncpg.Record):
    """流式版：逐 token yield 文本增量（前端边生成边显示）。调用方收完后自行 clean_outline_md 落库。"""
    return llm.chat_stream(_OUTLINE_MD_SYS, _outline_md_user(project), temperature=0.25)


# ═══════════ 2. 目录（每章带故事线流水账）═══════════

# 规则与输出格式分离：流式版（pipeline_stream）复用规则、把 JSON 输出契约换成 MD 模板
_OUTLINE_RULES = """你是网文大纲架构师。基于项目信息生成章节目录，**每章必须带故事发展简介（流水账式：谁做了什么、局势如何变化、抛出/回收什么伏笔）**——这是整条故事线的落地，后续每章写作靠它保持1000章不飘。
要求：
- 项目大纲中的“新增提案”视为可用开发设定；可为章节落地补充必要的临时人物、过场场景和局部事件
- 不得擅自替换固定主角、改变核心目标、推翻已确认世界规则或让临时角色喧宾夺主
- 新增细节必须服务本章因果链，不得为了凑章节使用无关支线
- 章节故事线必须首尾相接成完整因果链，不许跳跃断裂
- 均匀铺设伏笔与回收点，注明（伏笔：xxx）（回收：xxx）"""

_OUTLINE_SYS = _OUTLINE_RULES + """
- 严格输出 JSON：
{"chapters": [{"seq": 1, "title": "章节名", "summary": "本章故事发展简介流水账（60-120字，含伏笔标注）"}]}"""

_OUTLINE_PROMO_RULES = """你是品牌短视频企划编导。基于企划架构大纲，产出**逐集目录**，每集独立成篇。
要求：
- 每集围绕一个产品功能/卖点展开：先场景、再微型故事、再卖点演示，结尾落在品牌记忆点
- 集与集之间不要求连贯；严禁出现“伏笔/回收/承上集/上一集”等连续剧手法与标注
- 单集标题吸引人；简介写清“场景 + 微型故事 + 卖点呈现”（60-120字）
- 功能卖点覆盖均衡，不重复堆叠同一卖点（除非原始需求要求递进演示）"""

_OUTLINE_PROMO_SYS = _OUTLINE_PROMO_RULES + """
- 严格输出 JSON：
{"chapters": [{"seq": 1, "title": "第X集：标题（卖点）", "summary": "场景+故事+卖点呈现+结尾记忆点（60-120字）"}]}"""


def _outline_user(project: asyncpg.Record | dict[str, Any], count: int) -> str:
    cfg = project["config"] if isinstance(project["config"], dict) else {}
    if _is_promo(project):
        return (
            f"企划名：{project['title']}\n方向：{cfg.get('genre', '')}\n"
            f"建议集数：{count}\n企划概述：{project['synopsis']}\n文案风格：{project['writing_style']}\n"
            f"节奏主线：{project['storyline']}\n"
            f"已确认企划架构大纲：\n{project['outline_md'] or ''}\n"
            f"原始需求（核心方向与不可偏离项）：\n{project['draft_text'] or ''}\n\n"
            f"请以已确认企划大纲为基线生成 {count} 集目录：每集独立成篇、围绕一个产品功能，"
            "不要求集与集连贯，不使用伏笔标注。"
        )
    return (
        f"书名：{project['title']}\n题材：{cfg.get('genre', '')}\n"
        f"梗概：{project['synopsis']}\n文风：{project['writing_style']}\n"
        f"主线故事线：{project['storyline']}\n"
        f"已确认架构大纲：\n{project['outline_md'] or ''}\n"
        f"原始草稿（核心方向与不可偏离项）：\n{project['draft_text'] or ''}\n\n"
        f"请以已确认架构大纲为当前开发设定基线生成 {count} 章目录。"
        "允许用临时人物、过场场景和局部事件把因果链落地；"
        "不得替换固定主角、改变核心目标或再新增会改写全书方向的重大设定。"
    )


async def gen_outline(project: asyncpg.Record, count: int) -> list[dict[str, Any]]:
    sys_prompt = _OUTLINE_PROMO_SYS if _is_promo(project) else _OUTLINE_SYS
    data = await llm.chat_json(sys_prompt, _outline_user(project, count), max_tokens=8000)
    chapters = data.get("chapters") or []
    return chapters[:count]


# ═══════════ 3. 核心要素 ═══════════

_ELEMENTS_SYS = """你是小说设定集架构师。基于项目信息与章节目录，抽取/设计核心要素。
只允许抽取原始草稿、项目梗概和章节目录中已经明确存在的要素；禁止为了凑数量新增人物、势力、地点、道具、能力或剧情线。无法确认的字段留空或标记未知。
kind 只能取：__KINDS__。
- character 的 state 必须含 {"处境":"","目标":"","关系":""}
  （外貌不在此产出——由后置「角色档案补全」按项目年代背景逐个生成，避免单次输出膨胀与"古装现代脸"）
- character 的 meta 还必须含 "voice_profile"——判定角色的发声形态：
  vocal_mode: speech(说人话的角色，含拟人化动物，如疯狂动物城)/call(真动物只发叫声)/
  hybrid(以鸣叫为主偶有传意)/silent(不发声的背景生物或器物)；
  language: 发声语言描述，如"中文人声"/"动物叫声(狼嚎)"/"自创语言(小黄人式叽喳)"，call/silent 填"无"或叫声描述；
  timbre_brief: 音色气质一句话（如"低哑沧桑的中年男声"/"清脆急促的鸟鸣"）。
  判定依据是角色在故事中的实际呈现形态而非物种本身——拟人化动物照样 speech。
- plotline/conflict 的 state 必须含 {"进度":"未开始"}
- 每个要素的 meta 必须含 "needs_image"(bool) 与 "needs_voice"(bool)，由你判定：
  needs_image=true 当该要素是有具体视觉形象、可出设定图的实体（角色、场景，以及有实物形态的设定如法宝/器物/服饰）；
    抽象要素（剧情线 plotline、冲突线 conflict、伏笔 foreshadow，以及无实物的规则/体系类 setting）needs_image=false。
  needs_voice=true 仅当该要素会真正发声（角色且 voice_profile.vocal_mode 属于 speech/call/hybrid）；
    silent 角色与一切非角色要素 needs_voice=false。
- character 若在故事中存在**身份/阶段/形态的显著外形变化**（变身如平民↔超级英雄、境遇剧变如乞丐↔皇后、
  大跨度年龄、易容伪装等，凡"看起来明显不同、需各自一张设定图"的），meta 里给 "variants" 数组，
  每个形态一条 {"tag":"简短形态名(乞丐/皇后/变身后)","desc":"何时呈现此形态的一句话剧情条件"}；
  只有单一稳定形象的角色不给 variants。此处**只出标签与触发剧情，不产外貌**（外貌由后置档案补全逐形态生成）。
- 每个要素给 appears_in（预计出现的章节 seq 数组，依据目录故事线）
严格输出 JSON：
{"elements": [{"kind":"character","name":"","brief":"要素简介(40-100字)","state":{},
  "meta":{"voice_profile":{"vocal_mode":"speech","language":"中文人声","timbre_brief":""},"needs_image":true,"needs_voice":true,"variants":[{"tag":"","desc":""}]},"appears_in":[1,2]}]}"""


# 未做类型判定（老项目/任务失败）时的内置六类兜底
_DEFAULT_ELEMENT_KINDS = [
    {"code": "character", "label": "角色"}, {"code": "scene", "label": "场景"},
    {"code": "plotline", "label": "剧情线"}, {"code": "conflict", "label": "冲突线"},
    {"code": "foreshadow", "label": "伏笔"}, {"code": "setting", "label": "设定"},
]


def project_element_kinds(project: asyncpg.Record | dict[str, Any]) -> list[dict[str, str]]:
    """项目要素分组类型（gen_element_kinds 按剧情判定并写入 config），未判定回退内置六类。"""
    cfg = project["config"] if isinstance(project["config"], dict) else json.loads(project["config"] or "{}")
    kinds = [k for k in (cfg.get("element_kinds") or []) if isinstance(k, dict) and k.get("code")]
    return kinds or _DEFAULT_ELEMENT_KINDS


def _elements_sys(kinds: list[dict[str, str]], suffix: str = "") -> str:
    """要素抽取系统提示词：kind 枚举按项目已判定的要素类型动态织入。"""
    line = "/".join(f"{k['code']}({k['label']})" for k in kinds)
    return _ELEMENTS_SYS.replace("__KINDS__", line) + suffix


def _elements_user(project: asyncpg.Record | dict[str, Any], chapters: list[dict[str, Any]]) -> str:
    outline_text = "\n".join(f"第{c['seq']}章 {c['title']}：{c['summary']}" for c in chapters[:60])
    return (
        f"书名：{project['title']}\n梗概：{project['synopsis']}\n主线：{project['storyline']}\n\n"
        f"原始草稿（核心方向与不可偏离项）：\n{project['draft_text'] or ''}\n\n"
        f"已确认架构大纲（包含已接受的开发期新增设定）：\n"
        f"{project['outline_md'] or ''}\n\n"
        f"章节目录：\n{outline_text}\n\n"
        "请只抽取上述已批准内容中明确存在的核心要素；数量按剧情实际需要，不设最低数量。"
    )


async def gen_elements(
    project: asyncpg.Record, chapters: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    kinds = project_element_kinds(project)
    data = await llm.chat_json(_elements_sys(kinds), _elements_user(project, chapters), max_tokens=8000)
    return data.get("elements") or []


# ═══════════ 落库编排 ═══════════

async def create_project_from_draft(
    pool: asyncpg.Pool, draft: str, overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    """草稿→项目即时落库（纯 DB，不等任何 LLM）+ seed 数字员工。
    overrides=引导式新建各步暂存值直接写入；用户留空的字段先空着，
    由端点随后入队的 gen_project_info 后台任务按草稿补拟（→再链 gen_outline_md）。"""
    from .employees import seed_employees

    info = dict(overrides or {})
    cfg = {
        # 画幅比例来自引导「画面设定」步（默认 16:9），视频生成与工作台预览按此执行
        **({"aspect_ratio": info["aspect_ratio"]} if info.get("aspect_ratio") else {}),
        "character_mode": info.get("character_mode") or "virtual",
        "realistic_character": "enable" if info.get("character_mode") == "real" else "disable",
        # 标签是项目级能力路由元数据；空标签保持旧项目兼容。
        "tags": [str(t).strip() for t in (info.get("tags") or []) if str(t).strip()],
        # genre/suggested_chapters 由 gen_project_info 后台任务补写
    }
    outline_md = None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO content_projects
               (title, project_type, draft_text, synopsis, writing_style, art_style, storyline, outline_md, config, status)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,'info_ready') RETURNING *""",
            info.get("title", "未命名"), info.get("project_type") or "novel_comic", draft, info.get("synopsis", ""),
            info.get("writing_style", ""), info.get("art_style", ""), info.get("storyline", ""),
            outline_md, json.dumps(cfg, ensure_ascii=False),
        )
        await seed_employees(conn, row["id"])
    return dict(row)


def _suggested_chapters(project: asyncpg.Record | dict[str, Any]) -> int:
    """项目配置里的建议章节数（config 可能是 jsonb dict 或 str）。"""
    cfg = project["config"] if isinstance(project["config"], dict) else json.loads(project["config"] or "{}")
    try:
        return max(1, int(cfg.get("suggested_chapters") or 20))
    except (TypeError, ValueError):
        return 20


async def build_outline(pool: asyncpg.Pool, project_id: int, count: int) -> list[dict[str, Any]]:
    """生成目录并落 content_nodes（章节点，summary=故事线流水账预填）。"""
    async with pool.acquire() as conn:
        project = await conn.fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
        if not project:
            raise ValueError("项目不存在")
    chapters = await gen_outline(project, count)
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 全量重建目录=回到「无卷」形态（隐式卷1）：删旧卷+旧章（级联清空正文/分镜），章节 parent_id 留空
            await conn.execute(
                "DELETE FROM content_nodes WHERE project_id=$1 AND kind IN ('chapter','volume')", project_id)
            out = []
            for c in chapters:
                r = await conn.fetchrow(
                    "INSERT INTO content_nodes (project_id, kind, seq, title, summary) "
                    "VALUES ($1,'chapter',$2,$3,$4) RETURNING id, seq, title, summary",
                    project_id, int(c.get("seq", 0)), c.get("title", ""), c.get("summary", ""),
                )
                out.append(dict(r))
            await conn.execute(
                "UPDATE content_projects SET status='outline_ready', updated_at=now() WHERE id=$1",
                project_id,
            )
    return out


# 规则与输出格式分离：流式版（pipeline_stream）复用规则、把 JSON 输出契约换成 MD 模板
_APPEND_RULES = """你是网文大纲架构师。已有一部作品的章节目录，请根据【续写要求】紧接最后一章继续生成后续章节目录。
- **自行判断续写多少章**：要求里给了明确数量就按数量（如"续写10章"→10章）；只给了剧情方向（如"让XX复活并复仇"）就按情节需要合理续写（一般3-12章）；要求为空则续写1章。
- 与已有故事线首尾相接、因果连贯，不跳跃、不重复已有章节；铺设或回收伏笔时注明（伏笔：xxx）（回收：xxx）。"""

_APPEND_CHAPTERS_SYS = _APPEND_RULES + """
严格输出 JSON：{"chapters": [{"title": "章节名", "summary": "本章故事发展简介流水账（60-120字，含伏笔标注）"}]}"""


def _append_chapters_user(
    project: asyncpg.Record | dict[str, Any], rows: list[Any], requirement: str, next_seq: int,
) -> str:
    # 只喂末 12 章作接续锚点（长篇目录不必整本进上下文）
    tail = "\n".join(f"第{r['seq']}章 {r['title']}：{r['summary']}" for r in list(rows)[-12:])
    return (
        f"书名：{project['title']}\n梗概：{project['synopsis']}\n主线故事线：{project['storyline']}\n\n"
        f"已有目录（末尾片段）：\n{tail}\n\n"
        f"【续写要求】{requirement.strip() or '（未指定，续写1章）'}\n\n"
        f"请从第 {next_seq} 章起续写后续章节目录。"
    )


async def append_chapters(
    pool: asyncpg.Pool, project_id: int, requirement: str = ""
) -> list[dict[str, Any]]:
    """新增（续写）章节：按续写要求紧接目录末尾生成 1..N 章并落库（数量由模型按要求判断，上限30）。"""
    async with pool.acquire() as conn:
        project = await conn.fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
        if not project:
            raise ValueError("项目不存在")
        rows = await conn.fetch(
            "SELECT seq, title, summary FROM content_nodes "
            "WHERE project_id=$1 AND kind='chapter' ORDER BY seq", project_id,
        )
    if not rows:
        # 新项目尚无目录：首次点"新增章节"直接生成整本初始目录，不再报错要求先建目录
        return await build_outline(pool, project_id, _suggested_chapters(project))
    next_seq = max(r["seq"] for r in rows) + 1
    user = _append_chapters_user(project, rows, requirement, next_seq)
    data = await llm.chat_json(_APPEND_CHAPTERS_SYS, user, max_tokens=6000)
    chapters = (data.get("chapters") or [])[:30]
    if not chapters:
        raise ValueError("续写未产出章节，请重试")
    out = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            vol_id = await volumes.last_volume_id(conn, project_id)  # 续写落到最后一卷；无卷则留空(隐式卷1)
            for i, c in enumerate(chapters):
                seq = next_seq + i  # seq 由代码确定（模型不参与编号）
                r = await conn.fetchrow(
                    "INSERT INTO content_nodes (project_id, parent_id, kind, seq, title, summary) "
                    "VALUES ($1,$2,'chapter',$3,$4,$5) RETURNING id, seq, title, summary, status",
                    project_id, vol_id, seq, c.get("title", f"第{seq}章"), c.get("summary", ""),
                )
                out.append(dict(r))
    return out


async def _save_element(
    conn: asyncpg.Connection, project_id: int,
    e: dict[str, Any], seq_to_node: dict[int, int],
) -> dict[str, Any]:
    """单要素落库（upsert 同 kind+name）+ 预填出现索引，build/add/流式三路共用。"""
    emeta = e.get("meta") or {}
    kind = e.get("kind", "setting")
    if kind == "character" and isinstance(emeta.get("voice_profile"), dict):
        emeta["voice_profile"].setdefault("source", "gen_elements")
    # 多形态标签（批量抽取只出 tag/desc，外貌由后置档案补全逐形态填）：规整并去空；单形态不留 variants
    if kind == "character" and emeta.get("variants"):
        from . import element_variants as ev
        vs = ev.normalize_variants(emeta["variants"])
        if len(vs) >= 2:
            emeta["variants"] = vs
        else:
            emeta.pop("variants", None)
    else:
        emeta.pop("variants", None)
    # needs_image/needs_voice：优先模型给的 meta 值，兜底顶层误放值，最后按类型缺省
    for fld, default in (("needs_image", kind in ("character", "scene")),
                         ("needs_voice", kind == "character")):
        val = emeta.get(fld, e.get(fld))
        emeta[fld] = bool(default if val is None else val)
    r = await conn.fetchrow(
        """INSERT INTO content_elements (project_id, kind, name, brief, state, meta)
           VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb)
           ON CONFLICT (project_id, kind, name) DO UPDATE
             SET brief=EXCLUDED.brief, state=EXCLUDED.state,
                 meta=EXCLUDED.meta, updated_at=now()
           RETURNING id, kind, name, brief""",
        project_id, kind, e.get("name", ""),
        e.get("brief", ""),
        json.dumps(e.get("state") or {}, ensure_ascii=False),
        json.dumps(emeta, ensure_ascii=False),
    )
    for seq in e.get("appears_in") or []:
        node_id = seq_to_node.get(int(seq))
        if node_id:
            await conn.execute(
                "INSERT INTO element_appearances (project_id, element_id, node_id, snapshot) "
                "VALUES ($1,$2,$3,'（目录预填，待写作回写）') "
                "ON CONFLICT (element_id, node_id) DO NOTHING",
                project_id, r["id"], node_id,
            )
    return dict(r)


async def _save_elements(
    pool: asyncpg.Pool, project_id: int,
    elements: list[dict[str, Any]], seq_to_node: dict[int, int],
) -> list[dict[str, Any]]:
    """要素落库（upsert 同 kind+name）+ 预填出现索引，build/add 两路共用。"""
    out = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            for e in elements:
                out.append(await _save_element(conn, project_id, e, seq_to_node))
            await conn.execute(
                "UPDATE content_projects SET status='elements_ready', updated_at=now() WHERE id=$1",
                project_id,
            )
    return out


async def build_elements(pool: asyncpg.Pool, project_id: int) -> list[dict[str, Any]]:
    """全量生成核心要素并落库 + 预填要素出现索引（检索路④）。"""
    async with pool.acquire() as conn:
        project = await conn.fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
        nodes = await conn.fetch(
            "SELECT id, seq, title, summary FROM content_nodes "
            "WHERE project_id=$1 AND kind='chapter' ORDER BY seq", project_id,
        )
    if not project:
        raise ValueError("项目不存在")
    if not nodes:
        # 尚无目录：自动先生成目录再抽要素，串成一次调用
        await build_outline(pool, project_id, _suggested_chapters(project))
        async with pool.acquire() as conn:
            nodes = await conn.fetch(
                "SELECT id, seq, title, summary FROM content_nodes "
                "WHERE project_id=$1 AND kind='chapter' ORDER BY seq", project_id,
            )
    chapters = [dict(n) for n in nodes]
    elements = await gen_elements(project, chapters)
    seq_to_node = {c["seq"]: c["id"] for c in chapters}
    return await _save_elements(pool, project_id, elements, seq_to_node)


_ADD_ELEMENTS_SUFFIX = """

本次任务是【按新增要求补充要素】而非全量抽取：
- **自行判断生成多少个**：要求里给了明确数量就按数量（如"补充3个场景"→3个）；只给了方向（如"给主角加个师父"）就按需要合理生成（一般1-6个）。
- 不要重复「已有要素」清单中的条目；若要求明确是修改/重做某个已有要素，则输出同 kind+同名的新版本（会覆盖旧值）。"""


def _add_elements_user(
    project: asyncpg.Record | dict[str, Any], chapters: list[dict[str, Any]],
    existing: list[Any], requirement: str,
) -> str:
    outline_text = "\n".join(
        f"第{c['seq']}章 {c['title']}：{c['summary']}" for c in chapters[:60]
    ) or "（暂无目录）"
    existing_text = "\n".join(
        f"- {r['kind']} | {r['name']}：{r['brief']}" for r in existing
    ) or "（暂无）"
    return (
        f"书名：{project['title']}\n梗概：{project['synopsis']}\n主线：{project['storyline']}\n\n"
        f"章节目录：\n{outline_text}\n\n已有要素：\n{existing_text}\n\n"
        f"【新增要求】{requirement.strip()}"
    )


async def add_elements_ai(
    pool: asyncpg.Pool, project_id: int, requirement: str = ""
) -> list[dict[str, Any]]:
    """按自由文本要求 AI 新增核心要素（一个还是多个由模型按要求判断）；留空则等同全量重建。"""
    if not (requirement or "").strip():
        return await build_elements(pool, project_id)
    async with pool.acquire() as conn:
        project = await conn.fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
        if not project:
            raise ValueError("项目不存在")
        nodes = await conn.fetch(
            "SELECT id, seq, title, summary FROM content_nodes "
            "WHERE project_id=$1 AND kind='chapter' ORDER BY seq", project_id,
        )
        existing = await conn.fetch(
            "SELECT kind, name, brief FROM content_elements WHERE project_id=$1 ORDER BY kind, id",
            project_id,
        )
    chapters = [dict(n) for n in nodes]
    user = _add_elements_user(project, chapters, existing, requirement)
    data = await llm.chat_json(
        _elements_sys(project_element_kinds(project), _ADD_ELEMENTS_SUFFIX), user, max_tokens=8000)
    elements = (data.get("elements") or [])[:20]
    if not elements:
        raise ValueError("未产出要素，请换个说法重试")
    seq_to_node = {c["seq"]: c["id"] for c in chapters}
    return await _save_elements(pool, project_id, elements, seq_to_node)


# ═══════════ 章节正文生成（核心原则1检索管线，供后续使用）═══════════

_WRITER_RULES = """你为「影视漫剧/短剧」写分集正文，写的是对白与画面驱动的场景化叙事，不是小说散文。
要求：
- 进场晚退场早：每场从冲突或关键信息切入，砍掉铺垫寒暄；转折点一到立刻收
- 对白驱动为主，展示而非叙述：情绪靠动作与细节呈现，不直述心理
- 环境描写压到一两句，只留承载信息或情绪的那一笔，其余交给分镜
- 严格衔接「最近章节流水账」，不得与已有事实矛盾
- 只能使用出现在「本章要素」或「本章故事线」中的角色/场景，遵守其当前状态；故事线只写群体时不得擅自指定姓名
- 按「本章故事线」推进剧情，落实其中的伏笔标注
- 严格遵守写作偏好指令"""

_CHAPTER_FORMAT = """写完正文后另起一行输出 JSON（用 <STATE> 包裹）：
<STATE>{"chapter_summary":"本章实际故事发展流水账(60-120字)","element_updates":[{"name":"要素名","snapshot":"本章中该要素的状态变化摘要","new_state":{}}]}</STATE>"""

_CHAPTER_SYS = _WRITER_RULES + "\n" + _CHAPTER_FORMAT


async def _writer_system(conn: asyncpg.Connection, project_id: int) -> str:
    """写作员工系统提示词装配：章程 + 技能(kb,项目覆盖全局) + 回写格式(代码强制)。"""
    emp = await conn.fetchrow(
        "SELECT charter FROM agents WHERE project_id=$1 AND code='writer'", project_id
    )
    skill = await conn.fetchrow(
        "SELECT content FROM kb_entries WHERE kind='skill' AND agent_code='writer' AND enabled "
        "AND (scope='global' OR (scope='project' AND project_id=$1)) "
        "AND ((SELECT project_type FROM content_projects WHERE id=$1)='novel_comic' "
        "     OR cardinality(tags)=0 OR (SELECT project_type FROM content_projects WHERE id=$1)=ANY(tags)) "
        "ORDER BY scope DESC LIMIT 1", project_id,
    )
    parts = []
    if emp and emp["charter"]:
        parts.append(emp["charter"])
    parts.append(skill["content"] if skill and skill["content"] else _WRITER_RULES)
    parts.append(_CHAPTER_FORMAT)
    return "\n\n".join(parts)


async def chapter_prompt(pool: asyncpg.Pool, project_id: int, node_id: int, *,
                         target_minutes: int | None = None,
                         creative_brief: str | None = None) -> tuple[str, str]:
    """检索管线：装配写作 system + user 提示词（一次性与流式两版正文生成共用）。"""
    async with pool.acquire() as conn:
        project = await conn.fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
        node = await conn.fetchrow("SELECT * FROM content_nodes WHERE id=$1", node_id)
        # 生效设置=项目 ⊕ 本章所属卷覆盖（writing_style 兜底跟随卷）
        project = await volumes.effective_for_chapter(conn, project, node_id)
        # 检索路②：最近 K 章流水账
        recent = await conn.fetch(
            "SELECT seq, title, summary FROM content_nodes WHERE project_id=$1 AND kind='chapter' "
            "AND seq < $2 ORDER BY seq DESC LIMIT 5", project_id, node["seq"],
        )
        # 检索路④→③：本章要素及其当前状态 + 上次出现快照
        elems = await conn.fetch(
            """SELECT e.id, e.kind, e.name, e.brief, e.state,
                      (SELECT ea2.snapshot FROM element_appearances ea2
                        JOIN content_nodes n2 ON n2.id = ea2.node_id
                       WHERE ea2.element_id = e.id AND n2.seq < $3
                       ORDER BY n2.seq DESC LIMIT 1) AS last_snapshot
               FROM content_elements e
               WHERE e.project_id = $1
                 AND (EXISTS (SELECT 1 FROM element_appearances ea
                               WHERE ea.element_id=e.id AND ea.node_id=$2)
                      OR position(e.name in $4) > 0)""",
            project_id, node_id, node["seq"], node["summary"] or "",
        )
        prefs = await project_preferences(conn, project_id, "writer")
        system = await _writer_system(conn, project_id)

    recent_text = "\n".join(f"第{r['seq']}章 {r['title']}：{r['summary']}" for r in reversed(list(recent))) or "（这是第一章）"
    elem_text = "\n".join(
        f"[{e['kind']}] {e['name']}：{e['brief']}｜当前状态 {e['state']}｜上次出现 {e['last_snapshot'] or '首次登场'}"
        for e in elems
    ) or "（无预关联要素，可按故事线引入）"
    pref_text = "\n".join(f"- {p}" for p in prefs) or f"- {project['writing_style']}"

    runtime = ""
    if target_minutes:
        runtime = (
            f"\n\n# 成片时长硬约束\n目标约{target_minutes}分钟（允许误差±1分钟），正文约"
            f"{target_minutes * 240}–{target_minutes * 420}个汉字；至少5个明确场景段、"
            "30–50个可拍动作/反应节点。动作戏可少对白，但必须用可见事件填足时长，"
            "不得靠重复描写或新增支线灌水。"
        )
    if creative_brief:
        runtime += f"\n\n# 本次创作要求\n{creative_brief.strip()}"
    user = (
        f"# 项目\n{project['title']}｜{project['synopsis']}\n主线：{project['storyline']}\n\n"
        f"# 写作偏好（最高优先级）\n{pref_text}\n\n"
        f"# 最近章节流水账\n{recent_text}\n\n"
        f"# 本章要素（当前状态）\n{elem_text}\n\n"
        f"# 本章故事线\n第{node['seq']}章 {node['title']}：{node['summary']}\n\n"
        f"请写本集正文：对白与画面驱动，场景化推进，叙述与环境描写压到最少。"
        + runtime
    )
    return system, user


def split_chapter_state(raw: str) -> tuple[str, dict[str, Any]]:
    """拆正文与 <STATE> 回写块（前端流式显示时也按 <STATE> 截断展示）。"""
    content, state = raw, {}
    if "<STATE>" in raw:
        content, _, tail = raw.partition("<STATE>")
        state_text = tail.split("</STATE>")[0].strip()
        try:
            state = json.loads(state_text)
        except json.JSONDecodeError:
            state = {}
    return content.strip(), state


async def persist_chapter(
    pool: asyncpg.Pool, project_id: int, node_id: int, raw: str
) -> dict[str, Any]:
    """正文落库 + 回写三件（流水账/要素状态/出现索引快照）。"""
    content, state = split_chapter_state(raw)
    async with pool.acquire() as conn:
        async with conn.transaction():
            version = await conn.fetchval(
                "SELECT coalesce(max(version),0)+1 FROM content_bodies WHERE node_id=$1", node_id)
            await conn.execute(
                "INSERT INTO content_bodies (project_id, node_id, content, word_count, version) "
                "VALUES ($1,$2,$3,$4,$5)", project_id, node_id, content, len(content), version,
            )
            # 回写①：本章流水账（覆盖预填）
            if state.get("chapter_summary"):
                await conn.execute(
                    "UPDATE content_nodes SET summary=$2, status='drafted', updated_at=now() WHERE id=$1",
                    node_id, state["chapter_summary"],
                )
            else:
                await conn.execute(
                    "UPDATE content_nodes SET status='drafted', updated_at=now() WHERE id=$1", node_id
                )
            # 回写②③：要素状态 + 出现索引快照
            for u in state.get("element_updates") or []:
                elem = await conn.fetchrow(
                    "SELECT id, state FROM content_elements WHERE project_id=$1 AND name=$2",
                    project_id, u.get("name", ""),
                )
                if not elem:
                    continue
                if u.get("new_state"):
                    await conn.execute(
                        "UPDATE content_elements SET state = state || $2::jsonb, updated_at=now() WHERE id=$1",
                        elem["id"], json.dumps(u["new_state"], ensure_ascii=False),
                    )
                await conn.execute(
                    """INSERT INTO element_appearances (project_id, element_id, node_id, snapshot)
                       VALUES ($1,$2,$3,$4)
                       ON CONFLICT (element_id, node_id) DO UPDATE SET snapshot=EXCLUDED.snapshot""",
                    project_id, elem["id"], node_id, u.get("snapshot", ""),
                )
    return {"node_id": node_id, "word_count": len(content), "state": state}


def chapter_acceptance_errors(raw: str, *, target_minutes: int | None = None,
                              required_terms: list[str] | None = None,
                              forbidden_terms: list[str] | None = None) -> list[str]:
    """章节正文硬验收：返回不通过的原因列表（全通过则空）。一次性版与流式版共用。

    动作/画面驱动的影视脚本通常比小说叙述字数更少；以 240 字/分钟作为可拍内容下限，
    配合场景数与动作节点约束，避免用重复描写灌水。"""
    content, _state = split_chapter_state(raw)
    errors: list[str] = []
    if target_minutes:
        lower, upper = target_minutes * 240, target_minutes * 420
        if len(content) < lower:
            errors.append(f"正文仅{len(content)}字，至少需要{lower}字")
        if len(content) > upper:
            errors.append(f"正文{len(content)}字，最多允许{upper}字")
    missing = [term for term in (required_terms or []) if term not in content]
    if missing:
        errors.append(f"缺少必需剧情词：{'、'.join(missing)}")
    found = [term for term in (forbidden_terms or []) if term in raw]
    if found:
        errors.append(f"出现越界剧情词：{'、'.join(found)}")
    return errors


async def write_chapter(pool: asyncpg.Pool, project_id: int, node_id: int, *,
                        target_minutes: int | None = None,
                        creative_brief: str | None = None,
                        required_terms: list[str] | None = None,
                        forbidden_terms: list[str] | None = None) -> dict[str, Any]:
    """检索管线→生成→回写三件（一次性版；流式版见 API 层 write_chapter_stream）。

    验收规则抽到 chapter_acceptance_errors，与流式版共用一份——此前只有本函数校验，
    流式版（前端实际走的那条）完全没校验，短稿静默落库。"""
    system, user = await chapter_prompt(
        pool, project_id, node_id,
        target_minutes=target_minutes, creative_brief=creative_brief)
    last_errors: list[str] = []
    for attempt in range(3):
        retry = ("\n\n上一次草稿未通过硬验收：" + "；".join(last_errors)
                 + "。请完整重写，不要只补丁式续写。") if last_errors else ""
        raw = await llm.chat_text(system, user + retry)
        errors = chapter_acceptance_errors(
            raw, target_minutes=target_minutes,
            required_terms=required_terms, forbidden_terms=forbidden_terms)
        if not errors:
            return await persist_chapter(pool, project_id, node_id, raw)
        last_errors = errors
    raise RuntimeError("章节正文连续3次未通过验收：" + "；".join(last_errors))
