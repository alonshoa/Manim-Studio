import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from manim_studio.authoring_sessions import AuthoringSessionError
from manim_studio.research import ResearchLog
from manim_studio.research_artifacts import (
    CAPTURE,
    DEFAULT_POLICY,
    ResearchArtifacts,
    decision_lock,
    digest,
)
from manim_studio.research_files import read_project_file
from manim_studio.research_sessions import ResearchSessionError, ResearchSessions
from tests.test_authoring_sessions import (
    AuthoringFixture,
    FakeRenderRunner,
    fake_manim_module,
)


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.log = ResearchLog(self.root)
        self.log.configure(True)
        self.session = self.log.start_session("vectors")
        self.service = ResearchArtifacts(self.root)
        self.no_workers = patch("manim_studio.research_artifacts.kick_worker")
        self.no_workers.start()
        self.addCleanup(self.no_workers.stop)

    def read(self, action="list", **params):
        return self.service.dispatch(action, dict(session_id=self.session, **params))

    def write(self, action="checkpoint", **params):
        return self.service.dispatch(
            action,
            {"session_id": self.session, "request_id": str(uuid.uuid4()), **params},
        )

    def file(self, path, content="hello"):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf8")
        return p

    def test_snapshots_preserve_markdown_yaml_changes_and_deletions(self):
        self.file("lesson-plan.md", "ראשון")
        self.file("research-inputs/story.yaml", "x: 1")
        self.write(
            "configure",
            values=dict(DEFAULT_POLICY, paths=["research-inputs"]),
            expected_revision=0,
        )
        first = self.write()
        self.file("lesson-plan.md", "שני")
        (self.root / "research-inputs/story.yaml").unlink()
        second = self.write()
        self.assertEqual(second["missing"], ["research-inputs/story.yaml"])
        artifact = next(
            a
            for a in self.read()["artifacts"]
            if a["sha256"] == first["files"]["lesson-plan.md"]
        )
        self.assertEqual(
            self.read("content", artifact_id=artifact["artifact_id"])["text"], "ראשון"
        )
        self.assertNotEqual(
            first["files"]["lesson-plan.md"], second["files"]["lesson-plan.md"]
        )
        self.assertIn(
            "coverage.observed", [e["type"] for e in self.read("history")["events"]]
        )

    def test_policy_preview_exclusions_symlinks_and_read_limits(self):
        self.file("lesson-plan.md")
        self.file("research-inputs/.env", "SECRET")
        self.file(".venv/private.py", "SECRET")
        self.file("research-inputs/large.md", "a" * 100)
        self.write(
            "configure",
            values=dict(DEFAULT_POLICY, paths=["research-inputs"], file_bytes=10),
            expected_revision=0,
        )
        self.assertRaises(
            ValueError, read_project_file, self.root, "research-inputs/large.md", 10
        )
        try:
            (self.root / "research-inputs/link.md").symlink_to(
                self.root / "research-inputs/.env"
            )
        except OSError:
            pass
        state = self.write()
        self.assertNotIn("research-inputs/.env", state["files"])
        self.assertTrue(any(o["reason"] == "too_large" for o in state["omitted"]))
        for path in (
            "../private.md",
            ".venv/private.py",
            ".env",
            "/tmp/secret",
            "C:/private.md",
        ):
            with self.assertRaises(ValueError):
                self.write(
                    "configure",
                    values=dict(DEFAULT_POLICY, paths=[path]),
                    expected_revision=1,
                )

    def test_quota_never_silently_drops_or_truncates_content(self):
        self.file("lesson-plan.md", "a" * 20)
        self.write(
            "configure",
            values=dict(DEFAULT_POLICY, session_bytes=1),
            expected_revision=0,
        )
        result = self.write()
        self.assertEqual(result["files"], {})
        self.assertIn("omitted_quota", [o["reason"] for o in result["omitted"]])
        self.assertEqual(self.read()["artifacts"][0]["status"], "unavailable")

    def test_receipt_retry_is_stable_after_state_changes_and_key_order(self):
        self.file("lesson-plan.md")
        request = str(uuid.uuid4())
        payload = {"session_id": self.session, "request_id": request}
        first = self.service.dispatch("checkpoint", payload)
        self.file("lesson-plan.md", "changed")
        again = self.service.dispatch(
            "checkpoint", dict(reversed(list(payload.items())))
        )
        self.assertEqual(first, again)
        with self.assertRaisesRegex(ValueError, "request_id_conflict"):
            self.service.dispatch("checkpoint", dict(payload, reason="different"))

    def test_policy_cas_two_writers_one_conflict(self):
        def save(value):
            try:
                return self.write(
                    "configure",
                    expected_revision=0,
                    values=dict(DEFAULT_POLICY, session_bytes=value),
                )["revision"]
            except ResearchSessionError as e:
                return e.code

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(save, [10, 20]))
        self.assertCountEqual(results, [1, "policy_conflict"])

    def test_cross_project_session_and_capture_boundaries(self):
        self.file("lesson-plan.md")
        self.write()
        artifact = self.read()["artifacts"][0]
        other = self.log.start_session("other")
        with self.assertRaisesRegex(ValueError, "artifact_not_found"):
            self.service.dispatch(
                "content", {"session_id": other, "artifact_id": artifact["artifact_id"]}
            )
        with self.assertRaisesRegex(ValueError, "project_mismatch"):
            self.service.dispatch(
                "checkpoint",
                {
                    "session_id": self.session,
                    "request_id": "bad-project",
                    "project_id": "wrong",
                },
            )
        self.log.configure(False)
        self.assertEqual(
            self.read("content", artifact_id=artifact["artifact_id"])["text"], "hello"
        )
        with self.assertRaisesRegex(ValueError, "capture_disabled"):
            self.write()
        with self.assertRaisesRegex(ValueError, "capture_disabled"):
            self.write(
                "presented",
                artifact_id=artifact["artifact_id"],
                sha256=artifact["sha256"],
            )

    def test_purge_preserves_history_and_shared_content(self):
        self.file("lesson-plan.md")
        self.write()
        self.write()
        a, b = self.read()["artifacts"]
        self.write(
            "purge", artifact_id=a["artifact_id"], expected_revision=a["revision"]
        )
        self.service.collect_garbage()
        self.assertEqual(
            self.read("content", artifact_id=b["artifact_id"])["text"], "hello"
        )
        with self.assertRaisesRegex(ValueError, "artifact_unavailable"):
            self.read("content", artifact_id=a["artifact_id"])
        self.write(
            "purge", artifact_id=b["artifact_id"], expected_revision=b["revision"]
        )
        self.service.collect_garbage()
        self.assertFalse(self.service._content_path(b["sha256"]).exists())
        self.assertEqual(
            len(
                [
                    e
                    for e in self.read("history")["events"]
                    if e["type"] == "artifact.purged"
                ]
            ),
            2,
        )

    def build(self):
        directory = self.root / "builds/test-build"
        directory.mkdir(parents=True)
        (directory / "video.mp4").write_bytes(b"original video")
        (directory / "stdout.log").write_text("output")
        (directory / "stderr.log").write_text("")
        (directory / "manifest.json").write_text(
            json.dumps(
                {
                    "build_id": "test-build",
                    "artifacts": [{"path": "video.mp4", "kind": "video"}],
                }
            )
        )
        token = CAPTURE.set({"root": str(self.root), "session_id": self.session})
        try:
            self.service.enqueue_build(directory, "test-build")
        finally:
            CAPTURE.reset(token)
        return directory

    def drain(self):
        while self.service.work_once():
            pass

    def test_durable_build_jobs_survive_capture_off_and_original_cleanup(self):
        directory = self.build()
        self.log.configure(False)
        self.drain()
        shutil.rmtree(directory)
        artifacts = self.read()["artifacts"]
        self.assertEqual(len(artifacts), 4)
        video = next(a for a in artifacts if a["role"] == "preview_video")
        result = self.read("content", artifact_id=video["artifact_id"])
        self.assertEqual(Path(result["path"]).read_bytes(), b"original video")
        self.assertEqual({a["status"] for a in artifacts}, {"retained"})

    def test_changed_or_missing_build_not_mislabeled_retained(self):
        directory = self.build()
        (directory / "video.mp4").write_bytes(b"changed video")
        (directory / "stdout.log").unlink()
        self.drain()
        artifacts = self.read()["artifacts"]
        self.assertEqual(
            next(a for a in artifacts if a["role"] == "preview_video")["reason"],
            "source_changed",
        )
        self.assertEqual(
            next(a for a in artifacts if a["path"].endswith("stdout.log"))["reason"],
            "source_missing",
        )

    def test_corrupt_archive_detected_on_read(self):
        self.file("lesson-plan.md")
        self.write()
        a = self.read()["artifacts"][0]
        self.service._content_path(a["sha256"]).write_bytes(b"wrong")
        with self.assertRaisesRegex(ValueError, "artifact_corrupt"):
            self.read("content", artifact_id=a["artifact_id"])

    def test_store_write_failure_rolls_back_metadata_and_receipt(self):
        self.file("lesson-plan.md")
        with patch.object(self.service, "_put", side_effect=OSError("disk full")):
            # A bounded snapshot reports an omission rather than claiming retained content.
            result = self.write()
        self.assertFalse(result["files"])
        self.assertTrue(result["omitted"])
        self.assertFalse(
            any(a["status"] == "retained" for a in self.read()["artifacts"])
        )

    def test_real_rpc_and_restart_receipt(self):
        self.file("lesson-plan.md")
        payload = {"session_id": self.session, "request_id": "durable-request"}

        def run():
            request = (
                json.dumps(
                    {"id": 1, "method": "artifacts.checkpoint", "params": payload}
                )
                + "\n"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "manim_studio.research_cli",
                    "--root",
                    str(self.root),
                    "rpc",
                ],
                input=request,
                text=True,
                capture_output=True,
                check=True,
            )
            response = json.loads(result.stdout)
            self.assertTrue(response["ok"], response)
            return response["data"]

        self.assertEqual(run(), run())

    def test_expired_worker_lease_resumes_without_duplicate_artifact(self):
        self.build()
        with self.log.connection() as db:
            row = db.execute("SELECT id,payload FROM artifact_jobs LIMIT 1").fetchone()
            data = json.loads(row[1])
            data["lease_until"] = 0
            db.execute(
                "UPDATE artifact_jobs SET status='running',payload=? WHERE id=?",
                (json.dumps(data), row[0]),
            )
        self.drain()
        self.assertEqual(len(self.read()["artifacts"]), 4)
        self.assertTrue(all(j["status"] == "completed" for j in self.read()["jobs"]))

    def test_migration_backup_future_rejection_and_failed_ddl_rollback(self):
        with self.log.connection() as db:
            db.execute("PRAGMA user_version=4")
        self.read()
        backups = list(self.log.directory.glob("migration-backup-*"))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)
        with self.log.connection() as db:
            db.execute("PRAGMA user_version=99")
        with self.assertRaisesRegex(ValueError, "unsupported_schema"):
            self.read()
        with closing(sqlite3.connect(self.log.database)) as db:
            db.execute("PRAGMA user_version=4")
        with patch(
            "manim_studio.research_schema.ARTIFACTS", "CREATE TABLE bad (broken syntax;"
        ):
            with self.assertRaises(ResearchSessionError) as caught:
                self.read()
            self.assertEqual(caught.exception.code, "storage_error")
        with closing(sqlite3.connect(self.log.database)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 4)

    def test_managed_session_initial_snapshot_and_pause(self):
        self.file("lesson-plan.md")
        sessions = ResearchSessions(self.root)
        managed = sessions.dispatch(
            "create",
            {"title": "managed", "topic": "vectors", "request_id": "create-managed"},
        )
        state = self.service.dispatch("list", {"session_id": managed["session_id"]})
        self.assertEqual(len(state["snapshots"]), 1)
        sessions.dispatch(
            "pause",
            {
                "session_id": managed["session_id"],
                "expected_revision": 1,
                "request_id": "pause-managed",
            },
        )
        with self.assertRaisesRegex(ValueError, "session_paused"):
            self.service.dispatch(
                "checkpoint",
                {
                    "session_id": managed["session_id"],
                    "request_id": "paused-checkpoint",
                },
            )

    def test_checkpoint_crash_after_file_publish_has_no_partial_receipt(self):
        self.file("lesson-plan.md", "durable source")
        code = """
import os,sys
from manim_studio.research_artifacts import ResearchArtifacts
s=ResearchArtifacts(sys.argv[1]);put=s._put
s._put=lambda content: (put(content),os._exit(29))[0]
s.dispatch('checkpoint',dict(session_id=sys.argv[2],request_id='crash-request'))
"""
        result = subprocess.run(
            [sys.executable, "-c", code, str(self.root), self.session], check=False
        )
        self.assertEqual(result.returncode, 29)
        self.assertEqual(self.read()["total"], 0)
        recovered = self.write(request_id="crash-request")
        self.assertEqual(len(recovered["files"]), 1)
        self.assertEqual(self.read()["total"], 1)

    def test_source_export_contains_archived_bytes_but_metadata_has_no_content(self):
        self.file("lesson-plan.md", "SENSITIVE_SOURCE_SENTINEL")
        self.write()
        self.log.export(self.root / "metadata.jsonl")
        self.assertNotIn(
            "SENSITIVE_SOURCE_SENTINEL", (self.root / "metadata.jsonl").read_text()
        )
        self.log.export(self.root / "content.jsonl", include_content=True)
        import base64

        blobs = [
            r
            for r in map(
                json.loads, (self.root / "content.jsonl").read_text().splitlines()
            )
            if r["type"] == "source.blob"
        ]
        self.assertIn(
            b"SENSITIVE_SOURCE_SENTINEL", [base64.b64decode(r["base64"]) for r in blobs]
        )

    def test_project_quota_cannot_be_bypassed_by_session_override(self):
        self.file("lesson-plan.md", "some source")
        self.write(
            "configure",
            scope="project",
            values=dict(DEFAULT_POLICY, project_bytes=1),
            expected_revision=0,
        )
        self.write(
            "configure",
            scope="session",
            values=dict(DEFAULT_POLICY, project_bytes=100_000),
            expected_revision=0,
        )
        self.assertEqual(self.write()["files"], {})
        self.assertEqual(self.read()["artifacts"][0]["reason"], "omitted_quota")

    def test_video_view_extension_and_purge_remove_the_view(self):
        self.build()
        self.drain()
        a = next(a for a in self.read()["artifacts"] if a["role"] == "preview_video")
        result = self.read("content", artifact_id=a["artifact_id"])
        view = Path(result["path"])
        self.assertEqual(view.suffix, ".mp4")
        self.assertEqual(view.read_bytes(), b"original video")
        self.write(
            "purge", artifact_id=a["artifact_id"], expected_revision=a["revision"]
        )
        self.service.collect_garbage()
        self.assertFalse(view.exists())
        self.assertFalse(self.service._content_path(a["sha256"]).exists())

    def test_directory_symlink_or_windows_junction_cannot_escape_project(self):
        with tempfile.TemporaryDirectory() as outside:
            Path(outside, "secret.md").write_text("outside secret")
            link = self.root / "linked"
            if os.name == "nt":
                result = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(link), outside],
                    capture_output=True,
                    check=False,
                )
                if result.returncode:
                    self.skipTest("Windows junction creation unavailable")
            else:
                link.symlink_to(outside, target_is_directory=True)
            try:
                with self.assertRaises((ValueError, OSError)):
                    read_project_file(self.root, "linked/secret.md", 1000)
            finally:
                if os.name == "nt":
                    os.rmdir(link)
                else:
                    link.unlink()

    def test_worker_crash_after_publish_retries_same_artifact(self):
        self.build()
        code = """
import os,sys
from manim_studio.research_artifacts import ResearchArtifacts
s=ResearchArtifacts(sys.argv[1]);s._save_artifact=lambda *args: os._exit(31)
s.work_once()
"""
        result = subprocess.run(
            [sys.executable, "-c", code, str(self.root)], check=False
        )
        self.assertEqual(result.returncode, 31)
        with self.log.connection() as db:
            for row in db.execute(
                "SELECT id,payload FROM artifact_jobs WHERE status='running'"
            ).fetchall():
                data = json.loads(row[1])
                data["lease_until"] = 0
                db.execute(
                    "UPDATE artifact_jobs SET payload=? WHERE id=?",
                    (json.dumps(data), row[0]),
                )
        self.drain()
        self.assertEqual(self.read()["total"], 4)
        retained = [
            e
            for e in self.read("history")["events"]
            if e["type"] == "artifact.retained"
        ]
        self.assertEqual(len(retained), 4)

    def test_media_loaded_is_separate_from_generated_or_unverified_content(self):
        self.build()
        self.assertFalse(
            any(
                e["type"] == "artifact.presented"
                for e in self.read("history")["events"]
            )
        )
        self.write("presented_build", build_id="test-build")
        events = self.read("history")["events"]
        self.assertTrue(
            any(e["type"] == "artifact.presentation_unverified" for e in events)
        )
        self.assertFalse(any(e["type"] == "artifact.presented" for e in events))
        self.drain()
        self.write("presented_build", build_id="test-build")
        event = [
            e
            for e in self.read("history")["events"]
            if e["type"] == "artifact.presented"
        ][-1]
        self.assertEqual(event["payload"]["sha256"], digest(b"original video"))
        self.assertEqual(event["payload"]["evidence"], "client_reported_media_loaded")


class DecisionIntegrationTests(unittest.TestCase):
    def test_rpc_decisions_archive_candidates_origin_and_render_failure(self):
        with (
            AuthoringFixture() as fixture,
            fake_manim_module(),
            patch("manim_studio.research_artifacts.kick_worker"),
        ):
            log = ResearchLog(fixture.root)
            log.configure(True)
            session = log.start_session("research")
            controller = fixture.controller()
            authoring = controller.start_session(title="Vectors", deck_id="vectors")
            aid = authoring["session_id"]
            metadata = {
                "session_id": session,
                "decision_origin": "human",
                "origin_evidence": "explicit_test_click",
            }

            def propose(body):
                return controller.propose_next_movie_step(aid, body)[
                    "active_proposal_id"
                ]

            proposal = propose("self.add(Dot())")
            result = controller.dispatch(
                "reject_proposal",
                {"session_id": aid, "proposal_id": proposal, "_research": metadata},
            )
            self.assertEqual(result["status"], "rejected")
            service = ResearchArtifacts(fixture.root)
            state = service.dispatch("list", {"session_id": session})
            self.assertEqual(len(state["decisions"]), 1)
            decision = state["decisions"][0]
            self.assertEqual(
                (decision["origin"], decision["status"]), ("human", "completed")
            )
            candidate = decision["candidate"]["candidate_source"]
            shutil.rmtree(fixture.root / "builds" / "staged" / proposal)
            self.assertIn(
                "Dot()",
                service.dispatch(
                    "content",
                    {"session_id": session, "artifact_id": candidate["artifact_id"]},
                )["text"],
            )
            propose("self.wait(0.1)")
            controller.render_runner = FakeRenderRunner(
                returncode=1, stderr="failed render"
            )
            with self.assertRaises(AuthoringSessionError):
                controller.dispatch(
                    "accept_proposal", {"session_id": aid, "_research": metadata}
                )
            decisions = service.dispatch("list", {"session_id": session})["decisions"]
            self.assertEqual([d["status"] for d in decisions], ["completed", "failed"])
            self.assertTrue(decisions[-1]["candidate"]["candidate_source"]["sha256"])

    def test_nested_accept_exact_candidate_unknown_origin_and_nonblocking_lock(self):
        with (
            AuthoringFixture() as fixture,
            fake_manim_module(),
            patch("manim_studio.research_artifacts.kick_worker"),
        ):
            log = ResearchLog(fixture.root)
            log.configure(True)
            session = log.start_session("research")
            controller = fixture.controller()
            aid = controller.start_session(title="Story", deck_id="story")["session_id"]
            controller.propose_next_movie_step(aid, "self.wait(0.1)")
            with decision_lock(log.directory):  # noqa: SIM117 - boundary for the concurrent caller
                with self.assertRaisesRegex(Exception, "Another decision"):
                    controller.dispatch(
                        "accept_proposal",
                        {"session_id": aid, "_research": {"session_id": session}},
                    )
            result = controller.dispatch(
                "accept_proposal",
                {"session_id": aid, "_research": {"session_id": session}},
            )
            self.assertEqual(result["status"], "accepted")
            service = ResearchArtifacts(fixture.root)
            state = service.dispatch("list", {"session_id": session})
            self.assertEqual(len(state["decisions"]), 1)
            decision = state["decisions"][0]
            self.assertEqual(decision["origin"], "unknown")
            self.assertEqual(decision["status"], "completed")
            candidate = decision["candidate"]["candidate_source"]
            self.assertEqual(
                candidate["sha256"],
                digest(service._read_content(candidate["sha256"], candidate["size"])),
            )
            self.assertNotIn(
                "research",
                [
                    p.name
                    for p in (fixture.root / "builds" / "staged").rglob("research")
                ],
            )

    def test_archiving_failure_does_not_change_authoring_result(self):
        with AuthoringFixture() as fixture, fake_manim_module():
            log = ResearchLog(fixture.root)
            log.configure(True)
            session = log.start_session("research")
            controller = fixture.controller()
            aid = controller.start_session(title="Story", deck_id="story")["session_id"]
            controller.propose_next_movie_step(aid, "self.wait(0.1)")
            with (
                patch.object(
                    ResearchArtifacts, "checkpoint", side_effect=OSError("disk full")
                ),
                self.assertWarns(RuntimeWarning),
            ):
                result = controller.dispatch(
                    "reject_proposal",
                    {"session_id": aid, "_research": {"session_id": session}},
                )
            self.assertEqual(result["status"], "rejected")

    def test_decision_request_retry_returns_original_outcome_once(self):
        with (
            AuthoringFixture() as fixture,
            fake_manim_module(),
            patch("manim_studio.research_artifacts.kick_worker"),
        ):
            log = ResearchLog(fixture.root)
            log.configure(True)
            session = log.start_session("research")
            controller = fixture.controller()
            aid = controller.start_session(title="Story", deck_id="story")["session_id"]
            controller.propose_next_movie_step(aid, "self.wait(0.1)")
            params = {
                "session_id": aid,
                "_research": {"session_id": session, "request_id": "same-decision"},
            }
            first = controller.dispatch("accept_proposal", params)
            second = controller.dispatch("accept_proposal", params)
            self.assertEqual(first, second)
            service = ResearchArtifacts(fixture.root)
            self.assertEqual(
                len(service.dispatch("list", {"session_id": session})["decisions"]), 1
            )
            with self.assertRaisesRegex(ValueError, "request_id_conflict"):
                controller.dispatch("reject_proposal", params)

    def test_candidate_changed_during_render_is_not_accepted(self):
        from manim_studio import staged_edits

        with (
            AuthoringFixture() as fixture,
            fake_manim_module(),
            patch("manim_studio.research_artifacts.kick_worker"),
        ):
            log = ResearchLog(fixture.root)
            log.configure(True)
            session = log.start_session("research")
            controller = fixture.controller()
            aid = controller.start_session(title="Story", deck_id="story")["session_id"]
            pid = controller.propose_next_movie_step(aid, "self.wait(0.1)")[
                "active_proposal_id"
            ]
            apply = staged_edits.apply_scene_patch

            def changed(*args, **kwargs):
                source = staged_edits.proposal_source_path(fixture.root, "builds", pid)
                source.write_text(source.read_text() + "\n# external concurrent edit\n")
                return apply(*args, **kwargs)

            with patch.object(staged_edits, "apply_scene_patch", side_effect=changed):  # noqa: SIM117 - concurrent edit injection
                with self.assertRaisesRegex(Exception, "Candidate changed"):
                    controller.dispatch(
                        "accept_proposal",
                        {"session_id": aid, "_research": {"session_id": session}},
                    )
            decisions = ResearchArtifacts(fixture.root).dispatch(
                "list", {"session_id": session}
            )["decisions"]
            self.assertEqual(decisions[0]["status"], "failed")

    def test_capture_off_on_during_render_does_not_backfill_build(self):
        with (
            AuthoringFixture() as fixture,
            fake_manim_module(),
            patch("manim_studio.research_artifacts.kick_worker"),
        ):
            log = ResearchLog(fixture.root)
            log.configure(True)
            session = log.start_session("research")
            controller = fixture.controller()
            aid = controller.start_session(title="Story", deck_id="story")["session_id"]
            controller.propose_next_movie_step(aid, "self.wait(0.1)")
            runner = controller.render_runner

            def boundary(*args, **kwargs):
                log.configure(False)
                log.configure(True)
                return runner(*args, **kwargs)

            controller.render_runner = boundary
            with self.assertWarns(RuntimeWarning):
                result = controller.dispatch(
                    "accept_proposal",
                    {"session_id": aid, "_research": {"session_id": session}},
                )
            self.assertEqual(result["status"], "accepted")
            state = ResearchArtifacts(fixture.root).dispatch(
                "list", {"session_id": session}
            )
            self.assertEqual(state["jobs"], [])
            self.assertEqual(state["decisions"][0]["status"], "outcome_unknown")


if __name__ == "__main__":
    unittest.main()
