from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from manim_studio.research import ResearchLog
from manim_studio.research_capture import CodexCapture
from manim_studio.research_sessions import ResearchSessions, ResearchSessionError


class ResearchSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.log = ResearchLog(self.root)
        self.log.configure(True)
        self.manager = ResearchSessions(self.root)

    def call(self, action, **payload):
        if action not in ('configure', 'list', 'get', 'sources', 'status'):
            payload.setdefault('request_id', str(uuid.uuid4()))
        return self.manager.dispatch(action, payload)

    def create(self, title='Vectors'):
        return self.call('create', title=title, topic='Vectors')

    def change(self, action, session):
        return self.call(action, session_id=session['session_id'], expected_revision=session['revision'])

    def events(self, session=None):
        with self.log.connection() as db:
            return [dict(r, payload=json.loads(r['payload'])) for r in db.execute(
                'SELECT * FROM events ORDER BY seq') if session is None or r['session_id'] == session]

    def append(self, path, kind, payload):
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'type': kind, 'payload': payload}, ensure_ascii=False) + '\n')

    def observe(self, thread='thread-a'):
        path = self.root / (thread + '.jsonl')
        self.append(path, 'session_meta', {'id': thread, 'cwd': str(self.root)})
        self.hook(thread, path, 'SessionStart', source='startup')
        source = next(s for s in self.manager.sources()['sources'] if s['thread_id'] == thread)
        return path, source

    def hook(self, thread, path, name, turn='turn-1', **payload):
        return CodexCapture(self.root).handle(dict(cwd=str(self.root), session_id=thread,
            transcript_path=str(path), turn_id=turn, hook_event_name=name, **payload))

    def bind(self, session, thread='thread-a'):
        path, source = self.observe(thread)
        updated = self.call('attach_source', session_id=session['session_id'],
                            source_id=source['source_id'], expected_revision=session['revision'])
        return updated, path

    def turn(self, thread, path, turn, prompt, answer):
        self.hook(thread, path, 'UserPromptSubmit', turn, prompt=prompt)
        self.append(path, 'turn_context', {'turn_id': turn, 'model': 'test'})
        self.append(path, 'response_item', {'type': 'message', 'role': 'assistant',
                    'phase': 'final_answer', 'content': [{'type': 'output_text', 'text': answer}]})
        self.hook(thread, path, 'Stop', turn, last_assistant_message=answer)

    def test_lifecycle_identity_persists_and_finished_cannot_resume(self):
        session = self.create()
        session = self.change('pause', session)
        self.manager = ResearchSessions(self.root)
        self.assertEqual(self.manager.get(session['session_id'])['state'], 'paused')
        resumed = self.change('resume', session)
        self.assertEqual(resumed['session_id'], session['session_id'])
        finished = self.change('finish', resumed)
        with self.assertRaisesRegex(ResearchSessionError, 'session_finished'):
            self.change('resume', finished)
        self.assertNotEqual(self.create()['session_id'], session['session_id'])

    def test_retry_after_lost_reply_returns_original_result_and_rejects_changed_request(self):
        payload = dict(title='Vectors', topic='Math', request_id='stable-request')
        first = self.call('create', **payload)
        reopened = ResearchSessions(self.root)
        self.assertEqual(reopened.dispatch('create', payload), first)
        self.assertEqual(reopened.dispatch('create', dict(reversed(list(payload.items())))), first)
        self.assertEqual(len(self.manager.list()['sessions']), 1)
        with self.assertRaisesRegex(ResearchSessionError, 'request_id_conflict'):
            reopened.dispatch('create', dict(payload, topic='Other'))

    def test_concurrent_windows_cannot_overwrite_revision(self):
        s = self.create()
        def transition(action):
            try:
                return self.change(action, s)['state']
            except ResearchSessionError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(transition, ['pause', 'finish']))
        self.assertEqual(results.count('revision_conflict'), 1)
        self.assertEqual(self.manager.get(s['session_id'])['revision'], 2)

    def test_create_failure_rolls_back_identity_and_request(self):
        original = ResearchLog._event
        def fail(log, db, *args, **kwargs):
            original(log, db, *args, **kwargs)
            raise OSError('simulated loss')
        payload = dict(title='retry', topic='topic', request_id='retry')
        with patch.object(ResearchLog, '_event', fail):
            with self.assertRaises(OSError):
                self.call('create', **payload)
        self.assertEqual(self.events(), [])
        self.assertEqual(len(self.call('create', **payload)['session_id']), 36)

    def test_unbound_source_collects_no_content_or_fake_session(self):
        self.create()
        path, _ = self.observe()
        self.turn('thread-a', path, 'old', 'PRIVATE BEFORE BINDING', 'PRIVATE RESPONSE')
        self.assertNotIn('PRIVATE', json.dumps(self.events()))
        self.assertEqual(len([e for e in self.events() if e['type'] == 'session.started']), 1)

    def test_attach_skips_old_history_then_records_exact_messages(self):
        session = self.create()
        path, source = self.observe()
        self.turn('thread-a', path, 'old', 'BEFORE BINDING', 'OLD ANSWER')
        session = self.call('attach_source', session_id=session['session_id'], source_id=source['source_id'],
                            expected_revision=session['revision'])
        self.turn('thread-a', path, 'new', 'שאלה', 'תשובה')
        messages = [e for e in self.events() if e['type'] in ('prompt.recorded', 'model.responded')]
        self.assertEqual([e['payload']['text'] for e in messages], ['שאלה', 'תשובה'])
        self.assertEqual(messages[1]['prompt_id'], messages[0]['id'])
        self.assertEqual({e['session_id'] for e in messages}, {session['session_id']})

    def test_source_cannot_be_rebound_and_session_has_one_thread(self):
        a, b = self.create('A'), self.create('B')
        a, path = self.bind(a)
        source = self.manager.sources()['sources'][0]
        with self.assertRaisesRegex(ResearchSessionError, 'source_already_bound'):
            self.call('attach_source', session_id=b['session_id'], source_id=source['source_id'], expected_revision=b['revision'])
        _, other = self.observe('thread-b')
        with self.assertRaisesRegex(ResearchSessionError, 'session_already_bound'):
            self.call('attach_source', session_id=a['session_id'], source_id=other['source_id'], expected_revision=a['revision'])

    def test_parallel_research_and_pause_are_independent_and_private(self):
        a, pa = self.bind(self.create('A'), 'a')
        b, pb = self.bind(self.create('B'), 'b')
        self.turn('a', pa, 'a1', 'A1', 'Answer A1')
        a = self.change('pause', a)
        self.turn('a', pa, 'paused', 'PAUSED PRIVATE', 'PAUSED PRIVATE ANSWER')
        self.turn('b', pb, 'b1', 'B1', 'Answer B1')
        a = self.change('resume', a)
        self.turn('a', pa, 'a2', 'A2', 'Answer A2')
        records = self.events()
        self.assertNotIn('PRIVATE', json.dumps(records))
        for e in records:
            if e['type'] == 'prompt.recorded':
                self.assertEqual(e['session_id'], a['session_id'] if e['payload']['text'].startswith('A') else b['session_id'])
        destination = self.root / 'export.jsonl'
        self.log.export(destination, True)
        self.assertNotIn('PRIVATE', destination.read_text(encoding='utf-8'))
        self.assertEqual(len([e for e in records if e['type'] == 'model.responded']), 3)

    def test_finished_terminal_context_does_not_record_or_block_operation(self):
        from manim_mcp.services import StudioContext, list_decks
        s = self.create()
        self.call('bind_client', session_id=s['session_id'], client_id='terminal', client_type='terminal')
        self.change('finish', s)
        context = StudioContext(self.root, research_client_id='terminal')
        with self.assertWarns(RuntimeWarning):
            response = list_decks(context)
        self.assertIsInstance(response, dict)
        self.assertEqual(len([e for e in self.events() if e['type'].startswith('action.')]), 0)

    def test_old_action_result_cannot_leak_after_pause_and_resume(self):
        s = self.create()
        p = self.log.record_prompt(s['session_id'], 'work')
        action = self.log.begin_action(s['session_id'], 'edit', {}, p)
        s = self.change('pause', s)
        s = self.change('resume', s)
        with self.assertRaisesRegex(ValueError, 'boundary'):
            self.log.end_action(s['session_id'], action, {'text': 'PRIVATE RESULT'}, 1, p)
        self.assertNotIn('PRIVATE RESULT', json.dumps(self.events()))
        self.assertEqual(self.manager.get(s['session_id'])['incomplete_actions'], 1)
        self.assertEqual(len([e for e in self.events() if e['type'] == 'action.observation_ended']), 1)

    def test_same_turn_late_response_after_resume_is_not_assigned_to_new_prompt(self):
        s, path = self.bind(self.create())
        self.hook('thread-a', path, 'UserPromptSubmit', 'mixed', prompt='before pause')
        self.append(path, 'turn_context', {'turn_id': 'mixed'})
        s = self.change('pause', s)
        self.hook('thread-a', path, 'Stop', 'mixed', last_assistant_message='PRIVATE PAUSED')
        s = self.change('resume', s)
        self.hook('thread-a', path, 'UserPromptSubmit', 'mixed', prompt='new steering')
        self.hook('thread-a', path, 'Stop', 'mixed', last_assistant_message='PRIVATE PAUSED')
        self.assertNotIn('PRIVATE PAUSED', json.dumps(self.events()))
        self.assertTrue(any(e['type'] == 'capture.gap' for e in self.events()))

    def test_legacy_adoption_preserves_event_identity_and_content(self):
        path, source = self.observe()
        self.turn('thread-a', path, 'legacy', 'legacy prompt', 'legacy answer')
        before = self.events()
        adopted = self.call('adopt_legacy', session_id=source['session_id'], title='Adopted', topic='Topic')
        self.assertEqual(adopted['session_id'], source['session_id'])
        self.assertEqual(self.events()[:len(before)], before)
        self.assertEqual(len([e for e in self.events() if e['type'] == 'session.started']), 1)

    def test_context_validation_never_falls_back_or_guesses_prompt(self):
        a, b = self.create('A'), self.create('B')
        self.call('bind_client', session_id=a['session_id'], client_id='a', client_type='rpc')
        self.assertEqual(self.manager.resolve(client_id='a'), (a['session_id'], None))
        with self.assertRaisesRegex(ResearchSessionError, 'context_conflict'):
            self.manager.resolve(b['session_id'], client_id='a')
        with self.assertRaisesRegex(ResearchSessionError, 'unbound_client'):
            self.manager.resolve()
        p = self.log.record_prompt(b['session_id'], 'B')
        with self.assertRaisesRegex(ResearchSessionError, 'prompt_mismatch'):
            self.manager.resolve(a['session_id'], p)

    def test_logging_storage_failure_does_not_break_authoring(self):
        from manim_mcp.services import StudioContext, list_decks
        ctx = StudioContext(self.root)
        expected = list_decks(ctx)
        with patch.object(ResearchSessions, 'resolve', side_effect=OSError('storage unavailable')):
            with self.assertWarns(RuntimeWarning):
                self.assertEqual(list_decks(ctx), expected)

    def test_direct_stale_prompt_response_cannot_cross_pause_boundary(self):
        s = self.create()
        prompt = self.log.record_prompt(s['session_id'], 'old prompt')
        s = self.change('pause', s)
        s = self.change('resume', s)
        with self.assertRaisesRegex(ValueError, 'boundary'):
            self.log.record_response(s['session_id'], prompt, 'PRIVATE LATE RESPONSE')
        self.assertNotIn('PRIVATE LATE RESPONSE', json.dumps(self.events()))

    def test_unknown_paused_tool_turn_cannot_leak_result_on_resume(self):
        s, path = self.bind(self.create())
        s = self.change('pause', s)
        # Multiple turns can be observed while paused; a result from an earlier
        # paused turn arrives after resumption, rather than the last observed turn.
        self.hook('thread-a', path, 'PreToolUse', 'paused-one', tool_name='shell', tool_use_id='old', tool_input={'text': 'PRIVATE TOOL'})
        self.hook('thread-a', path, 'UserPromptSubmit', 'paused-two', prompt='PRIVATE SECOND')
        s = self.change('resume', s)
        self.hook('thread-a', path, 'PostToolUse', 'paused-one', tool_name='shell', tool_use_id='old', tool_response='PRIVATE TOOL RESULT')
        self.assertNotIn('PRIVATE', json.dumps(self.events()))

    def test_global_pause_after_binding_does_not_backfill_transcript(self):
        s, path = self.bind(self.create())
        self.log.configure(False)
        self.append(path, 'turn_context', {'turn_id': 'private'})
        self.append(path, 'response_item', {'type': 'message', 'role': 'assistant',
                    'content': [{'type': 'output_text', 'text': 'PRIVATE GLOBAL'}]})
        self.log.configure(True)
        self.turn('thread-a', path, 'new', 'new prompt', 'new answer')
        self.assertNotIn('PRIVATE GLOBAL', json.dumps(self.events()))
        self.assertEqual(len([e for e in self.events() if e['type'] == 'model.responded']), 1)

    def test_unread_buffer_at_pause_is_reported_as_a_persistent_coverage_gap(self):
        s, path = self.bind(self.create())
        self.hook('thread-a', path, 'UserPromptSubmit', 'first', prompt='first')
        self.append(path, 'turn_context', {'turn_id': 'first'})
        self.append(path, 'response_item', {'type': 'message', 'role': 'assistant',
                    'content': [{'type': 'output_text', 'text': 'BUFFERED BEFORE PAUSE'}]})
        s = self.change('pause', s)
        s = self.change('resume', s)
        self.turn('thread-a', path, 'next', 'new', 'answer')
        status = self.call('status', session_id=s['session_id'])
        self.assertEqual(status['capture'][0]['capture_status'], 'partial')
        self.assertGreater(status['capture'][0]['gap_count'], 0)
        self.assertTrue(any(e['type'] == 'capture.gap' and e['payload']['code'] == 'collection_boundary_skipped_bytes' for e in self.events()))

    def test_real_legacy_schema_adoption_cannot_accept_second_source(self):
        path, source = self.observe()
        # Emulate a v2 ledger: the old adapter had no research_sources registry.
        with self.log.connection() as db:
            db.execute('DELETE FROM research_sources')
        s = self.call('adopt_legacy', session_id=source['session_id'], title='Legacy', topic='Topic')
        _, other = self.observe('other-thread')
        with self.assertRaisesRegex(ResearchSessionError, 'session_already_bound'):
            self.call('attach_source', session_id=s['session_id'], source_id=other['source_id'], expected_revision=s['revision'])

    def test_explicit_empty_rpc_context_does_not_use_stale_environment(self):
        from manim_studio.authoring_sessions import AuthoringSessionController
        s = self.create()
        controller = AuthoringSessionController(self.root, check_executables=False)
        with patch.dict(os.environ, {'MANIM_STUDIO_RESEARCH_SESSION': s['session_id']}):
            with self.assertWarns(RuntimeWarning):
                controller.dispatch('list_sessions', {'_research': {}})
        self.assertFalse(any(e['type'] == 'action.started' for e in self.events()))

    def test_managed_collection_does_not_use_an_unbound_legacy_environment(self):
        from manim_mcp.services import default_context, list_decks
        legacy = self.log.start_session('Installer legacy session')
        self.create()
        with patch.dict(os.environ, {'MANIM_STUDIO_REPO_ROOT': str(self.root),
                         'MANIM_STUDIO_RESEARCH_SESSION': legacy, 'MANIM_STUDIO_RESEARCH_CLIENT': ''}):
            with self.assertWarns(RuntimeWarning):
                list_decks(default_context())
        self.assertFalse(any(e['type'] == 'action.started' for e in self.events()))

    def test_bound_terminal_environment_has_current_attribution(self):
        from manim_mcp.services import default_context, list_decks
        session = self.create()
        self.call('bind_client', session_id=session['session_id'], client_id='terminal-env', client_type='terminal')
        with patch.dict(os.environ, {'MANIM_STUDIO_REPO_ROOT': str(self.root),
                         'MANIM_STUDIO_RESEARCH_SESSION': session['session_id'],
                         'MANIM_STUDIO_RESEARCH_CLIENT': 'terminal-env', 'MANIM_STUDIO_RESEARCH_PROMPT': ''}):
            list_decks(default_context())
        actions = [e for e in self.events() if e['type'] == 'action.started']
        self.assertEqual(actions[0]['session_id'], session['session_id'])
        self.assertEqual(actions[0]['payload']['source']['client_id'], 'terminal-env')

    def test_managed_enable_discovers_sources_without_creating_legacy_sessions(self):
        self.call('configure', enabled=True)
        path, source = self.observe()
        self.assertIsNone(source['session_id'])
        self.assertFalse(self.events())

    def test_actual_process_crash_before_and_after_commit(self):
        environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
        script = '''
import json, os, sys
from manim_studio.research_sessions import ResearchSessions
root, mode, payload = json.load(sys.stdin)
if mode == 'before':
    original = ResearchSessions._create
    def fail(self, *args, **kwargs):
        original(self, *args, **kwargs)
        os._exit(29)
    ResearchSessions._create = fail
result = ResearchSessions(root).dispatch('create', payload)
print(json.dumps(result), flush=True)
os._exit(30)
'''
        before = dict(title='Before crash', topic='Math', request_id='crash-before')
        result = subprocess.run([sys.executable, '-X', 'utf8', '-c', script],
            input=json.dumps([str(self.root), 'before', before]), text=True,
            capture_output=True, env=environment, timeout=15)
        self.assertEqual(result.returncode, 29, result.stderr)
        self.assertEqual(self.manager.list()['sessions'], [])
        self.assertFalse(self.events())
        recovered = self.manager.dispatch('create', before)
        after = dict(title='After commit', topic='Math', request_id='crash-after')
        result = subprocess.run([sys.executable, '-X', 'utf8', '-c', script],
            input=json.dumps([str(self.root), 'after', after]), text=True,
            capture_output=True, env=environment, timeout=15)
        self.assertEqual(result.returncode, 30, result.stderr)
        saved = json.loads(result.stdout)
        self.assertEqual(ResearchSessions(self.root).dispatch('create', after), saved)
        self.assertNotEqual(saved['session_id'], recovered['session_id'])
        self.assertEqual(len(self.manager.list()['sessions']), 2)

    def test_explicit_mcp_client_overrides_stale_base_context(self):
        import asyncio
        from manim_mcp.server import create_server
        from manim_mcp.services import StudioContext
        a, b = self.create('A'), self.create('B')
        self.call('bind_client', session_id=b['session_id'], client_id='B', client_type='mcp')
        server = create_server(StudioContext(self.root, research_session_id=a['session_id']))
        asyncio.run(server.call_tool('list_decks', {'research_client_id': 'B'}))
        actions = [e for e in self.events() if e['type'] == 'action.started']
        self.assertEqual([e['session_id'] for e in actions], [b['session_id']])

    def test_cross_project_context_is_rejected_without_guessing(self):
        session = self.create()
        with tempfile.TemporaryDirectory() as other:
            log = ResearchLog(Path(other)); log.configure(True)
            with self.assertRaisesRegex(ResearchSessionError, 'session_not_found'):
                ResearchSessions(Path(other)).resolve(session['session_id'])

    def test_real_mcp_transport_controls_lifecycle_and_request_attribution(self):
        import asyncio
        import shutil
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        shutil.copytree(Path(__file__).parent / 'fixtures' / 'external_project', self.root, dirs_exist_ok=True)
        environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'), MANIM_STUDIO_REPO_ROOT=str(self.root))
        async def run():
            params = StdioServerParameters(command=sys.executable, args=['-X', 'utf8', '-m', 'manim_mcp.server'], env=environment, cwd=str(self.root))
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as client:
                    await client.initialize()
                    async def call(tool, arguments):
                        result = await client.call_tool(tool, arguments)
                        self.assertFalse(result.isError, result)
                        data = result.structuredContent or json.loads(result.content[0].text)
                        self.assertTrue(data['ok'], data)
                        return data['data']
                    async def manage(action, **payload):
                        return await call('research_log', {'action': 'research.' + action,
                            'payload': dict(payload, request_id=str(uuid.uuid4()))})
                    a = await manage('create', title='A', topic='Math')
                    b = await manage('create', title='B', topic='Other')
                    await manage('bind_client', session_id=a['session_id'], client_id='mcp-A', client_type='mcp')
                    await manage('bind_client', session_id=b['session_id'], client_id='mcp-B', client_type='mcp')
                    await call('list_decks', {'research_client_id': 'mcp-A'})
                    a = await manage('pause', session_id=a['session_id'], expected_revision=a['revision'])
                    await call('list_decks', {'research_client_id': 'mcp-A'})
                    await call('list_decks', {'research_client_id': 'mcp-B'})
                    a = await manage('resume', session_id=a['session_id'], expected_revision=a['revision'])
                    await call('list_decks', {'research_client_id': 'mcp-A'})
                    await manage('finish', session_id=a['session_id'], expected_revision=a['revision'])
                    actions = [e for e in self.events() if e['type'] == 'action.started']
                    self.assertEqual([e['session_id'] for e in actions], [a['session_id'], b['session_id'], a['session_id']])
                    self.assertEqual({e['prompt_id'] for e in actions}, {None})
                    self.assertEqual([e['payload']['source']['client_id'] for e in actions], ['mcp-A', 'mcp-B', 'mcp-A'])
        asyncio.run(asyncio.wait_for(run(), timeout=30))

    def test_paused_direct_bridge_cannot_record_content_or_blobs(self):
        s = self.change('pause', self.create())
        with self.assertRaisesRegex(ValueError, 'paused'):
            self.log.record_prompt(s['session_id'], 'PRIVATE')
        with self.assertRaisesRegex(ValueError, 'paused'):
            self.log.begin_action(s['session_id'], 'edit', {'text': 'PRIVATE'})
        self.assertNotIn('PRIVATE', json.dumps(self.events()))

    def test_real_rpc_and_cli_processes_share_the_same_lifecycle(self):
        environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
        request = dict(id=1, method='research.create', params=dict(title='Remote', topic='Math', request_id='rpc-create'))
        result = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'manim_studio.cli', 'authoring', 'rpc', '--repo-root', str(self.root)],
                                input=json.dumps(request)+'\n', text=True, capture_output=True, env=environment, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertTrue(response['ok'], response)
        session = response['data']
        result = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'manim_studio.research_cli', '--root', str(self.root), 'research.pause'],
            input=json.dumps(dict(session_id=session['session_id'], expected_revision=session['revision'], request_id='cli-pause')),
            text=True, capture_output=True, env=environment, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['data']['state'], 'paused')
        self.assertEqual(self.manager.get(session['session_id'])['state'], 'paused')
        self.assertFalse(any(e['type'].startswith('action.') for e in self.events()))

