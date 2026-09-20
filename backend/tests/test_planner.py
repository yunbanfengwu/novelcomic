"""P3 规划落库测试：容错解析 / 状态机 / 进度 / create+advance 闭环（2026-09-17）。

create/advance 的 SQL 路径用脚本化假 pool 走通（不依赖真实库）；状态机与解析是纯函数直测。
"""
import asyncio
import json
from unittest.mock import patch

import pytest

from backend.app.services import planner


# ── parse_steps：模型输出的千奇百怪都要兜住 ────────────────────────────────

def test_parse_steps_list_passthrough_and_renumber():
    out = planner.parse_steps([
        {"title": "查设定", "detail": "检索世界观", "tool_hints": ["kb.search"]},
        {"title": "写大纲"},
    ])
    assert [s["seq"] for s in out] == [1, 2]
    assert out[0]["tool_hints"] == ["kb.search"] and out[1]["detail"] is None


def test_parse_steps_dict_with_steps_key_and_single_object():
    assert len(planner.parse_steps({"steps": [{"title": "a"}, {"title": "b"}]})) == 2
    assert len(planner.parse_steps({"title": "只有一步"})) == 1
    with pytest.raises(planner.PlannerError):
        planner.parse_steps("先查设定再写大纲")  # 裸文本无 JSON 结构=拒绝，不落假计划


def test_parse_steps_fenced_and_embedded_json():
    raw = "```json\n[{\"title\":\"s1\"},{\"title\":\"s2\"}]\n```"
    assert len(planner.parse_steps(raw)) == 2
    noisy = "好的，计划如下：[{\"title\":\"s1\"}] 以上。"
    assert planner.parse_steps(noisy)[0]["title"] == "s1"
    # 外层对象里带 steps 键的围栏
    fenced2 = "```json\n{\"steps\": [{\"title\": \"x\"}]}\n```"
    assert planner.parse_steps(fenced2)[0]["title"] == "x"


def test_parse_steps_rejects_garbage_and_empty():
    with pytest.raises(planner.PlannerError):
        planner.parse_steps("这不是JSON")
    with pytest.raises(planner.PlannerError):
        planner.parse_steps([{"detail": "没有标题的步"}, {"detail": "同上"}])


def test_parse_steps_normalizes_tool_hints_string():
    out = planner.parse_steps([{"title": "s", "tool_hints": "kb.search, db.query"}])
    assert out[0]["tool_hints"] == ["kb.search", "db.query"]


# ── 状态机：禁止跳跃 ──────────────────────────────────────────────────────

def test_step_transition_happy_paths():
    assert planner.step_transition("pending", "start") == "running"
    assert planner.step_transition("running", "done") == "done"
    assert planner.step_transition("running", "fail") == "failed"
    assert planner.step_transition("failed", "retry") == "pending"
    assert planner.step_transition("running", "resume") == "pending"
    assert planner.step_transition("skipped", "retry") == "pending"


def test_step_transition_forbids_jumps():
    for cur, action in [("pending", "done"), ("pending", "retry"),
                        ("done", "retry"), ("done", "start"),
                        ("skipped", "start"), ("failed", "done")]:
        with pytest.raises(ValueError):
            planner.step_transition(cur, action)


def test_plan_status_after():
    p = planner.plan_status_after
    assert p("draft", any_pending=True, last_step_failed=False) == "running"
    assert p("running", any_pending=False, last_step_failed=False) == "done"
    assert p("running", any_pending=False, last_step_failed=True) == "failed"
    assert p("aborted", any_pending=True, last_step_failed=False) == "aborted"


def test_progress_and_step_charter():
    steps = [{"seq": 1, "status": "done", "title": "s1", "result": {"output": "r1"}},
             {"seq": 2, "status": "pending", "title": "s2", "result": None}]
    prog = planner.progress(steps)
    assert prog["total"] == 2 and prog["done"] == 1 and prog["next_seq"] == 2
    charter = planner.step_charter("目标G", steps, {**steps[1], "detail": "做s2"})
    assert "目标G" in charter and "做s2" in charter and "s1" in charter
    assert "kb.search" not in planner.step_charter(
        "G", steps, {"seq": 2, "title": "t", "tool_hints": []})


# ── 假 pool：create/advance 的 SQL 闭环 ───────────────────────────────────

class _FakeTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, state):
        self.state = state

    def transaction(self):
        return _FakeTx()

    async def fetchval(self, sql, *args):
        if sql.lstrip().startswith("INSERT INTO agent_plans"):
            self.state["plan_id"] += 1
            return self.state["plan_id"]
        raise AssertionError(f"unexpected fetchval: {sql[:60]}")

    async def execute(self, sql, *args):
        s = sql.lstrip()
        if s.startswith("INSERT INTO agent_plan_steps"):
            self.state["inserts"].append(args)
        elif s.startswith("UPDATE agent_plan_steps"):
            if "status='pending'" in s:  # 崩溃恢复：running 归位
                for st in self.state["steps"]:
                    if st["status"] == "running":
                        st["status"] = "pending"
            elif "$2, started_at" in s or "started_at=now()" in s:
                self._set_step(args[0], status=args[1])
            else:  # 回写 status/result/error
                self._set_step(args[0], status=args[1],
                               result=args[2] if len(args) > 2 else None,
                               error=args[3] if len(args) > 3 else None)
        elif s.startswith("UPDATE agent_plans"):
            if "current_seq" in s or "status='running'" in s:
                self.state["plan"]["status"] = "running"
            else:
                self.state["plan"]["status"] = args[1]
        return "OK"

    def _set_step(self, sid, **kw):
        for st in self.state["steps"]:
            if st["id"] == sid:
                st.update(kw)  # 不过滤 None：真实 asyncpg 会把 error 写成 NULL
                return
        raise AssertionError(f"step {sid} not found")

    async def fetchrow(self, sql, *args):
        if "FROM agent_plans WHERE id=$1" in sql:
            return self.state["plan"]
        if "FROM agent_plan_steps WHERE plan_id=$1 AND seq=$2" in sql:
            for st in self.state["steps"]:
                if st["seq"] == args[1]:
                    return st
            return None
        raise AssertionError(f"unexpected fetchrow: {sql[:60]}")

    async def fetch(self, sql, *args):
        assert "FROM agent_plan_steps" in sql
        return self.state["steps"]


class _FakePool:
    def __init__(self, state):
        self.state = state

    def acquire(self):
        state = self.state

        class _C:
            async def __aenter__(self_inner):
                return _FakeConn(state)

            async def __aexit__(self, *exc):
                return False

        return _C()

    async def fetchrow(self, sql, *args):
        return await _FakeConn(self.state).fetchrow(sql, *args)

    async def fetch(self, sql, *args):
        return await _FakeConn(self.state).fetch(sql, *args)

    async def execute(self, sql, *args):
        return await _FakeConn(self.state).execute(sql, *args)


def _state():
    return {
        "plan_id": 100,
        "plan": {"id": 100, "project_id": 1, "goal": "出 1 章大纲",
                 "status": "draft", "current_seq": 0, "meta": {"tool_names": []}},
        "steps": [
            {"id": 1, "seq": 1, "title": "查设定", "detail": "检索世界观",
             "tool_hints": [], "status": "pending", "result": None, "error": None},
            {"id": 101, "seq": 2, "title": "写大纲", "detail": None,
             "tool_hints": [], "status": "pending", "result": None, "error": None},
        ],
        "inserts": [],
    }


def test_create_plan_inserts_draft_with_renumbered_steps():
    state = _state()
    with patch.object(planner.llm, "chat_json",
                      return_value=[{"title": f"步{i}"} for i in range(3)]):
        out = asyncio.run(planner.create_plan(
            _FakePool(state), goal="出 1 章大纲", project_id=1,
            created_by="sys_dev", meta={"tool_names": ["kb.search"]}))
    assert out["plan_id"] == 101
    assert [s["seq"] for s in out["steps"]] == [1, 2, 3]
    # 插入语句带 tool_hints 数组与自增后的 plan_id
    assert state["inserts"][0][0] == 101 and state["inserts"][0][4] == []


def test_advance_happy_path_runs_pending_and_finishes():
    state = _state()

    async def runner(pool, **kw):
        assert "出 1 章大纲" in kw["charter"]  # charter 含计划目标
        assert kw["tool_names"] == []
        return {"output": "大纲产出", "steps": [{"tool": "kb.search"}]}

    out = asyncio.run(planner.advance(_FakePool(state), 100, runner=runner))
    assert out["step"]["status"] == "done"
    assert state["steps"][0]["status"] == "done"
    assert json.dumps(state["steps"][0]["result"], ensure_ascii=False) != "None"
    assert out["progress"]["done"] == 1 and out["progress"]["next_seq"] == 2
    assert state["plan"]["status"] == "running"  # 还有 pending → 保持 running


def test_advance_failure_marks_step_failed_not_crash():
    state = _state()

    async def runner(pool, **kw):
        raise RuntimeError("模型超时")

    out = asyncio.run(planner.advance(_FakePool(state), 100, runner=runner))
    assert out["step"]["status"] == "failed" and "RuntimeError" in out["step"]["error"]
    assert state["steps"][0]["status"] == "failed"
    # 计划不炸：还有 pending 步 → 保持 running；失败步等 retry
    assert state["plan"]["status"] == "running"
    assert out["progress"]["next_seq"] == 2


def test_advance_when_no_pending_and_resume_idempotent():
    state = _state()
    state["plan"]["status"] = "done"
    with pytest.raises(planner.PlannerError):
        asyncio.run(planner.advance(_FakePool(state), 100))
    # 崩溃恢复：running 卡住的步会被 advance 归位后执行
    state2 = _state()
    state2["steps"][0]["status"] = "running"
    asyncio.run(planner.advance(_FakePool(state2), 100, runner=_fake_run))
    assert state2["steps"][0]["status"] == "done"


def test_retry_step_revives_failed_only():
    state = _state()
    state["steps"][0]["status"] = "failed"
    state["steps"][0]["error"] = "boom"
    with patch.object(planner.agent_runtime, "run", side_effect=_fake_run):
        out = asyncio.run(planner.retry_step(_FakePool(state), 100, 1,
                                             caller="sys_dev"))
    assert out["step"]["seq"] == 1 and out["step"]["status"] == "done"
    assert state["steps"][0]["error"] is None


def test_retry_step_forbidden_on_done():
    state = _state()
    state["steps"][0]["status"] = "done"
    with pytest.raises(ValueError):
        asyncio.run(planner.retry_step(_FakePool(state), 100, 1))



async def _fake_run(pool, **kw):
    return {"output": "x", "steps": []}
