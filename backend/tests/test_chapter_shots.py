"""章级分镜能力：清单是循环数据源，「生成或查询」必须缺才跑。

盯的是三条会静默出错的约束：
1. items 声明了 items.properties —— 画布「设为循环」靠它给循环体 {{item.shot_id}}，
   丢了就只能选到一个不透明的 json 字段，配不出逐镜链；
2. 已有详细分镜时 ensure 不入队 —— 一旦回归，每次跑编排都会把整章时间轴重拆一遍；
3. 只有粗拆骨架时补的是 expand_shot_details 而不是 breakdown_chapter ——
   重拆会把已有镜清空重来，用户手改过的镜就没了。
"""
import asyncio

import pytest

from backend.app.services import workflow_actions as W


class FakePool:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, _sql, *_args):
        return self.rows


def shot(sid, seq, *, detail_pending=False, keyframe=""):
    return {"id": sid, "seq": seq, "title": f"镜头{seq}", "summary": "画面", "status": "storyboarded",
            "meta": {"shot_no": str(seq), "action": "走进门", "dialogue": "无", "scale": "中景",
                     "duration_s": 5, "cuts": [{"seconds": 2}], "keyframe_url": keyframe,
                     "detail_pending": detail_pending}}


def run(coro):
    return asyncio.run(coro)


def test_items_declare_item_properties():
    """循环体要能引 {{item.shot_id}}，靠的就是这份 items.properties。"""
    props = W.spec("chapter.shots")["outputs"]["items"]["items"]["properties"]
    assert "shot_id" in props and "keyframe_url" in props


def test_shots_flatten_meta_and_count_readiness():
    out = run(W.chapter_shots(FakePool([shot(11, 1, keyframe="u1"), shot(12, 2, detail_pending=True)]),
                              project_id=25, chapter_id=7))
    assert [i["shot_id"] for i in out["items"]] == [11, 12]
    assert out["items"][0]["scale"] == "中景" and out["items"][0]["cuts"] == 1
    assert out["count"] == 2 and out["pending_details"] == 1 and out["with_keyframe"] == 1


def test_ensure_skips_when_details_are_ready():
    """缺才跑：已有详细分镜就零成本返回，绝不重拆。"""
    out = run(W.chapter_ensure_storyboard(FakePool([shot(11, 1)]), project_id=25, chapter_id=7))
    assert out["generated"] is False and out["tasks"] == [] and out["count"] == 1


@pytest.mark.parametrize(("rows", "expect_kind"), [
    ([shot(11, 1, detail_pending=True)], "expand_shot_details"),   # 只有粗拆 → 补展开
    ([], "breakdown_chapter"),                                     # 一镜都没有 → 从正文拆
])
def test_ensure_picks_the_right_step(monkeypatch, rows, expect_kind):
    called: list[str] = []

    async def fake_enqueue(_pool, *, kind, **_kw):
        called.append(kind)
        return {"task_id": 900}

    async def fake_await(_pool, _task_id):
        return "done", "", {}

    from backend.app.services import flow, workflow
    monkeypatch.setattr(flow, "enqueue_with_deps", fake_enqueue)
    monkeypatch.setattr(workflow, "_await_task", fake_await)
    out = run(W.chapter_ensure_storyboard(FakePool(rows), project_id=25, chapter_id=7))
    assert called == [expect_kind] and out["generated"] is True
