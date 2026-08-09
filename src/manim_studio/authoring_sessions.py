from __future__ import annotations

import ast
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from manim_studio import movie_sessions, staged_edits
from manim_studio.catalog import CatalogEntry, entry_target
from manim_studio.live import LiveError, plan_live_preview
from manim_studio.profiles import get_profile


DEFAULT_AUTHORING_ROOT = ".manim-studio/authoring"
LiveProcessStarter = Callable[..., Any]


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
    live_status: str
    updated_at: str
    live_pid: int | None = None
    live_source_root: str | None = None
    live_source_path: str | None = None
    last_error: str | None = None


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
        state = self._state_from_movie_session(session, live_status="stopped")
        self._write_state(state)
        return self._compact(state, status="started")

    def get_status(self, session_id: str) -> dict[str, Any]:
        state = self._load_state(session_id)
        state = self._refresh_live_status(state)
        self._write_state(state)
        return self._compact(state)

    def list_proposals(self, session_id: str) -> dict[str, Any]:
        state = self._load_state(session_id)
        staged_root = self._staged_root()
        proposals: list[dict[str, Any]] = []
        if staged_root.exists():
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
                proposals.append(
                    {
                        "proposal_id": proposal.get("proposal_id"),
                        "created_at": proposal.get("created_at"),
                        "rationale": proposal.get("rationale", ""),
                        "changed_lines": _changed_lines(str(proposal.get("diff", ""))),
                        "validation_status": _status_field(proposal.get("validation")),
                        "draft_render_status": _status_field(proposal.get("draft_render")),
                        "applied_status": _status_field(proposal.get("applied")),
                    }
                )
        return {
            "ok": True,
            "status": "success",
            "session_id": state.session_id,
            "target": state.target,
            "active_proposal_id": state.active_proposal_id,
            "proposals": proposals,
        }

    def preview_proposal(self, session_id: str, proposal_id: str) -> dict[str, Any]:
        state = self._load_state(session_id)
        proposal = self._prepare_candidate_source(state, proposal_id)
        state = self._replace_state(
            state,
            active_proposal_id=proposal_id,
            preview_revision=proposal["checksum"],
            current_beat=proposal["beat"],
            live_source_root=proposal["workspace_root"],
            live_source_path=proposal["source_path"],
            updated_at=_utc_now(),
            last_error=None,
        )
        self._write_state(state)
        if state.live_status in {"running", "failed", "reloading", "starting"}:
            state = self._restart_live_process(state)
            self._write_state(state)
        return self._compact(state, status="preview_ready", changed_lines=proposal["changed_lines"])

    def accept_proposal(
        self,
        session_id: str,
        proposal_id: str,
        note: str = "",
        confirm: str = "accept",
    ) -> dict[str, Any]:
        if confirm != "accept":
            raise AuthoringSessionError("approval_required", "accept requires confirm='accept'")
        state = self._load_state(session_id)
        proposal = self._prepare_candidate_source(state, proposal_id)
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
        if state.live_status in {"running", "failed", "reloading", "starting"}:
            state = self._restart_live_process(state)
            self._write_state(state)
        return self._compact(state, status="accepted", changed_lines=proposal["changed_lines"])

    def reject_proposal(self, session_id: str, proposal_id: str | None = None) -> dict[str, Any]:
        state = self._load_state(session_id)
        if proposal_id is not None and state.active_proposal_id not in {None, proposal_id}:
            raise AuthoringSessionError(
                "proposal_mismatch",
                "requested proposal is not the active proposal",
                {"active_proposal_id": state.active_proposal_id, "proposal_id": proposal_id},
            )
        movie = movie_sessions.get_movie_session(self.repo_root, session_id)
        state = self._replace_state(
            state,
            preview_revision=None,
            active_proposal_id=None,
            current_beat=self._latest_movie_beat(movie),
            live_source_root=str(self.repo_root),
            live_source_path=movie["source_path"],
            updated_at=_utc_now(),
            last_error=None,
        )
        self._write_state(state)
        if state.live_status in {"running", "failed", "reloading", "starting"}:
            state = self._restart_live_process(state)
            self._write_state(state)
        return self._compact(state, status="rejected")

    def start_live(self, session_id: str) -> dict[str, Any]:
        state = self._load_state(session_id)
        state = self._replace_state(state, live_status="starting", updated_at=_utc_now())
        self._write_state(state)
        state = self._restart_live_process(state, starting=True)
        self._write_state(state)
        return self._compact(state, status=state.live_status)

    def reload_live(self, session_id: str) -> dict[str, Any]:
        state = self._load_state(session_id)
        state = self._replace_state(state, live_status="reloading", updated_at=_utc_now())
        self._write_state(state)
        state = self._restart_live_process(state)
        self._write_state(state)
        return self._compact(state, status=state.live_status)

    def stop_live(self, session_id: str) -> dict[str, Any]:
        state = self._load_state(session_id)
        self._terminate_pid(state.live_pid)
        state = self._replace_state(
            state,
            live_status="stopped",
            live_pid=None,
            updated_at=_utc_now(),
            last_error=None,
        )
        self._write_state(state)
        return self._compact(state, status="stopped")

    def rpc_loop(self) -> int:
        for line in _iter_stdin_lines():
            try:
                request = json.loads(line)
                method = str(request.get("method", ""))
                params = request.get("params") if isinstance(request.get("params"), dict) else {}
                data = self.dispatch(method, params)
                response = {"id": request.get("id"), "ok": True, "data": data}
            except Exception as exc:  # noqa: BLE001 - JSON-RPC adapter must report structured failures.
                response = {"id": None, "ok": False, "error": _exception_payload(exc)}
            print(json.dumps(response, sort_keys=True), flush=True)
        return 0

    def dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "start_session":
            return self.start_session(**params)
        if method == "get_status":
            return self.get_status(str(params["session_id"]))
        if method == "list_proposals":
            return self.list_proposals(str(params["session_id"]))
        if method == "preview_proposal":
            return self.preview_proposal(str(params["session_id"]), str(params["proposal_id"]))
        if method == "accept_proposal":
            return self.accept_proposal(
                str(params["session_id"]),
                str(params["proposal_id"]),
                note=str(params.get("note", "")),
                confirm=str(params.get("confirm", "accept")),
            )
        if method == "reject_proposal":
            return self.reject_proposal(str(params["session_id"]), params.get("proposal_id"))
        if method == "start_live":
            return self.start_live(str(params["session_id"]))
        if method == "reload_live":
            return self.reload_live(str(params["session_id"]))
        if method == "stop_live":
            return self.stop_live(str(params["session_id"]))
        raise AuthoringSessionError("unsupported", f"unknown authoring method: {method}")

    def _prepare_candidate_source(self, state: AuthoringSessionState, proposal_id: str) -> dict[str, str]:
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
            "source_path": proposal["source_path"],
            "changed_lines": _changed_lines(proposal.get("diff", "")),
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
            return self._replace_state(
                state,
                live_status="running",
                live_pid=pid,
                live_source_root=str(plan.cwd),
                live_source_path=plan.entry.source_path,
                updated_at=_utc_now(),
                last_error=None,
            )
        except (LiveError, OSError) as exc:
            return self._replace_state(
                state,
                live_status="failed",
                live_pid=None,
                updated_at=_utc_now(),
                last_error=getattr(exc, "message", str(exc)),
            )

    def _entry_for_state(self, state: AuthoringSessionState) -> CatalogEntry:
        source_path = state.live_source_path or state.canonical_source
        return CatalogEntry(
            deck_id=state.target.split("/", 1)[0],
            scene_id=state.target.split("/", 1)[1],
            source_path=source_path,
            class_name=self._movie_session(state.session_id)["class_name"],
            base_scene_type="Scene",
            renderer="manim",
            language=state.language,
            description=f"Interactive movie session: {state.title}",
            parameter_notes="Built incrementally from accepted interactive steps.",
            render_command=f"manim -ql {source_path} {self._movie_session(state.session_id)['class_name']}",
            migration_notes="Generated by studio session start.",
        )

    def _load_state(self, session_id: str) -> AuthoringSessionState:
        path = self._state_path(session_id)
        if path.exists():
            return _state_from_data(json.loads(path.read_text(encoding="utf-8")))
        movie = self._movie_session(session_id)
        state = self._state_from_movie_session(movie, live_status="stopped")
        self._write_state(state)
        return state

    def _state_from_movie_session(
        self,
        session: dict[str, Any],
        live_status: str,
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
            live_status=live_status,
            updated_at=_utc_now(),
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

    def _live_process_kwargs(self, state: AuthoringSessionState, plan: Any) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"cwd": plan.cwd, "env": plan.env}
        if os.name == "nt" and self.live_starter is subprocess.Popen:
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
            return kwargs

        log_dir = self._state_path(state.session_id).parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        kwargs["stdin"] = subprocess.DEVNULL
        kwargs["stdout"] = (log_dir / "live_stdout.log").open("ab")
        kwargs["stderr"] = (log_dir / "live_stderr.log").open("ab")
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
        if state.live_pid is None or state.live_status in {"stopped", "failed"}:
            return state
        try:
            os.kill(state.live_pid, 0)
        except OSError:
            return self._replace_state(state, live_status="stopped", live_pid=None, updated_at=_utc_now())
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

    def _compact(
        self,
        state: AuthoringSessionState,
        status: str | None = None,
        changed_lines: str | None = None,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "status": status or state.live_status,
            "session_id": state.session_id,
            "target": state.target,
            "proposal_id": state.active_proposal_id,
            "revision": state.revision_number,
            "beat": state.current_beat,
            "live_status": state.live_status,
            "live_pid": state.live_pid,
            "canonical_source": state.canonical_source,
            "steps_path": state.steps_path,
            "language": state.language,
            "source_root": state.live_source_root or str(self.repo_root),
            "source_path": state.live_source_path or state.canonical_source,
            "changed_lines": changed_lines,
            "warnings": [],
            "error": state.last_error,
        }


def ensure_step_beat(source: str, beat_id: str, label: str) -> str:
    if f'self.beat("{beat_id}"' in source or f"self.beat('{beat_id}'" in source:
        return source
    lines = source.splitlines(keepends=True)
    insert_at = _step_beat_insert_index(lines)
    indent = _line_indent(lines[insert_at]) if insert_at < len(lines) else "        "
    beat_line = f'{indent}self.beat("{beat_id}", label="{label}")\n'
    lines.insert(insert_at, beat_line)
    return "".join(lines)


def _step_beat_insert_index(lines: list[str]) -> int:
    for index in range(len(lines) - 1, -1, -1):
        if "self.wait(" in lines[index]:
            return index
    for index in range(len(lines) - 1, -1, -1):
        line = lines[index]
        if line.strip() and line.startswith("        "):
            return index + 1
    return len(lines)


def _line_indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())] or "        "


def _state_from_data(data: dict[str, Any]) -> AuthoringSessionState:
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
        current_beat=str(data.get("current_beat", "empty")),
        revision_number=int(data.get("revision_number", 0)),
        live_status=str(data.get("live_status", "stopped")),
        updated_at=str(data.get("updated_at", _utc_now())),
        live_pid=data.get("live_pid") if data.get("live_pid") is None else int(data.get("live_pid")),
        live_source_root=data.get("live_source_root") if data.get("live_source_root") is None else str(data.get("live_source_root")),
        live_source_path=data.get("live_source_path") if data.get("live_source_path") is None else str(data.get("live_source_path")),
        last_error=data.get("last_error") if data.get("last_error") is None else str(data.get("last_error")),
    )


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
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
    if isinstance(exc, AuthoringSessionError):
        return {"code": exc.code, "message": exc.message, "detail": exc.detail}
    if isinstance(exc, movie_sessions.MovieSessionError):
        return {"code": exc.code, "message": exc.message, "detail": exc.detail}
    if isinstance(exc, staged_edits.StagedEditError):
        return {"code": exc.code, "message": exc.message, "detail": exc.detail}
    return {"code": "internal_error", "message": str(exc), "detail": None}
