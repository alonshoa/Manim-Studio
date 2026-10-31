import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from manim_studio.research import ResearchLog
from manim_studio.research_sessions import ResearchSessions, ResearchSessionError
from manim_studio.prompt_classifications import PromptClassifications, annotation_state


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.log = ResearchLog(self.root); self.log.configure(True)
        self.session = self.log.start_session('Vectors')
        self.prompt = self.log.record_prompt(self.session, 'הדוגמה לא מסבירה למה צריך נרמול')
        self.service = PromptClassifications(self.root)

    def read(self, action='get', **kwargs):
        return self.service.dispatch(action, dict(session_id=self.session, **({} if action == 'list' else {'prompt_id': self.prompt}), **kwargs))

    def write(self, action='save', **kwargs):
        current = self.read()
        payload = dict(project_id=current['project_id'], session_id=self.session, prompt_id=self.prompt,
            expected_human_head=current['human_head_event_id'], request_id=str(uuid.uuid4()))
        if action in ('save','suggest'):
            payload.update(prompt_type='corrective', reasons=['unclear_explanation'])
        payload.update(kwargs)
        return self.service.dispatch(action, payload)

    def test_versioned_save_correction_clear_and_skip_have_distinct_meanings(self):
        self.assertIsNone(self.read()['human_head_event_id'])
        first = self.write(prompt_type='irrelevant', reasons=None)
        self.assertEqual(first['review_status'], 'confirmed')
        second = self.write(prompt_type='continuation', reasons=[])
        self.assertEqual(second['current']['payload']['reasons'], [])
        self.write('clear')
        skipped = self.write('skip')
        self.assertEqual(skipped['review_status'], 'deferred')
        self.assertIsNone(skipped['current'])
        self.assertEqual([e['type'] for e in self.read('history')['history']],
            ['classification.confirmed','classification.confirmed','classification.cleared','classification.skipped'])
        counts = self.read('list')['counts']
        self.assertEqual((counts['total'], counts['confirmed'], counts['missing'], counts['deferred']), (1,0,1,1))

    def test_suggestion_never_becomes_human_without_explicit_action(self):
        suggestion = self.write('suggest', classifier={'name':'fixture', 'version':'1'})
        self.assertIsNone(suggestion['human_head_event_id'])
        self.assertIsNone(suggestion['current'])
        approved = self.write(suggestion_id=suggestion['event_id'])
        self.assertEqual(approved['current']['actor'], 'human')
        self.assertEqual(approved['current']['payload']['suggestion_id'], suggestion['event_id'])
        head = approved['human_head_event_id']
        latest = self.write('suggest', prompt_type='continuation', reasons=None)
        self.assertEqual(latest['human_head_event_id'], head)
        self.assertEqual(latest['current']['payload']['prompt_type'], 'corrective')

    def test_two_windows_get_one_success_and_one_conflict(self):
        state = self.read()
        def save(value):
            try:
                return self.service.dispatch('save', dict(project_id=state['project_id'], session_id=self.session,
                    prompt_id=self.prompt, expected_human_head=None, request_id=str(uuid.uuid4()), prompt_type=value))['event_id']
            except ResearchSessionError as exc:
                return exc.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, ['initial','corrective']))
        self.assertEqual(results.count('classification_conflict'), 1)
        self.assertEqual(len(self.read('history')['history']), 1)

    def test_retry_of_committed_request_does_not_append_or_require_current_head(self):
        state = self.read()
        payload = dict(project_id=state['project_id'], session_id=self.session, prompt_id=self.prompt,
                       expected_human_head=None, request_id='stable', prompt_type='initial')
        saved = self.service.dispatch('save', payload)
        self.write(prompt_type='continuation')
        replay = PromptClassifications(self.root).dispatch('save', dict(reversed(list(payload.items()))))
        self.assertEqual(replay, saved)
        self.assertEqual(len(self.read('history')['history']), 2)
        with self.assertRaisesRegex(ValueError, 'request_id_conflict'):
            self.service.dispatch('save', dict(payload, prompt_type='corrective'))

    def test_reasons_null_empty_other_and_unsupported_taxonomy_are_validated(self):
        self.assertIsNone(self.write(reasons=None)['current']['payload']['reasons'])
        self.assertEqual(self.write(reasons=[])['current']['payload']['reasons'], [])
        self.assertEqual(self.write(reasons=['other'], other='הסבר נוסף')['current']['payload']['other'], 'הסבר נוסף')
        for data in ({'reasons':['other'],'other':''}, {'reasons':['unknown']}, {'reasons':'bad'},
                     {'prompt_type':['initial','corrective']}, {'other':'unselected'}, {'taxonomy_version':9}):
            with self.subTest(data=data), self.assertRaises(ValueError): self.write(**data)

    def test_skip_cannot_replace_existing_human_classification(self):
        saved = self.write()
        with self.assertRaisesRegex(ValueError, 'already_classified'): self.write('skip')
        self.assertEqual(self.read()['human_head_event_id'], saved['event_id'])

    def test_cross_project_and_cross_session_writes_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'project_mismatch'): self.write(project_id='other')
        other = self.log.start_session('Other')
        with self.assertRaisesRegex(ValueError, 'prompt_not_found'): self.write(session_id=other)
        with self.assertRaisesRegex(ValueError, 'prompt_not_found'): self.write(prompt_id='missing')
        self.assertFalse(self.read('history')['history'])

    def test_finished_paused_and_disabled_capture_can_be_annotated_without_enabling(self):
        manager = ResearchSessions(self.root)
        state = manager.dispatch('adopt_legacy', dict(session_id=self.session,title='Closed',topic='Math',request_id='adopt'))
        state = manager.dispatch('pause', dict(session_id=self.session,expected_revision=state['revision'],request_id='pause'))
        self.write()
        manager.dispatch('finish', dict(session_id=self.session,expected_revision=state['revision'],request_id='finish'))
        self.log.configure(False)
        result = self.write(prompt_type='continuation')
        self.assertEqual(result['session']['state'], 'finished')
        self.assertFalse(self.log.enabled)

    def test_legacy_null_confirmation_is_missing_not_a_skip(self):
        with self.log.connection() as db:
            self.log._event(db, 'classification.confirmed', self.session,
                            {'prompt_type':None, 'reasons':None}, actor='human', prompt_id=self.prompt)
        state = self.read()
        self.assertEqual(state['review_status'], 'unclassified')
        self.assertIsNotNone(state['human_head_event_id'])
        self.assertEqual(self.read('list')['counts']['deferred'], 0)

    def test_unknown_legacy_taxonomy_is_readable_but_not_human_validity(self):
        with self.log.connection() as db:
            self.log._event(db, 'classification.confirmed', self.session, {'prompt_type':'initial','taxonomy_version':9}, actor='human',prompt_id=self.prompt)
        self.assertIsNone(self.read()['current'])
        self.assertEqual(len(self.read('history')['history']), 1)

    def test_history_projection_matches_export_and_metadata_excludes_text(self):
        self.write(reasons=['other'],other='PRIVATE ANNOTATION')
        self.write('suggest', classifier={'name':'demo','version':'1','model':'demo-model'})
        self.write('clear'); self.write('skip')
        full, meta = self.root/'full.jsonl', self.root/'meta.jsonl'
        self.log.export(full,True); self.log.export(meta)
        events = [r for r in map(json.loads, full.read_text(encoding='utf-8').splitlines()) if r.get('prompt_id')==self.prompt and r['type'].startswith('classification.')]
        self.assertEqual(annotation_state(events)['human_head_event_id'], self.read()['human_head_event_id'])
        text = meta.read_text(encoding='utf-8')
        self.assertNotIn('PRIVATE ANNOTATION',text); self.assertNotIn('נרמול',text)
        self.assertIn('taxonomy_version', text)

    def test_snapshot_pagination_and_counts_are_consistent(self):
        for index in range(5): self.log.record_prompt(self.session, str(index))
        first = self.read('list', filter='all', limit=2)
        self.write()
        self.log.record_prompt(self.session, 'NEW')
        second = self.read('list', filter='all', limit=2, offset=2, snapshot_seq=first['snapshot_seq'])
        self.assertEqual(first['counts'], second['counts'])
        self.assertEqual(first['counts']['total'], 6)
        self.assertEqual(self.read('list',filter='all')['counts']['total'], 7)

    def test_old_human_bridge_cannot_bypass_revision_guard(self):
        with self.assertRaisesRegex(ValueError,'classification_revision_required'):
            self.log.classify(self.session,self.prompt,'initial')
        state = self.read()
        self.log.classify(self.session,self.prompt,'initial',request_id='bridge',expected_human_head=None)
        with self.assertRaisesRegex(ValueError,'classification_conflict'):
            self.write(expected_human_head=state['human_head_event_id'])

    def test_classifier_metadata_does_not_accept_arbitrary_settings(self):
        with self.assertRaises(ValueError): self.write('suggest',classifier={'api_key':'PRIVATE'})
        self.assertFalse(self.read('history')['history'])

    def test_write_fault_rolls_back_event_and_receipt(self):
        original = ResearchLog._event
        def fail(log, db, *args, **kwargs):
            original(log,db,*args,**kwargs)
            raise OSError('injected after insert')
        with patch.object(ResearchLog,'_event',fail), self.assertRaisesRegex(ValueError, 'storage is unavailable'): self.write(request_id='retry')
        self.assertFalse(self.read('history')['history'])
        self.write(request_id='retry')
        self.assertEqual(len(self.read('history')['history']),1)

    def test_dedicated_rpc_round_trip_and_non_annotation_methods_are_rejected(self):
        env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
        requests=[{'id':1,'method':'classification.list','params':{'session_id':self.session}},
                  {'id':2,'method':'render_scene','params':{}}, {'id':3,'method':'research.list','params':{}}]
        result=subprocess.run([sys.executable,'-X','utf8','-m','manim_studio.cli','research','rpc','--repo-root',str(self.root)],
            input='\n'.join(map(json.dumps,requests))+'\n',text=True,capture_output=True,env=env,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        responses=list(map(json.loads,result.stdout.splitlines()))
        self.assertTrue(responses[0]['ok']); self.assertFalse(responses[1]['ok']); self.assertTrue(responses[2]['ok'])

    def test_shared_context_is_marked_ambiguous_not_inferred(self):
        with self.log.connection() as db:
            self.log._event(db,'model.responded',self.session,{'text':'shared','related_prompt_ids':[self.prompt]},actor='model')
        self.assertEqual(self.read()['context'][0]['relation'],'shared')

    def test_busy_annotation_storage_fails_with_bounded_wait(self):
        import time
        with self.log.connection() as locked:
            locked.execute('BEGIN IMMEDIATE')
            started = time.monotonic()
            with self.assertRaisesRegex(ValueError, 'storage is unavailable'): self.write()
            self.assertLess(time.monotonic()-started, 3.0)

    def test_real_mcp_annotation_round_trip_and_old_writer_guard(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'),MANIM_STUDIO_REPO_ROOT=str(self.root))
        self.log.configure(False)
        async def run():
            params=StdioServerParameters(command=sys.executable,args=['-X','utf8','-m','manim_mcp.server'],env=env,cwd=str(self.root))
            async with stdio_client(params) as (reader,writer):
                async with ClientSession(reader,writer) as client:
                    await client.initialize()
                    async def call(action,payload):
                        response=await client.call_tool('research_log',{'action':action,'payload':payload})
                        self.assertFalse(response.isError)
                        return response.structuredContent or json.loads(response.content[0].text)
                    current=await call('classification.get',{'session_id':self.session,'prompt_id':self.prompt})
                    self.assertTrue(current['ok'])
                    old=await call('classify',{'session_id':self.session,'prompt_id':self.prompt,'prompt_type':'initial'})
                    self.assertFalse(old['ok'])
                    result=await call('classification.save',{'project_id':current['data']['project_id'],'session_id':self.session,'prompt_id':self.prompt,
                        'prompt_type':'corrective','reasons':[],'expected_human_head':None,'request_id':'mcp-save'})
                    self.assertTrue(result['ok'],result)
                    self.assertEqual(result['data']['current']['actor'],'human')
        asyncio.run(asyncio.wait_for(run(),timeout=20))

    def test_actual_crash_before_and_after_annotation_commit(self):
        env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
        current=self.read()
        payload=dict(project_id=current['project_id'],session_id=self.session,prompt_id=self.prompt,request_id='crash',expected_human_head=None,prompt_type='initial')
        script='''
import json,os,sys
from manim_studio.research import ResearchLog
from manim_studio.prompt_classifications import PromptClassifications
root,mode,payload=json.load(sys.stdin)
if mode=='before':
    original=ResearchLog._event
    def fail(self,*args,**kwargs):
        original(self,*args,**kwargs)
        os._exit(29)
    ResearchLog._event=fail
result=PromptClassifications(root).dispatch('save',payload)
print(json.dumps(result),flush=True)
os._exit(30)
'''
        for mode,code in [('before',29),('after',30)]:
            result=subprocess.run([sys.executable,'-X','utf8','-c',script],input=json.dumps([str(self.root),mode,payload]),text=True,capture_output=True,env=env,timeout=10)
            self.assertEqual(result.returncode,code,result.stderr)
            if mode=='before': self.assertFalse(self.read('history')['history'])
            else:
                self.assertEqual(self.service.dispatch('save',payload),json.loads(result.stdout))
                self.assertEqual(len(self.read('history')['history']),1)
