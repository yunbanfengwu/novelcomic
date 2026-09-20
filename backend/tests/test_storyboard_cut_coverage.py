from app.services.storyboard import professionalize_cut_coverage


def test_professionalize_cut_coverage_alternates_adjacent_scales():
    shots = [{
        "shot_no": 4,
        "scale": "特写",
        "cuts": [
            {"seconds": 3, "scale": "特写", "subject": "阿澈", "action": "说话"},
            {"seconds": 4, "scale": "特写", "subject": "三长老", "action": "反问"},
            {"seconds": 3, "scale": "特写", "subject": "阿澈", "action": "回答"},
        ],
    }]

    result = professionalize_cut_coverage(shots)

    assert [cut["scale"] for cut in result[0]["cuts"]] == ["特写", "近景", "特写"]
    assert all(cut["camera_move"] == "固定" for cut in result[0]["cuts"])


def test_professionalize_cut_coverage_preserves_authored_coverage_and_move():
    shots = [{
        "shot_no": 1,
        "cuts": [
            {"seconds": 3, "scale": "中景", "camera_move": "慢推", "subject": "双人"},
            {"seconds": 3, "scale": "近景", "camera_move": "固定", "subject": "角色A"},
        ],
    }]

    result = professionalize_cut_coverage(shots)

    assert result[0]["cuts"] == shots[0]["cuts"]
