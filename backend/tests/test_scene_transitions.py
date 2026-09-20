import unittest

from app.services.scene_transitions import analyze_boundary, validate_scene_boundaries


def shot(no, scene, characters, action, description=""):
    return {
        "shot_no": no,
        "scene": scene,
        "characters": characters,
        "action": action,
        "description": description,
    }


class SubjectAwareSceneTransitionTests(unittest.TestCase):
    def test_allows_empty_establishing_shot_after_protagonists(self):
        previous = shot(1, "议事厅/白天", ["洛汐", "岚牙"], "众人继续商议")
        current = shot(2, "城市街道/白天", [], "人群来往，商贩叫卖")
        result = analyze_boundary(previous, current)
        self.assertEqual(result["transition_mode"], "new_lane_direct_cut")
        self.assertEqual(result["errors"], [])

    def test_allows_parallel_cut_between_police_and_criminal(self):
        previous = shot(1, "警察局/夜", ["警察甲"], "分析案情")
        current = shot(2, "废弃仓库/夜", ["犯罪分子乙"], "仓皇逃跑")
        result = analyze_boundary(previous, current)
        self.assertEqual(result["transition_mode"], "new_lane_direct_cut")
        self.assertEqual(result["errors"], [])

    def test_allows_ordinary_same_subject_ellipsis(self):
        previous = shot(1, "办公室/傍晚", ["林川"], "收起文件离开办公室")
        current = shot(2, "林川家/夜", ["林川"], "坐在餐桌前打开文件")
        result = analyze_boundary(previous, current)
        self.assertEqual(result["transition_mode"], "same_subject_ellipsis")
        self.assertEqual(result["errors"], [])

    def test_rejects_unexplained_same_subject_flight_and_shared_wings(self):
        previous = shot(
            12, "议事厅/白天", ["洛汐", "岚牙"],
            "洛汐与岚牙沿中央通道走向议事厅出口",
        )
        current = shot(
            13, "雷暴云墙航道/白天", ["洛汐", "岚牙"],
            "洛汐和岚牙在雷暴云墙中飞行，翅膀快速扇动",
        )
        current["_character_profiles"] = {
            "洛汐": "16岁人类少女，翼帆学徒",
            "岚牙": "幼年风脊龙，四足双翼",
        }
        result = analyze_boundary(previous, current)
        codes = {e["code"] for e in result["errors"]}
        self.assertEqual(result["transition_mode"], "bridge_required")
        self.assertIn("same_subject_unexplained_transport_jump", codes)
        self.assertIn("ambiguous_shared_locomotion_capability", codes)

    def test_does_not_assume_two_dragons_cannot_both_fly(self):
        previous = shot(1, "龙巢/白天", ["岚牙", "赤翼"], "两条龙站在崖边")
        current = shot(2, "云海/白天", ["岚牙", "赤翼"], "岚牙和赤翼扇动翅膀飞行")
        current["_character_profiles"] = {
            "岚牙": "风脊龙，四足双翼",
            "赤翼": "赤焰龙，拥有双翼",
        }
        result = analyze_boundary(previous, current)
        codes = {e["code"] for e in result["errors"]}
        self.assertNotIn("ambiguous_shared_locomotion_capability", codes)

    def test_allows_explicit_rider_mount_transition(self):
        previous = shot(
            12, "议事厅/白天", ["洛汐", "岚牙"],
            "洛汐与岚牙沿中央通道走向议事厅出口",
        )
        current = shot(
            13, "雷暴云墙航道/白天", ["洛汐", "岚牙"],
            "离开后，洛汐骑在岚牙背上；岚牙载着洛汐飞入雷暴云墙",
        )
        result = analyze_boundary(previous, current)
        self.assertEqual(result["transition_mode"], "same_subject_ellipsis")
        self.assertEqual(result["errors"], [])

    def test_validate_boundaries_only_flags_risky_overlap(self):
        shots = [
            shot(1, "警察局/夜", ["警察甲"], "分析案情"),
            shot(2, "仓库/夜", ["犯罪分子乙"], "逃跑"),
            shot(3, "屋顶/夜", ["犯罪分子乙"], "站在屋顶边缘"),
            shot(4, "直升机外/夜", ["犯罪分子乙"], "在空中飞行"),
        ]
        errors = validate_scene_boundaries(shots)
        self.assertEqual(len(errors), 1)
        self.assertIn("镜4", errors[0])


if __name__ == "__main__":
    unittest.main()
