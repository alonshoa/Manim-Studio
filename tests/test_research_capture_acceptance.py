"""Closure checks: subprocess integration and regressions found on 2026-10-31.

These do not substitute for native Codex / VS Code / Windows delivery checks.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from tests import test_research_capture as fixtures


class CaptureAcceptanceTests(fixtures.CaptureTests):
    # Inherit the tested ledger fixture, but collect only the new acceptance cases.
    __unittest_skip__ = False

    def cli(self, action, payload=None):
        result = subprocess.run(
            [sys.executable, '-m', 'manim_studio.research_cli', '--root', str(self.root), action],
            input=json.dumps(payload or {}, ensure_ascii=False), text=True,
            encoding='utf-8', capture_output=True,
            env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src')),
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_cli_workflow_with_edit_failure_resume_classify_and_export(self):
        def hook(name, **extra):
            payload = dict(session_id='thread1', cwd=str(self.root),
                           transcript_path=str(self.transcript), turn_id='turn1',
                           hook_event_name=name, **extra)
            result = self.cli('codex-hook', payload)
            self.assertEqual(json.loads(result.stdout), {})
            self.assertEqual(result.stderr, '')

        self.cli('codex-connect')
        hook('UserPromptSubmit', prompt='הוסף דוגמה')
        self.append('turn_context', {'turn_id': 'turn1', 'model': 'integration-fixture'})
        self.response('בודק את הדוגמה', 'commentary')
        source = self.root / 'decks' / 'scene.py'
        source.parent.mkdir()
        source.write_text('before', encoding='utf-8')
        hook('PreToolUse', tool_name='apply_patch', tool_use_id='edit1', tool_input={})
        source.write_text('after', encoding='utf-8')
        hook('PostToolUse', tool_name='apply_patch', tool_use_id='edit1', tool_response={'ok': True})
        hook('PreToolUse', tool_name='render', tool_use_id='render1', tool_input={})
        hook('PostToolUse', tool_name='render', tool_use_id='render1',
             tool_response={'ok': False, 'error': 'synthetic render failure'})
        self.response('הרינדור נכשל')
        hook('Stop', last_assistant_message='הרינדור נכשל')
        first_status = json.loads(self.cli('capture-status').stdout)['data']
        session = first_status['threads'][0]['session_id']
        hook('SessionStart', source='resume')
        prompt = self.typed('prompt.recorded')[0]['id']
        self.cli('classify', dict(session_id=session, prompt_id=prompt,
                                 prompt_type='corrective', reasons=['technical_render']))
        destination = self.root / 'complete.jsonl'
        self.cli('export', dict(destination=str(destination), include_content=True))
        records = [json.loads(line) for line in destination.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(self.typed('prompt.recorded')), 1)
        self.assertEqual(len(self.typed('model.responded')), 2)
        starts = {event['id']: event for event in self.typed('action.started')}
        finishes = self.typed('action.finished')
        self.assertEqual(len(finishes), 2)
        for finish in finishes:
            self.assertEqual(finish['prompt_id'], prompt)
            self.assertEqual(starts[finish['parent_id']]['prompt_id'], prompt)
        self.assertFalse(finishes[-1]['payload']['result']['ok'])
        before = starts[finishes[0]['parent_id']]['payload']['state']['files']['decks/scene.py']
        after = finishes[0]['payload']['state']['files']['decks/scene.py']
        self.assertNotEqual(before, after)
        self.assertTrue(any(r['type'] == 'source.blob' for r in records))
        self.assertTrue(any(r['type'] == 'classification.confirmed' for r in records))
        self.assertFalse(self.typed('capture.gap'))
        status = json.loads(self.cli('capture-status').stdout)['data']
        self.assertEqual(status['threads'][0]['session_id'], session)

    def test_buffered_final_replay_does_not_duplicate_on_next_stop(self):
        self.prompt()
        self.send('Stop', last_assistant_message='final')
        # Stop can precede a buffered commentary + final transcript flush.
        self.response('working', 'commentary')
        self.response('final')
        self.send('Stop', last_assistant_message='final')
        # The reconciled response state must survive a new adapter instance.
        self.capture = fixtures.CodexCapture(self.root)
        self.send('Stop', last_assistant_message='final')
        finals = [e for e in self.typed('model.responded') if e['payload']['text'] == 'final']
        self.assertEqual(len(finals), 1, 'buffered replay must reconcile the Stop fallback')
        self.assertEqual(len(self.typed('model.responded')), 2)

    def test_real_mcp_stdio_transport_preserves_capture_ids(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        shutil.copytree(Path(__file__).parent / 'fixtures' / 'external_project',
                        self.root, dirs_exist_ok=True)
        self.prompt('list decks')
        session = self.capture.status()['threads'][0]['session_id']
        prompt = self.typed('prompt.recorded')[0]['id']
        environment = dict(os.environ,
            PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'),
            MANIM_STUDIO_REPO_ROOT=str(self.root))
        async def run():
            parameters = StdioServerParameters(command=sys.executable,
                args=['-m', 'manim_mcp.server'], env=environment, cwd=str(self.root))
            async with stdio_client(parameters) as (reader, writer):
                async with ClientSession(reader, writer) as client:
                    await client.initialize()
                    result = await client.call_tool('list_decks', {
                        'research_session_id': session, 'research_prompt_id': prompt})
                    self.assertFalse(result.isError, result)
                    content = result.structuredContent or json.loads(result.content[0].text)
                    self.assertTrue(content['ok'], content)
                    # A real service failure is returned and recorded over the same transport.
                    result = await client.call_tool('render_scene', {
                        'target': 'demo/missing', 'research_session_id': session,
                        'research_prompt_id': prompt})
                    self.assertFalse(result.isError, result)
                    content = result.structuredContent or json.loads(result.content[0].text)
                    self.assertFalse(content['ok'], content)
        asyncio.run(asyncio.wait_for(run(), timeout=20))
        starts = self.typed('action.started')
        finishes = self.typed('action.finished')
        self.assertEqual(len(starts), 2)
        self.assertEqual(len(finishes), 2)
        self.assertEqual({e['prompt_id'] for e in starts + finishes}, {prompt})
        self.assertEqual({e['parent_id'] for e in finishes}, {e['id'] for e in starts})
        self.assertFalse(finishes[-1]['payload']['result']['ok'])

    def test_real_authoring_rpc_transport_preserves_capture_ids(self):
        self.prompt('list sessions')
        session = self.capture.status()['threads'][0]['session_id']
        prompt = self.typed('prompt.recorded')[0]['id']
        request = {'id': 1, 'method': 'list_sessions', 'params': {
            '_research': {'session_id': session, 'prompt_id': prompt}}}
        result = subprocess.run([sys.executable, '-m', 'manim_studio.cli',
            'authoring', 'rpc', '--repo-root', str(self.root)],
            input=json.dumps(request) + '\n', text=True, capture_output=True,
            env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src')),
            timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        reply = json.loads(result.stdout)
        self.assertEqual(reply['id'], 1)
        self.assertTrue(reply['ok'], reply)
        start, finish = self.typed('action.started')[0], self.typed('action.finished')[0]
        self.assertEqual(start['payload']['name'], 'authoring.list_sessions')
        self.assertEqual(start['prompt_id'], prompt)
        self.assertEqual(finish['parent_id'], start['id'])
        self.assertEqual(finish['prompt_id'], prompt)

    def test_incomplete_transcript_is_not_reported_as_complete(self):
        self.prompt()
        self.send('PreCompact')  # Consume the recognized turn context first.
        record = json.dumps({'type': 'response_item', 'payload': {
            'type': 'message', 'role': 'assistant', 'phase': 'final_answer',
            'content': [{'type': 'output_text', 'text': 'final'}]}}).encode() + b'\n'
        split = len(record) // 2
        with self.transcript.open('ab') as stream:
            stream.write(record[:split])
        self.send('Stop', last_assistant_message='final')
        status = self.capture.status()['threads'][0]
        self.assertEqual(status['capture_status'], 'partial',
                         'a pending transcript tail must remain visibly incomplete')
        self.assertLess(status['transcript_offset'], self.transcript.stat().st_size)
        # Temporary buffering is not a permanent collection gap.
        with self.transcript.open('ab') as stream:
            stream.write(record[split:])
        self.capture = fixtures.CodexCapture(self.root)
        self.send('SessionEnd')
        status = self.capture.status()['threads'][0]
        self.assertEqual(status['capture_status'], 'hooks_and_transcript_best_effort')
        self.assertEqual(status['gap_count'], 0)
        self.assertEqual(status['transcript_offset'], self.transcript.stat().st_size)
        self.assertEqual(len(self.typed('model.responded')), 1)

    def test_rejected_hook_is_visible_in_status_after_cli_returns_success(self):
        self.prompt()
        self.response('final')
        self.send('Stop', last_assistant_message='final')
        before = self.capture.status()['threads'][0]['gap_count']
        # A malformed invocation must preserve fail-open authoring, but its loss
        # must be visible when the warning tells the researcher to check status.
        result = self.cli('codex-hook', dict(session_id='thread1', cwd=str(self.root),
                          hook_event_name='UserPromptSubmit', prompt='lost', turn_id=None))
        self.assertEqual(json.loads(result.stdout), {})
        self.assertIn('not collected', result.stderr)
        status = self.capture.status()['threads'][0]
        self.assertGreater(status['gap_count'], before,
                           'capture-status must expose a dropped hook delivery')
        self.assertEqual(status['capture_status'], 'partial')
        reopened = fixtures.CodexCapture(self.root)
        failure = reopened.status()['failures'][0]
        self.assertEqual(failure['thread_id'], 'thread1')
        self.assertEqual(failure['error_type'], 'ValueError')
        self.assertEqual(self.typed('capture.gap')[-1]['payload']['code'], 'hook_delivery_rejected')
        self.assertNotIn('lost', json.dumps(self.events()) + json.dumps(reopened.status()))

    def test_unidentifiable_failure_is_reported_without_inventing_a_session(self):
        before = len(self.capture.status()['threads'])
        result = self.cli('codex-hook', {'secret': 'DO NOT RETAIN'})
        self.assertEqual(json.loads(result.stdout), {})
        status = fixtures.CodexCapture(self.root).status()
        self.assertEqual(len(status['threads']), before)
        self.assertEqual(status['unassigned_failure_count'], 1)
        self.assertIsNone(status['failures'][0]['thread_id'])
        self.assertIsNone(status['failures'][0]['hook'])
        self.assertNotIn('DO NOT RETAIN', json.dumps(status) + json.dumps(self.events()))

    def test_cross_project_failure_does_not_mark_an_existing_thread_partial(self):
        self.prompt()
        self.response('final')
        self.send('Stop', last_assistant_message='final')
        self.cli('codex-hook', dict(session_id='thread1', cwd=str(self.root.parent),
                 hook_event_name='UserPromptSubmit', prompt='OUTSIDE SECRET', turn_id='turn2'))
        status = self.capture.status()
        self.assertEqual(status['threads'][0]['gap_count'], 0)
        self.assertEqual(status['unassigned_failure_count'], 1)
        self.assertNotIn('OUTSIDE SECRET', json.dumps(status) + json.dumps(self.events()))

    def test_paused_capture_does_not_collect_failure_diagnostics(self):
        self.log.configure(False)
        self.cli('codex-hook', {'secret': 'PAUSED SECRET'})
        self.assertEqual(self.capture.status()['failures'], [])
        self.assertFalse(self.typed('capture.gap'))

    def test_failure_diagnostic_write_error_preserves_fail_open(self):
        import contextlib
        import io
        from unittest.mock import patch
        from manim_studio import research_cli
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', ['studio-research', '--root', str(self.root), 'codex-hook']), \
                patch.object(sys, 'stdin', io.StringIO('{bad json')), \
                patch.object(fixtures.CodexCapture, 'record_failure', side_effect=OSError('PRIVATE ERROR')), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            research_cli.main()
        self.assertEqual(json.loads(stdout.getvalue()), {})
        self.assertIn('could not be persisted', stderr.getvalue())
        self.assertIn('not collected', stderr.getvalue())
        self.assertNotIn('PRIVATE ERROR', stderr.getvalue())


# Avoid collecting the inherited baseline tests a second time.
for _name in fixtures.CaptureTests.__dict__:
    if _name.startswith('test_'):
        setattr(CaptureAcceptanceTests, _name, None)
