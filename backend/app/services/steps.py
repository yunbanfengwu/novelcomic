"""生成环节 Step 实现：每类任务的 前置(before) / 执行(run) / next(收尾)。

2026-07-11 从旧 worker if 链迁移到统一管线（flow.py，路由守卫模式）。
预检均带缓存有效期（flow.cache_valid：源文本指纹 + TTL），命中免重跑：
- 提示词质检：指纹=提示词文本，72h —— 生成前只查状态，不再每次重烧 30-60s 评审
- 音频预检：指纹=对白+音色绑定，24h
- 要素设定图：指纹=外貌提示词|brief，无限期（图在且指纹对即有效；旧图无指纹视为有效）
"""
import asyncio
import json
import logging
from typing import Any

from .. import media
from ..oss import store_bytes, store_url
from . import continuity, element_variants as ev
from . import flow, volumes
from .flow import Blocked, Ctx, RunResult, Step, register

log = logging.getLogger("steps")


def _meta(row: Any) -> dict[str, Any]:
    m = row["meta"]
    return m if isinstance(m, dict) else json.loads(m)


async def _shot_meta(ctx: Ctx) -> dict[str, Any]:
    row = await ctx.pool.fetchrow(
        "SELECT meta FROM content_nodes WHERE id=$1 AND kind='shot'", ctx.node_id
    )
    if not row:
        raise Blocked("分镜不存在（可能已被重拆删除）")
    return _meta(row)


async def _node_meta_conn(conn: Any, node_id: int | None) -> dict[str, Any]:
    """missing_deps 入队期读节点 meta（走依赖解析事务的 conn，不新开连接）。"""
    if not node_id:
        return {}
    row = await conn.fetchrow("SELECT meta FROM content_nodes WHERE id=$1", node_id)
    return _meta(row) if row else {}


def _shot_variant_corpus(smeta: dict[str, Any]) -> str:
    """本镜供"多形态自动选图"关键词匹配的剧本文本：画面+动作+对白+各切。"""
    bits = [smeta.get("summary") or "", smeta.get("action") or "", smeta.get("dialogue") or ""]
    for c in smeta.get("cuts") or []:
        bits += [c.get("subject") or "", c.get("action") or ""]
    return " ".join(b for b in bits if b)


# 同一要素的设定图生成锁（进程内）：多镜并发（worker 6 协程）同时发现同一要素缺图时，
# 只有第一个真的生成，其余在锁内复查指纹后直接复用——防重复烧图、防同要素出两张不同设定图
_SHEET_LOCKS: dict[int, asyncio.Lock] = {}


async def _ensure_element_sheets(ctx: Ctx, force: bool = False) -> bool:
    """镜级生成的确定性前置（用户 2026-07-09 定稿）：本镜关联要素缺设定图，
    或外貌提示词已改（指纹失配）→ 先生成再继续。设定图是身份/画风锚点，
    缺图会导致引用落空或画风崩（巡夜卡通鳐鱼事故）。旧图无指纹视为有效（不回溯重生成）。"""
    async with ctx.pool.acquire() as conn:
        shot = await conn.fetchrow("SELECT summary, meta FROM content_nodes WHERE id=$1", ctx.node_id)
        if not shot:
            return False
        smeta = {**_meta(shot), "summary": shot["summary"] or ""}
        ids = smeta.get("element_ids") or []
        if not ids:
            return False
    # 本镜按剧情选定的形态（镜级预检写入）：{element_id: variant_id}；缺则按剧本关键词兜底选
    return await ensure_element_assets(
        ctx, ids, corpus=_shot_variant_corpus(smeta),
        chosen={str(k): v for k, v in (smeta.get("element_variants") or {}).items()},
        force=force)


async def ensure_element_assets(
    ctx: Ctx, element_ids: list[Any], corpus: str = "",
    chosen: dict[str, Any] | None = None, force: bool = False,
) -> bool:
    """要素身份资产的统一前置：对给定要素，保证「角色档案 → 设定图」都就位。

    凡是最终会把角色画进画面的环节（镜级首帧、场景空间图、分镜组图）都必须先过这里，
    否则缺档案的要素装配出"年龄=未设定、性别=未设定"的提示词、缺图的要素引用直接落空，
    模型只能自由发挥——而且这个错误会被下游每一张图"一致地"继承下去。
    以要素为锁粒度，并发调用安全；指纹未变且已有图的直接跳过，零成本。"""
    from .element_sheet import assemble_element_sheet_prompt

    chosen = chosen or {}
    changed = False
    for eid in element_ids:
        async with _SHEET_LOCKS.setdefault(int(eid), asyncio.Lock()):
            e = await ctx.pool.fetchrow(
                "SELECT id, kind, name, brief, meta FROM content_elements "
                "WHERE project_id=$1 AND id=$2",
                ctx.project_id, eid,
            )
            if not e:
                continue
            em = _meta(e)
            # 只补当前剧情真正要用的那个形态的设定图（不为一处把角色所有形态全画出来）
            variant = ev.pick_variant(em, corpus, chosen.get(str(eid)))
            vid = variant.get("id")
            fp = flow.fingerprint(ev.sheet_source(variant, e["brief"]))
            stale = variant.get("sheet_fingerprint") and variant["sheet_fingerprint"] != fp
            if variant.get("sheet_url") and not stale and not force:
                continue
            # 出图前先保证有角色档案：缺 profile 的要素（早期由项目要素抽取粗建、
            # 只有一句性格简介的那批）装配出来的设定图提示词会写成"年龄=未设定，性别=未设定"，
            # 模型只能自由发挥——阿砚因此被画成黑色无袖紧身衣+现代运动鞋的通用少年，
            # 且这个错误会被下游每一张图"一致地"继承。档案是身份锚的源头，必须先补。
            if e["kind"] in ("character", "item") and not em.get("profile"):
                from .element_profile import gen_element_profile
                try:
                    await gen_element_profile(ctx.pool, ctx.project_id, e["id"])
                    e = await ctx.pool.fetchrow(
                        "SELECT id, kind, name, brief, meta FROM content_elements WHERE id=$1", e["id"])
                    em = _meta(e)
                    variant = ev.pick_variant(em, corpus, chosen.get(str(eid)))
                    vid = variant.get("id")
                    fp = flow.fingerprint(ev.sheet_source(variant, e["brief"]))
                    log.info("要素 %s 缺角色档案，已在出设定图前补齐", e["name"])
                except Exception as exc:  # noqa: BLE001 补档失败不阻塞，仍按现有信息出图
                    log.warning("要素 %s 补档失败（仍继续出设定图）: %s", e["name"], exc)
            prompts = await assemble_element_sheet_prompt(ctx.pool, ctx.project_id, e["id"], vid)
            token = media.GEN_AUDIT.set({
                "project_id": ctx.project_id, "node_id": ctx.node_id, "task_id": ctx.task_id,
                "kind": "gen_element_sheet",
                "source": f"project_{ctx.project_id}_element_{e['id']}_sheet",
            })
            try:
                url = await media.generate_image(
                    prompts["sheet_prompt"], store_prefix="sheet",
                    profile_id=ctx.payload.get("model_profile_id"),
                    feature_code="element_sheet")
            finally:
                media.GEN_AUDIT.reset(token)
            async with ctx.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO content_attachments (project_id, element_id, kind, url, meta) "
                    "VALUES ($1,$2,'image',$3,$4::jsonb)",
                    ctx.project_id, e["id"], url,
                    json.dumps({"prompt": prompts["sheet_prompt"], "type": "sheet",
                                "variant_id": vid, "tag": variant.get("tag") or "",
                                "auto": "生成前置自动补图"}, ensure_ascii=False),
                )
                # 回写到该形态（含主形态镜像回顶层，兼容老读点）；重读 meta 防并发覆盖
                cur = await conn.fetchrow("SELECT meta FROM content_elements WHERE id=$1", e["id"])
                patch = ev.set_variant_sheet(_meta(cur), vid, url, fp)
                await conn.execute(
                    "UPDATE content_elements SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
                    e["id"], json.dumps(patch, ensure_ascii=False),
                )
            log.info("节点 %s 前置生成要素设定图: %s%s%s", ctx.node_id, e["name"],
                     f"·{variant.get('tag')}" if variant.get("tag") else "",
                     "（外貌已改）" if stale else "")
            changed = True
    return changed


async def _review_prompt_cached(ctx: Ctx, meta: dict[str, Any], kind: str) -> None:
    """镜级生成前置②：提示词质检（带缓存有效期）。缓存命中=指纹匹配且未过期→零成本放行；
    未命中→九维评审（不合格自动重构→复审，review_* 内部完成）。
    质检失败不阻塞生成（尽力而为）；用户手编提示词（prompt_overridden）豁免。"""
    from .storyboard import review_image_prompt, review_video_prompt

    if ctx.payload.get("prompt_overridden"):
        return
    if kind == "gen_keyframe":
        entry, cur = meta.get("prompt_review_image"), meta.get("image_prompt")
    else:
        entry, cur = meta.get("prompt_review"), meta.get("video_prompt")
    if cur and flow.cache_valid(entry, cur):
        ctx.payload["prompt"] = cur
        return
    try:
        if kind == "gen_keyframe":
            rv = await review_image_prompt(ctx.pool, ctx.project_id, ctx.node_id)
            ctx.payload["prompt"] = rv.get("image_prompt") or ctx.payload["prompt"]
        else:
            rv = await review_video_prompt(ctx.pool, ctx.project_id, ctx.node_id)
            ctx.payload["prompt"] = rv.get("video_prompt") or ctx.payload["prompt"]
            # 质检重构加长了时间轴 → 提交时长跟随重构版（否则视频被掐一半）
            if rv.get("duration_s"):
                ctx.payload["duration_s"] = rv["duration_s"]
        if rv.get("重构"):
            log.info("task %s 提示词质检重构 (合格=%s 得分=%s)", ctx.task_id, rv.get("合格"), rv.get("得分"))
    except Exception as e:  # noqa: BLE001 — 质检失败不阻塞生成
        log.warning("task %s 提示词质检异常，按原提示词生成: %s", ctx.task_id, e)


def _refs_off(meta: dict[str, Any], target: str) -> set[str]:
    """本镜在该目标（image/video）下停用的参考图名单（要素名/"故事板"）。"""
    return set(((meta.get("ref_off") or {}).get(target)) or [])


# 参考图引用句（「图片N是…」）单一实现在 media.ref_intro_line，本文件不再自拼


# 送进生图提示词的视觉硬锁（顺序即渲染顺序）。故意不含 location_id / scene_version /
# story_day / camera_axis——那几项是连续性台账编码（CHAPTER_001、AXIS_003），
# 对画面模型是纯噪声，场景名与空间拓扑已经把地点说清楚了。
_VISUAL_LOCKS = (
    ("time_of_day", "时间段"),
    ("weather", "天气"),
    ("primary_light_source", "主光源"),
    ("lighting_direction", "光向"),
    ("color_temperature", "色温"),
    ("palette", "色板"),
)
# 锁值是英文枚举码，直接塞进中文提示词会削弱约束力，逐项译回中文
_LOCK_VALUE_CN = {
    "time_of_day": {"dawn": "黎明", "morning": "清晨", "noon": "正午", "afternoon": "午后",
                    "dusk": "黄昏", "night": "夜晚", "midnight": "午夜"},
    "weather": {"thunderstorm": "雷暴", "heavy_rain": "暴雨", "rain": "雨", "snow": "雪",
                "fog": "雾", "clear": "晴", "storm": "风暴", "overcast": "阴云密布"},
    "primary_light_source": {"firelight": "火光", "daylight": "日光", "lightning": "雷光",
                             "moonlight": "月光", "lamplight": "灯光"},
    "color_temperature": {"warm": "暖调", "cool": "冷调", "neutral": "中性色温"},
}


def _lock_cn(key: str, value: Any) -> str:
    """锁值渲染：枚举码译中文，自由文本（色板/光向）原样带出"""
    return _LOCK_VALUE_CN.get(key, {}).get(str(value), str(value))


async def _frame_size(ctx: Ctx, chapter_id: int | None = None) -> str:
    """生图尺寸跟随项目/卷画幅（用户 2026-07-16：竖版项目的首帧/尾帧/场景图必须出竖图，
    否则 I2V 首帧与视频画幅不符）：9:16→1440x2560，其余→2560x1440（与封面同一组值）。
    chapter_id 缺省时按 ctx.node_id（镜）向上取所属章；仅 ARK Seedream 吃 size，GRSAI 忽略。"""
    cid = chapter_id
    if cid is None:
        row = await ctx.pool.fetchrow("SELECT parent_id FROM content_nodes WHERE id=$1", ctx.node_id)
        cid = row["parent_id"] if row else None
    proj = await ctx.pool.fetchrow("SELECT * FROM content_projects WHERE id=$1", ctx.project_id)
    eff = await volumes.effective_for_chapter(ctx.pool, proj, cid) if proj and cid else dict(proj or {})
    cfg = eff.get("config") or {}
    cfg = cfg if isinstance(cfg, dict) else json.loads(cfg or "{}")
    return "1440x2560" if cfg.get("aspect_ratio") == "9:16" else "2560x1440"


async def _frame_aspect_ratio(ctx: Ctx, chapter_id: int | None = None) -> str:
    """业务画幅合同；具体像素由 media provider 适配层决定。"""
    cid = chapter_id
    if cid is None:
        row = await ctx.pool.fetchrow("SELECT parent_id FROM content_nodes WHERE id=$1", ctx.node_id)
        cid = row["parent_id"] if row else None
    proj = await ctx.pool.fetchrow("SELECT * FROM content_projects WHERE id=$1", ctx.project_id)
    eff = await volumes.effective_for_chapter(ctx.pool, proj, cid) if proj and cid else dict(proj or {})
    cfg = eff.get("config") or {}
    cfg = cfg if isinstance(cfg, dict) else json.loads(cfg or "{}")
    return "9:16" if cfg.get("aspect_ratio") == "9:16" else "16:9"


def _drop_unmentioned_chars(prompt: str, refs: list[dict[str, Any]], where: str) -> list[dict[str, Any]]:
    """角色参考图硬闸（2026-07-14 定稿）：最终提示词（含手编）没点到的角色不上传设定图——
    名字/基名/@设定图引用都不在词里还传图，模型会把人硬画进画面（空景镜被塞进主角实锤）。
    只闸角色：场景/道具/故事板等环境类参考不受影响。"""
    from .storyboard import _name_in_text  # 惰性导入防循环依赖

    out, dropped = [], []
    for r in refs or []:
        n = r.get("name") or ""
        if (r.get("kind") != "character" or f"@设定图[{n}]" in prompt
                or _name_in_text(n, prompt)):
            out.append(r)
        else:
            dropped.append(n)
    if dropped:
        log.info("%s 提示词未点到角色 %s，设定图不上传（硬闸）", where, "、".join(dropped))
    return out


async def _shot_audit_ctx(ctx: Ctx, kind: str, suffix: str) -> dict[str, Any]:
    """镜级生成的审计上下文（media 层据此落 gen_logs）：章节/镜号 + 来源标记。
    source=project_{项目}_{章seq}_{镜号}_{video|image}——前缀筛即得该分镜全部生成记录；
    节点非镜（章级宫格等）时退化为 project_{项目}_node_{节点}_{suffix}。"""
    row = await ctx.pool.fetchrow(
        "SELECT s.meta->>'shot_no' AS shot_no, c.id AS chapter_id, c.seq AS chapter_seq,"
        " c.title AS chapter_title FROM content_nodes s"
        " LEFT JOIN content_nodes c ON c.id=s.parent_id WHERE s.id=$1", ctx.node_id)
    # 完整镜号（含手动插入镜的小数号）进 source 前缀；gen_logs.shot_no 为 INT 列，
    # 仅纯整数镜号落库，小数号落 None（source 里已保留完整号可筛）
    label = row["shot_no"] if row else None
    shot_no = int(label) if label and label.isdigit() else None
    mid = (f"{row['chapter_seq']}_{label}" if row and row["chapter_seq"] and label
           else f"node_{ctx.node_id}")
    return {
        "project_id": ctx.project_id, "node_id": ctx.node_id, "task_id": ctx.task_id,
        "chapter_id": row["chapter_id"] if row else None,
        "chapter_title": row["chapter_title"] if row else None, "shot_no": shot_no,
        "kind": kind, "source": f"project_{ctx.project_id}_{mid}_{suffix}",
    }


async def _shot_gen_before(ctx: Ctx, kind: str) -> dict[str, Any]:
    """镜级生成共用前置：①要素预检（LLM 判断本镜所需要素，缺失自动补建入库，带缓存）
    ②补设定图③重装配（拾取短引用与参考图）④提示词质检（缓存）。

    重装配无条件执行（纯 DB+字符串，零 LLM 成本）：设定图 URL 固化在镜 meta.reference_images
    里，仅靠外貌指纹判断会漏掉"同外貌重出设定图"（URL 已换但指纹未变）——每次生成前
    重新装配才能保证参考图/提示词永远指向要素当前的最新设定图。装配输出确定性强，
    文本未变时质检缓存（指纹=提示词全文）依然命中，不产生额外质检成本。"""
    from .continuity_records import assert_shot_generation_ready
    from .shot_elements import ensure_shot_required_elements

    try:
        await assert_shot_generation_ready(ctx.pool, ctx.node_id)
    except ValueError as e:
        raise Blocked(str(e)) from e

    try:
        # 剧本指纹缓存命中即零成本；失败不阻塞生成（要素齐全时本就多余）
        await ensure_shot_required_elements(ctx.pool, ctx.project_id, ctx.node_id)
    except Exception as e:  # noqa: BLE001
        log.warning("镜 %s 要素预检失败（不阻塞生成）: %s", ctx.node_id, e)
    try:
        # 场景空间规划兜底（2026-07-16 站位锚）：本镜所在场景组缺站位链→先规划再装配；
        # 组内剧本指纹缓存命中即零成本，失败不阻塞生成（老章节/重拆后首次生成自动补齐）
        from .scene_blocking import ensure_scene_blocking

        row = await ctx.pool.fetchrow(
            "SELECT parent_id, meta FROM content_nodes WHERE id=$1 AND kind='shot'", ctx.node_id)
        if row:
            await ensure_scene_blocking(ctx.pool, ctx.project_id, row["parent_id"],
                                        only_seg=_meta(row).get("scene_seg"))
    except Exception as e:  # noqa: BLE001
        log.warning("镜 %s 场景空间规划失败（不阻塞生成）: %s", ctx.node_id, e)
    await _ensure_element_sheets(ctx)
    from .storyboard import assemble_shot_prompts

    fresh = await assemble_shot_prompts(ctx.pool, ctx.project_id, ctx.node_id)
    if not ctx.payload.get("prompt_overridden"):
        ctx.payload["prompt"] = (
            fresh["image_prompt"] if kind == "gen_keyframe" else fresh["video_prompt"]
        )
    ctx.payload["prompt_textonly"] = fresh.get("video_prompt_textonly") or ctx.payload.get("prompt_textonly")
    ctx.payload["reference_images"] = fresh.get("reference_images") or []
    # 权威时长以本镜内容的专业评估为准（assemble 已按 estimate_shot_duration 回写）——
    # 提交给模型的 duration 跟随重装配刷新，不再用 enqueue 时的粗拆预估（用户 2026-07-12）
    ctx.payload["duration_s"] = fresh.get("duration_s") or ctx.payload.get("duration_s") or 5
    meta = await _shot_meta(ctx)
    await _review_prompt_cached(ctx, meta, kind)
    return meta


# ═══════════════ Steps ═══════════════

@register
class ShotStoryboardStep(Step):
    """生成单镜分镜剧本（时间轴/CUT）；是提示词与视频生成的显式前置节点。"""

    kind = "gen_shot_storyboard"
    group = "分镜"
    gen_slot = "storyboard_script"
    timeout_s = 420
    before_notes = ["镜头基本信息与连续性记录就绪"]
    run_note = "生成镜内时间轴、景别、主体动作、运镜与硬切"
    next_notes = ["回写 cuts；无需切换的短镜标记为连续单镜"]

    async def before(self, ctx: Ctx) -> None:
        from .continuity_records import assert_shot_generation_ready

        await _shot_meta(ctx)
        try:
            await assert_shot_generation_ready(ctx.pool, ctx.node_id)
        except ValueError as e:
            raise Blocked(str(e)) from e

    async def run(self, ctx: Ctx) -> RunResult:
        from .storyboard import redesign_shot_coverage

        result = await redesign_shot_coverage(ctx.pool, ctx.node_id)
        await ctx.pool.execute(
            "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
            ctx.node_id,
            json.dumps({
                "storyboard_script_ready": True,
                "storyboard_script_at": flow.now_iso(),
            }, ensure_ascii=False),
        )
        return RunResult({"cuts": len(result.get("cuts") or [])})


@register
class GenPromptsStep(Step):
    """提示词生成（装配+质检合并，2026-07-11 按钮合并定稿）：
    run=三套提示词装配；next=九维双评审（首帧+视频→不合格自动重构→复审→有保留放行），
    结果带指纹+有效期落 meta——后续生成任务的前置只查状态，不重跑。"""

    kind = "gen_prompts"
    group = "提示词"
    dep_kinds = ["gen_shot_storyboard"]
    gen_slot = "prompts"
    timeout_s = 420
    before_notes = ["分镜存在守卫"]
    run_note = "装配三套提示词：首帧图 / 视频 / 纯文本（外貌全文兜底版）"
    next_notes = [
        "九维双评审（首帧+视频）→ 不合格自动重构 → 复审 → 有保留放行",
        "结果盖指纹 + 72h 有效期落 meta（后续生成前置只查状态不重跑）",
    ]

    async def missing_deps(self, conn: Any, project_id: int | None,
                           node_id: int | None, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if payload.get("only") == "image":
            return []
        meta = await _node_meta_conn(conn, node_id)
        if meta.get("storyboard_script_ready") or meta.get("cuts"):
            return []
        return [{"kind": "gen_shot_storyboard", "payload": {}, "priority": 10}]

    async def before(self, ctx: Ctx) -> None:
        from .continuity_records import assert_shot_generation_ready

        await _shot_meta(ctx)
        try:
            await assert_shot_generation_ready(ctx.pool, ctx.node_id)
        except ValueError as e:
            raise Blocked(str(e)) from e

    async def run(self, ctx: Ctx) -> RunResult:
        from .storyboard import assemble_shot_prompts, redesign_shot_coverage

        # 显式重生成=用户放弃手编内容：先清对应侧 edited 标记（含双字段分段标记），
        # 装配才会覆盖手编提示词
        only = ctx.payload.get("only")
        _img_flags = ["image_prompt_edited", "image_prompt_user_edited", "image_prompt_anchor_edited"]
        _vid_flags = ["video_prompt_edited", "video_prompt_user_edited", "video_prompt_anchor_edited"]
        clear = ([] if only == "video" else _img_flags) + ([] if only == "image" else _vid_flags)
        await ctx.pool.execute(
            "UPDATE content_nodes SET meta = meta - $2::text[], updated_at=now() WHERE id=$1",
            ctx.node_id, clear,
        )
        # 兼容旧入口的显式重做参数；新画布使用独立 gen_shot_storyboard 节点。
        if ctx.payload.get("redesign_cuts"):
            await redesign_shot_coverage(ctx.pool, ctx.node_id)
        await assemble_shot_prompts(ctx.pool, ctx.project_id, ctx.node_id)
        return RunResult({})

    async def next(self, ctx: Ctx, result: dict[str, Any]) -> dict[str, Any]:
        from .storyboard import review_image_prompt, review_video_prompt

        def brief(r: dict[str, Any]) -> dict[str, Any]:
            return {k: r.get(k) for k in ("合格", "得分", "重构", "有保留") if k in r}

        # only=image/video → 只审一侧（单独重生成某套提示词时省一半质检成本）。
        # 双侧并发（互不依赖：各自评审各自的提示词，落 meta 的 jsonb 合并键不相交）——
        # 评审内容与串行完全一致，只省等待时间
        only = ctx.payload.get("only")
        out: dict[str, Any] = {}
        if only == "image":
            out["image"] = brief(await review_image_prompt(ctx.pool, ctx.project_id, ctx.node_id))
        elif only == "video":
            out["video"] = brief(await review_video_prompt(ctx.pool, ctx.project_id, ctx.node_id))
        else:
            img, vid = await asyncio.gather(
                review_image_prompt(ctx.pool, ctx.project_id, ctx.node_id),
                review_video_prompt(ctx.pool, ctx.project_id, ctx.node_id),
            )
            out["image"], out["video"] = brief(img), brief(vid)
        return out


@register
class BreakdownStep(Step):
    """章节→**粗拆分镜骨架**（两阶段拆镜第一阶段，2026-07-12）。before=章节存在守卫；
    run=粗拆（小 JSON+粗审重拆闭环，落 detail_pending=true）；
    next=只串一个 expand_shot_details 任务——按板补详细分镜后再串逐镜 gen_prompts
    （提示词装配依赖详细字段）。宫格总览图不再自动串出（仅手动）。链深受限防环。"""

    kind = "breakdown_chapter"
    group = "拆镜"
    chains_to = ["expand_shot_details"]
    gen_slot = "storyboard"
    before_notes = ["章节存在守卫"]
    run_note = "流式粗拆分镜骨架（Gate 重拆 + 总审重拆闭环，落 detail_pending）"
    next_notes = ["串出 expand_shot_details（详细分镜）；宫格总览图不再自动出"]
    max_retries = 0  # 内部已有流式→JSON 回退与重拆闭环；整任务重跑会让时间轴再清空重来一遍
    timeout_s = 1200

    async def before(self, ctx: Ctx) -> None:
        row = await ctx.pool.fetchrow(
            "SELECT id FROM content_nodes WHERE id=$1 AND kind='chapter'", ctx.node_id
        )
        if not row:
            raise Blocked("章节不存在")

    async def run(self, ctx: Ctx) -> RunResult:
        from .storyboard import breakdown_chapter

        # task_id 传入：流式拆镜逐镜上报进度（SSE 实时推前端）
        shots = await breakdown_chapter(ctx.pool, ctx.project_id, ctx.node_id, task_id=ctx.task_id)
        return RunResult({"shot_ids": [s["id"] for s in shots]})

    async def next(self, ctx: Ctx, result: dict[str, Any]) -> dict[str, Any]:
        # 粗拆完串详细分镜展开（其 next 再串逐镜 gen_prompts）。宫格总览图不再自动出
        # （用户 2026-07-12：总图效果不佳，gen_overview_grid 仅手动触发）
        depth = int(ctx.payload.get("chain_depth") or 0)
        details_task: int | None = None
        if depth < flow.MAX_CHAIN_DEPTH and result.get("shot_ids"):
            g = await flow.enqueue(
                ctx.pool, kind="expand_shot_details", project_id=ctx.project_id,
                node_id=ctx.node_id, payload={"chain_depth": depth + 1}, priority=5,
                root_task_id=ctx.task["root_task_id"] or ctx.task_id,
            )
            details_task = g["task_id"]
        return {"shots": len(result.get("shot_ids") or []), "details_task": details_task}


async def _expand_pending_details(ctx: Ctx) -> int:
    """按板(≤16)把粗拆分镜 LLM 展开成详细分镜（两阶段拆镜第二阶段）。
    幂等：detail_pending 非真的镜跳过（重触发/续跑不重复 LLM）。返回本次展开的镜数。"""
    from ..knowledge import project_preferences
    from .overview_grid import board_slices
    from .storyboard import _director_system, expand_board_details

    async with ctx.pool.acquire() as conn:
        shot_rows = await conn.fetch(
            "SELECT id, seq, summary, meta FROM content_nodes "
            "WHERE parent_id=$1 AND kind='shot' AND deleted_at IS NULL ORDER BY seq", ctx.node_id,
        )
    if not shot_rows:
        raise Blocked("本章尚无分镜，请先拆分镜")
    if not any(_meta(r).get("detail_pending") for r in shot_rows):
        return 0
    async with ctx.pool.acquire() as conn:
        project = await conn.fetchrow("SELECT * FROM content_projects WHERE id=$1", ctx.project_id)
        node = await conn.fetchrow("SELECT * FROM content_nodes WHERE id=$1", ctx.node_id)
        project = await volumes.effective_for_chapter(conn, project, ctx.node_id)  # 画风跟随本章所属卷
        body = await conn.fetchrow(
            "SELECT content FROM content_bodies WHERE node_id=$1 ORDER BY version DESC LIMIT 1",
            ctx.node_id,
        )
        prefs = await project_preferences(conn, ctx.project_id, "director")
        system = await _director_system(conn, ctx.project_id, "详细分镜输出格式")
        scenes = await conn.fetch(
            "SELECT name, brief FROM content_elements WHERE project_id=$1 AND kind='scene'",
            ctx.project_id,
        )
        known_chars = {
            r["name"] for r in await conn.fetch(
                "SELECT name FROM content_elements WHERE project_id=$1 AND kind='character'",
                ctx.project_id,
            )
        }
    source = body["content"] if body else f"（本章尚无正文，按故事线拆镜）{node['summary']}"
    pref_text = "\n".join(f"- {p}" for p in prefs)
    scene_text = "\n".join(f"- {s['name']}：{s['brief']}" for s in scenes) or "（无）"
    user_prefix = (
        f"项目画风：{project['art_style']}\n"
        + (f"导演偏好：\n{pref_text}\n" if pref_text else "")
        + f"\n项目场景要素：\n{scene_text}\n"
        + f"\n第{node['seq']}章《{node['title']}》原文（详细分镜的画面描述须忠实于此，"
        f"不得臆造原文没有的情节）：\n{source[:8000]}"
    )
    total = 0
    for batch in board_slices(list(shot_rows)):
        total += await expand_board_details(
            ctx.pool, ctx.project_id, ctx.node_id, system,
            user_prefix, source, known_chars, batch,
        )
    log.info("task %s 详细分镜按板展开: %d 镜（%d 板）", ctx.task_id, total,
             len(board_slices(list(shot_rows))))
    return total


@register
class ShotDetailsStep(Step):
    """详细分镜展开（两阶段拆镜第二阶段，独立任务）：粗拆后自动串出，按板(≤16)把粗镜
    LLM 展开成详细分镜（幂等），next 再为每镜串 gen_prompts（装配三套提示词+九维质检）。
    2026-07-12 与宫格总览图解耦：总图效果不佳，不再作为拆镜链的强制环节。"""

    kind = "expand_shot_details"
    group = "拆镜"
    chains_to = ["scene_blocking"]
    gen_slot = "shot_details"
    run_note = "按板（≤16）LLM 展开详细分镜 + 首帧画面描述 cuts（幂等）"
    next_notes = ["串出 scene_blocking（场景组空间规划：站位链+多景别图提示词）"]
    timeout_s = 1200  # 按板 LLM 展开（N/16 次）

    async def run(self, ctx: Ctx) -> RunResult:
        expanded = await _expand_pending_details(ctx)
        return RunResult({"expanded": expanded})

    async def next(self, ctx: Ctx, result: dict[str, Any]) -> dict[str, Any]:
        # 提示词不在此预装配（2026-07-14：改为生成首帧/视频时按需前置装配+质检）。
        # 详细分镜就绪后串场景空间规划（2026-07-16）：按场景组产出空间布局+逐镜站位链——
        # 站位锚是装配期跨镜空间连贯的输入，必须先于首帧/视频出
        depth = int(ctx.payload.get("chain_depth") or 0)
        blocking_task: int | None = None
        if depth < flow.MAX_CHAIN_DEPTH:
            g = await flow.enqueue(
                ctx.pool, kind="scene_blocking", project_id=ctx.project_id,
                node_id=ctx.node_id, payload={"chain_depth": depth + 1}, priority=5,
                root_task_id=ctx.task["root_task_id"] or ctx.task_id,
            )
            blocking_task = g["task_id"]
        return {"expanded": result.get("expanded"), "blocking_task": blocking_task}


@register
class SceneBlockingStep(Step):
    """场景组空间规划（2026-07-16 站位锚定）：分镜按 scene 连续段归组（meta.scene_seg），
    逐组 LLM 产出空间布局+组开场角色占位+逐镜站位链+镜内移动（落每镜 meta.blocking），
    以及「场景多景别参考图」提示词（落章 meta.scene_blocking.groups，人工确认后点击生成）。
    组内剧本指纹缓存：没改不重烧；详细分镜后自动串出，也可手动重跑（force 全量重规划）。"""

    kind = "scene_blocking"
    group = "拆镜"
    gen_slot = "scene_blocking"
    timeout_s = 1200  # 逐组 LLM（含校验重试），组数=章内场景连续段数
    before_notes = ["章节存在守卫"]
    run_note = "场景归组（scene 连续段）→ 逐组 LLM 空间规划（站位链+多景别图提示词，指纹缓存）"
    next_notes = ["站位锚落每镜 meta.blocking；组级汇总落章 meta.scene_blocking（装配期织入提示词）"]

    async def before(self, ctx: Ctx) -> None:
        row = await ctx.pool.fetchrow(
            "SELECT id FROM content_nodes WHERE id=$1 AND kind='chapter'", ctx.node_id)
        if not row:
            raise Blocked("章节不存在")

    async def run(self, ctx: Ctx) -> RunResult:
        from .continuity_records import materialize_chapter
        from .scene_blocking import ensure_scene_blocking

        out = await ensure_scene_blocking(
            ctx.pool, ctx.project_id, ctx.node_id,
            only_seg=ctx.payload.get("only_seg"),
            force=bool(ctx.payload.get("force")),
        )
        continuity = await materialize_chapter(ctx.pool, ctx.project_id, ctx.node_id)
        return RunResult({**out, "continuity": continuity})


def scene_sheet_ref_intro(refs: list[dict[str, Any]]) -> str:
    """参考图引用句（站位图与整集组图共用）：告诉模型每张传图是什么。

    空场景基准图（kind=scene_empty）与设定图的用法完全相反——前者要照搬构图与光线、
    后者只提供造型不提供构图，所以两类必须分别措辞，不能笼统说"按设定图还原"。"""
    if not refs:
        return ""
    intro = "，".join(media.ref_intro_line(i, r, scope="group")
                      for i, r in enumerate(refs, start=1))
    return (f"{intro}。基准图决定空间、机位与光线（照搬）；"
            "设定图只决定造型，构图与姿态按下文描述重新塑造。")


def build_scene_empty_prompt(prompt: str, refs: list[dict[str, Any]],
                             scene: str = "", space: str = "") -> str:
    """纯函数：第一阶段「空场景基准图」的最终生成提示词（可单测）。

    参考池只有环境锚点与场景设定图，绝不含角色图——带了角色图模型就会把人画进来，
    而这一张的全部价值就在于无人。末尾的无人硬约束是最后一道闸：历史提示词、
    场景设定图里的路人都可能把人带回画面。

    室内锁（2026-07-28 实测补）：镜头级提示词与整集组图早有这条锁（_lock_line /
    build_group_keyframe_prompt），唯独基准图没有——线上"机械工坊"跑出来右侧整面墙
    敞开、直接露出海面与雷云。基准图是整组的空间真值，它露天了，站位图照搬、组内每个
    镜头再照搬，一路错到底。"""
    from .scene_blocking import SINGLE_FRAME_RULE, is_indoor

    name_to_no = {r["name"]: i for i, r in enumerate(refs[:4], start=1) if r.get("name")}
    body = media._resolve_ref_markers(prompt, name_to_no)  # noqa: SLF001
    intro = ""
    if refs:
        intro = "，".join(media.ref_intro_line(i, r, scope="group")
                          for i, r in enumerate(refs[:4], start=1))
        intro += ("。按设定图还原场景外观、材质与画风；"
                  "**但设定图里若出现人物，本次一律不要画进来**。")
    # 只有文字锁不够：场景设定图常常本身就是"缺一面墙的剖面图"（为了展示内部），
    # 而上面的 intro 又要求"按设定图还原外观"——视觉参考压过文字，模型就照着把墙拆了
    # （线上"机械工坊"实测：设定图两格都是敞开式，基准图跟着敞开、直接连海）。
    # 所以必须点名参考图的取景不算数，只取材质/陈设/画风。
    indoor = ("**封闭室内且屋顶完整**：四面墙与屋顶必须闭合，不得改成露天、庭院、"
              "剖面图或缺一面墙的舞台布景；天空、海面与远景只能透过窗或门洞出现。"
              "设定图若把空间画成缺墙的剖面或开放式布景，**不要照搬那个取景**——"
              "只取它的材质、陈设与画风，空间本身一律按四壁闭合的室内来画。"
              if is_indoor(scene, space) else "")
    return (
        intro + body
        + "。【最终硬约束（以本段为准）】这是空场景基准图：**画面中不得出现任何人物、动物、"
        "生物或它们的剪影与背影**，只有空间本身与陈设。"
        + indoor
        + f"{SINGLE_FRAME_RULE}。"
    )


def build_scene_sheet_prompt(prompt: str, refs: list[dict[str, Any]], has_empty: bool) -> str:
    """纯函数：第二阶段「角色站位图」的最终生成提示词（可单测）。

    has_empty=参考池首位是不是本场景的空场景基准图。是则收口成"照搬图片1的空间与光线、
    只加人"——这是两阶段方案的全部意义：空间不再靠文字自证，而是有实物锚。
    没有基准图时退化成老口径（单幅、按文字画），不至于卡死。"""
    from .scene_blocking import EMPTY_ANCHOR_RULE, SINGLE_FRAME_RULE

    name_to_no = {r["name"]: i for i, r in enumerate(refs[:4], start=1) if r.get("name")}
    body = media._resolve_ref_markers(prompt, name_to_no)  # noqa: SLF001
    lock = (EMPTY_ANCHOR_RULE if has_empty else
            "按文字描述塑造空间与光线（本场景尚无空场景基准图）")
    return (
        scene_sheet_ref_intro(refs[:4]) + body
        + f"。【最终硬约束（以本段为准，忽略上文任何冲突描述）】{lock}。"
        "角色造型严格按各自设定图还原，不得增减人数、不得换脸换装；"
        f"{SINGLE_FRAME_RULE}。"
    )


async def _scene_group(ctx: Ctx) -> dict[str, Any]:
    """取本任务 payload.seg 对应的场景组条目（两个场景图 Step 共用的守卫）。"""
    row = await ctx.pool.fetchrow(
        "SELECT meta FROM content_nodes WHERE id=$1 AND kind='chapter'", ctx.node_id)
    if not row:
        raise Blocked("章节不存在")
    seg = int(ctx.payload.get("seg") or 0)
    grp = next((g for g in ((_meta(row).get("scene_blocking") or {}).get("groups") or [])
                if int(g.get("seg") or 0) == seg), None)
    if not grp:
        raise Blocked(f"场景组 {seg} 不存在——请先运行场景空间规划")
    return grp


def _rotate_group_image(g: dict[str, Any], url: str, url_field: str,
                        ver_field: str, task_id: Any) -> None:
    """场景组条目图指针轮换唯一实现：旧图进版本链、新图上位（url 相同则幂等不动）。
    单场景落库与整集组图落库共用这一份，勿再各写。"""
    old = g.get(url_field)
    if old and old != url:
        versions = list(g.get(ver_field) or [])
        if not any(isinstance(v, dict) and v.get("url") == old for v in versions):
            versions.append({"url": old, "superseded_by_task": task_id})
        g[ver_field] = versions
    g[url_field] = url


async def _write_scene_image(ctx: Ctx, url: str, att_type: str, url_field: str,
                             ver_field: str) -> None:
    """两阶段共用的落库：章级附件留档 + 回写组条目指针（旧图进版本链）。

    读改写 groups 数组必须整段包在事务里：批量一次派 N 个任务、6 个 worker 并发落库，
    FOR UPDATE 的行锁在自动提交下随语句即刻释放 → 各自读到同一份旧 groups、全量写回时
    互相覆盖，只有最后一个 seg 留得下来（丢更新）。"""
    seg = int(ctx.payload.get("seg") or 0)
    async with ctx.pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO content_attachments (project_id, node_id, kind, url, meta) "
            "VALUES ($1,$2,'image',$3,$4::jsonb)",
            ctx.project_id, ctx.node_id, url,
            json.dumps({"prompt": ctx.payload.get("prompt"), "type": att_type,
                        "prompt_final": ctx.payload.get("prompt_final"),
                        "seg": seg}, ensure_ascii=False))
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT meta FROM content_nodes WHERE id=$1 FOR UPDATE", ctx.node_id)
            sb = (_meta(row).get("scene_blocking") or {}) if row else {}
            for g in sb.get("groups") or []:
                if int(g.get("seg") or 0) != seg:
                    continue
                _rotate_group_image(g, url, url_field, ver_field, ctx.task_id)
            await conn.execute(
                "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
                ctx.node_id, json.dumps({"scene_blocking": sb}, ensure_ascii=False))


@register
class GenSceneEmptyStep(Step):
    """第一阶段·空场景基准图：一张**无人**的场景图，锁死本场景组的空间几何与光影。

    2026-07-28 两阶段改造的上游。此前"一张多宫格图自己交代空间"实测治不了漂移
    （章1026 场景1：空场景格里站着人、俯视格画成场景设定图的翻版、同一条龙两个样），
    根因是格与格之间除文字外没有任何硬锚。先出这一张，站位图再拿它当参考图，
    空间与光线就有了实物锚，模型只需在给定空间里摆人。"""

    kind = "gen_scene_empty"
    group = "生图"
    manual = True
    timeout_s = 600
    dep_kinds = ["scene_blocking"]
    before_notes = ["取章 meta.scene_blocking.groups 对应组的 empty_prompt 与环境参考池",
                    "装配最终提示词：参考图引用句 + 无人硬约束（参考池不含任何角色图）"]
    run_note = "生成无人的空场景基准图（项目环境锚点+场景设定图作参考）→ OSS"
    next_notes = ["落章级附件（type=scene_empty）+ 回写组条目 empty_url（站位图与下游镜头的空间真值）"]

    async def missing_deps(self, conn: Any, project_id: int | None,
                           node_id: int | None, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """硬前置=本组的空间规划。empty_prompt 是规划的产物，缺了就该去生产它，
        而不是判 Blocked 甩给用户——旧单阶段数据一律没有这个字段，而"先去跑场景空间规划"
        在界面上一度根本点不到，用户只能看着任务反复失败（2026-07-28 线上实测）。
        only_seg 限定只重规划本组（不动同章其它组）；force 绕开指纹缓存——
        缺 empty_prompt 恰恰说明缓存里那份是旧版产物，不强制就会被原样跳过。"""
        if payload.get("prompt"):
            return []
        seg = int(payload.get("seg") or 0)
        meta = await _node_meta_conn(conn, node_id)
        grp = next((g for g in ((meta.get("scene_blocking") or {}).get("groups") or [])
                    if int(g.get("seg") or 0) == seg), None)
        if grp and grp.get("empty_prompt"):
            return []
        return [{"kind": "scene_blocking", "node_id": node_id,
                 "payload": {"only_seg": seg, "force": True}, "priority": 10}]

    async def before(self, ctx: Ctx) -> None:
        grp = await _scene_group(ctx)
        if not ctx.payload.get("prompt"):
            ctx.payload["prompt"] = grp.get("empty_prompt")
        if not ctx.payload.get("prompt"):
            raise Blocked("空场景图提示词为空——请先运行场景空间规划或手动填写")
        refs = [r for r in (grp.get("empty_refs") or []) if r.get("url")][:4]
        # 兜底：老数据的 empty_refs 不存在时，从 sheet_refs 里捞非角色的环境类参考。
        # 角色图一张都不能进——这一张的全部价值就是无人。
        if not refs:
            refs = [r for r in (grp.get("sheet_refs") or [])
                    if r.get("url") and r.get("kind") in ("style", "scene")][:4]
        ctx.payload["reference_images"] = refs
        ctx.payload["prompt_final"] = build_scene_empty_prompt(
            ctx.payload["prompt"], refs, grp.get("scene") or "", grp.get("space") or "")
        if not ctx.payload.get("size"):
            ctx.payload["size"] = await _frame_size(ctx, chapter_id=ctx.node_id)

    async def run(self, ctx: Ctx) -> RunResult:
        token = media.GEN_AUDIT.set({
            "project_id": ctx.project_id, "node_id": ctx.node_id, "task_id": ctx.task_id,
            "kind": self.kind, "chapter_id": ctx.node_id,
            "source": f"project_{ctx.project_id}_node_{ctx.node_id}_empty{ctx.payload.get('seg')}",
        })
        try:
            refs = [r for r in (ctx.payload.get("reference_images") or []) if r.get("url")]
            url = await media.generate_image(
                ctx.payload["prompt_final"], size=ctx.payload.get("size"),
                reference_images=[r["url"] for r in refs[:4]] or None,
                store_prefix="scene_empty", profile_id=ctx.payload.get("model_profile_id"),
                feature_code="scene_sheet")
        finally:
            media.GEN_AUDIT.reset(token)
        return RunResult({"url": url})

    async def next(self, ctx: Ctx, result: dict[str, Any]) -> dict[str, Any]:
        await _write_scene_image(ctx, result["url"], "scene_empty", "empty_url", "empty_versions")
        return result


@register
class GenSceneSheetStep(Step):
    """第二阶段·角色站位图：把角色按站位锚放进已定死的空场景里。

    参考池首位是本组的空场景基准图（gen_scene_empty 产出），空间、机位与光线一律照搬它，
    本步唯一新增的是人。这是 2026-07-28 两阶段改造的下游——此前让模型在一张多宫格图里
    自己保证跨格空间一致性，实测做不到。提示词由空间规划自动产出、人工确认后点击生成。"""

    kind = "gen_scene_sheet"
    group = "生图"
    manual = True
    timeout_s = 600
    dep_kinds = ["gen_scene_empty", "scene_blocking"]
    before_notes = ["取章 meta.scene_blocking.groups 对应组的提示词与角色参考池（payload.prompt 可覆盖）",
                    "把本组空场景基准图插到参考池首位，装配「照搬基准图、只加人」的最终提示词"]
    run_note = "在空场景基准图上生成角色站位图（基准图+角色设定图作参考）→ OSS"
    next_notes = ["落章级附件（type=scene_sheet）+ 回写组条目 sheet_url"]

    async def missing_deps(self, conn: Any, project_id: int | None,
                           node_id: int | None, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """硬前置=本组的空场景基准图。缺了就先派 gen_scene_empty——没有它这一步会退化成
        老口径（纯文字塑造空间），正是要根治的那个毛病。

        提示词同理：sheet_prompt 是空间规划的产物，组条目里没有（旧单阶段数据/从未规划）
        就该去补规划，而不是判 Blocked 让用户自己去点一个入口。组条目整个不存在时也一样——
        原先这里直接 return [] 什么都不派，等于把"没规划过"的章节推给 before 去判失败。"""
        seg = int(payload.get("seg") or 0)
        meta = await _node_meta_conn(conn, node_id)
        grp = next((g for g in ((meta.get("scene_blocking") or {}).get("groups") or [])
                    if int(g.get("seg") or 0) == seg), None)
        deps: list[dict[str, Any]] = []
        # 基准图已有、只缺提示词时才直接派规划；基准图也缺的话由下面的 gen_scene_empty
        # 串出规划即可（它自己声明了 scene_blocking 前置），避免同一个规划任务重复入队。
        if (not payload.get("prompt") and not (grp or {}).get("sheet_prompt")
                and grp and grp.get("empty_url")):
            deps.append({"kind": "scene_blocking", "node_id": node_id,
                         "payload": {"only_seg": seg, "force": True}, "priority": 10})
        if not grp or not grp.get("empty_url"):
            deps.append({"kind": "gen_scene_empty", "node_id": node_id,
                         "payload": {"seg": seg}, "priority": 10})
        return deps

    async def before(self, ctx: Ctx) -> None:
        grp = await _scene_group(ctx)
        if not ctx.payload.get("prompt"):
            ctx.payload["prompt"] = grp.get("sheet_prompt")
        if not ctx.payload.get("prompt"):
            raise Blocked("场景图提示词为空——请先运行场景空间规划或手动填写")
        # 基准图占参考池首位（依赖 DAG 保证它已生成；单点重出时也可能还没有 → 退化但不卡死）
        empty_url = grp.get("empty_url")
        refs: list[dict[str, Any]] = []
        if empty_url:
            refs.append({"name": "空场景基准图", "kind": "scene_empty", "url": empty_url})
        refs += [r for r in (grp.get("sheet_refs") or [])
                 if r.get("url") and r.get("kind") != "scene_empty"]
        refs = refs[:4]
        ctx.payload["reference_images"] = refs
        # 提示词装配属于 before：run 只负责调模型。人工编辑的提示词原样留在 payload.prompt
        # （落库与回显用），机器最终口径另存 prompt_final。
        ctx.payload["prompt_final"] = build_scene_sheet_prompt(
            ctx.payload["prompt"], refs, bool(empty_url))
        # 生图尺寸跟随项目/卷画幅（组内镜头以其为空间参考，画幅必须一致）
        if not ctx.payload.get("size"):
            ctx.payload["size"] = await _frame_size(ctx, chapter_id=ctx.node_id)

    async def run(self, ctx: Ctx) -> RunResult:
        token = media.GEN_AUDIT.set({
            "project_id": ctx.project_id, "node_id": ctx.node_id, "task_id": ctx.task_id,
            "kind": self.kind, "chapter_id": ctx.node_id,
            "source": f"project_{ctx.project_id}_node_{ctx.node_id}_scene{ctx.payload.get('seg')}",
        })
        try:
            refs = [r for r in (ctx.payload.get("reference_images") or []) if r.get("url")]
            url = await media.generate_image(
                ctx.payload.get("prompt_final") or ctx.payload["prompt"],
                size=ctx.payload.get("size"),
                reference_images=[r["url"] for r in refs[:4]] or None,
                store_prefix="scene_sheet", profile_id=ctx.payload.get("model_profile_id"),
                feature_code="scene_sheet")
        finally:
            media.GEN_AUDIT.reset(token)
        return RunResult({"url": url})

    async def next(self, ctx: Ctx, result: dict[str, Any]) -> dict[str, Any]:
        await _write_scene_image(ctx, result["url"], "scene_sheet", "sheet_url", "sheet_versions")
        return result


_STILL_SYS = """你是分镜师。分镜图=一个镜头的**某一个定格画面**，一个镜头只出一张。

给你一整集按序排列的镜头，为每个镜头选出**唯一**那个定格瞬间：

1. 选取标准：这一瞬要能突出**本镜的关键画面或关键剧情走向**——是这个镜头存在的理由。
   不是随手取第一秒，也不是取最平淡的那一刻。
2. role 标记这个定格在镜头时间轴上的位置：
   - first=画面开始的那一刻（本镜靠"进入状态/建立关系"叙事时选它）
   - key=镜头中段的高潮瞬间（动作爆发、情绪转折、关键物件显露时选它）
   - last=画面收束的那一刻（本镜的意义在结果/反应上时选它）
3. moment 写**可定格的静态画面**：写得出"这一帧长什么样"。
   写动作的**顶点或凝固姿态**（"扳手悬在半空、手腕绷紧"），
   不要写过程（"正在转动扳手"），不要写因果结论（"表明了决心"）。
4. subject 写这一帧的画面主体（角色名或物件名）。
5. **相邻镜头的定格必须彼此不同**：连着几个镜头不得都选同一个人物的同一姿态；
   景别与主体要有变化，整集读下来像一组有节奏的分镜，而不是同一张图重复。
   同一场景内若相邻两镜的动作本就相近，就换主体或换景别来区分（一个给人物特写、
   一个给手部或物件特写、一个给关系中景），**严禁两条 moment 写成近乎同一句**。
6. **描述光线时只写光源与受光效果，绝不要把光写在人物五官上**：
   写"油灯从下方照亮他的下颌与眉骨，眼窝落进阴影"，
   **不要写"光在他脸上剧烈晃动""火光映在他眼里"**——这类写法会被作画理解成
   人物眼睛/瞳孔自己在发光，画出发光眼的怪物脸（实测顾临连续两版被画成发光红瞳）。

严格输出 JSON：
{"stills":[{"shot_no":1,"role":"first|key|last","subject":"画面主体","moment":"可定格的静态画面描述，30-60字"}]}"""


@register
class StillPromptsStep(Step):
    """分镜定格选取（2026-07-28）：整集一次 LLM 通读，为每镜选定唯一的分镜定格。

    分镜图是"镜头的某一个定格画面"，此前装配一律机械地取首切动作当定格，
    既未必是本镜的关键画面，相邻镜之间也容易撞成同一姿态。改为整集一次判断后，
    定格瞬间落 meta.storyboard_still，装配期覆盖首切口径，
    定格提示词随即走既有的九维质检与组图链路（不另起一套）。"""

    kind = "gen_stills"
    group = "分镜"
    manual = True
    timeout_s = 900
    gen_slot = "stills"
    before_notes = ["取本集全部分镜脚本（缺详细分镜先补）"]
    run_note = "整集一次 LLM 选定格：逐镜给出 role（首帧/尾帧/关键帧）+ 定格瞬间"
    next_notes = ["逐镜落 meta.storyboard_still；装配期覆盖首切定格，随后走九维质检"]

    async def before(self, ctx: Ctx) -> None:
        await _expand_pending_details(ctx)

    async def run(self, ctx: Ctx) -> RunResult:
        from .. import llm

        rows = await ctx.pool.fetch(
            "SELECT id,seq,summary,meta FROM content_nodes WHERE parent_id=$1 AND kind='shot' "
            "AND deleted_at IS NULL ORDER BY seq,id", ctx.node_id)
        if not rows:
            raise Blocked("本集尚无分镜")
        lines = []
        for r in rows:
            m = _meta(r)
            cuts = "｜".join(
                f"{c.get('scale', '')}·{c.get('subject', '')}·{c.get('action', '')}"
                for c in (m.get("cuts") or [])[:5])
            lines.append(
                f"- 镜{m.get('shot_no') or r['seq']}｜景别：{m.get('scale', '')}"
                f"｜情绪功能：{m.get('mood', '')}｜出场：{'、'.join(m.get('characters') or [])}\n"
                f"  画面：{(r['summary'] or '')[:160]}\n"
                f"  切：{cuts or '（无切）'}")
        data = await llm.chat_json(
            _STILL_SYS, "【本集镜头（按序）】\n" + "\n".join(lines), max_tokens=8000)
        by_no = {}
        for item in (data or {}).get("stills") or []:
            try:
                by_no[str(item.get("shot_no"))] = item
            except Exception:  # noqa: BLE001, S112
                continue
        picked = 0
        async with ctx.pool.acquire() as conn:
            for r in rows:
                m = _meta(r)
                item = by_no.get(str(m.get("shot_no"))) or by_no.get(str(r["seq"]))
                if not item or not (item.get("moment") or "").strip():
                    continue
                role = item.get("role") if item.get("role") in ("first", "key", "last") else "key"
                await conn.execute(
                    "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() "
                    "WHERE id=$1", r["id"],
                    json.dumps({"storyboard_still": {
                        "role": role,
                        "subject": (item.get("subject") or "").strip(),
                        "moment": item["moment"].strip(),
                        "at": flow.now_iso(),
                    }}, ensure_ascii=False))
                picked += 1
        return RunResult({"shots": len(rows), "picked": picked})


def _lock_line(lock: dict[str, Any]) -> str:
    """把一个场景的视觉硬锁渲染成一句中文（组图逐张段落用）"""
    parts = [f"{label}：{_lock_cn(key, lock[key])}"
             for key, label in _VISUAL_LOCKS if lock.get(key)]
    if lock.get("enclosure") == "interior":
        parts.append("封闭室内且屋顶完整，不得露出天空")
    elif lock.get("enclosure") == "exterior":
        parts.append("室外空间")
    return "；".join(parts)


def build_scene_sheets_group_prompt(scenes: list[dict[str, Any]], refs: list[dict[str, Any]],
                                    art_style: str = "", note: str = "") -> str:
    """纯函数：拼「整集场景图组图」提示词（可单测）。

    逐场景独立出图时，各场景的画风、材质表现与色彩基调会各自漂移——本集九个场景就是
    九次独立采样。改为一次组图后，N 张共享同一生成上下文，跨场景一致性从此有实物依据；
    各场景自己的时间/天气/光线由逐张段落里的硬锁分别钉住，不会互相污染。

    两阶段口径与单场景一致：scenes[i].empty_ref 指向该场景空场景基准图在参考池里的名字，
    逐张段落要求照搬它的空间与光线，本次只加人。"""

    head = [
        f"场景角色站位图组图：本次共生成 {len(scenes)} 张图，按下方场景编号顺序逐张输出、"
        "一一对应，禁止合并、跳过或调换顺序，每张只画对应编号场景描述的画面",
        "每张都是满幅完整连续的单幅电影画面，画面铺满整个图幅；"
        "每张的空间与光线照搬该场景段落指定的空场景基准图，本次只把角色放进去",
        "严禁宫格、拼图、分镜板、接触表、分割线、画中画、相框白边或同一画面的重复变体；"
        "不同场景之间不得合并到同一张图里",
    ]
    if refs:
        intro = "，".join(media.ref_intro_line(i, r, scope="group")
                          for i, r in enumerate(refs, start=1))
        head.append(intro + "。画面中出现的角色严格按其设定图还原面部特征、发型与服装；"
                    "设定图仅提供造型，角色在各张中的姿势、朝向与站位按该场景的站位描述重新塑造。"
                    "角色面部不是本组图的表现重点，避免五官正面特写与直视镜头")
    if art_style:
        head.append(f"项目固定画风与媒介（全部 {len(scenes)} 张必须完全统一）：{art_style}")
    head.append(
        f"全集统一性硬要求：这 {len(scenes)} 张同属一集，画风、媒介、材质表现、镜头语言与"
        "整体色彩基调必须完全一致；同一地点在多张中复现时，空间结构与陈设必须一致。"
        "各场景的时间段、天气与光线按其自己段落里的标注执行，按剧情顺序自然推进，"
        "严禁把某一场景的天气或光线扩散到其它场景")
    if (note or "").strip():
        head.append(note.strip())
    parts = ["。".join(h.rstrip("。") for h in head) + "。"
             + "画面中禁止出现任何文字、字幕、标注与水印, no text, no captions, no watermark."]
    name_to_no = media._ref_name_map(refs)
    for i, s in enumerate(scenes, start=1):
        seg = s.get("seg")
        body = [f"第{i}张【场景{seg}·{s.get('scene') or ''}】：{s.get('desc') or ''}"]
        if s.get("space"):
            body.append(f"空间布局：{s['space']}")
        if s.get("blocking"):
            body.append(f"角色站位：{s['blocking']}")
        line = _lock_line(s.get("lock") or {})
        if line:
            body.append(f"光线与氛围：{line}")
        # 批量=同一条两阶段流程跑 N 次：每张各自照搬自己那张空场景基准图，只加人。
        # 不能因为走了组图就退回"按文字重新塑造空间"——那正是要根治的漂移来源。
        if s.get("empty_ref"):
            body.append(f"空间与光线基准：严格照搬 @图片{name_to_no.get(s['empty_ref'], '?')}"
                        "（本场景的空场景基准图）的空间结构、陈设、机位、景别与光线，"
                        "不得改动、不得换机位、不得增删结构物；本张唯一新增的是角色")
        parts.append(media._resolve_ref_markers("。".join(x.rstrip("。") for x in body) + "。",
                                                name_to_no))
    return "\n".join(parts)


@register
class SceneSheetsGroupStep(Step):
    """整集场景图组图（2026-07-28）：把本集全部场景的空间与站位参考图**一次组图出齐**。

    跨场景一致性的唯一实物锚——逐场景独立生成时每张都是一次独立采样，画风与色调必然
    各自漂移；一次组图让 N 张共享生成上下文，之后每个场景的分镜只需对齐自己那张，
    跨场景一致性就自动继承下来。各场景的时间/天气/光线仍由各自的硬锁分别钉住。"""

    kind = "gen_scene_sheets_group"
    group = "生图"
    manual = True
    timeout_s = 1200
    max_retries = 0  # 整组重烧太贵，业务失败人工再点
    gen_slot = "scene_sheets_group"
    dep_kinds = ["gen_scene_empty"]
    before_notes = ["取章 meta.scene_blocking.groups（缺则先跑场景空间规划）",
                    "逐场景取最新连续性合同的视觉硬锁（时间/天气/光线/色板）",
                    "各场景空场景基准图优先占参考槽 + 本集角色设定图（参考数+生成数 ≤15）"]
    run_note = "一次组图出齐本集全部角色站位图（各自照搬自己的空场景基准图）→ OSS"
    next_notes = ["逐场景落章级附件 + 回写 groups[*].sheet_url（装配期自动挂进组内各镜参考池）"]

    async def missing_deps(self, conn: Any, project_id: int | None,
                           node_id: int | None, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """硬前置=每个目标场景的空场景基准图（逐场景一个 gen_scene_empty）。
        批量与单场景走同一条两阶段流程：先把空间钉死，再一次组图把人放进去。"""
        meta = await _node_meta_conn(conn, node_id)
        want = {int(s) for s in (payload.get("segs") or [])}
        force = bool(payload.get("force"))
        out = []
        for g in (meta.get("scene_blocking") or {}).get("groups") or []:
            seg = int(g.get("seg") or 0)
            if want and seg not in want:
                continue
            if not want and not force and g.get("sheet_url"):
                continue
            if not g.get("empty_url"):
                out.append({"kind": "gen_scene_empty", "node_id": node_id,
                            "payload": {"seg": seg}, "priority": 10})
        return out

    async def before(self, ctx: Ctx) -> None:
        row = await ctx.pool.fetchrow(
            "SELECT meta FROM content_nodes WHERE id=$1 AND kind='chapter'", ctx.node_id)
        if not row:
            raise Blocked("章节不存在")
        groups = (_meta(row).get("scene_blocking") or {}).get("groups") or []
        if not groups:
            raise Blocked("本集尚无场景分组——请先运行场景空间规划")
        want = {int(s) for s in (ctx.payload.get("segs") or [])}
        force = bool(ctx.payload.get("force"))
        targets = [g for g in groups
                   if (not want or int(g.get("seg") or 0) in want)
                   and (force or want or not g.get("sheet_url"))]
        if not targets:
            raise Blocked("本集场景图已全部生成——如需重出请指定场景或勾选强制重出")

        # 逐场景取最新合同的视觉硬锁：同一次组图里各场景的时间/天气/光线各自独立
        locks: dict[int, dict[str, Any]] = {}
        for r in await ctx.pool.fetch(
            "SELECT ns.seq AS seg, c.hard_locks FROM narrative_scenes ns "
            "JOIN LATERAL (SELECT hard_locks FROM scene_continuity_contracts "
            "  WHERE narrative_scene_id=ns.id ORDER BY version DESC LIMIT 1) c ON true "
            "WHERE ns.chapter_id=$1", ctx.node_id,
        ):
            raw = r["hard_locks"]
            locks[int(r["seg"] or 0)] = raw if isinstance(raw, dict) else json.loads(raw or "{}")

        # 场景图里会把角色画进去 → 先保证出场角色的档案与设定图都在。
        # 缺了就只能靠文字硬撑，模型自由发挥出的造型还会被后续分镜"一致地"继承。
        segs = {int(g.get("seg") or 0) for g in targets}
        eids = [r["id"] for r in await ctx.pool.fetch(
            "SELECT DISTINCT e.id FROM content_nodes n "
            "CROSS JOIN LATERAL jsonb_array_elements_text("
            "  coalesce(n.meta->'element_ids','[]'::jsonb)) AS x(eid) "
            "JOIN content_elements e ON e.id = x.eid::bigint "
            "WHERE n.parent_id=$1 AND n.kind='shot' AND n.deleted_at IS NULL "
            "AND coalesce((n.meta->>'scene_seg')::int,1) = ANY($2::int[]) "
            "AND e.kind IN ('character','item')", ctx.node_id, list(segs))]
        if eids:
            await ensure_element_assets(ctx, eids)
            row = await ctx.pool.fetchrow(
                "SELECT meta FROM content_nodes WHERE id=$1", ctx.node_id)
            groups = (_meta(row).get("scene_blocking") or {}).get("groups") or []
            by_seg = {int(g.get("seg") or 0): g for g in groups}
            targets = [by_seg.get(int(t.get("seg") or 0)) or t for t in targets]

        scenes, refs, seen = [], [], set()
        # 各场景的空场景基准图先进参考池（每场景一张，逐张段落按名引用它）。
        # 它们是本组图的空间真值，必须优先占槽——角色图挤掉了还能靠文字撑，
        # 基准图挤掉了这一批就退回"按文字重新塑造空间"的老毛病。
        for g in targets:
            url = g.get("empty_url")
            name = f"场景{int(g.get('seg') or 0)}空场景基准图"
            if url and name not in seen:
                seen.add(name)
                refs.append({"name": name, "kind": "scene_empty", "url": url})
        for g in targets:
            seg = int(g.get("seg") or 0)
            anchors = g.get("anchors") or {}
            empty_name = f"场景{seg}空场景基准图"
            scenes.append({
                "seg": seg, "scene": g.get("scene"),
                "desc": g.get("sheet_desc") or g.get("scene") or "",
                "space": g.get("space"),
                "blocking": "；".join(f"「{k}」{v}" for k, v in anchors.items() if v),
                "lock": locks.get(seg) or {},
                "empty_ref": empty_name if g.get("empty_url") else "",
            })
            # 参考池 = 各场景站位参考里的角色设定图并集（站位图本身不作参考，正在出的就是它）。
            # 按 name 去重而不是按 url：同一角色的设定图重出过就会有多个 URL 版本，
            # 按 url 去重会让同一个人占掉两个参考槽（实测阿砚占了 2 槽）。
            for ref in g.get("sheet_refs") or []:
                url, name = ref.get("url"), ref.get("name")
                if not url or ref.get("kind") in ("scene_sheet", "scene_empty") or name in seen:
                    continue
                seen.add(name)
                refs.append({"name": name, "kind": ref.get("kind"), "url": url})
        # 刚补出的设定图不在场景规划期快照的 sheet_refs 里，按要素当前图补进参考池
        # （取图统一走 effective_meta，多形态按本组场景描述/站位语料选形态）
        fresh = await ctx.pool.fetch(
            "SELECT name, kind, meta FROM content_elements WHERE id = ANY($1::bigint[])",
            [int(x) for x in eids]) if eids else []
        _corpus = " ".join(f"{s.get('desc') or ''} {s.get('blocking') or ''}" for s in scenes)
        for r in fresh:
            em = ev.effective_meta(_meta(r), _corpus)
            if not em.get("sheet_url") or r["name"] in seen:
                continue
            seen.add(r["name"])
            refs.append({"name": r["name"], "kind": r["kind"], "url": em["sheet_url"]})
        # 参考图 + 生成数合计 ≤15（Seedream 组图硬上限）
        ctx.payload["scenes"] = scenes
        ctx.payload["refs"] = refs[:max(0, 15 - len(scenes))]
        if not ctx.payload.get("size"):
            ctx.payload["size"] = await _frame_size(ctx, chapter_id=ctx.node_id)
        log.info("场景组图任务 %s：%d 个场景，参考池 %d 张", ctx.task_id, len(scenes),
                 len(ctx.payload["refs"]))

    async def run(self, ctx: Ctx) -> RunResult:
        row = await ctx.pool.fetchrow("SELECT seq,title FROM content_nodes WHERE id=$1", ctx.node_id)
        token = media.GEN_AUDIT.set({
            "project_id": ctx.project_id, "node_id": ctx.node_id, "task_id": ctx.task_id,
            "chapter_id": ctx.node_id, "chapter_title": row["title"] if row else None,
            "kind": self.kind,
            "source": f"project_{ctx.project_id}_{row['seq'] if row else ctx.node_id}_scene_group",
        })
        try:
            scenes = ctx.payload["scenes"]
            refs = ctx.payload.get("refs") or []
            project = await ctx.pool.fetchrow(
                "SELECT * FROM content_projects WHERE id=$1", ctx.project_id)
            project = await volumes.effective_for_chapter(ctx.pool, project, ctx.node_id)
            prompt = build_scene_sheets_group_prompt(
                scenes, refs, (project["art_style"] if project else "") or "",
                ctx.payload.get("note") or "")
            urls = await media.generate_image_group(
                prompt, count=len(scenes), size=ctx.payload.get("size"),
                reference_images=[r["url"] for r in refs] or None,
                store_prefix="scene_sheet")
        finally:
            media.GEN_AUDIT.reset(token)
        return RunResult({"urls": urls, "prompt": prompt})

    async def next(self, ctx: Ctx, result: dict[str, Any]) -> dict[str, Any]:
        scenes = ctx.payload["scenes"]
        urls = result.get("urls") or []
        # 同 GenSceneSheetStep：读改写 groups 数组必须在事务内，否则与并发落库的
        # 单场景出图/空间规划互相全量覆盖（FOR UPDATE 在自动提交下不跨语句持锁）
        async with ctx.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT meta FROM content_nodes WHERE id=$1 FOR UPDATE", ctx.node_id)
            sb = (_meta(row).get("scene_blocking") or {}) if row else {}
            by_seg = {int(g.get("seg") or 0): g for g in (sb.get("groups") or [])}
            for s, url in zip(scenes, urls):
                seg = int(s.get("seg") or 0)
                await conn.execute(
                    "INSERT INTO content_attachments (project_id, node_id, kind, url, meta) "
                    "VALUES ($1,$2,'image',$3,$4::jsonb)",
                    ctx.project_id, ctx.node_id, url,
                    json.dumps({"type": "scene_sheet", "seg": seg,
                                "group_task": ctx.task_id}, ensure_ascii=False))
                g = by_seg.get(seg)
                if not g:
                    continue
                _rotate_group_image(g, url, "sheet_url", "sheet_versions", ctx.task_id)
            await conn.execute(
                "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
                ctx.node_id, json.dumps({"scene_blocking": sb}, ensure_ascii=False))
        out: dict[str, Any] = {"generated": len(urls), "expected": len(scenes)}
        if len(urls) < len(scenes):  # 模型少生：后面的场景留空，可再点补齐
            out["missing_segs"] = [s.get("seg") for s in scenes[len(urls):]]
        return out


@register
class OverviewGridStep(Step):
    """章级分镜总览宫格故事板（一集多张，3:2）：一次生成的多格共享造型与空间逻辑
    →约束镜头间连贯。不裁切（裁错是静默错）：每镜只记 storyboard_ref（第几张第几格+整图 URL），
    「按本张出图」批量首帧时整图作参考 + 固定引用句定位到格。
    2026-07-12 起仅手动触发（总图效果不佳，拆镜后不再自动串出，也不再串 gen_prompts——
    详细分镜与提示词链由 expand_shot_details 负责）；before 仍幂等补详细分镜兜底。
    payload.board=N 只重出第 N 张（分镜图画布内单张重出，其余张不动）；
    payload.prompt 覆盖该张的装配提示词（画布里人工/AI 改过的正文，模板前言仍由 run 拼接）。"""

    kind = "gen_overview_grid"
    group = "草图"
    manual = True
    before_notes = ["幂等补详细分镜兜底（detail_pending）"]
    run_note = "章级分镜总览宫格（一集多张 3:2，模板预渲染格线/镜号）→ OSS"
    next_notes = ["落附件 + 每镜记 storyboard_ref（第几张第几格）+ 章 meta 总览"]
    gen_slot = "overview_grid"
    timeout_s = 1200  # 可能含按板 LLM 详细展开兜底（N/16 次），比纯出图更重

    async def before(self, ctx: Ctx) -> None:
        await _expand_pending_details(ctx)

    async def run(self, ctx: Ctx) -> RunResult:
        from .overview_grid import PAGE_SIZE, assemble_overview_boards, render_grid_template

        all_boards = await assemble_overview_boards(ctx.pool, ctx.project_id, ctx.node_id)
        # 本章总镜数按整章算：单张重出时 next 仍要写对每镜 storyboard_ref.total
        total = sum(len(b["shot_ids"]) for b in all_boards)
        only = ctx.payload.get("board")
        boards = [b for b in all_boards if b["no"] == int(only)] if only is not None else all_boards
        if not boards:
            raise ValueError(f"第{only}张宫格不存在（本章共{len(all_boards)}张）")
        override = (ctx.payload.get("prompt") or "").strip()
        if override and len(boards) == 1:
            boards[0]["prompt"] = override
        for b in boards:
            # 模板方案（彩色版 2026-07-12 定稿）：格线/中央定位镜号/留空格由代码预渲染成模板——
            # 分割线是唯一不得重绘的结构；中央镜号只作定位提示，作画时被覆盖（成图无数字）
            tpl = render_grid_template(b["rows"], b["cols"], b["shot_nos"])
            tpl_url = await store_bytes(tpl, "storyboard_tpl", ".png")
            prompt, refs = b["prompt"], []
            if tpl_url:
                elem_refs = b.get("element_refs") or []
                intro_bits = [media.ref_intro_line(i, r, scope="group")
                              for i, r in enumerate(elem_refs, start=2)]
                prompt = (
                    "图片1是本页分镜宫格模板：绿色底板与宽分割线、尾部纯绿留空格已预先画好；"
                    "每个白色格子中央有一个浅绿色数字，仅用于标注该格对应的镜号——"
                    "作画时**用画面完全覆盖这些数字，成图中不得残留任何数字**。"
                    "**绿色宽分割线是唯一不得重绘、移动或变色的结构**；纯绿留空格保持纯绿不作画。"
                    + ("，".join(intro_bits) + "。出场角色的造型与服色严格按对应设定图还原，"
                       "场景外观按场景设定图还原。" if intro_bits else "")
                    + "在每个白色格子内画出对应镜号的全彩故事板画面。"
                ) + prompt
                refs = [tpl_url] + [r["url"] for r in elem_refs]
                b["template_url"] = tpl_url
            token = media.GEN_AUDIT.set({
                "project_id": ctx.project_id, "node_id": ctx.node_id, "task_id": ctx.task_id,
                "kind": self.kind,
                "source": f"project_{ctx.project_id}_node_{ctx.node_id}_overview",
            })
            try:
                b["url"] = await media.generate_image(
                    prompt, size=PAGE_SIZE, reference_images=refs[:4] or None,
                    store_prefix="storyboard", profile_id=ctx.payload.get("model_profile_id"),
                    feature_code="storyboard_grid")
            finally:
                media.GEN_AUDIT.reset(token)
        return RunResult({"boards": boards, "total": total})

    async def next(self, ctx: Ctx, result: dict[str, Any]) -> dict[str, Any]:
        boards = result["boards"]
        # 本章总镜数（shot_no 已是字符串，不可 max）：单张重出时取 run 记下的整章数
        total = result.get("total") or sum(len(b["shot_ids"]) for b in boards)
        for b in boards:
            await ctx.pool.execute(
                "INSERT INTO content_attachments (project_id, node_id, kind, url, meta) "
                "VALUES ($1,$2,'storyboard_image',$3,$4::jsonb)",
                ctx.project_id, ctx.node_id, b["url"],
                json.dumps({"board": b["no"], "prompt": b["prompt"],
                            "template_url": b.get("template_url")}, ensure_ascii=False),
            )
            # 每镜记 storyboard_ref（自足去范式化：首帧引用句/前端展示都不用再查章节点）
            for idx, sid in enumerate(b["shot_ids"]):
                row, col = divmod(idx, b["cols"])
                ref = {
                    "board": b["no"], "panel": idx + 1, "row": row + 1, "col": col + 1,
                    "rows": b["rows"], "cols": b["cols"], "url": b["url"],
                    "first_no": b["shot_nos"][0], "last_no": b["shot_nos"][-1], "total": total,
                }
                await ctx.pool.execute(
                    "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
                    sid, json.dumps({"storyboard_ref": ref}, ensure_ascii=False),
                )
        # prompt 一并落章 meta：前端总览辅助区展示（人审草图时对照提示词）。
        # 单张重出（payload.board）只替换该张条目，其余张沿用旧总览——否则整章总览会被抹成一张
        fresh = [{k: b[k] for k in ("no", "url", "rows", "cols", "shot_nos", "scenes", "prompt")}
                 for b in boards]
        merged = fresh
        if ctx.payload.get("board") is not None:
            row = await ctx.pool.fetchrow(
                "SELECT meta FROM content_nodes WHERE id=$1", ctx.node_id)
            prev = (_meta(row).get("storyboard_overview") or {}) if row else {}
            kept = [b for b in (prev.get("boards") or []) if b.get("no") not in {f["no"] for f in fresh}]
            merged = sorted(kept + fresh, key=lambda b: b.get("no") or 0)
        overview = {"boards": merged, "at": flow.now_iso()}
        await ctx.pool.execute(
            "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
            ctx.node_id, json.dumps({"storyboard_overview": overview}, ensure_ascii=False),
        )
        # 不再串 gen_prompts（2026-07-12）：提示词链归 expand_shot_details，
        # 宫格图只是可选的人审/构图参考资产，重出图不应重烧整章提示词
        return {"boards": len(boards), "shots": total}


@register
class KeyframeStep(Step):
    """彩色首帧关键帧：I2V 首帧锚定画风与构图。角色一致性根治=设定图作参考图传入生图
    +「图片N是…」引用句（镜22 实测：纯文本路径角色必漂）。"""

    kind = "gen_keyframe"
    group = "生图"
    dep_kinds = ["gen_prompts"]
    soft_deps = ["gen_element_sheet"]  # before 补设定图（_ensure_element_sheets，不建独立任务）
    # 下标被 production_canvas._CHAIN_NODES/_CHAIN_ORDER 引用（guard:i），只改文案别动顺序；
    # 编排画布的展示顺序按 _CHAIN_ORDER 重排（生产逻辑顺序），这里保持执行顺序语义
    before_notes = [
        "缺首帧提示词 → 派 gen_prompts（依赖）",
        "连续性守卫：连续性记录未就绪则 Blocked",
        "取本镜出场要素：已列全直接取用；缺则模型按正文补建入库（缓存）",
        "场景站位兜底：所在场景组缺站位链 → 先空间规划（缓存，失败不阻塞）",
        "补要素设定图：外貌指纹失配则重生成（画风/身份锚点）",
        "重装配参考图 + 短引用（指向要素最新设定图）",
        "提示词九维质检（缓存 72h 命中即零成本）",
        "wide 景别软化 + 故事板参考挂载 + 角色硬闸（未点名不传图）",
    ]
    run_note = "生图：设定图作参考图传入 +「图片N 是…」引用句（角色一致性根治）→ OSS"
    next_notes = ["落附件 + 回写 keyframe_url", "link_prev 连贯 → 回填上一镜尾帧（接缝帧，跨镜无缝）"]
    gen_slot = "keyframe"
    timeout_s = 600

    async def missing_deps(self, conn: Any, project_id: int | None,
                           node_id: int | None, payload: dict[str, Any]) -> list[dict[str, Any]]:
        # 前置=首帧提示词。缺则派发整镜 gen_prompts（不用 only=image：依赖去重会把
        # 视频链与首帧链合并到同一个 gen_prompts 任务，必须两套提示词都产出）
        if payload.get("prompt") or payload.get("prompt_overridden"):
            return []
        meta = await _node_meta_conn(conn, node_id)
        if meta.get("image_prompt"):
            return []
        return [{"kind": "gen_prompts", "payload": {}, "priority": 10}]

    async def before(self, ctx: Ctx) -> None:
        meta = await _shot_gen_before(ctx, self.kind)
        # 业务层只声明画幅比例，像素由当前图片 provider 适配。
        if not ctx.payload.get("aspect_ratio"):
            ctx.payload["aspect_ratio"] = await _frame_aspect_ratio(ctx)
        # 首帧生效景别为 wide（全景/远景/大远景）→ run 侧软化设定图指令并把场景图排前：
        # 角色特写设定图+"严格还原面部"会把人群/远景镜的主体抢成主角特写（第3章镜4实测）
        _fc = (meta.get("cuts") or [{}])[0]
        ctx.payload["wide_frame"] = (_fc.get("scale") or meta.get("scale", "")) in ("全景", "远景", "大远景")
        # 参考图按目标独立关联：首帧停用名单里的要素不上传设定图（用户逐镜管理）
        off = _refs_off(meta, "image")
        ctx.payload["reference_images"] = [
            r for r in (ctx.payload.get("reference_images") or []) if r.get("name") not in off
        ]
        # 宫格故事板整图 → 构图参考（软约束，不裁切）：**仅显式要求时挂载**
        # （use_storyboard=按板批量出图端点传入；2026-07-12 起普通首帧生成不再自动挂）。
        # 身份设定图优先（占前3槽），故事板整图固定占末位（seedream 最多 4 张参考图，
        # 身份一致性 > 构图一致性）。固定引用句在此装配，run 拼进提示词
        ref = (meta.get("storyboard_ref") or {}) if ctx.payload.get("use_storyboard") else {}
        refs = ctx.payload.get("reference_images") or []
        if ref.get("url") and "故事板" not in off and all(r.get("url") != ref["url"] for r in refs):
            ctx.payload["reference_images"] = refs[:3] + [{
                "name": f"第{ref.get('board')}张·镜{ref.get('first_no')}-{ref.get('last_no')}",
                "kind": "storyboard", "url": ref["url"],
            }]
            shot_no = meta.get("shot_no")
            # 前后镜衔接提示仅对整数镜号（拆镜镜）计算；手动插入镜的小数号跳过邻镜提示（仍给格位引用）
            if isinstance(shot_no, int) and all(ref.get(k) for k in ("panel", "row", "col", "rows", "cols")):
                neighbors = [n for n in (shot_no - 1, shot_no + 1)
                             if 1 <= n <= (ref.get("total") or 0)]
                ctx.payload["storyboard_ref_text"] = (
                    f"该故事板为{ref['rows']}行×{ref['cols']}列宫格，"
                    f"依次为镜{ref.get('first_no')}至镜{ref.get('last_no')}。"
                    f"请参考故事板中第{ref['panel']}格（第{ref['row']}行第{ref['col']}列，镜{shot_no}）"
                    "生成本镜画面——沿用该格的构图、景别与人物站位"
                    + (f"；请注意与前后分镜（{'、'.join(f'镜{n}' for n in neighbors)}）的画面衔接连贯"
                       if neighbors else "")
                    + "。故事板仅供构图与站位参考，成图的画风与细节以下文画风描述为准，"
                    "忽略故事板中的绿色分割线。"
                )

    async def run(self, ctx: Ctx) -> RunResult:
        # 首帧生图审计（用户 2026-07-14：图片生成也进 gen_logs，source 按分镜可筛）
        token = media.GEN_AUDIT.set(await _shot_audit_ctx(ctx, self.kind, "image"))
        try:
            return await self._run_gen(ctx)
        finally:
            media.GEN_AUDIT.reset(token)

    async def _run_gen(self, ctx: Ctx) -> RunResult:
        refs = _drop_unmentioned_chars(ctx.payload.get("prompt") or "",
                                       ctx.payload.get("reference_images") or [],
                                       f"镜 {ctx.node_id} {self.kind}")
        wide = bool(ctx.payload.get("wide_frame"))
        if wide:
            # wide 镜：场景图>多景别空间图>故事板>角色图——角色特写设定图排前会把远景主体抢成主角特写
            order = {"scene": 0, "scene_sheet": 1, "storyboard": 2}
            refs = sorted(refs, key=lambda r: order.get(r.get("kind"), 3))
        # 预览动作帧是“本镜怎么演、怎么构图”的证据，必须保留在 4 图上限内；
        # 角色/场景设定图仍按原顺序锁定身份和画风，动作帧固定占最后一槽。
        refs = media._cap_reference_images(refs, 4)
        kf_prompt = ctx.payload["prompt"]
        # 正文里的 @设定图[名] 引用按实际传图解析为 @图片N；未传图（停用/超4张/降级）的
        # 名字降级为「名」设定图普通文字，引用永不落空
        name_to_no = media._ref_name_map(refs[:4])
        kf_prompt = media._resolve_ref_markers(kf_prompt, name_to_no)
        if refs:
            intro = "，".join(media.ref_intro_line(i, r)
                              for i, r in enumerate(refs[:4], start=1))
            # 防机械拼贴（用户 2026-07-14 实测回归）：设定图是半身/特写立绘，只说"按图还原"
            # 会把设定图的姿势与景别整体照搬进场景——必须显式限定"只取造型，不取构图"
            rules = ("角色设定图仅供远距离辨识（服色/体型/生物形态轮廓）：本镜为远景/全景，"
                     "人物是画面中的小比例身影，严禁将任何角色放大为主体或刻画面部细节；场景外观按场景设定图还原。"
                     if wide else
                     "严格按设定图还原对应角色的面部特征、发型与服装及场景外观；"
                     "设定图仅提供长相与服饰造型，画面中角色的姿势、动作、朝向、表情与景别"
                     "必须完全按下文画面描述与动作瞬间重新塑造，"
                     "严禁照搬设定图中的站姿、半身特写或直视镜头的构图。")
            if any(r.get("kind") == "scene_sheet" for r in refs[:4]):
                rules += ("场景空间与站位参考图交代本场景的空间布局、角色站位与光线——空间结构与人物位置"
                          "以其为准；本镜的构图、景别与画风按下文画面描述执行。")
            if any(r.get("kind") == "storyboard" for r in refs[:4]):
                rules += ctx.payload.get("storyboard_ref_text") or (
                    "故事板仅用于参考本镜的构图、景别与人物站位，"
                    "成图的画风与细节以下文画风描述为准，忽略故事板中的绿色分割线。")
            if any(r.get("kind") == "preview_action" for r in refs[:4]):
                rules += (
                    "动作构图参考帧只用于本镜姿势、动作、朝向、构图与空间关系；"
                    "角色身份、服饰、伤势、武器及场景风格仍以角色/场景设定图和下文剧情描述为准。"
                )
            kf_prompt = f"{intro}。{rules}{kf_prompt}"
        url = await media.generate_image(
            kf_prompt, size=ctx.payload.get("size"), aspect_ratio=ctx.payload.get("aspect_ratio"),
            reference_images=[r["url"] for r in refs[:4]] or None,
            store_prefix="keyframe",  # OSS 转存内置：审计日志记录的即是永久 URL
            profile_id=ctx.payload.get("model_profile_id"),
            feature_code="keyframe",
        )
        return RunResult({"url": url})

    async def next(self, ctx: Ctx, result: dict[str, Any]) -> dict[str, Any]:
        async with ctx.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO content_attachments (project_id, node_id, kind, url, meta) "
                "VALUES ($1,$2,'image',$3,$4::jsonb)",
                ctx.project_id, ctx.node_id, result["url"],
                json.dumps({"prompt": ctx.payload["prompt"], "type": "keyframe"}, ensure_ascii=False),
            )
            # keyframe_source：区分「生成」与「从上一镜视频抽取」（api/shots.py frame_from_neighbor）
            await conn.execute(
                "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
                ctx.node_id, json.dumps({"keyframe_url": result["url"],
                                         "keyframe_source": "gen"}, ensure_ascii=False),
            )
            await _backfill_seam_for(conn, ctx.node_id, result["url"])
        return result


async def _backfill_seam_for(conn: Any, shot_id: int | None, url: str) -> None:
    """接缝帧共用（跨镜连贯，2026-07-14）：本镜 link_prev=连贯 → 本镜首帧就是两镜接缝，
    自动回填为上一镜的尾帧——上一镜视频收束于此、本镜视频从此起步，像素级无缝。
    只写空位或刷新旧接缝帧（source=next_keyframe）；用户手动生成/抽帧的尾帧不覆盖。
    （模块级共用：单镜 KeyframeStep 与整页组图 KeyframeGroupStep 都走这里。）"""
    shot = await conn.fetchrow(
        "SELECT parent_id, seq, meta FROM content_nodes WHERE id=$1 AND kind='shot'", shot_id)
    if not shot or not _meta(shot).get("link_prev"):
        return
    prev = await conn.fetchrow(
        "SELECT id, meta FROM content_nodes WHERE parent_id=$1 AND kind='shot' AND seq<$2 "
        "AND deleted_at IS NULL ORDER BY seq DESC LIMIT 1", shot["parent_id"], shot["seq"])
    if not prev:
        return
    pm = _meta(prev)
    if pm.get("last_frame_url") and pm.get("last_frame_source") not in (None, "next_keyframe"):
        return  # 用户手动生成（gen）或抽帧（next_video）的尾帧优先，不动
    await conn.execute(
        "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
        prev["id"], json.dumps({"last_frame_url": url,
                                "last_frame_source": "next_keyframe"}, ensure_ascii=False),
    )
    log.info("镜 %s 首帧作为接缝帧回填上一镜 %s 的尾帧（link_prev=连贯）", shot_id, prev["id"])


def build_group_keyframe_prompt(shots: list[dict[str, Any]], refs: list[dict[str, Any]],
                                note: str = "", scene_lock: dict[str, Any] | None = None) -> str:
    """纯函数：拼组图提示词（可单测）。结构=组图规则 → 设定图引用+造型约束 →
    用户全局要求（弹框可编辑，一致性句在此）→ 逐镜编号段（每段=该镜首帧提示词，
    @设定图[名] 已按本次实际传图解析为 @图片N）。"""
    name_to_no = media._ref_name_map(refs)
    head = [
        f"分镜首帧组图：本次共生成 {len(shots)} 张图，按下方镜头编号顺序逐张输出、一一对应，"
        "禁止合并、跳过或调换顺序，每张只画对应编号镜头描述的画面",
        # 实测回归（2026-07-17 proj10 ch296）：组图模式下模型偶尔把单张当「相册照片」
        # 处理，画面外圈加白色相框边——必须显式禁掉
        "每张图都是满幅电影画面，画面铺满整个图幅，严禁白边、相框、拼贴边框或拍立得效果",
    ]
    if refs:
        # 接缝帧紧跟其后另有专门的继承规则句
        intro = "，".join(media.ref_intro_line(i, r, scope="group")
                          for i, r in enumerate(refs, start=1))
        head.append(intro + "。严格按设定图还原对应角色的面部特征、发型与服装及场景外观；"
                    "设定图仅提供长相与造型，各张画面中角色的姿势、动作、朝向与景别"
                    "以对应镜头描述为准，严禁照搬设定图构图")
        # 定格描述里的"油灯的光在他脸上剧烈晃动"被模型理解成了眼睛发光，
        # 顾临因此在两张里长出橙红发光瞳孔——环境光打在脸上不等于人物自己在发光
        head.append(
            "画面中的光一律来自环境光源（天光、灯火、闪电等），照亮人物只表现为受光面、"
            "阴影与轮廓光；**除非该角色的设定图本身就画着发光特征，否则人物的眼睛、瞳孔、"
            "面部与皮肤一律不得自发光，不得出现发光眼、光束眼或面部光效**")
        seam_nos = [i for i, r in enumerate(refs, start=1)
                    if r.get("kind") == "continuity_frame"]
        if seam_nos:
            head.append(
                f"图片{seam_nos[0]}是同一场景上一批最后镜头的视觉接缝帧："
                "严格继承其曝光、白平衡、主光方向、阴影方向、空间材质与建筑封闭状态；"
                "只继承视觉状态，不照搬人物动作、站位、景别或构图"
            )
    lock = scene_lock or {}
    if lock:
        lock_parts = [
            f"场景组{lock.get('scene_seg')}",
            f"地点：{lock.get('scene')}" if lock.get("scene") else "",
            f"空间拓扑：{lock.get('architectural_topology')}" if lock.get("architectural_topology") else "",
            *(f"{label}：{_lock_cn(key, lock[key])}"
              for key, label in _VISUAL_LOCKS if lock.get(key)),
        ]
        if lock.get("enclosure") == "interior":
            lock_parts.append("封闭室内且屋顶完整；不得改成露天、庭院或直接露出天空和雷云")
        elif lock.get("enclosure") == "exterior":
            lock_parts.append("室外空间；不得擅自改成室内")
        head.append("同场景连续性硬锁（整组每一张都必须一致）：" + "；".join(x for x in lock_parts if x))
    if (note or "").strip():
        head.append(note.strip())
    parts = ["。".join(h.rstrip("。") for h in head) + "。"]
    for i, s in enumerate(shots, start=1):
        body = media._resolve_ref_markers(s.get("prompt") or "", name_to_no)
        parts.append(f"第{i}张【镜{s.get('shot_no')}】：{body}")
    return "\n".join(parts)


@register
class KeyframeGroupStep(Step):
    """整页分镜首帧·组图（Seedream sequential_image_generation，2026-07-17）：
    一次请求按镜号顺序生成 N 张首帧——组内共享生成上下文，角色/场景/画风/光线一致性
    远优于逐镜独立采样（治「同一场景镜1正午、镜2黄昏」式跨镜漂移）。
    节点=章；payload.shot_ids=目标镜（缺首帧的，镜号序）、refs=弹框勾选的要素设定图、
    note=弹框全局要求（一致性约束句，用户可编辑）。参考图+生成数合计 ≤15（Seedream 硬上限）。"""

    kind = "gen_keyframes_group"
    group = "生图"
    dep_kinds = ["gen_prompts", "gen_scene_sheets_group"]
    manual = True  # 仅总览「批量首帧」弹框触发，不进自动链
    before_notes = [
        "缺首帧提示词的镜 → 逐镜派 gen_prompts 子任务（依赖挂对应镜节点）",
        "复核目标镜仍存在且有提示词（重拆/软删的镜剔除；全空 Blocked）",
    ]
    run_note = "组图生图：组图规则+设定图引用+逐镜编号提示词 → 一次出 N 张 → OSS"
    next_notes = ["按序逐镜落附件 + 回写 keyframe_url（少生的镜留空可再批）",
                  "link_prev 连贯镜回填上一镜尾帧（接缝帧，与单镜同一逻辑）"]
    gen_slot = "keyframes_group"
    # 一次 N 张渲染远慢于单图；before 还可能补要素档案与设定图（每个缺图角色一次生图），
    # 且组图对供应商串行发起、前面可能排着别的组图——900s 实测会在补图那步被掐断。
    timeout_s = 2400
    max_retries = 0   # 整组重烧太贵：HTTP 级抖动 media 层已自动重试，业务失败人工再点

    async def missing_deps(self, conn: Any, project_id: int | None,
                           node_id: int | None, payload: dict[str, Any]) -> list[dict[str, Any]]:
        # 依赖 DAG 跨节点派发：组图任务挂章节点。没有提示词，或首帧质检未通过/
        # 已过期的镜，逐个挂对应镜节点重装配并质检。图像组图成本高，不能仅凭“字段非空”
        # 绕过质检门禁。
        out: list[dict[str, Any]] = []
        # 场景图软前置：本组场景缺空间站位图就先派整集场景组图补齐。它是组内每张的
        # 空间/光线主锚，也是跨场景一致性的唯一实物依据——缺它整组只能靠文字硬撑。
        if node_id:
            meta = await _node_meta_conn(conn, node_id)
            segs = set()
            for sid in payload.get("shot_ids") or []:
                sm = await _node_meta_conn(conn, sid)
                segs.add(int(sm.get("scene_seg") or 1))
            groups = (meta.get("scene_blocking") or {}).get("groups") or []
            missing = [int(g.get("seg") or 0) for g in groups
                       if int(g.get("seg") or 0) in segs and not g.get("sheet_url")]
            if missing:
                out.append({"kind": "gen_scene_sheets_group", "node_id": node_id,
                            "payload": {"segs": missing}, "priority": 8})
        for sid in payload.get("shot_ids") or []:
            meta = await _node_meta_conn(conn, sid)
            prompt = meta.get("image_prompt") if meta else None
            review = meta.get("prompt_review_image") if meta else None
            if meta and (
                not prompt
                or not isinstance(review, dict)
                or not review.get("合格")
                or not flow.cache_valid(review, prompt)
            ):
                out.append({
                    "kind": "gen_prompts",
                    "node_id": sid,
                    "payload": {"only": "image"},
                    "priority": 5,
                })
        return out

    async def before(self, ctx: Ctx) -> None:
        from .continuity_records import assert_shot_generation_ready

        rows = await ctx.pool.fetch(
            "SELECT id,parent_id,seq,meta FROM content_nodes "
            "WHERE id = ANY($1::bigint[]) AND kind='shot' "
            "AND deleted_at IS NULL ORDER BY seq,id", ctx.payload.get("shot_ids") or [])
        # 组图链路此前从不补要素设定图：单镜 gen_keyframe 走 _shot_gen_before 会补，
        # 而组图的依赖只有 gen_prompts，这条链上没有这一步——本集的龙「砾光」因此
        # 全程无设定图，24 张里每一张的龙都是模型现编的（前几镜深青带蓝晶纹，
        # 后几镜变成白色）。身份资产必须在出图前保证，和单镜同一口径。
        all_eids: list[Any] = []
        for r in rows:
            all_eids += (_meta(r).get("element_ids") or [])
        if all_eids:
            await ensure_element_assets(ctx, list(dict.fromkeys(all_eids)))

        shots, skipped = [], []
        scene_keys: set[tuple[int, int | None]] = set()
        # 组图参考池在这里（依赖跑完后）从各镜 meta 现读，不能沿用入队快照：入队时缺提示词的
        # 镜还没有 reference_images，前端只能报空，等 gen_prompts 补完也不会回填 payload——
        # 整组就零角色/场景参考出图，提示词里「以『岚音』设定图为准」却一张图都没传，
        # 成图自然不是本剧角色（实测镜9/13）。这里只刷参考池，不重装配提示词：
        # 提示词与它的九维质检是配套的（指纹=提示词全文），重装配会让缓存失效并把
        # 质检环节的重构结果冲掉。
        assembled: list[dict[str, Any]] = []
        fresh_refs: list[dict[str, Any]] = []   # 按要素当前设定图补的锚（治装配期快照过期）
        for r in rows:
            m = _meta(r)
            scene_keys.add((
                int(m.get("scene_seg") or 1),
                (m.get("continuity") or {}).get("scene_contract_id"),
            ))
            try:
                await assert_shot_generation_ready(ctx.pool, r["id"])
            except ValueError as e:
                raise Blocked(f"镜{m.get('shot_no') or r['id']}：{e}") from e
            prompt = m.get("image_prompt")
            review = m.get("prompt_review_image")
            if (
                not prompt
                or not isinstance(review, dict)
                or not review.get("合格")
                or not flow.cache_valid(review, prompt)
            ):
                # 与"个别镜无提示词就跳过"同一口径：单镜质检未过只剔除这一镜，
                # 不拖死整批——一批 6 镜里坏 1 镜就整批 Blocked，等于让用户反复重试。
                skipped.append(str(m.get("shot_no") or r["id"]))
                continue
            shots.append({"id": r["id"], "shot_no": m.get("shot_no"), "prompt": prompt})
            # 参考图按目标独立关联：本镜首帧停用名单里的要素不进组图参考池
            off = _refs_off(m, "image")
            assembled += [
                ref for ref in (m.get("reference_images") or [])
                # 故事板格位图是单镜构图参考，整组共用会把所有镜画成同一格
                if ref.get("url") and ref.get("kind") != "storyboard" and ref.get("name") not in off
            ]
            # reference_images 是装配期的快照：装配之后才补出的设定图（本步 before 里
            # ensure_element_assets 刚给砾光补的那张就是）不在里面，于是同一角色在
            # 先后两批组图里一批有锚图、一批没有，颜色与造型必然对不上。
            # 按本镜 element_ids 取要素**当前**设定图补进池，不动提示词与质检缓存。
            eids = [int(x) for x in (m.get("element_ids") or []) if str(x).isdigit()]
            if eids:
                # 取图统一走 effective_meta：按本镜提示词语料 + 镜级选形态（与逐镜装配同口径），
                # 多形态角色不再恒拿主形态图
                _chosen = {str(k): v for k, v in (m.get("element_variants") or {}).items()}
                for e in await ctx.pool.fetch(
                        "SELECT id, name, kind, meta FROM content_elements "
                        "WHERE id = ANY($1::bigint[])", eids):
                    if e["name"] in off:
                        continue
                    em = ev.effective_meta(_meta(e), prompt or "", _chosen.get(str(e["id"])))
                    if em.get("sheet_url"):
                        fresh_refs.append(
                            {"name": e["name"],
                             "kind": "character_style" if e["kind"] == "character" else e["kind"],
                             "url": em["sheet_url"]})
        if not shots:
            raise Blocked("目标镜均无可用的首帧提示词（无提示词或质检未通过）"
                          + (f"：镜{'、'.join(skipped)}" if skipped else ""))
        if len(scene_keys) != 1:
            raise Blocked("组图只能包含同一场景合同下的镜头；跨场景必须切换场景锚点并单独生成")
        scene_seg, contract_id = next(iter(scene_keys))
        ctx.payload["seg"] = scene_seg
        ctx.payload["scene_contract_id"] = contract_id

        contract = None
        if contract_id:
            contract = await ctx.pool.fetchrow(
                "SELECT hard_locks FROM scene_continuity_contracts WHERE id=$1", contract_id)
        locks = None
        if contract:
            raw_locks = contract["hard_locks"]
            locks = raw_locks if isinstance(raw_locks, dict) else json.loads(raw_locks or "{}")
        chapter = await ctx.pool.fetchrow("SELECT meta FROM content_nodes WHERE id=$1", ctx.node_id)
        chapter_meta = _meta(chapter) if chapter else {}
        group = next((
            g for g in ((chapter_meta.get("scene_blocking") or {}).get("groups") or [])
            if int(g.get("seg") or 0) == scene_seg
        ), {})
        # 实时场景锚定的全部视觉硬锁都要送进组图提示词：此前只钉了拓扑/封闭性/色温/主光源
        # 四项，story_day / time_of_day / weather / lighting_direction / palette 全丢了——
        # 那几项恰恰是「同场景各画面时间段、天气与光线完全一致」的判据。
        ctx.payload["scene_lock"] = {
            "scene_seg": scene_seg,
            "scene": group.get("scene"),
            **{k: v for k, v in (locks or {}).items()
               if k in continuity.HARD_LOCK_KEYS and v not in (None, "", [])},
            "architectural_topology": (locks or {}).get("architectural_topology")
            or group.get("space"),
        }

        # 组图参考池 = 用户在画布上显式勾选的（优先，含素材库补充） + 各镜重装配出的设定图并集。
        # 按 url 去重；场景空间站位图排在最前——它是整组共用的空间/光线主锚，
        # 且供应商上限逼近时（14 镜只剩 1 个参考槽）截断保留的必须是它。
        # 按 name 去重（不是按 url）：同一角色的设定图重出过就有多个 URL 版本，
        # 按 url 去重会让同一个人白占两个参考槽——槽位本来就紧张。
        picked = [r for r in (ctx.payload.get("refs") or []) if r.get("url")]
        seen_names = {r.get("name") for r in picked}
        for ref in [*assembled, *fresh_refs]:
            if ref.get("name") in seen_names:
                continue
            seen_names.add(ref.get("name"))
            picked.append({"name": ref.get("name"), "kind": ref.get("kind"), "url": ref["url"]})
        picked.sort(key=lambda r: r.get("kind") != "scene_sheet")
        ctx.payload["refs"] = picked
        log.info("组图任务 %s：%d 镜，参考池 %d 张（%s）", ctx.task_id, len(shots), len(picked),
                 "、".join(str(r.get("name")) for r in picked) or "空")

        # 同场景被供应商上限或超时迫使拆组时，自动把上一批末帧作为视觉接缝。
        # 一旦跨 scene_seg/contract 则绝不继承，避免把上一场的光线带入下一场。
        first = rows[0]
        previous = await ctx.pool.fetchrow(
            "SELECT id,meta FROM content_nodes WHERE parent_id=$1 AND kind='shot' "
            "AND deleted_at IS NULL AND (seq,id)<($2,$3) ORDER BY seq DESC,id DESC LIMIT 1",
            first["parent_id"], first["seq"], first["id"])
        if previous:
            pm = _meta(previous)
            same_scene = int(pm.get("scene_seg") or 1) == scene_seg
            same_contract = (
                (pm.get("continuity") or {}).get("scene_contract_id") == contract_id
            )
            if same_scene and same_contract and pm.get("keyframe_url"):
                seam_ref = {
                    "kind": "continuity_frame",
                    "name": "同场景上一批末帧",
                    "url": pm["keyframe_url"],
                }
                current_refs = [r for r in (ctx.payload.get("refs") or [])
                                if r.get("url") != seam_ref["url"]]
                ctx.payload["refs"] = [seam_ref, *current_refs]
        if skipped:  # 依赖失败兜底：个别镜仍无提示词就跳过，不拖死整组
            ctx.payload["skipped"] = skipped
            log.warning("组图任务 %s：镜 %s 无首帧提示词，跳过", ctx.task_id, "、".join(skipped))
        ctx.payload["shots"] = shots
        if not ctx.payload.get("size"):
            ctx.payload["size"] = await _frame_size(ctx, chapter_id=ctx.node_id)

    async def run(self, ctx: Ctx) -> RunResult:
        row = await ctx.pool.fetchrow(
            "SELECT seq, title FROM content_nodes WHERE id=$1", ctx.node_id)
        token = media.GEN_AUDIT.set({
            "project_id": ctx.project_id, "node_id": ctx.node_id, "task_id": ctx.task_id,
            "chapter_id": ctx.node_id, "chapter_title": row["title"] if row else None,
            "kind": self.kind,
            "source": f"project_{ctx.project_id}_{row['seq'] if row else ctx.node_id}_group_image",
        })
        try:
            return await self._run_gen(ctx)
        finally:
            media.GEN_AUDIT.reset(token)

    async def _run_gen(self, ctx: Ctx) -> RunResult:
        shots = ctx.payload["shots"]
        refs = [r for r in (ctx.payload.get("refs") or []) if r.get("url")]
        refs = refs[:max(0, 15 - len(shots))]  # 参考+生成合计 ≤15，超出截断（勾选顺序优先）
        prompt = build_group_keyframe_prompt(
            shots, refs, ctx.payload.get("note") or "", ctx.payload.get("scene_lock"))
        urls = await media.generate_image_group(
            prompt, count=len(shots), size=ctx.payload.get("size"),
            reference_images=[r["url"] for r in refs] or None,
            store_prefix="keyframe",
        )
        return RunResult({"urls": urls})

    async def next(self, ctx: Ctx, result: dict[str, Any]) -> dict[str, Any]:
        shots = ctx.payload["shots"]
        urls = result.get("urls") or []
        async with ctx.pool.acquire() as conn:
            for s, url in zip(shots, urls):
                # 每镜一个事务：FOR UPDATE 的行锁只在事务里才跨语句持有，
                # 否则并发的单镜出图/批量组图会读到同一份旧 meta 互相覆盖版本链
                async with conn.transaction():
                    old_meta_row = await conn.fetchrow(
                        "SELECT meta FROM content_nodes WHERE id=$1 FOR UPDATE", s["id"])
                    old_meta = _meta(old_meta_row) if old_meta_row else {}
                    versions = list(old_meta.get("keyframe_versions") or [])
                    old_url = old_meta.get("keyframe_url")
                    if old_url and old_url != url and not any(
                        isinstance(v, dict) and v.get("url") == old_url for v in versions
                    ):
                        versions.append({
                            "url": old_url,
                            "source": old_meta.get("keyframe_source"),
                            "superseded_by_task": ctx.task_id,
                        })
                    await conn.execute(
                        "INSERT INTO content_attachments (project_id, node_id, kind, url, meta) "
                        "VALUES ($1,$2,'image',$3,$4::jsonb)",
                        ctx.project_id, s["id"], url,
                        json.dumps({"prompt": s["prompt"], "type": "keyframe",
                                    "group_task": ctx.task_id}, ensure_ascii=False),
                    )
                    await conn.execute(
                        "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() "
                        "WHERE id=$1",
                        s["id"], json.dumps({"keyframe_url": url,
                                             "keyframe_source": "gen",
                                             "keyframe_versions": versions}, ensure_ascii=False),
                    )
                    await _backfill_seam_for(conn, s["id"], url)
        out: dict[str, Any] = {"generated": len(urls), "expected": len(shots)}
        if len(urls) < len(shots):  # 模型少生：后面的镜留空（前端仍显示缺首帧，可再点批量补齐）
            out["missing_shots"] = [s["shot_no"] for s in shots[len(urls):]]
        if ctx.payload.get("skipped"):
            out["skipped_no_prompt"] = ctx.payload["skipped"]
        return out


@register
class LastKeyframeStep(KeyframeStep):
    """尾帧定格画面（可选）：与首帧同路径生图（设定图参考+引用句），产物写 meta.last_frame_url。
    视频提交时不占 first/last frame 通道——media 层折算为 reference_image，
    提示词织入「开始参考@首帧、结尾落在@尾帧」引用句（Seedance 2.0 实测约束）。
    提示词恒为用户/AI 手动内容（meta.last_image_prompt），无自动装配与九维质检链。"""

    kind = "gen_last_keyframe"
    group = "生图"
    manual = True
    dep_kinds: list[str] = []  # 覆盖 KeyframeStep：尾帧无自动装配链，不向上派 gen_prompts
    soft_deps: list[str] = []  # 覆盖 KeyframeStep：尾帧走独立装配，不共用 element_sheet 隐式补图
    before_notes = [
        "补设定图 + 重装配参考图",
        "取 meta.last_image_prompt（空则 Blocked，需先填/AI 生成）",
    ]
    run_note = "生尾帧定格画面（与首帧同路径）→ OSS"
    next_notes = ["落附件 + 回写 last_frame_url（视频提交时折算为参考图 +「结尾落在@尾帧」）"]
    gen_slot = "last_keyframe"

    async def missing_deps(self, conn: Any, project_id: int | None,
                           node_id: int | None, payload: dict[str, Any]) -> list[dict[str, Any]]:
        # 尾帧无自动装配链：提示词在 API 侧校验（缺则 400），不向上派发 gen_prompts
        return []

    async def before(self, ctx: Ctx) -> None:
        # 不走 _shot_gen_before（其质检分支只认 image/video 两套提示词）：
        # 只补设定图 + 重装配刷新参考图池（纯 DB+字符串，保证指向要素最新设定图）
        await _ensure_element_sheets(ctx)
        from .storyboard import assemble_shot_prompts

        fresh = await assemble_shot_prompts(ctx.pool, ctx.project_id, ctx.node_id)
        meta = await _shot_meta(ctx)
        if not ctx.payload.get("prompt"):
            ctx.payload["prompt"] = meta.get("last_image_prompt")
        if not ctx.payload.get("prompt"):
            raise Blocked("尾帧提示词为空——请先在尾帧卡填写或 AI 生成")
        # 尾帧是收束画面：wide 判定按最后一个切换的景别（首帧按第一个）
        _lc = (meta.get("cuts") or [{}])[-1]
        ctx.payload["wide_frame"] = (_lc.get("scale") or meta.get("scale", "")) in ("全景", "远景", "大远景")
        off = _refs_off(meta, "last")
        ctx.payload["reference_images"] = [
            r for r in (fresh.get("reference_images") or []) if r.get("name") not in off
        ]
        # 生图尺寸跟随项目/卷画幅（与首帧同口径）
        if not ctx.payload.get("size"):
            ctx.payload["size"] = await _frame_size(ctx)

    async def next(self, ctx: Ctx, result: dict[str, Any]) -> dict[str, Any]:
        async with ctx.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO content_attachments (project_id, node_id, kind, url, meta) "
                "VALUES ($1,$2,'image',$3,$4::jsonb)",
                ctx.project_id, ctx.node_id, result["url"],
                json.dumps({"prompt": ctx.payload["prompt"], "type": "last_keyframe"}, ensure_ascii=False),
            )
            # last_frame_source：区分「生成」与「从下一镜视频抽取」（api/shots.py frame_from_neighbor）
            await conn.execute(
                "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
                ctx.node_id, json.dumps({"last_frame_url": result["url"],
                                         "last_frame_source": "gen"}, ensure_ascii=False),
            )
        return result


@register
class ElementSheetStep(Step):
    """要素设定图（角色身份版三视图/表情/动作/色板；场景概念图）。生成时记外貌指纹——
    外貌提示词改动后，镜级前置会判定设定图过期并自动重生成。"""

    kind = "gen_element_sheet"
    group = "生图"
    run_note = "生要素设定图（角色三视图/表情/色板；场景概念图，可带用户参考图）→ OSS"
    next_notes = ["落附件 + 回写形态 sheet_url + sheet_fingerprint（外貌指纹，改动后镜级前置自动重生成）"]

    async def run(self, ctx: Ctx) -> RunResult:
        token = media.GEN_AUDIT.set({
            "project_id": ctx.project_id, "node_id": ctx.node_id, "task_id": ctx.task_id,
            "kind": self.kind,
            "source": f"project_{ctx.project_id}_element_{ctx.payload.get('element_id')}_sheet",
        })
        try:
            # 用户手选的参考图（meta.extra_refs 去掉 sheet_ref_off 停用项，入队时已并入 payload）
            refs = [r["url"] for r in (ctx.payload.get("reference_images") or []) if r.get("url")]
            url = await media.generate_image(
                ctx.payload["prompt"], reference_images=refs[:4] or None, store_prefix="sheet",
                profile_id=ctx.payload.get("model_profile_id"),
                feature_code="element_sheet")
            hair_url = None
            if ctx.payload.get("hair_prompt"):
                hair_url = await media.generate_image(
                    ctx.payload["hair_prompt"], store_prefix="sheet-hair",
                    profile_id=ctx.payload.get("model_profile_id"),
                    feature_code="element_sheet")
        finally:
            media.GEN_AUDIT.reset(token)
        return RunResult({"url": url, "hair_url": hair_url})

    async def next(self, ctx: Ctx, result: dict[str, Any]) -> dict[str, Any]:
        element_id = ctx.payload["element_id"]
        variant_id = ctx.payload.get("variant_id")
        async with ctx.pool.acquire() as conn:
            elem = await conn.fetchrow(
                "SELECT brief, meta FROM content_elements WHERE id=$1", element_id
            )
            em = _meta(elem) if elem else {}
            variant = ev.find_variant(em, variant_id) or ev.primary_variant(em)
            fp = flow.fingerprint(ev.sheet_source(variant, elem["brief"])) if elem else ""
            await conn.execute(
                "INSERT INTO content_attachments (project_id, element_id, kind, url, meta) "
                "VALUES ($1,$2,'image',$3,$4::jsonb)",
                ctx.project_id, element_id, result["url"],
                json.dumps({"prompt": ctx.payload["prompt"], "type": "sheet",
                            "variant_id": variant.get("id"), "tag": variant.get("tag") or ""},
                           ensure_ascii=False),
            )
            patch = ev.set_variant_sheet(em, variant_id, result["url"], fp)
            if result.get("hair_url"):
                patch["hair_sheet_url"] = result["hair_url"]
            await conn.execute(
                "UPDATE content_elements SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
                element_id, json.dumps(patch, ensure_ascii=False),
            )
        return result


@register
class CanvasImageStep(Step):
    """画布自由出图（2026-08-01）：提示词 + 上游参考图 → 一张图 → 落项目附件。

    这是 tapflow 画布上「从某个节点拖出来再生成一张」的执行体。与 gen_element_sheet
    的分工是**产物归属**：那条焊在要素上（回写 meta.sheet_url + 外貌指纹，是产线的
    正式设定图），拖出来的这张没有要素归属，只落一条附件——素材库看得见、可以拿去用，
    但绝不覆盖任何要素的正式设定图。混用会出事：用户拖出来试个构图，正式设定图就被换掉了。

    提示词从哪来由引擎决定（见 workflow._run_gen_node）：生成条里手写的、上游文本节点
    的产物、系统提示词让模型写的，本步只管把拿到的那段发给出图模型。
    """

    kind = "gen_canvas_image"
    group = "生图"
    manual = True          # 只在画布上被 gen 节点派发，不进任何自动链
    run_note = "按提示词 + 上游参考图出一张自由图 → OSS"
    next_notes = ["落附件（kind=image, meta.type=canvas）；不回写任何要素的设定图"]

    async def run(self, ctx: Ctx) -> RunResult:
        prompt = str(ctx.payload.get("prompt") or "").strip()
        if not prompt:
            raise Blocked("这个节点还没有提示词：在生成条里写一句，或从上游连一个文本节点进来")
        token = media.GEN_AUDIT.set({
            "project_id": ctx.project_id, "node_id": ctx.node_id, "task_id": ctx.task_id,
            "kind": self.kind, "source": f"project_{ctx.project_id}_canvas",
        })
        try:
            refs = [r["url"] for r in (ctx.payload.get("reference_images") or []) if r.get("url")]
            # 功能配置：画布节点可在 config.feature_code 点名功能（如九宫格），
            # 未点名时按通用"画布出图"功能取档；显式 model_profile_id 仍优先
            url = await media.generate_image(
                prompt, reference_images=refs[:4] or None, store_prefix="canvas",
                profile_id=ctx.payload.get("model_profile_id"),
                feature_code=ctx.payload.get("feature_code") or "canvas_image")
        finally:
            media.GEN_AUDIT.reset(token)
        return RunResult({"url": url})

    async def next(self, ctx: Ctx, result: dict[str, Any]) -> dict[str, Any]:
        # element_id 可空：自由节点通常没有归属要素，挂在项目上即可（素材库按项目列）
        await ctx.pool.execute(
            "INSERT INTO content_attachments (project_id, node_id, element_id, kind, url, meta) "
            "VALUES ($1,$2,$3,'image',$4,$5::jsonb)",
            ctx.project_id, ctx.node_id, ctx.payload.get("element_id"), result["url"],
            # meta.node = 画布上那张卡的 id：节点的「缺才跑」探针按它回查自己上次出的图
            # （见前端 lib/tapflowCustomNode），少了这一项，整图每跑一遍就重出一次
            json.dumps({"prompt": ctx.payload.get("prompt") or "", "type": "canvas",
                        "node": ctx.payload.get("node_key") or "",
                        "title": ctx.payload.get("title") or ""}, ensure_ascii=False),
        )
        return result


@register
class CanvasVideoStep(Step):
    """Generate a free canvas video and persist the result as a project attachment.

    The planner supplies the prompt and optional frame references. The provider
    URL is temporary, so ``next`` transfers it to OSS before writing the
    attachment and returning the durable URL to the canvas.
    """

    kind = "gen_canvas_video"
    group = "生视频"
    manual = True
    timeout_s = 900
    run_note = "按提示词 + 上游首/尾帧出一段自由视频 → OSS"
    next_notes = ["OSS 转存后落附件（kind=video, meta.type=canvas）"]

    async def run(self, ctx: Ctx) -> RunResult:
        prompt = str(ctx.payload.get("prompt") or "").strip()
        if not prompt:
            raise Blocked("video node requires a prompt")
        token = media.GEN_AUDIT.set({
            "project_id": ctx.project_id, "node_id": ctx.node_id, "task_id": ctx.task_id,
            "kind": self.kind, "source": f"project_{ctx.project_id}_canvas",
        })
        try:
            result = await media.generate_video(
                prompt,
                image_url=ctx.payload.get("first_frame_url") or None,
                last_frame_url=ctx.payload.get("last_frame_url") or None,
                duration=int(ctx.payload.get("duration_s") or 5),
                ratio=str(ctx.payload.get("ratio") or "16:9"),
            )
        finally:
            media.GEN_AUDIT.reset(token)
        return RunResult({"url": result["url"], "provider": result.get("provider")})

    async def next(self, ctx: Ctx, result: dict[str, Any]) -> dict[str, Any]:
        source_url = str(result.get("url") or "").strip()
        if not source_url:
            raise RuntimeError("video generation returned no URL")
        url = await store_url(source_url, "canvas_video")
        await ctx.pool.execute(
            "INSERT INTO content_attachments (project_id, node_id, element_id, kind, url, meta) "
            "VALUES ($1,$2,$3,'video',$4,$5::jsonb)",
            ctx.project_id, ctx.node_id, ctx.payload.get("element_id"), url,
            json.dumps({"prompt": ctx.payload.get("prompt") or "", "type": "canvas",
                        "node": ctx.payload.get("node_key") or "",
                        "title": ctx.payload.get("title") or "",
                        "provider": result.get("provider") or ""}, ensure_ascii=False),
        )
        return {**result, "url": url}


@register
class VideoStep(Step):
    """镜级视频生成。before=①设定图②提示词质检状态（均带缓存）③音频预检（缓存，永不阻断）；
    run=ARK 提交即释放（waiting_external，poller 收割后回调 next）或 GRSAI 同步兜底；
    next=OSS 转存→附件+meta 回写→镜 status=rendered。"""

    kind = "gen_video"
    group = "生视频"
    dep_kinds = ["gen_prompts", "gen_keyframe"]
    soft_deps = ["gen_element_sheet", "gen_last_keyframe"]  # before 补设定图 + 尾帧折算（有则用）
    before_notes = [
        "缺视频提示词 → 派 gen_prompts；缺首帧 → 派 gen_keyframe（I2V 锚点）",
        "补设定图 + 重装配参考图（实时刷新 keyframe_url）",
        "提示词九维质检（缓存 72h）",
        "音频预检：对白×音色 → 参考声线（缓存 24h，永不阻断，失败降级不传音频）",
        "首/尾帧 + 接缝帧折算（尾帧空则取下一镜首帧，跨镜无缝）",
        "角色硬闸：提示词没点名的角色不传设定图",
    ]
    run_note = ("ARK 提交即释放（waiting_external，poller 收割）/ GRSAI 同步兜底；"
                "输入审核拒收走降级级联：去首帧留参考图 → 仅动作构图帧 → 纯文生视频")
    next_notes = ["OSS 转存 → 落附件 + video_url", "镜 status=rendered", "回写 gen_logs 审计闭环"]
    gen_slot = "video"
    timeout_s = 900
    # 视频不自动重试（用户 2026-07-12 定稿）：失败即 failed，人工看错误（含提交模态摘要）后手动重试。
    # 输入审核拒收的确定性降级级联仍在 run 内按错误类型走，与盲重试无关
    max_retries = 0

    async def missing_deps(self, conn: Any, project_id: int | None,
                           node_id: int | None, payload: dict[str, Any]) -> list[dict[str, Any]]:
        # 前置=视频提示词 + 首帧图（I2V 锚点）。缺则逐级向上派发：gen_keyframe 自己
        # 又依赖 image_prompt → 再派 gen_prompts（幂等去重把两条链的 gen_prompts 合并为一）。
        # 用户显式停用首帧（ref_off.video 含"首帧"）则不派首帧任务，走参考图/纯文本路径。
        meta = await _node_meta_conn(conn, node_id)
        out: list[dict[str, Any]] = []
        if not (payload.get("prompt") or meta.get("video_prompt")):
            out.append({"kind": "gen_prompts", "payload": {}, "priority": 10})
        off = _refs_off(meta, "video")
        if "首帧" not in off and not meta.get("keyframe_url"):
            out.append({"kind": "gen_keyframe", "priority": 10, "payload": {
                "prompt_overridden": bool(meta.get("image_prompt_edited")),
            }})
        return out

    async def before(self, ctx: Ctx) -> None:
        meta = await _shot_gen_before(ctx, self.kind)
        off = _refs_off(meta, "video")
        # 首帧引用随 meta 实时刷新（依赖链修正）：enqueue 时首帧可能尚未生成
        # （由依赖子任务补出），提交前必须重读 keyframe_url 才能走 I2V 路径
        ctx.payload["first_frame_url"] = None if "首帧" in off else meta.get("keyframe_url")
        # 尾帧可选（用户手动生成/留空）：有且未停用才传——media 层折算为 reference_image
        # + 「结尾落在@图片N」引用句，不占 last_frame 通道（与参考图/音频可共存）
        ctx.payload["last_frame_url"] = None if "尾帧" in off else meta.get("last_frame_url")
        # 接缝帧兜底（跨镜连贯）：尾帧空缺且下一镜与本镜「连贯」相接、其首帧已出
        # → 直接取下一镜首帧作本镜尾帧（本镜视频收束到下一镜开场，跨镜像素级无缝）。
        # 常态由 KeyframeStep._backfill_seam 提前回填，这里兜"先出本镜视频后出下镜首帧"的时序
        if ctx.payload["last_frame_url"] is None and "尾帧" not in off:
            nxt = await ctx.pool.fetchrow(
                "SELECT meta FROM content_nodes WHERE kind='shot' AND deleted_at IS NULL AND parent_id="
                "(SELECT parent_id FROM content_nodes WHERE id=$1) AND seq>"
                "(SELECT seq FROM content_nodes WHERE id=$1) ORDER BY seq LIMIT 1", ctx.node_id)
            nm = _meta(nxt) if nxt else {}
            if nm.get("link_prev") and nm.get("keyframe_url"):
                ctx.payload["last_frame_url"] = nm["keyframe_url"]
                await ctx.pool.execute(
                    "UPDATE content_nodes SET meta = meta || $2::jsonb, updated_at=now() WHERE id=$1",
                    ctx.node_id, json.dumps({"last_frame_url": nm["keyframe_url"],
                                             "last_frame_source": "next_keyframe"}, ensure_ascii=False))
                log.info("镜 %s 尾帧取下一镜首帧（接缝帧，link_prev=连贯）", ctx.node_id)
        # 参考图按目标独立关联：视频停用名单里的要素不上传设定图
        # （其身份层已在装配时回退外貌全文，引用与附件同生死）
        ctx.payload["reference_images"] = [
            r for r in (ctx.payload.get("reference_images") or []) if r.get("name") not in off
        ]
        # 角色参考图硬闸：视频提示词（含手编）没点到的角色不传设定图
        ctx.payload["reference_images"] = _drop_unmentioned_chars(
            ctx.payload.get("prompt") or meta.get("video_prompt") or "",
            ctx.payload["reference_images"], f"镜 {ctx.node_id} gen_video")
        # 前置③：音频预检（对白×音色）→ audio_refs 供音画闭环。缓存=对白+绑定指纹，24h。
        # 永不阻断生成：失败只降级为"不传参考音频"；不受 prompt_overridden 豁免（与手编提示词无关）。
        from .audio_precheck import precheck_shot_audio, precheck_source

        try:
            src = await precheck_source(ctx.pool, ctx.project_id, meta)
            ap = meta.get("audio_precheck")
            if flow.cache_valid(ap, src):
                ctx.payload["audio_refs"] = ap.get("audio_refs") or []
            else:
                pc = await precheck_shot_audio(ctx.pool, ctx.project_id, ctx.node_id)
                ctx.payload["audio_refs"] = pc.get("audio_refs") or []
                if pc.get("required"):
                    log.info("task %s 音频预检: 合格=%s refs=%d degraded=%s", ctx.task_id,
                             pc.get("合格"), len(ctx.payload["audio_refs"]), pc.get("degraded"))
        except Exception as e:  # noqa: BLE001
            log.warning("task %s 音频预检异常，不传参考音频: %s", ctx.task_id, e)
            ctx.payload["audio_refs"] = []
        # 用户停用的音频参考（ref_off.video 含"音频·{角色}"）：生成时不上传该角色声线
        ctx.payload["audio_refs"] = [
            r for r in (ctx.payload.get("audio_refs") or [])
            if f"音频·{r.get('speaker', '')}" not in off
        ]

    async def run(self, ctx: Ctx) -> RunResult:
        # 生成审计上下文（用户 2026-07-12）：本任务每次真实提交由 media 层落 gen_logs
        # （含降级级联每一跳的完整入参）；带章节/镜号与来源标记便于按剧集/分镜复盘。
        # finally 必须 reset——worker 协程复用，不 reset 会把上下文漏给下一单任务
        token = media.GEN_AUDIT.set(await _shot_audit_ctx(ctx, self.kind, "video"))
        try:
            return await self._run_inner(ctx)
        finally:
            media.GEN_AUDIT.reset(token)

    async def _run_inner(self, ctx: Ctx) -> RunResult:
        payload = ctx.payload
        if not await media.video_provider_is_ark():
            # 非 ARK = 同步路径（提交与结果同刻）：百炼 dashscope / GRSAI。
            # 首/尾帧照传：百炼 i2v 两个通道都吃（接缝帧因此在这条路上同样生效），
            # GRSAI 纯文生视频会忽略。审计由 media._dashscope_video 内部落，这里只兜
            # GRSAI——它没有自己的审计，补一行免得同步路径在 gen_logs 里断档。
            res = await media.generate_video(
                payload["prompt"], image_url=payload.get("first_frame_url"),
                last_frame_url=payload.get("last_frame_url"),
                duration=int(payload.get("duration_s", 5)),
            )
            if res["provider"].startswith("grsai:"):
                await media._audit_log(  # noqa: SLF001
                    provider="grsai", model=res["provider"], modality="text",
                    request={"prompt": payload["prompt"],
                             "duration": int(payload.get("duration_s", 5))},
                    external_task_id=None, status="done", result={"video_url": res["url"]})
            return RunResult({"video_url": res["url"], "provider": res["provider"]})
        try:
            ext_id = await media.submit_ark_video(
                payload["prompt"],
                image_url=payload.get("first_frame_url"),
                last_frame_url=payload.get("last_frame_url"),
                reference_images=payload.get("reference_images"),
                duration=int(payload.get("duration_s", 5)),
                ratio=payload.get("ratio", "16:9"),  # 全项目视频画幅统一
                audio_refs=payload.get("audio_refs"),  # 音画闭环：预检产出，有对白才有
            )
        except RuntimeError as e:
            # 实测：过于写实的首帧/设定图会被 ARK 输入审核判"疑似真人"拒收——确定性降级级联：
            # ①去首帧留参考图 → ②仅保留预览动作构图帧 → ③纯文生视频。
            # 第②级优先挽救从母带到最终镜头的动作/构图约束，身份改由提示词全文兜底。
            if "SensitiveContentDetected" not in str(e) or not payload.get("first_frame_url"):
                raise
            log.warning("task %s 首帧被输入审核拦截，降级参考图/纯文本: %s", ctx.task_id, str(e)[:200])
            try:
                ext_id = await media.submit_ark_video(
                    payload["prompt"],
                    reference_images=payload.get("reference_images"),
                    duration=int(payload.get("duration_s", 5)),
                    ratio=payload.get("ratio", "16:9"),
                    audio_refs=payload.get("audio_refs"),  # 仍有参考图伴随，音频保留
                )
            except RuntimeError as e2:
                if "SensitiveContentDetected" not in str(e2):
                    raise
                preview_refs = [
                    ref for ref in (payload.get("reference_images") or [])
                    if ref.get("kind") == "preview_action"
                ]
                if preview_refs:
                    log.warning(
                        "task %s 全量参考图被拦截，仅保留动作构图帧重试: %s",
                        ctx.task_id, str(e2)[:200],
                    )
                    try:
                        ext_id = await media.submit_ark_video(
                            payload["prompt"],
                            reference_images=preview_refs,
                            duration=int(payload.get("duration_s", 5)),
                            ratio=payload.get("ratio", "16:9"),
                            audio_refs=payload.get("audio_refs"),
                        )
                        return RunResult(external_id=ext_id)
                    except RuntimeError as e3:
                        if "SensitiveContentDetected" not in str(e3):
                            raise
                        log.warning(
                            "task %s 动作构图帧也被拦截，纯文生视频: %s",
                            ctx.task_id, str(e3)[:200],
                        )
                else:
                    log.warning("task %s 参考图被拦截且无动作构图帧，纯文生视频: %s",
                                ctx.task_id, str(e2)[:200])
                # 零输入图 → 引用式身份层失效，必须换外貌全文版提示词；
                # 音频透传但 media 层 use_audio 条件（必须伴随图）会自动掐掉，无需特判
                ext_id = await media.submit_ark_video(
                    payload.get("prompt_textonly") or payload["prompt"],
                    duration=int(payload.get("duration_s", 5)),
                    ratio=payload.get("ratio", "16:9"),
                    audio_refs=payload.get("audio_refs"),
                )
        return RunResult(external_id=ext_id)

    async def next(self, ctx: Ctx, result: dict[str, Any]) -> dict[str, Any]:
        url = result.get("video_url") or result.get("url")
        provider = result.get("provider") or "ark"
        url = await store_url(url, "video")
        # 默认抽首帧作视频封面：抽帧转存 OSS，作为一条 image 附件落库，视频行的
        # cover_attachment_id 指向它；镜头 meta 也存 video_cover_url 供前端 <video poster>。
        # 抽帧/转存失败不阻断视频落地（封面为可选增强），只记日志。
        cover_url: str | None = None
        try:
            from .frames import extract_frame

            frame = await extract_frame(url, "first")
            cover_url = await store_bytes(frame, "video_cover", ".jpeg") or None
        except Exception as e:  # noqa: BLE001 — 封面为增强项，失败降级为无封面
            log.warning("task %s 视频首帧封面抽取失败：%s", ctx.task_id, str(e)[:200])
        async with ctx.pool.acquire() as conn:
            cover_att_id: int | None = None
            if cover_url:
                cover_att_id = await conn.fetchval(
                    "INSERT INTO content_attachments (project_id, node_id, kind, url, meta) "
                    "VALUES ($1,$2,'image',$3,$4::jsonb) RETURNING id",
                    ctx.project_id, ctx.node_id, cover_url,
                    json.dumps({"type": "video_cover", "from": "video_first_frame"}, ensure_ascii=False),
                )
            await conn.execute(
                "INSERT INTO content_attachments (project_id, node_id, kind, url, meta, cover_attachment_id) "
                "VALUES ($1,$2,'video',$3,$4::jsonb,$5)",
                ctx.project_id, ctx.node_id, url,
                json.dumps({"prompt": ctx.payload.get("prompt"), "provider": provider,
                            "cover_url": cover_url}, ensure_ascii=False),
                cover_att_id,
            )
            node_patch: dict[str, Any] = {"video_url": url}
            if cover_url:
                node_patch["video_cover_url"] = cover_url
            await conn.execute(
                "UPDATE content_nodes SET meta = meta || $2::jsonb, status='rendered', updated_at=now() WHERE id=$1",
                ctx.node_id, json.dumps(node_patch, ensure_ascii=False),
            )
            # 审计闭环：本单被 ARK 受理的那次提交（accepted）回写最终结果（OSS 转存后 URL）
            await conn.execute(
                "UPDATE gen_logs SET status='done', result=$2::jsonb, finished_at=now() "
                "WHERE task_id=$1 AND status='accepted'",
                ctx.task_id, json.dumps({"video_url": url, "provider": provider}, ensure_ascii=False),
            )
        return {"url": url, "provider": provider}


@register
class ProjectInfoStep(Step):
    """项目基本信息初拟（建项目即返，后台补齐）：只填用户引导里留空的字段
    （书名/梗概/文风/画风/主线 + config 的 genre/suggested_chapters），
    用户已填的一律不动；完成后链式入队架构大纲任务（大纲以基本信息为输入）。"""

    kind = "gen_project_info"
    group = "筹备"
    chains_to = ["gen_outline_md"]
    timeout_s = 300
    run_note = "LLM 补齐用户留空的基本信息（书名/梗概/文风/画风/主线 + 题材/建议章数）"
    next_notes = ["串出 gen_outline_md（大纲以基本信息为输入）"]

    async def run(self, ctx: Ctx) -> RunResult:
        from . import pipeline

        row = await ctx.pool.fetchrow("SELECT * FROM content_projects WHERE id=$1", ctx.project_id)
        if not row:
            raise Blocked("项目不存在（可能已被删除）")
        cfg = row["config"] if isinstance(row["config"], dict) else json.loads(row["config"] or "{}")
        # 「未命名」是创建时的占位书名，视同缺失
        missing = [k for k in ("title", "synopsis", "writing_style", "art_style", "storyline")
                   if not (row[k] or "").strip() or (k == "title" and row[k] == "未命名")]
        need_cfg = not cfg.get("genre") or not cfg.get("suggested_chapters")
        if not missing and not need_cfg:
            return RunResult({"filled": []})
        chunks = await ctx.pool.fetch(
            "SELECT c.content, c.summary FROM project_material_chunks c "
            "JOIN project_materials m ON m.id=c.material_id "
            "WHERE m.project_id=$1 ORDER BY m.id, c.chunk_index LIMIT 12", ctx.project_id)
        material_context = "\n\n".join((c["summary"] or c["content"] or "") for c in chunks)
        info = await pipeline.gen_project_info(
            row["draft_text"] or "", row["project_type"] or "novel_comic", material_context)
        filled = {k: str(info.get(k) or "").strip() for k in missing if str(info.get(k) or "").strip()}
        if not cfg.get("genre"):
            cfg["genre"] = info.get("genre", "")
        if not cfg.get("suggested_chapters"):
            cfg["suggested_chapters"] = info.get("suggested_chapters", 20)
        sets = "".join(f", {k}=${i}" for i, k in enumerate(filled, start=3))
        await ctx.pool.execute(
            f"UPDATE content_projects SET config=$2::jsonb{sets}, updated_at=now() WHERE id=$1",
            ctx.project_id, json.dumps(cfg, ensure_ascii=False), *filled.values(),
        )
        return RunResult({"filled": sorted(filled)})

    async def next(self, ctx: Ctx, result: dict[str, Any]) -> dict[str, Any]:
        # 基本信息就绪后再拟长篇架构大纲（其提示词以基本信息为输入）；已有大纲则不重复
        row = await ctx.pool.fetchrow(
            "SELECT outline_md FROM content_projects WHERE id=$1", ctx.project_id)
        if row and not (row["outline_md"] or "").strip():
            await flow.enqueue(
                ctx.pool, kind="gen_outline_md", project_id=ctx.project_id,
                root_task_id=ctx.task["root_task_id"] or ctx.task_id,
            )
        return result


@register
class OutlineMdStep(Step):
    """长篇架构大纲（Markdown 全文）：建项目时入队后台生成（LLM 大输出不占创建请求），
    失败不影响项目——总览「大纲」区可随时手动重新生成。"""

    kind = "gen_outline_md"
    group = "筹备"
    chains_to = ["gen_element_kinds"]
    timeout_s = 900
    run_note = "LLM 生成长篇架构大纲（Markdown 全文）"
    next_notes = ["串出 gen_element_kinds（判定要素类型）"]

    async def run(self, ctx: Ctx) -> RunResult:
        from . import pipeline

        row = await ctx.pool.fetchrow(
            "SELECT * FROM content_projects WHERE id=$1", ctx.project_id
        )
        if not row:
            raise Blocked("项目不存在（可能已被删除）")
        project = dict(row)
        chunks = await ctx.pool.fetch(
            "SELECT c.content, c.summary FROM project_material_chunks c "
            "JOIN project_materials m ON m.id=c.material_id "
            "WHERE m.project_id=$1 ORDER BY m.id, c.chunk_index LIMIT 24", ctx.project_id)
        project["_material_context"] = "\n\n".join((c["content"] or c["summary"] or "") for c in chunks)
        review = await pipeline.gen_outline_md_with_review(project)
        md = review.pop("revised_markdown")
        async with ctx.pool.acquire() as conn:
            async with conn.transaction():
                archived_id = await pipeline.archive_outline_version(
                    conn, ctx.project_id, row["outline_md"],
                    task_id=ctx.task_id, reason="background_regenerate")
                await conn.execute(
                    "UPDATE content_projects SET outline_md=$2, "
                    "config=config || $3::jsonb, updated_at=now() WHERE id=$1",
                    ctx.project_id, md,
                    json.dumps({"outline_content_review": review}, ensure_ascii=False),
                )
        return RunResult({
            "chars": len(md),
            "archived_material_id": archived_id,
            "content_review": review,
        })

    async def next(self, ctx: Ctx, result: dict[str, Any]) -> dict[str, Any]:
        # 大纲就绪后自动判定要素类型（已有类型则不发；enqueue 幂等去重）
        cfg = await ctx.pool.fetchval(
            "SELECT config FROM content_projects WHERE id=$1", ctx.project_id)
        cfg = cfg if isinstance(cfg, dict) else json.loads(cfg or "{}")
        if not cfg.get("element_kinds"):
            await flow.enqueue(
                ctx.pool, kind="gen_element_kinds", project_id=ctx.project_id,
                root_task_id=ctx.task["root_task_id"] or ctx.task_id,
            )
        return result


@register
class ElementKindsStep(Step):
    """要素类型判定：把知识库内置要素类型（kind=element_type）整份清单喂给 LLM，
    按剧情判定本项目需要哪些分组，写入 config.element_kinds（[{code,label}]，
    核心类型强制保留，顺序按知识库排列）。大纲完成后自动链发；核心要素页缺类型也会补发。"""

    kind = "gen_element_kinds"
    group = "筹备"
    timeout_s = 180
    run_note = "LLM 按剧情从内置要素类型清单挑选本项目需要的分组 → config.element_kinds"

    async def run(self, ctx: Ctx) -> RunResult:
        from .. import llm

        row = await ctx.pool.fetchrow(
            "SELECT * FROM content_projects WHERE id=$1", ctx.project_id)
        if not row:
            raise Blocked("项目不存在（可能已被删除）")
        cfg = row["config"] if isinstance(row["config"], dict) else json.loads(row["config"] or "{}")
        if cfg.get("element_kinds"):  # 已判定过（并发补发/手动重跑）：直接返回
            return RunResult({"element_kinds": cfg["element_kinds"], "skipped": True})
        types = await ctx.pool.fetch(
            "SELECT name, content, meta FROM kb_entries "
            "WHERE kind='element_type' AND enabled ORDER BY id")
        if not types:
            raise Blocked("知识库无内置要素类型（kind=element_type），请检查 seed")
        catalog: dict[str, str] = {}  # code → label（保持知识库顺序）
        core: list[str] = []
        for t in types:
            m = _meta(t)
            code = str(m.get("code") or t["name"])
            catalog[code] = t["name"]
            if m.get("core"):
                core.append(code)
        menu = "\n".join(
            f"- {_meta(t).get('code') or t['name']}（{t['name']}）：{t['content']}" for t in types)
        sys = (
            "你是小说设定集架构师。根据作品剧情，从下列内置要素类型中挑选本项目需要建立的"
            "设定集分组类型。只挑剧情真正会用到的，宁缺毋滥。\n"
            f"可选类型：\n{menu}\n\n"
            '严格输出 JSON：{"kinds": ["character", "..."]}（值只能取上面列出的类型代码）'
        )
        user = (
            f"书名：{row['title']}\n题材：{cfg.get('genre', '')}\n梗概：{row['synopsis']}\n"
            f"主线：{row['storyline']}\n大纲节选：{(row['outline_md'] or '')[:2000]}"
        )
        data = await llm.chat_json(sys, user)
        picked = {k for k in (data.get("kinds") or []) if k in catalog} | set(core)
        kinds = [{"code": c, "label": label} for c, label in catalog.items() if c in picked]
        await ctx.pool.execute(
            "UPDATE content_projects SET config = config || $2::jsonb, updated_at=now() WHERE id=$1",
            ctx.project_id, json.dumps({"element_kinds": kinds}, ensure_ascii=False),
        )
        return RunResult({"element_kinds": kinds})


@register
class VoiceSamplesStep(Step):
    """批量试听样本：遍历缺 sample 的音色 → TTS → OSS → 回写。单条失败不阻塞批量；
    整体失败不自动重试（TTS 欠费属终态，充值后手动再点）。"""

    kind = "gen_voice_samples"
    group = "音色"
    max_retries = 0
    run_note = "遍历缺 sample 的音色 → TTS → OSS → 回写 sample_audio_url（单条失败不阻塞批量）"
    timeout_s = 900

    async def run(self, ctx: Ctx) -> RunResult:
        from .voice_casting import generate_emotion_samples

        rows = await ctx.pool.fetch(
            "SELECT id, name, meta FROM kb_entries WHERE kind='voice' AND enabled ORDER BY id"
        )
        done_n, skip_n = 0, 0
        for row in rows:
            meta = _meta(row)
            if meta.get("samples") or not meta.get("voice_type"):  # 已有 5 情绪小样则跳过
                skip_n += 1
                continue
            try:  # 按角色定制的 5 情绪小样（人声）/ 单条拟声小样（兽鸣）
                res = await generate_emotion_samples(ctx.pool, row["id"])
                if res.get("samples"):
                    done_n += 1
            except Exception as e:  # noqa: BLE001 — 单条失败不阻塞批量
                log.warning("音色样本失败 %s: %s", row["name"], e)
        return RunResult({"generated": done_n, "skipped": skip_n})
