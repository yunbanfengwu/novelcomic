from backend.app.services.element_sheet import (
    _character_action_gaze,
    _character_age_gender,
    _character_appellations,
    _is_real_character_project,
    _project_medium_clause,
)


def test_virtual_character_mode_wins_over_legacy_realistic_enable():
    assert not _is_real_character_project(
        {"character_mode": "virtual", "realistic_character": "enable"},
        legacy_default=True,
    )


def test_real_character_mode_wins_over_legacy_realistic_disable():
    assert _is_real_character_project(
        {"character_mode": "real", "realistic_character": "disable"},
        legacy_default=False,
    )


def test_legacy_projects_still_use_old_override_and_default():
    assert _is_real_character_project({"realistic_character": "enable"}, legacy_default=False)
    assert not _is_real_character_project({"realistic_character": "disable"}, legacy_default=True)
    assert _is_real_character_project({}, legacy_default=True)


def test_character_age_gender_prefers_profile_and_exact_age():
    assert _character_age_gender(
        {"age_years": 17, "profile": {"年龄段": "十六岁少女", "性别": "女"}},
        "飞行员",
    ) == ("17岁", "女")


def test_character_age_gender_recovers_legacy_appearance_text():
    assert _character_age_gender(
        {"外貌提示词": "二十岁上下、年轻女性、短发"},
    ) == ("二十岁上下", "女")


def test_character_age_gender_uses_female_kinship_in_character_name():
    assert _character_age_gender(
        {"外貌提示词": "年迈龙医、银白辫发"},
        "温和锐利的老人",
        "赫玛婆婆",
    ) == ("老年", "女")


def test_character_age_gender_uses_male_kinship_in_character_name():
    assert _character_age_gender({}, "村中老人", "林爷爷") == ("老年", "男")


def test_character_appellations_use_open_llm_extracted_field():
    assert _character_appellations(
        "赫玛婆婆",
        {"身份称谓": "婆婆、潮语者、龙医", "身份": "龙医师"},
        "温和锐利的部族长老",
    ) == ["婆婆", "潮语者", "龙医"]


def test_character_appellations_fallback_preserves_full_name_without_enumeration():
    assert _character_appellations(
        "阿芒·逐星使",
        {"身份": "第七码头的雾契承人"},
    ) == ["阿芒·逐星使", "第七码头的雾契承人"]


def test_character_action_gaze_uses_profile_fields():
    assert _character_action_gaze({
        "profile": {
            "身份": "侠女",
            "招牌动作": "左手按住剑鞘，右手停在剑柄上",
            "招牌眼神": "目光稳定锐利，警觉扫视前方",
        }
    }) == ("左手按住剑鞘，右手停在剑柄上", "目光稳定锐利，警觉扫视前方")


def test_project_medium_clause_locks_3d_and_rejects_2d():
    clause = _project_medium_clause("高品质三维动画电影")
    assert "统一的3D/三维动画项目" in clause
    assert "禁止2D" in clause


def test_project_medium_clause_locks_2d_and_rejects_3d():
    clause = _project_medium_clause("二维手绘赛璐璐动画")
    assert "统一的2D/二维动画项目" in clause
    assert "禁止3D" in clause
