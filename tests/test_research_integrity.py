"""Research acceptance fixtures have explicit expectations, independent of the checker."""
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from manim_studio.research import ResearchLog, _json
from manim_studio.research_artifacts import ResearchArtifacts
from manim_studio.research_integrity import check, snapshot
from manim_studio.research_jobs import ResearchJobs, JobLock
from manim_studio.research_sessions import ResearchSessionError, ResearchSessions
from manim_studio.research_time import ResearchTiming


@pytest.fixture
def research(tmp_path):
    root = tmp_path / 'פרויקט מחקר'; root.mkdir()
    log = ResearchLog(root); log.configure(True)
    session = log.start_session('Vectors')
    prompt = log.record_prompt(session, 'PRIVATE_PROMPT')
    return root, log, session, prompt, ResearchJobs(root)


def plan(log, session):
    with log.connection() as db:
        db.execute('BEGIN')
        return snapshot(log, db, session)


def codes(report):
    return {f['code'] for f in report['findings']}


def test_delivery_unverified_even_without_checksum_failures(research):
    root, log, session, _, _ = research
    report = check(plan(log, session), root, deep=True)
    assert report['domains']['conversation'] == 'unverified'
    assert report['domains']['links'] == 'valid'
    assert report['domains']['content'] == 'valid'
    assert codes(report) == {'source_delivery_unverified', 'human_time_missing', 'model_metadata_unknown'}


def test_quick_check_does_not_claim_deep_content_validation(research):
    root, log, session, _, _ = research
    report = check(plan(log, session), root)
    assert 'content_bytes_unverified' in codes(report)
    assert report['domains']['content'] == 'unverified'


def test_global_seq_gaps_other_session_and_null_prompt_are_valid(research):
    root, log, session, _, _ = research
    other = log.start_session('other'); log.record_prompt(other, 'OTHER_SECRET')
    action = log.begin_action(session, 'render_scene', {}, prompt_id=None)
    log.end_action(session, action, {'ok': True}, .5)
    report = check(plan(log, session), root, True)
    assert report['domains']['links'] == 'valid'
    assert not any(f['severity'] == 'error' for f in report['findings'])


def test_cross_session_wrong_parent_and_missing_finish(research):
    root, log, session, _, _ = research
    other = log.start_session('other'); foreign = log.record_prompt(other, 'OTHER')
    action = log.begin_action(session, 'render_scene', {})
    with log.connection() as db:
        db.execute('UPDATE events SET prompt_id=? WHERE id=?', (foreign, action))
    report = check(plan(log, session), root, True)
    assert codes(report) >= {'event_reference_invalid', 'action_pending_or_interrupted'}
    assert report['domains']['links'] == 'invalid'


def test_duplicate_completion_detected(research):
    root, log, session, _, _ = research
    a = log.begin_action(session, 'render', {})
    log.end_action(session, a, {}, 1); log.end_action(session, a, {}, 1)
    assert 'duplicate_action_finish' in codes(check(plan(log, session), root, True))


def test_source_snapshot_missing_and_corrupt_bytes(research):
    root, log, session, _, _ = research
    (root / 'lesson-plan.md').write_text('lesson', encoding='utf-8')
    log.begin_action(session, 'render', {})
    data = plan(log, session)
    sha = hashlib.sha256(b'lesson').hexdigest()
    assert sha in data['contents']
    with log.connection() as db:
        db.execute('UPDATE blobs SET content=? WHERE sha256=?', (b'wrong!', sha))
    assert 'content_missing_or_corrupt' in codes(check(data, root, True))
    with log.connection() as db:
        db.execute('DELETE FROM blobs WHERE sha256=?', (sha,))
    assert 'content_reference_missing' in codes(check(plan(log, session), root, True))


def test_artifact_purge_is_explicit_not_corruption(research):
    root, log, session, _, _ = research; a = ResearchArtifacts(root)
    with log.connection() as db:
        retained = a.retain(db, session, 'x.md', 'candidate_source', b'abc')
    a.dispatch('purge', dict(session_id=session, artifact_id=retained['artifact_id'], expected_revision=retained['revision'], request_id='purge'))
    a.collect_garbage()
    report = check(plan(log, session), root, True)
    assert 'artifact_purged' in codes(report)
    assert 'content_reference_missing' not in codes(report)


def test_classification_corrections_skip_and_clear_replay(research):
    root, log, session, prompt, _ = research
    from manim_studio.prompt_classifications import PromptClassifications
    service = PromptClassifications(root); head = None
    for i, action in enumerate(('save', 'save', 'clear', 'skip')):
        params = dict(project_id=plan(log, session)['project_id'], session_id=session, prompt_id=prompt, expected_human_head=head, request_id=str(i))
        if action == 'save':
            params.update(prompt_type='continuation', reasons=[])
        head = service.dispatch(action, params)['event_id']
    report = check(plan(log, session), root, True)
    assert report['domains']['links'] == 'valid'


def test_check_job_is_idempotent_durable_and_stale_only_on_own_events(research):
    root, log, session, _, jobs = research
    params = dict(session_id=session, request_id='check', deep=True)
    first = jobs.dispatch('integrity', 'check', params)
    assert jobs.dispatch('integrity', 'check', dict(reversed(list(params.items())))) == first
    with pytest.raises(ResearchSessionError, match='request_id_conflict'):
        jobs.dispatch('integrity', 'check', dict(params, deep=False))
    assert ResearchJobs(root).work_once()
    status = jobs.dispatch('integrity', 'status', dict(session_id=session, job_id=first['job_id']))['jobs'][0]
    assert status['status'] == 'completed' and not status['stale']
    log.record_prompt(log.start_session('Other'), 'other')
    assert not jobs.dispatch('integrity', 'status', dict(session_id=session))['jobs'][0]['stale']
    log.record_prompt(session, 'new')
    assert jobs.dispatch('integrity', 'status', dict(session_id=session))['jobs'][0]['stale']


def test_cancel_is_durable_and_wrong_session_cannot_cancel(research):
    root, log, session, _, jobs = research
    id = jobs.dispatch('integrity', 'check', dict(session_id=session, deep=True, request_id='a'))['job_id']
    with pytest.raises(ResearchSessionError, match='job_not_found'):
        jobs.dispatch('integrity', 'cancel', dict(session_id=log.start_session('Other'), job_id=id, request_id='wrong'))
    jobs.dispatch('integrity', 'cancel', dict(session_id=session, job_id=id, request_id='cancel'))
    assert not jobs.work_once()
    assert jobs.dispatch('integrity', 'status', dict(session_id=session))['jobs'][0]['status'] == 'cancelled'


def test_recovery_never_replays_creation_or_invents_outcome(research):
    root, log, session, _, jobs = research
    action = log.begin_action(session, 'accept_proposal', {})
    params = dict(session_id=session, request_id='recover')
    result = jobs.dispatch('integrity', 'reconcile', params)
    assert result == {'repairs': [], 'unknown_outcomes_preserved': True}
    assert jobs.dispatch('integrity', 'reconcile', params) == result
    with log.connection() as db:
        assert db.execute("SELECT count(*) FROM events WHERE type='action.finished'").fetchone()[0] == 0
        assert db.execute('SELECT type FROM events WHERE id=?', (action,)).fetchone()[0] == 'action.started'


def test_recovery_uses_matching_copy_never_live_source(research):
    root, log, session, _, jobs = research; a = ResearchArtifacts(root)
    with log.connection() as db:
        art = a.retain(db, session, 'lesson.md', 'candidate_source', b'exact')
        db.execute('INSERT INTO blobs VALUES (?,?)', (art['sha256'], b'exact'))
    a._content_path(art['sha256']).write_bytes(b'wrong')
    (root / 'lesson.md').write_text('different live file')
    assert 'content_missing_or_corrupt' in codes(check(plan(log, session), root, True))
    result = jobs.dispatch('integrity', 'reconcile', dict(session_id=session, request_id='recovery'))
    assert result['repairs'][0]['code'] == 'content_copy_restored'
    assert a._content_path(art['sha256']).read_bytes() == b'exact'
    assert (root / 'lesson.md').read_text() == 'different live file'


def test_recovery_timer_preserves_last_checkpoint(research):
    root, log, session, _, jobs = research
    timer = ResearchTiming(root)
    state = timer.dispatch('status', dict(session_id=session))
    started = timer.dispatch('start', dict(session_id=session, client_id='timer-client', expected_revision=state['revision'], category='authoring', request_id='start'))
    interval = started['active']['interval_id']
    with log.connection() as db:
        row = db.execute('SELECT payload FROM timing_intervals WHERE id=?', (interval,)).fetchone()
        data = json.loads(row[0]); data['last_wall'] = time.time() - 500
        data['last_monotonic'] = time.monotonic() - 500
        db.execute('UPDATE timing_intervals SET payload=? WHERE id=?', (_json(data), interval))
    jobs.dispatch('integrity', 'reconcile', dict(session_id=session, request_id='recovery'))
    with log.connection() as db:
        data = json.loads(db.execute('SELECT payload FROM timing_intervals WHERE id=?', (interval,)).fetchone()[0])
    assert data['status'] == 'interrupted' and data['measured_seconds'] == 0 and data['tail_unknown']


def test_migration_v6_backup_and_future_schema_rejection(research):
    root, log, session, _, jobs = research
    with log.connection() as db:
        db.execute('DROP TABLE research_pins'); db.execute('DROP TABLE research_jobs'); db.execute('PRAGMA user_version=6')
    jobs.dispatch('integrity', 'status', dict(session_id=session))
    backups = list(log.directory.glob('migration-backup-*.sqlite3'))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 6
    with log.connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 7
        db.execute('PRAGMA user_version=99')
    with pytest.raises(ValueError, match='unsupported_schema'):
        jobs.dispatch('integrity', 'status', dict(session_id=session))


def test_migration_failure_keeps_v6_unchanged(research):
    root, log, session, _, jobs = research
    with log.connection() as db:
        db.execute('PRAGMA user_version=6')
    with patch('manim_studio.research_schema.INTEGRITY', 'CREATE TABLE invalid( broken syntax;'):
        with pytest.raises(ResearchSessionError, match='storage'):
            jobs.dispatch('integrity', 'status', dict(session_id=session))
    with sqlite3.connect(log.database) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 6


def test_worker_lock_fails_closed_and_releases_on_exit(research):
    root, *_ = research; path = root / 'worker.lock'
    with JobLock(path):
        result = subprocess.run([sys.executable, '-c',
            'from pathlib import Path; from manim_studio.research_jobs import JobLock; '
            'lock=JobLock(Path(__import__("sys").argv[1])); lock.__enter__()', str(path)], capture_output=True, timeout=5)
        assert result.returncode != 0
    with JobLock(path):
        pass
