"""镜号（shot_no）与排序键（seq）解耦的纯逻辑（零 IO）。

设计（2026-07-16 定稿，见 memory 讨论）：
- content_nodes.seq（INT）是**唯一排序键**，全站 ORDER BY seq；插入镜时用大步长留间隙 + 中点法
  取值，间隙耗尽时惰性把兄弟按 SEQ_STEP 重排（相对顺序不变、shot_no 不变）——由 shots.py 落库侧执行。
- meta.shot_no 只是**展示镜号**：拆镜时为连续整数 1..N；手动插入镜时生成一个「介于前后两镜之间」的
  人类可读十进制点分号（8 与 9 之间→8.5；8.1 与 8.2 之间→8.15），永不参与任何数值排序。
- 删除镜只删该行，不重排、不回收镜号——被删镜号自然「永久保留、不复用」（其它镜 shot_no 不动）。

镜号按**十进制数值**理解（8.11 位于 8.1 与 8.2 之间：8.10 < 8.11 < 8.20），用 Decimal 避免浮点误差。
"""
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

# 拆镜/重排时兄弟 seq 的基础步长：相邻镜留 SEQ_STEP 的整数间隙，足够多次二分插入
SEQ_STEP = 1000


def _to_dec(label: object) -> Decimal:
    """镜号（int / str / Decimal）→ Decimal。异常镜号（空/非数字）兜底为 0。"""
    try:
        return Decimal(str(label))
    except Exception:  # noqa: BLE001
        return Decimal(0)


def _fmt(d: Decimal) -> str:
    """Decimal → 最简定点字符串（去尾零、无科学计数法）：8.50→'8.5'，13→'13'，0.5→'0.5'。"""
    d = d.normalize()
    if d == d.to_integral_value():
        d = d.to_integral_value()
    return format(d, "f")


def _shortest_between(a: Decimal, b: Decimal) -> str:
    """求一个小数位尽量少、且严格落在开区间 (a, b) 内、尽量靠近中点的十进制镜号。
    a<b 前提；异常兜底返回真中点。8 与 9→8.5；8.1 与 8.2→8.15。"""
    if a >= b:  # 兜底：调用方保证 a<b，这里防御异常镜号
        return _fmt(a + Decimal("0.5"))
    for p in range(0, 9):  # 逐级放开小数位，命中即为最短
        q = Decimal(1).scaleb(-p)  # 10^-p
        mid = ((a + b) / 2).quantize(q, rounding=ROUND_HALF_UP)
        if a < mid < b:
            return _fmt(mid)
    return _fmt((a + b) / 2)


def between_labels(prev: object | None, nxt: object | None) -> str:
    """生成严格介于前一镜(prev)与后一镜(nxt)镜号之间的可读镜号。
    None 表示无边界：prev=None 插到最前；nxt=None 追加到最后；两者皆 None=空章第一镜。"""
    if prev is None and nxt is None:
        return "1"
    if prev is None:  # 插到最前：0 与 nxt 之间最短小数（如 nxt='1'→'0.5'）
        return _shortest_between(Decimal(0), _to_dec(nxt))
    if nxt is None:  # 追加到最后：floor(prev)+1，保证 > prev（'12'→'13'，'8.5'→'9'）
        return _fmt(_to_dec(prev).to_integral_value(rounding=ROUND_FLOOR) + 1)
    return _shortest_between(_to_dec(prev), _to_dec(nxt))
