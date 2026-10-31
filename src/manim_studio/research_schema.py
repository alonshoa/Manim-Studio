"""Transactional, backed-up migrations for the shared research ledger."""

import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path

VERSION = 5
BASE = """
CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE, session_id TEXT NOT NULL,
    prompt_id TEXT, parent_id TEXT, type TEXT NOT NULL,
    timestamp TEXT NOT NULL, actor TEXT NOT NULL, stage TEXT NOT NULL,
    payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS blobs (sha256 TEXT PRIMARY KEY, content BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS research_sessions (
    session_id TEXT PRIMARY KEY, title TEXT NOT NULL, topic TEXT NOT NULL,
    state TEXT NOT NULL, revision INTEGER NOT NULL, capture_epoch INTEGER NOT NULL,
    created_at TEXT NOT NULL, finished_at TEXT);
CREATE TABLE IF NOT EXISTS research_sources (
    source_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL UNIQUE,
    session_id TEXT UNIQUE, transcript_path TEXT, last_turn_id TEXT,
    last_hook_at TEXT NOT NULL, connected INTEGER NOT NULL, protocol_version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS research_clients (
    client_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, client_type TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_requests (
    request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL);
"""
ARTIFACTS = """
CREATE TABLE IF NOT EXISTS artifact_policies (scope TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_artifacts (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS artifacts_session ON research_artifacts(session_id);
CREATE TABLE IF NOT EXISTS artifact_jobs (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS artifact_snapshots (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_decisions (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, payload TEXT NOT NULL);
"""


def migrate(db, database, timeout=30):
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version > VERSION:
        raise ValueError("unsupported_schema: use a matching Studio version")
    if version == VERSION:
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        # A concurrent upgrader may have completed while we waited for the lock.
        if db.execute("PRAGMA user_version").fetchone()[0] == VERSION:
            db.commit()
            return
        existing = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='events'"
        ).fetchone()
        if existing:
            backup = Path(database).with_name(
                "migration-backup-" + uuid.uuid4().hex + ".sqlite3"
            )
            partial = backup.with_suffix(".sqlite3.tmp")
            deadline = time.monotonic() + timeout

            def progress(status, remaining, total):
                if time.monotonic() > deadline:
                    raise sqlite3.OperationalError("Migration backup timed out")

            try:
                # A separate reader avoids backing up a connection with an active write txn.
                with (
                    closing(sqlite3.connect(database, timeout=timeout)) as source,
                    closing(sqlite3.connect(partial)) as target,
                ):
                    source.backup(target, pages=64, progress=progress, sleep=0.01)
                partial.replace(backup)
            finally:
                partial.unlink(missing_ok=True)
        for statement in (BASE + ARTIFACTS).split(";"):
            if statement.strip():
                db.execute(statement)
        db.execute("PRAGMA user_version=5")
        db.commit()
    except BaseException:
        db.rollback()
        raise
