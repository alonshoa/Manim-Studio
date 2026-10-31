"""Create synthetic research records for reproducible UI tests/screenshots only."""
import json
import sys
from pathlib import Path
from manim_studio.research import ResearchLog
from manim_studio.research_sessions import ResearchSessions
from manim_studio.prompt_classifications import PromptClassifications

root = Path(sys.argv[1]).resolve()
root.mkdir(parents=True, exist_ok=True)
log = ResearchLog(root)
if log.database.exists():
    raise SystemExit('Refusing to overwrite an existing research ledger')
log.configure(True)
session = log.start_session('וקטורים — ניסיון 01')
messages = [
    'בוא נבנה שיעור על מרחק ודמיון בין וקטורים, עם דוגמה חזותית פשוטה.',
    'כן, תמשיך לדוגמה הבאה ותראה גם את החישוב ב־NumPy.',
    'הדוגמה הזו לא מסבירה למה צריך נרמול. תתחיל מההבדל בין אורך לכיוון, ואז תחזור לחישוב.',
    'תגדיל את המספרים ליד החיצים ותאט קצת את המעבר בין השלבים.',
    'רגע, זה לא קשור לשיעור — נחזור לזה אחר כך.',
    'הרינדור נכשל בגלל הגופן בעברית. תבדוק את ההגדרה ותנסה שוב.',
]
prompts = []
for message in messages:
    prompt = log.record_prompt(session, message)
    log.record_response(session, prompt, 'אפשר להציג שני וקטורים בעלי אותו כיוון ואורכים שונים, ואז לנרמל אותם לאורך יחידה.')
    prompts.append(prompt)
service = PromptClassifications(root)
project = service.dispatch('get', {'session_id':session,'prompt_id':prompts[0]})['project_id']
for index, kind in [(0,'initial'),(1,'continuation')]:
    service.dispatch('save', dict(project_id=project,session_id=session,prompt_id=prompts[index],
        prompt_type=kind,reasons=None if index == 0 else [],expected_human_head=None,request_id=f'seed-human-{index}'))
service.dispatch('skip',dict(project_id=project,session_id=session,prompt_id=prompts[4],expected_human_head=None,request_id='seed-skip'))
service.dispatch('suggest',dict(project_id=project,session_id=session,prompt_id=prompts[2],
    prompt_type='corrective',reasons=['unclear_explanation','narrative_order'],request_id='seed-suggestion',
    classifier={'name':'DemoClassifier','version':'1.0','model':'fixture-only'}))
manager = ResearchSessions(root)
state = manager.dispatch('adopt_legacy', dict(session_id=session,title='וקטורים — ניסיון 01',topic='מרחק ודמיון בין וקטורים',request_id='seed-adopt'))
manager.dispatch('finish',dict(session_id=session,expected_revision=state['revision'],request_id='seed-finish'))
with log.connection() as db:
    log._event(db,'capture.gap',session,{'code':'synthetic_coverage_example','source':{'client':'fixture'}})
log.configure(False)
print(json.dumps({'session_id':session,'project_id':project,'prompts':prompts},ensure_ascii=False))
