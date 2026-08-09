from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

from manim_mcp import services
from manim_studio.authoring_sessions import AuthoringSessionController
from manim_studio.cli import main


class AuthoringSessionTests(unittest.TestCase):
    def test_hebrew_title_creates_ascii_session_id_and_reloads(self) -> None:
        with AuthoringFixture() as fixture:
            controller = fixture.controller()
            started = controller.start_session(
                title="סרטון בדיקה",
                deck_id="hebrew",
                class_name="HebrewScene",
            )
            status = fixture.controller().get_status(started["session_id"])

        self.assertEqual("he", status["language"])
        self.assertTrue(status["session_id"].isascii())
        self.assertEqual("empty", status["beat"])

    def test_preview_reject_and_accept_use_candidate_then_canonical_source(self) -> None:
        with AuthoringFixture() as fixture, fake_manim_module():
            controller = fixture.controller()
            started = controller.start_session(
                title="Story",
                deck_id="story",
                scene_id="scratch",
                class_name="ScratchScene",
            )
            session_id = started["session_id"]
            context = fixture.context()
            proposed = services.propose_movie_step(
                session_id,
                [
                    {
                        "op": "insert_after",
                        "line": 8,
                        "expected": '        self.beat("empty", label="Empty slate")\n',
                        "text": "        dot = Dot(color=RED)\n        self.add(dot)\n",
                    }
                ],
                "add red dot",
                context,
            )
            proposal_id = proposed["data"]["proposal_id"]
            canonical_before = fixture.source_text("decks/story/scratch.py")

            preview = controller.preview_proposal(session_id, proposal_id)
            candidate_text = Path(preview["source_root"], preview["source_path"]).read_text(
                encoding="utf-8"
            )
            canonical_after_preview = fixture.source_text("decks/story/scratch.py")
            rejected = controller.reject_proposal(session_id, proposal_id)

            second = services.propose_movie_step(
                session_id,
                [
                    {
                        "op": "insert_after",
                        "line": 8,
                        "expected": '        self.beat("empty", label="Empty slate")\n',
                        "text": (
                            "        dot = Dot(color=RED)\n"
                            "        label = Text(\"point\")\n"
                            "        self.add(dot, label)\n"
                        ),
                    }
                ],
                "add dot and label",
                context,
            )
            accepted = controller.accept_proposal(session_id, second["data"]["proposal_id"])
            canonical_final = fixture.source_text("decks/story/scratch.py")

        self.assertEqual(canonical_before, canonical_after_preview)
        self.assertIn("dot = Dot(color=RED)", candidate_text)
        self.assertIn('self.beat("step_001"', candidate_text)
        self.assertEqual("empty", rejected["beat"])
        self.assertEqual("accepted", accepted["status"])
        self.assertEqual("step_001", accepted["beat"])
        self.assertIn('self.beat("step_001"', canonical_final)
        self.assertIn('label = Text("point")', canonical_final)

    def test_live_start_and_preview_restart_select_expected_source_roots(self) -> None:
        with AuthoringFixture() as fixture:
            fake_live = FakeLiveStarter()
            controller = fixture.controller(live_starter=fake_live)
            started = controller.start_session(
                title="Story",
                deck_id="story",
                scene_id="scratch",
                class_name="ScratchScene",
            )
            session_id = started["session_id"]
            live = controller.start_live(session_id)
            proposed = services.propose_movie_step(
                session_id,
                [
                    {
                        "op": "insert_after",
                        "line": 8,
                        "expected": '        self.beat("empty", label="Empty slate")\n',
                        "text": "        dot = Dot()\n        self.add(dot)\n",
                    }
                ],
                context=fixture.context(),
            )
            preview = controller.preview_proposal(session_id, proposed["data"]["proposal_id"])

        self.assertEqual("running", live["live_status"])
        self.assertEqual(2, len(fake_live.calls))
        self.assertEqual(fixture.root, fake_live.calls[0]["cwd"])
        self.assertNotEqual(fixture.root, fake_live.calls[1]["cwd"])
        self.assertEqual("step_001", preview["beat"])

    def test_authoring_cli_start_and_status_json(self) -> None:
        with AuthoringFixture() as fixture:
            start_output = io.StringIO()
            with contextlib.redirect_stdout(start_output):
                start_exit = main(
                    [
                        "authoring",
                        "start",
                        "--title",
                        "סרטון",
                        "--deck-id",
                        "story",
                        "--scene-id",
                        "scratch",
                        "--class-name",
                        "ScratchScene",
                        "--repo-root",
                        str(fixture.root),
                        "--json",
                    ]
                )
            session_id = json.loads(start_output.getvalue())["session_id"]
            status_output = io.StringIO()
            with contextlib.redirect_stdout(status_output):
                status_exit = main(
                    [
                        "authoring",
                        "status",
                        session_id,
                        "--repo-root",
                        str(fixture.root),
                        "--json",
                    ]
                )
            status = json.loads(status_output.getvalue())

        self.assertEqual(0, start_exit)
        self.assertEqual(0, status_exit)
        self.assertEqual("he", status["language"])
        self.assertEqual("empty", status["beat"])


class AuthoringFixture:
    def __enter__(self) -> "AuthoringFixture":
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "catalog").mkdir()
        (self.root / "docs").mkdir()
        (self.root / "docs" / "conventions.md").write_text("# Conventions\n", encoding="utf-8")
        (self.root / "catalog" / "scenes.yaml").write_text(
            "version: 1\nscenes: []\n",
            encoding="utf-8",
        )
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.tempdir.cleanup()

    def controller(self, live_starter=None) -> AuthoringSessionController:
        return AuthoringSessionController(
            self.root,
            live_starter=live_starter or FakeLiveStarter(),
            render_runner=FakeRenderRunner(returncode=0),
            check_executables=False,
        )

    def context(self) -> services.StudioContext:
        return services.StudioContext(
            self.root,
            runner=FakeRenderRunner(returncode=0),
            check_executables=False,
        )

    def source_text(self, relative_path: str) -> str:
        return (self.root / relative_path).read_text(encoding="utf-8")


class FakeLiveStarter:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, command, **kwargs):
        self.calls.append({"command": list(command), "cwd": Path(kwargs["cwd"])})
        return types.SimpleNamespace(pid=None)


class FakeRenderRunner:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def __call__(self, command, **kwargs):
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


@contextlib.contextmanager
def fake_manim_module():
    module = types.ModuleType("manim")
    module.RED = "RED"
    module.Scene = type(
        "Scene",
        (),
        {
            "add": lambda self, *_args, **_kwargs: None,
            "wait": lambda self, *_args, **_kwargs: None,
        },
    )
    module.Dot = type("Dot", (), {"__init__": lambda self, *args, **kwargs: None})
    module.Text = type("Text", (), {"__init__": lambda self, *args, **kwargs: None})
    original = sys.modules.get("manim")
    sys.modules["manim"] = module
    try:
        yield
    finally:
        if original is None:
            sys.modules.pop("manim", None)
        else:
            sys.modules["manim"] = original


if __name__ == "__main__":
    unittest.main()
