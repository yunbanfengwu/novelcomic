"""镜级要素预检（用户 2026-07-13 定稿）：生成图片/视频前，由大模型依据镜头剧本判断
本镜需要哪些视觉要素（角色/场景/关键实物），与要素库做代码匹配双重验证；
库中没有的（尤其角色、场景、武器等实物）自动补建进核心要素库并关联本镜——
设定图随后由镜级前置 _ensure_element_sheets 按 needs_image 补出。

结果带指纹缓存（镜头剧本文本指纹 + TTL）落镜 meta.elements_precheck：
剧本没改就不重烧 LLM；失败不阻塞生成（尽力而为）。
"""
import json
import logging
from typing import Any

import asyncpg

from .. import llm
from . import element_variants as ev
from . import flow
from .character_context import era_anchor
from .element_profile import gen_element_profile

log = logging.getLogger("shot_elements")

_PRECHECK_TTL_H = 168  # 剧本指纹不变即命中，TTL 只是兜底刷新

_SHOT_ELEMENTS_SYS = """你是分镜要素核对员。给定一个镜头的剧本信息、项目世界观/年代背景与项目核心要素库清单，\
判断本镜画面中实际出现、需要跨镜视觉一致性锚定的要素：
- character：画面中需要辨识身份的**具名/关键角色**（无名背景路人不算）
- scene：本镜地点对应的场景
- setting：画面中的关键实物——**极严格，宁缺勿滥**：只挑本故事**专属、会反复出现、且对剧情有实质作用**的招牌物件（主角专属武器/法宝/信物/关键机关/坐骑/核心器物）。\
**绝大多数镜头没有这类物件，就不要给 setting**。严禁把通用、常见、消耗、一次性或场景自带的物件当要素——例如：盐、糖、绳子、鞭子、杯碗盘碟、桌椅、食物酒水、蜡烛、纸张信件、火把、普通刀剑、日用杂物等**一律不建**，这些交给画面描述即可，无需跨镜一致性。判定基准：换掉这个物件，观众会认不出剧情吗？不会就不建。
  反过来，**满足下面任一条就必须建**，哪怕它体积小、看着像日用品：①被郑重交付/传承/取出的信物、凭证、徽记；\
②角色反复使用、或用它触发关键剧情的器物（哨子、钥匙、罗盘、铃铛、印章…）；③剧情围绕它展开或以它命名的物件。\
判定基准：**这一集里如果它每次出现长得都不一样，观众会不会看不懂？**会就必须建——小物件被画错（铜哨画成望远镜）比大物件更常见，因为模型没有锚图就按字面自由发挥。

**世界观/年代一致性（最重要）**：新建要素的 brief 与外貌提示词必须严格贴合下方【项目世界观/年代背景】——\
古代/古典/东方项目绝不出现现代物或异域文化（现代马车/汽车/霓虹灯/西装/美式街景），科幻按其设定材质，\
地域、民族、建筑、器物、服饰风格都要与该世界观同源，绝不穿越、绝不换文化背景。

对每个要素做两步判断：
1. 若要素库清单中已有对应条目（包括名称变体，如剧本写"老船长"、清单原名"沉默老船长（黑衣人）"），library_name 必须填清单原名
2. 清单中确实没有 → library_name 填空串，并补全新要素定义：
   - character：brief 只写该角色的**身份定位**（是谁、什么身份、与主角/剧情什么关系），40字内，**绝不要写这一个镜头里的动作/表情/光线/站位**；外貌提示词**留空**（正式外貌稍后由「角色档案」按项目年代统一补全，此处不要定死）。
   - scene / setting：brief（40字内中文外观简介）+ 外貌提示词（中文标签短语式，顿号「、」分隔、精炼，用于生图，具体到形制/材质/颜色/磨损等视觉细节，且**贴合项目世界观**）。
要素 name 必须是干净的实体名（如"废弃码头"、"青铜古剑"），不要照抄剧本里的"场景/时间/地点"格式串；地点为"未知/待定"等占位时不要生造 scene 要素。
3. 多形态选择：若清单里某要素带【形态：标签1/标签2…】（该角色有身份/阶段/形态变化，如"平民/变身后"、"乞丐/皇后"），\
必须依据本镜剧情判断此刻是哪个形态，把对应标签原文填进 variant_tag；要素无形态标注时 variant_tag 留空串。
严格输出 JSON：
{"required": [{"kind":"character|scene|setting","name":"要素名","library_name":"清单原名或空串","variant_tag":"形态标签或空串","brief":"","外貌提示词":""}]}"""


def _meta_of(row: Any) -> dict[str, Any]:
    m = row["meta"]
    return m if isinstance(m, dict) else json.loads(m or "{}")


def _shot_script(summary: str | None, meta: dict[str, Any]) -> str:
    """预检的判定源文本（同时作缓存指纹源）：画面+动作+对白+地点+出场角色。"""
    bits = [
        summary or "",
        meta.get("action") or "",
        meta.get("dialogue") or "",
        meta.get("scene") or "",
        "、".join(meta.get("characters") or []),
    ]
    return "\n".join(b for b in bits if b and b != "无")


async def ensure_shot_required_elements(
    pool: asyncpg.Pool, project_id: int | None, node_id: int | None,
    force: bool = False,
) -> list[int]:
    """LLM 判断 + 代码匹配双重验证本镜所需要素；缺失的补建入库并关联本镜。
    返回本次新关联到镜上的要素 id 列表（含新建）；缓存命中/无镜返回 []。
    force=True 无视指纹缓存重判（编排「重跑此步」/质检回退用）。"""
    from .storyboard import _names_match

    if not project_id or not node_id:
        return []
    async with pool.acquire() as conn:
        shot = await conn.fetchrow(
            "SELECT summary, meta FROM content_nodes WHERE id=$1 AND kind='shot'", node_id
        )
        if not shot:
            return []
        meta = _meta_of(shot)
        script = _shot_script(shot["summary"], meta)
        if not script or (not force and flow.cache_valid(meta.get("elements_precheck"), script)):
            return []
        rows = await conn.fetch(
            "SELECT id, kind, name, brief, meta FROM content_elements WHERE project_id=$1",
            project_id,
        )
        project = await conn.fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
    def _roster_line(r: Any) -> str:
        line = f"- {r['kind']} | {r['name']}：{(r['brief'] or '')[:30]}"
        tags = [v.get("tag") for v in ev.variants_of(_meta_of(r)) if v.get("tag")]
        return line + (f"【形态：{'/'.join(tags)}】" if tags else "")

    roster = "\n".join(_roster_line(r) for r in rows) or "（空）"
    # 项目世界观/年代背景：让新建要素（尤其场景/道具的外貌提示词）与本项目同源，
    # 治"中国古代却出美国现代马车"（era 复用角色档案的年代锚逻辑，config.era 缺省则据梗概/画风推断）
    world = era_anchor(project) if project else "（无）"
    user = (
        f"【项目世界观/年代背景】{world}\n\n"
        f"镜头剧本：\n画面：{shot['summary'] or ''}\n动作：{meta.get('action') or ''}\n"
        f"对白：{meta.get('dialogue') or '无'}\n地点：{meta.get('scene') or ''}\n"
        f"出场角色：{'、'.join(meta.get('characters') or []) or '（未标注）'}\n\n"
        f"项目要素库清单：\n{roster}"
    )
    data = await llm.chat_json(_SHOT_ELEMENTS_SYS, user)
    required = [x for x in (data.get("required") or []) if isinstance(x, dict)][:10]

    def _match_id(kind: str, *names: str) -> int | None:
        """代码侧双重验证：精确名 → 基名模糊，按 kind 收敛。

        kind 按等价类收敛而不是精确相等：预检只输出 character|scene|setting，
        而要素库里同一件实物可能建成 item/prop（项目要素抽取用的是另一套 kind 词表）。
        严格相等会让已存在的 item 永远匹配不上，于是每次预检都重建一条 setting
        ——同一个「古老风帆翼」两条记录两张设定图，画面里当然对不上。"""
        alias = {
            "setting": ("setting", "item", "prop"),
            "item": ("item", "setting", "prop"),
            "prop": ("prop", "item", "setting"),
        }.get(kind, (kind,))
        for n in names:
            n = (n or "").strip()
            if not n:
                continue
            hit = next((r for r in rows if r["kind"] in alias and r["name"] == n), None) or next(
                (r for r in rows if r["kind"] in alias and _names_match(n, r["name"])), None
            )
            if hit:
                return hit["id"]
        return None

    by_id = {r["id"]: r for r in rows}

    def _resolve_variant(eid: int, tag: str) -> str | None:
        """把 LLM 选的形态标签解析成该要素的 variant_id：标签精确/包含匹配，命中即返回。"""
        emeta = _meta_of(by_id[eid]) if eid in by_id else {}
        if not (tag and ev.has_variants(emeta)):
            return None
        tag = tag.strip()
        vs = ev.variants_of(emeta)
        hit = next((v for v in vs if (v.get("tag") or "").strip() == tag), None) or next(
            (v for v in vs if tag and (tag in (v.get("tag") or "") or (v.get("tag") or "") in tag)), None)
        return hit.get("id") if hit else None

    linked: list[int] = []
    created: list[str] = []
    variant_map: dict[str, str] = {}   # {element_id: variant_id}，本镜多形态要素的形态选择
    for item in required:
        kind = (item.get("kind") or "").strip()
        name = (item.get("name") or "").strip()
        if kind not in ("character", "scene", "setting") or not name:
            continue
        eid = _match_id(kind, item.get("library_name") or "", name)
        if eid is not None:
            vid = _resolve_variant(eid, item.get("variant_tag") or "")
            if vid:
                variant_map[str(eid)] = vid
        if eid is None:
            # 双重验证均未命中 → 缺失要素：补建入核心要素库（needs_image=true 走设定图前置）
            emeta = {
                "外貌提示词": (item.get("外貌提示词") or "").strip(),
                "needs_image": True, "needs_voice": kind == "character",
                "source": "shot_precheck",
            }
            r = await pool.fetchrow(
                """INSERT INTO content_elements (project_id, kind, name, brief, state, meta)
                   VALUES ($1,$2,$3,$4,'{}'::jsonb,$5::jsonb)
                   ON CONFLICT (project_id, kind, name) DO UPDATE SET updated_at=now()
                   RETURNING id""",
                project_id, kind, name, (item.get("brief") or "").strip(),
                json.dumps(emeta, ensure_ascii=False),
            )
            eid = r["id"]
            created.append(f"{kind}:{name}")
            if kind in ("character", "item"):
                # 新建角色/关键道具不拿镜头单句当身份：走年代/世界观感知的正规档案补全，
                # 生成结构化 profile + 贴合项目年代的外貌提示词（补上预检留空的外貌），
                # 设定图前置随后据此出图——治"配角首帧=通用陌生人、道具=现代穿越件、风格不对"
                try:
                    await gen_element_profile(pool, project_id, eid)
                except Exception as e:  # noqa: BLE001 — 补档失败不阻塞生成，保留粗建可后续手动补
                    log.warning("新建要素 %s 档案补全失败（保留粗建，可稍后手动补档）: %s", name, e)
        linked.append(eid)

    stamp: dict[str, Any] = {"created": created}
    flow.stamp_validity(stamp, script, _PRECHECK_TTL_H)
    async with pool.acquire() as conn:
        # 重读镜 meta 再合并（预检与其它生成任务可能并发改 meta）
        cur = await conn.fetchrow("SELECT meta FROM content_nodes WHERE id=$1", node_id)
        if not cur:
            return []
        m = _meta_of(cur)
        old_ids = [int(x) for x in (m.get("element_ids") or [])]
        new_ids = [e for e in linked if e not in old_ids]
        patch: dict[str, Any] = {"elements_precheck": stamp}
        if new_ids:
            patch["element_ids"] = old_ids + new_ids
        if variant_map:
            # 合并保留已有选择（用户手改/上轮预检），本轮新判定覆盖同一要素
            patch["element_variants"] = {**(m.get("element_variants") or {}), **variant_map}
        await conn.execute(
            "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
            node_id, json.dumps(patch, ensure_ascii=False),
        )
        for eid in new_ids:
            await conn.execute(
                "INSERT INTO element_appearances (project_id, element_id, node_id, snapshot) "
                "VALUES ($1,$2,$3,$4) ON CONFLICT (element_id, node_id) DO NOTHING",
                project_id, eid, node_id,
                (meta.get("action") or shot["summary"] or "")[:200],
            )
    if created or new_ids:
        log.info("镜 %s 要素预检: 新建 %s，新关联 %d 个要素", node_id, created or "无", len(new_ids))
    return new_ids
