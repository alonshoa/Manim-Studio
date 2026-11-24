"""Seed only a new temporary demo project. Synthetic data; no model calls."""

import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from manim_studio.research import ResearchLog
from manim_studio.research_artifacts import ResearchArtifacts
from tests.test_authoring_sessions import AuthoringFixture, fake_manim_module

root = Path(sys.argv[1]).resolve()
if (root / ".manim-studio").exists():
    raise RuntimeError("Demo refuses an existing research project")
with (
    AuthoringFixture() as fixture,
    fake_manim_module(),
    patch("manim_studio.research_artifacts.kick_worker"),
):
    log = ResearchLog(fixture.root)
    log.configure(True)
    session = log.start_session("וקטורים — ניסיון 01")
    (fixture.root / "lesson-plan.md").write_text(
        "# וקטורים\nהסבר אינטואיטיבי על מרחק וכיוון.\n", encoding="utf8"
    )
    controller = fixture.controller()
    aid = controller.start_session(title="וקטורים", deck_id="vectors")["session_id"]
    controller.propose_next_movie_step(aid, "self.add(Dot())", title="הצעה ראשונה")
    controller.dispatch(
        "reject_proposal",
        {
            "session_id": aid,
            "_research": {
                "session_id": session,
                "decision_origin": "human",
                "origin_evidence": "synthetic_fixture",
            },
        },
    )
    controller.propose_next_movie_step(aid, "self.wait(0.1)", title="הצעה מתוקנת")
    controller.dispatch(
        "accept_proposal",
        {
            "session_id": aid,
            "_research": {
                "session_id": session,
                "decision_origin": "human",
                "origin_evidence": "synthetic_fixture",
            },
        },
    )
    service = ResearchArtifacts(fixture.root)
    while service.work_once():
        pass
    # A real missing source observation, visible rather than fabricated retained content.
    with log.connection() as db:
        service.retain(
            db,
            session,
            "builds/old-render.mp4",
            "preview_video",
            reason="source_missing",
        )
    shutil.copytree(fixture.root, root, dirs_exist_ok=True)
print(json.dumps({"session_id": session}, ensure_ascii=False))
