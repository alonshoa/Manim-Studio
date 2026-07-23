from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from manim_mcp import services


class ManimMcpServiceTests(unittest.TestCase):
    def test_list_decks_and_scene_context(self) -> None:
        with McpFixture() as fixture:
            response = services.list_decks(fixture.context())
            context = services.get_scene_context("demo/slides", fixture.context())

        self.assertTrue(response["ok"], response)
        self.assertEqual("demo", response["data"]["decks"][0]["deck_id"])
        self.assertTrue(context["ok"], context)
        self.assertEqual("demo/slides", context["data"]["target"])
        self.assertIn("class DemoSlide", context["data"]["source"]["text"])
        self.assertEqual("result", context["data"]["beats"][0]["id"])

    def test_validate_scene_reports_valid_and_invalid_targets(self) -> None:
        with McpFixture() as fixture:
            valid = services.validate_scene("demo/intro", context=fixture.context())
            invalid = services.validate_scene("../demo/intro", context=fixture.context())
            missing = services.validate_scene("demo/missing", context=fixture.context())

        self.assertTrue(valid["ok"], valid)
        self.assertEqual("invalid_target", invalid["error"]["code"])
        self.assertEqual("target_not_found", missing["error"]["code"])

    def test_render_scene_records_manifest_artifacts_and_log(self) -> None:
        with McpFixture() as fixture:
            runner = FakeRunner(returncode=0, stdout="rendered\n")
            context = fixture.context(runner=runner)

            response = services.render_scene("demo/intro", context=context)
            build_id = response["data"]["build_id"]
            artifacts = services.get_artifacts(build_id, context)
            stdout = services.get_build_log(build_id, "stdout", context)

        self.assertTrue(response["ok"], response)
        self.assertEqual("success", response["data"]["manifest"]["status"])
        self.assertEqual(
            [{"kind": "video", "path": "media/video.mp4"}],
            artifacts["data"]["artifacts"],
        )
        self.assertEqual("rendered\n", stdout["data"]["text"])

    def test_failed_preflight_returns_validation_failed(self) -> None:
        with McpFixture() as fixture:
            fixture.write_scene(
                "broken.py",
                "import module_that_should_not_exist\n\nclass BrokenScene:\n    pass\n",
            )
            fixture.write_catalog(
                """
                version: 1
                scenes:
                  - deck_id: demo
                    scene_id: broken
                    source_path: broken.py
                    class_name: BrokenScene
                    base_scene_type: Scene
                    renderer: manim
                    language: en
                """
            )
            response = services.render_scene(
                "demo/broken",
                context=fixture.context(runner=FakeRunner(returncode=0)),
            )

        self.assertFalse(response["ok"])
        self.assertEqual("validation_failed", response["error"]["code"])
        self.assertEqual(
            "validation_failed",
            response["data"]["manifest"]["failure_class"],
        )

    def test_render_beat_handles_success_and_unknown_beat(self) -> None:
        with McpFixture() as fixture:
            runner = FakeRunner(returncode=0)
            context = fixture.context(runner=runner)

            response = services.render_beat("demo/slides", "result", context=context)
            missing = services.render_beat("demo/slides", "missing", context=context)

        self.assertTrue(response["ok"], response)
        self.assertIn("--save_sections", runner.commands[0])
        self.assertEqual("result", runner.envs[0]["MANIM_STUDIO_BEAT"])
        self.assertEqual("beat_not_found", missing["error"]["code"])

    def test_build_deck_and_export_pptx(self) -> None:
        with McpFixture() as fixture:
            context = fixture.context(runner=FakeRunner(returncode=0))

            build = services.build_deck("demo", context=context)
            export = services.export_deck("slides_only", "pptx", profile="draft", context=context)

        self.assertTrue(build["ok"], build)
        self.assertEqual("deck", build["data"]["manifest"]["kind"])
        self.assertTrue(export["ok"], export)
        self.assertEqual("export", export["data"]["manifest"]["kind"])
        self.assertIn(
            {"kind": "presentation", "path": "export/slides-only.pptx"},
            export["data"]["artifacts"],
        )

    def test_export_deck_reports_invalid_requests(self) -> None:
        with McpFixture() as fixture:
            context = fixture.context(runner=FakeRunner(returncode=0))

            missing = services.export_deck("missing", "pptx", profile="draft", context=context)
            unsupported = services.export_deck("slides_only", "html", profile="draft", context=context)
            mixed = services.export_deck("demo", "pptx", profile="draft", context=context)

        self.assertEqual("target_not_found", missing["error"]["code"])
        self.assertEqual("unsupported", unsupported["error"]["code"])
        self.assertEqual("unsupported_deck", mixed["error"]["code"])

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp SDK is not installed")
    def test_server_can_be_constructed_when_sdk_is_available(self) -> None:
        with McpFixture() as fixture:
            from manim_mcp.server import create_server

            server = create_server(fixture.context())

        self.assertIsNotNone(server)

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "mcp SDK is not installed")
    def test_stdio_server_lists_export_tool_when_sdk_is_available(self) -> None:
        async def run() -> None:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            with McpFixture() as fixture:
                env = os.environ.copy()
                source_root = Path(__file__).resolve().parents[1] / "src"
                pythonpath = env.get("PYTHONPATH", "")
                env["PYTHONPATH"] = (
                    str(source_root)
                    if not pythonpath
                    else os.pathsep.join([str(source_root), pythonpath])
                )
                env["MANIM_STUDIO_REPO_ROOT"] = str(fixture.root)
                server = StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "manim_mcp.server"],
                    env=env,
                )
                async with stdio_client(server) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = await session.list_tools()

            tool_names = {tool.name for tool in tools.tools}
            self.assertIn("export_deck", tool_names)

        asyncio.run(run())


class McpFixture:
    def __enter__(self) -> "McpFixture":
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "catalog").mkdir()
        (self.root / "docs").mkdir()
        (self.root / "docs" / "conventions.md").write_text(
            "# Conventions\n",
            encoding="utf-8",
        )
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
              - deck_id: slides_only
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

    def context(self, runner=None) -> services.StudioContext:
        return services.StudioContext(
            self.root,
            runner=runner or FakeRunner(returncode=0),
            check_executables=False,
        )

    def write_scene(self, relative_path: str, content: str) -> None:
        (self.root / relative_path).write_text(content, encoding="utf-8")

    def write_catalog(self, content: str) -> None:
        (self.root / "catalog" / "scenes.yaml").write_text(
            textwrap.dedent(content).strip() + "\n",
            encoding="utf-8",
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
        if list(command)[:2] == ["manim-slides", "convert"]:
            dest = Path(command[-1])
            dest.parent.mkdir(parents=True, exist_ok=True)
            if self.returncode == 0:
                dest.write_bytes(b"fake pptx")
            return subprocess.CompletedProcess(
                args=command,
                returncode=self.returncode,
                stdout=self.stdout,
                stderr=self.stderr,
            )
        media_dir = Path(command[command.index("--media_dir") + 1])
        media_dir.mkdir(parents=True, exist_ok=True)
        if self.returncode == 0:
            (media_dir / "video.mp4").write_bytes(b"fake mp4")
            if list(command)[:2] == ["manim-slides", "render"]:
                root = Path(kwargs["cwd"])
                class_name = command[-1]
                slides_dir = root / "slides"
                files_dir = slides_dir / "files" / class_name
                files_dir.mkdir(parents=True, exist_ok=True)
                (slides_dir / f"{class_name}.json").write_text(
                    '{"slides": []}\n',
                    encoding="utf-8",
                )
                (files_dir / "video.mp4").write_bytes(b"fake mp4")
        return subprocess.CompletedProcess(
            args=command,
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )


if __name__ == "__main__":
    unittest.main()
