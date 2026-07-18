from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from manim_studio.catalog import CatalogEntry
from manim_studio.profiles import get_profile
from manim_studio.validation import validate_scene_preflight


class ScenePreflightValidationTests(unittest.TestCase):
    def test_valid_scene_passes(self) -> None:
        with ValidationFixture() as fixture:
            fixture.write_scene("scene.py", "class DemoScene:\n    pass\n")

            result = validate_scene_preflight(
                fixture.root,
                fixture.entry(),
                get_profile("draft"),
                check_executables=False,
            )

        self.assertTrue(result.ok, result.issues)

    def test_reports_python_syntax_error(self) -> None:
        with ValidationFixture() as fixture:
            fixture.write_scene("scene.py", "class DemoScene(:\n    pass\n")

            result = validate_scene_preflight(
                fixture.root,
                fixture.entry(),
                get_profile("draft"),
                check_executables=False,
            )

        self.assertFalse(result.ok)
        self.assert_issue(result, "python_syntax_error")

    def test_reports_missing_scene_class(self) -> None:
        with ValidationFixture() as fixture:
            fixture.write_scene("scene.py", "class OtherScene:\n    pass\n")

            result = validate_scene_preflight(
                fixture.root,
                fixture.entry(),
                get_profile("draft"),
                check_executables=False,
            )

        self.assertFalse(result.ok)
        self.assert_issue(result, "missing_scene_class")

    def test_reports_failed_import(self) -> None:
        with ValidationFixture() as fixture:
            fixture.write_scene(
                "scene.py",
                "import module_that_should_not_exist\n\nclass DemoScene:\n    pass\n",
            )

            result = validate_scene_preflight(
                fixture.root,
                fixture.entry(),
                get_profile("draft"),
                check_executables=False,
            )

        self.assertFalse(result.ok)
        self.assert_issue(result, "source_import_failed")

    def test_reports_missing_literal_asset(self) -> None:
        with ValidationFixture() as fixture:
            fixture.write_scene(
                "scene.py",
                textwrap.dedent(
                    """
                    class DemoScene:
                        def construct(self):
                            ImageMobject("assets/missing.png")
                    """
                ).strip()
                + "\n",
            )

            result = validate_scene_preflight(
                fixture.root,
                fixture.entry(),
                get_profile("draft"),
                check_executables=False,
            )

        self.assertFalse(result.ok)
        self.assert_issue(result, "missing_asset")

    def test_reports_unsupported_renderer(self) -> None:
        with ValidationFixture() as fixture:
            fixture.write_scene("scene.py", "class DemoScene:\n    pass\n")

            result = validate_scene_preflight(
                fixture.root,
                fixture.entry(renderer="blender"),
                get_profile("draft"),
                check_executables=False,
            )

        self.assertFalse(result.ok)
        self.assert_issue(result, "unsupported_renderer")

    def test_reports_missing_renderer_executable(self) -> None:
        with ValidationFixture() as fixture:
            fixture.write_scene("scene.py", "class DemoScene:\n    pass\n")

            result = validate_scene_preflight(
                fixture.root,
                fixture.entry(),
                get_profile("draft"),
                check_executables=True,
                executable_resolver=lambda _name: None,
            )

        self.assertFalse(result.ok)
        self.assert_issue(result, "missing_renderer_executable")

    def assert_issue(self, result, code: str) -> None:
        self.assertTrue(
            any(issue.code == code for issue in result.issues),
            f"{code!r} not found in {result.issues!r}",
        )


class ValidationFixture:
    def __enter__(self) -> "ValidationFixture":
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.tempdir.cleanup()

    def write_scene(self, relative_path: str, content: str) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def entry(self, renderer: str = "manim") -> CatalogEntry:
        return CatalogEntry(
            deck_id="demo",
            scene_id="intro",
            source_path="scene.py",
            class_name="DemoScene",
            base_scene_type="Scene",
            renderer=renderer,
            language="en",
        )


if __name__ == "__main__":
    unittest.main()
