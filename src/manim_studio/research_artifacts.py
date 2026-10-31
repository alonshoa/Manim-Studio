"""Research evidence archive. No model calls or authoring side effects."""

from __future__ import annotations

import contextvars
import functools
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
import warnings
from pathlib import Path

from manim_studio.research import ResearchLog, _json
from manim_studio.research_files import (
    TEXT_TYPES,
    candidates,
    open_project_file,
    read_project_file,
    relative_path,
)
from manim_studio.research_sessions import ResearchSessionError, collection_epoch

ACTIONS = (
    "list",
    "get",
    "history",
    "policy",
    "preview_scope",
    "checkpoint",
    "configure",
    "purge",
    "job_status",
    "presented",
    "presented_build",
    "content",
    "retry_jobs",
)
DEFAULT_POLICY = {
    "paths": [],
    "file_bytes": 1_000_000,
    "snapshot_bytes": 10_000_000,
    "max_files": 500,
    "video_bytes": 100 * 1024**2,
    "log_bytes": 5 * 1024**2,
    "session_bytes": 2 * 1024**3,
    "project_bytes": 10 * 1024**3,
}
CAPTURE = contextvars.ContextVar("research_evidence_context", default=None)
TRANSITION = contextvars.ContextVar("research_evidence_transition", default=None)
_worker = {}


def fail(code):
    raise ResearchSessionError(code)


def digest(content):
    return hashlib.sha256(content).hexdigest()


def stamp(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def quiet(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - collection must preserve authoring results
        warnings.warn(
            f"Research evidence unavailable ({type(exc).__name__}); authoring continues.",
            RuntimeWarning,
        )
        return None


class ResearchArtifacts:
    def __init__(self, root):
        self.log = ResearchLog(root)
        self.root = self.log.root
        self.store = self.log.directory / "artifacts"

    def _session(self, db, session_id, active=False):
        if (
            not isinstance(session_id, str)
            or not db.execute(
                "SELECT 1 FROM events WHERE id=? AND type='session.started'",
                (session_id,),
            ).fetchone()
        ):
            fail("session_not_found")
        if active:
            enabled = db.execute(
                "SELECT value FROM config WHERE key='enabled'"
            ).fetchone()
            if not enabled or enabled[0] != "true":
                fail("capture_disabled")
            global_epoch = db.execute(
                "SELECT value FROM config WHERE key='capture_epoch'"
            ).fetchone()
            epoch = [
                global_epoch[0] if global_epoch else "0",
                collection_epoch(db, session_id),
            ]
            context = CAPTURE.get()
            if (
                context
                and context.get("session_id") == session_id
                and "epoch" in context
                and context["epoch"] != epoch
            ):
                fail("capture_boundary_changed")
            return epoch

    def _project(self, db):
        row = db.execute("SELECT value FROM config WHERE key='project_id'").fetchone()
        return row[0] if row else None

    def _event(self, db, session_id, kind, payload, prompt_id=None):
        return self.log._event(db, kind, session_id, payload, prompt_id=prompt_id)

    def policy(self, db, session_id):
        project = db.execute(
            "SELECT * FROM artifact_policies WHERE scope='project'"
        ).fetchone()
        specific = db.execute(
            "SELECT * FROM artifact_policies WHERE scope=?", (session_id,)
        ).fetchone()
        effective = specific or project
        return {
            "values": json.loads(effective["payload"])
            if effective
            else dict(DEFAULT_POLICY),
            "revision": specific["revision"] if specific else 0,
            "project_revision": project["revision"] if project else 0,
            "source": "session" if specific else "project" if project else "default",
        }

    def _validate_policy(self, values):
        if not isinstance(values, dict) or set(values) != set(DEFAULT_POLICY):
            fail("invalid_policy")
        paths = values["paths"]
        if not isinstance(paths, list) or len(paths) > 30:
            fail("invalid_policy")
        for value in paths:
            relative_path(value)
            if (self.root / value).suffix and Path(
                value
            ).suffix.lower() not in TEXT_TYPES:
                fail("invalid_policy")
        for key in DEFAULT_POLICY:
            if key != "paths" and (
                type(values[key]) is not int or not 1 <= values[key] <= 100 * 1024**3
            ):
                fail("invalid_policy")
        if (
            values["max_files"] > 500
            or values["file_bytes"] > 1_000_000
            or values["snapshot_bytes"] > 10_000_000
        ):
            fail("invalid_policy")
        if values["video_bytes"] > 100 * 1024**2 or values["log_bytes"] > 5 * 1024**2:
            fail("invalid_policy")
        return values

    def dispatch(self, action, payload):
        if action not in ACTIONS or not isinstance(payload, dict):
            fail("invalid_request")
        if not self.log.database.exists():
            fail("session_not_found")
        try:
            with self.log.connection(timeout=1) as db:
                mutation = action in (
                    "checkpoint",
                    "configure",
                    "purge",
                    "presented",
                    "presented_build",
                    "retry_jobs",
                )
                db.execute("BEGIN IMMEDIATE" if mutation else "BEGIN")
                session = payload.get("session_id")
                self._session(db, session)
                if payload.get("project_id", self._project(db)) != self._project(db):
                    fail("project_mismatch")
                if not mutation:
                    return self._read(db, action, payload)
                request = payload.get("request_id")
                if (
                    not isinstance(request, str)
                    or not request.strip()
                    or len(request) > 512
                ):
                    fail("request_id_required")
                # Canonical JSON is shared by UI and direct callers.
                fingerprint = digest(
                    json.dumps(
                        {"action": "artifacts." + action, "payload": payload},
                        sort_keys=True,
                        allow_nan=False,
                    ).encode()
                )
                old = db.execute(
                    "SELECT * FROM research_requests WHERE request_id=?", (request,)
                ).fetchone()
                if old:
                    if old["fingerprint"] != fingerprint:
                        fail("request_id_conflict")
                    return json.loads(old["result"])
                result = self._mutate(db, action, payload)
                db.execute(
                    "INSERT INTO research_requests VALUES (?,?,?)",
                    (request, fingerprint, _json(result)),
                )
                return result
        except (sqlite3.Error, OSError) as exc:
            raise ResearchSessionError(
                "storage_error", "Research evidence storage is unavailable."
            ) from exc

    def _artifact(self, db, session, artifact_id):
        row = db.execute(
            "SELECT * FROM research_artifacts WHERE id=? AND session_id=?",
            (artifact_id, session),
        ).fetchone()
        if not row:
            fail("artifact_not_found")
        return dict(json.loads(row["payload"]), revision=row["revision"])

    def _read(self, db, action, p):
        session = p["session_id"]
        if action == "policy":
            return dict(project_id=self._project(db), **self.policy(db, session))
        if action == "preview_scope":
            values = (
                self._validate_policy(p["values"])
                if "values" in p
                else self.policy(db, session)["values"]
            )
            paths, omitted = candidates(self.root, values["paths"], values["max_files"])
            return {"paths": paths, "omitted": omitted, "values": values}
        if action == "list":
            limit, offset = p.get("limit", 100), p.get("offset", 0)
            if (
                type(limit) is not int
                or not 1 <= limit <= 100
                or type(offset) is not int
                or offset < 0
            ):
                fail("invalid_request")
            rows = db.execute(
                "SELECT * FROM research_artifacts WHERE session_id=? ORDER BY rowid",
                (session,),
            ).fetchall()
            artifacts = [
                dict(json.loads(r["payload"]), revision=r["revision"]) for r in rows
            ]
            decisions = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload FROM research_decisions WHERE session_id=? ORDER BY rowid",
                    (session,),
                )
            ]
            for decision in decisions:
                decision.pop("result", None)
            snapshots = [
                dict(snapshot_id=r[0], **json.loads(r[1]))
                for r in db.execute(
                    "SELECT id,payload FROM artifact_snapshots WHERE session_id=? ORDER BY rowid DESC LIMIT 30",
                    (session,),
                )
            ]
            jobs = [
                {"job_id": r[0], "status": r[1]}
                for r in db.execute(
                    "SELECT id,status FROM artifact_jobs WHERE session_id=? ORDER BY rowid DESC LIMIT 100",
                    (session,),
                )
            ]
            lifecycle = db.execute(
                "SELECT state FROM research_sessions WHERE session_id=?", (session,)
            ).fetchone()
            enabled = db.execute(
                "SELECT value FROM config WHERE key='enabled'"
            ).fetchone()
            return {
                "session_title": json.loads(
                    db.execute(
                        "SELECT payload FROM events WHERE id=?", (session,)
                    ).fetchone()[0]
                ).get("label", session),
                "can_capture": bool(
                    enabled
                    and enabled[0] == "true"
                    and (not lifecycle or lifecycle[0] == "active")
                ),
                "project_id": self._project(db),
                "session_id": session,
                "artifacts": artifacts[offset : offset + limit],
                "next_offset": offset + limit
                if offset + limit < len(artifacts)
                else None,
                "offset": offset,
                "total": len(artifacts),
                "decisions": decisions,
                "snapshots": snapshots,
                "jobs": jobs,
                "policy": self.policy(db, session),
                "coverage": "partial"
                if any(a["status"] not in ("retained", "pending") for a in artifacts)
                else "unverified",
                "caveat": "External edits and client delivery are not continuously verified.",
            }
        if action == "job_status":
            row = db.execute(
                "SELECT * FROM artifact_jobs WHERE id=? AND session_id=?",
                (p.get("job_id"), session),
            ).fetchone()
            if not row:
                fail("job_not_found")
            return {
                "job_id": row["id"],
                "status": row["status"],
                "details": json.loads(row["payload"]),
            }
        if action == "history":
            artifact = (
                self._artifact(db, session, p.get("artifact_id"))
                if p.get("artifact_id")
                else None
            )
            rows = db.execute(
                "SELECT * FROM events WHERE session_id=? AND (type LIKE 'artifact.%' OR type LIKE 'decision.%' OR type LIKE 'snapshot.%' OR type='coverage.observed') ORDER BY seq",
                (session,),
            )
            events = [dict(r, payload=json.loads(r["payload"])) for r in rows]
            return {
                "events": [
                    e
                    for e in events
                    if not artifact
                    or e["payload"].get("artifact_id") == artifact["artifact_id"]
                ]
            }
        artifact = self._artifact(db, session, p.get("artifact_id"))
        if action == "content":
            if artifact["status"] != "retained":
                fail("artifact_unavailable")
            if artifact["role"] in ("preview_video", "final_product", "render_image"):
                # A validated immutable archive path; never caller-provided paths.
                path = self._content_path(artifact["sha256"])
                self._verify_content(path, artifact["sha256"], artifact["size"])
                views = self.store / "views"
                if views.exists() and (
                    views.is_symlink()
                    or getattr(views.lstat(), "st_file_attributes", 0) & 0x400
                ):
                    fail("unsafe_archive")
                views.mkdir(exist_ok=True)
                extension = Path(artifact["path"]).suffix.lower()
                if extension not in (".mp4", ".webm", ".pptx", ".html", ".png", ".svg"):
                    fail("unsupported_artifact")
                view = views / (artifact["artifact_id"] + extension)
                try:
                    os.link(path, view)
                except FileExistsError:
                    fd = open_project_file(
                        self.root, view.relative_to(self.root).as_posix(), internal=True
                    )
                    try:
                        if os.fstat(fd).st_ino != path.stat().st_ino:
                            fail("unsafe_archive")
                    finally:
                        os.close(fd)
                return {"path": str(view), "artifact": artifact}
            content = self._read_content(artifact["sha256"], artifact["size"])
            return {
                "text": content.decode("utf-8", errors="replace"),
                "artifact": artifact,
            }
        return {"artifact": artifact, "project_id": self._project(db)}

    def _mutate(self, db, action, p):
        session = p["session_id"]
        if action == "checkpoint":
            self._session(db, session, active=True)
            return self.checkpoint(db, session, reason="manual")
        if action == "configure":
            values = self._validate_policy(p.get("values"))
            if p.get("scope") not in (None, "session", "project"):
                fail("invalid_request")
            scope = "project" if p.get("scope") == "project" else session
            row = db.execute(
                "SELECT * FROM artifact_policies WHERE scope=?", (scope,)
            ).fetchone()
            revision = row["revision"] if row else 0
            if (
                type(p.get("expected_revision")) is not int
                or p["expected_revision"] != revision
            ):
                fail("policy_conflict")
            db.execute(
                "INSERT OR REPLACE INTO artifact_policies VALUES (?,?,?)",
                (scope, revision + 1, _json(values)),
            )
            self._event(
                db,
                session,
                "artifact.policy_changed",
                {"scope": scope, "revision": revision + 1, "values": values},
            )
            return dict(revision=revision + 1, **self._read(db, "preview_scope", p))
        if action == "retry_jobs":
            changed = 0
            for row in db.execute(
                "SELECT * FROM artifact_jobs WHERE session_id=? AND status='running'",
                (session,),
            ).fetchall():
                data = json.loads(row["payload"])
                if data.get("lease_until", 0) < time.time():
                    db.execute(
                        "UPDATE artifact_jobs SET status='pending' WHERE id=?",
                        (row["id"],),
                    )
                    changed += 1
            return {"requeued": changed}
        if action == "presented_build":
            self._session(db, session, active=True)
            artifacts = [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT payload FROM research_artifacts WHERE session_id=?",
                    (session,),
                )
            ]
            videos = [
                a
                for a in artifacts
                if a.get("build_id") == p.get("build_id")
                and a["role"] == "preview_video"
            ]
            if not videos:
                return {"recorded": False, "reason": "build_not_observed"}
            results = []
            for artifact in videos:
                job = db.execute(
                    "SELECT payload FROM artifact_jobs WHERE json_extract(payload,'$.artifact_id')=?",
                    (artifact["artifact_id"],),
                ).fetchone()
                unchanged = False
                if job:
                    try:
                        fd = open_project_file(self.root, artifact["path"])
                        try:
                            unchanged = (
                                stamp(os.fstat(fd)) == json.loads(job[0])["stamp"]
                            )
                        finally:
                            os.close(fd)
                    except (OSError, ValueError):
                        pass
                verified = unchanged and artifact["status"] == "retained"
                event = self._event(
                    db,
                    session,
                    "artifact.presented"
                    if verified
                    else "artifact.presentation_unverified",
                    {
                        "artifact_id": artifact["artifact_id"],
                        "build_id": p.get("build_id"),
                        "sha256": artifact["sha256"] if verified else None,
                        "evidence": "client_reported_media_loaded",
                        "reason": None
                        if verified
                        else "retention_or_source_not_verified",
                    },
                )
                results.append(event)
            return {"recorded": True, "event_ids": results}
        artifact = self._artifact(db, session, p.get("artifact_id"))
        if action == "presented":
            self._session(db, session, active=True)
            if (
                artifact["status"] != "retained"
                or p.get("sha256") != artifact["sha256"]
            ):
                fail("artifact_revision_conflict")
            event = self._event(
                db,
                session,
                "artifact.presented",
                {
                    "artifact_id": artifact["artifact_id"],
                    "sha256": artifact["sha256"],
                    "evidence": "client_reported_open",
                },
            )
            return {"event_id": event}
        if (
            type(p.get("expected_revision")) is not int
            or artifact["revision"] != p["expected_revision"]
        ):
            fail("artifact_revision_conflict")
        if artifact["status"] == "pending":
            fail("artifact_pending")
        artifact["status"] = "purged"
        self._save_artifact(db, artifact)
        self._event(
            db,
            session,
            "artifact.purged",
            {"artifact_id": artifact["artifact_id"], "sha256": artifact.get("sha256")},
        )
        # Physical garbage is removed separately after commit and only if no retained refs exist.
        return {"artifact": artifact}

    def _content_path(self, sha):
        if (
            not isinstance(sha, str)
            or len(sha) != 64
            or any(c not in "0123456789abcdef" for c in sha)
        ):
            fail("invalid_digest")
        path = self.store / "sha256" / sha[:2] / sha
        for part in (
            self.log.directory.parent,
            self.log.directory,
            self.store,
            self.store / "sha256",
            path.parent,
            path,
        ):
            if part.exists() and (
                part.is_symlink()
                or getattr(part.lstat(), "st_file_attributes", 0) & 0x400
            ):
                fail("unsafe_archive")
        return path

    def _put(self, content):
        sha = digest(content)
        path = self._content_path(sha)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self._verify_content(path, sha, len(content))
            return sha
        fd, tmp = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(tmp, path)
            except FileExistsError:
                self._verify_content(path, sha, len(content))
        finally:
            Path(tmp).unlink(missing_ok=True)
        return sha

    def _verify_content(self, path, sha, size):
        with os.fdopen(
            open_project_file(
                self.root,
                f".manim-studio/research/artifacts/sha256/{sha[:2]}/{sha}",
                internal=True,
            ),
            "rb",
        ) as stream:
            count = 0
            hashed = hashlib.sha256()
            while chunk := stream.read(65536):
                count += len(chunk)
                if count > size:
                    fail("artifact_corrupt")
                hashed.update(chunk)
        if count != size or hashed.hexdigest() != sha:
            fail("artifact_corrupt")

    def _read_content(self, sha, size):
        self._content_path(sha)
        content = read_project_file(
            self.root,
            f".manim-studio/research/artifacts/sha256/{sha[:2]}/{sha}",
            size,
            internal=True,
        )
        if len(content) != size or digest(content) != sha:
            fail("artifact_corrupt")
        return content

    def _quota(self, db, session, sha, size):
        policy = self.policy(db, session)["values"]

        def used(own):
            query = "SELECT json_extract(payload,'$.sha256'), max(json_extract(payload,'$.size')) FROM research_artifacts WHERE json_extract(payload,'$.status')='retained'"
            args = ()
            if own:
                query += " AND session_id=?"
                args = (session,)
            query += " GROUP BY json_extract(payload,'$.sha256')"
            return dict(db.execute(query, args).fetchall())

        project, local = used(False), used(True)
        global_policy = db.execute(
            "SELECT payload FROM artifact_policies WHERE scope='project'"
        ).fetchone()
        project_limit = (
            json.loads(global_policy[0])["project_bytes"]
            if global_policy
            else DEFAULT_POLICY["project_bytes"]
        )
        return (
            sum(project.values()) + (0 if sha in project else size) <= project_limit
            and sum(local.values()) + (0 if sha in local else size)
            <= policy["session_bytes"]
        )

    def _save_artifact(self, db, artifact):
        revision = artifact.pop("revision", 0) + 1
        db.execute(
            "INSERT OR REPLACE INTO research_artifacts VALUES (?,?,?,?)",
            (
                artifact["artifact_id"],
                artifact["session_id"],
                revision,
                _json(artifact),
            ),
        )
        artifact["revision"] = revision

    def retain(self, db, session, path, role, content=None, reason=None, **links):
        artifact = dict(
            artifact_id=str(uuid.uuid4()),
            session_id=session,
            path=path,
            role=role,
            status="unavailable",
            sha256=None,
            size=None,
            **links,
        )
        self._event(db, session, "artifact.observed", artifact)
        if content is not None:
            sha = digest(content)
            artifact.update(sha256=sha, size=len(content))
            if self._quota(db, session, sha, len(content)):
                self._put(content)
                artifact["status"] = "retained"
            else:
                reason = "omitted_quota"
        if reason:
            artifact["reason"] = reason
        self._save_artifact(db, artifact)
        self._event(
            db,
            session,
            "artifact.retained"
            if artifact["status"] == "retained"
            else "artifact.unavailable",
            artifact,
        )
        return dict(artifact)

    def checkpoint(self, db, session, reason="action", prompt_id=None):
        epoch = self._session(db, session, active=True)
        context = CAPTURE.get()
        if context and context.get("session_id") == session:
            context.setdefault("epoch", epoch)
        policy = self.policy(db, session)
        values = policy["values"]
        paths, omitted = candidates(self.root, values["paths"], values["max_files"])
        files = {}
        references = []
        total = 0
        for path in paths:
            try:
                content = read_project_file(
                    self.root,
                    path,
                    min(values["file_bytes"], max(0, values["snapshot_bytes"] - total)),
                )
                total += len(content)
                artifact = self.retain(
                    db,
                    session,
                    path,
                    "planning_document"
                    if Path(path).suffix in {".md", ".yaml", ".yml"}
                    else "source",
                    content,
                )
                references.append(artifact["artifact_id"])
                if artifact["status"] == "retained":
                    files[path] = artifact["sha256"]
                else:
                    omitted.append(
                        {"path": path, "reason": artifact.get("reason", "unavailable")}
                    )
            except (OSError, ValueError) as exc:
                omitted.append(
                    {
                        "path": path,
                        "reason": str(exc)
                        if isinstance(exc, ValueError)
                        else "read_error",
                    }
                )
        previous = db.execute(
            "SELECT payload FROM artifact_snapshots WHERE session_id=? ORDER BY rowid DESC LIMIT 1",
            (session,),
        ).fetchone()
        old = json.loads(previous[0]) if previous else {}
        missing = sorted(
            (set(old.get("files", {})) - set(paths))
            | {
                o["path"]
                for o in omitted
                if o["reason"] == "missing" and o["path"] in old.get("files", {})
            }
        )
        changed = bool(previous and (files != old.get("files") or missing))
        snapshot_id = str(uuid.uuid4())
        payload = {
            "files": files,
            "omitted": omitted,
            "missing": missing,
            "artifact_ids": references,
            "reason": reason,
            "policy": policy,
            "boundary_caveat": "Current state; edit authorship and changes during pauses are unknown.",
            "external_edits_verified": False,
        }
        db.execute(
            "INSERT INTO artifact_snapshots VALUES (?,?,?)",
            (snapshot_id, session, _json(payload)),
        )
        self._event(
            db,
            session,
            "snapshot.recorded",
            dict(snapshot_id=snapshot_id, **payload),
            prompt_id,
        )
        if changed:
            self._event(
                db,
                session,
                "coverage.observed",
                {
                    "snapshot_id": snapshot_id,
                    "reason": "state_changed_between_observations",
                    "actor": "unknown",
                },
            )
        return dict(snapshot_id=snapshot_id, **payload)

    def enqueue_build(self, build_dir, build_id):
        context = CAPTURE.get()
        if not context:
            return
        session = context["session_id"]
        with self.log.connection(timeout=1) as db:
            db.execute("BEGIN IMMEDIATE")
            self._session(db, session, active=True)
            directory = Path(build_dir).relative_to(self.root).as_posix()
            manifest = read_project_file(
                self.root, f"{directory}/manifest.json", 1_000_000
            )
            data = json.loads(manifest)
            if data.get("build_id") != build_id:
                fail("build_mismatch")
            # Only immutable build output directories, never arbitrary manifest paths.
            members = ["manifest.json", "stdout.log", "stderr.log"]
            for entry in data.get("artifacts", []):
                name = entry.get("path")
                if isinstance(name, str) and Path(name).suffix.lower() in (
                    ".mp4",
                    ".webm",
                    ".pptx",
                    ".html",
                    ".png",
                    ".svg",
                    ".srt",
                    ".vtt",
                ):
                    members.append(name)
            for name in dict.fromkeys(members):
                relative_path(name)
                relative = f"{directory}/{name}"
                role = (
                    "build_manifest"
                    if name == "manifest.json"
                    else "render_log"
                    if name.endswith(".log")
                    else "preview_video"
                    if name.endswith((".mp4", ".webm"))
                    else "render_image"
                    if name.endswith((".png", ".svg"))
                    else "render_caption"
                    if name.endswith((".srt", ".vtt"))
                    else "final_product"
                )
                if (
                    db.execute(
                        "SELECT count(*) FROM artifact_jobs WHERE status IN ('pending','running')"
                    ).fetchone()[0]
                    >= 256
                ):
                    self.retain(
                        db,
                        session,
                        relative,
                        role,
                        reason="queue_full",
                        build_id=build_id,
                    )
                    continue
                # Bounded stat/open only. Worker later verifies the exact immutable observation.
                try:
                    fd = open_project_file(self.root, relative)
                    try:
                        observed = stamp(os.fstat(fd))
                    finally:
                        os.close(fd)
                except (OSError, ValueError):
                    self.retain(
                        db,
                        session,
                        relative,
                        role,
                        reason="source_missing",
                        build_id=build_id,
                    )
                    continue
                artifact = {
                    "artifact_id": str(uuid.uuid4()),
                    "session_id": session,
                    "path": relative,
                    "role": role,
                    "status": "pending",
                    "sha256": None,
                    "size": observed[2],
                    "build_id": build_id,
                    "proposal_id": context.get("proposal_id"),
                }
                self._save_artifact(db, artifact)
                self._event(db, session, "artifact.observed", artifact)
                job_id = str(uuid.uuid4())
                policy = self.policy(db, session)["values"]
                limit = (
                    policy["video_bytes"]
                    if role in ("preview_video", "final_product")
                    else policy["log_bytes"]
                )
                job = {
                    "artifact_id": artifact["artifact_id"],
                    "path": relative,
                    "stamp": observed,
                    "limit": limit,
                    "epoch": context.get("epoch"),
                    "lease_until": 0,
                }
                db.execute(
                    "INSERT INTO artifact_jobs VALUES (?,?,?,?)",
                    (job_id, session, "pending", _json(job)),
                )
        kick_worker(self.root)

    def work_once(self):
        with self.log.connection(timeout=1) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM artifact_jobs WHERE status='pending' OR (status='running' AND json_extract(payload,'$.lease_until')<?) ORDER BY rowid LIMIT 1",
                (time.time(),),
            ).fetchone()
            if not row:
                return False
            job = json.loads(row["payload"])
            job["lease_until"] = time.time() + 120
            job["lease_token"] = str(uuid.uuid4())
            db.execute(
                "UPDATE artifact_jobs SET status='running',payload=? WHERE id=?",
                (_json(job), row["id"]),
            )
        content = None
        reason = None
        try:
            fd = open_project_file(self.root, job["path"])
            try:
                if stamp(os.fstat(fd)) != job["stamp"]:
                    raise ValueError("source_changed")
            finally:
                os.close(fd)
            content = read_project_file(self.root, job["path"], job["limit"])
            fd = open_project_file(self.root, job["path"])
            try:
                if stamp(os.fstat(fd)) != job["stamp"]:
                    raise ValueError("source_changed")
            finally:
                os.close(fd)
        except (OSError, ValueError) as exc:
            content = None
            reason = str(exc) if isinstance(exc, ValueError) else "source_missing"
        with self.log.connection(timeout=1) as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT status,payload FROM artifact_jobs WHERE id=?", (row["id"],)
            ).fetchone()
            if (
                current["status"] != "running"
                or json.loads(current["payload"]).get("lease_token")
                != job["lease_token"]
            ):
                return True
            artifact = self._artifact(db, row["session_id"], job["artifact_id"])
            if content is not None:
                sha = digest(content)
                artifact.update(sha256=sha, size=len(content))
                if self._quota(db, row["session_id"], sha, len(content)):
                    self._put(content)
                    artifact["status"] = "retained"
                else:
                    reason = "omitted_quota"
            if reason:
                artifact.update(status="unavailable", reason=reason)
            self._save_artifact(db, artifact)
            self._event(
                db,
                row["session_id"],
                "artifact.retained"
                if artifact["status"] == "retained"
                else "artifact.unavailable",
                artifact,
            )
            db.execute(
                "UPDATE artifact_jobs SET status=? WHERE id=?",
                (
                    "completed" if artifact["status"] == "retained" else "unavailable",
                    row["id"],
                ),
            )
        return True

    def collect_garbage(self):
        # Run explicitly after committed purge; serialize against new refs and workers.
        with self.log.connection(timeout=1) as db:
            db.execute("BEGIN IMMEDIATE")
            retained = {
                json.loads(r[0]).get("sha256")
                for r in db.execute("SELECT payload FROM research_artifacts")
                if json.loads(r[0]).get("status") == "retained"
            }
            for row in db.execute("SELECT payload FROM research_artifacts").fetchall():
                artifact = json.loads(row[0])
                sha = artifact.get("sha256")
                if artifact["status"] == "purged":
                    view = (
                        self.store
                        / "views"
                        / (
                            artifact["artifact_id"]
                            + Path(artifact["path"]).suffix.lower()
                        )
                    )
                    if view.parent.exists() and (
                        view.parent.is_symlink()
                        or getattr(view.parent.lstat(), "st_file_attributes", 0) & 0x400
                    ):
                        fail("unsafe_archive")
                    if view.exists():
                        view.unlink()
                if artifact["status"] == "purged" and sha and sha not in retained:
                    self._content_path(sha).unlink(missing_ok=True)


def kick_worker(root):
    service = ResearchArtifacts(root)
    if not service.log.database.exists():
        return
    with service.log.connection(timeout=1) as db:
        if not db.execute(
            "SELECT 1 FROM artifact_jobs WHERE status='pending' OR (status='running' AND json_extract(payload,'$.lease_until')<?) LIMIT 1",
            (time.time(),),
        ).fetchone():
            return
    key = str(root)
    process = _worker.get(key)
    if process and process.poll() is None:
        return
    _worker[key] = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "manim_studio.research_artifacts",
            "--worker",
            str(root),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=os.name != "nt",
        creationflags=0x00000008 if os.name == "nt" else 0,
    )


def worker_main(root):
    service = ResearchArtifacts(root)
    idle = time.monotonic() + 3
    while time.monotonic() < idle:
        try:
            if service.work_once():
                idle = time.monotonic() + 3
            else:
                time.sleep(0.2)
        except Exception:  # noqa: BLE001 - worker errors retain retryable jobs
            time.sleep(0.5)


def capture_context(root):
    current = CAPTURE.get()
    if current:
        return current if Path(root).resolve() == Path(current["root"]) else None
    session = os.environ.get("MANIM_STUDIO_RESEARCH_SESSION")
    client = os.environ.get("MANIM_STUDIO_RESEARCH_CLIENT")
    if not session and not client:
        return None
    from manim_studio.research_sessions import ResearchSessions

    session, prompt = ResearchSessions(root).resolve(
        session, os.environ.get("MANIM_STUDIO_RESEARCH_PROMPT"), client, "environment"
    )
    if not session:
        return None
    return {
        "root": str(Path(root).resolve()),
        "session_id": session,
        "prompt_id": prompt,
        "client_id": client,
        "origin": "unknown",
    }


def _decision_candidate(service, db, context, builds_root, proposal_id):
    from manim_studio import staged_edits

    metadata = staged_edits.inspect_scene_patch(service.root, builds_root, proposal_id)
    source = staged_edits.proposal_source_path(service.root, builds_root, proposal_id)
    candidate = source.relative_to(service.root).as_posix()
    baseline = relative_path(metadata["source_path"])
    result = {}
    for role, path in (("candidate_source", candidate), ("baseline_source", baseline)):
        try:
            content = read_project_file(service.root, path, 1_000_000)
            artifact = service.retain(
                db, context["session_id"], path, role, content, proposal_id=proposal_id
            )
        except (OSError, ValueError):
            artifact = service.retain(
                db,
                context["session_id"],
                path,
                role,
                reason="source_unavailable",
                proposal_id=proposal_id,
            )
        result[role] = artifact
    return result


def record_prepared_candidate(root, builds_root, proposal_id):
    transition = TRANSITION.get()
    context = CAPTURE.get()
    if not transition or not context:
        return
    context["prepared_evidence_valid"] = False
    service = ResearchArtifacts(root)
    with service.log.connection(timeout=1) as db:
        db.execute("BEGIN IMMEDIATE")
        service._session(db, context["session_id"], active=True)
        candidate = _decision_candidate(service, db, context, builds_root, proposal_id)
        row = db.execute(
            "SELECT payload FROM research_decisions WHERE id=?", (transition,)
        ).fetchone()
        if not row:
            return
        data = json.loads(row[0])
        data.update(candidate=candidate)
        db.execute(
            "UPDATE research_decisions SET payload=? WHERE id=?",
            (_json(data), transition),
        )
        service._event(
            db,
            context["session_id"],
            "decision.candidate_prepared",
            {"decision_id": transition, "candidate": candidate},
        )

    context["prepared_evidence_valid"] = True


class _DecisionLock:
    """Non-generator context manager: preserve even frozen authoring exceptions."""

    def __init__(self, directory):
        self.directory = directory
        self.fd = None

    def __enter__(self):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.fd = os.open(
                self.directory / "decision.lock",
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except OSError:
            warnings.warn(
                "Research decision lock unavailable; evidence may be incomplete.",
                RuntimeWarning,
            )
            return self
        try:
            if os.name == "nt":
                import msvcrt

                if os.fstat(self.fd).st_size == 0:
                    os.write(self.fd, b"0")
                os.lseek(self.fd, 0, 0)
                msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(self.fd)
            self.fd = None
            from manim_studio.staged_edits import StagedEditError

            raise StagedEditError(
                "decision_busy", "Another decision is in progress in this project"
            ) from exc
        return self

    def __exit__(self, kind, error, traceback):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        return False


def decision_lock(directory):
    return _DecisionLock(directory)


def research_transition(kind):
    """Observe once at the outermost core transition, across service/CLI/RPC paths."""

    def decorate(function):
        import inspect

        signature = inspect.signature(function)

        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            values = bound.arguments
            owner = values.get("self")
            root = owner.repo_root if owner else values.get("repo_root")
            if TRANSITION.get():
                return function(*args, **kwargs)
            context = quiet(capture_context, root) if root is not None else None
            if not context:
                return function(*args, **kwargs)
            service = ResearchArtifacts(root)
            with decision_lock(service.log.directory):
                request_id = context.get("request_id")
                fingerprint = digest(
                    json.dumps(
                        {
                            "kind": kind,
                            "arguments": {
                                k: v for k, v in values.items() if k != "self"
                            },
                        },
                        sort_keys=True,
                        default=str,
                    ).encode()
                )
                if request_id:
                    try:
                        with service.log.connection(timeout=1) as lookup:
                            prior = lookup.execute(
                                "SELECT payload FROM research_decisions WHERE json_extract(payload,'$.request_id')=?",
                                (request_id,),
                            ).fetchone()
                            if prior:
                                previous = json.loads(prior[0])
                                if (
                                    previous.get("fingerprint") != fingerprint
                                    or previous.get("session_id")
                                    != context["session_id"]
                                ):
                                    fail("request_id_conflict")
                                if previous["status"] != "completed":
                                    fail("decision_outcome_unknown")
                                return previous.get("result")
                    except (sqlite3.Error, OSError):
                        warnings.warn(
                            "Research receipt storage unavailable; authoring continues without confirmed evidence.",
                            RuntimeWarning,
                        )
                        skip = TRANSITION.set("unrecorded")
                        try:
                            return function(*args, **kwargs)
                        finally:
                            TRANSITION.reset(skip)
                proposal = values.get("proposal_id")
                builds = (
                    owner.builds_root if owner else values.get("builds_root", "builds")
                )
                if not proposal and owner:
                    state = quiet(owner._load_state, values.get("session_id"))
                    proposal = getattr(state, "active_proposal_id", None)
                if not proposal:
                    return function(*args, **kwargs)

                def begin():
                    with service.log.connection(timeout=1) as db:
                        db.execute("BEGIN IMMEDIATE")
                        epoch = service._session(db, context["session_id"], active=True)
                        context.setdefault("epoch", epoch)
                        if request_id:
                            prior = db.execute(
                                "SELECT payload FROM research_decisions WHERE json_extract(payload,'$.request_id')=?",
                                (request_id,),
                            ).fetchone()
                            if prior:
                                previous = json.loads(prior[0])
                                if (
                                    previous.get("fingerprint") != fingerprint
                                    or previous.get("session_id")
                                    != context["session_id"]
                                ):
                                    fail("request_id_conflict")
                                if previous["status"] != "completed":
                                    fail("decision_outcome_unknown")
                                return previous
                        candidate = _decision_candidate(
                            service, db, context, builds, proposal
                        )
                        before = service.checkpoint(
                            db, context["session_id"], reason="before_" + kind
                        )
                        decision = str(uuid.uuid4())
                        data = {
                            "decision_id": decision,
                            "kind": kind,
                            "session_id": context["session_id"],
                            "request_id": request_id,
                            "fingerprint": fingerprint,
                            "proposal_id": proposal,
                            "authoring_session_id": values.get("session_id")
                            if owner
                            else None,
                            "origin": context.get("origin")
                            if context.get("origin") in ("human", "automation")
                            else "unknown",
                            "origin_evidence": context.get("origin_evidence"),
                            "reported_by": context.get("client_id"),
                            "action_id": context.get("action_id"),
                            "prompt_id": context.get("prompt_id"),
                            "candidate": candidate,
                            "status": "outcome_unknown",
                            "before_snapshot_id": before["snapshot_id"],
                            "epoch": epoch,
                        }
                        db.execute(
                            "INSERT INTO research_decisions VALUES (?,?,?)",
                            (decision, context["session_id"], _json(data)),
                        )
                        service._event(
                            db,
                            context["session_id"],
                            "decision.requested",
                            data,
                            context.get("prompt_id"),
                        )
                        return decision

                try:
                    decision = begin()
                except ResearchSessionError as exc:
                    if exc.code in ("request_id_conflict", "decision_outcome_unknown"):
                        raise
                    warnings.warn(
                        "Research decision unavailable; authoring continues.",
                        RuntimeWarning,
                    )
                    decision = None
                except Exception as exc:  # noqa: BLE001 - collection must preserve authoring results
                    warnings.warn(
                        f"Research decision unavailable ({type(exc).__name__}); authoring continues.",
                        RuntimeWarning,
                    )
                    decision = None
                if isinstance(decision, dict):
                    return decision.get("result")
                capture_token = CAPTURE.set(dict(context, proposal_id=proposal))
                token = TRANSITION.set(decision or "unrecorded")
                result = None
                error = None
                try:
                    result = function(*args, **kwargs)
                    return result
                except Exception as exc:
                    error = type(exc).__name__
                    raise
                finally:

                    def finish():
                        with service.log.connection(timeout=1) as db:
                            db.execute("BEGIN IMMEDIATE")
                            epoch = service._session(
                                db, context["session_id"], active=True
                            )
                            row = db.execute(
                                "SELECT payload FROM research_decisions WHERE id=?",
                                (decision,),
                            ).fetchone()
                            data = json.loads(row[0])
                            if epoch != data["epoch"]:
                                return
                            failed = bool(
                                error
                                or isinstance(result, dict)
                                and result.get("ok") is False
                            )
                            after = service.checkpoint(
                                db, context["session_id"], reason="after_" + kind
                            )
                            data.update(
                                status="failed" if failed else "completed",
                                error_type=error,
                                after_snapshot_id=after["snapshot_id"],
                                result=result if not failed else None,
                            )
                            db.execute(
                                "UPDATE research_decisions SET payload=? WHERE id=?",
                                (_json(data), decision),
                            )
                            service._event(
                                db,
                                context["session_id"],
                                "decision.failed" if failed else "decision.completed",
                                data,
                                context.get("prompt_id"),
                            )

                    try:
                        if decision:
                            quiet(finish)
                    finally:
                        TRANSITION.reset(token)
                        CAPTURE.reset(capture_token)

        return wrapped

    return decorate


def observe_build(function):
    import inspect

    signature = inspect.signature(function)

    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        values = signature.bind(*args, **kwargs).arguments
        root = Path(values.get("repo_root", args[0] if args else ".")).resolve()
        context = quiet(capture_context, root)
        # Staged render roots differ from project root: inherit explicit active context.
        context = context or CAPTURE.get()
        token = CAPTURE.set(context)
        try:
            result = function(*args, **kwargs)
            if context and hasattr(result, "build_dir"):
                quiet(
                    ResearchArtifacts(context["root"]).enqueue_build,
                    result.build_dir,
                    result.build_id,
                )
            return result
        finally:
            CAPTURE.reset(token)

    return wrapped


def verify_transition_candidate(root, candidate_path):
    """Check immediately before a destructive transition; never silently relabel a revision."""
    context = CAPTURE.get()
    decision = TRANSITION.get()
    if (
        not context
        or not decision
        or decision == "unrecorded"
        or context.get("prepared_evidence_valid") is False
    ):
        return
    service = ResearchArtifacts(root)
    try:
        with service.log.connection(timeout=1) as db:
            row = db.execute(
                "SELECT payload FROM research_decisions WHERE id=?", (decision,)
            ).fetchone()
            if not row:
                return
            data = json.loads(row[0])
            expected = data["candidate"]["candidate_source"].get("sha256")
    except (OSError, sqlite3.Error, ValueError):
        warnings.warn(
            "Candidate evidence check unavailable; authoring continues.", RuntimeWarning
        )
        return
    if (
        expected
        and digest(
            read_project_file(
                service.root,
                Path(candidate_path).relative_to(service.root).as_posix(),
                1_000_000,
            )
        )
        != expected
    ):
        from manim_studio.staged_edits import StagedEditError

        raise StagedEditError(
            "stale_proposal", "Candidate changed after the decision was requested"
        )


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--worker":
    worker_main(Path(sys.argv[2]))
