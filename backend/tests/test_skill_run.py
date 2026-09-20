"""P2 技能试运行测试：dry-run 装配契约 + 用量聚合 SQL 形状（2026-09-17）。"""
import asyncio
from unittest.mock import patch

import pytest

from backend.app.api import skill_run


class _FakePool:
    """只覆盖 skill_run 用到的三个入口；SQL 原样透传给桩。"""

    def __init__(self, skill_row=None, usage_rows=None, total_row=None):
        self.skill_row = skill_row
        self.usage_rows = usage_rows or []
        self.total_row = total_row or {}
        self.calls = []

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        if "FROM skill_packages" in sql:
            return self.skill_row
        return self.total_row  # usage_total_sql

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        return True if "FROM skill_packages" in sql else None

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self.usage_rows


def _skill_row():
    # asyncpg.Record 用 dict 代替即可（skill_run 只按名取键）
    return {"slug": "outline-writer", "name": "大纲写手",
            "description": "写章节大纲", "skill_md": "# 大纲写法\n先列三幕。"}


def test_dry_run_charters_skill_md_and_sandboxes_tools():
    pool = _FakePool(skill_row=_skill_row())
    captured = {}

    async def fake_run(p, **kw):
        captured.update(kw)
        return {"output": "OK", "steps": [{"tool": "skill.read"}], "system": "s",
                "tools": ["skill.read"]}

    with patch.object(skill_run, "get_pool", return_value=pool), \
         patch.object(skill_run.agent_runtime, "run", side_effect=fake_run):
        out = asyncio.run(skill_run.dry_run(
            "outline-writer",
            skill_run.DryRunBody(task="给第 1 章写大纲", max_steps=6),
            user={"id": "sys_dev"}))
    assert out["output"] == "OK" and out["steps"]
    # 装配契约：charter=SKILL.md 全文；工具只留本地两把；无业务工具
    assert captured["charter"] == "# 大纲写法\n先列三幕。"
    assert captured["skills"] == ["outline-writer"]
    assert captured["tool_names"] == []
    assert captured["max_steps"] == 6
    assert captured["caller"] == "sys_dev"


def test_dry_run_404_when_not_installed():
    pool = _FakePool(skill_row=None)
    with patch.object(skill_run, "get_pool", return_value=pool):
        with pytest.raises(skill_run.HTTPException) as e:
            asyncio.run(skill_run.dry_run(
                "nope", skill_run.DryRunBody(task="x"), user={"id": "sys_dev"}))
    assert e.value.status_code == 404


def test_usage_sql_shape_and_day_clamp():
    sql, args = skill_run.usage_sql("outline-writer", 999)
    assert "$1" in sql and "args->>'slug'" in sql and "tool = 'skill.read'" in sql
    assert args[0] == "outline-writer" and args[1] == "90"  # 上限 90 天
    _, args2 = skill_run.usage_sql("outline-writer", 0)
    assert args2[1] == "1"  # 下限 1 天

    tsql, targs = skill_run.usage_total_sql("outline-writer", 30)
    assert "count(DISTINCT caller)" in tsql and targs[0] == "outline-writer"


def test_usage_endpoint_aggregates():
    pool = _FakePool(
        usage_rows=[{"caller": "sys_dev", "source": "agent", "day": "2026-09-17",
                     "calls": 3, "failures": 1, "avg_ms": 120}],
        total_row={"calls": 3, "failures": 1, "callers": 1, "avg_ms": 120,
                   "last_used_at": "2026-09-17T10:00:00+08:00"})
    with patch.object(skill_run, "get_pool", return_value=pool):
        out = asyncio.run(skill_run.usage("outline-writer", days=30,
                                          user={"id": "sys_dev"}))
    assert out["total"]["calls"] == 3 and out["total"]["failures"] == 1
    assert out["by_day"][0]["source"] == "agent"
    # 两条聚合都按 slug 过滤
    sql_calls = [c for c in pool.calls if c[0] in ("fetch", "fetchrow")]
    assert any("args->>'slug'" in c[1] for c in sql_calls)
