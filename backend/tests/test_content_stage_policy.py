from app.services import pipeline


PROJECT = {
    "title": "北境灯塔",
    "config": {"genre": "奇幻"},
    "synopsis": "少女与幼龙寻找浮空灯塔。",
    "writing_style": "电影化叙事",
    "storyline": "救龙→寻找灯塔→点亮灯塔",
    "outline_md": "新增提案：以港务议会形成现实阻力。",
    "draft_text": "岚音救下幼龙砾光。",
}


def test_chapter_planning_uses_approved_outline_as_current_baseline():
    prompt = pipeline._outline_user(PROJECT, 8)
    assert "已确认架构大纲" in prompt
    assert "允许用临时人物、过场场景和局部事件" in prompt
    assert "严格在上述事实范围内" not in prompt


def test_element_extraction_accepts_approved_development_additions():
    prompt = pipeline._elements_user(
        PROJECT, [{"seq": 1, "title": "风暴前夕", "summary": "港务议会封锁码头。"}])
    assert PROJECT["outline_md"] in prompt
    assert "包含已接受的开发期新增设定" in prompt
    assert "上述已批准内容" in prompt


def test_outline_integrity_rejects_truncated_revision():
    truncated = (
        "# 《北境灯塔》长篇架构\n"
        "## 【世界观设定】\n" + "世界设定。" * 300
        + "\n## 【主线架构：分卷核心冲突】\n"
        + "### 第一卷：相遇\n" + "主线事件。" * 100
        + "\n### 第二卷：远航\n" + "主线事件。" * 100
        + "\n## 【角色深度设计】\n### 岚音\n- 结局：她与砾光"
    )
    assert "末尾不是完整句，疑似截断" in pipeline.outline_integrity_issues(truncated)


def test_outline_decision_conflicts_reject_wins():
    accepted, rejected, conflicts = pipeline.normalize_outline_decisions(
        [{"name": "外岛势力", "reason": "增加压力"}, {"name": "神秘商会"}],
        [{"name": " 外岛势力 ", "reason": "与商会同质，应合并"}],
    )
    assert [x["name"] for x in accepted] == ["神秘商会"]
    assert [x["name"] for x in rejected] == ["外岛势力"]
    assert conflicts == ["外岛势力"]


def test_outline_policy_checks_prior_setting_reasonableness():
    review = {
        "rejected_additions": [
            {"name": "外岛势力"},
            {"name": "阿砚的家族传承"},
        ],
        "setting_assessments": [],
    }
    md = (
        "神秘商会暗中与外岛势力合作。"
        "阿砚的家族传承最终恢复。"
        "砾光是十年前龙群失踪事件的关键见证者。"
    )
    issues = pipeline.outline_policy_issues(md, review)
    assert any("外岛势力" in x for x in issues)
    assert any("阿砚的家族传承" in x for x in issues)
    assert any("幼龙砾光" in x for x in issues)


def test_deleted_prior_setting_must_not_survive_revision():
    review = {
        "rejected_additions": [],
        "setting_assessments": [
            {
                "name": "砾光亲历十年前事件",
                "origin": "既有大纲",
                "verdict": "删除",
                "reason": "年龄矛盾",
            }
        ],
    }
    assert pipeline.outline_policy_issues(
        "角色设定仍写着砾光亲历十年前事件。", review)


def test_redundant_origin_hooks_are_rejected_even_when_previously_present():
    md = """# 《北境灯塔》
## 【世界观设定】
## 【主线架构：分卷核心冲突】
## 【角色深度设计】
### 岚音
- 真相：父亲失踪，家族传承隐藏着灯塔秘密。
### 阿砚
- 真相：家族是古代守护者，他要恢复家族荣耀。
### 砾光
- 真相：它是龙族长老的后代，具有隐藏血统。
### 顾临
- 真相：普通守塔人，为隐瞒事故承担责任。
## 【结尾】
故事结束。"""
    issues = pipeline.outline_redundant_origin_issues(md)
    assert len(issues) == 1
    assert "岚音" in issues[0] and "阿砚" in issues[0] and "砾光" in issues[0]


def test_one_origin_hook_is_allowed():
    md = """## 【角色深度设计】
### 岚音
- 真相：父亲失踪，留下灯塔秘密。
### 阿砚
- 真相：靠航海经验帮助伙伴。
### 砾光
- 真相：受伤后逐步恢复。
## 【结尾】
故事结束。"""
    assert pipeline.outline_redundant_origin_issues(md) == []
