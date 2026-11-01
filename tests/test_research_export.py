import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.test_research_integrity import research, plan
from manim_studio.research import _json
from manim_studio.research_artifacts import ResearchArtifacts
from manim_studio.research_export import verify_export, restore_export, file_digest
from manim_studio.research_jobs import ResearchJobs
from manim_studio.research_sessions import ResearchSessionError


def export(research, tmp_path, mode='full', name='research.zip'):
    root, log, session, _, jobs = research
    result = jobs.dispatch('exports', 'start', dict(session_id=session, request_id=name, mode=mode, destination=str(tmp_path/name)))
    jobs.work_once()
    status = jobs.dispatch('exports', 'status', dict(session_id=session, job_id=result['job_id']))['jobs'][0]
    assert status['status'] == 'completed', status
    return tmp_path/name, result


def rewrite(path, change):
    with zipfile.ZipFile(path) as z:
        files = {n: z.read(n) for n in z.namelist()}
    change(files)
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in files.items():
            z.writestr(name, data)


def rehash(files):
    m = json.loads(files['manifest.json'])
    for name in m['members']:
        m['members'][name] = dict(size=len(files[name]), sha256=hashlib.sha256(files[name]).hexdigest())
    files['manifest.json'] = _json(m).encode()


def test_full_export_replays_without_original_db_and_exact_bytes(research, tmp_path):
    root, log, session, prompt, jobs = research
    (root/'lesson-plan.md').write_bytes('מקור\n'.encode())
    action = log.begin_action(session, 'render_scene', {}, prompt_id=prompt)
    log.end_action(session, action, dict(ok=False), 2, prompt_id=prompt, error='RenderError')
    path, result = export(research, tmp_path)
    expected = hashlib.sha256('מקור\n'.encode()).hexdigest()
    shutil.rmtree(root)
    verified = verify_export(path)
    assert verified['valid'] and verified['export_id'] == result['job_id']
    restore_export(path, tmp_path/'restored')
    assert (tmp_path/'restored/content/sha256'/expected).read_bytes() == 'מקור\n'.encode()
    with pytest.raises(FileExistsError):
        restore_export(path, tmp_path/'restored')


def test_scope_excludes_other_session_even_shared_physical_content(research, tmp_path):
    root, log, session, _, jobs = research; a = ResearchArtifacts(root)
    other = log.start_session('OTHER_SESSION_PRIVATE'); log.record_prompt(other, 'OTHER_SECRET')
    with log.connection() as db:
        a.retain(db, session, 'shared.md', 'candidate_source', b'shared')
        a.retain(db, other, 'shared.md', 'candidate_source', b'shared')
        a.retain(db, other, 'private.md', 'candidate_source', b'OTHER_ARTIFACT_SECRET')
    path, _ = export(research, tmp_path)
    with zipfile.ZipFile(path) as z:
        combined = b''.join(z.read(n) for n in z.namelist())
        assert b'OTHER_SECRET' not in combined and b'OTHER_ARTIFACT_SECRET' not in combined
        assert other.encode() not in combined
        assert z.read('content/sha256/' + hashlib.sha256(b'shared').hexdigest()) == b'shared'


def test_metadata_drops_free_text_at_all_known_nesting_points(research, tmp_path):
    root, log, session, prompt, jobs = research; secret = 'SENTINEL_FREE_TEXT'
    log.record_response(session, prompt, secret)
    with log.connection() as db:
        log._event(db, 'fixture', session, dict(text=secret, other=secret, feedback=secret,
             arguments=dict(text=secret), result=dict(text=secret), source=dict(text=secret, arguments=secret, client_id='C'),
             runtime=dict(api_key=secret, os=dict(text=secret)), settings=dict(api_key=secret)))
    a = ResearchArtifacts(root)
    with log.connection() as db:
        a.retain(db, session, 'lesson.md', 'candidate_source', secret.encode())
    path, _ = export(research, tmp_path, 'metadata')
    with zipfile.ZipFile(path) as z:
        assert not any(n.startswith('content/') for n in z.namelist())
        assert secret.encode() not in b''.join(z.read(n) for n in z.namelist())
        assert b'PRIVATE_PROMPT' not in b''.join(z.read(n) for n in z.namelist())
    assert verify_export(path)['mode'] == 'metadata'


def test_export_cutoff_immutable_across_new_events_and_corrections(research, tmp_path):
    root, log, session, _, jobs = research
    timer = __import__('manim_studio.research_time', fromlist=['ResearchTiming']).ResearchTiming(root)
    timer.dispatch('report', dict(session_id=session, client_id='C', category='authoring', seconds=12, request_id='report'))
    pending = jobs.dispatch('exports', 'start', dict(session_id=session, request_id='frozen', mode='full', destination=str(tmp_path/'frozen.zip')))
    log.record_prompt(session, 'LATER_EVENT_SHOULD_NOT_APPEAR')
    timer.dispatch('report', dict(session_id=session, client_id='C', category='authoring', seconds=99, request_id='later_report'))
    jobs.work_once()
    with zipfile.ZipFile(tmp_path/'frozen.zip') as z:
        assert b'LATER_EVENT_SHOULD_NOT_APPEAR' not in z.read('events.jsonl')
        assert json.loads(z.read('summaries/time.json'))['self_reported_seconds']['authoring'] == 12
        assert json.loads(z.read('manifest.json'))['snapshot_seq'] == pending['snapshot_seq']
    assert verify_export(tmp_path/'frozen.zip')['valid']


def test_export_pin_blocks_purge_and_is_released_after_cancel(research, tmp_path):
    root, log, session, _, jobs = research; a = ResearchArtifacts(root)
    with log.connection() as db:
        artifact = a.retain(db, session, 'video.mp4', 'preview_video', b'video')
    pending = jobs.dispatch('exports','start', dict(session_id=session, request_id='export', mode='full', destination=str(tmp_path/'pin.zip')))
    args = dict(session_id=session, request_id='purge', artifact_id=artifact['artifact_id'], expected_revision=artifact['revision'])
    with pytest.raises(ResearchSessionError, match='artifact_pinned'):
        a.dispatch('purge', args)
    jobs.dispatch('exports','cancel', dict(session_id=session, job_id=pending['job_id'], request_id='cancel'))
    a.dispatch('purge', args); a.collect_garbage()
    assert not a._content_path(artifact['sha256']).exists()
    assert not (tmp_path/'pin.zip').exists()


def test_cancel_during_write_never_publishes_partial(research, tmp_path):
    root, log, session, _, jobs = research
    pending = jobs.dispatch('exports','start', dict(session_id=session, request_id='export', mode='full', destination=str(tmp_path/'cancel.zip')))
    from manim_studio.research_export import write_package
    def cancelled(*args):
        jobs.dispatch('exports','cancel', dict(session_id=session, job_id=pending['job_id'], request_id='cancel'))
        return write_package(*args)
    with patch('manim_studio.research_export.write_package', side_effect=cancelled):
        jobs.work_once()
    assert not (tmp_path/'cancel.zip').exists()
    assert not list(tmp_path.glob('*.partial'))
    assert jobs.dispatch('exports','status',dict(session_id=session))['jobs'][0]['status'] == 'cancelled'


def test_retry_same_request_returns_same_archive(research, tmp_path):
    root, log, session, _, jobs = research
    path, result = export(research, tmp_path)
    old = file_digest(path)
    again = jobs.dispatch('exports','start',dict(session_id=session, request_id='research.zip', mode='full', destination=str(path)))
    assert again == result and not jobs.work_once() and file_digest(path) == old


def test_destination_exists_at_publication_is_not_overwritten(research, tmp_path):
    root, log, session, _, jobs = research
    path = tmp_path/'existing.zip'
    jobs.dispatch('exports','start',dict(session_id=session, request_id='export', mode='full', destination=str(path)))
    path.write_bytes(b'foreign')
    jobs.work_once()
    assert path.read_bytes() == b'foreign'
    assert jobs.dispatch('exports','status',dict(session_id=session))['jobs'][0]['status'] == 'failed'


def test_process_crash_after_publish_adopts_only_durable_hash(research, tmp_path):
    root, log, session, _, jobs = research; path = tmp_path/'crash.zip'
    jobs.dispatch('exports','start',dict(session_id=session, request_id='export', mode='full', destination=str(path)))
    link = os.link
    def crash(source, target):
        link(source, target)
        raise KeyboardInterrupt('simulate process death')
    with patch('manim_studio.research_jobs.os.link', side_effect=crash):
        with pytest.raises(KeyboardInterrupt):
            jobs.work_once()
    original = file_digest(path)
    ResearchJobs(root).work_once()
    status = jobs.dispatch('exports','status',dict(session_id=session))['jobs'][0]
    assert status['status'] == 'completed' and status['archive_sha256'] == original
    assert verify_export(path)['valid']


def test_mid_write_failure_no_final_and_releases_pins(research, tmp_path):
    root, log, session, _, jobs = research
    jobs.dispatch('exports','start',dict(session_id=session, request_id='export', mode='full', destination=str(tmp_path/'fail.zip')))
    with patch('manim_studio.research_export.write_package', side_effect=OSError('disk full')):
        jobs.work_once()
    assert not (tmp_path/'fail.zip').exists()
    status = jobs.dispatch('exports','status',dict(session_id=session))['jobs'][0]
    assert status['status'] == 'failed' and status['error'] == 'storage_or_export_error'
    with log.connection() as db:
        assert db.execute('SELECT count(*) FROM research_pins').fetchone()[0] == 0


def test_missing_corrupt_content_can_be_exported_as_declared_partial(research, tmp_path):
    root, log, session, _, jobs = research; a = ResearchArtifacts(root)
    with log.connection() as db:
        artifact = a.retain(db, session, 'video.mp4', 'preview_video', b'video')
    a._content_path(artifact['sha256']).unlink()
    path, _ = export(research, tmp_path)
    assert verify_export(path)['coverage'] == 'partial'
    with zipfile.ZipFile(path) as z:
        assert artifact['sha256'] in json.loads(z.read('manifest.json'))['unavailable']


@pytest.mark.parametrize('name',['../escape','/absolute','C:/windows','a\\b'])
def test_unsafe_zip_path_rejected(research, tmp_path, name):
    path, _ = export(research, tmp_path)
    with zipfile.ZipFile(path, 'a') as z:
        z.writestr(name, b'evil')
    with pytest.raises(ValueError):
        verify_export(path)
    assert not (tmp_path.parent/'escape').exists()


def test_checksum_mismatch_rejected(research, tmp_path):
    path, _ = export(research, tmp_path)
    rewrite(path, lambda files: files.update({'events.jsonl': files['events.jsonl'] + b' '}))
    with pytest.raises(ValueError):
        verify_export(path)


def test_cross_session_tamper_even_with_updated_hash_rejected(research, tmp_path):
    path, _ = export(research, tmp_path)
    def tamper(files):
        events = [json.loads(e) for e in files['events.jsonl'].splitlines()]
        events[-1]['session_id'] = 'other'
        files['events.jsonl'] = ('\n'.join(_json(e) for e in events)+'\n').encode(); rehash(files)
    rewrite(path, tamper)
    with pytest.raises(ValueError):
        verify_export(path)


def test_duplicate_member_and_symlink_rejected(research, tmp_path):
    path, _ = export(research, tmp_path)
    with zipfile.ZipFile(path, 'a') as z:
        with pytest.warns(UserWarning):
            z.writestr('events.jsonl', b'')
    with pytest.raises(ValueError):
        verify_export(path)
    path, _ = export(research, tmp_path, name='symlink.zip')
    with zipfile.ZipFile(path, 'a') as z:
        info = zipfile.ZipInfo('link'); info.create_system = 3; info.external_attr = (0o120777 << 16)
        z.writestr(info, b'/outside')
    with pytest.raises(ValueError):
        verify_export(path)


def test_source_and_db_destinations_rejected(research, tmp_path):
    root, log, session, _, jobs = research
    for destination in (root/'source.zip', log.database):
        with pytest.raises(ValueError):
            jobs.dispatch('exports','start',dict(session_id=session, request_id=str(destination), mode='full', destination=str(destination)))


def test_worker_subprocess_rpc_and_cli_verify_without_authoring_queue(research, tmp_path):
    root, log, session, _, jobs = research
    path = tmp_path/'subprocess.zip'
    payload = dict(session_id=session, request_id='rpc', mode='full', destination=str(path))
    request = _json(dict(id=1,method='exports.start',params=payload))+'\n'
    result = subprocess.run([sys.executable,'-m','manim_studio.research_cli','--root',str(root),'rpc'],input=request, text=True,encoding='utf-8',capture_output=True,timeout=10)
    response = json.loads(result.stdout); assert response['ok'], result.stderr
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        status = jobs.dispatch('exports','status',dict(session_id=session))['jobs'][0]
        if status['status'] in ('completed','failed'):
            break
        time.sleep(.1)
    assert status['status'] == 'completed', status
    assert verify_export(path)['valid']
    # Standalone verifier module needs no Manim/renderer or original database.
    shutil.rmtree(root)
    code = 'from manim_studio.research_export import verify_export; import sys; assert verify_export(sys.argv[1])["valid"]'
    result = subprocess.run([sys.executable,'-c',code,str(path)],capture_output=True,timeout=10)
    assert result.returncode == 0, result.stderr


def test_combined_authoring_reject_failed_render_accept_and_export(tmp_path):
    """Real authoring services, deterministic render double; native render is a CI gate."""
    from tests.test_authoring_sessions import AuthoringFixture, FakeRenderRunner, fake_manim_module
    from manim_studio.research import ResearchLog
    from manim_studio.authoring_sessions import AuthoringSessionError
    from manim_studio.research_time import ResearchTiming
    from manim_studio.prompt_classifications import PromptClassifications
    with AuthoringFixture() as f, fake_manim_module(), patch('manim_studio.research_artifacts.kick_worker'):
        log = ResearchLog(f.root); log.configure(True)
        (f.root/'lesson-plan.md').write_text('lesson original')
        sid = log.start_session('research'); prompt = log.record_prompt(sid, 'create')
        other = log.start_session('other'); log.record_prompt(other, 'OTHER_SECRET_COMBINED')
        controller = f.controller(); aid = controller.start_session(title='Story',deck_id='story')['session_id']
        meta = dict(session_id=sid,prompt_id=prompt,decision_origin='human',origin_evidence='explicit_test_click')
        controller.propose_next_movie_step(aid, 'self.add(Dot())')
        controller.dispatch('reject_proposal',dict(session_id=aid,_research=meta))
        controller.propose_next_movie_step(aid, 'self.wait(0.1)')
        controller.render_runner = FakeRenderRunner(returncode=1,stderr='failed render')
        with pytest.raises(AuthoringSessionError):
            controller.dispatch('accept_proposal',dict(session_id=aid,_research=meta))
        controller.render_runner = FakeRenderRunner(returncode=0)
        controller.dispatch('accept_proposal',dict(session_id=aid,_research=meta))
        archive = ResearchArtifacts(f.root)
        while archive.work_once():
            pass
        decisions = archive.dispatch('list',dict(session_id=sid))['decisions']
        assert [d['status'] for d in decisions] == ['completed','failed','completed']
        assert [d['kind'] for d in decisions] == ['reject','accept','accept']
        classifications = PromptClassifications(f.root)
        project = plan(log,sid)['project_id']
        result = classifications.dispatch('save',dict(project_id=project,session_id=sid,prompt_id=prompt,request_id='first',expected_human_head=None,prompt_type='corrective',reasons=['technical_render']))
        classifications.dispatch('save',dict(project_id=project,session_id=sid,prompt_id=prompt,request_id='correction',expected_human_head=result['event_id'],prompt_type='continuation',reasons=[]))
        ResearchTiming(f.root).dispatch('report',dict(session_id=sid,request_id='time',client_id='C',category='authoring',seconds=30))
        log.configure(False)  # Reading/annotation/export remain available after collection stops.
        jobs = ResearchJobs(f.root)
        path, _ = export((f.root,log,sid,prompt,jobs),tmp_path)
        with zipfile.ZipFile(path) as z:
            data = json.loads(z.read('snapshot.json'))
            assert [r['payload']['status'] for r in data['projections']['research_decisions']] == ['completed','failed','completed']
            assert json.loads(z.read('summaries/time.json'))['self_reported_seconds']['authoring'] == 30
            assert b'OTHER_SECRET_COMBINED' not in b''.join(z.read(n) for n in z.namelist())
        assert verify_export(path)['valid']
        with zipfile.ZipFile(path) as z:
            report = json.loads(z.read('integrity.json'))
            assert report['domains']['decisions'] == 'valid'
            assert report['domains']['links'] == 'valid'


def test_real_process_crash_before_publish_resumes_frozen_plan(research, tmp_path):
    root, log, session, _, jobs = research; path = tmp_path/'real-crash.zip'
    pending = jobs.dispatch('exports','start',dict(session_id=session,request_id='real-crash',mode='full',destination=str(path)))
    code = '''
import os,sys
from manim_studio.research_jobs import ResearchJobs
from manim_studio import research_export
original=research_export.write_package
def die(*args):
    original(*args)
    os._exit(27)
research_export.write_package=die
ResearchJobs(sys.argv[1]).work_once()
'''
    result = subprocess.run([sys.executable,'-c',code,str(root)],capture_output=True,timeout=10)
    assert result.returncode == 27, result.stderr
    assert not path.exists()
    log.record_prompt(session, 'AFTER_PROCESS_CRASH')
    jobs.work_once()
    assert verify_export(path)['snapshot_seq'] == pending['snapshot_seq']
    with zipfile.ZipFile(path) as z:
        assert b'AFTER_PROCESS_CRASH' not in z.read('events.jsonl')
