from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from manim_studio.builds import build_deck, command_for_entry, render_scene
from manim_studio.catalog import CatalogEntry
from manim_studio.profiles import get_profile


class BuildServiceTests(unittest.TestCase):
    def test_command_generation_uses_renderer_and_profile(self) -> None:
        profile = get_profile("draft")

        manim_command = command_for_entry(manim_entry(), profile, Path("out"))
        self.assertEqual("manim", manim_command[0])
        self.assertIn("-ql", manim_command)
        self.assertNotIn("--save_sections", manim_command)
        self.assertEqual("scene.py", manim_command[-2])
        self.assertEqual("DemoScene", manim_command[-1])

        slides_command = command_for_entry(slides_entry(), profile, Path("out"))
        self.assertEqual(["manim-slides", "render"], slides_command[:2])
        self.assertIn("-ql", slides_command)
        self.assertNotIn("--save_sections", slides_command)
        self.assertEqual("slide.py", slides_command[-2])
        self.assertEqual("DemoSlide", slides_command[-1])

        targeted_command = command_for_entry(
            slides_entry(),
            profile,
            Path("out"),
            save_sections=True,
        )
        self.assertIn("--save_sections", targeted_command)

    def test_render_scene_creates_unique_builds_and_logs_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runner = FakeRunner(returncode=0, stdout="ok\n")

            first = render_scene(root, manim_entry(), get_profile("draft"), runner=runner)
            second = render_scene(root, manim_entry(), get_profile("draft"), runner=runner)

            self.assertNotEqual(first.build_id, second.build_id)
            self.assertEqual("success", first.status)
            self.assertTrue((first.build_dir / "command.json").exists())
            self.assertEqual("ok\n", (first.build_dir / "stdout.log").read_text())

            artifacts = read_json(first.build_dir / "artifacts.json")
            self.assertEqual(
                [{"kind": "video", "path": "media/video.mp4"}],
                artifacts["artifacts"],
            )

    def test_failed_render_preserves_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runner = FakeRunner(returncode=2, stderr="render failed\n")

            result = render_scene(root, manim_entry(), get_profile("review"), runner=runner)

            self.assertEqual("failed", result.status)
            self.assertEqual(2, result.returncode)
            self.assertEqual("render failed\n", (result.build_dir / "stderr.log").read_text())
            result_json = read_json(result.build_dir / "result.json")
            self.assertEqual("failed", result_json["status"])
            self.assertEqual("demo/intro", result_json["target"])

    def test_targeted_render_records_beat_metadata_and_env(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runner = FakeRunner(returncode=0, stdout="ok\n")

            result = render_scene(
                root,
                slides_entry(),
                get_profile("draft"),
                runner=runner,
                beat_id="result",
                beats=[{"id": "result", "label": "Show result", "line": 12}],
            )

            command = runner.commands[0]
            self.assertIn("--save_sections", command)
            self.assertEqual("result", runner.envs[0]["MANIM_STUDIO_BEAT"])
            result_json = read_json(result.build_dir / "result.json")
            self.assertEqual("result", result_json["requested_beat"])
            beats_json = read_json(result.build_dir / "beats.json")
            self.assertEqual(
                [{"id": "result", "label": "Show result", "line": 12}],
                beats_json["beats"],
            )

    def test_build_deck_runs_entries_serially_and_writes_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runner = FakeRunner(returncode=0, stdout="ok\n")

            result = build_deck(
                root,
                "demo",
                [manim_entry(), slides_entry()],
                get_profile("review"),
                runner=runner,
            )

            self.assertEqual("success", result.status)
            self.assertEqual(
                [
                    ["manim", "-qm"],
                    ["manim-slides", "render"],
                ],
                [command[:2] for command in runner.commands],
            )
            summary = read_json(result.build_dir / "result.json")
            self.assertEqual("deck", summary["kind"])
            self.assertEqual(2, len(summary["scene_builds"]))


class FakeRunner:
    def __init__(
        self,
        returncode: int,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.commands: list[list[str]] = []
        self.envs: list[dict[str, str]] = []

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        self.envs.append(kwargs.get("env") or {})
        media_dir = Path(command[command.index("--media_dir") + 1])
        media_dir.mkdir(parents=True, exist_ok=True)
        if self.returncode == 0:
            (media_dir / "video.mp4").write_bytes(b"fake mp4")
        return subprocess.CompletedProcess(
            args=command,
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )


def manim_entry() -> CatalogEntry:
    return CatalogEntry(
        deck_id="demo",
        scene_id="intro",
        source_path="scene.py",
        class_name="DemoScene",
        base_scene_type="Scene",
        renderer="manim",
        language="en",
    )


def slides_entry() -> CatalogEntry:
    return CatalogEntry(
        deck_id="demo",
        scene_id="slides",
        source_path="slide.py",
        class_name="DemoSlide",
        base_scene_type="Slide",
        renderer="manim-slides",
        language="en",
    )


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
