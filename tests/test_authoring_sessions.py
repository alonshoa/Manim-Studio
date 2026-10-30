from __future__ import annotations

import contextlib
import io
import json
import os
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
        self.assertEqual("READY", status["authoring_status"])
        self.assertEqual("NONE", status["proposal_status"])
        self.assertEqual("WAIT_FOR_PROPOSAL", status["next_action"])

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
            discovered_after_reject = controller.discover_active_proposal(session_id)

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
        self.assertIsNone(discovered_after_reject["active_proposal_id"])
        self.assertEqual("NONE", discovered_after_reject["proposal_status"])
        self.assertEqual("WAIT_FOR_PROPOSAL", discovered_after_reject["next_action"])
        self.assertEqual("accepted", accepted["status"])
        self.assertEqual("READY", accepted["authoring_status"])
        self.assertEqual("NONE", accepted["proposal_status"])
        self.assertEqual("WAIT_FOR_PROPOSAL", accepted["next_action"])
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

        self.assertEqual("RUNNING", live["live_status"])
        self.assertEqual(2, len(fake_live.calls))
        self.assertEqual(fixture.root, fake_live.calls[0]["cwd"])
        self.assertNotEqual(fixture.root, fake_live.calls[1]["cwd"])
        self.assertEqual("step_001", preview["beat"])

    def test_render_authoring_preview_renders_canonical_source(self) -> None:
        with AuthoringFixture() as fixture, fake_manim_module():
            controller = fixture.controller()
            started = controller.start_session(
                title="Story",
                deck_id="story",
                scene_id="scratch",
                class_name="ScratchScene",
            )
            before = fixture.source_text("decks/story/scratch.py")
            render = controller.dispatch("render_authoring_preview", {"session_id": started["session_id"]})
            artifact_exists = Path(str(render["artifact_path"])).is_file()
            after = fixture.source_text("decks/story/scratch.py")

        self.assertEqual("canonical", render["source_kind"])
        self.assertEqual("success", render["render_status"])
        self.assertEqual("empty", render["beat"])
        self.assertEqual(0, render["revision"])
        self.assertIsNone(render["proposal_id"])
        self.assertIsNotNone(render["build_id"])
        self.assertTrue(artifact_exists)
        self.assertEqual(before, after)

    def test_render_authoring_preview_renders_previewed_candidate(self) -> None:
        with AuthoringFixture() as fixture, fake_manim_module():
            controller = fixture.controller()
            started = controller.start_session(
                title="Story",
                deck_id="story",
                scene_id="scratch",
                class_name="ScratchScene",
            )
            proposed = controller.propose_next_movie_step(
                started["session_id"],
                "dot = Dot(color=RED)\nself.add(dot)",
                title="Add dot",
            )
            before = fixture.source_text("decks/story/scratch.py")
            controller.preview_proposal(started["session_id"], proposed["active_proposal_id"])
            render = controller.render_authoring_preview(started["session_id"])
            artifact_exists = Path(str(render["artifact_path"])).is_file()
            after = fixture.source_text("decks/story/scratch.py")

        self.assertEqual("candidate", render["source_kind"])
        self.assertEqual(proposed["active_proposal_id"], render["proposal_id"])
        self.assertEqual("success", render["render_status"])
        self.assertEqual("step_001", render["beat"])
        self.assertEqual(0, render["revision"])
        self.assertIn("_preview", str(render["artifact_path"]))
        self.assertTrue(artifact_exists)
        self.assertEqual(before, after)

    def test_render_authoring_preview_failure_returns_structured_error(self) -> None:
        with AuthoringFixture() as fixture, fake_manim_module():
            controller = fixture.controller(render_runner=FakeRenderRunner(returncode=1, stderr="boom"))
            started = controller.start_session(
                title="Story",
                deck_id="story",
                scene_id="scratch",
                class_name="ScratchScene",
            )
            render = controller.render_authoring_preview(started["session_id"])
            status = controller.get_status(started["session_id"])

        self.assertEqual("failed", render["render_status"])
        self.assertIsNone(render["artifact_path"])
        self.assertEqual("render_failed", render["render_error"]["code"])
        self.assertIn("boom", render["render_error"]["detail"]["log_excerpt"])
        self.assertEqual("READY", status["authoring_status"])
        self.assertEqual("NONE", status["proposal_status"])

    def test_default_live_launch_does_not_create_new_windows_console(self) -> None:
        with AuthoringFixture() as fixture:
            controller = AuthoringSessionController(fixture.root, check_executables=False)
            started = controller.start_session(
                title="Story",
                deck_id="story",
                scene_id="scratch",
                class_name="ScratchScene",
            )
            state = controller._load_state(started["session_id"])
            plan = types.SimpleNamespace(cwd=fixture.root, env={})
            kwargs = controller._live_process_kwargs(state, plan)
            try:
                if os.name == "nt":
                    self.assertEqual(subprocess.CREATE_NO_WINDOW, kwargs.get("creationflags"))
                    self.assertNotEqual(subprocess.CREATE_NEW_CONSOLE, kwargs.get("creationflags"))
                self.assertEqual(subprocess.DEVNULL, kwargs["stdin"])
                self.assertIn("live_stdout.log", str(kwargs["stdout"].name))
                self.assertIn("live_stderr.log", str(kwargs["stderr"].name))
            finally:
                kwargs["stdout"].close()
                kwargs["stderr"].close()

    def test_semantic_append_inserts_inside_construct_before_helper_methods(self) -> None:
        with AuthoringFixture() as fixture:
            controller = fixture.controller()
            started = controller.start_session(
                title="Story",
                deck_id="story",
                scene_id="scratch",
                class_name="ScratchScene",
            )
            source_path = fixture.root / "decks" / "story" / "scratch.py"
            source_path.write_text(
                "from manim import *\n\n"
                "from manim_kit.beats import BeatMixin\n\n\n"
                "class ScratchScene(BeatMixin, Scene):\n"
                "    def construct(self):\n"
                "        self.beat(\"empty\", label=\"Empty slate\")\n"
                "        self.wait(0.1)\n\n"
                "    def helper(self):\n"
                "        self.wait(9)\n",
                encoding="utf-8",
            )

            proposed = controller.propose_next_movie_step(
                started["session_id"],
                "title = Text(\"Vector Addition\")\nself.play(FadeIn(title))",
                title="Show title",
                rationale="append title",
            )
            preview = controller.preview_proposal(started["session_id"], proposed["active_proposal_id"])
            candidate_text = Path(preview["source_root"], preview["source_path"]).read_text(encoding="utf-8")

        self.assertIn('# <manim-studio-step id="step_001">', candidate_text)
        self.assertLess(candidate_text.index("Vector Addition"), candidate_text.index("def helper"))
        self.assertLess(candidate_text.index("Vector Addition"), candidate_text.index("self.wait(0.1)"))
        self.assertIn('self.beat("step_001", label="Show title")', candidate_text)

    def test_discover_revision_pause_resume_and_finish_flow(self) -> None:
        with AuthoringFixture() as fixture, fake_manim_module():
            controller = fixture.controller()
            started = controller.start_session(
                title="Story",
                deck_id="story",
                scene_id="scratch",
                class_name="ScratchScene",
            )
            session_id = started["session_id"]
            proposed = controller.propose_next_movie_step(
                session_id,
                "dot = Dot()\nself.add(dot)",
                title="Add dot",
            )
            discovered = controller.discover_active_proposal(session_id)
            preview = controller.preview_proposal(session_id)
            revised = controller.revise_proposal(session_id, "להגביה את הכותרת")
            replacement = controller.propose_next_movie_step(
                session_id,
                "dot = Dot()\nlabel = Text(\"point\")\nself.add(dot, label)",
                title="Add dot and label",
            )
            paused = controller.pause_session(session_id)
            resumed = controller.resume_session(session_id)
            accepted = controller.accept_proposal(session_id, replacement["active_proposal_id"])
            finished = controller.finish_session(session_id)

        self.assertEqual(proposed["active_proposal_id"], discovered["active_proposal_id"])
        self.assertEqual("PREVIEWED", preview["proposal_status"])
        self.assertEqual("NEEDS_REVISION", revised["proposal_status"])
        self.assertIn("להגביה", revised["revision_feedback"][0]["feedback"])
        self.assertEqual("PAUSED", paused["authoring_status"])
        self.assertEqual("RUNNING", resumed["live_status"])
        self.assertEqual("READY", accepted["authoring_status"])
        self.assertEqual("COMPLETED", finished["authoring_status"])
        self.assertIsNotNone(finished["finish_build_id"])

    def test_finish_render_failure_preserves_resumable_error_state(self) -> None:
        with AuthoringFixture() as fixture, fake_manim_module():
            controller = fixture.controller(render_runner=FakeRenderRunner(returncode=1, stderr="boom"))
            started = controller.start_session(
                title="Story",
                deck_id="story",
                scene_id="scratch",
                class_name="ScratchScene",
            )
            failed = controller.finish_session(started["session_id"])

        self.assertEqual("ERROR", failed["authoring_status"])
        self.assertEqual("RETRY", failed["next_action"])
        self.assertEqual("draft render failed", failed["last_error"])

    def test_rpc_error_preserves_request_id(self) -> None:
        with AuthoringFixture() as fixture:
            controller = fixture.controller()
            request = {"id": 7, "method": "missing_method", "params": {}}
            response_id = None
            try:
                controller.dispatch(request["method"], request["params"])
            except Exception as exc:  # noqa: BLE001 - mirrors rpc_loop error path without stdio plumbing.
                response_id = request["id"]
                payload = {"id": response_id, "ok": False, "error": {"message": str(exc)}}

        self.assertEqual(7, payload["id"])
        self.assertFalse(payload["ok"])

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
        self.assertEqual("READY", status["authoring_status"])


class AuthoringFixture:
    def __enter__(self) -> "AuthoringFixture":
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name).resolve()
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

    def controller(self, live_starter=None, render_runner=None) -> AuthoringSessionController:
        return AuthoringSessionController(
            self.root,
            live_starter=live_starter or FakeLiveStarter(),
            render_runner=render_runner or FakeRenderRunner(returncode=0),
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
