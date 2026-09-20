"""章级分镜总览宫格故事板：可选的连贯性约束环节（2026-07-12 起仅手动触发，不再强制自动生成）。

一集（章）N 个分镜拆成多张 3:2 宫格图（每张 6-15 格，宁多张不多格——格数越多版式遵循度越差），
一张=一次生成，格与格天然共享角色造型/空间方位/光源逻辑 → 约束镜头间连贯。
「按本张出图」批量首帧时把**整张宫格图**作参考图 + 固定引用句（"请参考故事板中第M格（镜K）…
注意前后分镜衔接"）；普通首帧/视频生成不自动挂载故事板。
不做裁切：裁切依赖模型严格守格线，裁错是静默错；整图引用最差只是构图参考弱化（用户 2026-07-12 定稿）。
"""
import io
import json
import math
from typing import Any

import asyncpg

from ..knowledge import get_block
from . import element_variants as ev
from . import volumes

# 宫格画布：3:2 横幅（用户 2026-07-11 定稿）。
# 尺寸 2400x1600：生图 API 要求 ≥3,686,400 像素（1536x1024 会被 400 拒收，
# 任务 836/886 实测），2400x1600=384 万像素且保持 3:2 版式不变。
PAGE_SIZE = "2400x1600"
_W, _H = 2400, 1600
_DIVIDER = 16  # 宽分割线（模板预画，模型不得改动——全模板唯一不许重绘的结构）
# 框架色（用户 2026-07-12 定稿）：底板/分割线/留空格统一用高饱和绿，改红色只需换此常量
_FRAME_COLOR = "#00A550"
# 格中央定位镜号的颜色（浅绿）：仅供模型识别"该格画哪一镜"，作画时被画面完全覆盖，
# 成图不得残留数字（用户 2026-07-12 定稿：序号居中可遮挡，成图无镜号）
_HINT_COLOR = "#9ADBB8"

# 版式兜底（kb 块 sheet/分镜宫格草图 可项目级覆盖风格词，行列由代码注入）。
# 彩色方案（用户 2026-07-12 定稿：黑白线稿效果不佳）：格内画全彩故事板画面，
# 构图/站位/动势清晰，人物造型与服色跨格一致（关联设定图作参考传入）
_DEFAULT_STYLE = (
    "vivid full-color storyboard panels, cinematic composition sketches, "
    "clear staging and blocking, expressive rough concept-art painting, "
    "consistent character designs and costume colors across panels, "
    "coherent spatial continuity between panels, no text, no numbers, no captions"
)

# 序号/留空文字字体：Windows 部署优先微软雅黑（含中文），全缺时回退 PIL 位图字体
_FONT_PATHS = (
    "C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def _font(size: int):
    from PIL import ImageFont

    for p in _FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_grid_template(rows: int, cols: int, shot_nos: list[int]) -> bytes:
    """代码预渲染宫格模板（确定性，零模型参与）：白格 + 绿色宽分割线 + **格中央浅绿定位镜号**
    + 尾部绿色留空格（标"此处留空"）。作参考图传入，模型在白格内画全彩故事板画面——
    中央镜号只用于告诉模型"该格画哪一镜"，作画时被画面完全覆盖（成图无数字）；
    分割线是唯一不得重绘的结构。根治格数不守/格序错乱（扩散模型画不准小数字）。"""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (_W, _H), _FRAME_COLOR)  # 底色即分割线色：先全绿再挖白格
    draw = ImageDraw.Draw(img)
    cw = (_W - _DIVIDER * (cols + 1)) / cols
    ch = (_H - _DIVIDER * (rows + 1)) / rows
    k = len(shot_nos)
    num_font = _font(max(48, int(ch * 0.4)))  # 大号居中：可被覆盖的定位提示，不是要保留的标注
    blank_font = _font(max(16, int(ch * 0.10)))
    for idx in range(rows * cols):
        r, c = divmod(idx, cols)
        x0 = round(_DIVIDER + c * (cw + _DIVIDER))
        y0 = round(_DIVIDER + r * (ch + _DIVIDER))
        x1, y1 = round(x0 + cw), round(y0 + ch)
        if idx < k:
            draw.rectangle((x0, y0, x1, y1), fill="white")
            # 格中央浅绿镜号：定位提示（模型被要求作画时完全覆盖，成图不留数字）
            no = str(shot_nos[idx])
            try:
                draw.text(((x0 + x1) / 2, (y0 + y1) / 2), no,
                          fill=_HINT_COLOR, font=num_font, anchor="mm")
            except (ValueError, TypeError):  # 位图字体不支持 anchor 的兜底
                draw.text((x0 + int(cw / 2) - 10, y0 + int(ch / 2) - 10), no,
                          fill=_HINT_COLOR, font=num_font)
        else:
            try:
                draw.text(((x0 + x1) / 2, (y0 + y1) / 2), "此处留空",
                          fill="white", font=blank_font, anchor="mm")
            except (ValueError, TypeError):
                pass  # 无中文字体：纯绿格本身已是"留空"语义
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# 版式白名单（用户 2026-07-12 定稿：单边≤4，4×4 封顶）：2×2 / 3×2 / 3×3 / 4×3 / 4×4
# （行/列，3:2 横幅列多于行）——容量 4/6/9/12/16，装不满的尾格模板预画纯黑留空。
# 上限收到 16：一板≤16镜也是详细分镜按板 LLM 展开的批量上限（每次输出≤16镜，不截断）
_MAX_PER_BOARD = 16
_LAYOUTS: tuple[tuple[int, tuple[int, int]], ...] = (
    (4, (2, 2)), (6, (2, 3)), (9, (3, 3)), (12, (3, 4)), (16, (4, 4)),
)


def board_sizes(n: int) -> list[int]:
    """一集 n 镜 → 每张宫格的格数序列：最少张数（每张≤16）后均分——
    16→[16]、18→[9,9]、30→[15,15]、17→[9,8]。"""
    boards = max(1, math.ceil(n / _MAX_PER_BOARD))
    base, extra = divmod(n, boards)
    return [base + (1 if i < extra else 0) for i in range(boards)]


def board_slices(shots: list) -> list[list]:
    """把有序镜头列表按 board_sizes 切成每板一段——详细分镜展开(before)与宫格出图(run)
    共用同一分板，保证镜↔板映射一致。"""
    out, pos = [], 0
    for k in board_sizes(len(shots)):
        out.append(shots[pos:pos + k])
        pos += k
    return out


def grid_layout(k: int) -> tuple[int, int]:
    """k 格 → 白名单里最小能装下的 (rows, cols)。"""
    for cap, rc in _LAYOUTS:
        if k <= cap:
            return rc
    return (4, 4)


async def assemble_overview_boards(
    pool: asyncpg.Pool, project_id: int, node_id: int
) -> list[dict[str, Any]]:
    """装配一集总览宫格故事板的逐张提示词（彩色方案 2026-07-12）。
    返回 [{no,rows,cols,shot_ids,shot_nos,scenes,prompt,element_refs}]——
    element_refs=本板出场要素的设定图（≤3，角色按出场频次+场景兜底），生成时作参考图。"""
    async with pool.acquire() as conn:
        chapter = await conn.fetchrow(
            "SELECT seq, title FROM content_nodes WHERE id=$1 AND kind='chapter'", node_id
        )
        project = await conn.fetchrow(
            "SELECT * FROM content_projects WHERE id=$1", project_id
        )
        project = await volumes.effective_for_chapter(conn, project, node_id)  # 画风跟随本章所属卷
        shots = await conn.fetch(
            "SELECT id, seq, summary, meta FROM content_nodes "
            "WHERE parent_id=$1 AND kind='shot' AND deleted_at IS NULL ORDER BY seq", node_id,
        )
        if not shots:
            raise ValueError("请先拆分镜")
        style_block = await get_block(conn, "sheet", "分镜宫格草图")
        # 全章涉及要素的设定图一次取全（板级再按出场频次挑）
        all_eids = sorted({
            eid for r in shots
            for eid in ((r["meta"] if isinstance(r["meta"], dict)
                         else json.loads(r["meta"] or "{}")).get("element_ids") or [])
        })
        elem_rows = await conn.fetch(
            "SELECT id, kind, name, meta FROM content_elements "
            "WHERE project_id=$1 AND id = ANY($2::bigint[])", project_id, all_eids,
        ) if all_eids else []
    # 取图统一走 effective_meta（多形态按本章剧本语料选形态，与逐镜首帧同一套选图逻辑）
    _corpus = " ".join(r["summary"] or "" for r in shots)
    sheet_map = {}
    for e in elem_rows:
        em = e["meta"] if isinstance(e["meta"], dict) else json.loads(e["meta"] or "{}")
        em = ev.effective_meta(em, _corpus)
        if em.get("sheet_url"):
            sheet_map[e["id"]] = {"name": e["name"], "kind": e["kind"], "url": em["sheet_url"]}

    style = style_block["positive"] if style_block else _DEFAULT_STYLE
    slices = board_slices(list(shots))
    boards: list[dict[str, Any]] = []
    for bi, batch in enumerate(slices, start=1):
        k = len(batch)
        rows, cols = grid_layout(k)
        lines = [
            style,  # 版式不进提示词（格线/定位镜号/留空由模板参考图预画），风格块只管画面质感
            f"项目画风：{project['art_style'] or ''}",
            f"第{chapter['seq']}集《{chapter['title']}》分镜故事板宫格 第{bi}/{len(slices)}张："
            f"{rows}行×{cols}列共{k}个白格，从左到右、从上到下依次为——",
        ]
        scenes: list[str] = []
        eid_freq: dict[int, int] = {}   # 本板要素出场频次（挑参考图用）
        for j, r in enumerate(batch, start=1):
            m = r["meta"] if isinstance(r["meta"], dict) else json.loads(r["meta"] or "{}")
            chars = "、".join(m.get("characters") or [])
            sc = m.get("scene_element") or m.get("scene") or ""
            if sc and sc != "无" and sc not in scenes:
                scenes.append(sc)
            for eid in m.get("element_ids") or []:
                eid_freq[eid] = eid_freq.get(eid, 0) + 1
            lines.append(
                f"格{j}（镜{m.get('shot_no', r['seq'])}）[{m.get('scale', '')}·{m.get('angle', '')}"
                f"·{m.get('camera_move', '')}]：{(r['summary'] or '')[:30]}"
                + (f"（出场：{chars}）" if chars else "")
            )
        lines.append(
            "要求：每格是一幅**全彩故事板画面**——构图、站位与动势清晰，色彩与光线服务本镜情绪，"
            "整张遵循项目画风；同一角色的造型与服色在所有格中保持一致（有设定图的严格按设定图还原）；"
            "相邻格空间方位与视线方向连贯，同一场景的格共享同一空间；"
            "严禁在画面中书写任何文字与数字（格中央的定位数字要用画面完全覆盖），严禁对白框与水印"
        )
        # 本板参考图：角色设定图按出场频次降序，场景设定图兜底，≤3（生图共4槽，模板占1）
        ranked = sorted(eid_freq.items(), key=lambda t: -t[1])
        refs = [sheet_map[eid] for eid, _ in ranked if eid in sheet_map]
        element_refs = ([r for r in refs if r["kind"] == "character"]
                        + [r for r in refs if r["kind"] == "scene"])[:3]
        boards.append({
            "no": bi, "rows": rows, "cols": cols,
            "shot_ids": [r["id"] for r in batch],
            "shot_nos": [
                str((r["meta"] if isinstance(r["meta"], dict) else json.loads(r["meta"] or "{}"))
                    .get("shot_no", r["seq"])) for r in batch  # 统一字符串：手动插入镜号含小数
            ],
            "scenes": scenes,  # 本张覆盖的场景要素（详情标注：前端展示 + 人审对照）
            "element_refs": element_refs,
            "prompt": "\n".join(lines),
        })
    return boards
