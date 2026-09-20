"""提示词双字段（用户 2026-07-17 定稿）：系统锚定提示词(anchor) × 用户提示词(user)。

分工（用户拍板「锚定段只放结构句」）：
- user 段 = 叙事内容（画面/动作/时间轴/外貌/站位/场景光色）——系统装配预填、用户可改；
- anchor 段 = 结构句（画风锚词/一致性约束/禁文字字幕水印/质量词/运动约束/时长画质/版式规范）
  ——系统装配自动刷新（画风改了、规则升级了都能跟上），用户改过则打手编标记冻结；
- 编译全文 full = user ⊕ anchor（沿用原 {key} 字段）：提交/质检/展示等全部消费方零改动；
- 编辑框展示 user + 分隔线 + anchor（叙事在前与提交顺序一致），保存按分隔线拆回两段，
  变了哪段打哪段的 {key}_user_edited / {key}_anchor_edited 冻结标记；
- 提交兜底：media 层提交前统一剥离分隔线行（strip_dividers）——任何入口混入分隔线都不上模型；
- 历史数据不迁移：无 _anchor 段的旧行视为纯 full（编辑框无分隔线，保存走旧整段 {key}_edited 语义）。
"""
import re

# 编辑框两段之间的分隔线（独占一行）。同时兼容用户手写的「锚定提示词：」标题行形式
DIVIDER = "——————"
_DIV_LINE = re.compile(r"^\s*(?:[—\-_=]{4,}|锚定提示词[:：]?)\s*$", re.M)


def compose(user: str, anchor: str, sep: str = "。") -> str:
    """编译全文：user ⊕ anchor（任一为空只取另一段）。图片类传 sep=', '（英文锚词逗号衔接），
    视频/中文语境用默认句号。"""
    user, anchor = (user or "").strip(), (anchor or "").strip()
    if not user:
        return anchor
    if not anchor:
        return user
    return f"{user.rstrip('。, ')}{sep}{anchor}"


def join_for_edit(user: str, anchor: str) -> str:
    """两段 → 编辑框文本（user 在上、anchor 在下，中间分隔线）。"""
    user, anchor = (user or "").strip(), (anchor or "").strip()
    if not anchor:
        return user
    return f"{user}\n{DIVIDER}\n{anchor}"


def split_edit_text(text: str) -> tuple[str, str] | None:
    """编辑框文本 → (user, anchor)：按第一条分隔线行拆两段。
    无分隔线返回 None（调用方走旧整段语义——历史数据/用户删掉分隔线都兼容）。"""
    m = _DIV_LINE.search(text or "")
    if not m:
        return None
    return (text[:m.start()].strip(), text[m.end():].strip())


def strip_dividers(prompt: str) -> str:
    """提交前剥离分隔线行（用户要求「提交时去掉分割线」的兜底）：任何入口
    （弹框直传/AI 改写回填/手编）混入的分隔线都不发给模型；段落正文原样保留。"""
    if not prompt or not _DIV_LINE.search(prompt):
        return prompt
    lines = [ln for ln in prompt.splitlines() if not _DIV_LINE.match(ln)]
    return "\n".join(lines).strip()
