import unittest

from app.services.continuity import assert_generation_ready, validate_shot
from app.services.continuity_records import (
    _detect_color_temperature,
    _detect_enclosure,
    _detect_primary_light,
    _detect_time,
    _detect_weather,
)
from app.services.steps import build_group_keyframe_prompt


LOCKS = {
    "location_id": "LOC_WIND_PORT",
    "story_day": "DAY_01",
    "time_of_day": "morning",
    "weather": "post_storm_clear",
    "lighting_direction": "right_low",
}


class ContinuityTests(unittest.TestCase):
    def test_extracts_scene_time_and_weather_locks(self):
        self.assertEqual(_detect_time("黄昏港口，低角度暖光"), "dusk")
        self.assertEqual(_detect_weather("雷暴夜，暴雨将至"), "thunderstorm")
        self.assertEqual(_detect_enclosure("议事厅内，木石拱顶"), "interior")
        self.assertEqual(_detect_color_temperature("暖色火光映照"), "warm")
        self.assertEqual(_detect_primary_light("墙面火把提供暖色主光"), "firelight")

    def test_rejects_indoor_takeoff_without_exit_transition(self):
        errors = validate_shot(
            {**LOCKS, "enclosure": "interior", "ceiling_state": "roofed"},
            {"enclosure": "interior", "ceiling_state": "roofed"},
            {"type": "explicit_script_action", "changes": {}},
            {"enclosure": "interior", "ceiling_state": "roofed"},
            {"event_ids": ["E004"], "quote": "洛汐和岚牙一跃而起，飞向雷暴云墙。"},
        )
        self.assertIn("indoor_action_breaks_enclosure", {e["code"] for e in errors})

    def test_allows_indoor_departure_through_exit(self):
        errors = validate_shot(
            {**LOCKS, "enclosure": "interior", "ceiling_state": "roofed"},
            {"enclosure": "interior", "ceiling_state": "roofed"},
            {"type": "explicit_script_action", "changes": {}},
            {"enclosure": "interior", "ceiling_state": "roofed"},
            {"event_ids": ["E005"], "quote": "洛汐与岚牙沿中央通道走向议事厅出口。"},
        )
        self.assertNotIn("indoor_action_breaks_enclosure", {e["code"] for e in errors})

    def test_group_prompt_carries_visual_seam_and_indoor_locks(self):
        prompt = build_group_keyframe_prompt(
            [{"shot_no": 9, "prompt": "中景，人物继续交谈"}],
            [{"kind": "continuity_frame", "name": "同场景上一批末帧", "url": "https://x/a.jpg"}],
            scene_lock={
                "scene_seg": 2,
                "scene": "议事厅内",
                "enclosure": "interior",
                "color_temperature": "warm",
                "primary_light_source": "firelight",
            },
        )
        self.assertIn("继承其曝光、白平衡、主光方向", prompt)
        self.assertIn("封闭室内且屋顶完整", prompt)
        self.assertIn("不得改成露天", prompt)

    def test_rejects_morning_to_dusk_without_scene_change(self):
        errors = validate_shot(
            LOCKS,
            {"time_of_day": "morning", "洛汐": {"zone": "port.platform"}},
            {"type": "explicit_script_action", "changes": {}},
            {"time_of_day": "dusk", "洛汐": {"zone": "port.platform"}},
            {"event_ids": ["E001"], "quote": "洛汐站在起降台上。"},
        )
        self.assertIn("scene_hard_lock_after", {e["code"] for e in errors})
        self.assertIn("undeclared_state_change", {e["code"] for e in errors})

    def test_rejects_position_jump_without_action(self):
        errors = validate_shot(
            LOCKS,
            {"time_of_day": "morning", "洛汐": {"zone": "port.platform"}},
            {"type": "explicit_script_action", "changes": {}},
            {"time_of_day": "morning", "洛汐": {"zone": "dragon.saddle"}},
            {"event_ids": ["E002"], "quote": "岚牙在平台边缘警惕后退。"},
        )
        self.assertIn("undeclared_state_change", {e["code"] for e in errors})

    def test_allows_evidenced_position_change_and_inherits_injury(self):
        before = {
            "time_of_day": "morning",
            "洛汐": {"zone": "port.platform", "costume": "flight_01"},
            "岚牙": {"zone": "port.edge", "injury": "left_wing_bandaged"},
        }
        after = {
            "time_of_day": "morning",
            "洛汐": {"zone": "dragon.saddle", "costume": "flight_01"},
            "岚牙": {"zone": "port.edge", "injury": "left_wing_bandaged"},
        }
        assert_generation_ready(
            LOCKS, before,
            {"type": "explicit_script_action", "changes": {
                "洛汐.zone": {"from": "port.platform", "to": "dragon.saddle"},
            }},
            after,
            {"event_ids": ["E003"], "quote": "洛汐踩上岚牙放低的前肢，翻身坐上鞍带。"},
        )


if __name__ == "__main__":
    unittest.main()
