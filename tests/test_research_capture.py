from __future__ import annotations

import base64
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from manim_studio.research import ResearchLog
from manim_studio.research_capture import CodexCapture, connect, hook_config


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.log = ResearchLog(self.root)
        self.log.configure(True)
        self.capture = CodexCapture(self.root)
        self.transcript = self.root / 'rollout.jsonl'
        self.append('session_meta', {'id': 'thread1', 'cwd': str(self.root),
                    'cli_version': 'fixture-v1', 'source': 'vscode', 'model_provider': 'openai',
                    'api_key': 'DO NOT COPY'})
        self.send('SessionStart', source='startup')

    def append(self, kind, payload):
        with self.transcript.open('a', encoding='utf-8') as output:
            output.write(json.dumps({'timestamp': '2026-10-30T12:00:00Z',
                                     'type': kind, 'payload': payload}, ensure_ascii=False) + '\n')

    def send(self, name, **extra):
        delivery = extra.pop('delivery_id', None)
        return self.capture.handle(dict(dict(session_id='thread1', cwd=str(self.root),
                 transcript_path=str(self.transcript), turn_id='turn1', hook_event_name=name), **extra),
                 delivery_id=delivery)

    def prompt(self, text='תסביר את הרעיון', turn='turn1'):
        self.send('UserPromptSubmit', prompt=text, turn_id=turn, model='test-model')
        self.append('turn_context', {'turn_id': turn, 'model': 'test-model', 'effort': 'medium',
                                     'credentials': 'DO NOT COPY'})

    def response(self, text='הסבר', phase='final_answer'):
        self.append('response_item', {'type': 'message', 'role': 'assistant', 'phase': phase,
                                     'content': [{'type': 'output_text', 'text': text}]})

    def events(self):
        with self.log.connection() as db:
            return [dict(r, payload=json.loads(r['payload'])) for r in db.execute('SELECT * FROM events ORDER BY seq')]

    def typed(self, kind):
        return [e for e in self.events() if e['type'] == kind]

    def test_planning_only_prompt_response_and_model_metadata(self):
        self.prompt()
        self.response()
        self.send('Stop', last_assistant_message='הסבר')
        prompt, response = self.typed('prompt.recorded')[0], self.typed('model.responded')[0]
        self.assertEqual(response['prompt_id'], prompt['id'])
        self.assertEqual(response['payload']['text'], 'הסבר')
        self.assertEqual(response['payload']['model']['provider'], 'openai')
        self.assertEqual(response['payload']['model']['client_version'], 'fixture-v1')
        self.assertIsNone(prompt['payload']['classification'])
        self.assertEqual(self.capture.status()['threads'][0]['capture_status'],
                         'hooks_and_transcript_best_effort')
        self.assertNotIn('DO NOT COPY', json.dumps(self.events()))

    def test_intermediate_messages_and_duplicate_transcript_event_stream(self):
        self.prompt()
        self.response('בודק', 'commentary')
        self.append('event_msg', {'type': 'agent_message', 'message': 'בודק'})
        self.response('סיימתי')
        self.send('Stop', last_assistant_message='סיימתי')
        self.send('Stop', last_assistant_message='סיימתי')
        self.assertEqual([e['payload']['text'] for e in self.typed('model.responded')], ['בודק', 'סיימתי'])

    def test_repeated_identical_prompts_are_distinct_and_delivery_retry_is_not(self):
        self.send('UserPromptSubmit', prompt='again', delivery_id='delivery1')
        self.send('UserPromptSubmit', prompt='again', delivery_id='delivery1')
        self.send('UserPromptSubmit', prompt='again', delivery_id='delivery2')
        self.assertEqual(len(self.typed('prompt.recorded')), 2)

    def test_tool_links_preserve_original_prompt_when_user_steers(self):
        self.prompt('first')
        self.send('PreToolUse', tool_name='mcp__manim__render_scene', tool_use_id='call1',
                  tool_input={'target': 'demo'})
        first = self.typed('prompt.recorded')[0]['id']
        self.send('UserPromptSubmit', prompt='steering')
        self.send('PostToolUse', tool_name='mcp__manim__render_scene', tool_use_id='call1',
                  tool_response={'ok': False, 'error': 'render failed'})
        self.send('PostToolUse', tool_name='mcp__manim__render_scene', tool_use_id='call1',
                  tool_response={'ok': False})
        start, finish = self.typed('action.started')[0], self.typed('action.finished')[0]
        self.assertEqual(finish['parent_id'], start['id'])
        self.assertEqual(finish['prompt_id'], first)
        self.assertEqual(finish['payload']['related_prompt_ids'], [first])
        self.assertFalse(finish['payload']['result']['ok'])
        self.assertEqual(len(self.typed('action.finished')), 1)

    def test_multiple_prompts_in_turn_do_not_get_fabricated_causal_link(self):
        self.prompt('first')
        self.send('UserPromptSubmit', prompt='second')
        self.response('combined response')
        self.send('Stop', last_assistant_message='combined response')
        response = self.typed('model.responded')[0]
        self.assertIsNone(response['prompt_id'])
        self.assertEqual(len(response['payload']['related_prompt_ids']), 2)

    def test_unmatched_tool_finish_is_explicit_gap(self):
        self.prompt()
        self.send('PostToolUse', tool_name='Bash', tool_use_id='lost', tool_response='done')
        self.assertIsNone(self.typed('action.finished')[0]['parent_id'])
        self.assertIn('tool_finish_without_start', [e['payload']['code'] for e in self.typed('capture.gap')])

    def test_snapshots_before_and_after_tool(self):
        decks = self.root / 'decks'
        decks.mkdir()
        source = decks / 'demo.py'
        source.write_text('before')
        self.prompt()
        self.send('PreToolUse', tool_name='apply_patch', tool_use_id='edit', tool_input={})
        source.write_text('after')
        self.send('PostToolUse', tool_name='apply_patch', tool_use_id='edit', tool_response='ok')
        before = self.typed('action.started')[0]['payload']['state']['files']['decks/demo.py']
        after = self.typed('action.finished')[0]['payload']['state']['files']['decks/demo.py']
        self.assertNotEqual(before, after)

    def test_partial_utf8_line_waits_for_complete_record(self):
        self.prompt()
        line = json.dumps({'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant',
                 'content': [{'type': 'output_text', 'text': 'שלום'}]}}, ensure_ascii=False).encode('utf-8')
        split = line.index('שלום'.encode('utf-8')) + 1
        with self.transcript.open('ab') as output:
            output.write(line[:split])
        self.send('PreCompact')
        self.assertFalse(self.typed('model.responded'))
        with self.transcript.open('ab') as output:
            output.write(line[split:] + b'\n')
        self.send('PostCompact')
        self.assertEqual(self.typed('model.responded')[0]['payload']['text'], 'שלום')

    def test_pause_does_not_backfill_and_session_survives_restart(self):
        self.prompt()
        session = self.capture.status()['threads'][0]['session_id']
        self.log.configure(False)
        self.response('PRIVATE WHILE PAUSED')
        self.send('Stop', last_assistant_message='PRIVATE WHILE PAUSED')
        self.log.configure(True)
        self.capture = CodexCapture(self.root)
        self.send('UserPromptSubmit', prompt='new', turn_id='turn2')
        self.assertEqual(self.capture.status()['threads'][0]['session_id'], session)
        self.assertNotIn('PRIVATE WHILE PAUSED', json.dumps(self.events()))
        self.assertIn('collection_paused', [e['payload']['code'] for e in self.typed('capture.gap')])

    def test_two_threads_do_not_mix_sessions_or_tool_ids(self):
        self.prompt('first')
        self.send('PreToolUse', tool_name='Bash', tool_use_id='shared', tool_input={})
        other = CodexCapture(self.root)
        def send(name, **kwargs):
            return other.handle(dict(session_id='thread2', cwd=str(self.root), turn_id='turn1',
                                     hook_event_name=name, **kwargs))
        send('SessionStart', source='startup')
        send('UserPromptSubmit', prompt='second')
        send('PreToolUse', tool_name='Bash', tool_use_id='shared', tool_input={})
        send('PostToolUse', tool_name='Bash', tool_use_id='shared', tool_response='ok')
        self.send('PostToolUse', tool_name='Bash', tool_use_id='shared', tool_response='ok')
        for event in self.typed('action.finished'):
            start = next(e for e in self.typed('action.started') if e['id'] == event['parent_id'])
            self.assertEqual(start['session_id'], event['session_id'])
            self.assertEqual(start['prompt_id'], event['prompt_id'])
        self.assertEqual(len({e['session_id'] for e in self.typed('prompt.recorded')}), 2)

    def test_no_transcript_still_records_hook_prompt_final_and_gap(self):
        self.prompt()
        self.send('Stop', transcript_path=None, last_assistant_message='final')
        self.assertEqual(self.typed('model.responded')[0]['payload']['text'], 'final')
        self.assertEqual(self.capture.status()['threads'][0]['capture_status'], 'partial')

    def test_late_transcript_final_does_not_duplicate_stop_fallback(self):
        self.prompt()
        self.send('Stop', last_assistant_message='final')
        self.response('final')
        self.send('SessionEnd')
        self.assertEqual(len(self.typed('model.responded')), 1)

    def test_unknown_transcript_format_and_malformed_json_are_visible(self):
        self.prompt()
        self.append('new_format', {'secret': 'DO NOT COPY'})
        with self.transcript.open('ab') as output:
            output.write(b'not json\n')
        self.response()
        self.send('Stop', last_assistant_message='הסבר')
        self.assertEqual(len(self.typed('model.responded')), 1)
        self.assertEqual(self.capture.status()['threads'][0]['capture_status'], 'partial')
        self.assertNotIn('DO NOT COPY', json.dumps(self.events()))

    def test_transcript_replacement_is_detected_without_reimporting_history(self):
        self.prompt()
        self.response('first')
        self.send('Stop', last_assistant_message='first')
        content = self.transcript.read_text()
        self.transcript.write_text(content.replace('first', 'WRONG'))
        self.send('PreCompact')
        self.assertNotIn('WRONG', json.dumps(self.events()))
        self.assertEqual(self.capture.status()['threads'][0]['capture_status'], 'partial')

    def test_rejects_cross_project_and_cross_thread_transcript(self):
        with self.assertRaises(ValueError):
            self.send('UserPromptSubmit', cwd=str(self.root.parent), prompt='secret')
        self.transcript.write_text(json.dumps({'type': 'session_meta', 'payload': {
            'id': 'other', 'cwd': str(self.root)}}) + '\n')
        self.send('Stop', last_assistant_message='safe')
        self.assertIn('transcript_identity_mismatch', [e['payload']['code'] for e in self.typed('capture.gap')])

    def test_failed_transaction_rolls_back_cursor_and_messages_for_retry(self):
        self.prompt()
        self.response()
        original = ResearchLog._event
        def fail(log, db, kind, *args, **kwargs):
            if kind == 'client.turn.completed':
                raise sqlite3.OperationalError('disk full')
            return original(log, db, kind, *args, **kwargs)
        with patch.object(ResearchLog, '_event', fail):
            with self.assertRaises(sqlite3.OperationalError):
                self.send('Stop', last_assistant_message='הסבר', delivery_id='retry')
        self.assertFalse(self.typed('model.responded'))
        self.send('Stop', last_assistant_message='הסבר', delivery_id='retry')
        self.assertEqual(len(self.typed('model.responded')), 1)

    def test_concurrent_writers_and_restart_keep_one_transcript_message(self):
        self.prompt()
        self.response()
        payload = dict(session_id='thread1', cwd=str(self.root), transcript_path=str(self.transcript),
                       turn_id='turn1', hook_event_name='Stop', last_assistant_message='הסבר')
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda _: CodexCapture(self.root).handle(payload, delivery_id='same'), range(8)))
        self.assertEqual(len(self.typed('model.responded')), 1)

    def test_disabled_does_not_create_storage_or_read_transcript(self):
        other_root = self.root / 'disabled'
        other_root.mkdir()
        capture = CodexCapture(other_root)
        with patch.object(Path, 'open', side_effect=AssertionError('must not read')):
            result = capture.handle(dict(session_id='x', cwd=str(other_root),
                hook_event_name='Stop', turn_id='t', transcript_path=str(self.transcript)))
        self.assertFalse(result['recorded'])
        self.assertFalse(capture.log.directory.exists())

    def test_metadata_export_redacts_content_but_preserves_links(self):
        self.prompt('SECRET PROMPT')
        self.response('SECRET RESPONSE')
        self.send('Stop', last_assistant_message='SECRET RESPONSE')
        destination = self.root / 'metadata.jsonl'
        self.log.export(destination)
        text = destination.read_text()
        self.assertNotIn('SECRET', text)
        self.assertNotIn('medium', text)  # run settings remain content-only
        self.assertIn('thread1', text)
        full = self.root / 'full.jsonl'
        self.log.export(full, True)
        self.assertIn('SECRET RESPONSE', full.read_text())

    def test_attachment_starts_at_current_end_without_importing_old_chat(self):
        self.prompt()
        self.response('OLD PRIVATE')
        # A different research ledger first observes a resume of this thread.
        with self.log.connection() as db:
            db.execute('DELETE FROM capture_threads')
            db.execute('DELETE FROM capture_receipts')
        self.send('SessionStart', source='resume')
        self.assertNotIn('OLD PRIVATE', json.dumps(self.events()))
        self.assertIn('attached_mid_conversation', [e['payload']['code'] for e in self.typed('capture.gap')])

    def test_connect_merges_and_is_idempotent_without_overriding_other_hooks(self):
        folder = self.root / '.codex'
        folder.mkdir()
        existing = {'description': 'keep', 'hooks': {'Stop': [
            {'hooks': [{'type': 'command', 'command': 'keep-existing'}]}]}}
        destination = folder / 'hooks.json'
        destination.write_text(json.dumps(existing))
        connect(self.root)
        first = destination.read_text()
        connect(self.root)
        self.assertEqual(first, destination.read_text())
        result = json.loads(first)
        self.assertEqual(result['description'], 'keep')
        self.assertEqual(result['hooks']['Stop'][0]['hooks'][0]['command'], 'keep-existing')
        self.assertNotIn('dangerously', first)
        self.assertTrue(self.log.enabled)

    def test_hook_command_uses_safe_posix_and_windows_quoting(self):
        config = hook_config(self.root / 'space Hebrew עברית', python='C:\\Program Files\\Python\\python.exe')
        for groups in config['hooks'].values():
            handler = groups[0]['hooks'][0]
            self.assertIn('commandWindows', handler)
            self.assertNotIn('async', handler)
            self.assertEqual(handler['timeout'], 3)
        encoded = config['hooks']['Stop'][0]['hooks'][0]['commandWindows'].split()[-1]
        self.assertIn("'C:\\Program Files\\Python\\python.exe'", base64.b64decode(encoded).decode('utf-16le'))

    def test_cli_is_passive_and_fail_open_with_valid_hook_json(self):
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
        result = subprocess.run([sys.executable, '-m', 'manim_studio.research_cli',
            '--root', str(self.root), 'codex-hook'], input='{not json', text=True,
            capture_output=True, env=env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {})
        self.assertIn('not collected', result.stderr)
        self.assertNotIn('{not json', result.stderr)

    def test_additive_upgrade_keeps_existing_events(self):
        old = self.log.start_session('legacy')
        prompt = self.log.record_prompt(old, 'keep')
        self.prompt()
        self.assertIn(prompt, [e['id'] for e in self.events()])

    def test_pause_reset_cannot_assign_response_to_previous_turn(self):
        self.prompt('old', turn='turn1')
        self.send('PreCompact')
        self.log.configure(False)
        self.log.configure(True)
        self.append('turn_context', {'turn_id': 'turn2', 'model': 'new-model'})
        self.send('UserPromptSubmit', prompt='new', turn_id='turn2')
        self.response('new response')
        self.send('Stop', turn_id='turn2', last_assistant_message='new response')
        response = self.typed('model.responded')[0]
        self.assertEqual(response['prompt_id'], self.typed('prompt.recorded')[-1]['id'])
        self.assertEqual(response['payload']['source']['turn_id'], 'turn2')

    def test_large_record_is_skipped_and_later_messages_are_not_stuck(self):
        self.prompt()
        with patch('manim_studio.research_capture.MAX_LINE', 512):
            self.append('response_item', {'type': 'reasoning', 'text': 'x' * 3000})
            self.response('small')
            self.send('Stop', last_assistant_message='small')
        self.assertEqual(self.typed('model.responded')[0]['payload']['text'], 'small')
        self.assertIn('transcript_record_too_large', [e['payload']['code'] for e in self.typed('capture.gap')])

    def test_invalid_header_does_not_lose_hook_prompt(self):
        self.transcript.write_text('[]\n')
        self.send('UserPromptSubmit', prompt='still collected')
        self.assertEqual(self.typed('prompt.recorded')[0]['payload']['text'], 'still collected')

    def test_two_identical_final_messages_after_stop_are_not_text_deduplicated(self):
        self.prompt()
        self.send('Stop', last_assistant_message='same')
        self.response('same')
        self.response('same')
        self.send('SessionEnd')
        self.assertEqual(len(self.typed('model.responded')), 2)

    def test_commentary_with_same_text_as_final_is_not_suppressed(self):
        self.prompt()
        self.response('same', 'commentary')
        self.send('Stop', last_assistant_message='same')
        self.assertEqual(len(self.typed('model.responded')), 2)

    @unittest.skipIf(os.name == 'nt', 'POSIX shell command; Windows encoding tested separately')
    def test_generated_hook_runs_real_cli_from_path_with_shell_characters(self):
        root = self.root / "עברית spaces &$'project"
        root.mkdir()
        connect(root)
        command = hook_config(root)['hooks']['Stop'][0]['hooks'][0]['command']
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
        for name, extra in [('SessionStart', {'source': 'startup'}),
                            ('UserPromptSubmit', {'prompt': 'Explain only'}),
                            ('Stop', {'last_assistant_message': 'Planning answer'})]:
            result = subprocess.run(command, shell=True, text=True, input=json.dumps(dict(
                cwd=str(root), session_id='cli-thread', turn_id='cli-turn', hook_event_name=name, **extra)),
                env=env, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {})
            self.assertFalse(result.stderr)
        log = ResearchLog(root)
        with log.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE type='prompt.recorded'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE type='model.responded'").fetchone()[0], 1)

    def test_malformed_existing_hook_config_is_not_overwritten(self):
        folder = self.root / '.codex'
        folder.mkdir()
        destination = folder / 'hooks.json'
        destination.write_text('{broken')
        with self.assertRaises(ValueError):
            connect(self.root)
        self.assertEqual(destination.read_text(), '{broken')

    def test_tool_identity_mismatch_does_not_create_wrong_parent_link(self):
        self.prompt()
        self.send('PreToolUse', tool_name='Bash', tool_use_id='call', tool_input={})
        self.send('PostToolUse', tool_name='different', tool_use_id='call', tool_response='wrong')
        self.assertFalse(self.typed('action.finished'))
        self.assertIn('tool_identity_mismatch', [e['payload']['code'] for e in self.typed('capture.gap')])

    def test_internal_reasoning_and_unknown_channels_are_never_collected(self):
        self.prompt()
        self.append('response_item', {'type': 'reasoning', 'summary': ['PRIVATE REASONING']})
        self.append('response_item', {'type': 'message', 'role': 'assistant', 'channel': 'analysis',
                    'content': [{'type': 'output_text', 'text': 'PRIVATE REASONING'}]})
        self.response('visible')
        self.send('Stop', last_assistant_message='visible')
        self.assertNotIn('PRIVATE REASONING', json.dumps(self.events()))

    def test_same_capture_instance_serializes_concurrent_deliveries(self):
        def submit(index):
            return self.capture.handle(dict(cwd=str(self.root), session_id=f'parallel-{index}',
                turn_id='turn1', hook_event_name='UserPromptSubmit', prompt=f'prompt-{index}'))
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(submit, range(8)))
        prompts = self.typed('prompt.recorded')
        self.assertEqual(len({p['session_id'] for p in prompts}), 8)
        for prompt in prompts:
            suffix = prompt['payload']['source']['thread_id'].split('-')[-1]
            self.assertEqual(prompt['payload']['text'], 'prompt-' + suffix)


if __name__ == '__main__':
    unittest.main()
