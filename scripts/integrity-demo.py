"""Synthetic research fixture for local UI verification; no user files or model calls."""
import json
import sys
from pathlib import Path
from manim_studio.research import ResearchLog
from manim_studio.research_artifacts import ResearchArtifacts
from manim_studio.research_jobs import ResearchJobs
from manim_studio.research_time import ResearchTiming
root = Path(sys.argv[1]); root.mkdir(exist_ok=True)
(root/'lesson-plan.md').write_text('# וקטורים\nדוגמה סינתטית\n', encoding='utf-8')
log = ResearchLog(root); log.configure(True)
session = log.start_session('וקטורים · ניסוי סינתטי', model={'provider':'fixture','model':'synthetic-demo'})
prompt = log.record_prompt(session, 'הכן הסבר על חיבור וקטורים')
a = log.begin_action(session, 'render_scene', {}, prompt_id=prompt)
log.end_action(session, a, {'ok':False}, .2, prompt_id=prompt, error='SyntheticRenderError')
log.begin_action(session, 'render_scene', {})
archive = ResearchArtifacts(root)
with log.connection() as db:
    artifact = archive.retain(db, session, 'preview.mp4', 'preview_video', b'synthetic-not-a-real-video')
archive._content_path(artifact['sha256']).unlink()
timer = ResearchTiming(root)
timer.dispatch('report',dict(session_id=session,client_id='synthetic',request_id='report',category='authoring',seconds=120))
other = log.start_session('מחקר שני')
jobs = ResearchJobs(root)
jobs.dispatch('integrity','check',dict(session_id=session,deep=True,request_id='first'))
jobs.work_once()
print(json.dumps(dict(session_id=session,other_session_id=other),ensure_ascii=False))
