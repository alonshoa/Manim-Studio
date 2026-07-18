from __future__ import annotations

import contextlib
import io
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from manim_studio.cli import build_parser, main, run_build, run_render
from manim_studio.profiles import profile_names


class StudioCliTests(unittest.TestCase):
    def test_profile_choices_come_from_profile_registry(self) -> None:
        parser = build_parser()

        self.assertEqual(profile_names(), find_profile_choices(parser, "render"))
        self.assertEqual(profile_names(), find_profile_choices(parser, "build"))

    def test_list_prints_decks_and_scenes(self) -> None:
        with StudioFixture() as fixture:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(["list", "--repo-root", str(fixture.root)])

        self.assertEqual(0, exit_code)
        self.assertIn("demo", output.getvalue())
        self.assertIn("intro", output.getvalue())

    def test_validate_accepts_scene_and_deck_targets(self) -> None:
        with StudioFixture() as fixture:
            scene_output = io.StringIO()
            with contextlib.redirect_stdout(scene_output):
                scene_exit = main(
                    ["validate", "demo/intro", "--repo-root", str(fixture.root)]
                )

            deck_output = io.StringIO()
            with contextlib.redirect_stdout(deck_output):
                deck_exit = main(["validate", "demo", "--repo-root", str(fixture.root)])

        self.assertEqual(0, scene_exit)
        self.assertIn("Target valid: demo/intro", scene_output.getvalue())
        self.assertEqual(0, deck_exit)
        self.assertIn("Target valid: demo (2 scene(s))", deck_output.getvalue())

    def test_validate_reports_missing_target(self) -> None:
        with StudioFixture() as fixture:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(
                    ["validate", "demo/missing", "--repo-root", str(fixture.root)]
                )

        self.assertEqual(1, exit_code)
        self.assertIn("Target not found: demo/missing", output.getvalue())

    def test_render_uses_fake_runner_and_can_be_inspected(self) -> None:
        with StudioFixture() as fixture:
            runner = FakeRunner(returncode=0, stdout="rendered\n")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = run_render(
                    "demo/intro",
                    "draft",
                    repo_root=fixture.root,
                    runner=runner,
                )

            build_id = output.getvalue().splitlines()[0].split(": ", maxsplit=1)[1]
            inspect_output = io.StringIO()
            with contextlib.redirect_stdout(inspect_output):
                inspect_exit = main(
                    ["inspect", build_id, "--repo-root", str(fixture.root)]
                )

        self.assertEqual(0, exit_code)
        self.assertEqual(0, inspect_exit)
        self.assertIn("Status: success", inspect_output.getvalue())
        self.assertIn("Artifacts:", inspect_output.getvalue())

    def test_beats_lists_scene_beats(self) -> None:
        with StudioFixture() as fixture:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(["beats", "demo/slides", "--repo-root", str(fixture.root)])

        self.assertEqual(0, exit_code)
        self.assertIn("demo/slides", output.getvalue())
        self.assertIn("result", output.getvalue())
        self.assertIn("Show result", output.getvalue())

    def test_beats_reports_missing_target(self) -> None:
        with StudioFixture() as fixture:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(
                    ["beats", "demo/missing", "--repo-root", str(fixture.root)]
                )

        self.assertEqual(1, exit_code)
        self.assertIn("Target not found: demo/missing", output.getvalue())

    def test_render_with_beat_validates_and_records_target(self) -> None:
        with StudioFixture() as fixture:
            runner = FakeRunner(returncode=0)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = run_render(
                    "demo/slides",
                    "draft",
                    repo_root=fixture.root,
                    beat_id="result",
                    runner=runner,
                )

        self.assertEqual(0, exit_code)
        self.assertEqual(1, len(runner.commands))
        self.assertIn("--save_sections", runner.commands[0])
        self.assertEqual("result", runner.envs[0]["MANIM_STUDIO_BEAT"])
        self.assertIn("Build success:", output.getvalue())

    def test_render_with_unknown_beat_does_not_invoke_runner(self) -> None:
        with StudioFixture() as fixture:
            runner = FakeRunner(returncode=0)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = run_render(
                    "demo/slides",
                    "draft",
                    repo_root=fixture.root,
                    beat_id="missing",
                    runner=runner,
                )

        self.assertEqual(1, exit_code)
        self.assertEqual([], runner.commands)
        self.assertIn("Beat not found: missing", output.getvalue())

    def test_render_ignores_unrelated_catalog_import_failure(self) -> None:
        with StudioFixture() as fixture:
            fixture.add_unrelated_broken_scene()
            runner = FakeRunner(returncode=0)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = run_render(
                    "demo/intro",
                    "draft",
                    repo_root=fixture.root,
                    runner=runner,
                )

        self.assertEqual(0, exit_code)
        self.assertEqual(1, len(runner.commands))
        self.assertIn("Build success:", output.getvalue())

    def test_build_deck_uses_fake_runner(self) -> None:
        with StudioFixture() as fixture:
            runner = FakeRunner(returncode=0)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = run_build(
                    "demo",
                    "review",
                    repo_root=fixture.root,
                    runner=runner,
                )

        self.assertEqual(0, exit_code)
        self.assertEqual(4, len(runner.commands))
        self.assertIn("Deck build success:", output.getvalue())

    def test_build_deck_ignores_unrelated_catalog_import_failure(self) -> None:
        with StudioFixture() as fixture:
            fixture.add_unrelated_broken_scene()
            runner = FakeRunner(returncode=0)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = run_build(
                    "demo",
                    "review",
                    repo_root=fixture.root,
                    runner=runner,
                )

        self.assertEqual(0, exit_code)
        self.assertEqual(4, len(runner.commands))
        self.assertIn("Deck build success:", output.getvalue())

    def test_inspect_reports_manifest_validation_failure(self) -> None:
        with StudioFixture() as fixture:
            fixture.add_selected_broken_scene()
            runner = FakeRunner(returncode=0)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = run_render(
                    "demo/broken",
                    "draft",
                    repo_root=fixture.root,
                    runner=runner,
                )

            build_id = output.getvalue().splitlines()[0].split(": ", maxsplit=1)[1]
            inspect_output = io.StringIO()
            with contextlib.redirect_stdout(inspect_output):
                inspect_exit = main(
                    ["inspect", build_id, "--repo-root", str(fixture.root)]
                )

        self.assertEqual(1, exit_code)
        self.assertEqual([], runner.commands)
        self.assertEqual(0, inspect_exit)
        self.assertIn("Failure class: validation_failed", inspect_output.getvalue())
        self.assertIn("Preflight: failed", inspect_output.getvalue())
        self.assertIn("source_import_failed", inspect_output.getvalue())

    def test_force_records_override_and_runs_selected_broken_scene(self) -> None:
        with StudioFixture() as fixture:
            fixture.add_selected_broken_scene()
            runner = FakeRunner(returncode=0)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = run_render(
                    "demo/broken",
                    "draft",
                    repo_root=fixture.root,
                    force=True,
                    runner=runner,
                )

            build_id = output.getvalue().splitlines()[0].split(": ", maxsplit=1)[1]
            inspect_output = io.StringIO()
            with contextlib.redirect_stdout(inspect_output):
                inspect_exit = main(
                    ["inspect", build_id, "--repo-root", str(fixture.root)]
                )

        self.assertEqual(0, exit_code)
        self.assertEqual(1, len(runner.commands))
        self.assertEqual(0, inspect_exit)
        self.assertIn("Override: force", inspect_output.getvalue())


class StudioFixture:
    def __enter__(self) -> "StudioFixture":
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "catalog").mkdir()
        self.write_scene("scene.py", "class DemoScene:\n    pass\n")
        self.write_scene(
            "slide.py",
            "class DemoSlide:\n"
            "    def construct(self):\n"
            "        self.beat(\"result\", label=\"Show result\")\n",
        )
        self.write_catalog(
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
                scene_id: slides
                source_path: slide.py
                class_name: DemoSlide
                base_scene_type: Slide
                renderer: manim-slides
                language: en
            """
        )
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.tempdir.cleanup()

    def write_scene(self, relative_path: str, content: str) -> None:
        path = self.root / relative_path
        path.write_text(content, encoding="utf-8")

    def write_catalog(self, content: str) -> None:
        (self.root / "catalog" / "scenes.yaml").write_text(
            textwrap.dedent(content).strip() + "\n",
            encoding="utf-8",
        )

    def add_unrelated_broken_scene(self) -> None:
        self.write_scene(
            "broken.py",
            "import module_that_should_not_exist\n\nclass BrokenScene:\n    pass\n",
        )
        self.write_catalog(
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
                scene_id: slides
                source_path: slide.py
                class_name: DemoSlide
                base_scene_type: Slide
                renderer: manim-slides
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

    def add_selected_broken_scene(self) -> None:
        self.write_scene(
            "broken.py",
            "import module_that_should_not_exist\n\nclass BrokenScene:\n    pass\n",
        )
        self.write_catalog(
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
                scene_id: slides
                source_path: slide.py
                class_name: DemoSlide
                base_scene_type: Slide
                renderer: manim-slides
                language: en
              - deck_id: demo
                scene_id: broken
                source_path: broken.py
                class_name: BrokenScene
                base_scene_type: Scene
                renderer: manim
                language: en
            """
        )


class FakeRunner:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
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


def find_profile_choices(parser, command: str) -> tuple[str, ...]:
    command_parser = find_subparser(parser, command)
    for action in command_parser._actions:
        if "--profile" in action.option_strings:
            return tuple(action.choices)
    raise AssertionError(f"{command} parser has no --profile option")


def find_subparser(parser, command: str):
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if choices and command in choices:
            return choices[command]
    raise AssertionError(f"parser has no {command!r} subcommand")


if __name__ == "__main__":
    unittest.main()
