from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from manim_studio.research import ResearchLog
from manim_studio.research_cli import dispatch
from manim_mcp import services
from tests.test_manim_mcp_services import McpFixture


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.log = ResearchLog(self.root)
        self.log.configure(True)
        self.session = self.log.start_session('test', {'provider': 'test', 'model': 'fake-v1'})
        self.prompt = self.log.record_prompt(self.session, 'הוסף דוגמה', stage='storyboard')

    def annotate(self, session_id, prompt_id, *args, **kwargs):
        from manim_studio.prompt_classifications import PromptClassifications
        state = PromptClassifications(self.root).dispatch('get', {'session_id': session_id, 'prompt_id': prompt_id})
        return self.log.classify(session_id, prompt_id, *args, **kwargs,
                                request_id=str(uuid.uuid4()), expected_human_head=state['human_head_event_id'])

    def events(self):
        with self.log.connection() as db:
            return [dict(r, payload=json.loads(r['payload'])) for r in db.execute('SELECT * FROM events ORDER BY seq')]

    def test_disabled_is_noop_and_does_not_create_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            log = ResearchLog(Path(directory))
            self.assertFalse(log.enabled)
            self.assertFalse(log.directory.exists())
            self.assertEqual(dispatch(Path(directory), 'status', {}), {'enabled': False})
            self.assertFalse(log.directory.exists())

    def test_missing_classification_stays_missing_and_sources_remain_separate(self):
        self.assertIsNone(self.events()[-1]['payload']['classification'])
        self.annotate(self.session, self.prompt, 'corrective', ['add_content'], source='model')
        self.annotate(self.session, self.prompt, 'continuation', [], source='human', human_seconds=3)
        self.annotate(self.session, self.prompt, None, None)
        events = self.events()
        self.assertEqual([e['type'] for e in events[-3:]],
                         ['classification.suggested', 'classification.confirmed', 'classification.cleared'])
        self.assertEqual(events[-2]['payload']['prompt_type'], 'continuation')
        self.assertIsNone(events[-1]['payload']['prompt_type'])
        self.assertIsNone(events[-1]['payload']['reasons'])

    def test_reference_validation_prevents_cross_session_links(self):
        other_session = self.log.start_session()
        for call in (
            lambda: self.log.record_response(other_session, self.prompt, 'wrong'),
            lambda: self.annotate('unknown', self.prompt),
            lambda: self.log.record_response(self.session, None, 'wrong'),
            lambda: self.annotate(self.session, None),
            lambda: self.log.begin_action(other_session, 'render', {}, self.prompt),
        ):
            with self.assertRaises(ValueError):
                call()

    def test_invalid_enums_and_human_time(self):
        for kwargs in ({'prompt_type': 'bad'}, {'reasons': ['bad']}, {'human_seconds': -1},
                       {'human_seconds': float('nan')}, {'human_seconds': True},
                       {'source': 'model', 'human_seconds': 1}, {'other': 'free text'}):
            with self.assertRaises(ValueError):
                self.annotate(self.session, self.prompt, **kwargs)

    def test_reconstructs_before_after_content_and_deletions_from_export(self):
        source = self.root / 'decks' / 'scene.py'
        source.parent.mkdir()
        source.write_text('before', encoding='utf-8')
        action = self.log.begin_action(self.session, 'edit', {}, self.prompt)
        source.write_text('after', encoding='utf-8')
        self.log.end_action(self.session, action, {'ok': True}, 0.1, self.prompt)
        source.unlink()
        second = self.log.begin_action(self.session, 'deleted', {}, self.prompt)
        full = self.root / 'full.jsonl'
        self.log.export(full, True)
        records = [json.loads(line) for line in full.read_text().splitlines()]
        blobs = {r['sha256']: base64.b64decode(r['base64']) for r in records if r['type'] == 'source.blob'}
        events = [r for r in records if 'seq' in r]
        before, after = events[-3:-1]
        self.assertEqual(after['parent_id'], action)
        self.assertEqual(before['prompt_id'], self.prompt)
        self.assertEqual(blobs[before['payload']['state']['files']['decks/scene.py']], b'before')
        self.assertEqual(blobs[after['payload']['state']['files']['decks/scene.py']], b'after')
        self.assertNotIn('decks/scene.py', events[-1]['payload']['state']['files'])
        self.assertEqual(events[-1]['id'], second)
        self.assertTrue(all(e['project_id'] for e in events))

    def test_metadata_export_excludes_sensitive_payload_and_cannot_overwrite(self):
        self.log.record_response(self.session, self.prompt, 'secret response')
        self.annotate(self.session, self.prompt, 'corrective', ['other'], other='secret note')
        path = self.root / 'metadata.jsonl'
        self.log.export(path)
        content = path.read_text()
        self.assertNotIn('secret', content)
        self.assertNotIn('הוסף', content)
        self.assertNotIn('test', content)
        with self.assertRaises(FileExistsError):
            self.log.export(path)
        with self.assertRaises(ValueError):
            self.log.export(self.log.database)

    def test_snapshot_omissions_and_symlinks(self):
        decks = self.root / 'decks'
        decks.mkdir()
        (decks / 'large.py').write_bytes(b'x' * 1_000_001)
        (self.root / 'private.txt').write_text('private')
        (decks / 'link.py').symlink_to(self.root / 'private.txt')
        action = self.log.begin_action(self.session, 'test', {})
        state = self.events()[-1]['payload']['state']
        self.assertEqual(set(state['omitted']), {'decks/large.py', 'decks/link.py'})
        self.assertEqual(state['files'], {})

    def test_concurrent_prompts_are_unique_ordered_and_durable(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            ids = list(executor.map(lambda i: self.log.record_prompt(self.session, str(i)), range(20)))
        self.assertEqual(len(set(ids)), 20)
        reopened = ResearchLog(self.root)
        self.assertTrue(reopened.enabled)
        sequences = [e['seq'] for e in self.events()]
        self.assertEqual(sequences, sorted(set(sequences)))

    def test_pause_prevents_collection(self):
        self.log.configure(False)
        with self.assertRaises(ValueError):
            self.log.record_prompt(self.session, 'not recorded')
        self.assertIsNone(self.log.end_action(self.session, 'unknown', {}, 1))
        self.log.configure(True)
        self.log.record_prompt(self.session, 'resumed')

    def test_service_logging_failure_does_not_change_result(self):
        with McpFixture() as fixture:
            log = ResearchLog(fixture.root)
            log.configure(True)
            session = log.start_session()
            ctx = replace(fixture.context(), research_session_id=session)
            expected = services.list_decks(fixture.context())
            with patch.object(ResearchLog, 'begin_action', side_effect=OSError('disk full')):
                with self.assertWarns(RuntimeWarning):
                    actual = services.list_decks(ctx)
            self.assertEqual(actual, expected)

    def test_mcp_bridge_and_request_scoped_action_links(self):
        from manim_mcp.server import create_server
        with McpFixture() as fixture:
            log = ResearchLog(fixture.root)
            log.configure(True)
            session = log.start_session()
            prompt = log.record_prompt(session, 'render')
            server = create_server(fixture.context())
            async def run():
                result = await server.call_tool('list_decks', {'research_session_id': session, 'research_prompt_id': prompt})
                await server.call_tool('list_decks', {})
                return result
            asyncio.run(run())
            with log.connection() as db:
                actions = list(db.execute("SELECT * FROM events WHERE type LIKE 'action.%'"))
            self.assertEqual(len(actions), 2)
            self.assertTrue(all(r['prompt_id'] == prompt for r in actions))

    def test_rpc_reserved_metadata_does_not_change_authoring_api(self):
        from manim_studio.authoring_sessions import AuthoringSessionController
        controller = AuthoringSessionController(self.root, check_executables=False)
        result = controller.dispatch('list_sessions', {'_research': {'session_id': self.session, 'prompt_id': self.prompt}})
        self.assertIsInstance(result, dict)
        self.assertEqual([event for event in self.events() if event['type']=='action.started'][-1]['payload']['name'], 'authoring.list_sessions')
        self.assertEqual(self.events()[-1]['prompt_id'], self.prompt)

    def test_action_exception_is_logged_and_preserved(self):
        from manim_studio.research import instrument
        from types import SimpleNamespace
        @instrument
        def fail(context=None):
            raise RuntimeError('original')
        ctx = SimpleNamespace(repo_root=self.root, research_session_id=self.session, research_prompt_id=self.prompt)
        with self.assertRaisesRegex(RuntimeError, 'original'):
            fail(ctx)
        self.assertEqual(self.events()[-1]['payload']['error']['type'], 'RuntimeError')

    def test_privacy_options_require_json_booleans(self):
        with self.assertRaises(ValueError):
            self.log.configure("false")
        with self.assertRaises(ValueError):
            self.log.export(self.root / 'bad.jsonl', "false")
        with self.assertRaises(ValueError):
            self.log.record_prompt(self.session, 123)

    def test_stage_is_inherited_and_render_stage_is_explicit(self):
        self.log.record_response(self.session, self.prompt, 'answer')
        self.assertEqual(self.events()[-1]['stage'], 'storyboard')
        action = self.log.begin_action(self.session, 'render_scene', {}, self.prompt)
        self.log.end_action(self.session, action, {'ok': False}, 0.2, self.prompt)
        self.assertEqual([e['stage'] for e in self.events()[-2:]], ['render', 'render'])

    def test_action_finish_must_match_its_start_prompt(self):
        action = self.log.begin_action(self.session, 'edit', {}, self.prompt)
        other = self.log.record_prompt(self.session, 'another prompt')
        with self.assertRaises(ValueError):
            self.log.end_action(self.session, action, {}, 0.1, other)

    def test_connection_releases_database_handle_after_transaction(self):
        with self.log.connection() as db:
            db.execute("SELECT 1").fetchone()
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute("SELECT 1")
