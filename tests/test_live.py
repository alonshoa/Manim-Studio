from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
import unittest.mock
from pathlib import Path

from manim_studio.live import (
    LIVE_BEAT_ENV,
    TARGET_BEAT_ENV,
    diagnose_live_preview,
    plan_live_preview,
    run_live_preview,
)


class LivePreviewTests(unittest.TestCase):
    def test_plan_live_preview_builds_opengl_command_and_env(self) -> None:
        with LiveFixture() as fixture:
            plan = plan_live_preview(
                "demo/slides",
                "result",
                repo_root=fixture.root,
                session_id="test-session",
                base_env={"PYTHONPATH": "existing"},
            )

        self.assertEqual("demo/slides", plan.target)
        self.assertEqual("result", plan.beat_id)
        self.assertEqual(
            [
                sys.executable,
                "-m",
                "manim",
                "--renderer=opengl",
                "--force_window",
                "-ql",
                "--media_dir",
                str(fixture.root / ".manim-studio" / "live" / "test-session" / "media"),
                "slide.py",
                "DemoSlide",
            ],
            list(plan.command),
        )
        self.assertEqual("result", plan.env[TARGET_BEAT_ENV])
        self.assertEqual("result", plan.env[LIVE_BEAT_ENV])
        self.assertIn(str(fixture.root / "src"), plan.env["PYTHONPATH"])
        self.assertIn("existing", plan.env["PYTHONPATH"])

    def test_run_live_preview_invokes_attached_runner_without_build_manifest(self) -> None:
        with LiveFixture() as fixture:
            runner = FakeRunner()
            output = io.StringIO()
            with _display_env(), contextlib.redirect_stdout(output):
                exit_code = run_live_preview(
                    "demo/slides",
                    "result",
                    repo_root=fixture.root,
                    runner=runner,
                    executable_resolver=lambda name: f"C:/fake/{name}",
                    module_finder=module_finder(
                        "manim",
                        "manim_slides",
                        "manim.renderer.opengl_renderer",
                        "IPython",
                    ),
                    tty_checker=lambda: True,
                )

            manifest_paths = list(fixture.root.rglob("manifest.json"))

        self.assertEqual(0, exit_code)
        self.assertEqual(1, len(runner.commands))
        self.assertIn("--renderer=opengl", runner.commands[0])
        self.assertIn("--force_window", runner.commands[0])
        self.assertNotIn("capture_output", runner.kwargs[0])
        self.assertEqual("result", runner.kwargs[0]["env"][TARGET_BEAT_ENV])
        self.assertEqual("result", runner.kwargs[0]["env"][LIVE_BEAT_ENV])
        self.assertEqual([], manifest_paths)
        self.assertIn("Starting live preview: demo/slides", output.getvalue())

    def test_run_live_preview_reports_unknown_target_before_runner(self) -> None:
        with LiveFixture() as fixture:
            runner = FakeRunner()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = run_live_preview(
                    "demo/missing",
                    "result",
                    repo_root=fixture.root,
                    runner=runner,
                )

        self.assertEqual(1, exit_code)
        self.assertEqual([], runner.commands)
        self.assertIn("target_not_found", output.getvalue())

    def test_run_live_preview_reports_unknown_beat_before_runner(self) -> None:
        with LiveFixture() as fixture:
            runner = FakeRunner()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = run_live_preview(
                    "demo/slides",
                    "missing",
                    repo_root=fixture.root,
                    runner=runner,
                )

        self.assertEqual(1, exit_code)
        self.assertEqual([], runner.commands)
        self.assertIn("beat_not_found", output.getvalue())
        self.assertIn("Available beats: intro, result", output.getvalue())

    def test_run_live_preview_blocks_duplicate_beat_ids_before_runner(self) -> None:
        with LiveFixture() as fixture:
            fixture.write_scene(
                "slide.py",
                "class DemoSlide:\n"
                "    def construct(self):\n"
                "        self.beat(\"result\")\n"
                "        self.beat(\"result\", label=\"Duplicate\")\n",
            )
            runner = FakeRunner()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = run_live_preview(
                    "demo/slides",
                    "result",
                    repo_root=fixture.root,
                    runner=runner,
                )

        self.assertEqual(1, exit_code)
        self.assertEqual([], runner.commands)
        self.assertIn("duplicate beat id 'result'", output.getvalue())

    def test_diagnostics_report_missing_manim(self) -> None:
        with LiveFixture() as fixture:
            plan = plan_live_preview("demo/slides", "result", repo_root=fixture.root)
            with _display_env():
                diagnostics = diagnose_live_preview(
                    plan,
                    executable_resolver=lambda name: None,
                    module_finder=module_finder("manim_slides", "IPython"),
                    tty_checker=lambda: True,
                )

        failures = [item for item in diagnostics if not item.ok]
        self.assertTrue(any(item.code == "live_environment_failed" for item in failures))
        self.assertTrue(any(item.name == "Manim CLI" for item in failures))
        self.assertTrue(any(item.name == "Python import: manim" for item in failures))

    def test_diagnostics_report_missing_tty(self) -> None:
        with LiveFixture() as fixture:
            plan = plan_live_preview("demo/slides", "result", repo_root=fixture.root)
            with _display_env():
                diagnostics = diagnose_live_preview(
                    plan,
                    executable_resolver=lambda name: f"C:/fake/{name}",
                    module_finder=module_finder(
                        "manim",
                        "manim_slides",
                        "manim.renderer.opengl_renderer",
                        "IPython",
                    ),
                    tty_checker=lambda: False,
                )

        self.assertTrue(
            any(item.code == "live_tty_missing" for item in diagnostics if not item.ok)
        )

    def test_ipython_diagnostic_is_warning_not_failure(self) -> None:
        with LiveFixture() as fixture:
            plan = plan_live_preview("demo/slides", "result", repo_root=fixture.root)
            with _display_env():
                diagnostics = diagnose_live_preview(
                    plan,
                    executable_resolver=lambda name: f"C:/fake/{name}",
                    module_finder=module_finder(
                        "manim",
                        "manim_slides",
                        "manim.renderer.opengl_renderer",
                    ),
                    tty_checker=lambda: True,
                )

        ipython = next(item for item in diagnostics if item.name == "IPython")
        self.assertTrue(ipython.ok)
        self.assertEqual("warning", ipython.severity)


class LiveFixture:
    def __enter__(self) -> "LiveFixture":
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "catalog").mkdir()
        self.write_scene("scene.py", "class DemoScene:\n    pass\n")
        self.write_scene(
            "slide.py",
            "class DemoSlide:\n"
            "    def construct(self):\n"
            "        self.beat(\"intro\")\n"
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
        (self.root / relative_path).write_text(content, encoding="utf-8")

    def write_catalog(self, content: str) -> None:
        (self.root / "catalog" / "scenes.yaml").write_text(
            textwrap.dedent(content).strip() + "\n",
            encoding="utf-8",
        )


class FakeRunner:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.commands: list[list[str]] = []
        self.kwargs: list[dict] = []

    def __call__(self, command, **kwargs):
        self.commands.append(list(command))
        self.kwargs.append(dict(kwargs))
        return subprocess.CompletedProcess(command, self.returncode)


def module_finder(*available: str):
    available_set = set(available)

    def find(name: str):
        return object() if name in available_set else None

    return find


@contextlib.contextmanager
def _display_env():
    with unittest.mock.patch.dict(
        os.environ,
        {
            "DISPLAY": ":1",
            "MANIM_STUDIO_ALLOW_CONTAINER_LIVE": "1",
        },
    ):
        yield


if __name__ == "__main__":
    unittest.main()
