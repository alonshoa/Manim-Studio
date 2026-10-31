from __future__ import annotations

from manim_studio.research_artifacts import research_transition

import ast
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from manim_studio import movie_sessions, staged_edits
from manim_studio.research import instrument_rpc
from manim_studio.builds import render_scene
from manim_studio.catalog import CatalogEntry
from manim_studio.live import LiveError, plan_live_preview
from manim_studio.profiles import get_profile
from manim_studio.validation import validate_scene_preflight


DEFAULT_AUTHORING_ROOT = ".manim-studio/authoring"
LiveProcessStarter = Callable[..., Any]


class _CompatStrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class AuthoringStatus(_CompatStrEnum):
    READY = "READY"
    DECISION_REQUIRED = "DECISION_REQUIRED"
    PAUSED = "PAUSED"
    FINISHING = "FINISHING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


class ProposalStatus(_CompatStrEnum):
    NONE = "NONE"
    PROPOSED = "PROPOSED"
    PREVIEWED = "PREVIEWED"
    NEEDS_REVISION = "NEEDS_REVISION"


class LiveStatus(_CompatStrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    RELOADING = "RELOADING"
    FAILED = "FAILED"


class NextAction(_CompatStrEnum):
    WAIT_FOR_PROPOSAL = "WAIT_FOR_PROPOSAL"
    PREVIEW_PROPOSAL = "PREVIEW_PROPOSAL"
    ACCEPT_REVISE_OR_REJECT = "ACCEPT_REVISE_OR_REJECT"
    RESUME_SESSION = "RESUME_SESSION"
    RETRY = "RETRY"
    NONE = "NONE"


@dataclass(frozen=True)
class AuthoringSessionError(Exception):
    code: str
    message: str
    detail: Any = None


@dataclass(frozen=True)
class AuthoringSessionState:
    session_id: str
    title: str
    target: str
    canonical_source: str
    steps_path: str
    language: str
    working_revision: str
    preview_revision: str | None
    active_proposal_id: str | None
    current_beat: str
    revision_number: int
    authoring_status: str
    proposal_status: str
    live_status: str
    updated_at: str
    live_pid: int | None = None
    live_source_root: str | None = None
    live_source_path: str | None = None
    last_error: str | None = None
    revision_feedback: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    finish_build_id: str | None = None
    finish_artifact_path: str | None = None


class AuthoringSessionController:
    def __init__(
        self,
        repo_root: Path | str,
        catalog_path: Path | str = "catalog/scenes.yaml",
        builds_root: Path | str = "builds",
        authoring_root: Path | str = DEFAULT_AUTHORING_ROOT,
        live_root: Path | str = ".manim-studio/live",
        live_starter: LiveProcessStarter = subprocess.Popen,
        render_runner: Any = subprocess.run,
        check_executables: bool = True,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.catalog_path = catalog_path
        self.builds_root = builds_root
        self.authoring_root = self._repo_path(Path(authoring_root), "authoring_root")
        self.live_root = live_root
        self.live_starter = live_starter
        self.render_runner = render_runner
        self.check_executables = check_executables

    def start_session(
        self,
        title: str = "Interactive Movie",
        deck_id: str = "interactive",
        scene_id: str | None = None,
        class_name: str | None = None,
        language: str | None = None,
    ) -> dict[str, Any]:
        session = movie_sessions.start_movie_session(
            self.repo_root,
            self.catalog_path,
            title=title,
            deck_id=deck_id,
            scene_id=scene_id,
            class_name=class_name,
            language=language,
        )
        state = self._state_from_movie_session(session, live_status=LiveStatus.STOPPED)
        self._write_state(state)
        return self._compact(state, status="started")

    def list_sessions(self) -> dict[str, Any]:
        sessions: list[dict[str, Any]] = []
        seen: set[str] = set()
        if self.authoring_root.exists():
            for path in sorted(self.authoring_root.glob("*/session.json")):
                try:
                    state = _state_from_data(json.loads(path.read_text(encoding="utf-8")))
                    state = self._refresh_live_status(state)
                    self._write_state(state)
                except Exception:  # noqa: BLE001 - listing should skip corrupt local state.
                    continue
                seen.add(state.session_id)
                sessions.append(self._session_summary(state))

        decks_root = self.repo_root / "decks"
        if decks_root.exists():
            for steps_path in decks_root.rglob("*.steps.json"):
                try:
                    data = json.loads(steps_path.read_text(encoding="utf-8"))
                    session_id = str(data.get("session_id", ""))
                    if not session_id or session_id in seen:
                        continue
                    state = self._state_from_movie_session(data, live_status=LiveStatus.STOPPED)
                    self._write_state(state)
                    sessions.append(self._session_summary(state))
                except Exception:  # noqa: BLE001 - ignore non-session JSON artifacts.
                    continue

        sessions.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
        return {"ok": True, "status": "success", "sessions": sessions}

    def get_status(self, session_id: str) -> dict[str, Any]:
        state = self._load_state(session_id)
        state = self._refresh_live_status(state)
        state = self._discover_active_proposal_state(state)
        self._write_state(state)
        return self._compact(state)

    def list_proposals(self, session_id: str) -> dict[str, Any]:
        state = self._load_state(session_id)
        proposals = self._proposal_summaries(state, actionable_only=False)
        return {
            "ok": True,
            "status": "success",
            "session_id": state.session_id,
            "target": state.target,
            "active_proposal_id": state.active_proposal_id,
            "proposals": proposals,
        }

    def discover_active_proposal(self, session_id: str) -> dict[str, Any]:
        state = self._load_state(session_id)
        state = self._discover_active_proposal_state(state)
        self._write_state(state)
        return self._compact(state, status="discovered")

    def propose_next_movie_step(
        self,
        session_id: str,
        body: str,
        title: str = "Next step",
        rationale: str = "",
    ) -> dict[str, Any]:
        state = self._load_state(session_id)
        _assert_transition(state, "propose")
        movie = self._movie_session(session_id)
        proposal = _semantic_append_proposal(
            self.repo_root,
            self.catalog_path,
            self.builds_root,
            movie,
            body,
            title,
            rationale,
        )
        state = self._replace_state(
            state,
            authoring_status=AuthoringStatus.DECISION_REQUIRED,
            proposal_status=ProposalStatus.PROPOSED,
            active_proposal_id=proposal["proposal_id"],
            updated_at=_utc_now(),
            last_error=None,
        )
        self._write_state(state)
        return self._compact(
            state,
            status="proposed",
            changed_lines=_changed_lines(str(proposal.get("diff", ""))),
        )

    def preview_proposal(self, session_id: str, proposal_id: str | None = None) -> dict[str, Any]:
        state = self._load_state(session_id)
        if proposal_id is None:
            state = self._discover_active_proposal_state(state)
            proposal_id = state.active_proposal_id
        if not proposal_id:
            raise AuthoringSessionError("proposal_not_found", "no actionable proposal is available")
        if state.proposal_status == ProposalStatus.NONE:
            state = self._replace_state(
                state,
                authoring_status=AuthoringStatus.DECISION_REQUIRED,
                proposal_status=ProposalStatus.PROPOSED,
                active_proposal_id=proposal_id,
                updated_at=_utc_now(),
            )
        _assert_transition(state, "preview")
        proposal = self._prepare_candidate_source(state, proposal_id)
        state = self._replace_state(
            state,
            authoring_status=AuthoringStatus.DECISION_REQUIRED,
            proposal_status=ProposalStatus.PREVIEWED,
            active_proposal_id=proposal_id,
            preview_revision=proposal["checksum"],
            current_beat=proposal["beat"],
            live_source_root=proposal["workspace_root"],
            live_source_path=proposal["source_path"],
            updated_at=_utc_now(),
            last_error=None,
        )
        self._write_state(state)
        if state.live_status in {LiveStatus.RUNNING, LiveStatus.FAILED, LiveStatus.RELOADING, LiveStatus.STARTING}:
            state = self._restart_live_process(state)
            self._write_state(state)
        return self._compact(state, status="preview_ready", changed_lines=proposal["changed_lines"])

    @research_transition('accept')
    def accept_proposal(
        self,
        session_id: str,
        proposal_id: str | None = None,
        note: str = "",
        confirm: str = "accept",
    ) -> dict[str, Any]:
        if confirm != "accept":
            raise AuthoringSessionError("approval_required", "accept requires confirm='accept'")
        state = self._load_state(session_id)
        proposal_id = proposal_id or state.active_proposal_id
        if not proposal_id:
            raise AuthoringSessionError("proposal_not_found", "no active proposal is available")
        if state.proposal_status == ProposalStatus.NONE:
            state = self._replace_state(
                state,
                authoring_status=AuthoringStatus.DECISION_REQUIRED,
                proposal_status=ProposalStatus.PROPOSED,
                active_proposal_id=proposal_id,
                updated_at=_utc_now(),
            )
        _assert_transition(state, "accept")
        proposal = self._prepare_candidate_source(state, proposal_id)
        from manim_studio.research_artifacts import quiet, record_prepared_candidate
        quiet(record_prepared_candidate, self.repo_root, self.builds_root, proposal_id)
        profile = get_profile("draft")
        validation = staged_edits.validate_scene_patch(
            self.repo_root,
            self.builds_root,
            proposal_id,
            profile,
            check_executables=self.check_executables,
        )
        validation_data = validation.get("validation")
        if isinstance(validation_data, dict) and validation_data.get("status") != "success":
            raise AuthoringSessionError("validation_failed", "proposal failed staged validation")
        _metadata, build = staged_edits.render_scene_patch(
            self.repo_root,
            self.builds_root,
            proposal_id,
            profile,
            runner=self.render_runner,
            check_executables=self.check_executables,
        )
        if build.status != "success":
            raise AuthoringSessionError(
                "render_failed",
                "proposal failed staged draft render",
                {"build_id": build.build_id},
            )
        movie_sessions.accept_movie_step(
            self.repo_root,
            self.builds_root,
            session_id,
            proposal_id,
            note=note,
            confirm=confirm,
        )
        movie = movie_sessions.get_movie_session(self.repo_root, session_id)
        revision = len(movie.get("accepted_steps", []))
        checksum = self._canonical_checksum(movie)
        state = self._replace_state(
            state,
            authoring_status=AuthoringStatus.READY,
            proposal_status=ProposalStatus.NONE,
            working_revision=checksum,
            preview_revision=None,
            active_proposal_id=None,
            current_beat=proposal["beat"],
            revision_number=revision,
            live_source_root=str(self.repo_root),
            live_source_path=movie["source_path"],
            updated_at=_utc_now(),
            last_error=None,
        )
        self._write_state(state)
        if state.live_status in {LiveStatus.RUNNING, LiveStatus.FAILED, LiveStatus.RELOADING, LiveStatus.STARTING}:
            state = self._restart_live_process(state)
            self._write_state(state)
        return self._compact(state, status="accepted", changed_lines=proposal["changed_lines"])

    @research_transition('reject')
    def reject_proposal(self, session_id: str, proposal_id: str | None = None) -> dict[str, Any]:
        state = self._load_state(session_id)
        proposal_id = proposal_id or state.active_proposal_id
        if proposal_id is not None and state.active_proposal_id not in {None, proposal_id}:
            raise AuthoringSessionError(
                "proposal_mismatch",
                "requested proposal is not the active proposal",
                {"active_proposal_id": state.active_proposal_id, "proposal_id": proposal_id},
            )
        _assert_transition(state, "reject")
        movie = movie_sessions.get_movie_session(self.repo_root, session_id)
        staged_edits.reject_scene_patch(self.repo_root, self.builds_root, proposal_id)
        state = self._replace_state(
            state,
            authoring_status=AuthoringStatus.READY,
            proposal_status=ProposalStatus.NONE,
            preview_revision=None,
            active_proposal_id=None,
            current_beat=self._latest_movie_beat(movie),
            live_source_root=str(self.repo_root),
            live_source_path=movie["source_path"],
            updated_at=_utc_now(),
            last_error=None,
        )
        self._write_state(state)
        if state.live_status in {LiveStatus.RUNNING, LiveStatus.FAILED, LiveStatus.RELOADING, LiveStatus.STARTING}:
            state = self._restart_live_process(state)
            self._write_state(state)
        return self._compact(state, status="rejected")

    @research_transition('request_revision')
    def revise_proposal(
        self,
        session_id: str,
        feedback: str,
        proposal_id: str | None = None,
    ) -> dict[str, Any]:
        state = self._load_state(session_id)
        proposal_id = proposal_id or state.active_proposal_id
        if not proposal_id:
            raise AuthoringSessionError("proposal_not_found", "no active proposal is available")
        _assert_transition(state, "revise")
        movie = self._movie_session(session_id)
        entry = {
            "proposal_id": proposal_id,
            "feedback": str(feedback),
            "revision": state.revision_number,
            "requested_at": _utc_now(),
        }
        state = self._replace_state(
            state,
            authoring_status=AuthoringStatus.DECISION_REQUIRED,
            proposal_status=ProposalStatus.NEEDS_REVISION,
            revision_feedback=(*state.revision_feedback, entry),
            active_proposal_id=None,
            current_beat=self._latest_movie_beat(movie),
            live_source_root=str(self.repo_root),
            live_source_path=movie["source_path"],
            preview_revision=None,
            updated_at=_utc_now(),
            last_error=None,
        )
        self._write_state(state)
        if state.live_status in {LiveStatus.RUNNING, LiveStatus.FAILED, LiveStatus.RELOADING, LiveStatus.STARTING}:
            state = self._restart_live_process(state)
            self._write_state(state)
        return self._compact(state, status="revision_requested")

    def pause_session(self, session_id: str, proposal_policy: str = "keep") -> dict[str, Any]:
        state = self._load_state(session_id)
        if state.active_proposal_id and proposal_policy not in {"keep", "reject"}:
            raise AuthoringSessionError(
                "decision_required",
                "pause with an active proposal requires proposal_policy 'keep' or 'reject'",
            )
        if state.active_proposal_id and proposal_policy == "reject":
            state = self._state_from_compact(self.reject_proposal(session_id, state.active_proposal_id))
        self._terminate_pid(state.live_pid)
        state = self._replace_state(
            state,
            authoring_status=AuthoringStatus.PAUSED,
            live_status=LiveStatus.STOPPED,
            live_pid=None,
            updated_at=_utc_now(),
            last_error=None,
        )
        self._write_state(state)
        return self._compact(state, status="paused")

    def resume_session(self, session_id: str, start_live: bool = True) -> dict[str, Any]:
        state = self._load_state(session_id)
        if state.authoring_status == AuthoringStatus.COMPLETED:
            raise AuthoringSessionError("completed", "completed sessions must be reopened explicitly")
        state = self._replace_state(
            state,
            authoring_status=(
                AuthoringStatus.DECISION_REQUIRED
                if state.proposal_status in {ProposalStatus.PROPOSED, ProposalStatus.PREVIEWED, ProposalStatus.NEEDS_REVISION}
                else AuthoringStatus.READY
            ),
            updated_at=_utc_now(),
            last_error=None,
        )
        self._write_state(state)
        if start_live:
            state = self._restart_live_process(state)
            self._write_state(state)
        return self._compact(state, status="resumed")

    def finish_session(self, session_id: str) -> dict[str, Any]:
        state = self._load_state(session_id)
        _assert_transition(state, "finish")
        state = self._replace_state(state, authoring_status=AuthoringStatus.FINISHING, updated_at=_utc_now())
        self._write_state(state)
        movie = self._movie_session(session_id)
        entry = self._entry_for_state(
            self._replace_state(
                state,
                live_source_root=str(self.repo_root),
                live_source_path=movie["source_path"],
                current_beat=self._latest_movie_beat(movie),
            )
        )
        profile = get_profile("draft")
        preflight = validate_scene_preflight(
            self.repo_root,
            entry,
            profile,
            check_executables=self.check_executables,
        )
        if not preflight.ok:
            state = self._replace_state(
                state,
                authoring_status=AuthoringStatus.ERROR,
                last_error="session validation failed",
                updated_at=_utc_now(),
            )
            self._write_state(state)
            return self._compact(state, status="failed")
        build = render_scene(
            self.repo_root,
            entry,
            profile,
            builds_root=self.builds_root,
            runner=self.render_runner,
            force=False,
        )
        if build.status != "success":
            state = self._replace_state(
                state,
                authoring_status=AuthoringStatus.ERROR,
                last_error="draft render failed",
                finish_build_id=build.build_id,
                updated_at=_utc_now(),
            )
            self._write_state(state)
            return self._compact(state, status="failed")
        self._terminate_pid(state.live_pid)
        artifact = _first_video_artifact(build.build_dir)
        state = self._replace_state(
            state,
            authoring_status=AuthoringStatus.COMPLETED,
            proposal_status=ProposalStatus.NONE,
            live_status=LiveStatus.STOPPED,
            live_pid=None,
            active_proposal_id=None,
            preview_revision=None,
            live_source_root=str(self.repo_root),
            live_source_path=movie["source_path"],
            finish_build_id=build.build_id,
            finish_artifact_path=artifact,
            updated_at=_utc_now(),
            last_error=None,
        )
        self._write_state(state)
        return self._compact(state, status="completed")

    def render_authoring_preview(self, session_id: str) -> dict[str, Any]:
        state = self._load_state(session_id)
        state = self._refresh_live_status(state)
        profile = get_profile("draft")
        proposal_id = state.active_proposal_id if state.proposal_status == ProposalStatus.PREVIEWED else None
        source_kind = "candidate" if proposal_id else "canonical"
        source_root = self.repo_root
        entry_state = state
        try:
            if proposal_id:
                proposal = self._prepare_candidate_source(state, proposal_id)
                source_root = Path(str(proposal["workspace_root"])).resolve()
                entry_state = self._replace_state(
                    state,
                    live_source_root=str(source_root),
                    live_source_path=str(proposal["source_path"]),
                    current_beat=str(proposal["beat"]),
                )
                builds_root: Path | str = self._preview_render_root(proposal_id)
            else:
                movie = self._movie_session(session_id)
                source_root = self.repo_root
                entry_state = self._replace_state(
                    state,
                    live_source_root=str(self.repo_root),
                    live_source_path=movie["source_path"],
                    current_beat=self._latest_movie_beat(movie),
                )
                builds_root = self.builds_root

            build = render_scene(
                source_root,
                self._entry_for_state(entry_state),
                profile,
                builds_root=builds_root,
                runner=self.render_runner,
                beat_id=entry_state.current_beat,
                force=False,
            )
            artifact = _first_video_artifact(build.build_dir)
            return {
                **self._compact(entry_state, status="rendered"),
                "source_kind": source_kind,
                "proposal_id": proposal_id,
                "render_status": build.status,
                "artifact_path": artifact,
                "build_id": build.build_id,
                "render_error": None if build.status == "success" else _render_error(build),
                "error": None if build.status == "success" else _render_error(build),
            }
        except Exception as exc:  # noqa: BLE001 - RPC result must be structured and non-fatal for preview.
            return {
                **self._compact(state, status="render_failed"),
                "source_kind": source_kind,
                "proposal_id": proposal_id,
                "render_status": "failed",
                "artifact_path": None,
                "build_id": None,
                "render_error": _exception_payload(exc),
                "error": _exception_payload(exc),
            }

    def start_live(self, session_id: str) -> dict[str, Any]:
        state = self._load_state(session_id)
        _assert_transition(state, "live")
        state = self._replace_state(state, live_status=LiveStatus.STARTING, updated_at=_utc_now())
        self._write_state(state)
        state = self._restart_live_process(state, starting=True)
        self._write_state(state)
        return self._compact(state, status=str(state.live_status))

    def reload_live(self, session_id: str) -> dict[str, Any]:
        state = self._load_state(session_id)
        _assert_transition(state, "live")
        state = self._replace_state(state, live_status=LiveStatus.RELOADING, updated_at=_utc_now())
        self._write_state(state)
        state = self._restart_live_process(state)
        self._write_state(state)
        return self._compact(state, status=str(state.live_status))

    def stop_live(self, session_id: str) -> dict[str, Any]:
        state = self._load_state(session_id)
        self._terminate_pid(state.live_pid)
        state = self._replace_state(
            state,
            live_status=LiveStatus.STOPPED,
            live_pid=None,
            updated_at=_utc_now(),
            last_error=None,
        )
        self._write_state(state)
        return self._compact(state, status="stopped")

    def rpc_loop(self) -> int:
        from manim_studio.rpc_stdio import configure_utf8
        configure_utf8()
        for line in _iter_stdin_lines():
            request_id: Any = None
            try:
                request = json.loads(line)
                if isinstance(request, dict):
                    request_id = request.get("id")
                    method = str(request.get("method", ""))
                    params = request.get("params") if isinstance(request.get("params"), dict) else {}
                else:
                    raise AuthoringSessionError("invalid_request", "RPC request must be an object")
                data = self.dispatch(method, params)
                response = {"id": request_id, "ok": True, "data": data}
            except Exception as exc:  # noqa: BLE001 - JSON-RPC adapter must report structured failures.
                response = {"id": request_id, "ok": False, "error": _exception_payload(exc)}
            print(json.dumps(response, sort_keys=True), flush=True)
        return 0

    @instrument_rpc
    def dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method.startswith(('research.', 'classification.', 'artifacts.', 'timing.')):
            from manim_studio.research_cli import dispatch
            return dispatch(self.repo_root, method, params)
        if method == "start_session":
            return self.start_session(**params)
        if method == "list_sessions":
            return self.list_sessions()
        if method == "get_status":
            return self.get_status(str(params["session_id"]))
        if method == "list_proposals":
            return self.list_proposals(str(params["session_id"]))
        if method == "discover_active_proposal":
            return self.discover_active_proposal(str(params["session_id"]))
        if method == "propose_next_movie_step":
            return self.propose_next_movie_step(
                str(params["session_id"]),
                str(params["body"]),
                title=str(params.get("title", "Next step")),
                rationale=str(params.get("rationale", "")),
            )
        if method == "preview_proposal":
            proposal_id = params.get("proposal_id")
            return self.preview_proposal(
                str(params["session_id"]),
                None if proposal_id is None else str(proposal_id),
            )
        if method == "accept_proposal":
            proposal_id = params.get("proposal_id")
            return self.accept_proposal(
                str(params["session_id"]),
                None if proposal_id is None else str(proposal_id),
                note=str(params.get("note", "")),
                confirm=str(params.get("confirm", "accept")),
            )
        if method == "reject_proposal":
            proposal_id = params.get("proposal_id")
            return self.reject_proposal(
                str(params["session_id"]),
                None if proposal_id is None else str(proposal_id),
            )
        if method == "revise_proposal":
            proposal_id = params.get("proposal_id")
            return self.revise_proposal(
                str(params["session_id"]),
                str(params["feedback"]),
                None if proposal_id is None else str(proposal_id),
            )
        if method == "pause_session":
            return self.pause_session(
                str(params["session_id"]),
                proposal_policy=str(params.get("proposal_policy", "keep")),
            )
        if method == "resume_session":
            return self.resume_session(
                str(params["session_id"]),
                start_live=bool(params.get("start_live", True)),
            )
        if method == "finish_session":
            return self.finish_session(str(params["session_id"]))
        if method == "render_authoring_preview":
            return self.render_authoring_preview(str(params["session_id"]))
        if method == "start_live":
            return self.start_live(str(params["session_id"]))
        if method == "reload_live":
            return self.reload_live(str(params["session_id"]))
        if method == "stop_live":
            return self.stop_live(str(params["session_id"]))
        raise AuthoringSessionError("unsupported", f"unknown authoring method: {method}")

    def _prepare_candidate_source(self, state: AuthoringSessionState, proposal_id: str) -> dict[str, str | None]:
        proposal = staged_edits.inspect_scene_patch(self.repo_root, self.builds_root, proposal_id)
        if proposal.get("target") != state.target:
            raise AuthoringSessionError(
                "invalid_target",
                "proposal target does not match authoring session",
                {"proposal_target": proposal.get("target"), "session_target": state.target},
            )
        canonical_text = self._source_text(state.canonical_source)
        if _sha256_text(canonical_text) != proposal.get("base_checksum"):
            raise AuthoringSessionError("stale_proposal", "canonical source changed since proposal creation")
        if _status_field(proposal.get("applied")) == "success":
            raise AuthoringSessionError("stale_proposal", "proposal has already been applied")
        source_path = staged_edits.proposal_source_path(self.repo_root, self.builds_root, proposal_id)
        text = source_path.read_text(encoding="utf-8")
        ast.parse(text, filename=str(source_path))
        beat = f"step_{state.revision_number + 1:03d}"
        text_with_beat = ensure_step_beat(text, beat, f"Accepted step {state.revision_number + 1}")
        if text_with_beat != text:
            staged_edits.update_scene_patch_source(
                self.repo_root,
                self.builds_root,
                proposal_id,
                text_with_beat,
            )
            text = text_with_beat
            ast.parse(text, filename=str(source_path))
        workspace = staged_edits.proposal_workspace_path(self.repo_root, self.builds_root, proposal_id)
        return {
            "beat": beat,
            "checksum": _sha256_text(text),
            "workspace_root": str(workspace),
            "source_path": str(proposal["source_path"]),
            "changed_lines": _changed_lines(str(proposal.get("diff", ""))),
        }

    def _restart_live_process(
        self,
        state: AuthoringSessionState,
        starting: bool = False,
    ) -> AuthoringSessionState:
        self._terminate_pid(state.live_pid)
        try:
            source_root = Path(state.live_source_root) if state.live_source_root else self.repo_root
            entry = self._entry_for_state(state)
            plan = plan_live_preview(
                state.target,
                state.current_beat,
                repo_root=self.repo_root,
                catalog_path=self.catalog_path,
                live_root=self.live_root,
                session_id=state.session_id,
                source_repo_root=source_root,
                source_entry=entry,
            )
            plan.media_dir.mkdir(parents=True, exist_ok=True)
            process_kwargs = self._live_process_kwargs(state, plan)
            try:
                process = self.live_starter(list(plan.command), **process_kwargs)
            finally:
                for stream_name in ("stdout", "stderr"):
                    stream = process_kwargs.get(stream_name)
                    if hasattr(stream, "close"):
                        stream.close()
            pid = int(getattr(process, "pid", 0) or 0) or None
            poll = getattr(process, "poll", None)
            if callable(poll):
                early_code = poll()
                if early_code is not None:
                    return self._replace_state(
                        state,
                        live_status=LiveStatus.FAILED,
                        live_pid=None,
                        updated_at=_utc_now(),
                        last_error=f"live process exited early with code {early_code}",
                    )
            return self._replace_state(
                state,
                live_status=LiveStatus.RUNNING,
                live_pid=pid,
                live_source_root=str(plan.cwd),
                live_source_path=plan.entry.source_path,
                updated_at=_utc_now(),
                last_error=None,
            )
        except (LiveError, OSError) as exc:
            return self._replace_state(
                state,
                live_status=LiveStatus.FAILED,
                live_pid=None,
                updated_at=_utc_now(),
                last_error=getattr(exc, "message", str(exc)),
            )

    def _entry_for_state(self, state: AuthoringSessionState) -> CatalogEntry:
        source_path = state.live_source_path or state.canonical_source
        movie = self._movie_session(state.session_id)
        return CatalogEntry(
            deck_id=state.target.split("/", 1)[0],
            scene_id=state.target.split("/", 1)[1],
            source_path=source_path,
            class_name=movie["class_name"],
            base_scene_type="Scene",
            renderer="manim",
            language=state.language,
            description=f"Interactive movie session: {state.title}",
            parameter_notes="Built incrementally from accepted interactive steps.",
            render_command=f"manim -ql {source_path} {movie['class_name']}",
            migration_notes="Generated by studio session start.",
        )

    def _load_state(self, session_id: str) -> AuthoringSessionState:
        path = self._state_path(session_id)
        if path.exists():
            return _state_from_data(json.loads(path.read_text(encoding="utf-8")))
        movie = self._movie_session(session_id)
        state = self._state_from_movie_session(movie, live_status=LiveStatus.STOPPED)
        self._write_state(state)
        return state

    def _state_from_movie_session(
        self,
        session: dict[str, Any],
        live_status: LiveStatus | str,
    ) -> AuthoringSessionState:
        revision = len(session.get("accepted_steps", []))
        return AuthoringSessionState(
            session_id=session["session_id"],
            title=session.get("title", "Interactive Movie"),
            target=session["target"],
            canonical_source=session["source_path"],
            steps_path=session["steps_path"],
            language=session.get("language", "en"),
            working_revision=self._canonical_checksum(session),
            preview_revision=None,
            active_proposal_id=None,
            current_beat=self._latest_movie_beat(session),
            revision_number=revision,
            authoring_status=AuthoringStatus.READY,
            proposal_status=ProposalStatus.NONE,
            live_status=str(live_status),
            updated_at=str(session.get("updated_at") or _utc_now()),
            live_source_root=str(self.repo_root),
            live_source_path=session["source_path"],
        )

    def _write_state(self, state: AuthoringSessionState) -> None:
        _atomic_write_json(self._state_path(state.session_id), asdict(state))

    def _state_path(self, session_id: str) -> Path:
        safe = _safe_id(session_id)
        return self.authoring_root / safe / "session.json"

    def _staged_root(self) -> Path:
        path = Path(self.builds_root)
        if not path.is_absolute():
            path = self.repo_root / path
        return path.resolve() / "staged"

    def _preview_render_root(self, proposal_id: str) -> Path:
        digest = hashlib.sha256(proposal_id.encode("utf-8")).hexdigest()[:10]
        return self._staged_root() / "_preview" / digest

    def _proposal_summaries(
        self,
        state: AuthoringSessionState,
        actionable_only: bool,
    ) -> list[dict[str, Any]]:
        proposals: list[dict[str, Any]] = []
        staged_root = self._staged_root()
        if not staged_root.exists():
            return proposals
        canonical_checksum = _sha256_text(self._source_text(state.canonical_source))
        for proposal_dir in sorted(staged_root.iterdir(), key=lambda path: path.name, reverse=True):
            if not proposal_dir.is_dir():
                continue
            try:
                proposal = staged_edits.inspect_scene_patch(
                    self.repo_root,
                    self.builds_root,
                    proposal_dir.name,
                )
            except staged_edits.StagedEditError:
                continue
            if proposal.get("target") != state.target:
                continue
            applied_status = _status_field(proposal.get("applied"))
            unresolved = applied_status in {"", "pending", "none"}
            actionable = unresolved and proposal.get("base_checksum") == canonical_checksum
            if actionable_only and not actionable:
                continue
            proposals.append(
                {
                    "proposal_id": proposal.get("proposal_id"),
                    "created_at": proposal.get("created_at"),
                    "rationale": proposal.get("rationale", ""),
                    "changed_lines": _changed_lines(str(proposal.get("diff", ""))),
                    "validation_status": _status_field(proposal.get("validation")),
                    "draft_render_status": _status_field(proposal.get("draft_render")),
                    "applied_status": applied_status,
                    "actionable": actionable,
                }
            )
        proposals.sort(key=lambda item: (not bool(item["actionable"]), str(item.get("created_at", ""))), reverse=False)
        actionable = [item for item in proposals if item["actionable"]]
        stale = [item for item in proposals if not item["actionable"]]
        actionable.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        stale.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return actionable + stale

    def _discover_active_proposal_state(self, state: AuthoringSessionState) -> AuthoringSessionState:
        if state.authoring_status in {AuthoringStatus.PAUSED, AuthoringStatus.FINISHING, AuthoringStatus.COMPLETED}:
            return state
        if state.active_proposal_id:
            try:
                self._prepare_candidate_source(state, state.active_proposal_id)
                return state
            except (AuthoringSessionError, staged_edits.StagedEditError, SyntaxError):
                pass
        proposals = self._proposal_summaries(state, actionable_only=True)
        revised_ids = {
            str(item.get("proposal_id"))
            for item in state.revision_feedback
            if item.get("proposal_id") is not None
        }
        proposals = [item for item in proposals if str(item.get("proposal_id")) not in revised_ids]
        if not proposals:
            if state.proposal_status == ProposalStatus.NEEDS_REVISION:
                return state
            if state.proposal_status in {ProposalStatus.PROPOSED, ProposalStatus.PREVIEWED}:
                return self._replace_state(
                    state,
                    authoring_status=AuthoringStatus.READY,
                    proposal_status=ProposalStatus.NONE,
                    active_proposal_id=None,
                    preview_revision=None,
                    updated_at=_utc_now(),
                )
            return state
        proposal_id = str(proposals[0]["proposal_id"])
        return self._replace_state(
            state,
            authoring_status=AuthoringStatus.DECISION_REQUIRED,
            proposal_status=ProposalStatus.PROPOSED,
            active_proposal_id=proposal_id,
            updated_at=_utc_now(),
            last_error=None,
        )

    def _live_process_kwargs(self, state: AuthoringSessionState, plan: Any) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"cwd": plan.cwd, "env": plan.env}
        log_dir = self._state_path(state.session_id).parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        kwargs["stdin"] = subprocess.DEVNULL
        kwargs["stdout"] = (log_dir / "live_stdout.log").open("ab")
        kwargs["stderr"] = (log_dir / "live_stderr.log").open("ab")
        if os.name == "nt" and self.live_starter is subprocess.Popen:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return kwargs

    def _repo_path(self, path: Path, label: str) -> Path:
        resolved = path if path.is_absolute() else self.repo_root / path
        resolved = resolved.resolve()
        try:
            resolved.relative_to(self.repo_root)
        except ValueError as exc:
            raise AuthoringSessionError("invalid_target", f"{label} must stay inside the repository") from exc
        return resolved

    def _source_text(self, source_path: str) -> str:
        return self._repo_path(Path(source_path), "source_path").read_text(encoding="utf-8")

    def _canonical_checksum(self, session: dict[str, Any]) -> str:
        return _sha256_text(self._source_text(session["source_path"]))

    def _movie_session(self, session_id: str) -> dict[str, Any]:
        return movie_sessions.get_movie_session(self.repo_root, session_id)

    def _latest_movie_beat(self, session: dict[str, Any]) -> str:
        steps = session.get("accepted_steps", [])
        if not steps:
            return "empty"
        last = steps[-1]
        if isinstance(last, dict) and isinstance(last.get("beat_id"), str):
            return last["beat_id"]
        return f"step_{len(steps):03d}"

    def _refresh_live_status(self, state: AuthoringSessionState) -> AuthoringSessionState:
        if state.live_pid is None or state.live_status in {LiveStatus.STOPPED, LiveStatus.FAILED}:
            return state
        try:
            os.kill(state.live_pid, 0)
        except OSError:
            return self._replace_state(
                state,
                live_status=LiveStatus.STOPPED,
                live_pid=None,
                updated_at=_utc_now(),
                last_error="live process is no longer running",
            )
        return state

    def _terminate_pid(self, pid: int | None) -> None:
        if pid is None:
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return

    def _replace_state(self, state: AuthoringSessionState, **changes: Any) -> AuthoringSessionState:
        data = asdict(state)
        data.update(changes)
        return _state_from_data(data)

    def _state_from_compact(self, data: dict[str, Any]) -> AuthoringSessionState:
        return self._load_state(str(data["session_id"]))

    def _session_summary(self, state: AuthoringSessionState) -> dict[str, Any]:
        return {
            "session_id": state.session_id,
            "title": state.title,
            "target": state.target,
            "authoring_status": state.authoring_status,
            "proposal_status": state.proposal_status,
            "live_status": state.live_status,
            "beat": state.current_beat,
            "revision": state.revision_number,
            "updated_at": state.updated_at,
            "next_action": _next_action(state),
        }

    def _compact(
        self,
        state: AuthoringSessionState,
        status: str | None = None,
        changed_lines: str | None = None,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "status": status or "success",
            "session_id": state.session_id,
            "title": state.title,
            "target": state.target,
            "authoring_status": state.authoring_status,
            "proposal_status": state.proposal_status,
            "live_status": state.live_status,
            "active_proposal_id": state.active_proposal_id,
            "proposal_id": state.active_proposal_id,
            "revision": state.revision_number,
            "beat": state.current_beat,
            "next_action": _next_action(state),
            "live_pid": state.live_pid,
            "canonical_source": state.canonical_source,
            "steps_path": state.steps_path,
            "language": state.language,
            "source_root": state.live_source_root or str(self.repo_root),
            "source_path": state.live_source_path or state.canonical_source,
            "changed_lines": changed_lines,
            "revision_feedback": list(state.revision_feedback),
            "finish_build_id": state.finish_build_id,
            "finish_artifact_path": state.finish_artifact_path,
            "warnings": [],
            "last_error": state.last_error,
            "error": state.last_error,
        }


def ensure_step_beat(source: str, beat_id: str, label: str) -> str:
    if f'self.beat("{beat_id}"' in source or f"self.beat('{beat_id}'" in source:
        return source
    module = ast.parse(source)
    construct = _single_construct(module)
    insert_after = _construct_insert_after_line(construct)
    lines = source.splitlines(keepends=True)
    indent = _construct_body_indent(lines, construct)
    escaped_label = json.dumps(label, ensure_ascii=False)
    beat_line = f"{indent}self.beat({json.dumps(beat_id)}, label={escaped_label})\n"
    lines[insert_after:insert_after] = [beat_line]
    return "".join(lines)


def _semantic_append_proposal(
    repo_root: Path,
    catalog_path: Path | str,
    builds_root: Path | str,
    session: dict[str, Any],
    body: str,
    title: str,
    rationale: str,
) -> dict[str, Any]:
    source_path = (repo_root / session["source_path"]).resolve()
    source_path.relative_to(repo_root)
    original = source_path.read_text(encoding="utf-8")
    module = ast.parse(original, filename=str(source_path))
    construct = _construct_for_class(module, str(session["class_name"]))
    step_id = f"step_{len(session.get('accepted_steps', [])) + 1:03d}"
    block = _step_block(step_id, body, title)
    lines = original.splitlines(keepends=True)
    if len(construct.body) == 1 and isinstance(construct.body[0], ast.Pass):
        pass_node = construct.body[0]
        patched_lines = list(lines)
        patched_lines[pass_node.lineno - 1 : pass_node.end_lineno or pass_node.lineno] = _text_lines(block)
        patched = "".join(patched_lines)
        start_line = pass_node.lineno
        end_line = pass_node.end_lineno or pass_node.lineno
        expected = "".join(lines[start_line - 1 : end_line])
        edits = [{"op": "replace", "start_line": start_line, "end_line": end_line, "expected": expected, "text": block}]
    else:
        insert_after = _construct_insert_after_line(construct)
        expected = lines[insert_after - 1] if insert_after > 0 else ""
        edits = [{"op": "insert_after", "line": insert_after, "expected": expected, "text": block}]
        patched_lines = list(lines)
        patched_lines[insert_after:insert_after] = _text_lines(block)
        patched = "".join(patched_lines)
    ast.parse(patched, filename=str(source_path))
    entry = _session_entry(session)
    return staged_edits.propose_scene_patch(
        repo_root,
        catalog_path,
        builds_root,
        entry,
        edits,
        rationale or title,
    )


def _step_block(step_id: str, body: str, title: str) -> str:
    clean_body = textwrap.dedent(body).strip("\n")
    if not clean_body.strip():
        raise AuthoringSessionError("invalid_patch", "next step body must not be empty")
    indented_body = textwrap.indent(clean_body, "        ")
    label = title.strip() or f"Accepted step {step_id}"
    return (
        f'        # <manim-studio-step id="{step_id}">\n'
        f"{indented_body}\n"
        f"        self.beat({json.dumps(step_id)}, label={json.dumps(label, ensure_ascii=False)})\n"
        f"        # </manim-studio-step>\n"
    )


def _single_construct(module: ast.Module) -> ast.FunctionDef:
    constructs = [
        node
        for class_node in module.body
        if isinstance(class_node, ast.ClassDef)
        for node in class_node.body
        if isinstance(node, ast.FunctionDef) and node.name == "construct"
    ]
    if len(constructs) != 1:
        raise AuthoringSessionError("invalid_target", "source must contain exactly one construct() method")
    return constructs[0]


def _construct_for_class(module: ast.Module, class_name: str) -> ast.FunctionDef:
    for class_node in module.body:
        if isinstance(class_node, ast.ClassDef) and class_node.name == class_name:
            for node in class_node.body:
                if isinstance(node, ast.FunctionDef) and node.name == "construct":
                    return node
            raise AuthoringSessionError("invalid_target", f"{class_name} has no construct() method")
    raise AuthoringSessionError("invalid_target", f"scene class not found: {class_name}")


def _construct_insert_after_line(construct: ast.FunctionDef) -> int:
    body = list(construct.body)
    if body and _is_terminal_empty_wait(body[-1]) and len(body) > 1:
        return int(body[-2].end_lineno or body[-2].lineno)
    if body:
        return int(body[-1].end_lineno or body[-1].lineno)
    return int(construct.lineno)


def _is_terminal_empty_wait(node: ast.AST) -> bool:
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return False
    call = node.value
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "wait"
        and isinstance(func.value, ast.Name)
        and func.value.id == "self"
    )


def _construct_body_indent(lines: list[str], construct: ast.FunctionDef) -> str:
    for node in construct.body:
        if node.lineno - 1 < len(lines):
            indent = _line_indent(lines[node.lineno - 1])
            if indent:
                return indent
    return "        "


def _session_entry(session: dict[str, Any]) -> CatalogEntry:
    return CatalogEntry(
        deck_id=str(session["deck_id"]),
        scene_id=str(session["scene_id"]),
        source_path=str(session["source_path"]),
        class_name=str(session["class_name"]),
        base_scene_type="Scene",
        renderer="manim",
        language=str(session.get("language", "en")),
        description=f"Interactive movie session: {session.get('title', 'Interactive Movie')}",
        parameter_notes="Built incrementally from accepted interactive steps.",
        render_command=f"manim -ql {session['source_path']} {session['class_name']}",
        migration_notes="Generated by studio session start.",
    )


def _assert_transition(state: AuthoringSessionState, action: str) -> None:
    if state.authoring_status == AuthoringStatus.COMPLETED:
        raise AuthoringSessionError("completed", "session is completed")
    if state.authoring_status == AuthoringStatus.FINISHING:
        raise AuthoringSessionError("busy", "session is finishing")
    if action in {"propose", "live"} and state.authoring_status == AuthoringStatus.PAUSED:
        raise AuthoringSessionError("paused", "resume the session before continuing")
    if action == "propose" and state.proposal_status not in {ProposalStatus.NONE, ProposalStatus.NEEDS_REVISION}:
        raise AuthoringSessionError("decision_required", "resolve the active proposal before proposing another")
    if action == "preview" and state.proposal_status not in {ProposalStatus.PROPOSED, ProposalStatus.PREVIEWED, ProposalStatus.NEEDS_REVISION}:
        raise AuthoringSessionError("proposal_not_found", "no proposal is waiting to preview")
    if action in {"accept", "reject", "revise"} and state.proposal_status not in {
        ProposalStatus.PROPOSED,
        ProposalStatus.PREVIEWED,
        ProposalStatus.NEEDS_REVISION,
    }:
        raise AuthoringSessionError("proposal_not_found", "no active proposal is available")
    if action == "finish" and state.proposal_status != ProposalStatus.NONE:
        raise AuthoringSessionError("decision_required", "resolve the active proposal before finishing")


def _next_action(state: AuthoringSessionState) -> str:
    if state.authoring_status == AuthoringStatus.PAUSED:
        return str(NextAction.RESUME_SESSION)
    if state.authoring_status == AuthoringStatus.ERROR or state.live_status == LiveStatus.FAILED:
        return str(NextAction.RETRY)
    if state.authoring_status == AuthoringStatus.COMPLETED:
        return str(NextAction.NONE)
    if state.proposal_status == ProposalStatus.PROPOSED:
        return str(NextAction.PREVIEW_PROPOSAL)
    if state.proposal_status == ProposalStatus.NEEDS_REVISION:
        return str(NextAction.WAIT_FOR_PROPOSAL)
    if state.proposal_status == ProposalStatus.PREVIEWED:
        return str(NextAction.ACCEPT_REVISE_OR_REJECT)
    if state.authoring_status == AuthoringStatus.READY:
        return str(NextAction.WAIT_FOR_PROPOSAL)
    return str(NextAction.NONE)


def _state_from_data(data: dict[str, Any]) -> AuthoringSessionState:
    live_status = _normalize_live_status(data.get("live_status", "STOPPED"))
    proposal_status = _normalize_proposal_status(data.get("proposal_status"), data.get("active_proposal_id"))
    authoring_status = _normalize_authoring_status(data.get("authoring_status"), proposal_status)
    feedback = data.get("revision_feedback", [])
    if not isinstance(feedback, (list, tuple)):
        feedback = []
    return AuthoringSessionState(
        session_id=str(data["session_id"]),
        title=str(data.get("title", "Interactive Movie")),
        target=str(data["target"]),
        canonical_source=str(data["canonical_source"]),
        steps_path=str(data["steps_path"]),
        language=str(data.get("language", "en")),
        working_revision=str(data["working_revision"]),
        preview_revision=data.get("preview_revision") if data.get("preview_revision") is None else str(data.get("preview_revision")),
        active_proposal_id=data.get("active_proposal_id") if data.get("active_proposal_id") is None else str(data.get("active_proposal_id")),
        current_beat=str(data.get("current_beat", data.get("beat", "empty"))),
        revision_number=int(data.get("revision_number", data.get("revision", 0))),
        authoring_status=str(authoring_status),
        proposal_status=str(proposal_status),
        live_status=str(live_status),
        updated_at=str(data.get("updated_at", _utc_now())),
        live_pid=data.get("live_pid") if data.get("live_pid") is None else int(data.get("live_pid")),
        live_source_root=data.get("live_source_root") if data.get("live_source_root") is None else str(data.get("live_source_root")),
        live_source_path=data.get("live_source_path") if data.get("live_source_path") is None else str(data.get("live_source_path")),
        last_error=data.get("last_error") if data.get("last_error") is None else str(data.get("last_error")),
        revision_feedback=tuple(item for item in feedback if isinstance(item, dict)),
        finish_build_id=data.get("finish_build_id") if data.get("finish_build_id") is None else str(data.get("finish_build_id")),
        finish_artifact_path=data.get("finish_artifact_path") if data.get("finish_artifact_path") is None else str(data.get("finish_artifact_path")),
    )


def _normalize_authoring_status(value: Any, proposal_status: str) -> str:
    if isinstance(value, str):
        upper = value.upper()
        if upper in AuthoringStatus.__members__:
            return upper
    return AuthoringStatus.DECISION_REQUIRED if proposal_status != ProposalStatus.NONE else AuthoringStatus.READY


def _normalize_proposal_status(value: Any, active_proposal_id: Any) -> str:
    if isinstance(value, str):
        upper = value.upper()
        if upper in ProposalStatus.__members__:
            return upper
    return ProposalStatus.PROPOSED if active_proposal_id else ProposalStatus.NONE


def _normalize_live_status(value: Any) -> str:
    mapping = {
        "stopped": LiveStatus.STOPPED,
        "starting": LiveStatus.STARTING,
        "running": LiveStatus.RUNNING,
        "reloading": LiveStatus.RELOADING,
        "failed": LiveStatus.FAILED,
    }
    if isinstance(value, str):
        if value in mapping:
            return str(mapping[value])
        upper = value.upper()
        if upper in LiveStatus.__members__:
            return upper
    return LiveStatus.STOPPED


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        newline="",
    ) as handle:
        handle.write(text)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _safe_id(value: str) -> str:
    if not value or any(part in {"", ".", ".."} for part in Path(value).parts):
        raise AuthoringSessionError("session_not_found", "session id must be a local identifier")
    if "/" in value or "\\" in value:
        raise AuthoringSessionError("session_not_found", "session id must be a local identifier")
    return value


def _changed_lines(diff: str) -> str | None:
    ranges: list[str] = []
    for line in diff.splitlines():
        if not line.startswith("@@"):
            continue
        parts = line.split()
        if len(parts) < 3 or not parts[2].startswith("+"):
            continue
        span = parts[2][1:]
        start, _, count = span.partition(",")
        if not start.isdigit():
            continue
        if count.isdigit() and int(count) > 1:
            ranges.append(f"{start}-{int(start) + int(count) - 1}")
        else:
            ranges.append(start)
    return ", ".join(ranges) if ranges else None


def _status_field(value: Any) -> str | None:
    if isinstance(value, dict):
        status = value.get("status")
        return str(status) if status is not None else None
    return None


def _line_indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())] or "        "


def _text_lines(text: str) -> list[str]:
    return (text if text.endswith("\n") else text + "\n").splitlines(keepends=True)


def _first_video_artifact(build_dir: Path) -> str | None:
    for path in sorted(build_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".mp4", ".mov", ".webm"}:
            return str(path)
    return None


def _render_error(build: Any) -> dict[str, Any]:
    manifest_path = Path(build.build_dir) / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    stderr_path = Path(build.build_dir) / str(manifest.get("stderr_log", "stderr.log"))
    stdout_path = Path(build.build_dir) / str(manifest.get("stdout_log", "stdout.log"))
    detail = ""
    for log_path in (stderr_path, stdout_path):
        if log_path.exists():
            text = log_path.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                detail = text[-2000:]
                break
    return {
        "code": str(manifest.get("failure_class") or "render_failed"),
        "message": "authoring preview render failed",
        "detail": {
            "build_id": getattr(build, "build_id", None),
            "returncode": getattr(build, "returncode", None),
            "build_dir": str(getattr(build, "build_dir", "")),
            "stderr_log": str(stderr_path),
            "stdout_log": str(stdout_path),
            "log_excerpt": detail,
        },
    }


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iter_stdin_lines():
    while True:
        raw = sys.stdin.buffer.readline()
        if not raw:
            break
        line = raw.decode("utf-8")
        if line.strip():
            yield line


def _exception_payload(exc: Exception) -> dict[str, Any]:
    from manim_studio.research_sessions import ResearchSessionError
    if isinstance(exc, ResearchSessionError):
        return {"code": exc.code, "message": str(exc), "detail": None}
    if isinstance(exc, AuthoringSessionError):
        return {"code": exc.code, "message": exc.message, "detail": exc.detail}
    if isinstance(exc, movie_sessions.MovieSessionError):
        return {"code": exc.code, "message": exc.message, "detail": exc.detail}
    if isinstance(exc, staged_edits.StagedEditError):
        return {"code": exc.code, "message": exc.message, "detail": exc.detail}
    return {"code": "internal_error", "message": str(exc), "detail": None}
