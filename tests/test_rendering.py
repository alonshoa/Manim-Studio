from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manim_studio.builds import BuildResult
from manim_studio.rendering import (
    RenderRequest,
    RenderRequestError,
    execute_render,
)


class RenderingApplicationServiceTests(unittest.TestCase):
    def test_resolves_scene_profile_and_executes_build(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            write_project(root)
            build = fake_build(root)

            with patch("manim_studio.rendering.render_scene", return_value=build) as renderer:
                result = execute_render(
                    RenderRequest(root, "demo/intro", "draft", force=True)
                )

            self.assertEqual(build, result.build)
            args, kwargs = renderer.call_args
            self.assertEqual(root, args[0])
            self.assertEqual("intro", args[1].scene_id)
            self.assertEqual("draft", args[2].name)
            self.assertTrue(kwargs["force"])
            self.assertIsNone(kwargs["beat_id"])

    def test_resolves_named_beat_once_for_all_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            write_project(root, with_beat=True)

            with patch(
                "manim_studio.rendering.render_scene",
                return_value=fake_build(root),
            ) as renderer:
                execute_render(
                    RenderRequest(root, "demo/intro", "draft", beat_id="result")
                )

            kwargs = renderer.call_args.kwargs
            self.assertEqual("result", kwargs["beat_id"])
            self.assertEqual("result", kwargs["beats"][0]["id"])

    def test_reports_available_beats_for_unknown_beat(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            write_project(root, with_beat=True)

            with self.assertRaises(RenderRequestError) as raised:
                execute_render(
                    RenderRequest(root, "demo/intro", "draft", beat_id="missing")
                )

            self.assertEqual("beat_not_found", raised.exception.code)
            self.assertEqual(
                "result",
                raised.exception.detail["available_beats"][0]["id"],
            )

    def test_rejects_unknown_target_before_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            write_project(root)

            with patch("manim_studio.rendering.render_scene") as renderer:
                with self.assertRaises(RenderRequestError) as raised:
                    execute_render(RenderRequest(root, "demo/missing", "draft"))

            self.assertEqual("target_not_found", raised.exception.code)
            renderer.assert_not_called()


def write_project(root: Path, with_beat: bool = False) -> None:
    catalog_dir = root / "catalog"
    catalog_dir.mkdir()
    catalog_dir.joinpath("scenes.yaml").write_text(
        """version: 1
scenes:
  - deck_id: demo
    scene_id: intro
    source_path: scene.py
    class_name: DemoScene
    base_scene_type: Scene
    renderer: manim
    language: en
""",
        encoding="utf-8",
    )
    body = "        self.beat('result', label='Show result')\n" if with_beat else "        pass\n"
    root.joinpath("scene.py").write_text(
        "class DemoScene:\n    def construct(self):\n" + body,
        encoding="utf-8",
    )


def fake_build(root: Path) -> BuildResult:
    return BuildResult(
        build_id="build-1",
        build_dir=root / "builds" / "build-1",
        target="demo/intro",
        profile="draft",
        status="success",
        returncode=0,
    )


if __name__ == "__main__":
    unittest.main()
