"""Opt-in, local research ledger. No model calls or authoring dependencies."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
import uuid
import sys

from manim_studio import __version__
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 5
CLASSIFICATION_UNSET = object()
PROMPT_TYPES = ('initial', 'continuation', 'corrective', 'irrelevant')
REASONS = ('factual_math', 'narrative_order', 'unclear_explanation', 'add_content',
           'remove_content', 'visual_animation', 'intent_mismatch', 'technical_render', 'other')
STAGES = ('task', 'lesson_plan', 'storyboard', 'scene_creation', 'revision',
          'validation', 'render', 'export', 'other', 'unknown')
ACTORS = ('human', 'model', 'system')


def _id():
    return str(uuid.uuid4())


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class ResearchLog:
    """SQLite transactions serialize writers; event order is a database sequence."""
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.directory = self.root / '.manim-studio' / 'research'
        self.database = self.directory / 'events.sqlite3'

    @contextmanager
    def connection(self, timeout=30):
        self.directory.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database, timeout=timeout)) as db, db:
            db.row_factory = sqlite3.Row
            from manim_studio.research_schema import migrate
            migrate(db, self.database, timeout=timeout)
            yield db

    @property
    def enabled(self):
        if not self.database.exists():
            return False
        with self.connection() as db:
            row = db.execute("SELECT value FROM config WHERE key='enabled'").fetchone()
            return row is not None and row[0] == 'true'

    def configure(self, enabled: bool, managed: bool = False):
        if not isinstance(enabled, bool):
            raise ValueError('enabled must be a boolean')
        if not isinstance(managed, bool):
            raise ValueError('managed must be a boolean')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if managed:
                db.execute("INSERT OR REPLACE INTO config VALUES ('managed_sessions','true')")
            previous = db.execute("SELECT value FROM config WHERE key='enabled'").fetchone()
            if previous is None or previous[0] != ('true' if enabled else 'false'):
                # Capture adapters must not backfill content produced while paused.
                db.execute("INSERT INTO config VALUES ('capture_epoch','1') ON CONFLICT(key) "
                           "DO UPDATE SET value=CAST(value AS INTEGER)+1")
            for key, value in [('enabled', 'true' if enabled else 'false')]:
                db.execute('INSERT OR REPLACE INTO config VALUES (?, ?)', (key, value))
            if db.execute("SELECT 1 FROM config WHERE key='project_id'").fetchone() is None:
                db.execute('INSERT INTO config VALUES (?, ?)', ('project_id', _id()))
        return {'enabled': enabled}

    def _event(self, db, kind, session_id, payload, *, prompt_id=None, parent_id=None,
               actor='system', stage='unknown'):
        if not db.in_transaction:
            db.execute('BEGIN IMMEDIATE')
        if kind in ('prompt.recorded', 'model.responded', 'action.started', 'action.finished'):
            from manim_studio.research_sessions import collection_epoch
            enabled = db.execute("SELECT value FROM config WHERE key='enabled'").fetchone()
            if not enabled or enabled[0] != 'true':
                raise ValueError('research logging is disabled')
            epoch = collection_epoch(db, session_id)
            if epoch is not None:
                payload = dict(payload, research_epoch=epoch)
                if kind == 'action.finished' and parent_id:
                    start = db.execute('SELECT payload FROM events WHERE id=?', (parent_id,)).fetchone()
                    if start and json.loads(start[0]).get('research_epoch') != epoch:
                        raise ValueError('action crosses research collection boundary')
        if actor not in ACTORS or stage not in STAGES:
            raise ValueError('invalid actor or stage')
        if kind != 'session.started':
            session = db.execute("SELECT id FROM events WHERE id=? AND type='session.started'",
                                 (session_id,)).fetchone()
            if session is None:
                raise ValueError('unknown research session')
        if prompt_id is not None:
            prompt = db.execute("SELECT session_id,stage,payload FROM events WHERE id=? AND type='prompt.recorded'",
                                (prompt_id,)).fetchone()
            if prompt is None or prompt[0] != session_id:
                raise ValueError('prompt does not belong to research session')
            if stage == 'unknown':
                stage = prompt[1]
            if kind in ('model.responded', 'action.started') and payload.get('research_epoch') is not None:
                if json.loads(prompt[2]).get('research_epoch') != payload['research_epoch']:
                    raise ValueError('prompt crosses research collection boundary')
        if parent_id is not None:
            parent = db.execute('SELECT session_id FROM events WHERE id=?', (parent_id,)).fetchone()
            if parent is None or parent[0] != session_id:
                raise ValueError('parent does not belong to research session')
        event_id = session_id if kind == 'session.started' else _id()
        db.execute('''INSERT INTO events
            (id,session_id,prompt_id,parent_id,type,timestamp,actor,stage,payload)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            (event_id, session_id, prompt_id, parent_id, kind,
             datetime.now(timezone.utc).isoformat(), actor, stage, _json(payload)))
        return event_id

    def _require_enabled(self):
        if not self.enabled:
            raise ValueError('research logging is disabled')

    def start_session(self, label='', model=None, run_settings=None):
        self._require_enabled()
        if not isinstance(label, str):
            raise ValueError('session label must be text')
        if model is not None and not isinstance(model, dict):
            raise ValueError('model metadata must be an object or null')
        if run_settings is not None and not isinstance(run_settings, dict):
            raise ValueError('run settings must be an object or null')
        with self.connection() as db:
            session_id = _id()
            self._event(db, 'session.started', session_id,
                        {'label': label, 'model': model, 'run_settings': run_settings,
                         'studio_version': __version__,
                         'python_version': sys.version,
                         'schema_version': SCHEMA_VERSION})
        return session_id

    def record_prompt(self, session_id, text, stage='unknown', model=None):
        """Model metadata is supplied by the host; unknown values remain null."""
        self._require_enabled()
        if not isinstance(text, str) or (model is not None and not isinstance(model, dict)):
            raise ValueError('prompt requires text and optional model metadata object')
        with self.connection() as db:
            return self._event(db, 'prompt.recorded', session_id,
                               {'text': text, 'model': model, 'classification': None},
                               actor='human', stage=stage)

    def record_response(self, session_id, prompt_id, text, model=None):
        self._require_enabled()
        if not prompt_id:
            raise ValueError('response requires a prompt ID')
        if not isinstance(text, str) or (model is not None and not isinstance(model, dict)):
            raise ValueError('response requires text and optional model metadata object')
        with self.connection() as db:
            return self._event(db, 'model.responded', session_id,
                               {'text': text, 'model': model}, prompt_id=prompt_id, actor='model')

    def classify(self, session_id, prompt_id, prompt_type=None, reasons=None, other=None,
                 source='human', human_seconds=None, request_id=None,
                 expected_human_head=CLASSIFICATION_UNSET, taxonomy_version=1,
                 suggestion_id=None, classifier=None):
        from manim_studio.prompt_classifications import PromptClassifications
        if source not in ('human', 'model'):
            raise ValueError('invalid classification source')
        service = PromptClassifications(self.root)
        state = service.dispatch('get', {'session_id': session_id, 'prompt_id': prompt_id})
        payload = dict(project_id=state['project_id'], session_id=session_id, prompt_id=prompt_id,
                       prompt_type=prompt_type, reasons=reasons, other=other, human_seconds=human_seconds,
                       taxonomy_version=taxonomy_version, suggestion_id=suggestion_id, classifier=classifier,
                       request_id=request_id or (_id() if source == 'model' else None))
        if expected_human_head is not CLASSIFICATION_UNSET:
            payload['expected_human_head'] = expected_human_head
        action = 'suggest' if source == 'model' else 'clear' if prompt_type is None else 'save'
        return service.dispatch(action, payload)['event_id']

    def snapshot(self, db):
        """Bounded source-only snapshots; omissions are explicit, never follow symlinks."""
        from manim_studio.research_files import candidates, read_project_file
        from manim_studio.research_artifacts import CAPTURE, ResearchArtifacts
        context = CAPTURE.get()
        if context and context.get('session_id') and context.get('capture_snapshots',True):
            snapshot = ResearchArtifacts(self.root).checkpoint(db, context['session_id'], prompt_id=context.get('prompt_id'))
            return {'files': snapshot['files'], 'omitted': snapshot['omitted'], 'snapshot_id': snapshot['snapshot_id'], 'scope': 'configured research source policy'}
        files, omitted = {}, []
        paths, omissions = candidates(self.root)
        omitted = [item["path"] for item in omissions]
        total = 0
        for relative in paths:
            try:
                content = read_project_file(self.root, relative, min(1_000_000, max(0, 10_000_000-total)))
            except (OSError, ValueError):
                omitted.append(relative)
                continue
            total += len(content)
            sha = hashlib.sha256(content).hexdigest()
            db.execute('INSERT OR IGNORE INTO blobs VALUES (?,?)', (sha, content))
            files[relative] = sha
        return {'files': files, 'omitted': omitted, 'scope': 'bounded configured source files'}

    def begin_action(self, session_id, name, arguments, prompt_id=None, source=None):
        self._require_enabled()
        stage = ('export' if 'export' in name else 'render' if 'render' in name else
                 'validation' if 'validat' in name else 'unknown')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            from manim_studio.research_sessions import collection_epoch
            collection_epoch(db, session_id)
            return self._event(db, 'action.started', session_id,
                               {'name': name, 'arguments': arguments, 'state': self.snapshot(db), 'source': source},
                               prompt_id=prompt_id, stage=stage)

    def end_action(self, session_id, action_id, result, elapsed, prompt_id=None, error=None):
        # A pause during execution suppresses further collection.
        if not self.enabled:
            return None
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            from manim_studio.research_sessions import collection_epoch
            epoch = collection_epoch(db, session_id)
            action = db.execute("SELECT stage,prompt_id FROM events WHERE id=? AND type='action.started' AND session_id=?",
                                (action_id, session_id)).fetchone()
            if action is None or action[1] != prompt_id:
                raise ValueError('unknown action start or mismatched prompt')
            original = db.execute('SELECT payload FROM events WHERE id=?', (action_id,)).fetchone()
            start_payload = json.loads(original[0])
            if epoch is not None and start_payload.get('research_epoch') != epoch:
                raise ValueError('action crosses research collection boundary')
            return self._event(db, 'action.finished', session_id,
                               {'result': result, 'error': error, 'duration_seconds': elapsed,
                                'state': self.snapshot(db), 'source': start_payload.get('source')},
                               prompt_id=prompt_id, parent_id=action_id, stage=action[0])

    def export(self, destination: Path, include_content=False):
        """Default export omits prompt/response/source/arguments/result/free text."""
        if not isinstance(include_content, bool):
            raise ValueError('include_content must be a boolean')
        destination = Path(destination).resolve()
        if destination == self.database.resolve():
            raise ValueError('export cannot overwrite research database')
        with self.connection() as db:
            project = db.execute("SELECT value FROM config WHERE key='project_id'").fetchone()
            records = []
            for row in db.execute('SELECT * FROM events ORDER BY seq'):
                event = dict(row)
                event['schema_version'] = SCHEMA_VERSION
                event['project_id'] = project[0] if project else None
                event['payload'] = json.loads(event['payload'])
                if not include_content:
                    event['payload'] = {k: v for k, v in event['payload'].items() if k in
                        ('schema_version', 'studio_version', 'prompt_type', 'reasons',
                         'human_seconds', 'time_source', 'name', 'duration_seconds', 'state',
                         'source', 'related_prompt_ids', 'capture_status', 'code', 'status',
                         'source_id', 'thread_id', 'client_id', 'client_type', 'research_epoch',
                         'reason', 'boundary_verified', 'coverage_start', 'offset', 'taxonomy_version',
                         'previous_human_head', 'suggestion_id', 'classifier', 'request_id',
                         'artifact_id', 'sha256', 'size', 'role', 'build_id', 'proposal_id', 'revision',
                         'decision_id', 'kind', 'origin', 'reported_by', 'action_id', 'before_snapshot_id',
                         'after_snapshot_id', 'snapshot_id', 'files', 'omitted', 'missing', 'candidate')}
                records.append(event)
            if include_content:
                import base64
                for row in db.execute('SELECT * FROM blobs ORDER BY sha256'):
                    records.append({'schema_version': SCHEMA_VERSION, 'type': 'source.blob',
                                    'sha256': row[0], 'base64': base64.b64encode(row[1]).decode('ascii')})
                from manim_studio.research_artifacts import ResearchArtifacts
                archive = ResearchArtifacts(self.root)
                included = {r.get('sha256') for r in records if r.get('type') == 'source.blob'}
                for row in db.execute('SELECT payload FROM research_artifacts'):
                    artifact = json.loads(row[0])
                    sha = artifact.get('sha256')
                    if artifact['status'] != 'retained' or sha in included or artifact['role'] in ('preview_video','final_product'):
                        continue
                    content = archive._read_content(sha, artifact['size'])
                    records.append({'schema_version': SCHEMA_VERSION, 'type': 'source.blob',
                                    'sha256': sha, 'base64': base64.b64encode(content).decode('ascii')})
                    included.add(sha)
        with destination.open('x', encoding='utf-8') as output:
            for record in records:
                output.write(_json(record) + '\n')
        return {'events': sum('seq' in r for r in records), 'include_content': include_content}


def instrument(function):
    """Fail open, warn visibly, preserve exceptions and return values of the action."""
    import functools
    import inspect
    import warnings
    signature = inspect.signature(function)

    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        ctx = bound.arguments.get('context')
        if ctx is None:
            return function(*args, **kwargs)
        log = ResearchLog(ctx.repo_root)
        from manim_studio.research_sessions import ResearchSessions
        try:
            session_id, prompt_id = ResearchSessions(ctx.repo_root).resolve(
                getattr(ctx, 'research_session_id', None), getattr(ctx, 'research_prompt_id', None),
                getattr(ctx, 'research_client_id', None), getattr(ctx, 'research_context_origin', 'explicit'))
        except Exception as exc:
            # Fail open without retaining unbound arguments or choosing another session.
            from manim_studio.research_capture import CodexCapture
            try:
                CodexCapture(ctx.repo_root).record_failure({}, getattr(exc, 'code', 'invalid_context'))
            except Exception:
                pass
            warnings.warn(f'Research context rejected: {exc}', RuntimeWarning)
            return function(*args, **kwargs)
        if not session_id:
            return function(*args, **kwargs)
        from manim_studio.research_artifacts import CAPTURE
        inherited = CAPTURE.get()
        context_token = CAPTURE.set(inherited or dict(root=str(log.root), session_id=session_id, prompt_id=prompt_id,
            client_id=getattr(ctx, 'research_client_id', None), request_id=getattr(ctx,'research_request_id',None), origin=getattr(ctx, 'research_decision_origin', 'unknown'),
            origin_evidence=getattr(ctx, 'research_origin_evidence', None)))
        CAPTURE.get()['capture_snapshots'] = function.__name__ not in ('authoring.list_sessions','authoring.get_status','authoring.list_proposals','authoring.discover_active_proposal')
        action_id = None
        started = time.monotonic()
        try:
            if log.enabled:
                arguments = {k: v for k, v in bound.arguments.items() if k != 'context'}
                action_id = log.begin_action(session_id, function.__name__, arguments, prompt_id,
                    source={'client_id': getattr(ctx, 'research_client_id', None),
                            'boundary': 'rpc' if function.__name__.startswith('authoring.') else 'service'})
        except Exception as exc:
            warnings.warn(f'Research logging failed before {function.__name__}: {exc}', RuntimeWarning)
        if action_id:
            CAPTURE.get()['action_id'] = action_id
        result, error = None, None
        try:
            result = function(*args, **kwargs)
            return result
        except Exception as exc:
            error = {'type': type(exc).__name__, 'message': str(exc)}
            raise
        finally:
            if action_id:
                try:
                    # Service responses are already JSON-compatible apart from Path values.
                    serializable = json.loads(json.dumps(result, default=str))
                    log.end_action(session_id, action_id, serializable,
                                   time.monotonic() - started, prompt_id, error)
                except Exception as exc:
                    warnings.warn(f'Research logging failed after {function.__name__}: {exc}', RuntimeWarning)
            CAPTURE.reset(context_token)
    return wrapped


def instrument_rpc(function):
    """Request-local RPC bridge, using reserved _research metadata or environment IDs."""
    import functools
    import os
    from types import SimpleNamespace

    @functools.wraps(function)
    def wrapped(self, method, params):
        params = dict(params)
        if method.startswith(('research.', 'classification.', 'artifacts.')):
            return function(self, method, params)
        explicit = '_research' in params
        metadata = params.pop('_research', {})
        if not isinstance(metadata, dict):
            raise ValueError('_research must be an object')
        context = SimpleNamespace(
            repo_root=self.repo_root,
            research_session_id=metadata.get('session_id') if explicit else os.environ.get('MANIM_STUDIO_RESEARCH_SESSION'),
            research_prompt_id=metadata.get('prompt_id') if explicit else os.environ.get('MANIM_STUDIO_RESEARCH_PROMPT'),
            research_client_id=metadata.get('client_id') if explicit else os.environ.get('MANIM_STUDIO_RESEARCH_CLIENT'),
            research_context_origin='explicit' if explicit else 'environment',
            research_decision_origin=metadata.get('decision_origin') if metadata.get('decision_origin') in ('human', 'automation') else 'unknown',
            research_origin_evidence=metadata.get('origin_evidence') if isinstance(metadata.get('origin_evidence'), str) else None,
            research_request_id=metadata.get('request_id') if isinstance(metadata.get('request_id'),str) else None)

        def invoke(method, params, context=None):
            return function(self, method, params)
        invoke.__name__ = 'authoring.' + method
        return instrument(invoke)(method, params, context=context)
    return wrapped
