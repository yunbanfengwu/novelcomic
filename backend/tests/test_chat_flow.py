"""会话、规划与画布联动回归：隐式资料、历史压缩、SSE 与确定性节点执行。"""
import asyncio
import json
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest

from backend.app.api import chat


def run(coro):
    return asyncio.run(coro)


def message(mid, content, role="user", meta=None):
    return {"id": mid, "role": role, "content": content, "meta": meta or {}, "created_at": None}


class ReplyPool:
    def __init__(self, history):
        self.history = history
        self.saved = []
        self.conv = {"id": 1, "history_summary": "", "history_summary_through_id": 0}
        self.updates = []

    async def fetch(self, sql, *args):
        assert "chat_messages" in sql
        return self.history

    async def fetchrow(self, sql, *args):
        if "SELECT" in sql:
            return self.conv
        assert "INSERT INTO chat_messages" in sql
        row = message(len(self.history) + len(self.saved) + 1, args[1], "assistant", json.loads(args[2]))
        self.saved.append(row)
        return row

    async def execute(self, sql, *args):
        self.updates.append((sql, args))
        if "SET history_summary=" in sql:
            self.conv.update(history_summary=args[1], history_summary_through_id=args[2])


async def collect_reply(pool, chunks, *, fallback=None, context="上游隐藏内容：SECRET", seen=None):
    async def stream(messages, **kwargs):
        if seen is not None:
            seen.append(messages)
        if kwargs.get("max_tokens"):
            yield "1. 确认本次目标\n"
            yield "2. 提交节点生成"
        else:
            for chunk in chunks:
                yield chunk

    async def complete(*args, **kwargs):
        if isinstance(fallback, Exception):
            raise fallback
        return fallback or ""

    with patch.object(chat, "get_pool", return_value=pool), \
            patch.object(chat, "chat_messages_stream", stream), \
            patch.object(chat, "chat_messages", complete):
        response = await chat.reply_stream(1, chat.ReplyIn(context=context))
        return [json.loads(part[6:]) async for part in response.body_iterator]


@pytest.mark.parametrize("width", [1, 2, 7, 19, 2000])
def test_protocol_is_independent_of_token_boundaries_and_final_newline(width):
    raw = ('正在修改标题。\nACTION {"type":"update_node_prompt","node_key":"text-1","prompt":"新标题"}\n'
           'ACTION {"type":"run_node","node_key":"text-1"}\nSUGGEST ["继续调整"]')
    parser = chat._ProtocolStream()
    events = []
    for offset in range(0, len(raw), width):
        events.extend(parser.feed(raw[offset:offset + width]))
    events.extend(parser.finish())
    assert "".join(event["text"] for event in events if event["event"] == "delta") == "正在修改标题。\n"
    assert [event["action"]["type"] for event in events if event["event"] == "action"] == ["update_node_prompt", "run_node"]
    assert events[-1] == {"event": "suggestions", "items": ["继续调整"]}


def test_ordinary_prose_streams_without_waiting_for_a_line_break():
    parser = chat._ProtocolStream()
    assert parser.feed("我正在") == [{"event": "delta", "text": "我正在"}]
    assert parser.feed("调整") == [{"event": "delta", "text": "调整"}]


def test_canvas_context_tool_steps_recognize_compact_json_upstream_marker():
    # The browser uses JSON.stringify, which emits ``"upstream_context":true``
    # without a space after the colon.  That marker must still produce the
    # visible read-upstream milestone in the chat timeline.
    context = '{"key":"source","type":"text","upstream_context":true,' \
              '"generation_instruction":"按上游生成"}'
    titles = [step["title"] for step in chat._context_tool_steps(context)]
    assert "读取上游节点资料" in titles
    assert "整理当前节点生成提示词" in titles


def test_invalid_protocol_is_hidden_and_code_examples_do_not_execute():
    raw = ('ACTION {"type":"erase_database"}\nACTION {"type":[]}\nACTION {broken}\n'
           '```text\nACTION {"type":"run_canvas"}\n```\n正文')
    text, actions, _ = chat._strip_protocol(raw)
    assert actions == []
    assert "erase_database" not in text and "broken" not in text
    assert text == '```text\nACTION {"type":"run_canvas"}\n```\n正文'


def test_text_deliverable_action_requires_complete_content():
    action = chat._valid_action({
        "type": "update_node_content", "node_key": "text-1",
        "content": "第一段：小猫轻轻舔食。\\n第二段：镜头停在满足的眼神。",
    })
    assert action and action["content"].startswith("第一段")
    assert chat._valid_action({"type": "update_node_content", "node_key": "text-1"}) is None


def test_followup_edits_existing_text_deliverable_instead_of_new_instruction():
    # The first assistant turn is the actual canvas output.  A later user turn
    # must keep that output in model history while asking for a revision.
    history = [
        message(1, "生成一段小猫吃东西的文案脚本"),
        message(2, "第一段：小猫闻到香味。\\n第二段：小猫慢慢吃下食物。", role="assistant"),
        message(3, "每一段脚本的时长太长"),
    ]
    pool = ReplyPool(history)
    seen = []
    events = run(collect_reply(pool, [
        "\u5df2\u8bfb\u53d6\u73b0\u6709\u811a\u672c\u5e76\u538b\u7f29\u6bcf\u6bb5\u65f6\u957f\u3002" + chr(10),
        'ACTION {"type":"update_node_content","node_key":"text-1","content":"第一段：小猫闻香，轻轻舔食。\\\\n第二段：小猫满足地吃完。"}',
    ], seen=seen))
    actions = [event["action"] for event in events if event["event"] == "action"]
    assert actions == [{
        "type": "update_node_content", "node_key": "text-1",
        "content": "第一段：小猫闻香，轻轻舔食。\\n第二段：小猫满足地吃完。",
    }]
    assert len(seen) == 2
    for messages in seen:
        serialized = json.dumps(messages, ensure_ascii=False)
        assert "小猫慢慢吃下食物" in serialized
        assert "每一段脚本的时长太长" in serialized
    assert pool.saved[0]["meta"]["actions"] == actions


def test_text_instruction_action_is_repaired_before_it_reaches_canvas():
    pool = ReplyPool([message(1, "每一段脚本的时长太长")])
    context = '{"key":"text-1","type":"text","text":"第一段：小猫慢慢吃下食物。"}'
    repaired = 'ACTION {"type":"update_node_content","node_key":"text-1","content":"第一段：小猫轻轻舔食。"}'
    events = run(collect_reply(
        pool,
        ['ACTION {"type":"update_node_prompt","node_key":"text-1","prompt":"生成一段时长更短的小猫文案"}'],
        fallback=repaired,
        context=context,
    ))
    actions = [event["action"] for event in events if event["event"] == "action"]
    assert actions == [{
        "type": "update_node_content", "node_key": "text-1",
        "content": "第一段：小猫轻轻舔食。",
    }]
    assert pool.saved[0]["meta"]["actions"] == actions


@pytest.mark.parametrize("kind", ["text", "image", "video"])
def test_node_send_runs_original_prompt_once_even_when_model_only_talks(kind):
    request = {"node_key": f"{kind}-1", "mode": "on_demand", "prompt": "  节点原输入，保留空格  "}
    pool = ReplyPool([message(1, "生成这个节点", meta={"node_request": request})])
    seen = []
    events = run(collect_reply(pool, ["开始处理。\n", 'ACTION {"type":"run_node","node_key":"wrong"}'], seen=seen))
    actions = [event["action"] for event in events if event["event"] == "action"]
    assert actions == [{"type": "run_node", "node_key": f"{kind}-1", "prompt": request["prompt"]}]
    assert next(i for i, event in enumerate(events) if event["event"] == "action") < next(i for i, event in enumerate(events) if event["event"] == "delta")
    assert pool.saved[0]["meta"]["actions"] == actions
    assert pool.saved[0]["content"] == "开始处理。"
    # 两次模型调用均收到隐藏请求和画布资料，可见用户消息保持简洁。
    for messages in seen:
        assert "SECRET" in messages[0]["content"]
        assert request["prompt"] in messages[-1]["content"]
    assert pool.history[0]["content"] == "生成这个节点"
    assert all("SECRET" not in event.get("text", "") for event in events)


def test_pre_executed_canvas_send_does_not_dispatch_a_second_run():
    request = {"node_request": {
        "node_key": "image-1", "mode": "on_demand", "prompt": "existing prompt",
        "executed": True,
    }}
    parsed = chat._node_request(request)
    assert parsed and parsed["executed"] is True
    assert chat._direct_node_action(parsed) is None


def test_canvas_request_is_hidden_and_forces_run_after_planning():
    history = [message(1, "执行此画布", meta={
        "canvas_request": {"execute_after_planning": True, "special_requirement": ""},
    })]
    request = chat._canvas_request(history)
    assert request == {"execute_after_planning": True, "special_requirement": ""}


def test_canvas_request_stream_emits_run_canvas_after_answer():
    pool = ReplyPool([message(1, "执行此画布：夜景", meta={
        "canvas_request": {"execute_after_planning": True, "special_requirement": "夜景"},
    })])
    events = run(collect_reply(pool, ["已读取当前画布。"], context='{"type":"image","key":"image-1","prompt":"kitchen"}'))
    actions = [event["action"] for event in events if event["event"] == "action"]
    assert actions == [{"type": "run_canvas"}]


def test_canvas_request_orders_prompt_update_before_run():
    pool = ReplyPool([message(1, "执行此画布：改成夜景", meta={
        "canvas_request": {"execute_after_planning": True, "special_requirement": "改成夜景"},
    })])
    chunks = [
        'ACTION {"type":"run_canvas"}\n',
        'ACTION {"type":"update_node_prompt","node_key":"image-1","prompt":"夜景厨房，暖色灯光。"}\n',
    ]
    events = run(collect_reply(pool, chunks, context='{"type":"image","key":"image-1","prompt":"厨房"}'))
    actions = [event["action"] for event in events if event["event"] == "action"]
    assert [action["type"] for action in actions] == ["update_node_prompt", "run_canvas"]


def test_refusal_text_cannot_replace_media_prompt():
    bad = {"type": "update_node_prompt", "node_key": "image-1",
           "prompt": "现代家庭厨房：由于未找到本次需求相关内容，无法完成需求合理性分析和生成最终提示词，请提供【本次需求】。"}
    assert chat._needs_prompt_repair(bad)
    good = {**bad, "prompt": "现代家庭厨房，暖色自然光，空气炸锅工作中的食物特写。"}
    assert not chat._needs_prompt_repair(good)


@pytest.mark.parametrize("mode, expected", [
    ("rewrite_only", ["update_node_prompt"]),
    ("rewrite_generate", ["update_node_prompt", "run_node"]),
])
def test_rewrite_fallback_updates_before_generating(mode, expected):
    pool = ReplyPool([message(1, "修改文字", meta={"node_request": {
        "node_key": "text-1", "mode": mode, "prompt": "请把标题改成蓝色"}})])
    events = run(collect_reply(pool, ["调整标题。"], fallback=
        'ACTION {"type":"update_node_prompt","node_key":"text-1","prompt":"蓝色的新标题"}'))
    actions = [event["action"] for event in events if event["event"] == "action"]
    assert [action["type"] for action in actions] == expected
    assert actions[-1]["prompt"] == "蓝色的新标题"
    assert events[-1]["event"] == "done"
    assert pool.saved[0]["meta"]["actions"] == actions


def test_final_action_without_newline_is_emitted_and_persisted():
    pool = ReplyPool([message(1, "把刚才的标题改成春日并运行")])
    events = run(collect_reply(pool, [
        '马上更新。\nACTION {"type":"update_node_prompt","node_key":"text-1","prompt":"春日"}\n',
        'ACTION {"type":"run_node","node_key":"text-1"}',
    ]))
    actions = [event["action"] for event in events if event["event"] == "action"]
    assert len(actions) == 2
    assert pool.saved[0]["meta"]["actions"] == actions
    assert events[-1]["actions"] == actions


def test_rewrite_failure_does_not_generate_or_claim_success():
    pool = ReplyPool([message(1, "修改标题", meta={"node_request": {
        "node_key": "text-1", "mode": "rewrite_generate", "prompt": "蓝色"}})])
    events = run(collect_reply(pool, ["正在修改。"], fallback="无法改写"))
    assert not any(event["event"] == "action" for event in events)
    assert events[-1]["event"] == "error"
    assert "未执行生成" in events[-1]["message"]
    assert pool.saved[0]["meta"]["actions"] == []
    assert events[-1]["partial_message"] == pool.saved[0]


def test_recent_history_and_earlier_summary_are_shared_by_planner_and_reply():
    pool = ReplyPool([message(i, f"原始消息{i}") for i in range(1, 29)])
    pool.history[0]["meta"] = {"node_request": {"node_key": "image-original", "mode": "on_demand", "prompt": "最初海报标题"}}
    seen = []

    async def summarize(messages, **kwargs):
        source = messages[-1]["content"]
        assert "最初海报标题" in source and "image-original" in source
        assert "原始消息16" in source and "原始消息17" not in source
        return "用户在 image-original 创作海报，最初标题为最初海报标题。"

    async def stream(messages, **kwargs):
        seen.append(messages)
        yield "处理最新修改。"

    async def scenario():
        with patch.object(chat, "get_pool", return_value=pool), \
                patch.object(chat, "chat_messages", summarize), \
                patch.object(chat, "chat_messages_stream", stream):
            response = await chat.reply_stream(1, chat.ReplyIn())
            return [part async for part in response.body_iterator]

    run(scenario())
    assert len(seen) == 2
    assert seen[0][1:] == seen[1][1:]
    assert len(seen[0]) == 14  # system + summary + 12 recent messages
    assert "image-original" in seen[0][1]["content"]
    assert pool.conv["history_summary_through_id"] == 16
    assert len(pool.history) == 28  # 原文保留，摘要不插入可见消息


def test_summary_failure_keeps_all_history_and_prior_memory():
    pool = ReplyPool([message(i, f"消息{i}") for i in range(1, 27)])
    pool.conv.update(history_summary="更早的目标是 video-1", history_summary_through_id=1)

    async def fail(*args, **kwargs):
        raise RuntimeError("summary offline")

    with patch.object(chat, "get_pool", return_value=pool), patch.object(chat, "chat_messages", fail):
        messages, stats = run(chat._prepare_history(1, pool.history, pool.conv))
    assert len(messages) == 26  # earlier summary + all 25 unsummarized rows
    assert "video-1" in messages[0]["content"]
    assert messages[1]["content"] == "消息2" and messages[-1]["content"] == "消息26"
    assert stats["warning"]
    assert pool.conv["history_summary_through_id"] == 1


def test_reuses_persisted_summary_without_recompressing_recent_turns():
    pool = ReplyPool([message(i, f"消息{i}") for i in range(1, 29)])
    pool.conv.update(history_summary="当前修改目标 text-1", history_summary_through_id=16)
    with patch.object(chat, "get_pool", return_value=pool), patch.object(chat, "chat_messages") as llm:
        messages, stats = run(chat._prepare_history(1, pool.history, pool.conv))
    llm.assert_not_called()
    assert len(messages) == 13 and stats["has_summary"]


class ConversationPool:
    """模拟 scope 锁与唯一索引，覆盖多个 ensure 请求交错的旧问题。"""
    def __init__(self):
        self.lock = asyncio.Lock()
        self.rows = []

    @asynccontextmanager
    async def acquire(self):
        yield ConversationConnection(self)

    async def fetch(self, sql, *args):
        return []


class ConversationConnection:
    def __init__(self, pool):
        self.pool = pool
        self.locked = False

    @asynccontextmanager
    async def transaction(self):
        try:
            yield self
        finally:
            if self.locked:
                self.pool.lock.release()

    async def execute(self, sql, *args):
        if "pg_advisory_xact_lock" in sql and not self.locked:
            await self.pool.lock.acquire()
            self.locked = True
        elif "SET archived=true" in sql:
            for row in self.pool.rows:
                row["archived"] = True

    async def fetchrow(self, sql, *args):
        await asyncio.sleep(0)  # 允许首次创建请求真实交错
        if "SELECT" in sql:
            return next((row for row in self.pool.rows if not row["archived"]), None)
        if any(not row["archived"] for row in self.pool.rows):
            raise RuntimeError("duplicate unique active conversation")
        row = {"id": len(self.pool.rows) + 1, "title": args[2], "archived": False}
        self.pool.rows.append(row)
        return row


def test_concurrent_first_send_ensures_one_active_canvas_conversation():
    pool = ConversationPool()

    async def scenario():
        with patch.object(chat, "get_pool", return_value=pool):
            body = chat.ConversationIn(scope_kind="tapflow", scope_key="canvas:poster")
            responses = await asyncio.gather(*(chat.open_conversation(body) for _ in range(20)))
            fresh = await chat.open_conversation(body.model_copy(update={"fresh": True}))
            return responses, fresh

    responses, fresh = run(scenario())
    assert {response["id"] for response in responses} == {1}
    assert fresh["id"] == 2
    assert len([row for row in pool.rows if not row["archived"]]) == 1
