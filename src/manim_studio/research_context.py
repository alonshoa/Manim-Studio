"""Allowlisted, provenance-labelled run metadata. No credentials or model calls."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import platform
import subprocess
import sys
import sysconfig
import tempfile
import uuid
from datetime import UTC, datetime

MODEL_KEYS = (
    "provider",
    "model",
    "version",
    "deployment",
    "client_version",
    "client_surface",
)
SETTING_KEYS = (
    "temperature",
    "top_p",
    "seed",
    "max_tokens",
    "renderer",
    "profile",
    "effort",
    "summary",
    "client_version",
    "code_revision",
)


def filtered(value, keys):
    if not isinstance(value, dict):
        return None
    clean = {}
    for key in keys:
        item = value.get(key)
        if item is not None and not isinstance(item, (str, int, float, bool)):
            continue
        if isinstance(item, float) and not math.isfinite(item):
            continue
        if isinstance(item, str) and len(item) > 512:
            continue
        clean[key] = item
    return clean


def os_metadata():
    """Read local OS facts without platform.uname's Windows WMI queries.

    platform.system/release/machine all fill the same uname cache on Windows.
    Its WMI queries have no caller-controlled timeout and may block an MCP
    worker's first request. Use direct APIs instead; missing facts stay null.
    """
    if sys.platform == "win32":
        release = None
        try:
            version = sys.getwindowsversion()
            release = f"{version.major}.{version.minor}.{version.build}"
        except (AttributeError, OSError):
            pass
        return {
            "system": "Windows",
            "release": release,
            "architecture": sysconfig.get_platform(),
            "architecture_source": "python_build_platform",
        }
    try:
        info = os.uname()
    except (AttributeError, OSError):
        return {"system": sys.platform, "release": None, "architecture": None}
    return {
        "system": info.sysname,
        "release": info.release,
        "architecture": info.machine,
    }


def command_output(command, timeout=0.5):
    """Bounded metadata command, even when descendants inherit output handles.

    Windows subprocess.run(capture_output=True) drains its PIPE readers after
    killing a timed-out process, without a second deadline. A surviving child
    can keep those pipes open indefinitely. A regular temporary output file
    avoids waiting for EOF, and DEVNULL isolates commands from MCP's stdin.
    """
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            return None
        output.seek(0)
        return output.read(65536).decode("utf-8")


def runtime_probe(root):
    from manim_studio import __version__
    from manim_studio.research_schema import VERSION

    data = {
        "studio_version": __version__,
        "schema_version": VERSION,
        "taxonomy_version": 1,
        "python_version": platform.python_version(),
        "os": os_metadata(),
        "git": {"commit": None, "dirty": None, "provenance": "unavailable"},
    }
    try:
        commit = command_output(
            ["git", "--no-optional-locks", "-C", str(root), "rev-parse", "HEAD"]
        )
        if commit is not None and len(commit.strip()) == 40:
            data["git"] = {
                "commit": commit.strip(),
                "dirty": None,
                "provenance": "observed",
            }
            state = command_output(
                [
                    "git",
                    "--no-optional-locks",
                    "-C",
                    str(root),
                    "status",
                    "--porcelain",
                    "--untracked-files=normal",
                ]
            )
            if state is not None:
                data["git"]["dirty"] = bool(state.strip())
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        pass
    data["packages"] = {}
    for package in ("manim", "manim-slides", "mcp"):
        try:
            data["packages"][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            data["packages"][package] = None
    return data


def record_context(
    log,
    db,
    session,
    client_id=None,
    *,
    runtime=None,
    model=None,
    settings=None,
    extension_version=None,
):
    client_id = (
        client_id
        if isinstance(client_id, str) and len(client_id) <= 512
        else "unknown-client"
    )
    prior = db.execute(
        "SELECT * FROM run_contexts WHERE session_id=? AND client_id=? ORDER BY rowid DESC LIMIT 1",
        (session, client_id),
    ).fetchone()
    previous = json.loads(prior["payload"]) if prior else {}
    data = {
        "runtime": runtime if runtime is not None else previous.get("runtime"),
        "model": filtered(model, MODEL_KEYS),
        "settings": filtered(settings, SETTING_KEYS),
        "extension_version": extension_version
        if isinstance(extension_version, str) and len(extension_version) <= 128
        else previous.get("extension_version"),
        "provenance": {
            "runtime": "observed"
            if runtime is not None
            else "previously_observed"
            if previous.get("runtime")
            else "unavailable",
            "model": "client_reported" if model is not None else "unavailable",
            "settings": "client_reported" if settings is not None else "unavailable",
        },
    }
    # Stable identity ignores provenance wording about a reused runtime snapshot.
    fingerprint = hashlib.sha256(
        json.dumps(
            {k: v for k, v in data.items() if k != "provenance"},
            sort_keys=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    if prior and prior["fingerprint"] == fingerprint:
        return prior["id"]
    id = str(uuid.uuid4())
    data.update(client_id=client_id, observed_at=datetime.now(UTC).isoformat())
    db.execute(
        "INSERT INTO run_contexts VALUES (?,?,?,?,?)",
        (
            id,
            session,
            client_id,
            fingerprint,
            json.dumps(data, ensure_ascii=False, allow_nan=False),
        ),
    )
    log._event(db, "run.context.observed", session, dict(run_context_id=id, **data))
    return id


def context_for_event(log, db, kind, session, payload, parent=None):
    if kind not in (
        "prompt.recorded",
        "model.responded",
        "action.started",
        "action.finished",
        "client.turn.completed",
        "client.turn.interrupted",
    ):
        return payload
    if kind == "action.finished" and parent:
        row = db.execute(
            "SELECT payload FROM events WHERE id=? AND session_id=?", (parent, session)
        ).fetchone()
        if row:
            id = json.loads(row[0]).get("run_context_id")
            if id:
                return dict(payload, run_context_id=id)
    source = payload.get("source") or {}
    client = source.get("client_id") or (
        "codex:" + source["thread_id"]
        if isinstance(source.get("thread_id"), str)
        else None
    )
    if "model" in payload:
        id = record_context(
            log,
            db,
            session,
            client,
            model=payload.get("model"),
            settings=payload.get("run_settings"),
        )
    else:
        row = db.execute(
            "SELECT id FROM run_contexts WHERE session_id=? AND client_id=? ORDER BY rowid DESC LIMIT 1",
            (session, client or "unknown-client"),
        ).fetchone()
        if row:
            id = row[0]
        else:
            id = record_context(
                log, db, session, client, settings=payload.get("arguments")
            )
    return dict(payload, run_context_id=id)
