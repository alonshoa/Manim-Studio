from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
import textwrap
import unittest
from pathlib import Path

from manim_studio.catalog import validate_catalog
from manim_studio.cli import main


class CatalogValidationTests(unittest.TestCase):
    def test_checked_in_catalog_registers_example_scenes(self) -> None:
        if importlib.util.find_spec("manim") is None:
            self.skipTest("manim is not installed in this Python environment")
        if importlib.util.find_spec("manim_slides") is None:
            self.skipTest("manim_slides is not installed in this Python environment")

        repo_root = Path(__file__).resolve().parents[1]

        result = validate_catalog(repo_root)

        self.assertTrue(result.ok, result.errors)
        self.assertEqual(2, len(result.entries))
        self.assertEqual(
            {("examples", "square_to_circle"), ("examples", "basic_slide")},
            {(entry.deck_id, entry.scene_id) for entry in result.entries},
        )

    def test_valid_catalog(self) -> None:
        with CatalogFixture() as fixture:
            fixture.write_scene("scene.py", "class DemoScene:\n    pass\n")
            fixture.write_catalog(
                """
                version: 1
                scenes:
                  - deck_id: demo
                    scene_id: intro
                    source_path: scene.py
                    class_name: DemoScene
                    base_scene_type: Scene
                    renderer: manim
                    language: en
                """
            )

            result = validate_catalog(fixture.root)

        self.assertTrue(result.ok, result.errors)
        self.assertEqual((), result.errors)
        self.assertEqual(1, len(result.entries))

    def test_duplicate_scene_ids_within_deck(self) -> None:
        with CatalogFixture() as fixture:
            fixture.write_scene("scene.py", "class DemoScene:\n    pass\n")
            fixture.write_catalog(
                """
                version: 1
                scenes:
                  - deck_id: demo
                    scene_id: intro
                    source_path: scene.py
                    class_name: DemoScene
                    base_scene_type: Scene
                    renderer: manim
                    language: en
                  - deck_id: demo
                    scene_id: intro
                    source_path: scene.py
                    class_name: DemoScene
                    base_scene_type: Scene
                    renderer: manim
                    language: en
                """
            )

            result = validate_catalog(fixture.root)

        self.assertFalse(result.ok)
        self.assert_error_contains(result, "duplicate deck_id + scene_id")

    def test_missing_source_path(self) -> None:
        with CatalogFixture() as fixture:
            fixture.write_catalog(
                """
                version: 1
                scenes:
                  - deck_id: demo
                    scene_id: intro
                    source_path: missing.py
                    class_name: DemoScene
                    base_scene_type: Scene
                    renderer: manim
                    language: en
                """
            )

            result = validate_catalog(fixture.root)

        self.assertFalse(result.ok)
        self.assert_error_contains(result, "source file does not exist")

    def test_missing_class_name(self) -> None:
        with CatalogFixture() as fixture:
            fixture.write_scene("scene.py", "class OtherScene:\n    pass\n")
            fixture.write_catalog(
                """
                version: 1
                scenes:
                  - deck_id: demo
                    scene_id: intro
                    source_path: scene.py
                    class_name: DemoScene
                    base_scene_type: Scene
                    renderer: manim
                    language: en
                """
            )

            result = validate_catalog(fixture.root)

        self.assertFalse(result.ok)
        self.assert_error_contains(result, "class 'DemoScene' was not found")

    def test_missing_required_field(self) -> None:
        with CatalogFixture() as fixture:
            fixture.write_catalog(
                """
                version: 1
                scenes:
                  - deck_id: demo
                    source_path: scene.py
                    class_name: DemoScene
                    base_scene_type: Scene
                    renderer: manim
                    language: en
                """
            )

            result = validate_catalog(fixture.root)

        self.assertFalse(result.ok)
        self.assert_error_contains(result, "missing required field")
        self.assert_error_contains(result, "scene_id")

    def test_invalid_renderer(self) -> None:
        with CatalogFixture() as fixture:
            fixture.write_scene("scene.py", "class DemoScene:\n    pass\n")
            fixture.write_catalog(
                """
                version: 1
                scenes:
                  - deck_id: demo
                    scene_id: intro
                    source_path: scene.py
                    class_name: DemoScene
                    base_scene_type: Scene
                    renderer: blender
                    language: en
                """
            )

            result = validate_catalog(fixture.root)

        self.assertFalse(result.ok)
        self.assert_error_contains(result, "renderer 'blender' is not supported")

    def test_cli_returns_nonzero_for_invalid_catalog(self) -> None:
        with CatalogFixture() as fixture:
            fixture.write_catalog(
                """
                version: 1
                scenes:
                  - deck_id: demo
                    scene_id: intro
                    source_path: missing.py
                    class_name: DemoScene
                    base_scene_type: Scene
                    renderer: manim
                    language: en
                """
            )

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(
                    [
                        "catalog",
                        "validate",
                        "--repo-root",
                        str(fixture.root),
                    ]
                )

        self.assertEqual(1, exit_code)
        self.assertIn("Catalog validation failed:", output.getvalue())

    def assert_error_contains(self, result, text: str) -> None:
        self.assertTrue(
            any(text in error for error in result.errors),
            f"{text!r} not found in {result.errors!r}",
        )


class CatalogFixture:
    def __enter__(self) -> "CatalogFixture":
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "catalog").mkdir()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.tempdir.cleanup()

    def write_scene(self, relative_path: str, content: str) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def write_catalog(self, content: str) -> None:
        (self.root / "catalog" / "scenes.yaml").write_text(
            textwrap.dedent(content).strip() + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
