from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "generate_timeline.py"
SPEC = importlib.util.spec_from_file_location("generate_timeline", SCRIPT)
assert SPEC and SPEC.loader
timeline = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = timeline
SPEC.loader.exec_module(timeline)


def item(item_type: str) -> dict:
    return {
        "pk": "123",
        "item_type": item_type,
        "repository": "owner/media",
        "media_commit": "a" * 40,
        "path": f"{item_type}s/2026/07/24/item",
    }


class TimelineTests(unittest.TestCase):
    def test_quote_preserves_paragraphs_without_trailing_whitespace(self):
        result = timeline.quote("first line \n\nsecond line\t")
        self.assertEqual(result, "> first line\n>\n> second line")

    def test_image_preview_escapes_all_dynamic_attributes(self):
        result = timeline.image_preview(
            source='https://example.test/a?x="1"&y=2',
            href='https://example.test/b?x="2"&y=3',
            alt='A "quoted" & labeled image',
            width=360,
        )
        self.assertIn('x=&quot;1&quot;&amp;y=2', result)
        self.assertIn('x=&quot;2&quot;&amp;y=3', result)
        self.assertIn('A &quot;quoted&quot; &amp; labeled image', result)

    def test_story_and_post_images_use_expected_widths(self):
        position = {
            "media_index": 1,
            "presentation_kind": "image",
            "assets": [{"role": "image", "filename": "01-image.jpg"}],
        }
        self.assertIn('width="360"', timeline.display_asset(item("story"), position)[0])
        self.assertIn('width="720"', timeline.display_asset(item("post"), position)[0])

    def test_image_with_audio_has_blank_line_before_play_link(self):
        position = {
            "media_index": 1,
            "presentation_kind": "image_with_audio",
            "assets": [
                {"role": "image", "filename": "01-image.jpg"},
                {"role": "playable_video", "filename": "01-video.mp4"},
            ],
        }
        output = ["before"]
        timeline.append_block(output, timeline.display_asset(item("story"), position))
        text = "\n".join(output + ["after"])
        self.assertIn("before\n\n<a href=", text)
        self.assertIn("</a>\n\n[▶ 播放带声音版本", text)
        self.assertIn("Direct file", text)

    def test_video_poster_is_clickable_and_block_spaced(self):
        position = {
            "media_index": 1,
            "presentation_kind": "video",
            "assets": [
                {"role": "primary_video", "filename": "01-video.mp4"},
                {"role": "video_poster", "filename": "01-poster.jpg"},
            ],
        }
        output = ["before"]
        timeline.append_block(output, timeline.display_asset(item("post"), position))
        text = "\n".join(output + ["after"])
        self.assertIn('width="720"', text)
        self.assertIn("</a>\n\n[▶ 播放视频", text)


if __name__ == "__main__":
    unittest.main()
