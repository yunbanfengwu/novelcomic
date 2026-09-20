"""流式目录/核心要素（2026-07-14）：与流式粗拆（storyboard_stream）同一契约——
LLM 按固定 Markdown 逐条输出（流式逐 token 接收），增量解析：识别到完整一条
立即落库并回调（NDJSON 逐行推送前端：一条存一条、前端实时显示一条）。

为什么定死 MD 而不是 JSON：JSON 必须收到闭合括号才能解析（天然反流式），
截断=整包作废（目录/要素一次性 JSON 生成正因此报「LLM 未返回可解析 JSON」）；
MD 以「## 章N / ## 要素N」为块边界，每块独立可解析，截断只损失最后半条。
流式异常或零产出自动回退一次性 JSON 版（与拆镜同策略，绝不比改造前更差）。
"""
import logging
import re
from typing import Any, Awaitable, Callable

import asyncpg

from .. import llm
from . import pipeline, volumes

log = logging.getLogger("pipeline_stream")

# ═══════════ MD 解析原语（与 storyboard_stream 同一容错契约）═══════════

_FIELD = re.compile(r"^\s*[-*]?\s*\*{0,2}([^:：*\s][^:：*]{0,11}?)\*{0,2}\s*[:：]\s*(.*)$")


def _clean(v: str) -> str:
    return v.strip().strip("*").strip()


async def _stream_md_items(
    system: str, user: str, head: re.Pattern[str],
    parse: Callable[[str], dict[str, Any] | None],
    on_item: Callable[[dict[str, Any], int], Awaitable[None]],
    temperature: float = 0.6, max_tokens: int = 8000,
) -> list[dict[str, Any]]:
    """流式接收 MD：出现下一个块标题即判定上一块完整 → 解析并回调 on_item(item, 已解析条数)；
    流结束后冲洗最后一块。返回全部解析成功的条目。"""
    buf = ""
    items: list[dict[str, Any]] = []

    async def emit(block: str) -> None:
        it = parse(block)
        if it:
            items.append(it)
            await on_item(it, len(items))

    async for delta in llm.chat_stream(system, user, temperature=temperature, max_tokens=max_tokens):
        buf += delta
        while True:  # 单个 delta 可能带出多个完整块（提供商大颗粒转发）
            heads = list(head.finditer(buf))
            if len(heads) < 2:
                break
            await emit(buf[heads[0].start():heads[1].start()])
            buf = buf[heads[1].start():]
    heads = list(head.finditer(buf))
    if heads:
        await emit(buf[heads[0].start():])
    return items


# ═══════════ 章节：MD 模板与解析 ═══════════

CHAPTERS_MD_FORMAT = """严格按以下 Markdown 模板逐章输出：从「## 章1」开始，每章一个区块、每字段独占一行；
不得输出 JSON、代码围栏、前言、总结或任何模板之外的文本。
## 章1
- 标题: 章节名
- 简介: 本章故事发展简介流水账（60-120字：谁做了什么、局势如何变化，含伏笔标注（伏笔：xxx）（回收：xxx））"""

_CHAP_HEAD = re.compile(r"^#{1,4}\s*(?:章\s*\d+|第\s*\d+\s*[章集])\D*$", re.M)
_C_KEYMAP = {"标题": "title", "章节名": "title", "题目": "title",
             "简介": "summary", "概要": "summary", "故事线": "summary", "流水账": "summary"}


def parse_md_chapter(block: str) -> dict[str, Any] | None:
    """一章的 MD 区块 → {title, summary}。seq 由落库方按序分配（模型不参与编号）。"""
    lines = block.strip().splitlines()
    if not lines or not _CHAP_HEAD.match(lines[0].strip()):
        return None
    ch: dict[str, str] = {}
    last: str | None = None
    for raw in lines[1:]:
        m = _FIELD.match(raw)
        key = _C_KEYMAP.get(_clean(m.group(1))) if m else None
        if key:
            ch[key] = _clean(m.group(2))
            last = key
        elif raw.strip() and last == "summary":  # 简介换行续写并入
            ch[last] = f"{ch[last]}{raw.strip()}"
    if not (ch.get("title") or ch.get("summary")):
        return None  # 只有标题行的碎块（截断尾巴）不算一章
    # 模型偶把「第N章」编号写进标题——序号由代码分配且 UI 单独展示，剥掉避免"4 第4章 xxx"
    title = re.sub(r"^第\s*\d+\s*[章集]\s*[:：·\-—]?\s*", "", ch.get("title", ""))
    return {"title": title, "summary": ch.get("summary", "")}


# ═══════════ 要素：MD 模板与解析 ═══════════

_ELEMENTS_MD_SYS = """你是小说设定集架构师。基于项目信息与章节目录，抽取/设计核心要素。
类型只能取：__KINDS__。
判定规则：
- 发声形态（仅角色）：speech=说人话的角色（含拟人化动物，如疯狂动物城）/call=真动物只发叫声/
  hybrid=以鸣叫为主偶有传意/silent=不发声——依据角色在故事中的实际呈现形态而非物种本身。
- 需要设定图：有具体视觉形象、可出设定图的实体（角色、场景，及有实物形态的设定如法宝/器物/服饰）填 是；
  抽象要素（剧情线/冲突线/伏笔，及无实物的规则体系类设定）填 否。
- 需要配音：仅当角色真正发声（发声形态为 speech/call/hybrid）填 是；silent 角色与一切非角色要素填 否。
- 形态（仅角色，可省）：若角色有身份/阶段/形态的**显著外形变化**（变身如平民↔超级英雄、境遇剧变如乞丐↔皇后、
  大跨度年龄、易容伪装等，凡"看起来明显不同、需各自一张设定图"的），列出每个形态，格式
  「简短形态名=何时呈现此形态的一句话剧情条件」，多个形态用「；」分隔；只有单一稳定形象的角色省略此行。
  此处只出形态名与触发剧情、不产外貌（外貌由后置档案补全逐形态生成）。
- 出现章节：依据目录故事线给出预计出现的章节号列表。

严格按以下 Markdown 模板逐个要素输出：从「## 要素1」开始，每个要素一个区块、每字段独占一行；
非角色要素省略「处境/目标/关系/发声形态/发声语言/音色气质/形态」各行；
（角色外貌不在此产出——由后置「角色档案补全」按项目年代背景逐个生成，此处只给名称/简介/状态/发声/形态/出现章节）
不得输出 JSON、代码围栏、前言、总结或任何模板之外的文本。
## 要素1
- 类型: character
- 名称: 要素名
- 简介: 要素简介(40-100字)
- 处境: 角色当前处境一句话
- 目标: 角色目标一句话
- 关系: 与其他角色的关系一句话
- 发声形态: speech
- 发声语言: 中文人声（call/silent 填叫声描述或 无）
- 音色气质: 一句话（如"低哑沧桑的中年男声"）
- 需要设定图: 是
- 需要配音: 是
- 形态: 乞丐=沦落街头行乞时；皇后=登基后凤袍加身（无显著形态变化则删除此行）
- 出现章节: 1、2、5"""


def elements_md_sys(kinds: list[dict[str, str]], suffix: str = "") -> str:
    """要素 MD 系统提示词：kind 枚举按项目已判定的要素类型动态织入（与 JSON 版 _elements_sys 同构）。"""
    line = "/".join(f"{k['code']}({k['label']})" for k in kinds)
    return _ELEMENTS_MD_SYS.replace("__KINDS__", line) + suffix


_ELEM_HEAD = re.compile(r"^#{1,4}\s*要素\s*\d+\D*$", re.M)
_E_KEYMAP = {
    "类型": "kind", "名称": "name", "名字": "name", "简介": "brief", "描述": "brief",
    "处境": "s_处境", "目标": "s_目标", "关系": "s_关系",
    "外貌提示词": "外貌提示词", "外貌": "外貌提示词",
    "发声形态": "vocal_mode", "发声语言": "language", "音色气质": "timbre_brief",
    "需要设定图": "needs_image", "需要配音": "needs_voice",
    "形态": "variants_raw", "身份形态": "variants_raw",
    "出现章节": "appears_in", "出现": "appears_in",
}


def _parse_variants_raw(v: str | None) -> list[dict[str, str]]:
    """解析 MD 单行形态串「乞丐=沦落街头时；皇后=登基后」→ [{tag,desc}]。"""
    out: list[dict[str, str]] = []
    for part in re.split(r"[；;]", v or ""):
        part = part.strip()
        if not part:
            continue
        m = re.split(r"[=＝:：]", part, maxsplit=1)
        tag = m[0].strip()
        if tag and tag not in ("无", "默认"):
            out.append({"tag": tag, "desc": (m[1].strip() if len(m) > 1 else "")})
    return out
_KIND_ALIASES = (  # 内置类型兜底别名：值可能形如 "character（角色）"，按包含匹配
    ("character", "character"), ("角色", "character"), ("scene", "scene"), ("场景", "scene"),
    ("plotline", "plotline"), ("剧情线", "plotline"), ("阴谋线", "plotline"),
    ("conflict", "conflict"), ("冲突", "conflict"), ("foreshadow", "foreshadow"), ("伏笔", "foreshadow"),
    ("setting", "setting"), ("设定", "setting"),
)


def _norm_kind(v: str, kinds: list[dict[str, str]]) -> str:
    """类型归一：先按项目动态类型（code/label 包含匹配，长者优先），再走内置别名，最后 setting。"""
    s = (v or "").strip().lower()
    for k in sorted(kinds, key=lambda k: -len(k["code"])):
        if k["code"].lower() in s or (k.get("label") or "") in s:
            return k["code"]
    for alias, canon in _KIND_ALIASES:
        if alias in s:
            return canon
    return "setting"


def _norm_vocal(v: str | None) -> str:
    s = (v or "").strip().lower()
    for mode in ("silent", "hybrid", "call", "speech"):
        if mode in s:
            return mode
    return "speech"


def _parse_bool(v: str | None) -> bool | None:
    s = (v or "").strip().lower()
    if not s:
        return None
    if s.startswith(("是", "y", "t", "1", "需要")):
        return True
    if s.startswith(("否", "n", "f", "0", "无", "不")):
        return False
    return None


def parse_md_element(block: str, kinds: list[dict[str, str]]) -> dict[str, Any] | None:
    """一个要素的 MD 区块 → 与 JSON 版 gen_elements 同构的要素字典（供 _save_element 落库）。"""
    lines = block.strip().splitlines()
    if not lines or not _ELEM_HEAD.match(lines[0].strip()):
        return None
    f: dict[str, str] = {}
    last: str | None = None
    for raw in lines[1:]:
        m = _FIELD.match(raw)
        key = _E_KEYMAP.get(_clean(m.group(1))) if m else None
        if key:
            f[key] = _clean(m.group(2))
            last = key
        elif raw.strip() and last == "brief":
            f[last] = f"{f[last]}{raw.strip()}"
    name = (f.get("name") or "").strip()
    if not name:
        return None  # 无名碎块（截断尾巴）不算一个要素
    kind = _norm_kind(f.get("kind", ""), kinds)
    if kind == "character":
        state: dict[str, Any] = {"处境": f.get("s_处境", ""), "目标": f.get("s_目标", ""), "关系": f.get("s_关系", "")}
    elif kind in ("plotline", "conflict"):
        state = {"进度": "未开始"}
    else:
        state = {}
    meta: dict[str, Any] = {}
    if kind == "character":
        vm = _norm_vocal(f.get("vocal_mode"))
        meta["外貌提示词"] = f.get("外貌提示词", "")
        meta["voice_profile"] = {
            "vocal_mode": vm,
            "language": f.get("language") or ("中文人声" if vm == "speech" else "无"),
            "timbre_brief": f.get("timbre_brief", ""),
        }
        vraw = _parse_variants_raw(f.get("variants_raw"))
        if len(vraw) >= 2:  # 单一形态无需 variants（_save_element 亦会兜底剔除）
            meta["variants"] = vraw
    for fld in ("needs_image", "needs_voice"):
        val = _parse_bool(f.get(fld))
        if val is not None:  # 缺省交由 _save_element 按类型兜底
            meta[fld] = val
    return {"kind": kind, "name": name, "brief": f.get("brief", ""), "state": state, "meta": meta,
            "appears_in": [int(x) for x in re.findall(r"\d+", f.get("appears_in", ""))]}


# ═══════════ 编排：流式生成 + 逐条落库 + 回退 ═══════════

OnItem = Callable[[dict[str, Any]], Awaitable[None]]

_CHAPTER_INSERT = ("INSERT INTO content_nodes (project_id, parent_id, kind, seq, title, summary) "
                   "VALUES ($1,$2,'chapter',$3,$4,$5) RETURNING id, seq, title, summary, status")


async def stream_outline(
    pool: asyncpg.Pool, project_id: int, count: int, on_chapter: OnItem,
) -> list[dict[str, Any]]:
    """流式生成整本目录：清场旧章后解析到一章落库一章；零产出回退一次性 JSON 版。"""
    async with pool.acquire() as conn:
        project = await conn.fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
    if not project:
        raise ValueError("项目不存在")
    # 全量重建目录=回到「无卷」形态（隐式卷1）：删旧卷+旧章，逐章以 parent_id=NULL 挂入
    await pool.execute(
        "DELETE FROM content_nodes WHERE project_id=$1 AND kind IN ('chapter','volume')", project_id)
    saved: list[dict[str, Any]] = []

    async def on_item(c: dict[str, Any], n: int) -> None:
        if n > count:
            return
        r = await pool.fetchrow(_CHAPTER_INSERT, project_id, None, len(saved) + 1,
                                c.get("title", ""), c.get("summary", ""))
        saved.append(dict(r))
        await on_chapter(saved[-1])

    system = pipeline._OUTLINE_RULES + "\n" + CHAPTERS_MD_FORMAT
    try:
        await _stream_md_items(system, pipeline._outline_user(project, count),
                               _CHAP_HEAD, parse_md_chapter, on_item)
    except Exception as e:  # noqa: BLE001 — 提供商不支持流式/格式崩坏均回退，不让生成挂死
        log.warning("项目 %s 流式目录失败（已存 %d 章）: %s", project_id, len(saved), e)
    if not saved:
        rows = await pipeline.build_outline(pool, project_id, count)  # 回退含清场+状态推进
        for r in rows:
            await on_chapter(r)
        return rows
    await pool.execute(
        "UPDATE content_projects SET status='outline_ready', updated_at=now() WHERE id=$1", project_id)
    log.info("项目 %s 流式目录落库 %d 章", project_id, len(saved))
    return saved


async def stream_append_chapters(
    pool: asyncpg.Pool, project_id: int, requirement: str, on_chapter: OnItem,
) -> list[dict[str, Any]]:
    """流式新增（续写）章节：解析到一章落库一章（seq 由代码顺排，上限30）；
    尚无目录时转为流式生成整本初始目录；零产出回退一次性 JSON 版。"""
    async with pool.acquire() as conn:
        project = await conn.fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
        if not project:
            raise ValueError("项目不存在")
        rows = await conn.fetch(
            "SELECT seq, title, summary FROM content_nodes "
            "WHERE project_id=$1 AND kind='chapter' ORDER BY seq", project_id,
        )
    if not rows:
        return await stream_outline(pool, project_id, pipeline._suggested_chapters(project), on_chapter)
    next_seq = max(r["seq"] for r in rows) + 1
    vol_id = await volumes.last_volume_id(pool, project_id)  # 续写落到最后一卷；无卷则留空(隐式卷1)
    saved: list[dict[str, Any]] = []

    async def on_item(c: dict[str, Any], n: int) -> None:
        if n > 30:
            return
        seq = next_seq + len(saved)
        r = await pool.fetchrow(_CHAPTER_INSERT, project_id, vol_id, seq,
                                c.get("title") or f"第{seq}章", c.get("summary", ""))
        saved.append(dict(r))
        await on_chapter(saved[-1])

    system = pipeline._APPEND_RULES + "\n" + CHAPTERS_MD_FORMAT
    try:
        await _stream_md_items(system, pipeline._append_chapters_user(project, rows, requirement, next_seq),
                               _CHAP_HEAD, parse_md_chapter, on_item)
    except Exception as e:  # noqa: BLE001
        log.warning("项目 %s 流式续写失败（已存 %d 章）: %s", project_id, len(saved), e)
    if saved:
        log.info("项目 %s 流式续写落库 %d 章", project_id, len(saved))
        return saved
    rows_ = await pipeline.append_chapters(pool, project_id, requirement)
    for r in rows_:
        await on_chapter(r)
    return rows_


async def stream_elements(
    pool: asyncpg.Pool, project_id: int, requirement: str,
    on_chapter: OnItem, on_element: OnItem,
) -> list[dict[str, Any]]:
    """流式生成核心要素：解析到一个落库一个（upsert+出现索引预填）；
    要求留空=依目录全量抽取（无目录先流式建目录，章节同样逐条推送）；零产出回退一次性 JSON 版。"""
    requirement = (requirement or "").strip()
    async with pool.acquire() as conn:
        project = await conn.fetchrow("SELECT * FROM content_projects WHERE id=$1", project_id)
        if not project:
            raise ValueError("项目不存在")
        nodes = await conn.fetch(
            "SELECT id, seq, title, summary FROM content_nodes "
            "WHERE project_id=$1 AND kind='chapter' ORDER BY seq", project_id,
        )
    if not nodes and not requirement:
        await stream_outline(pool, project_id, pipeline._suggested_chapters(project), on_chapter)
        async with pool.acquire() as conn:
            nodes = await conn.fetch(
                "SELECT id, seq, title, summary FROM content_nodes "
                "WHERE project_id=$1 AND kind='chapter' ORDER BY seq", project_id,
            )
    chapters = [dict(n) for n in nodes]
    seq_to_node = {c["seq"]: c["id"] for c in chapters}
    kinds = pipeline.project_element_kinds(project)
    if requirement:
        async with pool.acquire() as conn:
            existing = await conn.fetch(
                "SELECT kind, name, brief FROM content_elements WHERE project_id=$1 ORDER BY kind, id",
                project_id,
            )
        system = elements_md_sys(kinds, pipeline._ADD_ELEMENTS_SUFFIX)
        user = pipeline._add_elements_user(project, chapters, existing, requirement)
        cap = 20
    else:
        system = elements_md_sys(kinds)
        user = pipeline._elements_user(project, chapters)
        cap = 50
    saved: list[dict[str, Any]] = []

    async def on_item(e: dict[str, Any], n: int) -> None:
        if n > cap:
            return
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await pipeline._save_element(conn, project_id, e, seq_to_node)
        saved.append(row)
        await on_element(row)

    try:
        await _stream_md_items(system, user, _ELEM_HEAD,
                               lambda b: parse_md_element(b, kinds), on_item, temperature=0.5)
    except Exception as e:  # noqa: BLE001
        log.warning("项目 %s 流式要素失败（已存 %d 个）: %s", project_id, len(saved), e)
    if saved:
        await pool.execute(
            "UPDATE content_projects SET status='elements_ready', updated_at=now() WHERE id=$1", project_id)
        log.info("项目 %s 流式要素落库 %d 个", project_id, len(saved))
        return saved
    if requirement:
        return await _fallback_add(pool, project_id, requirement, on_element)
    rows = await pipeline.build_elements(pool, project_id)
    for r in rows:
        await on_element(r)
    return rows


async def _fallback_add(
    pool: asyncpg.Pool, project_id: int, requirement: str, on_element: OnItem,
) -> list[dict[str, Any]]:
    rows = await pipeline.add_elements_ai(pool, project_id, requirement)
    for r in rows:
        await on_element(r)
    return rows
