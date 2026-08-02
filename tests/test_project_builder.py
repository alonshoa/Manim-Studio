from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from manim_studio.catalog import validate_catalog
from manim_studio.project_builder import (
    ProjectBuilderError,
    create_project,
    default_class_name,
    default_options,
    slugify_identifier,
)


class ProjectBuilderTests(unittest.TestCase):
    def test_defaults_sanitize_names_for_catalog_and_class(self) -> None:
        options = default_options(
            path="C:/tmp/123 Demo Slides!",
            name="123 Demo Slides!",
        )

        self.assertEqual("project_123_demo_slides", options.deck_id)
        self.assertEqual("intro", options.scene_id)
        self.assertEqual("Project123DemoSlidesIntroSlide", options.class_name)
        self.assertEqual("project", slugify_identifier("!!!"))
        self.assertEqual("MyDeckIntroSlide", default_class_name("My Deck"))

    def test_create_project_writes_expected_layout_and_mcp_config(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir) / "generated"
            options = default_options(
                path=root,
                name="Demo Project",
                image_tag="manim-studio:test",
            )
            result = create_project(options)

            expected_files = {
                ".gitignore",
                "README.md",
                "AGENTS.md",
                "compose.yml",
                "mcp.manim-studio.json",
                "catalog/scenes.yaml",
                "decks/demo_project/intro.py",
                "baselines/demo_project/intro/README.md",
                "docs/conventions.md",
                "tools/studio.cmd",
                "tools/start-mcp.cmd",
                "tools/start-mcp.ps1",
                "tools/stop-mcp.cmd",
                "tools/stop-mcp.ps1",
                "tools/validate.cmd",
                "tools/render-draft.cmd",
            }

            relative_written = {
                path.relative_to(root).as_posix() for path in result.files_written
            }
            self.assertEqual(expected_files, relative_written)
            self.assertIn("image: manim-studio:test", (root / "compose.yml").read_text())
            self.assertIn("MANIM_STUDIO_REPO_ROOT: /workspace", (root / "compose.yml").read_text())
            self.assertIn(
                "Python scene files are the source of truth",
                (root / "AGENTS.md").read_text(),
            )

            mcp_config = json.loads((root / "mcp.manim-studio.json").read_text())
            args = mcp_config["mcpServers"]["manim-studio"]["args"]
            self.assertIn("-i", args)
            self.assertNotIn("-t", args)
            self.assertIn("manim-studio:test", args)
            self.assertIn("manim-mcp", args)

            validate_script = (root / "tools" / "validate.cmd").read_text()
            self.assertIn("doctor --catalog", validate_script)
            self.assertIn("validate demo_project/intro", validate_script)

    def test_create_project_rejects_non_empty_directory_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "existing.txt").write_text("keep", encoding="utf-8")
            options = default_options(path=root, name="Demo Project")

            with self.assertRaises(ProjectBuilderError):
                create_project(options)

    def test_create_project_does_not_run_docker_subprocesses(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            options = default_options(path=root, name="Demo Project")

            with patch.object(subprocess, "run") as run:
                create_project(options)

            run.assert_not_called()

    def test_force_allows_overwriting_generated_files(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / ".gitignore").write_text("old", encoding="utf-8")
            options = default_options(path=root, name="Demo Project", force=True)

            create_project(options)

            self.assertIn("Manim Studio generated output", (root / ".gitignore").read_text())

    def test_generated_catalog_validates_with_lightweight_manim_stubs(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            options = default_options(path=root, name="Demo Project")
            create_project(options)

            fake_manim = types.ModuleType("manim")
            for name in ("DOWN", "FadeIn", "FadeOut", "LEFT", "Text", "VGroup"):
                setattr(fake_manim, name, object())

            fake_kit = types.ModuleType("manim_kit")
            fake_kit.BeatMixin = type("BeatMixin", (), {})

            fake_slides = types.ModuleType("manim_slides")
            fake_slides.Slide = type("Slide", (), {})

            with patch.dict(
                sys.modules,
                {
                    "manim": fake_manim,
                    "manim_kit": fake_kit,
                    "manim_slides": fake_slides,
                },
            ):
                result = validate_catalog(root, strict_metadata=True)

            self.assertTrue(result.ok, result.errors)
            self.assertEqual("demo_project", result.entries[0].deck_id)

    def test_installer_entrypoints_are_present_and_delegate_correctly(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]

        root_cmd = (repo_root / "new-manim-project.cmd").read_text(encoding="utf-8")
        ps1 = (repo_root / "scripts" / "new_manim_project.ps1").read_text(encoding="utf-8")

        self.assertIn("scripts\\new_manim_project.ps1", root_cmd)
        self.assertIn("-m manim_studio.cli project init", ps1)
        self.assertNotIn("manim_studio.project_builder", ps1)
        self.assertNotIn("--studio-root", ps1)


if __name__ == "__main__":
    unittest.main()
