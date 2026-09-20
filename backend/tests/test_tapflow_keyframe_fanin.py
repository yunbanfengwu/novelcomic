from app.services.workflow import _upstream_media


def test_loop_subflow_images_are_direct_downstream_references():
    ctx = {
        "__in__": ["each_element", "extra_refs", "prompt_qc"],
        "each_element": {
            "count": 2,
            "failed": 0,
            "results": [
                {"ensure_sheet": {"sheet_url": "https://asset/character.png", "exists": True}},
                {"ensure_sheet": {"sheet_url": "https://asset/scene.png", "exists": True}},
            ],
        },
        "extra_refs": {"refs": [{"name": "构图参考", "kind": "asset",
                                   "url": "https://asset/layout.png"}]},
        "prompt_qc": {"text": "最终关键帧定格提示词"},
    }

    texts, refs = _upstream_media(ctx)

    assert texts == ["最终关键帧定格提示词"]
    assert [r["url"] for r in refs] == [
        "https://asset/character.png",
        "https://asset/scene.png",
        "https://asset/layout.png",
    ]


def test_direct_reference_fanin_does_not_create_a_synthetic_node():
    texts, refs = _upstream_media({
        "__in__": ["each_element"],
        "each_element": {"results": [{"body": {"url": "https://asset/a.png"}}]},
    })
    assert texts == []
    assert refs == [{"name": "each_element", "kind": "canvas",
                     "url": "https://asset/a.png"}]
