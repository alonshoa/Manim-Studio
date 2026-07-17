from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from manim_studio.beats import beat_by_id, discover_scene_beats


class BeatDiscoveryTests(unittest.TestCase):
    def test_discovers_literal_self_beat_calls_in_source_order(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "scene.py"
            path.write_text(
                textwrap.dedent(
                    """
                    class DemoScene:
                        def construct(self):
                            self.beat("intro", label="Title")
                            self.helper.beat("ignored")
                            self.beat("result", "Show result")
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            result = discover_scene_beats(path)

        self.assertTrue(result.ok, result.errors)
        self.assertEqual(["intro", "result"], [beat.id for beat in result.beats])
        self.assertEqual(["Title", "Show result"], [beat.label for beat in result.beats])
        self.assertIsNotNone(beat_by_id(result.beats, "result"))
        self.assertIsNone(beat_by_id(result.beats, "missing"))

    def test_reports_duplicate_beat_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "scene.py"
            path.write_text(
                textwrap.dedent(
                    """
                    class DemoScene:
                        def construct(self):
                            self.beat("intro")
                            self.beat("intro", label="Duplicate")
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            result = discover_scene_beats(path)

        self.assertFalse(result.ok)
        self.assertTrue(any("duplicate beat id 'intro'" in error for error in result.errors))

    def test_ignores_dynamic_beat_calls_for_v1(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "scene.py"
            path.write_text(
                textwrap.dedent(
                    """
                    class DemoScene:
                        def construct(self):
                            beat_id = "intro"
                            self.beat(beat_id)
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            result = discover_scene_beats(path)

        self.assertTrue(result.ok, result.errors)
        self.assertEqual((), result.beats)


if __name__ == "__main__":
    unittest.main()
