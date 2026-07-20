from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from manim_kit import BeatMixin, DEFAULT_THEME, StudioTheme
from manim_kit.beats import _section_name


MANIM_AVAILABLE = importlib.util.find_spec("manim") is not None
SLIDES_AVAILABLE = importlib.util.find_spec("manim_slides") is not None


class ManimKitTests(unittest.TestCase):
    def test_theme_defaults_are_plain_python_values(self) -> None:
        self.assertIsInstance(DEFAULT_THEME, StudioTheme)
        self.assertEqual("DejaVu Sans", DEFAULT_THEME.hebrew_font)
        self.assertGreater(DEFAULT_THEME.panel_max_width, 0)
        self.assertGreater(DEFAULT_THEME.panel_stroke_opacity, 0)

    def test_package_keeps_beat_import_available(self) -> None:
        self.assertTrue(issubclass(BeatMixin, object))

    def test_beat_section_names_are_windows_filename_safe(self) -> None:
        section_name = _section_name(
            "transform:part",
            'Transform square: circle / review? <unsafe>|*',
        )

        self.assertEqual(
            "transform-part - Transform square- circle - review- -unsafe",
            section_name,
        )
        self.assertFalse(set(section_name) & set('<>:"/\\|?*'))

    def test_beat_mixin_uses_filename_safe_section_names(self) -> None:
        class DummyScene(BeatMixin):
            def __init__(self) -> None:
                self.sections: list[tuple[str, bool]] = []

            def next_section(self, name: str, skip_animations: bool = False) -> None:
                self.sections.append((name, skip_animations))

        scene = DummyScene()

        scene.beat("transform", label="Transform square: circle / review?")

        self.assertEqual(
            [("transform - Transform square- circle - review", False)],
            scene.sections,
        )
        self.assertFalse(set(scene.sections[0][0]) & set('<>:"/\\|?*'))

    def test_lightweight_public_imports_do_not_load_studio_tooling(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        script = """
import json
import sys

import manim_kit
from manim_kit import BeatMixin, DEFAULT_THEME, StudioTheme

print(json.dumps({
    "beat_is_class": issubclass(BeatMixin, object),
    "font": DEFAULT_THEME.hebrew_font,
    "theme": StudioTheme.__name__,
    "studio_modules": [
        name for name in sys.modules
        if name == "manim_studio" or name.startswith("manim_studio.")
    ],
}))
"""

        result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            cwd=repo_root,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )

        payload = json.loads(result.stdout)
        self.assertTrue(payload["beat_is_class"])
        self.assertEqual("DejaVu Sans", payload["font"])
        self.assertEqual("StudioTheme", payload["theme"])
        self.assertEqual([], payload["studio_modules"])

    @unittest.skipUnless(MANIM_AVAILABLE, "manim is not installed")
    def test_hebrew_text_uses_theme_font_and_scale(self) -> None:
        from manim_kit import hebrew_text

        text = hebrew_text("sample", scale=0.5)

        self.assertEqual(DEFAULT_THEME.hebrew_font, text.font)
        self.assertLess(text.height, hebrew_text("sample").height)

    @unittest.skipUnless(MANIM_AVAILABLE, "manim is not installed")
    def test_rtl_column_aligns_right_edges(self) -> None:
        from manim import Text
        from manim_kit import rtl_column

        first = Text("first", font=DEFAULT_THEME.body_font)
        second = Text("second", font=DEFAULT_THEME.body_font)

        column = rtl_column(first, second)

        self.assertEqual(2, len(column))
        self.assertAlmostEqual(
            column[0].get_right()[0],
            column[1].get_right()[0],
            places=6,
        )

    @unittest.skipUnless(MANIM_AVAILABLE, "manim is not installed")
    def test_explanation_panel_wraps_content_without_hiding_it(self) -> None:
        from manim import Text
        from manim_kit import explanation_panel

        content = Text("panel", font=DEFAULT_THEME.body_font)
        panel = explanation_panel(content, max_width=1.0)

        self.assertEqual(2, len(panel))
        self.assertIs(panel[1], content)
        self.assertLessEqual(content.width, 1.01)
        self.assertGreater(panel[0].width, content.width)

    @unittest.skipUnless(MANIM_AVAILABLE, "manim is not installed")
    def test_code_panel_creates_framed_monospaced_text(self) -> None:
        from manim_kit import code_panel

        panel = code_panel("x = 1")

        self.assertEqual(2, len(panel))
        self.assertEqual(DEFAULT_THEME.code_font, panel[1].font)

    @unittest.skipUnless(
        MANIM_AVAILABLE and SLIDES_AVAILABLE,
        "manim and manim-slides are not installed",
    )
    def test_slide_bases_preserve_beat_mixin(self) -> None:
        from manim_kit import HebrewSlide, StudioSlide

        self.assertTrue(issubclass(StudioSlide, BeatMixin))
        self.assertTrue(issubclass(HebrewSlide, StudioSlide))
        self.assertEqual("he", HebrewSlide.language)
        self.assertIs(DEFAULT_THEME, HebrewSlide.theme)


if __name__ == "__main__":
    unittest.main()
