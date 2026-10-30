"""Passive, project-scoped Codex hooks adapter. No model calls or client UI.

Hooks are the supported input contract. The optional rollout reader understands
the response_item/turn_context/session_meta JSONL dialect only; it is deliberately
reported as best effort, since Codex does not promise a stable transcript format.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shlex
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from manim_studio import __version__
from manim_studio.research import ResearchLog, SCHEMA_VERSION, _json

HOOKS = ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse',
         'Stop', 'Interrupt', 'SessionEnd', 'PreCompact', 'PostCompact')
MAX_LINE = 2_000_000
MAX_BATCH = 16_000_000
MARKER = 'Manim Studio research capture'


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _identifier(value, field):
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError(f'{field} must be a nonempty identifier')
    return value


def hook_config(root: Path, python: str | None = None):
    """Return mergeable config; never bypass hook trust or modify permissions."""
    args = [python or sys.executable, '-X', 'utf8', '-m', 'manim_studio.research_cli',
            '--root', str(Path(root).resolve()), 'codex-hook']
    # Explicit PowerShell encoding avoids cmd/PowerShell metacharacter expansion
    # in user paths (spaces, Hebrew, &, %, $, apostrophes). No extra dependency.
    windows_script = '& ' + ' '.join("'" + a.replace("'", "''") + "'" for a in args)
    windows_script += '; exit $LASTEXITCODE'
    encoded = base64.b64encode(windows_script.encode('utf-16le')).decode('ascii')
    handler = {'type': 'command', 'command': shlex.join(args),
               'commandWindows': 'powershell.exe -NoProfile -NonInteractive -EncodedCommand ' + encoded,
               'statusMessage': MARKER, 'timeout': 3}
    return {'hooks': {name: [{'hooks': [dict(handler)]}] for name in HOOKS}}


def connect(root: Path):
    """Explicit user command. Merge only our handlers, preserving other hooks."""
    root = Path(root).resolve()
    folder = root / '.codex'
    destination = folder / 'hooks.json'
    if folder.is_symlink() or destination.is_symlink():
        raise ValueError('refusing to replace symlinked hook configuration')
    config = json.loads(destination.read_text(encoding='utf-8')) if destination.exists() else {}
    if not isinstance(config, dict) or not isinstance(config.get('hooks', {}), dict):
        raise ValueError('existing hook configuration is not an object')
    hooks = config.setdefault('hooks', {})
    for name, groups in hook_config(root)['hooks'].items():
        existing = hooks.setdefault(name, [])
        if not isinstance(existing, list):
            raise ValueError('existing hook event must contain matcher groups')
        retained = []
        for group in existing:
            if not isinstance(group, dict) or not isinstance(group.get('hooks'), list):
                raise ValueError('invalid existing matcher group')
            handlers = [h for h in group['hooks'] if not (
                isinstance(h, dict) and h.get('statusMessage') == MARKER)]
            if handlers:
                retained.append(dict(group, hooks=handlers))
        hooks[name] = retained + groups
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / f'.research-hooks-{uuid.uuid4()}.tmp'
    try:
        temporary.write_text(_json(config) + '\n', encoding='utf-8')
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    ResearchLog(root).configure(True)
    return {'enabled': True, 'configuration': str(destination),
            'next_step': 'Review and trust these hooks in Codex, then resume the conversation. '
                         'Hook delivery in your CLI/IDE version must be verified with capture-status.'}


class CodexCapture:
    def __init__(self, root: Path):
        self.log = ResearchLog(root)
        self._lock = threading.Lock()

    @staticmethod
    def _schema(db):
        # Additive migration: existing v1 ledgers/events are kept unchanged.
        for statement in (
            '''CREATE TABLE IF NOT EXISTS capture_threads (
                thread_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, epoch TEXT NOT NULL,
                state TEXT NOT NULL, updated_at TEXT NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS capture_receipts (
                thread_id TEXT NOT NULL, source_key TEXT NOT NULL, event_id TEXT,
                PRIMARY KEY(thread_id,source_key))''',
        ):
            db.execute(statement)

    def status(self):
        if not self.log.database.exists():
            return {'enabled': False, 'threads': []}
        with self.log.connection() as db:
            self._schema(db)
            threads = []
            for row in db.execute('SELECT * FROM capture_threads ORDER BY updated_at'):
                state = json.loads(row['state'])
                threads.append({'thread_id': row['thread_id'], 'session_id': row['session_id'],
                                'last_hook_at': row['updated_at'],
                                'last_hook': state.get('last_hook'),
                                'capture_status': state.get('capture_status', 'partial'),
                                'gap_count': state.get('gap_count', 0),
                                'observed_turn_ids': list(state.get('prompts', {})),
                                'transcript_offset': state.get('offset')})
            enabled = db.execute("SELECT value FROM config WHERE key='enabled'").fetchone()
            return {'enabled': bool(enabled and enabled[0] == 'true'), 'threads': threads}

    def handle(self, payload: dict, *, delivery_id: str | None = None):
        """One hook invocation, one SQLite transaction (events + cursor + receipt).

        A host retry can supply the same delivery_id. Native hooks do not expose
        a delivery ID, so distinct prompt submissions are never text-deduplicated.
        """
        with self._lock:
            return self._handle(payload, delivery_id=delivery_id)

    def _handle(self, payload, *, delivery_id):
        if not isinstance(payload, dict):
            raise ValueError('hook payload must be an object')
        name = payload.get('hook_event_name')
        if name not in HOOKS:
            raise ValueError('unsupported Codex hook')
        cwd = Path(_identifier(payload.get('cwd'), 'cwd')).resolve()
        if not cwd.is_relative_to(self.log.root):
            raise ValueError('hook belongs to another project')
        thread = _identifier(payload.get('session_id'), 'session_id')
        turn = payload.get('turn_id')
        if turn is not None:
            turn = _identifier(turn, 'turn_id')
        if name not in ('SessionStart', 'SessionEnd') and not turn:
            raise ValueError('turn-scoped hook requires turn_id')
        if not self.log.database.exists():
            return {'recorded': False, 'reason': 'disabled'}
        with self.log.connection() as db:
            self._schema(db)
            db.execute('BEGIN IMMEDIATE')
            enabled = db.execute("SELECT value FROM config WHERE key='enabled'").fetchone()
            if not enabled or enabled[0] != 'true':
                return {'recorded': False, 'reason': 'disabled'}
            epoch = db.execute("SELECT value FROM config WHERE key='capture_epoch'").fetchone()
            epoch = epoch[0] if epoch else '0'
            row = db.execute('SELECT * FROM capture_threads WHERE thread_id=?', (thread,)).fetchone()
            if row:
                session, state = row['session_id'], json.loads(row['state'])
            else:
                session = str(uuid.uuid4())
                state = {'prompts': {}, 'model': {'provider': None, 'model': None, 'version': None},
                         'offset': 0, 'gap_count': 0,
                         'capture_status': 'hooks_only', 'last_responses': {}}
                self.log._event(db, 'session.started', session,
                                {'label': 'Codex conversation', 'schema_version': SCHEMA_VERSION,
                                 'studio_version': __version__, 'python_version': sys.version,
                                 'source': {'client': 'codex', 'thread_id': thread},
                                 'model': None, 'run_settings': None})
            self.db, self.thread, self.session, self.state = db, thread, session, state
            self.delivery = _identifier(delivery_id, 'delivery_id') if delivery_id is not None else str(uuid.uuid4())
            receipt = f'hook:{name}:{self.delivery}'
            if self._seen(receipt):
                return {'recorded': False, 'reason': 'duplicate', 'session_id': session}
            # Inspect only the explicitly supplied transcript. Never sweep ~/.codex.
            self._transcript(payload, reset=bool(row and row['epoch'] != epoch),
                             attach=not row and not (name == 'SessionStart' and
                                                    payload.get('source') == 'startup'))
            if isinstance(payload.get('model'), str):
                state['model']['model'] = payload['model']
            source = self._source(turn, hook=name)
            prompts = state['prompts'].get(turn, [])
            if name == 'UserPromptSubmit':
                text = payload.get('prompt')
                if not isinstance(text, str):
                    raise ValueError('prompt must be text')
                prompt = self._event('prompt.recorded',
                                     {'text': text, 'classification': None,
                                      'model': dict(state['model']), 'source': source},
                                     actor='human')
                state['prompts'].setdefault(turn, []).append(prompt)
            elif name in ('PreToolUse', 'PostToolUse'):
                self._tool(payload, source)
            elif name == 'Stop':
                text = payload.get('last_assistant_message')
                previous = state['last_responses'].get(turn)
                # A transcript final and Stop refer to the same assistant output.
                if isinstance(text, str) and text and not (isinstance(previous, dict) and
                        previous['hash'] == _digest(text.encode('utf-8')) and
                        previous.get('phase') != 'commentary'):
                    self._response(text, turn, dict(source, item_id=None, format='stop_hook'))
                if not state.get('transcript_verified'):
                    self._gap('assistant_intermediate_messages_unverified', turn)
                self._event('client.turn.completed', {'status': 'completed', 'source': source,
                                                      'related_prompt_ids': prompts})
            elif name == 'Interrupt':
                self._event('client.turn.interrupted', {'status': 'interrupted', 'source': source,
                                                       'related_prompt_ids': prompts})
            elif name in ('PreCompact', 'PostCompact'):
                self._event('client.context.compacted', {'source': source,
                                                        'status': name})
            elif name == 'SessionStart':
                self._event('client.session.observed', {'source': source,
                                                       'status': payload.get('source', 'unknown')})
            elif name == 'SessionEnd':
                self._event('client.session.ended', {'source': source, 'status': 'ended'})
            self._remember(receipt, None)
            state['last_hook'] = name
            state['last_hook_at'] = _now()
            db.execute('INSERT INTO capture_threads VALUES (?,?,?,?,?) '
                       'ON CONFLICT(thread_id) DO UPDATE SET epoch=excluded.epoch, '
                       'state=excluded.state,updated_at=excluded.updated_at',
                       (thread, session, epoch, _json(state), state['last_hook_at']))
            return {'recorded': True, 'session_id': session,
                    'capture_status': state['capture_status']}

    def _source(self, turn, **extra):
        return dict(client='codex', adapter_version=1, thread_id=self.thread, turn_id=turn, **extra)

    def _seen(self, key):
        return self.db.execute('SELECT 1 FROM capture_receipts WHERE thread_id=? AND source_key=?',
                               (self.thread, key)).fetchone() is not None

    def _remember(self, key, event):
        self.db.execute('INSERT INTO capture_receipts VALUES (?,?,?)', (self.thread, key, event))

    def _event(self, kind, payload, *, actor='system', prompt=None, parent=None):
        return self.log._event(self.db, kind, self.session, payload, actor=actor,
                               prompt_id=prompt, parent_id=parent)

    def _gap(self, code, turn=None):
        self.state['gap_count'] += 1
        self.state['capture_status'] = 'partial'
        self._event('capture.gap', {'code': code, 'capture_status': 'partial',
                                    'source': self._source(turn)})

    def _response(self, text, turn, source):
        prompts = self.state['prompts'].get(turn, [])
        source = dict(source)
        settings = source.pop('run_settings', None)
        self._event('model.responded', {'text': text, 'model': dict(self.state['model']),
                    'run_settings': settings, 'source': source, 'related_prompt_ids': prompts}, actor='model',
                    prompt=prompts[0] if len(prompts) == 1 else None)
        self.state['last_responses'][turn] = {'hash': _digest(text.encode('utf-8')),
                                             'phase': source.get('phase')}
        if not prompts:
            self._gap('response_without_captured_prompt', turn)

    def _tool(self, payload, source):
        call = _identifier(payload.get('tool_use_id'), 'tool_use_id')
        name = _identifier(payload.get('tool_name'), 'tool_name')
        phase = payload['hook_event_name']
        key = f'tool:{source["turn_id"]}:{call}:{phase}'
        if self._seen(key):
            return
        turn = source['turn_id']
        prompts = list(self.state['prompts'].get(turn, []))
        prompt = prompts[0] if len(prompts) == 1 else None
        source = dict(source, tool_call_id=call)
        if phase == 'PreToolUse':
            event = self._event('action.started', {
                'name': name, 'arguments': payload.get('tool_input'),
                'state': self.log.snapshot(self.db), 'source': source,
                'related_prompt_ids': prompts}, prompt=prompt)
        else:
            parent = self.db.execute('SELECT event_id FROM capture_receipts WHERE thread_id=? '
                                     'AND source_key=?',
                                     (self.thread, f'tool:{turn}:{call}:PreToolUse')).fetchone()
            if parent:
                start = self.db.execute('SELECT * FROM events WHERE id=?', (parent[0],)).fetchone()
                original = json.loads(start['payload'])
                if original['name'] != name:
                    self._gap('tool_identity_mismatch', turn)
                    return
                prompts, prompt = original['related_prompt_ids'], start['prompt_id']
                elapsed = max(0.0, (datetime.now(timezone.utc) -
                                   datetime.fromisoformat(start['timestamp'])).total_seconds())
            else:
                self._gap('tool_finish_without_start', turn)
                elapsed = None
            event = self._event('action.finished', {
                'name': name, 'result': payload.get('tool_response'), 'source': source,
                'duration_seconds': elapsed, 'time_source': 'hook_observation_wall_clock',
                'state': self.log.snapshot(self.db), 'related_prompt_ids': prompts,
            }, prompt=prompt, parent=parent[0] if parent else None)
        self._remember(key, event)

    def _transcript(self, payload, *, reset, attach):
        raw_path = payload.get('transcript_path')
        self.state['transcript_verified'] = False
        if not raw_path:
            if reset:
                self._gap('collection_paused')
            self.state['capture_status'] = 'partial' if self.state['gap_count'] else 'hooks_only'
            return
        if not isinstance(raw_path, str):
            raise ValueError('transcript_path must be text or null')
        path = Path(raw_path)
        # Read only regular files; avoid devices/FIFOs and symlink traversal.
        if path.is_symlink() or any(p.is_symlink() for p in path.parents) or not path.is_file():
            self._gap('transcript_unavailable')
            return
        file_key = _digest(str(path.resolve()).encode('utf-8'))
        try:
            with path.open('rb') as stream:
                header = stream.readline(MAX_LINE + 1)
                try:
                    meta = json.loads(header)
                except (ValueError, UnicodeError):
                    self._gap('unrecognized_transcript_header')
                    return
                if (not isinstance(meta, dict) or meta.get('type') != 'session_meta' or not isinstance(meta.get('payload'), dict)
                        or meta['payload'].get('id') != self.thread):
                    self._gap('transcript_identity_mismatch')
                    return
                meta = meta['payload']
                if not isinstance(meta.get('cwd'), str) or not Path(meta['cwd']).resolve().is_relative_to(self.log.root):
                    self._gap('transcript_project_mismatch')
                    return
                if isinstance(meta.get('cli_version'), str):
                    self.state['model']['client_version'] = meta['cli_version']
                if isinstance(meta.get('model_provider'), str):
                    self.state['model']['provider'] = meta['model_provider']
                if isinstance(meta.get('source'), str):
                    self.state['model']['client_surface'] = meta['source']
                prefix = _digest(header)
                size = os.fstat(stream.fileno()).st_size
                offset = self.state['offset']
                changed = bool(self.state.get('file_key') and (
                    self.state['file_key'] != file_key or self.state.get('header_hash') != prefix))
                anchor = self.state.get('anchor')
                if anchor and not changed and size >= offset:
                    stream.seek(max(0, offset - 128))
                    changed = _digest(stream.read(min(offset, 128))) != anchor
                if reset or attach or changed or size < offset:
                    self._gap('collection_paused' if reset else 'attached_mid_conversation' if attach
                              else 'transcript_replaced_or_truncated')
                    offset = size  # Never import old or paused conversation content.
                    self.state.pop('transcript_turn', None)
                    self.state.pop('transcript_dialect', None)
                    self.state.pop('discarding_record', None)
                self.state.update(file_key=file_key, header_hash=prefix, offset=offset)
                stream.seek(offset)
                consumed = 0
                while consumed < MAX_BATCH:
                    start = stream.tell()
                    line = stream.readline(MAX_LINE + 1)
                    if not line:
                        break
                    if self.state.get('discarding_record'):
                        self.state['discarding_record'] = not line.endswith(b'\n')
                        self.state['offset'] = stream.tell()
                        consumed += len(line)
                        continue
                    if not line.endswith(b'\n'):
                        # Retry incomplete UTF-8/JSON only after its newline arrives.
                        if len(line) > MAX_LINE:
                            self._gap('transcript_record_too_large')
                            self.state['discarding_record'] = True
                            self.state['offset'] = stream.tell()
                            consumed += len(line)
                            continue
                        break
                    consumed += len(line)
                    try:
                        item = json.loads(line)
                        self._transcript_item(item, file_key, start)
                    except (ValueError, TypeError, KeyError, UnicodeError):
                        self._gap('unrecognized_transcript_record')
                    self.state['offset'] = stream.tell()
                if stream.tell() < size:
                    self.state['capture_status'] = 'partial'
                elif not self.state['gap_count']:
                    self.state['capture_status'] = 'hooks_and_transcript_best_effort'
                end = self.state['offset']
                stream.seek(max(0, end - 128))
                self.state['anchor'] = _digest(stream.read(min(end, 128)))
                self.state['transcript_verified'] = self.state.get('transcript_dialect') == 1
        except OSError:
            self._gap('transcript_unavailable')

    def _transcript_item(self, record, file_key, offset):
        if not isinstance(record, dict) or not isinstance(record.get('payload'), dict):
            raise ValueError('invalid transcript record')
        kind, item = record.get('type'), record['payload']
        if kind == 'session_meta':
            return
        if kind == 'turn_context':
            self.state['transcript_turn'] = _identifier(item.get('turn_id'), 'turn_id')
            self.state['transcript_dialect'] = 1
            if isinstance(item.get('model'), str):
                self.state['model']['model'] = item['model']
            # Deliberate allowlist: never persist arbitrary config/auth/environment.
            self.state['run_settings'] = {k: item[k] for k in ('effort', 'summary')
                                          if isinstance(item.get(k), str)}
            return
        if kind in ('event_msg', 'compacted'):
            # event_msg duplicates response_item messages; compaction is not human input.
            return
        if kind != 'response_item':
            raise ValueError('unknown transcript record type')
        if item.get('type') != 'message':
            if item.get('type') not in ('reasoning', 'function_call', 'function_call_output',
                    'custom_tool_call', 'custom_tool_call_output', 'web_search_call',
                    'local_shell_call', 'image_generation_call', 'compaction'):
                raise ValueError('unknown response item')
            return
        if item.get('role') in ('user', 'system', 'developer'):
            return  # Hooks are authoritative for actual human prompt submissions.
        if item.get('role') != 'assistant' or not isinstance(item.get('content'), list):
            raise ValueError('unknown message shape')
        if (item.get('phase') not in (None, 'commentary', 'final_answer') or
                item.get('channel') not in (None, 'commentary', 'final')):
            raise ValueError('not a supported visible assistant message')
        parts = item['content']
        if any(not isinstance(p, dict) or p.get('type') not in ('output_text', 'text')
               or not isinstance(p.get('text'), str) for p in parts):
            raise ValueError('unsupported assistant content')
        turn = self.state.get('transcript_turn')
        if not turn:
            raise ValueError('message without turn context')
        item_id = item.get('id')
        if item_id is not None:
            item_id = _identifier(item_id, 'item_id')
        timestamp = record.get('timestamp')
        if timestamp is not None:
            if not isinstance(timestamp, str):
                raise ValueError('invalid source timestamp')
            datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        key = f'transcript:{file_key}:{offset}'
        if self._seen(key):
            return
        text = ''.join(p['text'] for p in parts)
        # Stop may have arrived before the buffered transcript was flushed.
        existing = self.db.execute("SELECT id,payload FROM events WHERE session_id=? "
                                   "AND type='model.responded'", (self.session,)).fetchall()
        fallback = next((r for r in reversed(existing) if not self._seen('fallback:' + r['id']) and (
            (p := json.loads(r['payload'])).get('source', {}).get('format') == 'stop_hook'
            and p['source'].get('turn_id') == turn and p.get('text') == text)), None)
        if fallback and item.get('phase') != 'commentary':
            self._remember(key, fallback['id'])
            self._remember('fallback:' + fallback['id'], fallback['id'])
            return
        self._response(text, turn, self._source(turn, item_id=item_id,
                       timestamp=timestamp, byte_offset=offset,
                       phase=item.get('phase'), format='codex_rollout_v1',
                       run_settings=self.state.get('run_settings', {})))
        self._remember(key, None)
