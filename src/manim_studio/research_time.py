"""Explicit human time accounting. Never infer effort from gaps between messages."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from manim_studio.research import ResearchLog, _json
from manim_studio.research_sessions import ResearchSessionError, collection_epoch

ACTIONS = (
    "status",
    "history",
    "start",
    "pause",
    "stop",
    "transfer",
    "heartbeat",
    "report",
    "correct",
    "void",
    "observe_context",
    "contexts",
)
CATEGORIES = ("authoring", "classification", "waiting")
PROCESS_TOKEN = str(uuid.uuid4())
LEASE_SECONDS = 45
HEARTBEAT_SECONDS = 15


def fail(code):
    raise ResearchSessionError(code)


def identifier(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        fail("invalid_identifier")
    return value


def seconds(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 366 * 86400
    ):
        fail("invalid_duration")
    return float(value)


def timestamp(value):
    if not isinstance(value, str):
        fail("invalid_timestamp")
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            fail("invalid_timestamp")
        return parsed.astimezone(UTC).timestamp()
    except (ValueError, OverflowError) as exc:
        raise ResearchSessionError("invalid_timestamp") from exc


class Clock:
    token = PROCESS_TOKEN

    def monotonic(self):
        return time.monotonic()

    def wall(self):
        return time.time()

    def utc(self):
        return datetime.fromtimestamp(self.wall(), UTC).isoformat()


class ResearchTiming:
    def __init__(self, root, clock=None):
        self.log = ResearchLog(Path(root))
        self.clock = clock or Clock()

    def _session(self, db, session, active=False):
        identifier(session)
        row = db.execute(
            "SELECT payload FROM events WHERE id=? AND type='session.started'",
            (session,),
        ).fetchone()
        if not row:
            fail("session_not_found")
        lifecycle = db.execute(
            "SELECT state FROM research_sessions WHERE session_id=?", (session,)
        ).fetchone()
        enabled = db.execute("SELECT value FROM config WHERE key='enabled'").fetchone()
        can_capture = bool(
            enabled
            and enabled[0] == "true"
            and (not lifecycle or lifecycle[0] == "active")
        )
        if active:
            if not enabled or enabled[0] != "true":
                fail("capture_disabled")
            collection_epoch(db, session)
        return {
            "title": json.loads(row[0]).get("label", session),
            "can_capture": can_capture,
            "state": lifecycle[0] if lifecycle else "legacy",
        }

    def _state(self, db):
        row = db.execute("SELECT * FROM timing_state WHERE id=1").fetchone()
        if not row:
            db.execute(
                "INSERT INTO timing_state VALUES (1,?,0,NULL)", (str(uuid.uuid4()),)
            )
            row = db.execute("SELECT * FROM timing_state WHERE id=1").fetchone()
        return dict(row)

    def _interval(self, db, id, session=None):
        row = db.execute("SELECT * FROM timing_intervals WHERE id=?", (id,)).fetchone()
        if not row or session and row["session_id"] != session:
            fail("interval_not_found")
        return dict(
            json.loads(row["payload"]), revision=row["revision"], status=row["status"]
        )

    def _active(self, db):
        state = self._state(db)
        return (
            self._interval(db, state["active_interval_id"])
            if state["active_interval_id"]
            else None
        )

    def _save(self, db, data):
        data = dict(data)
        revision = data.pop("revision", 0) + 1
        db.execute(
            "INSERT OR REPLACE INTO timing_intervals VALUES (?,?,?,?,?,?)",
            (
                data["interval_id"],
                data["session_id"],
                data["participant_id"],
                data["status"],
                revision,
                _json(data),
            ),
        )
        return dict(data, revision=revision)

    def _event(self, db, data, kind, extra=None):
        return self.log._event(
            db,
            kind,
            data["session_id"],
            dict(data, **(extra or {})),
            prompt_id=data.get("prompt_id"),
        )

    def _expire(self, db, client=None):
        active = self._active(db)
        if not active:
            return
        same = active["process_token"] == self.clock.token
        gap = (
            self.clock.monotonic() - active["last_monotonic"]
            if same
            else self.clock.wall() - active["last_wall"]
        )
        restarted = bool(client and client == active["client_id"] and not same)
        if restarted or gap < 0 or gap > LEASE_SECONDS:
            reason = (
                "process_restarted"
                if restarted
                else "lease_expired"
                if gap >= 0
                else "clock_reset"
            )
            return self._close(db, active, "interrupted", reason, measure=False)

    def _checkpoint(self, db, data):
        if data["process_token"] != self.clock.token:
            fail("timer_owner_mismatch")
        mono = self.clock.monotonic()
        wall = self.clock.wall()
        delta = mono - data["last_monotonic"]
        wall_delta = wall - data["last_wall"]
        if delta < 0 or delta > LEASE_SECONDS or wall_delta > LEASE_SECONDS:
            return self._close(
                db, data, "interrupted", "unconfirmed_gap", measure=False
            )
        if wall_delta < 0 or abs(wall_delta - delta) > 5:
            data["clock_anomaly"] = True
        data.update(
            measured_seconds=data["measured_seconds"] + delta,
            last_monotonic=mono,
            last_wall=wall,
            confirmed_end_utc=self.clock.utc(),
            sequence=data["sequence"] + 1,
        )
        data = self._save(db, data)
        self._event(db, data, "time.interval.checkpointed", {"delta_seconds": delta})
        return data

    def _close(self, db, data, status, reason, measure=False):
        if measure:
            data = self._checkpoint(db, data)
            if data["status"] != "active":
                return data
        data.update(
            status=status,
            end_utc=data["confirmed_end_utc"],
            close_reason=reason,
            tail_unknown=not measure or data.get("clock_anomaly", False),
        )
        data = self._save(db, data)
        db.execute(
            "UPDATE timing_state SET revision=revision+1,active_interval_id=NULL WHERE id=1"
        )
        self._event(
            db,
            data,
            "time.interval.interrupted"
            if status == "interrupted"
            else "time.interval.stopped",
        )
        return data

    def _revision(self, db, p):
        state = self._state(db)
        if (
            type(p.get("expected_revision")) is not int
            or p["expected_revision"] != state["revision"]
        ):
            fail("timing_conflict")
        return state

    def dispatch(self, action, p):
        if action not in ACTIONS or not isinstance(p, dict):
            fail("invalid_request")
        if not self.log.database.exists():
            fail("session_not_found")
        probe = None
        if action in ("observe_context", "start", "transfer"):
            from manim_studio.research_context import runtime_probe

            probe = runtime_probe(self.log.root)
        try:
            with self.log.connection(timeout=1) as db:
                db.execute("BEGIN IMMEDIATE")
                session = p.get("session_id")
                self._session(db, session)
                project = db.execute(
                    "SELECT value FROM config WHERE key='project_id'"
                ).fetchone()[0]
                if p.get("project_id", project) != project:
                    fail("project_mismatch")
                self._state(db)
                if action not in ("status", "history", "contexts"):
                    request = identifier(p.get("request_id"))
                    fingerprint = hashlib.sha256(
                        json.dumps(
                            {"action": "timing." + action, "payload": p},
                            sort_keys=True,
                            allow_nan=False,
                        ).encode()
                    ).hexdigest()
                    old = db.execute(
                        "SELECT * FROM research_requests WHERE request_id=?", (request,)
                    ).fetchone()
                    if old:
                        if old["fingerprint"] != fingerprint:
                            fail("request_id_conflict")
                        return json.loads(old["result"])
                if self._expire(db, p.get("client_id")):
                    db.commit()
                    db.execute("BEGIN IMMEDIATE")
                if action == "status":
                    return self.status(db, session, p.get("client_id"))
                if action == "history":
                    return {
                        "events": [
                            dict(row, payload=json.loads(row["payload"]))
                            for row in db.execute(
                                "SELECT * FROM events WHERE session_id=? AND (type LIKE 'time.%' OR type='run.context.observed') ORDER BY seq",
                                (session,),
                            )
                        ]
                    }
                if action == "contexts":
                    return {
                        "contexts": [
                            dict(context_id=row["id"], **json.loads(row["payload"]))
                            for row in db.execute(
                                "SELECT * FROM run_contexts WHERE session_id=? ORDER BY rowid",
                                (session,),
                            )
                        ]
                    }
                result = self._mutate(db, action, p, probe)
                db.execute(
                    "INSERT INTO research_requests VALUES (?,?,?)",
                    (request, fingerprint, _json(result)),
                )
                return result
        except (sqlite3.Error, OSError) as exc:
            raise ResearchSessionError(
                "storage_error",
                "Time data was not confirmed; retry the original request.",
            ) from exc

    def _mutate(self, db, action, p, probe):
        session = p["session_id"]
        if action == "observe_context":
            self._session(db, session, active=True)
            from manim_studio.research_context import record_context

            id = record_context(
                self.log,
                db,
                session,
                p.get("client_id"),
                runtime=probe,
                model=p.get("model"),
                settings=p.get("settings"),
                extension_version=p.get("extension_version"),
            )
            return {"context_id": id}
        if action in ("report", "correct", "void"):
            return self._report(db, action, p)
        client = identifier(p.get("client_id"))
        if action == "start":
            self._session(db, session, active=True)
            if self._active(db):
                fail("timer_already_running")
            self._revision(db, p)
            return self._start(db, p, probe)
        active = self._active(db)
        if (
            not active
            or active["interval_id"] != p.get("interval_id")
            or active["session_id"] != session
        ):
            fail("timer_not_active")
        if action == "heartbeat":
            self._session(db, session, active=True)
            if (
                active["client_id"] != client
                or active["process_token"] != self.clock.token
            ):
                fail("timer_owner_mismatch")
            if (
                type(p.get("sequence")) is not int
                or p["sequence"] != active["sequence"] + 1
            ):
                fail("heartbeat_sequence_conflict")
            self._checkpoint(db, active)
            return self.status(db, session, client)
        self._revision(db, p)
        if action == "transfer":
            target = p.get("target_session_id", session)
            self._session(db, target, active=True)
            category = p.get("category")
            if category not in ("authoring", "classification"):
                fail("invalid_category")
            own = (
                active["client_id"] == client
                and active["process_token"] == self.clock.token
            )
            self._close(
                db,
                active,
                "stopped" if own else "interrupted",
                "explicit_transfer",
                measure=own,
            )
            return self._start(db, dict(p, session_id=target), probe)
        if action in ("pause", "stop"):
            own = (
                active["client_id"] == client
                and active["process_token"] == self.clock.token
            )
            self._close(
                db,
                active,
                "paused"
                if own and action == "pause"
                else "stopped"
                if own
                else "interrupted",
                "explicit_" + action,
                measure=own,
            )
            return self.status(db, session, client)
        fail("invalid_request")

    def _start(self, db, p, probe=None):
        category = p.get("category", "authoring")
        if category not in ("authoring", "classification"):
            fail("invalid_category")
        session = p["session_id"]
        state = self._state(db)
        for field, kind in (
            ("prompt_id", "prompt.recorded"),
            ("action_id", "action.started"),
        ):
            value = p.get(field)
            if (
                value is not None
                and not db.execute(
                    "SELECT 1 FROM events WHERE id=? AND session_id=? AND type=?",
                    (value, session, kind),
                ).fetchone()
            ):
                fail("measurement_link_mismatch")
        data = {
            "interval_id": str(uuid.uuid4()),
            "session_id": session,
            "participant_id": state["participant_id"],
            "category": category,
            "client_id": p["client_id"],
            "process_token": self.clock.token,
            "status": "active",
            "start_utc": self.clock.utc(),
            "confirmed_end_utc": self.clock.utc(),
            "end_utc": None,
            "last_monotonic": self.clock.monotonic(),
            "last_wall": self.clock.wall(),
            "measured_seconds": 0.0,
            "sequence": 0,
            "clock_anomaly": False,
            "tail_unknown": False,
            "evidence": "explicit_timer",
            "prompt_id": p.get("prompt_id"),
            "action_id": p.get("action_id"),
        }
        from manim_studio.research_context import record_context

        data["run_context_id"] = record_context(
            self.log,
            db,
            session,
            p["client_id"],
            runtime=probe,
            extension_version=p.get("extension_version"),
        )
        data = self._save(db, data)
        db.execute(
            "UPDATE timing_state SET revision=revision+1,active_interval_id=? WHERE id=1",
            (data["interval_id"],),
        )
        self._event(db, data, "time.interval.started")
        return self.status(db, session, p["client_id"])

    def _report(self, db, action, p):
        session = p["session_id"]
        id = p.get("report_id")
        if action in ("correct", "void"):
            row = db.execute(
                "SELECT * FROM timing_reports WHERE id=? AND session_id=?",
                (id, session),
            ).fetchone()
            if not row:
                fail("report_not_found")
            if (
                type(p.get("expected_revision")) is not int
                or p["expected_revision"] != row["revision"]
            ):
                fail("report_conflict")
            previous = json.loads(row["payload"])
            revision = row["revision"] + 1
        else:
            previous = None
            revision = 1
            id = str(uuid.uuid4())
        category = p.get(
            "category", previous.get("category") if previous else "authoring"
        )
        if category not in CATEGORIES:
            fail("invalid_category")
        value = seconds(p.get("seconds", previous.get("seconds") if previous else None))
        start = p.get("start_utc", previous.get("start_utc") if previous else None)
        end = p.get("end_utc", previous.get("end_utc") if previous else None)
        if (start is None) != (end is None):
            fail("invalid_time_range")
        if start is not None and (
            timestamp(end) < timestamp(start)
            or value > timestamp(end) - timestamp(start)
        ):
            fail("invalid_time_range")
        ref = p.get(
            "measurement_ref", previous.get("measurement_ref") if previous else None
        )
        replacement = p.get(
            "replaces_interval_id",
            previous.get("replaces_interval_id") if previous else None,
        )
        if ref is not None:
            identifier(ref)
            event = db.execute(
                "SELECT * FROM events WHERE id=? AND session_id=? AND type='classification.confirmed'",
                (ref, session),
            ).fetchone()
            if (
                not event
                or category != "classification"
                or json.loads(event["payload"]).get("human_seconds") is None
            ):
                fail("invalid_measurement_ref")
        if replacement is not None:
            identifier(replacement)
            interval = self._interval(db, replacement, session)
            if interval["status"] == "active":
                fail("interval_still_active")
            expected = p.get("expected_interval_revision")
            if type(expected) is not int or expected != interval["revision"]:
                fail("timing_conflict")
            if category != interval["category"]:
                fail("invalid_category")
        existing = [
            json.loads(row[0])
            for row in db.execute(
                "SELECT payload FROM timing_reports WHERE session_id=? AND id!=?",
                (session, id),
            )
        ]
        if action != "void" and any(
            not r["voided"]
            and (
                ref
                and r.get("measurement_ref") == ref
                or replacement
                and r.get("replaces_interval_id") == replacement
            )
            for r in existing
        ):
            fail("measurement_already_reported")
        data = {
            "report_id": id,
            "session_id": session,
            "category": category,
            "seconds": value,
            "start_utc": start,
            "end_utc": end,
            "evidence": "self_report",
            "retrospective": True,
            "measurement_ref": ref,
            "replaces_interval_id": replacement,
            "voided": action == "void",
            "revision": revision,
            "previous_revision": revision - 1 if previous else None,
        }
        event = self.log._event(
            db,
            "time.voided"
            if action == "void"
            else "time.corrected"
            if previous
            else "time.reported",
            session,
            data,
            actor="human",
        )
        data["event_id"] = event
        db.execute(
            "INSERT OR REPLACE INTO timing_reports VALUES (?,?,?,?)",
            (id, session, revision, _json(data)),
        )
        return {"report": data}

    def status(self, db, session, client=None):
        state = self._state(db)
        active = self._active(db)
        metadata = self._session(db, session)
        intervals = [
            self._interval(db, row[0])
            for row in db.execute(
                "SELECT id FROM timing_intervals WHERE session_id=? ORDER BY rowid",
                (session,),
            )
        ]
        reports = [
            json.loads(row[0])
            for row in db.execute(
                "SELECT payload FROM timing_reports WHERE session_id=? ORDER BY rowid",
                (session,),
            )
        ]
        events = [
            dict(row, payload=json.loads(row["payload"]))
            for row in db.execute(
                "SELECT * FROM events WHERE session_id=? ORDER BY seq", (session,)
            )
        ]
        if active:
            active = dict(
                active,
                owned=active["client_id"] == client
                and active["process_token"] == self.clock.token,
                title=self._session(db, active["session_id"])["title"],
            )
        project = db.execute(
            "SELECT value FROM config WHERE key='project_id'"
        ).fetchone()[0]
        return dict(
            session_id=session,
            project_id=project,
            participant_id=state["participant_id"],
            revision=state["revision"],
            active=active,
            intervals=intervals,
            reports=reports,
            summary=summarize(intervals, reports, events),
            heartbeat_seconds=HEARTBEAT_SECONDS,
            lease_seconds=LEASE_SECONDS,
            **metadata,
        )


def close_session_timers(log, db, session=None, reason="research_boundary"):
    """Called inside the lifecycle/configuration transaction; never use another owner's clock."""
    service = ResearchTiming(log.root)
    row = db.execute(
        "SELECT id FROM timing_intervals WHERE status='active'"
        + (" AND session_id=?" if session else ""),
        (session,) if session else (),
    ).fetchone()
    if row:
        data = service._interval(db, row[0])
        service._close(
            db,
            data,
            "stopped"
            if data["process_token"] == service.clock.token
            else "interrupted",
            reason,
            measure=data["process_token"] == service.clock.token,
        )


def union_seconds(ranges):
    total = 0.0
    end = None
    for start, finish in sorted(ranges):
        if end is None or start > end:
            total += finish - start
            end = finish
        elif finish > end:
            total += finish - end
            end = finish
    return total


def summarize(intervals, reports, events):
    """Versioned accounting: separate measurement families, never add them together."""
    valid = [r for r in reports if not r["voided"]]
    replaced = {
        r["replaces_interval_id"] for r in valid if r.get("replaces_interval_id")
    }
    tracked = {
        c: sum(
            i["measured_seconds"]
            for i in intervals
            if i["category"] == c and i["interval_id"] not in replaced
        )
        for c in ("authoring", "classification")
    }
    canonical = {
        c: sum(
            i["measured_seconds"]
            for i in intervals
            if i["category"] == c
            and i["interval_id"] not in replaced
            and not i["clock_anomaly"]
        )
        for c in ("authoring", "classification")
    }
    warnings = []
    raw = {
        c: sum(r["seconds"] for r in valid if r["category"] == c) for c in CATEGORIES
    }
    if any(i["tail_unknown"] for i in intervals):
        warnings.append("unconfirmed_timer_tail")
    if any(i["clock_anomaly"] for i in intervals):
        warnings.append("clock_anomaly")
    ranges = []
    for r in valid:
        if r["start_utc"]:
            ranges.append(
                (timestamp(r["start_utc"]), timestamp(r["end_utc"]), r["report_id"])
            )
        else:
            warnings.append("report_without_range")
    for index, (start, end, id) in enumerate(ranges):
        if any(
            other != id and min(end, finish) > max(start, begin)
            for begin, finish, other in ranges[:index]
        ):
            warnings.append("overlapping_reports")
        if any(
            not i["clock_anomaly"]
            and i["interval_id"]
            != next(
                (r.get("replaces_interval_id") for r in valid if r["report_id"] == id),
                None,
            )
            and min(end, timestamp(i["confirmed_end_utc"]))
            > max(start, timestamp(i["start_utc"]))
            for i in intervals
        ):
            warnings.append("report_overlaps_timer")
    classifications = []
    for e in events:
        if (
            e["type"] == "classification.confirmed"
            and e["actor"] == "human"
            and e["payload"].get("human_seconds") is not None
        ):
            value = e["payload"]["human_seconds"]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                warnings.append("invalid_classification_time")
                continue
            classifications.append((e["id"], float(value)))
    refs = {r["measurement_ref"] for r in valid if r.get("measurement_ref")}
    legacy = sum(s for ref, s in classifications if ref not in refs)
    for index, i in enumerate(intervals):
        if i["clock_anomaly"] or i["interval_id"] in replaced:
            continue
        a, b = timestamp(i["start_utc"]), timestamp(i["confirmed_end_utc"])
        if any(
            not j["clock_anomaly"]
            and j["interval_id"] not in replaced
            and min(b, timestamp(j["confirmed_end_utc"]))
            > max(a, timestamp(j["start_utc"]))
            for j in intervals[:index]
        ):
            warnings.append("overlapping_tracked_intervals")
            canonical = {c: None for c in canonical}
    families = {}
    starts = {e["id"]: e for e in events if e["type"] == "action.started"}
    for family in ("tool", "render"):
        durations = []
        spans = []
        missing = 0
        seen = set()
        for e in events:
            if e["type"] != "action.finished":
                continue
            start = starts.get(e["parent_id"])
            name = start["payload"].get("name", "") if start else ""
            if family == "render" and "render" not in name:
                continue
            value = e["payload"].get("duration_seconds")
            if (
                not start
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                missing += 1
                continue
            if e["parent_id"] in seen:
                warnings.append("duplicate_action_completion")
                continue
            seen.add(e["parent_id"])
            durations.append(value)
            a, b = timestamp(start["timestamp"]), timestamp(e["timestamp"])
            if b >= a and abs((b - a) - value) < 5:
                spans.append((a, b))
            else:
                missing += 1
        finished_parents = {
            e["parent_id"] for e in events if e["type"] == "action.finished"
        }
        missing += sum(
            1
            for id, start in starts.items()
            if id not in finished_parents
            and (family == "tool" or "render" in start["payload"].get("name", ""))
        )
        families[family] = {
            "raw_seconds": sum(durations) if durations else None,
            "union_seconds": union_seconds(spans) if spans and not missing else None,
            "incomplete": missing,
            "observed_actions": len(durations),
        }
    # Pair explicit turn boundaries from the same client/thread/turn, not prompt gaps.
    turns = {}
    turn_spans = []
    turn_missing = 0
    for e in events:
        source = e["payload"].get("source") or {}
        turn = source.get("turn_id")
        thread = source.get("thread_id")
        key = (source.get("client_id") or source.get("client"), thread, turn)
        if not thread or not turn:
            continue
        if (
            e["type"] in ("client.turn.started", "client.turn.submitted")
            or e["type"] == "prompt.recorded"
            and source.get("hook") == "UserPromptSubmit"
        ):
            turns.setdefault(key, timestamp(e["timestamp"]))
        elif e["type"] in ("client.turn.completed", "client.turn.interrupted"):
            start = turns.pop(key, None)
            end = timestamp(e["timestamp"])
            if start is not None and end >= start:
                turn_spans.append((start, end))
            else:
                turn_missing += 1
    families["model_turn"] = {
        "union_seconds": union_seconds(turn_spans) if turn_spans else None,
        "incomplete": turn_missing + len(turns),
        "evidence": "client_observed_turn_not_gpu_time",
    }
    session_start = next(
        (e["timestamp"] for e in events if e["type"] == "session.started"), None
    )
    session_end = next(
        (e["timestamp"] for e in reversed(events) if e["type"] == "session.finished"),
        None,
    )
    wall_span = (
        timestamp(session_end) - timestamp(session_start)
        if session_start and session_end
        else None
    )
    if wall_span is not None and wall_span < 0:
        warnings.append("clock_anomaly")
        wall_span = None
    return {
        "aggregation_version": 1,
        "tracked_seconds": tracked,
        "canonical_tracked_seconds": canonical,
        "self_reported_seconds": raw,
        "legacy_classification_self_report_seconds": legacy,
        "classification_measurements": [
            {"measurement_ref": id, "seconds": s, "overridden": id in refs}
            for id, s in classifications
        ],
        "system": families,
        "research_wall_seconds": wall_span,
        "warnings": sorted(set(warnings)),
        "human_time_missing": not intervals and not valid and not classifications,
        "canonical_note": "Only confirmed tracked checkpoints; manual reports stay separate. Families overlap and must not be added.",
    }
