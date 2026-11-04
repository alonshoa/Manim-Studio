"""Explicit, conservative research start/finish orchestration.

Never infer an active Codex thread from filesystem scans. Hook delivery must first
identify a source; a new conversation may be required after hook installation.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from manim_studio.research import ResearchLog
from manim_studio.research_sessions import ResearchSessions
from manim_studio.research_capture import CodexCapture
from manim_studio.research_jobs import ResearchJobs, kick_worker


def _request():
    return str(uuid.uuid4())


def _active(sessions):
    return [s for s in sessions.list()['sessions'] if s['state'] == 'active']


def _attach(sessions, session, thread_id):
    candidates = [s for s in sessions.sources()['sources']
                  if not s['session_id'] and (thread_id is None or s['thread_id'] == thread_id)]
    if thread_id is None and len(candidates) != 1:
        return session, 'Provide --thread-id when multiple sources exist; wait for a Codex hook if none has been observed.'
    if not candidates:
        return session, 'No matching Codex hook source observed. Trust project hooks, then submit another Codex prompt and retry start.'
    candidate = candidates[0]
    result = sessions.dispatch('research.attach_source'.removeprefix('research.'), {
        'session_id': session['session_id'], 'source_id': candidate['source_id'],
        'expected_revision': session['revision'], 'request_id': _request()})
    return result, None


def start(root: Path, *, title: str, topic: str, thread_id: str | None = None):
    root = Path(root).resolve()
    sessions = ResearchSessions(root)
    existing = _active(sessions)
    if len(existing) > 1:
        return {'status': 'ACTION_REQUIRED', 'reason': 'multiple_active_sessions',
                'sessions': [s['session_id'] for s in existing]}
    if not ResearchLog(root).enabled:
        return {'status': 'ACTION_REQUIRED', 'reason': 'capture_disabled',
                'next_action': 'Install/trust Codex hooks and enable managed research capture before starting.'}
    session = existing[0] if existing else None
    if session is None:
        session = sessions.dispatch('create', {'title': title, 'topic': topic,
                                              'request_id': _request()})
    if not session['sources']:
        session, issue = _attach(sessions, session, thread_id)
        if issue:
            return {'status': 'ACTION_REQUIRED', 'session_id': session['session_id'],
                    'capture_ready': False, 'capture_verified': False, 'next_action': issue}
    capture = CodexCapture(root).status()
    threads = [t for t in capture['threads'] if t['session_id'] == session['session_id']]
    counts = session['counts']
    verified = bool(threads and counts.get('prompt.recorded', 0)
                    and counts.get('model.responded', 0))
    return {'status': 'READY' if verified else 'ACTION_REQUIRED',
            'session_id': session['session_id'], 'capture_ready': bool(threads),
            'capture_verified': verified,
            'next_action': None if verified else
            'Submit a new Codex prompt and verify its response was captured, then retry start.',
            'capture': threads, 'counts': counts}


def finish(root: Path, *, session_id: str | None = None, destination: str | None = None):
    root = Path(root).resolve()
    sessions = ResearchSessions(root)
    if session_id:
        session = sessions.get(session_id)
    else:
        active = _active(sessions)
        if len(active) != 1:
            return {'status': 'ACTION_REQUIRED', 'reason': 'expected_one_active_session',
                    'active_sessions': [s['session_id'] for s in active]}
        session = active[0]
    if session['state'] == 'active':
        session = sessions.dispatch('finish', {'session_id': session['session_id'],
                    'expected_revision': session['revision'], 'request_id': _request()})
    if session['state'] != 'finished':
        return {'status': 'ACTION_REQUIRED', 'reason': 'session_not_active',
                'session_id': session['session_id']}
    jobs = ResearchJobs(root)
    check = jobs.dispatch('integrity', 'check', {'session_id': session['session_id'],
                                                'deep': True, 'request_id': _request()})
    export = None
    if destination:
        export = jobs.dispatch('exports', 'start', {'session_id': session['session_id'],
                        'destination': destination, 'mode': 'full', 'request_id': _request()})
    kick_worker(root)
    return {'status': 'PROCESSING', 'session_id': session['session_id'],
            'integrity_job': check, 'export_job': export,
            'next_action': 'Poll integrity.status and exports.status until completed; verify the ZIP before reporting success.'}
