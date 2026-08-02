from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from manim_studio.project_builder import create_project, default_options
from manim_studio.project_verifier import verify_project


class ProjectVerifierTests(unittest.TestCase):
    def test_verification_runs_stages_in_order_without_render_by_default(self) -> None:
        with generated_project() as root:
            runner = FakeDockerRunner()

            result = verify_project(root, runner=runner, which=fake_which)

        self.assertTrue(result.success, result.message)
        self.assertEqual(
            [
                "Docker CLI",
                "Docker responsive",
                "Runtime image",
                "Studio doctor",
                "Studio list",
                "Starter target validation",
            ],
            [stage.name for stage in result.completed_stages],
        )
        self.assertNotIn(
            ["docker", "compose", "run", "--rm", "studio", "studio", "render"],
            [command[:7] for command in runner.commands],
        )

    def test_verification_stops_at_first_failed_stage(self) -> None:
        with generated_project() as root:
            runner = FakeDockerRunner(fail_at="Studio list")

            result = verify_project(root, runner=runner, which=fake_which)

        self.assertFalse(result.success)
        self.assertEqual("Studio list", result.failed_stage.name)
        self.assertEqual(
            [
                ["docker", "info"],
                ["docker", "image", "inspect", "manim-studio:local"],
                ["docker", "compose", "run", "--rm", "studio", "studio", "doctor", "--catalog"],
                ["docker", "compose", "run", "--rm", "studio", "studio", "list"],
            ],
            runner.commands,
        )

    def test_missing_docker_returns_actionable_failure(self) -> None:
        with generated_project() as root:
            result = verify_project(root, runner=FakeDockerRunner(), which=lambda name: None)

        self.assertFalse(result.success)
        self.assertEqual("Docker CLI", result.failed_stage.name)
        self.assertIn("PATH", result.message)

    def test_missing_runtime_image_returns_actionable_failure(self) -> None:
        with generated_project() as root:
            runner = FakeDockerRunner(fail_at="Runtime image")

            result = verify_project(root, runner=runner, which=fake_which)

        self.assertFalse(result.success)
        self.assertEqual("Runtime image", result.failed_stage.name)
        self.assertIn("manim-studio:local", result.message)
        self.assertIn("Build or install", result.message)

    def test_render_is_opt_in_and_requires_host_visible_artifact(self) -> None:
        with generated_project() as root:
            runner = FakeDockerRunner(create_render_artifact=True)

            result = verify_project(root, render=True, runner=runner, which=fake_which)

        self.assertTrue(result.success, result.message)
        self.assertIsNotNone(result.artifact)
        self.assertEqual("Render artifact", result.completed_stages[-1].name)
        self.assertIn(
            ["docker", "compose", "run", "--rm", "studio", "studio", "render"],
            [command[:7] for command in runner.commands],
        )


class generated_project:
    def __enter__(self) -> Path:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        create_project(default_options(self.root, "Demo Project"))
        return self.root

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.tempdir.cleanup()


class FakeDockerRunner:
    def __init__(
        self,
        fail_at: str | None = None,
        create_render_artifact: bool = False,
    ) -> None:
        self.fail_at = fail_at
        self.create_render_artifact = create_render_artifact
        self.commands: list[list[str]] = []

    def __call__(self, command, **kwargs):
        command = list(command)
        self.commands.append(command)
        stage = stage_for_command(command)
        returncode = 1 if stage == self.fail_at else 0
        if returncode == 0 and self.create_render_artifact and stage == "Draft render":
            root = Path(kwargs["cwd"])
            artifact = root / "builds" / "fake-build" / "media" / "video.mp4"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"fake mp4")
        return subprocess.CompletedProcess(
            args=command,
            returncode=returncode,
            stdout=f"{stage} ok\n" if returncode == 0 else "",
            stderr=f"{stage} failed\n" if returncode != 0 else "",
        )


def stage_for_command(command: list[str]) -> str:
    if command == ["docker", "info"]:
        return "Docker responsive"
    if command[:3] == ["docker", "image", "inspect"]:
        return "Runtime image"
    if command[-2:] == ["doctor", "--catalog"]:
        return "Studio doctor"
    if command[-2:] == ["studio", "list"]:
        return "Studio list"
    if command[-3:-1] == ["studio", "validate"]:
        return "Starter target validation"
    if "render" in command and command[-2:] == ["--profile", "draft"]:
        return "Draft render"
    return "unknown"


def fake_which(name: str) -> str | None:
    if name == "docker":
        return "C:/Program Files/Docker/docker.exe"
    return None


if __name__ == "__main__":
    unittest.main()
