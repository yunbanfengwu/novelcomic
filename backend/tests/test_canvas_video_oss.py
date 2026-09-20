import asyncio
from app.services.flow import Ctx
from app.services.steps import CanvasVideoStep


class _Pool:
    def __init__(self):
        self.calls = []

    async def execute(self, query, *args):
        self.calls.append((query, args))


def test_canvas_video_step_uses_oss_url_in_attachment(monkeypatch):
    pool = _Pool()
    ctx = Ctx(
        pool,
        {"id": 7, "project_id": 42, "node_id": 11},
        {"prompt": "a cat eating", "node_key": "video-1", "title": "Cat video"},
    )
    stored = "https://oss.example/novelcomic/canvas_video/video.mp4"
    seen = {}

    async def fake_store(url, prefix):
        seen.update(url=url, prefix=prefix)
        return stored

    monkeypatch.setattr("app.services.steps.store_url", fake_store)
    result = asyncio.run(CanvasVideoStep().next(
        ctx, {"url": "https://ark.example/temporary.mp4", "provider": "ark:seedance"}
    ))

    assert seen == {"url": "https://ark.example/temporary.mp4", "prefix": "canvas_video"}
    assert result["url"] == stored
    assert pool.calls
    assert pool.calls[0][1][3] == stored
