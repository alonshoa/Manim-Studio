"""Persistent research lifecycle shared by CLI, RPC, MCP and the VS Code UI."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from manim_studio.research import ResearchLog, SCHEMA_VERSION, _json

ACTIONS = ('configure', 'create', 'list', 'get', 'sources', 'attach_source', 'adopt_legacy',
           'pause', 'resume', 'finish', 'bind_client', 'status')


class ResearchSessionError(ValueError):
    def __init__(self, code, message=None):
        self.code = code
        super().__init__(message or code)


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ResearchSessionError('invalid_request', f'{field} must be a nonempty identifier')
    return value


def managed(db):
    row = db.execute("SELECT value FROM config WHERE key='managed_sessions'").fetchone()
    return bool(row and row[0] == 'true')


def session_row(db, session_id):
    row = db.execute('SELECT * FROM research_sessions WHERE session_id=?', (session_id,)).fetchone()
    if not row:
        raise ResearchSessionError('session_not_found')
    return row


def collection_epoch(db, session_id):
    row = db.execute('SELECT state,capture_epoch FROM research_sessions WHERE session_id=?',
                     (session_id,)).fetchone()
    if row:
        if row['state'] != 'active':
            raise ResearchSessionError('session_' + row['state'])
        return row['capture_epoch']
    return None


def boundary(root, thread_id, transcript_path, state):
    """Skip pre-binding/paused bytes, never import their text. Fail conservatively."""
    from manim_studio.research_capture import MAX_LINE, _digest
    state = dict(state)
    previous_offset = state.get('offset', 0)
    blocked = set(state.get('blocked_turns', [])) | set(state.get('prompts', {}))
    if state.get('transcript_turn'):
        blocked.add(state['transcript_turn'])
    state.update(prompts={}, last_responses={}, blocked_turns=sorted(blocked),
                 pending_boundary=True, transcript_verified=False)
    for key in ('transcript_turn', 'transcript_dialect', 'discarding_record', 'anchor'):
        state.pop(key, None)
    try:
        if not isinstance(transcript_path, str):
            return state
        path = Path(transcript_path)
        if path.is_symlink() or any(p.is_symlink() for p in path.parents) or not path.is_file():
            return state
        with path.open('rb') as stream:
            header = stream.readline(MAX_LINE + 1)
            record = json.loads(header)
            meta = record['payload']
            if record['type'] != 'session_meta' or meta['id'] != thread_id:
                return state
            if not Path(meta['cwd']).resolve().is_relative_to(root):
                return state
            size = os.fstat(stream.fileno()).st_size
            stream.seek(max(0, size - 128))
            state.update(file_key=_digest(str(path.resolve()).encode()), header_hash=_digest(header),
                         offset=size, anchor=_digest(stream.read(min(size, 128))), pending_boundary=False,
                         boundary_skipped_bytes=max(0, size - previous_offset))
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return state


class ResearchSessions:
    def __init__(self, root):
        self.log = ResearchLog(root)

    def dispatch(self, action, payload):
        if action not in ACTIONS or not isinstance(payload, dict):
            raise ResearchSessionError('invalid_request')
        if action == 'configure':
            return self.log.configure(**payload, managed=True)
        if action in ('list', 'get', 'sources', 'status'):
            return getattr(self, action)(**payload)
        request = identifier(payload.get('request_id'), 'request_id')
        fingerprint = hashlib.sha256(json.dumps({'action': action, 'payload': payload},
            sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        if not self.log.enabled:
            raise ResearchSessionError('capture_disabled')
        with self.log.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT value FROM config WHERE key='enabled'").fetchone()[0] != 'true':
                raise ResearchSessionError('capture_disabled')
            previous = db.execute('SELECT * FROM research_requests WHERE request_id=?', (request,)).fetchone()
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise ResearchSessionError('request_id_conflict')
                return json.loads(previous['result'])
            arguments = {k: v for k, v in payload.items() if k != 'request_id'}
            result = getattr(self, '_' + action)(db, **arguments)
            db.execute('INSERT INTO research_requests VALUES (?,?,?)', (request, fingerprint, _json(result)))
        if action == 'create':
            from manim_studio.research_artifacts import ResearchArtifacts, quiet
            quiet(ResearchArtifacts(self.log.root).dispatch, 'checkpoint',
                  dict(session_id=result['session_id'], request_id='initial-snapshot:' + request))
        return result

    def _revision(self, db, session_id, expected_revision):
        identifier(session_id, 'session_id')
        row = session_row(db, session_id)
        if type(expected_revision) is not int or expected_revision != row['revision']:
            raise ResearchSessionError('revision_conflict')
        return row

    def _create(self, db, title, topic):
        identifier(title, 'title')
        identifier(topic, 'topic')
        session, timestamp = str(uuid.uuid4()), now()
        self.log._event(db, 'session.started', session, {
            'label': title, 'topic': topic, 'schema_version': SCHEMA_VERSION, 'managed': True})
        db.execute('INSERT INTO research_sessions VALUES (?,?,?,?,?,?,?,?)',
                   (session, title.strip(), topic.strip(), 'active', 1, 1, timestamp, None))
        db.execute("INSERT OR REPLACE INTO config VALUES ('managed_sessions','true')")
        return self._status(db, session)

    def _adopt_legacy(self, db, session_id, title, topic):
        identifier(title, 'title')
        identifier(topic, 'topic')
        if db.execute('SELECT 1 FROM research_sessions WHERE session_id=?', (session_id,)).fetchone():
            raise ResearchSessionError('already_managed')
        if not db.execute("SELECT 1 FROM events WHERE id=? AND type='session.started'", (session_id,)).fetchone():
            raise ResearchSessionError('session_not_found')
        db.execute('INSERT INTO research_sessions VALUES (?,?,?,?,?,?,?,?)',
                   (session_id, title.strip(), topic.strip(), 'active', 1, 1, now(), None))
        db.execute("INSERT OR REPLACE INTO config VALUES ('managed_sessions','true')")
        self.log._event(db, 'session.adopted', session_id, {'title': title, 'topic': topic})
        from manim_studio.research_capture import CodexCapture
        CodexCapture._schema(db)
        for capture in db.execute('SELECT * FROM capture_threads WHERE session_id=?', (session_id,)).fetchall():
            db.execute('INSERT OR IGNORE INTO research_sources VALUES (?,?,?,?,?,?,?,?)',
                       (str(uuid.uuid4()), capture['thread_id'], session_id, None, None,
                        capture['updated_at'], -1, 0))
        return self._status(db, session_id)

    def _attach_source(self, db, session_id, source_id, expected_revision):
        self._revision(db, session_id, expected_revision)
        collection_epoch(db, session_id)
        source = db.execute('SELECT * FROM research_sources WHERE source_id=?', (source_id,)).fetchone()
        if not source:
            raise ResearchSessionError('source_not_found')
        if source['session_id'] == session_id:
            return self._status(db, session_id)
        if source['session_id']:
            raise ResearchSessionError('source_already_bound')
        if db.execute('SELECT 1 FROM research_sources WHERE session_id=?', (session_id,)).fetchone():
            raise ResearchSessionError('session_already_bound')
        if source['protocol_version'] not in range(3, SCHEMA_VERSION + 1):
            raise ResearchSessionError('unsupported_schema')
        from manim_studio.research_capture import CodexCapture
        CodexCapture._schema(db)
        state = boundary(self.log.root, source['thread_id'], source['transcript_path'], {
            'prompts': {}, 'model': {'provider': None, 'model': None, 'version': None},
            'offset': 0, 'gap_count': 0, 'capture_status': 'hooks_only', 'last_responses': {}})
        epoch = db.execute("SELECT value FROM config WHERE key='capture_epoch'").fetchone()[0]
        epoch += ':' + str(session_row(db, session_id)['capture_epoch'])
        db.execute('INSERT INTO capture_threads VALUES (?,?,?,?,?)',
                   (source['thread_id'], session_id, epoch, _json(state), now()))
        db.execute('UPDATE research_sources SET session_id=? WHERE source_id=?', (session_id, source_id))
        db.execute('UPDATE research_sessions SET revision=revision+1 WHERE session_id=?', (session_id,))
        self.log._event(db, 'session.source_attached', session_id, {
            'source_id': source_id, 'thread_id': source['thread_id'], 'offset': state['offset'],
            'coverage_start': 'explicit_binding', 'boundary_verified': not state['pending_boundary']})
        return self._status(db, session_id)

    def _bind_client(self, db, session_id, client_id, client_type):
        identifier(client_id, 'client_id')
        row = session_row(db, session_id)
        if row['state'] == 'finished':
            raise ResearchSessionError('session_finished')
        if client_type not in ('rpc', 'mcp', 'terminal'):
            raise ResearchSessionError('invalid_request')
        existing = db.execute('SELECT * FROM research_clients WHERE client_id=?', (client_id,)).fetchone()
        if existing:
            if existing['session_id'] != session_id or existing['client_type'] != client_type:
                raise ResearchSessionError('client_already_bound')
        else:
            db.execute('INSERT INTO research_clients VALUES (?,?,?)', (client_id, session_id, client_type))
            self.log._event(db, 'session.client_bound', session_id, {'client_id': client_id, 'client_type': client_type})
        return self._status(db, session_id)

    def _transition(self, db, session_id, expected_revision, target):
        row = self._revision(db, session_id, expected_revision)
        if row['state'] == target:
            return self._status(db, session_id)
        if row['state'] == 'finished':
            raise ResearchSessionError('session_finished')
        db.execute('UPDATE research_sessions SET state=?, revision=revision+1, '
                   'capture_epoch=capture_epoch+1, finished_at=? WHERE session_id=?',
                   (target, now() if target == 'finished' else None, session_id))
        self.log._event(db, {'active': 'session.resumed', 'paused': 'session.paused',
                            'finished': 'session.finished'}[target], session_id, {'state': target})
        # Mark incomplete observations, never claim the underlying operation failed.
        for action in self._incomplete(db, session_id):
            self.log._event(db, 'action.observation_ended', session_id,
                            {'reason': 'collection_' + target}, parent_id=action['id'])
        # Establish the boundary while the lifecycle transition holds the DB lock.
        from manim_studio.research_capture import CodexCapture
        CodexCapture._schema(db)
        for source in db.execute('SELECT * FROM research_sources WHERE session_id=?', (session_id,)).fetchall():
            capture = db.execute('SELECT state FROM capture_threads WHERE thread_id=?', (source['thread_id'],)).fetchone()
            if capture:
                state = boundary(self.log.root, source['thread_id'], source['transcript_path'], json.loads(capture[0]))
                if state['pending_boundary'] or state.get('boundary_skipped_bytes', 0):
                    state['gap_count'] = state.get('gap_count', 0) + 1
                    self.log._event(db, 'capture.gap', session_id, {
                        'code': 'collection_boundary_unverified' if state['pending_boundary'] else 'collection_boundary_skipped_bytes',
                        'capture_status': 'partial', 'source': {'client': 'codex', 'thread_id': source['thread_id']}})
                blocked = set(state.get('blocked_turns', []))
                if source['last_turn_id']:
                    blocked.add(source['last_turn_id'])
                state['blocked_turns'] = sorted(blocked)
                state['capture_status'] = 'partial'
                epoch = db.execute("SELECT value FROM config WHERE key='capture_epoch'").fetchone()[0]
                epoch += ':' + str(session_row(db, session_id)['capture_epoch'])
                db.execute('UPDATE capture_threads SET state=?,epoch=? WHERE thread_id=?',
                           (_json(state), epoch, source['thread_id']))
        return self._status(db, session_id)

    def _pause(self, db, **params):
        return self._transition(db, target='paused', **params)

    def _resume(self, db, **params):
        return self._transition(db, target='active', **params)

    def _finish(self, db, **params):
        return self._transition(db, target='finished', **params)

    @staticmethod
    def _incomplete(db, session_id):
        return db.execute("SELECT e.id FROM events e WHERE e.session_id=? AND e.type='action.started' "
                          "AND NOT EXISTS (SELECT 1 FROM events f WHERE f.parent_id=e.id "
                          "AND f.type IN ('action.finished','action.observation_ended'))", (session_id,)).fetchall()

    def _status(self, db, session_id):
        row = dict(session_row(db, session_id))
        sources = [dict(s) for s in db.execute('SELECT source_id,thread_id,session_id,last_hook_at,connected, '
                    'protocol_version FROM research_sources WHERE session_id=?', (session_id,))]
        capture = []
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='capture_threads'").fetchone():
            for c in db.execute('SELECT thread_id,state,updated_at FROM capture_threads WHERE session_id=?', (session_id,)):
                state = json.loads(c['state'])
                capture.append({'thread_id': c['thread_id'], 'capture_status': state.get('capture_status'),
                                'gap_count': state.get('gap_count', 0), 'last_hook_at': c['updated_at']})
        counts = {r[0]: r[1] for r in db.execute('SELECT type,count(*) FROM events WHERE session_id=? GROUP BY type', (session_id,))}
        clients = [dict(c) for c in db.execute('SELECT * FROM research_clients WHERE session_id=?', (session_id,))]
        unresolved = db.execute("SELECT count(*) FROM events e WHERE e.session_id=? AND e.type='action.started' "
                               "AND NOT EXISTS (SELECT 1 FROM events f WHERE f.parent_id=e.id AND f.type='action.finished')", (session_id,)).fetchone()[0]
        enabled = db.execute("SELECT value FROM config WHERE key='enabled'").fetchone()
        return dict(row, sources=sources, capture=capture, clients=clients, counts=counts,
                    incomplete_actions=unresolved, collecting=bool(sources and enabled and enabled[0] == 'true' and row['state'] == 'active'),
                    collection_enabled=bool(enabled and enabled[0] == 'true' and row['state'] == 'active'),
                    observed_at=now(), coverage='unbound' if not sources else 'unverified')

    def list(self):
        if not self.log.database.exists():
            return {'sessions': [], 'legacy_sessions': [], 'enabled': False}
        with self.log.connection() as db:
            ids = [r[0] for r in db.execute('SELECT session_id FROM research_sessions ORDER BY created_at')]
            legacy = []
            for r in db.execute("SELECT id,payload FROM events WHERE type='session.started' "
                                "AND id NOT IN (SELECT session_id FROM research_sessions)"):
                legacy.append({'session_id': r[0], 'title': json.loads(r[1]).get('label', 'Legacy session')})
            return {'sessions': [self._status(db, s) for s in ids], 'legacy_sessions': legacy, 'enabled': self._enabled(db)}

    @staticmethod
    def _enabled(db):
        row = db.execute("SELECT value FROM config WHERE key='enabled'").fetchone()
        return bool(row and row[0] == 'true')

    def get(self, session_id):
        if not self.log.database.exists():
            raise ResearchSessionError('session_not_found')
        with self.log.connection() as db:
            return self._status(db, session_id)

    def sources(self):
        if not self.log.database.exists():
            return {'sources': []}
        with self.log.connection() as db:
            return {'sources': [dict(r) for r in db.execute('SELECT source_id,thread_id,session_id,last_hook_at, '
                       'connected,protocol_version FROM research_sources ORDER BY last_hook_at DESC')]}

    def status(self, session_id):
        result = self.get(session_id)
        from manim_studio.research_capture import CodexCapture
        result['unassigned_failure_count'] = CodexCapture(self.log.root).status().get('unassigned_failure_count', 0)
        return result

    def resolve(self, session_id=None, prompt_id=None, client_id=None, origin='explicit'):
        """Validate request-local context. Never infer a prompt or select a global session."""
        session_id, prompt_id, client_id = session_id or None, prompt_id or None, client_id or None
        if not self.log.database.exists():
            return session_id, prompt_id
        with self.log.connection() as db:
            if managed(db) and origin == 'environment' and not client_id:
                raise ResearchSessionError('unbound_client')
            if client_id:
                client = db.execute('SELECT session_id FROM research_clients WHERE client_id=?', (client_id,)).fetchone()
                if not client:
                    raise ResearchSessionError('client_not_found')
                if session_id and session_id != client[0]:
                    raise ResearchSessionError('context_conflict')
                session_id = client[0]
            if not session_id:
                if managed(db):
                    raise ResearchSessionError('unbound_client')
                return None, None
            if not db.execute("SELECT 1 FROM events WHERE id=? AND type='session.started'", (session_id,)).fetchone():
                raise ResearchSessionError('session_not_found')
            collection_epoch(db, session_id)
            if prompt_id and not db.execute("SELECT 1 FROM events WHERE id=? AND session_id=? AND type='prompt.recorded'",
                                           (prompt_id, session_id)).fetchone():
                raise ResearchSessionError('prompt_mismatch')
            return session_id, prompt_id
