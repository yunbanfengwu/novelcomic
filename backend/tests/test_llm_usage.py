"""P4 Token 计量测试：usage 提取 / fire-and-forget 落库 / 聚合 SQL 形状（2026-09-17）。"""
import asyncio
from unittest.mock import patch

import pytest

from backend.app.services import llm_usage


def test_extract_usage_full_and_partial():
    full = llm_usage.extract_usage(
        {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
    assert full == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    # 缺 total → 自动求和；缺字段按 0
    assert llm_usage.extract_usage(
        {"usage": {"prompt_tokens": 10, "completion_tokens": 5}})["total_tokens"] == 15
    assert llm_usage.extract_usage({"usage": {}}) == {"prompt_tokens": 0,
                                                      "completion_tokens": 0,
                                                      "total_tokens": 0}


def test_extract_usage_rejects_missing_or_malformed():
    assert llm_usage.extract_usage({}) is None          # 无 usage（流式增量常见）
    assert llm_usage.extract_usage(None) is None
    assert llm_usage.extract_usage({"usage": "oops"}) is None
    assert llm_usage.extract_usage(None) is None


def test_record_response_skips_without_usage():
    # 无 usage → 连 task 都不起，不碰 pool
    with patch("backend.app.db.get_pool") as gp:
        llm_usage.record_response({"model": "m"}, {"choices": []}, 100)
        gp.assert_not_called()


def test_record_response_fires_and_forgets_insert():
    executed = []

    class _FakePool:
        async def execute(self, sql, *args):
            executed.append((sql, args))

    async def scenario():
        # 生产语义：record_response 在运行中的事件循环内被调（FastAPI 请求处理即如此）
        with patch("backend.app.db.get_pool", return_value=_FakePool()):
            llm_usage.record_response(
                {"model": "bge-chat"},
                {"usage": {"prompt_tokens": 100, "completion_tokens": 40,
                           "total_tokens": 140}},
                250)
            await asyncio.sleep(0)  # 排空事件循环：fire-and-forget 的 task 应已完成

    asyncio.run(scenario())
    assert len(executed) == 1
    sql, args = executed[0]
    assert "INSERT INTO llm_usage" in sql
    assert args == ("bge-chat", 100, 40, 140, 250)


def test_record_response_never_raises_outside_loop_and_bad_pool():
    # 无事件循环 → 静默放弃；坏 pool → 吞异常
    llm_usage.record_response({"model": "m"}, {"usage": {"total_tokens": 1}}, 5)
    with patch("backend.app.db.get_pool", side_effect=RuntimeError("池未起")):
        llm_usage.record_response({"model": "m"}, {"usage": {"total_tokens": 1}}, 5)


def test_summary_and_total_sql_shapes():
    sql, args = llm_usage.summary_sql(999)
    assert "GROUP BY day, model" in sql and args == ["365"]
    _, args2 = llm_usage.total_sql(0)
    assert args2 == ["1"]
