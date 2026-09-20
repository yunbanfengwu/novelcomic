"""P5 团队 ACL 测试：判定纯函数 + assert_project_access SQL 闭环（2026-09-17）。"""
import asyncio
from unittest.mock import patch

import pytest

from backend.app.services import teams


# ── decide_access：单点判定的所有分支 ─────────────────────────────────────

def test_owner_always_full_access():
    assert teams.decide_access(owner_id="u1", is_member=False, any_write=False,
                               user_id="u1", write=False)
    assert teams.decide_access(owner_id="u1", is_member=False, any_write=False,
                               user_id="u1", write=True)


def test_member_read_ok_write_needs_share_flag():
    assert teams.decide_access(owner_id="boss", is_member=True, any_write=False,
                               user_id="u2", write=False), "只读分享可读"
    assert not teams.decide_access(owner_id="boss", is_member=True, any_write=False,
                                   user_id="u2", write=True), "只读分享不可写"
    assert teams.decide_access(owner_id="boss", is_member=True, any_write=True,
                               user_id="u2", write=True), "可写分享可写"


def test_non_member_denied_even_for_write_flag():
    assert not teams.decide_access(owner_id="boss", is_member=False, any_write=True,
                                   user_id="u3", write=False)
    assert not teams.decide_access(owner_id="boss", is_member=False, any_write=True,
                                   user_id="u3", write=True)


# ── assert_project_access：SQL 闭环（假 pool）────────────────────────────

class _FakePool:
    def __init__(self, row):
        self.row = row
        self.captured = None

    async def fetchrow(self, sql, *args):
        assert "content_projects" in sql and "team_members" in sql
        self.captured = args
        return self.row


def _row(owner="boss", member=True, write=False):
    # asyncpg.Record 按名取键 → dict 顶替
    return {"owner_id": owner, "is_member": member, "any_write": write}


def test_assert_project_access_owner_passes():
    pool = _FakePool(_row(owner="sys_dev"))
    asyncio.run(teams.assert_project_access(pool, 1, "sys_dev", write=True))


def test_assert_project_access_member_read_only():
    pool = _FakePool(_row(owner="boss", member=True, write=False))
    asyncio.run(teams.assert_project_access(pool, 1, "u2"))  # 读 OK
    with pytest.raises(teams.AccessDenied):
        asyncio.run(teams.assert_project_access(pool, 1, "u2", write=True))


def test_assert_project_access_unknown_project_404():
    pool = _FakePool(None)
    with pytest.raises(teams.NotFound):
        asyncio.run(teams.assert_project_access(pool, 999, "u1"))


def test_assert_project_access_writes_are_gated():
    pool = _FakePool(_row(owner="boss", member=True, write=True))
    asyncio.run(teams.assert_project_access(pool, 1, "u2", write=True))  # 可写分享
    assert pool.captured == (1, "u2")  # (project_id, user_id) 传参正确


# ── 团队管理闭环（假 pool：create/share 的授权分支）──────────────────────

class _FakeAdminPool:
    """create_team：fetchval=INSERT...RETURNING，execute=INSERT member。"""

    def __init__(self):
        self.executed = []

    def acquire(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def transaction(self):
        return self

    async def fetchval(self, sql, *args):
        assert "INSERT INTO teams" in sql
        return 7

    async def execute(self, sql, *args):
        self.executed.append((sql.split("(")[0], args))
        return "OK"


def test_create_team_inserts_and_makes_creator_admin():
    pool = _FakeAdminPool()
    out = asyncio.run(teams.create_team(pool, name="漫剧组", created_by="sys_dev"))
    assert out["team_id"] == 7
    member_insert = [e for e in pool.executed if "INSERT INTO team_members" in e[0]]
    member_insert = [e for e in pool.executed if "INSERT INTO team_members" in e[0]]
    assert member_insert
    assert member_insert[0][1] == (7, "sys_dev")  # role 是字面量 'admin'


def test_create_team_rejects_blank_name():
    with pytest.raises(ValueError):
        asyncio.run(teams.create_team(_FakeAdminPool(), name="  ", created_by="u"))
