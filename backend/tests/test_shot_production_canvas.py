import asyncio

from app.api.shots import _canvas_state
from app.services.steps import GenPromptsStep


def test_canvas_state_uses_live_generation_state():
    meta = {"gen": {"video": {"state": "running"}, "keyframe": {"state": "failed", "error": "x"}}}
    assert _canvas_state(meta, "video", False) == ("running", None)
    assert _canvas_state(meta, "keyframe", False) == ("failed", "x")


def test_canvas_state_falls_back_to_real_artifact_presence():
    assert _canvas_state({}, "video", True) == ("done", None)
    assert _canvas_state({}, "video", False) == ("empty", None)


class _MetaConn:
    def __init__(self, meta):
        self.meta = meta

    async def fetchrow(self, *_args):
        return {"meta": self.meta}


def test_prompt_auto_scope_requires_storyboard_script_first():
    step = GenPromptsStep()
    deps = asyncio.run(step.missing_deps(_MetaConn({}), 1, 2, {"only": "video"}))
    assert deps == [{"kind": "gen_shot_storyboard", "payload": {}, "priority": 10}]


def test_prompt_auto_scope_skips_finished_storyboard_and_image_does_not_need_it():
    step = GenPromptsStep()
    assert asyncio.run(step.missing_deps(
        _MetaConn({"storyboard_script_ready": True}), 1, 2, {"only": "video"})) == []
    assert asyncio.run(step.missing_deps(_MetaConn({}), 1, 2, {"only": "image"})) == []
