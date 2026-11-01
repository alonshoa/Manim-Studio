"""Durable integrity/export jobs on a dedicated worker, isolated from authoring."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from manim_studio.research import ResearchLog, _json
from manim_studio.research_artifacts import ResearchArtifacts
from manim_studio.research_integrity import snapshot, check, utc, fail
from manim_studio.research_sessions import ResearchSessionError

ACTIONS = {'integrity': ('check', 'status', 'findings', 'reconcile', 'cancel'),
           'exports': ('start', 'status', 'cancel', 'list')}
TERMINAL = ('completed', 'cancelled', 'failed')
_processes = {}


def destination_path(log, value):
    if not isinstance(value, str) or not value.strip():
        fail('destination_required')
    path = Path(value).expanduser().absolute()
    if any(part.is_symlink() or (part.exists() and getattr(part.lstat(), 'st_file_attributes', 0) & 0x400)
           for part in (path, *path.parents)):
        fail('unsafe_destination')
    path = path.resolve()
    if path.is_relative_to(log.root) or not path.parent.is_dir():
        fail('destination_must_be_outside_project')
    if path.exists():
        fail('destination_exists')
    if path.suffix.lower() != '.zip':
        fail('zip_destination_required')
    return str(path)


class ResearchJobs:
    def __init__(self, root):
        self.log = ResearchLog(root)

    def dispatch(self, namespace, action, payload):
        if action not in ACTIONS.get(namespace, ()) or not isinstance(payload, dict):
            fail('invalid_request')
        if not self.log.database.exists():
            fail('session_not_found')
        try:
            with self.log.connection(timeout=1) as db:
                mutation = action in ('check', 'start', 'cancel', 'reconcile')
                db.execute('BEGIN IMMEDIATE' if mutation else 'BEGIN')
                session = payload.get('session_id')
                if not db.execute("SELECT 1 FROM events WHERE id=? AND type='session.started'", (session,)).fetchone():
                    fail('session_not_found')
                project = db.execute("SELECT value FROM config WHERE key='project_id'").fetchone()[0]
                if payload.get('project_id', project) != project:
                    fail('project_mismatch')
                if not mutation:
                    return self._read(db, namespace, action, payload)
                request = payload.get('request_id')
                if not isinstance(request, str) or not 1 <= len(request) <= 512:
                    fail('request_id_required')
                fingerprint = hashlib.sha256(json.dumps(dict(namespace=namespace, action=action, payload=payload), sort_keys=True, allow_nan=False).encode()).hexdigest()
                prior = db.execute('SELECT * FROM research_requests WHERE request_id=?', (request,)).fetchone()
                if prior:
                    if prior['fingerprint'] != fingerprint:
                        fail('request_id_conflict')
                    return json.loads(prior['result'])
                if action == 'cancel':
                    row, data = self._job(db, session, payload.get('job_id'), namespace)
                    if row['status'] not in TERMINAL:
                        data['updated_at'] = utc()
                        db.execute("UPDATE research_jobs SET status='cancelled',payload=? WHERE id=?", (_json(data), row['id']))
                        db.execute('DELETE FROM research_pins WHERE job_id=?', (row['id'],))
                    result = dict(job_id=row['id'], status=row['status'] if row['status'] in TERMINAL else 'cancelled')
                elif action == 'reconcile':
                    result = self._reconcile(db, payload)
                else:
                    if namespace == 'exports' and payload.get('mode') not in ('metadata', 'full'):
                        fail('invalid_export_mode')
                    if namespace == 'integrity' and type(payload.get('deep', False)) is not bool:
                        fail('invalid_request')
                    # Capture the entire plan and all projections in the same transaction.
                    data = dict(snapshot=snapshot(self.log, db, session), created_at=utc(), updated_at=utc(),
                                mode=payload.get('mode'), deep=payload.get('deep', False), progress=0)
                    if namespace == 'exports':
                        data['destination'] = destination_path(self.log, payload.get('destination'))
                    id = str(uuid.uuid4())
                    db.execute('INSERT INTO research_jobs VALUES (?,?,?,?,?)',
                               (id, session, namespace, 'pending', _json(data)))
                    for sha, descriptor in data['snapshot']['contents'].items():
                        if descriptor['storage'] == 'archive':
                            db.execute('INSERT INTO research_pins VALUES (?,?)', (id, sha))
                    result = dict(job_id=id, session_id=session, status='pending', snapshot_seq=data['snapshot']['snapshot_seq'])
                db.execute('INSERT INTO research_requests VALUES (?,?,?)', (request, fingerprint, _json(result)))
                return result
        except (OSError, __import__('sqlite3').Error) as exc:
            raise ResearchSessionError('storage_error', 'Research storage is unavailable; retry the same request.') from exc

    def _job(self, db, session, id, namespace):
        row = db.execute('SELECT * FROM research_jobs WHERE id=? AND session_id=? AND kind=?',
                         (id, session, namespace)).fetchone()
        if not row:
            fail('job_not_found')
        return row, json.loads(row['payload'])

    def _read(self, db, namespace, action, p):
        seq = db.execute('SELECT COALESCE(max(seq),0) FROM events').fetchone()[0]
        if action == 'list' or not p.get('job_id'):
            rows = db.execute('SELECT * FROM research_jobs WHERE session_id=? AND kind=? ORDER BY rowid DESC LIMIT 100',
                              (p['session_id'], namespace)).fetchall()
        else:
            rows = [self._job(db, p['session_id'], p['job_id'], namespace)[0]]
        jobs = []
        for row in rows:
            data = json.loads(row['payload'])
            boundary = data['snapshot']['snapshot_seq']
            # New events in a different session do not make this session's report stale.
            stale = bool(db.execute('SELECT 1 FROM events WHERE session_id=? AND seq>? LIMIT 1',
                                     (p['session_id'], boundary)).fetchone())
            result = dict(job_id=row['id'], kind=row['kind'], status=row['status'],
                          snapshot_seq=boundary, stale=stale, progress=data.get('progress', 0),
                          created_at=data['created_at'], updated_at=data['updated_at'],
                          mode=data.get('mode'), destination=data.get('destination'),
                          error=data.get('error'), archive_sha256=data.get('archive_sha256'),
                          report=data.get('report'))
            jobs.append(result)
        return dict(session_id=p['session_id'], jobs=jobs, current_seq=seq)

    def _reconcile(self, db, p):
        session = p['session_id']; repairs = []
        from manim_studio.research_time import ResearchTiming
        timing = ResearchTiming(self.log.root)
        active = timing._active(db)
        if active and active['session_id'] == session:
            before = active['status']
            timing._expire(db)
            after = timing._interval(db, active['interval_id'])
            if before != after['status']:
                repairs.append(dict(code='timer_closed_at_checkpoint', entity_id=active['interval_id']))
        archive = ResearchArtifacts(self.log.root)
        retried = archive._mutate(db, 'retry_jobs', dict(session_id=session))
        if retried['requeued']:
            repairs.append(dict(code='artifact_jobs_requeued', count=retried['requeued']))
        for row in db.execute('SELECT id,payload FROM research_artifacts WHERE session_id=?', (session,)).fetchall():
            artifact = json.loads(row['payload'])
            if artifact.get('status') != 'retained':
                continue
            sha = artifact.get('sha256')
            try:
                archive._verify_content(archive._content_path(sha), sha, artifact['size'])
                continue
            except (ValueError, OSError):
                pass
            # Only use an independently stored exact copy; never read the live source path.
            blob = db.execute('SELECT content FROM blobs WHERE sha256=? AND length(content)<=1000000', (sha,)).fetchone()
            if blob and hashlib.sha256(blob[0]).hexdigest() == sha and len(blob[0]) == artifact['size']:
                target = archive._content_path(sha)
                if target.exists():
                    # Preserve corrupt bytes for diagnosis before installing a verified copy.
                    target.rename(target.with_name(target.name + '.corrupt-' + uuid.uuid4().hex))
                archive._put(blob[0])
                event = self.log._event(db, 'integrity.content_recovered', session,
                                       dict(artifact_id=row['id'], sha256=sha, evidence='matching_sqlite_blob'))
                repairs.append(dict(code='content_copy_restored', event_id=event))
        # Reconcile only from an existing, matching durable decision outcome event.
        # No name/file heuristic, no accept/render replay, and no fabricated action.finished.
        for row in db.execute("SELECT * FROM events WHERE session_id=? AND type='action.started'", (session,)).fetchall():
            if db.execute("SELECT 1 FROM events WHERE parent_id=? AND type IN ('action.finished','integrity.reconciled')", (row['id'],)).fetchone():
                continue
            evidence = db.execute("SELECT * FROM events WHERE session_id=? AND type='decision.completed' AND json_extract(payload,'$.action_id')=?",
                                  (session, row['id'])).fetchone()
            if evidence:
                event = self.log._event(db, 'integrity.reconciled', session,
                                       dict(evidence_event_id=evidence['id'], outcome='observed_decision_only'),
                                       parent_id=row['id'])
                repairs.append(dict(code='decision_evidence_linked', event_id=event))
        self.log._event(db, 'integrity.recovery_checked', session, dict(repairs=repairs, unknown_outcomes_preserved=True))
        return dict(repairs=repairs, unknown_outcomes_preserved=True)

    def _save(self, db, row, data, status=None):
        data['updated_at'] = utc()
        db.execute('UPDATE research_jobs SET status=?,payload=? WHERE id=?',
                   (status or row['status'], _json(data), row['id']))

    def work_once(self):
        """Caller holds a process-wide OS lock; a dead process releases it immediately."""
        with self.log.connection(timeout=1) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM research_jobs WHERE status IN ('pending','running') ORDER BY rowid LIMIT 1").fetchone()
            if not row:
                return False
            row = dict(row); data = json.loads(row['payload'])
            self._save(db, row, data, 'running'); row['status'] = 'running'
        staging = None
        last_progress = [0.0]
        def progress(index, total):
            if time.monotonic() - last_progress[0] < .2:
                return
            last_progress[0] = time.monotonic()
            with self.log.connection(timeout=1) as db:
                db.execute('BEGIN IMMEDIATE')
                current = db.execute('SELECT status FROM research_jobs WHERE id=?', (row['id'],)).fetchone()
                if current[0] == 'cancelled':
                    fail('job_cancelled')
                if index is not None and total:
                    data['progress'] = round(index / total * 100, 1)
                self._save(db, row, data)
        try:
            if row['kind'] == 'exports':
                from manim_studio.research_export import write_package, file_digest, verify_export
                destination = Path(data['destination'])
                staging = destination.with_name('.' + destination.name + '.' + row['id'] + '.partial')
                # A final archive published before a crash is adopted only against a durable hash.
                if destination.exists():
                    if (not data.get('archive_sha256') or destination.is_symlink()
                            or file_digest(destination, progress) != data['archive_sha256']
                            or verify_export(destination, progress)['export_id'] != row['id']):
                        fail('destination_exists')
                else:
                    destination_path(self.log, str(destination))
                    if staging.is_symlink():
                        fail('unsafe_destination')
                    staging.unlink(missing_ok=True)
                    report = check(data['snapshot'], self.log.root, deep=True, progress=progress)
                    data['report'] = report
                    data['archive_sha256'] = write_package(self.log.root, data['snapshot'], report, row['id'],
                                                          data['mode'], staging, progress)
                    # Persist hash before publication so retry after a crash can identify the same archive.
                    with self.log.connection(timeout=1) as db:
                        db.execute('BEGIN IMMEDIATE')
                        status = db.execute('SELECT status FROM research_jobs WHERE id=?', (row['id'],)).fetchone()[0]
                        if status == 'cancelled':
                            fail('job_cancelled')
                        self._save(db, row, data)
                    with self.log.connection(timeout=1) as db:
                        db.execute('BEGIN IMMEDIATE')
                        if db.execute('SELECT status FROM research_jobs WHERE id=?', (row['id'],)).fetchone()[0] == 'cancelled':
                            fail('job_cancelled')
                        # Atomic, no-overwrite publication on Windows/NTFS and POSIX filesystems.
                        destination_path(self.log, str(destination))
                        os.link(staging, destination)
                        data['progress'] = 100
                        self._save(db, row, data, 'completed')
                        db.execute('DELETE FROM research_pins WHERE job_id=?', (row['id'],))
                    staging.unlink(missing_ok=True)
                    return True
            else:
                data['report'] = check(data['snapshot'], self.log.root, deep=data['deep'], progress=progress)
            with self.log.connection(timeout=1) as db:
                db.execute('BEGIN IMMEDIATE')
                current = db.execute('SELECT status FROM research_jobs WHERE id=?', (row['id'],)).fetchone()[0]
                if current != 'cancelled':
                    data['progress'] = 100
                    self._save(db, row, data, 'completed')
                db.execute('DELETE FROM research_pins WHERE job_id=?', (row['id'],))
        except Exception as exc:
            with self.log.connection(timeout=1) as db:
                db.execute('BEGIN IMMEDIATE')
                current = db.execute('SELECT status FROM research_jobs WHERE id=?', (row['id'],)).fetchone()[0]
                if current != 'cancelled':
                    # Stable codes only; never store OS exception text containing user paths/content.
                    data['error'] = exc.code if isinstance(exc, ResearchSessionError) else 'storage_or_export_error'
                    self._save(db, row, data, 'failed')
                db.execute('DELETE FROM research_pins WHERE job_id=?', (row['id'],))
        finally:
            if staging and staging.exists() and not staging.is_symlink():
                staging.unlink(missing_ok=True)
        return True


class JobLock:
    def __init__(self, path):
        self.path = path
        self.fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            if os.name == 'nt':
                import msvcrt
                if not os.fstat(self.fd).st_size:
                    os.write(self.fd, b'0')
                os.lseek(self.fd, 0, 0)
                msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(self.fd)
            self.fd = None
            raise
        return self

    def __exit__(self, *args):
        if self.fd is not None:
            os.close(self.fd)


def worker_main(root):
    service = ResearchJobs(root)
    try:
        with JobLock(service.log.directory / 'integrity-worker.lock'):
            idle = time.monotonic() + 2
            while time.monotonic() < idle:
                if service.work_once():
                    idle = time.monotonic() + 2
                else:
                    time.sleep(.2)
    except (ResearchSessionError, OSError):
        return


def kick_worker(root):
    service = ResearchJobs(root)
    with service.log.connection(timeout=1) as db:
        if not db.execute("SELECT 1 FROM research_jobs WHERE status IN ('pending','running') LIMIT 1").fetchone():
            return
    key = str(service.log.root)
    if key in _processes and _processes[key].poll() is None:
        return
    _processes[key] = subprocess.Popen([sys.executable, '-m', 'manim_studio.research_jobs', str(service.log.root)],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=os.name != 'nt', creationflags=0x00000008 if os.name == 'nt' else 0)


if __name__ == '__main__':
    worker_main(Path(sys.argv[1]))
