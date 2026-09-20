#!/usr/bin/env python3
"""全站把 tapnow 命名空间收敛成 tapflow（去掉 now）。

覆盖：源码标识符、目录名/文件名、路由 tab key、CSS 文件、注释、文档正文与文档文件名。
- Tapnow*/tapnow* -> Tapflow*/tapflow*（TapnowCanvas -> TapflowCanvas、tapnowData -> tapflowData）
- 顺带把先前一轮留下的 TapFlowPage/TapFlowModal 规整成单词形式 TapflowPage/TapflowModal
- 共享的 `Tap*` 家族（TapNode/TapEdge/TapFlowMeta/TapPickMenu…）本来就不含 now，不动
- `TapNow`（大写 N）是被复刻的外部产品名，默认保留；要一起改传 --brand

用法：
    python scripts/rename_tapflow.py --dry-run   # 只打印将要发生的改动
    python scripts/rename_tapflow.py             # 真正执行（重命名走 git mv）
    python scripts/rename_tapflow.py --brand     # 连外部产品名 TapNow 一起改
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 目录黑名单：构建产物 / 依赖 / 备份，改了没意义还容易误伤
SKIP_DIRS = {
    '.git', 'node_modules', 'dist', 'build', '.venv', 'venv', '__pycache__',
    '.next', '.vite', 'coverage', 'backups', '.idea', '.vscode',
}
# 只改这些扩展名的文本文件；截图等二进制只参与「改名」不参与「改内容」
TEXT_EXT = {
    '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.css', '.scss',
    '.py', '.sql', '.md', '.json', '.yml', '.yaml', '.html', '.txt', '.env',
}

PATTERN = re.compile(r'tapnow', re.IGNORECASE)
# 被复刻的外部产品名，默认不动（否则「1:1 复刻 TapNow 风格」会变成假话）
BRAND = 'TapNow'
# 上一轮 tapnowflow -> TapFlow 留下的驼峰，统一成单词形式，和 TapflowCanvas 对齐
LEGACY = re.compile(r'TapFlow(Page|Modal)')

# 本脚本自身（含大量待替换字面量）不参与改写
SELF = Path(__file__).resolve()
# AdminView 里的 LEGACY_TABS 存的是旧 URL 字面量（tapnowflow/tapnow），改了老书签就废了
KEEP_AS_IS = {ROOT / 'frontend' / 'src' / 'features' / 'admin' / 'AdminView.tsx'}


def replacement(m: re.Match[str]) -> str:
    """按原词的大小写风格产出对应的 tapflow 写法。"""
    s = m.group(0)
    if s == BRAND and not CONVERT_BRAND:
        return s
    if s.isupper():        # TAPNOW  -> TAPFLOW
        return 'TAPFLOW'
    if s.islower():        # tapnow  -> tapflow
        return 'tapflow'
    if s[0].islower():     # tapNow  -> tapFlow
        return 'tapFlow'
    return 'Tapflow'       # Tapnow / TapNow -> Tapflow


CONVERT_BRAND = False  # True = 连 TapNow 品牌名也改（--brand）


def convert(text: str) -> str:
    return LEGACY.sub(r'Tapflow\1', PATTERN.sub(replacement, text))


def git_tracked(path: Path) -> bool:
    r = subprocess.run(['git', 'ls-files', '--error-unmatch', str(path)],
                       cwd=ROOT, capture_output=True)
    return r.returncode == 0


def git_mv(src: Path, dst: Path) -> bool:
    r = subprocess.run(['git', 'mv', str(src), str(dst)], cwd=ROOT, capture_output=True)
    return r.returncode == 0


def walk() -> tuple[list[Path], list[Path]]:
    """返回 (文件, 目录)，均已剔除黑名单目录与脚本自身。"""
    files: list[Path] = []
    dirs: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for d in dirnames:
            dirs.append(Path(dirpath) / d)
        for name in filenames:
            p = Path(dirpath) / name
            if p.resolve() != SELF and p not in KEEP_AS_IS:
                files.append(p)
    return files, dirs


def move(src: Path, dst: Path) -> None:
    """tracked 的走 git mv 保留改名历史；git mv 失败（untracked/混合）退回文件系统改名。"""
    if not (git_tracked(src) and git_mv(src, dst)):
        src.rename(dst)


def rename(path: Path, renamed: list[tuple[Path, Path]], dry: bool) -> None:
    new_name = convert(path.name)
    # 比字符串而不是 Path：WindowsPath 的 == 大小写不敏感，会漏掉纯大小写改名
    if new_name == path.name:
        return
    target = path.with_name(new_name)
    renamed.append((path.relative_to(ROOT), target.relative_to(ROOT)))
    if dry:
        return
    # 只差大小写（TapFlowPage -> TapflowPage）：Windows 文件系统不区分大小写，
    # target.exists() 恒真且直接改名会被忽略，必须借道临时名两步走
    if target.name.lower() == path.name.lower():
        tmp = path.with_name(path.name + '.casetmp')
        move(path, tmp)
        move(tmp, target)
        return
    if target.exists():
        print(f'!! target exists, skipped: {target}', file=sys.stderr)
        return
    move(path, target)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='只打印，不落盘')
    ap.add_argument('--brand', action='store_true', help='连外部产品名 TapNow 一起改')
    args = ap.parse_args()

    global CONVERT_BRAND
    CONVERT_BRAND = args.brand

    edited: list[tuple[Path, int]] = []
    renamed: list[tuple[Path, Path]] = []
    skipped: list[Path] = []

    files, _ = walk()

    # 1) 改内容
    for f in files:
        if f.suffix.lower() not in TEXT_EXT:
            continue
        try:
            src = f.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            skipped.append(f)
            continue
        dst = convert(src)
        if dst == src:
            continue
        edited.append((f.relative_to(ROOT), len(PATTERN.findall(src))))
        if not args.dry_run:
            # 统一 UTF-8 无 BOM 写回，保留原换行（newline='' 不做转换）
            with open(f, 'w', encoding='utf-8', newline='') as fh:
                fh.write(dst)

    # 2) 先改文件名，再改目录名；两轮都自底向上，避免父目录先改导致子路径失效
    files, dirs = walk()
    for f in sorted(files, key=lambda p: len(p.parts), reverse=True):
        rename(f, renamed, args.dry_run)
    for d in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        if d.exists():          # dry-run 下父目录未改，路径仍有效；实跑时逐层收敛
            rename(d, renamed, args.dry_run)

    # 输出走纯 ASCII：Windows 控制台默认 GBK，中文提示会变乱码
    tag = '[dry-run] ' if args.dry_run else ''
    print(f'{tag}rewritten files: {len(edited)}')
    for p, n in edited:
        print(f'  {p}  ({n} hits)')
    print(f'{tag}renamed paths: {len(renamed)}')
    for a, b in renamed:
        print(f'  {a}  ->  {b}')
    if skipped:
        print(f'(skipped {len(skipped)} non-UTF-8 files)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
