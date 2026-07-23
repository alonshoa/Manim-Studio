from __future__ import annotations

import json
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from manim_mcp import services


class StagedEditServiceTests(unittest.TestCase):
    def test_proposal_is_staged_and_canonical_source_is_unchanged(self) -> None:
        with StagedFixture() as fixture:
            context = fixture.context()

            response = services.propose_scene_patch(
                "demo/intro",
                [
                    {
                        "op": "replace",
                        "start_line": 2,
                        "end_line": 2,
                        "expected": "    pass\n",
                        "text": "    def construct(self):\n        pass\n",
                    }
                ],
                "add construct method",
                context,
            )
            proposal_id = response["data"]["proposal_id"]
            metadata_path = fixture.root / "builds" / "staged" / proposal_id / "proposal.json"
            inspect_response = services.inspect_scene_patch(proposal_id, context)
            canonical_text = fixture.scene_text
            metadata_exists = metadata_path.exists()

        self.assertTrue(response["ok"], response)
        self.assertTrue(metadata_exists)
        self.assertEqual("class DemoScene:\n    pass\n", canonical_text)
        self.assertIn("-    pass", inspect_response["data"]["diff"])
        self.assertIn("+    def construct(self):", inspect_response["data"]["diff"])

    def test_invalid_target_and_patch_conflict_are_structured_failures(self) -> None:
        with StagedFixture() as fixture:
            context = fixture.context()
            invalid = services.propose_scene_patch(
                "../demo/intro",
                [{"op": "delete", "start_line": 1, "end_line": 1}],
                context=context,
            )
            conflict = services.propose_scene_patch(
                "demo/intro",
                [
                    {
                        "op": "replace",
                        "start_line": 2,
                        "end_line": 2,
                        "expected": "different\n",
                        "text": "    pass\n",
                    }
                ],
                context=context,
            )

        self.assertFalse(invalid["ok"])
        self.assertEqual("invalid_target", invalid["error"]["code"])
        self.assertFalse(conflict["ok"])
        self.assertEqual("patch_conflict", conflict["error"]["code"])

    def test_staged_validation_render_and_apply_success(self) -> None:
        with StagedFixture() as fixture:
            runner = FakeRunner(returncode=0, stdout="rendered\n")
            context = fixture.context(runner=runner)
            proposal_id = fixture.propose_construct(context)

            validation = services.validate_scene_patch(proposal_id, context=context)
            render = services.render_scene_patch(proposal_id, context)
            apply = services.apply_scene_patch(proposal_id, "apply", context)
            applied_text = fixture.scene_text

        self.assertTrue(validation["ok"], validation)
        self.assertEqual("success", validation["data"]["validation"]["status"])
        self.assertTrue(render["ok"], render)
        self.assertEqual("success", render["data"]["draft_render"]["status"])
        self.assertTrue(apply["ok"], apply)
        self.assertIn("def construct", applied_text)

    def test_apply_requires_confirm_validation_render_and_fresh_source(self) -> None:
        with StagedFixture() as fixture:
            context = fixture.context(runner=FakeRunner(returncode=0))
            proposal_id = fixture.propose_construct(context)

            missing_confirm = services.apply_scene_patch(proposal_id, "no", context)
            missing_validation = services.apply_scene_patch(proposal_id, "apply", context)
            services.validate_scene_patch(proposal_id, context=context)
            missing_render = services.apply_scene_patch(proposal_id, "apply", context)
            services.render_scene_patch(proposal_id, context)
            fixture.write_scene("class DemoScene:\n    changed = True\n")
            stale = services.apply_scene_patch(proposal_id, "apply", context)

        self.assertEqual("approval_required", missing_confirm["error"]["code"])
        self.assertEqual("validation_required", missing_validation["error"]["code"])
        self.assertEqual("render_required", missing_render["error"]["code"])
        self.assertEqual("stale_proposal", stale["error"]["code"])

    def test_render_debugging_proposes_minimal_name_error_patch(self) -> None:
        with StagedFixture() as fixture:
            fixture.write_scene(
                "class DemoScene:\n"
                "    def construct(self):\n"
                "        shape = Sqare()\n"
                "        self.add(shape)\n"
            )
            context = fixture.context(
                runner=FakeRunner(
                    returncode=1,
                    stderr="NameError: name 'Sqare' is not defined\n",
                )
            )
            failed_render = services.render_scene("demo/intro", context=context)
            build_id = failed_render["data"]["build_id"]

            debug = services.propose_render_debug_patch("demo/intro", build_id, context)
            canonical_text = fixture.scene_text

        self.assertFalse(failed_render["ok"])
        self.assertEqual("render_failed", failed_render["error"]["code"])
        self.assertTrue(debug["ok"], debug)
        self.assertIn("Sqare", debug["data"]["diff"])
        self.assertIn("Square", debug["data"]["diff"])
        self.assertEqual("class DemoScene:\n    def construct(self):\n        shape = Sqare()\n        self.add(shape)\n", canonical_text)

    def test_render_debugging_returns_unsupported_for_unknown_failures(self) -> None:
        with StagedFixture() as fixture:
            context = fixture.context(runner=FakeRunner(returncode=1, stderr="boom\n"))
            failed_render = services.render_scene("demo/intro", context=context)
            build_id = failed_render["data"]["build_id"]

            debug = services.propose_render_debug_patch("demo/intro", build_id, context)

        self.assertFalse(debug["ok"])
        self.assertEqual("unsupported", debug["error"]["code"])


class StagedFixture:
    def __enter__(self) -> "StagedFixture":
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "catalog").mkdir()
        (self.root / "docs").mkdir()
        (self.root / "docs" / "conventions.md").write_text("# Conventions\n", encoding="utf-8")
        self.write_scene("class DemoScene:\n    pass\n")
        (self.root / "catalog" / "scenes.yaml").write_text(
            textwrap.dedent(
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
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.tempdir.cleanup()

    @property
    def scene_text(self) -> str:
        return (self.root / "scene.py").read_text(encoding="utf-8")

    def write_scene(self, text: str) -> None:
        (self.root / "scene.py").write_text(text, encoding="utf-8")

    def context(self, runner=None) -> services.StudioContext:
        return services.StudioContext(
            self.root,
            runner=runner or FakeRunner(returncode=0),
            check_executables=False,
        )

    def propose_construct(self, context: services.StudioContext) -> str:
        response = services.propose_scene_patch(
            "demo/intro",
            [
                {
                    "op": "replace",
                    "start_line": 2,
                    "end_line": 2,
                    "expected": "    pass\n",
                    "text": "    def construct(self):\n        pass\n",
                }
            ],
            context=context,
        )
        if not response["ok"]:
            raise AssertionError(response)
        return response["data"]["proposal_id"]


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


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
