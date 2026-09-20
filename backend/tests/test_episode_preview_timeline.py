import unittest

from app import media
from app.services.episode_preview_timeline import (
    build_initial_timeline,
    normalise_edited_segments,
    normalise_script_bands,
)


class EpisodePreviewTimelineTests(unittest.TestCase):
    def setUp(self):
        self.timeline = build_initial_timeline(
            master_attachment_id=244,
            batch_id="244",
            master_meta={
                "mode": "adaptive_duration",
                "duration_s": 6,
                "source_minutes": 6,
                "beats": [
                    {
                        "no": 1,
                        "picture": "阿澈进入辉渊",
                        "evidence": "阿澈踏入辉渊。",
                        "characters": ["阿澈"],
                        "scene": "辉渊",
                        "output_start_s": 0,
                        "output_end_s": 3,
                        "source_start_s": 0,
                        "source_end_s": 180,
                    },
                    {
                        "no": 2,
                        "picture": "阿澈发现声弦",
                        "evidence": "银蓝声弦亮起。",
                        "characters": ["阿澈"],
                        "scene": "辉渊",
                        "output_start_s": 3,
                        "output_end_s": 6,
                        "source_start_s": 180,
                        "source_end_s": 360,
                    },
                ],
            },
            frames=[
                {"attachment_id": 301, "url": "https://x/1.jpg", "beat_no": 1, "at_s": 1.5},
                {"attachment_id": 302, "url": "https://x/2.jpg", "beat_no": 2, "at_s": 4.5},
            ],
        )

    def test_builds_three_clock_alignment(self):
        self.assertEqual(self.timeline["events"][1]["story_start_s"], 180)
        self.assertEqual(self.timeline["segments"][1]["preview_start_s"], 3)
        self.assertEqual(
            self.timeline["segments"][0]["selected_frame_attachment_id"], 301)

    def test_split_keeps_server_owned_story(self):
        edited = [
            {
                "id": "left",
                "script_event_ids": ["E001"],
                "preview_start_s": 0,
                "preview_end_s": 1.5,
                "selected_frame_attachment_id": 301,
                "locked": False,
                "picture": "客户端试图加入战舰",
            },
            {
                "id": "right",
                "script_event_ids": ["E001"],
                "preview_start_s": 1.5,
                "preview_end_s": 3,
                "selected_frame_attachment_id": 301,
                "locked": False,
            },
            {
                "id": "last",
                "script_event_ids": ["E002"],
                "preview_start_s": 3,
                "preview_end_s": 6,
                "selected_frame_attachment_id": 302,
                "locked": False,
            },
        ]
        result = normalise_edited_segments(self.timeline, edited)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["picture"], "阿澈进入辉渊")
        self.assertNotIn("战舰", result[0]["picture"])

    def test_script_track_is_versionable_and_contiguous(self):
        self.assertEqual(self.timeline["script_bands"], [
            {"event_id": "E001", "start_s": 0.0, "end_s": 3.0},
            {"event_id": "E002", "start_s": 3.0, "end_s": 6.0},
        ])
        edited = normalise_script_bands(self.timeline, [
            {"event_id": "E001", "start_s": 0, "end_s": 4},
            {"event_id": "E002", "start_s": 4, "end_s": 6},
        ])
        self.assertEqual(edited[0]["end_s"], 4.0)
        with self.assertRaisesRegex(ValueError, "首尾相接"):
            normalise_script_bands(self.timeline, [
                {"event_id": "E001", "start_s": 0, "end_s": 3.8},
                {"event_id": "E002", "start_s": 4, "end_s": 6},
            ])

    def test_rejects_gap_and_unknown_event(self):
        with self.assertRaisesRegex(ValueError, "首尾相接"):
            normalise_edited_segments(self.timeline, [
                {
                    "id": "one",
                    "script_event_ids": ["E001"],
                    "preview_start_s": 0,
                    "preview_end_s": 2.9,
                    "selected_frame_attachment_id": 301,
                },
                {
                    "id": "two",
                    "script_event_ids": ["E002"],
                    "preview_start_s": 3,
                    "preview_end_s": 6,
                    "selected_frame_attachment_id": 302,
                },
            ])
        with self.assertRaisesRegex(ValueError, "无效脚本事件"):
            normalise_edited_segments(self.timeline, [{
                "id": "one",
                "script_event_ids": ["E999"],
                "preview_start_s": 0,
                "preview_end_s": 6,
                "selected_frame_attachment_id": 301,
            }])

    def test_preview_action_frame_is_reserved_inside_reference_limit(self):
        refs = [
            {"name": "阿澈", "kind": "character", "url": "https://x/a.jpg"},
            {"name": "巡夜", "kind": "character", "url": "https://x/b.jpg"},
            {"name": "伊莎", "kind": "character", "url": "https://x/c.jpg"},
            {"name": "环礁城", "kind": "scene", "url": "https://x/d.jpg"},
            {"name": "本镜动作构图帧", "kind": "preview_action", "url": "https://x/action.jpg"},
        ]
        kept = media._cap_reference_images(refs, 4)
        self.assertEqual(len(kept), 4)
        self.assertEqual(kept[-1]["kind"], "preview_action")
        self.assertNotIn("https://x/d.jpg", [ref["url"] for ref in kept])

        content = media._build_ark_content(
            "阿澈受伤后继续前进",
            "seedance-2-0-pro",
            image_url="https://x/keyframe.jpg",
            reference_images=refs,
            max_refs=4,
        )
        sent_urls = [
            item["image_url"]["url"]
            for item in content
            if item.get("role") == "reference_image"
        ]
        self.assertEqual(len(sent_urls), 4)
        self.assertIn("https://x/action.jpg", sent_urls)
        self.assertIn("只约束本镜的姿势、动作、朝向、构图与空间关系", content[0]["text"])


if __name__ == "__main__":
    unittest.main()
