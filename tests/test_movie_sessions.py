from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

from manim_mcp import services
from manim_studio.cli import main
from manim_studio.movie_sessions import start_movie_session


class MovieSessionTests(unittest.TestCase):
    def test_start_movie_session_creates_empty_registered_scene_and_ledger(self) -> None:
        with MovieFixture() as fixture:
            session = start_movie_session(
                fixture.root,
                "catalog/scenes.yaml",
                title="My Movie",
                deck_id="story",
                scene_id="scratch",
                class_name="ScratchScene",
            )
            catalog_text = (fixture.root / "catalog" / "scenes.yaml").read_text(
                encoding="utf-8"
            )
            source_text = (fixture.root / session["source_path"]).read_text(
                encoding="utf-8"
            )
            steps_exists = (fixture.root / session["steps_path"]).exists()

        self.assertEqual("story/scratch", session["target"])
        self.assertEqual(
            "studio live story/scratch --beat empty --diagnose",
            session["live"]["command"],
        )
        self.assertTrue(steps_exists)
        self.assertIn("deck_id: story", catalog_text)
        self.assertIn("class ScratchScene(BeatMixin, Scene):", source_text)
        self.assertIn('self.beat("empty"', source_text)

    def test_propose_validate_render_and_accept_movie_step_records_history(self) -> None:
        with MovieFixture() as fixture, fake_manim_module():
            context = fixture.context()
            started = services.start_movie_session(
                title="My Movie",
                deck_id="story",
                scene_id="scratch",
                class_name="ScratchScene",
                context=context,
            )
            session_id = started["data"]["session_id"]
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
                "add first dot",
                context,
            )
            proposal_id = proposed["data"]["proposal_id"]

            validation = services.validate_scene_patch(proposal_id, context=context)
            render = services.render_scene_patch(proposal_id, context=context)
            accepted = services.accept_movie_step(
                session_id,
                proposal_id,
                note="first accepted visual",
                context=context,
            )
            inspected = services.get_movie_session(session_id, context)
            source_text = (fixture.root / "decks" / "story" / "scratch.py").read_text(
                encoding="utf-8"
            )

        self.assertTrue(validation["ok"], validation)
        self.assertTrue(render["ok"], render)
        self.assertTrue(accepted["ok"], accepted)
        self.assertEqual("accepted", accepted["data"]["status"])
        self.assertEqual(1, accepted["data"]["revision"])
        self.assertEqual("step_001", accepted["data"]["beat"])
        self.assertEqual(1, len(inspected["data"]["accepted_steps"]))
        self.assertEqual("first accepted visual", inspected["data"]["accepted_steps"][0]["note"])
        self.assertIn("dot = Dot()", source_text)

    def test_accept_requires_explicit_accept_confirmation(self) -> None:
        with MovieFixture() as fixture:
            context = fixture.context()
            started = services.start_movie_session(
                title="My Movie",
                deck_id="story",
                scene_id="scratch",
                context=context,
            )
            response = services.accept_movie_step(
                started["data"]["session_id"],
                "missing-proposal",
                confirm="no",
                context=context,
            )

        self.assertFalse(response["ok"])
        self.assertEqual("approval_required", response["error"]["code"])

    def test_session_cli_start_and_inspect(self) -> None:
        with MovieFixture() as fixture:
            start_output = io.StringIO()
            with contextlib.redirect_stdout(start_output):
                start_exit = main(
                    [
                        "session",
                        "start",
                        "--title",
                        "CLI Movie",
                        "--deck-id",
                        "story",
                        "--scene-id",
                        "scratch",
                        "--repo-root",
                        str(fixture.root),
                    ]
                )
            session_id = start_output.getvalue().splitlines()[0].split(": ", 1)[1]

            inspect_output = io.StringIO()
            with contextlib.redirect_stdout(inspect_output):
                inspect_exit = main(
                    ["session", "inspect", session_id, "--repo-root", str(fixture.root)]
                )

        self.assertEqual(0, start_exit)
        self.assertEqual(0, inspect_exit)
        self.assertIn("Target: story/scratch", inspect_output.getvalue())
        self.assertIn("Accepted steps: none", inspect_output.getvalue())


class MovieFixture:
    def __enter__(self) -> "MovieFixture":
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "catalog").mkdir()
        (self.root / "catalog" / "scenes.yaml").write_text(
            "version: 1\nscenes: []\n",
            encoding="utf-8",
        )
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.tempdir.cleanup()

    def context(self) -> services.StudioContext:
        return services.StudioContext(
            self.root,
            runner=FakeRunner(returncode=0),
            check_executables=False,
        )


class FakeRunner:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode

    def __call__(self, command, **kwargs):
        media_dir = Path(command[command.index("--media_dir") + 1])
        media_dir.mkdir(parents=True, exist_ok=True)
        if self.returncode == 0:
            (media_dir / "video.mp4").write_bytes(b"fake mp4")
        return subprocess.CompletedProcess(
            args=command,
            returncode=self.returncode,
            stdout="rendered\n",
            stderr="",
        )


@contextlib.contextmanager
def fake_manim_module():
    module = types.ModuleType("manim")
    module.Scene = type("Scene", (), {"wait": lambda self, *_args, **_kwargs: None})
    module.Dot = type("Dot", (), {})
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
