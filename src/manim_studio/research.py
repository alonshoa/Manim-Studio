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

SCHEMA_VERSION = 2
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
    def connection(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database, timeout=30)) as db, db:
            db.row_factory = sqlite3.Row
            db.executescript('''
                CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT NOT NULL UNIQUE, session_id TEXT NOT NULL,
                    prompt_id TEXT, parent_id TEXT, type TEXT NOT NULL,
                    timestamp TEXT NOT NULL, actor TEXT NOT NULL, stage TEXT NOT NULL,
                    payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS blobs (sha256 TEXT PRIMARY KEY, content BLOB NOT NULL);
            ''')
            yield db

    @property
    def enabled(self):
        if not self.database.exists():
            return False
        with self.connection() as db:
            row = db.execute("SELECT value FROM config WHERE key='enabled'").fetchone()
            return row is not None and row[0] == 'true'

    def configure(self, enabled: bool):
        if not isinstance(enabled, bool):
            raise ValueError('enabled must be a boolean')
        with self.connection() as db:
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
        if actor not in ACTORS or stage not in STAGES:
            raise ValueError('invalid actor or stage')
        if kind != 'session.started':
            session = db.execute("SELECT id FROM events WHERE id=? AND type='session.started'",
                                 (session_id,)).fetchone()
            if session is None:
                raise ValueError('unknown research session')
        if prompt_id is not None:
            prompt = db.execute("SELECT session_id,stage FROM events WHERE id=? AND type='prompt.recorded'",
                                (prompt_id,)).fetchone()
            if prompt is None or prompt[0] != session_id:
                raise ValueError('prompt does not belong to research session')
            if stage == 'unknown':
                stage = prompt[1]
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
                 source='human', human_seconds=None):
        self._require_enabled()
        if not prompt_id:
            raise ValueError('classification requires a prompt ID')
        if source not in ('human', 'model') or prompt_type not in (*PROMPT_TYPES, None):
            raise ValueError('invalid classification source or prompt type')
        if reasons is not None and (not isinstance(reasons, list) or
                                   any(r not in REASONS for r in reasons)):
            raise ValueError('invalid reasons')
        if other and (not reasons or 'other' not in reasons):
            raise ValueError('free text requires other reason')
        if human_seconds is not None and (source != 'human' or
            isinstance(human_seconds, bool) or not math.isfinite(human_seconds) or human_seconds < 0):
            raise ValueError('invalid self-reported human time')
        with self.connection() as db:
            return self._event(db, 'classification.confirmed' if source == 'human' else
                               'classification.suggested', session_id,
                               {'prompt_type': prompt_type, 'reasons': reasons, 'other': other,
                                'human_seconds': human_seconds,
                                'time_source': 'self_report' if human_seconds is not None else None},
                               prompt_id=prompt_id, actor=source)

    def snapshot(self, db):
        """Bounded source-only snapshots; omissions are explicit, never follow symlinks."""
        files, omitted = {}, []
        candidates = [self.root / 'catalog' / 'scenes.yaml']
        for directory in ('scenes', 'decks', '.manim-studio/authoring'):
            base = self.root / directory
            if base.is_symlink():
                omitted.append(directory)
                continue
            if base.exists():
                candidates.extend(p for p in base.rglob('*') if p.suffix in ('.py', '.json'))
        total = 0
        for path in sorted(set(candidates)):
            relative = path.relative_to(self.root).as_posix()
            if not path.exists():
                continue
            if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != self.root) or not path.is_file():
                omitted.append(relative)
                continue
            if path.stat().st_size > 1_000_000 or total + path.stat().st_size > 10_000_000:
                omitted.append(relative)
                continue
            content = path.read_bytes()
            total += len(content)
            sha = hashlib.sha256(content).hexdigest()
            db.execute('INSERT OR IGNORE INTO blobs VALUES (?,?)', (sha, content))
            files[relative] = sha
        return {'files': files, 'omitted': omitted, 'scope': 'catalog/scenes.yaml, scenes|decks|.manim-studio/authoring *.py|*.json'}

    def begin_action(self, session_id, name, arguments, prompt_id=None):
        self._require_enabled()
        stage = ('export' if 'export' in name else 'render' if 'render' in name else
                 'validation' if 'validat' in name else 'unknown')
        with self.connection() as db:
            return self._event(db, 'action.started', session_id,
                               {'name': name, 'arguments': arguments, 'state': self.snapshot(db)},
                               prompt_id=prompt_id, stage=stage)

    def end_action(self, session_id, action_id, result, elapsed, prompt_id=None, error=None):
        # A pause during execution suppresses further collection.
        if not self.enabled:
            return None
        with self.connection() as db:
            action = db.execute("SELECT stage,prompt_id FROM events WHERE id=? AND type='action.started' AND session_id=?",
                                (action_id, session_id)).fetchone()
            if action is None or action[1] != prompt_id:
                raise ValueError('unknown action start or mismatched prompt')
            return self._event(db, 'action.finished', session_id,
                               {'result': result, 'error': error, 'duration_seconds': elapsed,
                                'state': self.snapshot(db)}, prompt_id=prompt_id, parent_id=action_id, stage=action[0])

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
                         'source', 'related_prompt_ids', 'capture_status', 'code', 'status')}
                records.append(event)
            if include_content:
                import base64
                for row in db.execute('SELECT * FROM blobs ORDER BY sha256'):
                    records.append({'schema_version': SCHEMA_VERSION, 'type': 'source.blob',
                                    'sha256': row[0], 'base64': base64.b64encode(row[1]).decode('ascii')})
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
        if ctx is None or not ctx.research_session_id:
            return function(*args, **kwargs)
        log = ResearchLog(ctx.repo_root)
        action_id = None
        started = time.monotonic()
        try:
            if log.enabled:
                arguments = {k: v for k, v in bound.arguments.items() if k != 'context'}
                action_id = log.begin_action(ctx.research_session_id, function.__name__,
                                             arguments, ctx.research_prompt_id)
        except Exception as exc:
            warnings.warn(f'Research logging failed before {function.__name__}: {exc}', RuntimeWarning)
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
                    log.end_action(ctx.research_session_id, action_id, serializable,
                                   time.monotonic() - started, ctx.research_prompt_id, error)
                except Exception as exc:
                    warnings.warn(f'Research logging failed after {function.__name__}: {exc}', RuntimeWarning)
    return wrapped


def instrument_rpc(function):
    """Request-local RPC bridge, using reserved _research metadata or environment IDs."""
    import functools
    import os
    from types import SimpleNamespace

    @functools.wraps(function)
    def wrapped(self, method, params):
        params = dict(params)
        metadata = params.pop('_research', {})
        if not isinstance(metadata, dict):
            raise ValueError('_research must be an object')
        context = SimpleNamespace(
            repo_root=self.repo_root,
            research_session_id=metadata.get('session_id') or os.environ.get('MANIM_STUDIO_RESEARCH_SESSION'),
            research_prompt_id=metadata.get('prompt_id') or os.environ.get('MANIM_STUDIO_RESEARCH_PROMPT'))

        def invoke(method, params, context=None):
            return function(self, method, params)
        invoke.__name__ = 'authoring.' + method
        return instrument(invoke)(method, params, context=context)
    return wrapped
