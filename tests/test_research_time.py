import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from manim_studio.prompt_classifications import PromptClassifications
from manim_studio.research import ResearchLog
from manim_studio.research_context import os_metadata, record_context, runtime_probe
from manim_studio.research_sessions import ResearchSessionError, ResearchSessions
from manim_studio.research_time import LEASE_SECONDS, ResearchTiming, summarize


class FakeClock:
    def __init__(self, token="process-A"):
        self.token = token
        self.mono = 100.0
        self.epoch = 1_800_000_000.0

    def monotonic(self):
        return self.mono

    def wall(self):
        return self.epoch

    def utc(self):
        return datetime.fromtimestamp(self.epoch, UTC).isoformat()

    def advance(self, seconds, wall=None):
        self.mono += seconds
        self.epoch += seconds if wall is None else wall


class TimingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.log = ResearchLog(self.root)
        self.log.configure(True)
        self.session = self.log.start_session("וקטורים")
        self.clock = FakeClock()
        self.service = ResearchTiming(self.root, self.clock)

    def read(self, session=None, client="client-A"):
        return self.service.dispatch(
            "status", {"session_id": session or self.session, "client_id": client}
        )

    def write(self, action, **params):
        payload = {
            "session_id": self.session,
            "client_id": "client-A",
            "request_id": str(uuid.uuid4()),
        }
        if action in ("start", "pause", "stop", "transfer"):
            state = self.read()
            payload["expected_revision"] = state["revision"]
            if state["active"]:
                payload["interval_id"] = state["active"]["interval_id"]
        if action == "heartbeat":
            active = self.read()["active"]
            payload.update(
                interval_id=active["interval_id"], sequence=active["sequence"] + 1
            )
        payload.update(params)
        return self.service.dispatch(action, payload)

    def test_explicit_timer_checkpoints_pause_and_new_interval(self):
        first = self.write("start", category="authoring")
        id = first["active"]["interval_id"]
        self.clock.advance(15)
        beat = self.write("heartbeat")
        self.assertEqual(beat["active"]["measured_seconds"], 15)
        self.clock.advance(7)
        ended = self.write("pause")
        self.assertIsNone(ended["active"])
        self.assertEqual(ended["intervals"][0]["measured_seconds"], 22)
        self.assertEqual(ended["intervals"][0]["status"], "paused")
        self.assertEqual(ended["summary"]["tracked_seconds"]["authoring"], 22)
        new = self.write("start", category="authoring")
        self.assertNotEqual(new["active"]["interval_id"], id)

    def test_single_timer_across_two_clients_and_sessions(self):
        other = self.log.start_session("אחר")
        head = self.read()["revision"]

        def start(item):
            session, client = item
            try:
                return self.service.dispatch(
                    "start",
                    {
                        "session_id": session,
                        "client_id": client,
                        "category": "authoring",
                        "expected_revision": head,
                        "request_id": str(uuid.uuid4()),
                    },
                )["active"]["interval_id"]
            except ResearchSessionError as e:
                return e.code

        with ThreadPoolExecutor(2) as pool:
            result = list(
                pool.map(start, [(self.session, "client-A"), (other, "client-B")])
            )
        self.assertEqual(result.count("timer_already_running"), 1)
        with self.log.connection() as db:
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM timing_intervals WHERE status='active'"
                ).fetchone()[0],
                1,
            )

    def test_transfer_closes_and_opens_atomically(self):
        other = self.log.start_session("אחר")
        self.write("start", category="authoring")
        self.clock.advance(12)
        result = self.write(
            "transfer", target_session_id=other, category="classification"
        )
        self.assertEqual(result["active"]["session_id"], other)
        self.assertEqual(self.read()["summary"]["tracked_seconds"]["authoring"], 12)
        self.clock.advance(9)
        self.service.dispatch(
            "stop",
            {
                "session_id": other,
                "client_id": "client-A",
                "interval_id": result["active"]["interval_id"],
                "expected_revision": result["revision"],
                "request_id": "stop-transferred",
            },
        )
        self.assertEqual(
            self.read(other)["summary"]["tracked_seconds"]["classification"], 9
        )

    def test_heartbeat_idempotency_and_sequence_validation(self):
        state = self.write("start")
        self.clock.advance(15)
        params = {
            "session_id": self.session,
            "client_id": "client-A",
            "interval_id": state["active"]["interval_id"],
            "sequence": 1,
            "request_id": "heartbeat-one",
        }
        first = self.service.dispatch("heartbeat", params)
        self.clock.advance(5)
        self.assertEqual(
            self.service.dispatch("heartbeat", dict(reversed(list(params.items())))),
            first,
        )
        self.assertEqual(self.read()["active"]["measured_seconds"], 15)
        with self.assertRaisesRegex(ValueError, "heartbeat_sequence_conflict"):
            self.service.dispatch(
                "heartbeat", dict(params, request_id="new-wrong-sequence")
            )

    def test_lost_start_reply_receipt_survives_head_changes(self):
        params = {
            "session_id": self.session,
            "client_id": "client-A",
            "category": "authoring",
            "expected_revision": 0,
            "request_id": "start-one",
        }
        first = self.service.dispatch("start", params)
        self.clock.advance(3)
        self.write("stop")
        self.assertEqual(self.service.dispatch("start", params), first)
        self.assertIsNone(self.read()["active"])
        with self.assertRaisesRegex(ValueError, "request_id_conflict"):
            self.service.dispatch("start", dict(params, category="classification"))

    def test_expired_lease_keeps_only_confirmed_seconds(self):
        self.write("start")
        self.clock.advance(15)
        self.write("heartbeat")
        self.clock.advance(LEASE_SECONDS + 1)
        state = self.read()
        self.assertIsNone(state["active"])
        self.assertEqual(state["intervals"][0]["measured_seconds"], 15)
        self.assertEqual(state["intervals"][0]["status"], "interrupted")
        self.assertTrue(state["intervals"][0]["tail_unknown"])

    def test_process_restart_does_not_reuse_old_monotonic_origin(self):
        self.write("start")
        self.clock.advance(10)
        self.write("heartbeat")
        restarted = ResearchTiming(self.root, FakeClock("process-B"))
        state = restarted.dispatch(
            "status", {"session_id": self.session, "client_id": "client-A"}
        )
        self.assertIsNone(state["active"])
        self.assertEqual(state["intervals"][0]["measured_seconds"], 10)
        self.assertEqual(state["intervals"][0]["close_reason"], "process_restarted")

    def test_other_window_observation_does_not_interrupt_owner(self):
        self.write("start")
        other = ResearchTiming(self.root, FakeClock("process-B"))
        state = other.dispatch(
            "status", {"session_id": self.session, "client_id": "client-B"}
        )
        self.assertIsNotNone(state["active"])
        self.assertFalse(state["active"]["owned"])
        self.clock.advance(5)
        self.assertEqual(self.write("heartbeat")["active"]["measured_seconds"], 5)

    def test_other_window_stop_uses_only_last_checkpoint(self):
        state = self.write("start")
        self.clock.advance(10)
        state = self.write("heartbeat")
        self.clock.advance(12)
        other_clock = FakeClock("process-B")
        other_clock.epoch = self.clock.epoch
        other = ResearchTiming(self.root, other_clock)
        result = other.dispatch(
            "stop",
            {
                "session_id": self.session,
                "client_id": "client-B",
                "interval_id": state["active"]["interval_id"],
                "expected_revision": state["revision"],
                "request_id": "other-stop",
            },
        )
        self.assertEqual(result["intervals"][0]["status"], "interrupted")
        self.assertEqual(result["intervals"][0]["measured_seconds"], 10)

    def test_sleep_or_long_wall_gap_not_counted_as_effort(self):
        self.write("start")
        self.clock.advance(1, wall=3600)
        result = self.write("heartbeat")
        self.assertIsNone(result["active"])
        self.assertEqual(result["intervals"][0]["measured_seconds"], 0)

    def test_wall_clock_backwards_preserves_monotonic_but_marks_anomaly(self):
        self.write("start")
        self.clock.advance(10, wall=-20)
        result = self.write("heartbeat")
        self.assertEqual(result["active"]["measured_seconds"], 10)
        self.assertIn("clock_anomaly", result["summary"]["warnings"])
        self.assertEqual(result["summary"]["canonical_tracked_seconds"]["authoring"], 0)

    def test_report_validation_and_unknown_time_not_zero(self):
        state = self.read()
        self.assertTrue(state["summary"]["human_time_missing"])
        self.assertIsNone(state["summary"]["system"]["model_turn"]["union_seconds"])
        for value in (-1, float("inf"), float("nan"), True, "10"):
            with self.assertRaises((ValueError, ResearchSessionError)):
                self.write("report", seconds=value)
        for value in (False, 0, "", [], {}):
            with (
                self.subTest(boundary=value),
                self.assertRaisesRegex(ValueError, "invalid_timestamp"),
            ):
                self.write("report", seconds=0, start_utc=value, end_utc=value)
        for key in ("measurement_ref", "replaces_interval_id"):
            with (
                self.subTest(link=key),
                self.assertRaisesRegex(ValueError, "invalid_identifier"),
            ):
                self.write("report", seconds=1, **{key: []})
        with self.assertRaisesRegex(ValueError, "invalid_timestamp"):
            self.write(
                "report",
                seconds=1,
                start_utc="2026-10-31T10:00",
                end_utc="2026-10-31T10:01",
            )
        with self.assertRaisesRegex(ValueError, "invalid_time_range"):
            self.write(
                "report",
                seconds=100,
                start_utc="2026-10-31T10:00Z",
                end_utc="2026-10-31T10:01Z",
            )

    def test_report_correction_void_preserve_history_and_revision(self):
        report = self.write("report", seconds=60)["report"]
        changed = self.write(
            "correct", report_id=report["report_id"], expected_revision=1, seconds=45
        )["report"]
        self.assertEqual(changed["revision"], 2)
        with self.assertRaisesRegex(ValueError, "report_conflict"):
            self.write(
                "correct", report_id=report["report_id"], expected_revision=1, seconds=1
            )
        self.write("void", report_id=report["report_id"], expected_revision=2)
        self.assertEqual(
            self.read()["summary"]["self_reported_seconds"]["authoring"], 0
        )
        history = self.service.dispatch("history", {"session_id": self.session})[
            "events"
        ]
        self.assertEqual(
            [e["type"] for e in history if e["type"].startswith("time.")],
            ["time.reported", "time.corrected", "time.voided"],
        )

    def test_report_replaces_only_named_closed_interval_and_can_be_voided(self):
        self.write("start")
        self.clock.advance(20)
        self.write("stop")
        interval = self.read()["intervals"][0]
        report = self.write(
            "report",
            seconds=15,
            replaces_interval_id=interval["interval_id"],
            expected_interval_revision=interval["revision"],
        )["report"]
        summary = self.read()["summary"]
        self.assertEqual(summary["tracked_seconds"]["authoring"], 0)
        self.assertEqual(summary["self_reported_seconds"]["authoring"], 15)
        with self.assertRaisesRegex(ValueError, "measurement_already_reported"):
            self.write(
                "report",
                seconds=1,
                replaces_interval_id=interval["interval_id"],
                expected_interval_revision=interval["revision"],
            )
        self.write(
            "void",
            report_id=report["report_id"],
            expected_revision=1,
            expected_interval_revision=interval["revision"],
        )
        self.assertEqual(self.read()["summary"]["tracked_seconds"]["authoring"], 20)

    def test_classification_measurement_reference_is_not_counted_twice(self):
        prompt = self.log.record_prompt(self.session, "text")
        api = PromptClassifications(self.root)
        project = api.dispatch(
            "get", {"session_id": self.session, "prompt_id": prompt}
        )["project_id"]
        event = api.dispatch(
            "save",
            {
                "session_id": self.session,
                "prompt_id": prompt,
                "project_id": project,
                "prompt_type": "initial",
                "expected_human_head": None,
                "request_id": "classification-time",
                "human_seconds": 12,
            },
        )["event_id"]
        self.assertEqual(
            self.read()["summary"]["legacy_classification_self_report_seconds"], 12
        )
        self.write(
            "report", category="classification", seconds=10, measurement_ref=event
        )
        summary = self.read()["summary"]
        self.assertEqual(summary["legacy_classification_self_report_seconds"], 0)
        self.assertEqual(summary["self_reported_seconds"]["classification"], 10)
        with self.assertRaisesRegex(ValueError, "measurement_already_reported"):
            self.write(
                "report", category="classification", seconds=10, measurement_ref=event
            )

    def test_cross_session_and_project_validation(self):
        other = self.log.start_session("other")
        report = self.write("report", seconds=3)["report"]
        with self.assertRaisesRegex(ValueError, "report_not_found"):
            self.service.dispatch(
                "correct",
                {
                    "session_id": other,
                    "report_id": report["report_id"],
                    "expected_revision": 1,
                    "request_id": "cross",
                    "seconds": 4,
                },
            )
        with self.assertRaisesRegex(ValueError, "project_mismatch"):
            self.write("start", project_id="foreign")
        prompt = self.log.record_prompt(other, "not this study")
        with self.assertRaisesRegex(ValueError, "measurement_link_mismatch"):
            self.write("start", prompt_id=prompt)

    def test_pause_finish_and_capture_off_close_atomically(self):
        sessions = ResearchSessions(self.root)
        managed = sessions.dispatch(
            "create", {"title": "managed", "topic": "vectors", "request_id": "new"}
        )
        self.session = managed["session_id"]
        self.write("start")
        self.clock.advance(15)
        self.write("heartbeat")
        sessions.dispatch(
            "pause",
            {"session_id": self.session, "expected_revision": 1, "request_id": "pause"},
        )
        self.assertIsNone(self.read()["active"])
        self.assertEqual(self.read()["intervals"][0]["measured_seconds"], 15)
        self.write("report", seconds=10)
        with self.assertRaisesRegex(ValueError, "session_paused"):
            self.write("start")
        sessions.dispatch(
            "resume",
            {
                "session_id": self.session,
                "expected_revision": 2,
                "request_id": "resume",
            },
        )
        self.write("start")
        self.log.configure(False)
        self.assertIsNone(self.read()["active"])
        self.write("report", seconds=0)
        with self.assertRaisesRegex(ValueError, "capture_disabled"):
            self.write("start")
        self.log.configure(True)
        sessions.dispatch(
            "finish",
            {
                "session_id": self.session,
                "expected_revision": 3,
                "request_id": "finish",
            },
        )
        self.write("report", seconds=2)

    def test_write_failure_rolls_back_heartbeat_seconds_and_receipt(self):
        self.write("start")
        self.clock.advance(15)
        with patch.object(self.service, "_event", side_effect=OSError("disk full")):
            with self.assertRaises(ResearchSessionError) as error:
                self.write("heartbeat", request_id="failed-beat")
            self.assertEqual(error.exception.code, "storage_error")
        self.assertEqual(self.read()["active"]["measured_seconds"], 0)
        self.assertEqual(
            self.write("heartbeat", request_id="failed-beat")["active"][
                "measured_seconds"
            ],
            15,
        )

    def test_report_overlap_is_visible_and_not_added_to_tracked_time(self):
        self.write("start")
        self.clock.advance(30)
        self.write("stop")
        interval = self.read()["intervals"][0]
        self.write(
            "report",
            seconds=10,
            start_utc=interval["start_utc"],
            end_utc=interval["confirmed_end_utc"],
        )
        summary = self.read()["summary"]
        self.assertEqual(summary["canonical_tracked_seconds"]["authoring"], 30)
        self.assertEqual(summary["self_reported_seconds"]["authoring"], 10)
        self.assertIn("report_overlaps_timer", summary["warnings"])

    def test_migration_from_v5_does_not_invent_time(self):
        with self.log.connection() as db:
            db.execute("PRAGMA user_version=5")
        state = self.read()
        self.assertTrue(state["summary"]["human_time_missing"])
        self.assertTrue(list(self.log.directory.glob("migration-backup-*")))
        with self.log.connection() as db:
            from manim_studio.research_schema import VERSION
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], VERSION)

    def test_real_persistent_rpc_unicode_and_restart(self):
        env = dict(
            os.environ,
            PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
            PYTHONIOENCODING="cp1252",
        )
        requests = [
            {
                "id": 1,
                "method": "timing.status",
                "params": {"session_id": self.session, "client_id": "stdio"},
            },
            {
                "id": 2,
                "method": "timing.report",
                "params": {
                    "session_id": self.session,
                    "seconds": 12,
                    "request_id": "stdio-report",
                },
            },
            {
                "id": 3,
                "method": "timing.status",
                "params": {"session_id": self.session, "client_id": "stdio"},
            },
        ]
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "manim_studio.research_cli",
                "--root",
                str(self.root),
                "rpc",
            ],
            input="\n".join(map(json.dumps, requests)) + "\n",
            text=True,
            encoding="utf-8",
            capture_output=True,
            env=env,
            timeout=15,
            check=True,
        )
        responses = list(map(json.loads, result.stdout.splitlines()))
        self.assertTrue(all(r["ok"] for r in responses), responses)
        self.assertEqual(responses[-1]["data"]["title"], "וקטורים")
        self.assertEqual(
            responses[-1]["data"]["summary"]["self_reported_seconds"]["authoring"], 12
        )

    def test_actual_process_death_before_commit_and_after_lost_reply(self):
        for boundary in ("before_commit", "after_commit"):
            with self.subTest(boundary=boundary):
                state = self.write("start")
                payload = {
                    "session_id": self.session,
                    "client_id": "client-A",
                    "interval_id": state["active"]["interval_id"],
                    "sequence": 1,
                    "request_id": "crash-" + boundary,
                }
                child_script = """
import json,os,sys
from pathlib import Path
from tests.test_research_time import FakeClock
from manim_studio.research_time import ResearchTiming
clock=FakeClock();clock.advance(float(sys.argv[4]))
service=ResearchTiming(Path(sys.argv[1]),clock)
original=service.log._event
def event(db,kind,*args,**kwargs):
    result=original(db,kind,*args,**kwargs)
    if kind=='time.interval.checkpointed' and sys.argv[3]=='before_commit':os._exit(23)
    return result
service.log._event=event
service.dispatch('heartbeat',json.loads(sys.argv[2]))
os._exit(24)
"""
                elapsed = self.clock.mono - 100 + 10
                result = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        child_script,
                        str(self.root),
                        json.dumps(payload),
                        boundary,
                        str(elapsed),
                    ],
                    env=dict(
                        os.environ,
                        PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
                    ),
                    timeout=15,
                    check=False,
                )
                self.assertEqual(
                    result.returncode, 23 if boundary == "before_commit" else 24
                )
                with self.log.connection() as db:
                    data = json.loads(
                        db.execute(
                            "SELECT payload FROM timing_intervals WHERE id=?",
                            (payload["interval_id"],),
                        ).fetchone()[0]
                    )
                    self.assertEqual(
                        data["measured_seconds"],
                        0 if boundary == "before_commit" else 10,
                    )
                self.clock.advance(10)
                retried = self.service.dispatch("heartbeat", payload)
                self.assertEqual(retried["active"]["measured_seconds"], 10)
                self.assertEqual(self.read()["active"]["sequence"], 1)
                self.write("stop")


class SummaryTests(unittest.TestCase):
    def test_turn_ids_are_scoped_to_client_and_overlap_is_unioned(self):
        events = []
        for index, (client, kind, second) in enumerate(
            [
                ("A", "started", 0),
                ("B", "started", 5),
                ("A", "completed", 10),
                ("B", "completed", 15),
            ]
        ):
            events.append(
                self.event(
                    str(index),
                    "client.turn." + kind,
                    f"2026-10-31T10:00:{second:02}Z",
                    {
                        "source": {
                            "client_id": client,
                            "thread_id": "thread",
                            "turn_id": "turn",
                        }
                    },
                )
            )
        result = summarize([], [], events)["system"]["model_turn"]
        self.assertEqual(result["union_seconds"], 15)
        self.assertEqual(result["incomplete"], 0)

    def test_backward_session_clock_never_becomes_negative_duration(self):
        events = [
            self.event("a", "session.started", "2026-10-31T10:00:00Z", {}),
            self.event("b", "session.finished", "2026-10-31T09:00:00Z", {}),
        ]
        result = summarize([], [], events)
        self.assertIsNone(result["research_wall_seconds"])
        self.assertIn("clock_anomaly", result["warnings"])

    def event(self, id, kind, utc, payload, parent=None, actor="system"):
        return {
            "id": id,
            "type": kind,
            "timestamp": utc,
            "payload": payload,
            "parent_id": parent,
            "actor": actor,
        }

    def test_nested_and_overlapping_actions_have_union_not_raw_sum(self):
        events = [
            self.event(
                "a", "action.started", "2026-10-31T10:00:00Z", {"name": "render"}
            ),
            self.event(
                "b", "action.started", "2026-10-31T10:00:05Z", {"name": "render"}
            ),
            self.event(
                "c",
                "action.finished",
                "2026-10-31T10:00:10Z",
                {"duration_seconds": 10},
                "a",
            ),
            self.event(
                "d",
                "action.finished",
                "2026-10-31T10:00:15Z",
                {"duration_seconds": 10},
                "b",
            ),
        ]
        result = summarize([], [], events)["system"]
        self.assertEqual(result["tool"]["raw_seconds"], 20)
        self.assertEqual(result["tool"]["union_seconds"], 15)
        self.assertEqual(result["render"]["union_seconds"], 15)

    def test_incomplete_actions_and_turns_are_not_zero_measurements(self):
        events = [
            self.event(
                "a", "action.started", "2026-10-31T10:00:00Z", {"name": "render"}
            ),
            self.event(
                "b",
                "client.turn.completed",
                "2026-10-31T10:00:30Z",
                {"source": {"thread_id": "t", "turn_id": "x"}},
            ),
        ]
        summary = summarize([], [], events)
        self.assertIsNone(summary["system"]["tool"]["raw_seconds"])
        self.assertEqual(summary["system"]["tool"]["incomplete"], 1)
        self.assertEqual(summary["system"]["model_turn"]["incomplete"], 1)

    def test_turn_observation_uses_explicit_thread_and_hook(self):
        source = {"thread_id": "thread", "turn_id": "turn", "hook": "UserPromptSubmit"}
        events = [
            self.event(
                "a",
                "prompt.recorded",
                "2026-10-31T10:00:00Z",
                {"source": source},
                actor="human",
            ),
            self.event(
                "b", "client.turn.completed", "2026-10-31T10:00:20Z", {"source": source}
            ),
        ]
        self.assertEqual(
            summarize([], [], events)["system"]["model_turn"]["union_seconds"], 20
        )


class RunContextTests(unittest.TestCase):
    def test_metadata_timeout_does_not_wait_for_descendant_output_eof(self):
        # An isolated watchdog keeps the suite bounded even if PIPE cleanup
        # regresses. The grandchild holds stdout open after its parent is killed.
        code = """
import subprocess,sys,time
from manim_studio.research_context import command_output
parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(15)']); time.sleep(15)"
started=time.monotonic()
try:
    command_output([sys.executable,'-c',parent],timeout=0.5)
except subprocess.TimeoutExpired:
    print('bounded',flush=True)
else:
    raise AssertionError('expected a deadline')
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=8,
            check=True,
            env=dict(
                os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src")
            ),
        )
        self.assertEqual(result.stdout.strip(), "bounded")

    def test_windows_metadata_on_worker_never_queries_wmi_or_uname(self):
        from types import SimpleNamespace

        with (
            patch("manim_studio.research_context.sys.platform", "win32"),
            patch(
                "manim_studio.research_context.sys.getwindowsversion",
                create=True,
                return_value=SimpleNamespace(major=10, minor=0, build=20348),
            ),
            patch(
                "manim_studio.research_context.sysconfig.get_platform",
                return_value="win-amd64",
            ),
            patch(
                "manim_studio.research_context.platform.uname",
                side_effect=AssertionError("unbounded WMI"),
            ),
            ThreadPoolExecutor(1) as worker,
        ):
            data = worker.submit(os_metadata).result(timeout=2)
        self.assertEqual(data["system"], "Windows")
        self.assertEqual(data["release"], "10.0.20348")
        self.assertEqual(data["architecture"], "win-amd64")
        self.assertEqual(data["architecture_source"], "python_build_platform")

    def test_windows_version_unavailable_stays_null_without_wmi_fallback(self):
        with (
            patch("manim_studio.research_context.sys.platform", "win32"),
            patch(
                "manim_studio.research_context.sys.getwindowsversion",
                create=True,
                side_effect=OSError("unavailable"),
            ),
            patch(
                "manim_studio.research_context.sysconfig.get_platform",
                return_value="win-amd64",
            ),
            patch(
                "manim_studio.research_context.platform.uname",
                side_effect=AssertionError("unbounded WMI"),
            ),
        ):
            self.assertIsNone(os_metadata()["release"])

    def test_metadata_is_filtered_before_storage_and_past_event_context_is_immutable(
        self,
    ):
        with tempfile.TemporaryDirectory() as root:
            log = ResearchLog(Path(root))
            log.configure(True)
            session = log.start_session(
                "study",
                model={"model": "a", "api_key": "SECRET"},
                run_settings={"seed": 7, "password": "SECRET"},
            )
            first = log.record_prompt(
                session, "first", model={"model": "a", "token": "SECRET"}
            )
            second = log.record_prompt(
                session, "second", model={"model": "b", "token": "SECRET"}
            )
            with log.connection() as db:
                events = list(db.execute("SELECT id,payload FROM events"))
                self.assertNotIn("SECRET", str([row["payload"] for row in events]))
                ids = {row["id"]: json.loads(row["payload"]) for row in events}
                a, b = ids[first]["run_context_id"], ids[second]["run_context_id"]
                self.assertNotEqual(a, b)
                contexts = {
                    row["id"]: json.loads(row["payload"])
                    for row in db.execute("SELECT * FROM run_contexts")
                }
                self.assertEqual(contexts[a]["model"]["model"], "a")
                self.assertEqual(contexts[b]["model"]["model"], "b")

    def test_allowlist_model_changes_provenance_and_export(self):
        with tempfile.TemporaryDirectory() as root:
            log = ResearchLog(Path(root))
            log.configure(True)
            session = log.start_session("private label")
            timing = ResearchTiming(root)
            for model in ("model-a", "model-b"):
                timing.dispatch(
                    "observe_context",
                    {
                        "session_id": session,
                        "client_id": "client",
                        "request_id": model,
                        "model": {"model": model, "version": "v1", "api_key": "SECRET"},
                        "settings": {"seed": 3, "authorization": "SECRET"},
                    },
                )
            contexts = timing.dispatch("contexts", {"session_id": session})["contexts"]
            self.assertEqual(
                [c["model"]["model"] for c in contexts if c["client_id"] == "client"],
                ["model-a", "model-b"],
            )
            log.export(Path(root) / "metadata.jsonl")
            text = (Path(root) / "metadata.jsonl").read_text()
            self.assertNotIn("SECRET", text)
            self.assertNotIn("private label", text)
            self.assertIn("model-b", text)

    def test_git_commit_dirty_and_client_metadata_do_not_inherit_other_client(self):
        with tempfile.TemporaryDirectory() as root:
            subprocess.run(["git", "init", root], check=True, capture_output=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    root,
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.invalid",
                    "commit",
                    "--allow-empty",
                    "-m",
                    "fixture",
                ],
                check=True,
                capture_output=True,
            )
            info = runtime_probe(root)
            self.assertEqual(len(info["git"]["commit"]), 40)
            self.assertFalse(info["git"]["dirty"])
            Path(root, "new.txt").write_text("untracked")
            self.assertTrue(runtime_probe(root)["git"]["dirty"])
            log = ResearchLog(Path(root))
            log.configure(True)
            session = log.start_session("study")
            with log.connection() as db:
                a = record_context(log, db, session, "A", model={"model": "A"})
                b = record_context(log, db, session, "B")
                self.assertNotEqual(a, b)
                self.assertIsNone(
                    json.loads(
                        db.execute(
                            "SELECT payload FROM run_contexts WHERE id=?", (b,)
                        ).fetchone()[0]
                    )["model"]
                )

    def test_git_timeout_is_missing_metadata_not_failure(self):
        with patch(
            "manim_studio.research_context.subprocess.run",
            side_effect=subprocess.TimeoutExpired("git", 0.5),
        ):
            info = runtime_probe(Path.cwd())
        self.assertIsNone(info["git"]["commit"])
        self.assertEqual(info["git"]["provenance"], "unavailable")


if __name__ == "__main__":
    unittest.main()
