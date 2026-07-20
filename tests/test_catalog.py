from __future__ import annotations

import contextlib
import importlib.util
import io
import tempfile
import textwrap
import unittest
from pathlib import Path

from manim_studio.catalog import (
    find_scene_entry,
    load_catalog_entries,
    list_deck_entries,
    list_decks,
    parse_scene_target,
    validate_catalog,
    validate_catalog_selection,
)
from manim_studio.cli import main


class CatalogValidationTests(unittest.TestCase):
    def test_checked_in_catalog_registers_expected_scenes(self) -> None:
        if importlib.util.find_spec("manim") is None:
            self.skipTest("manim is not installed in this Python environment")
        if importlib.util.find_spec("manim_slides") is None:
            self.skipTest("manim_slides is not installed in this Python environment")

        repo_root = Path(__file__).resolve().parents[1]

        result = validate_catalog(repo_root)

        self.assertTrue(result.ok, result.errors)
        self.assertEqual(
            {
                ("examples", "square_to_circle"),
                ("examples", "basic_slide"),
                ("matrix_work", "vectors_ab_to_v"),
                ("losses", "binary_cross_entropy"),
                ("matrix_work", "parametric_curve_3d"),
            },
            {(entry.deck_id, entry.scene_id) for entry in result.entries},
        )

    def test_external_project_fixture_validates_with_strict_metadata(self) -> None:
        if importlib.util.find_spec("manim") is None:
            self.skipTest("manim is not installed in this Python environment")

        fixture_root = Path(__file__).resolve().parent / "fixtures" / "external_project"

        result = validate_catalog(fixture_root, strict_metadata=True)

        self.assertTrue(result.ok, result.errors)
        self.assertEqual(
            ("demo", "smoke"),
            (result.entries[0].deck_id, result.entries[0].scene_id),
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

    def test_catalog_lookup_helpers(self) -> None:
        with CatalogFixture() as fixture:
            fixture.write_scene("scene.py", "class DemoScene:\n    pass\n")
            fixture.write_scene("other.py", "class OtherScene:\n    pass\n")
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
                  - deck_id: other
                    scene_id: intro
                    source_path: other.py
                    class_name: OtherScene
                    base_scene_type: Scene
                    renderer: manim
                    language: en
                """
            )

            result = validate_catalog(fixture.root)

        self.assertTrue(result.ok, result.errors)
        self.assertEqual(("demo", "other"), list_decks(result.entries))
        self.assertEqual(1, len(list_deck_entries(result.entries, "demo")))
        self.assertIsNotNone(find_scene_entry(result.entries, "demo", "intro"))
        self.assertIsNone(find_scene_entry(result.entries, "demo", "missing"))
        self.assertEqual(("demo", "intro"), parse_scene_target("demo/intro"))

    def test_invalid_scene_target_syntax(self) -> None:
        with self.assertRaisesRegex(ValueError, "scene target"):
            parse_scene_target("demo")

    def test_load_catalog_entries_does_not_import_source_file(self) -> None:
        with CatalogFixture() as fixture:
            fixture.write_scene(
                "scene.py",
                "import module_that_should_not_exist\n\nclass DemoScene:\n    pass\n",
            )
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

            loaded = load_catalog_entries(fixture.root)
            validated = validate_catalog(fixture.root)

        self.assertTrue(loaded.ok, loaded.errors)
        self.assertFalse(validated.ok)
        self.assert_error_contains(validated, "source file import failed")

    def test_validate_catalog_selection_ignores_unselected_import_failures(self) -> None:
        with CatalogFixture() as fixture:
            fixture.write_scene("scene.py", "class DemoScene:\n    pass\n")
            fixture.write_scene(
                "broken.py",
                "import module_that_should_not_exist\n\nclass BrokenScene:\n    pass\n",
            )
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
                  - deck_id: other
                    scene_id: broken
                    source_path: broken.py
                    class_name: BrokenScene
                    base_scene_type: Scene
                    renderer: manim
                    language: en
                """
            )

            selected = validate_catalog_selection(
                fixture.root,
                deck_id="demo",
                scene_id="intro",
            )
            all_entries = validate_catalog(fixture.root)

        self.assertTrue(selected.ok, selected.errors)
        self.assertEqual(1, len(selected.entries))
        self.assertFalse(all_entries.ok)
        self.assert_error_contains(all_entries, "source file import failed")

    def test_valid_catalog_with_planning_metadata(self) -> None:
        with CatalogFixture() as fixture:
            fixture.write_scene("scene.py", "class DemoScene:\n    pass\n")
            fixture.write_baseline("baselines/demo/intro")
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
                    description: Demo scene.
                    asset_notes: No external assets.
                    font_notes: No special fonts.
                    parameter_notes: No parameters.
                    render_command: manim -ql scene.py DemoScene
                    baseline_path: baselines/demo/intro
                    migration_notes: Native fixture.
                """
            )

            result = validate_catalog(fixture.root, strict_metadata=True)

        self.assertTrue(result.ok, result.errors)
        self.assertEqual("Demo scene.", result.entries[0].description)
        self.assertEqual("baselines/demo/intro", result.entries[0].baseline_path)

    def test_optional_metadata_fields_must_be_strings(self) -> None:
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
                    parameter_notes:
                      - not
                      - a string
                """
            )

            result = validate_catalog(fixture.root)

        self.assertFalse(result.ok)
        self.assert_error_contains(result, "'parameter_notes' must be a string")

    def test_strict_metadata_requires_planning_fields(self) -> None:
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

            result = validate_catalog(fixture.root, strict_metadata=True)

        self.assertFalse(result.ok)
        self.assert_error_contains(result, "description is required")
        self.assert_error_contains(result, "render_command is required")
        self.assert_error_contains(result, "baseline_path is required")

    def test_baseline_path_must_exist_when_declared(self) -> None:
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
                    baseline_path: baselines/demo/missing
                """
            )

            result = validate_catalog(fixture.root)

        self.assertFalse(result.ok)
        self.assert_error_contains(result, "baseline_path does not exist")

    def test_rtl_entries_require_font_notes(self) -> None:
        with CatalogFixture() as fixture:
            fixture.write_scene("scene.py", "class DemoScene:\n    pass\n")
            fixture.write_catalog(
                """
                version: 1
                scenes:
                  - deck_id: demo
                    scene_id: rtl_intro
                    source_path: scene.py
                    class_name: DemoScene
                    base_scene_type: Scene
                    renderer: manim
                    language: he
                """
            )

            result = validate_catalog(fixture.root)

        self.assertFalse(result.ok)
        self.assert_error_contains(result, "font_notes must describe Hebrew/RTL")

    def test_render_command_must_match_source_and_class_when_declared(self) -> None:
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
                    render_command: manim -ql other.py OtherScene
                """
            )

            result = validate_catalog(fixture.root)

        self.assertFalse(result.ok)
        self.assert_error_contains(result, "render_command must include source_path")
        self.assert_error_contains(result, "render_command must include class_name")

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

    def test_cli_strict_metadata_flag(self) -> None:
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

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(
                    [
                        "catalog",
                        "validate",
                        "--repo-root",
                        str(fixture.root),
                        "--strict-metadata",
                    ]
                )

        self.assertEqual(1, exit_code)
        self.assertIn("description is required", output.getvalue())

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

    def write_baseline(self, relative_path: str) -> None:
        path = self.root / relative_path
        path.mkdir(parents=True, exist_ok=True)
        (path / "README.md").write_text("baseline\n", encoding="utf-8")

    def write_catalog(self, content: str) -> None:
        (self.root / "catalog" / "scenes.yaml").write_text(
            textwrap.dedent(content).strip() + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
