"""Snapshot-based research checks. Unknown delivery is never reported as complete."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone

from manim_studio.research import ResearchLog
from manim_studio.research_artifacts import ResearchArtifacts
from manim_studio.research_sessions import ResearchSessionError

CHECKER_VERSION = 1
SHA = re.compile(r"^[0-9a-f]{64}$")
PROJECTIONS = ('research_artifacts', 'artifact_snapshots', 'research_decisions',
               'timing_intervals', 'timing_reports', 'run_contexts')


def utc():
    return datetime.now(timezone.utc).isoformat()


def fail(code):
    raise ResearchSessionError(code)


def hashes(value):
    """Only known content references, not arbitrary 64-character user text."""
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'sha256' and isinstance(item, str) and SHA.fullmatch(item):
                found.add(item)
            elif key == 'files' and isinstance(item, dict):
                found.update(h for h in item.values() if isinstance(h, str) and SHA.fullmatch(h))
            elif isinstance(item, (dict, list)):
                found.update(hashes(item))
    elif isinstance(value, list):
        for item in value:
            found.update(hashes(item))
    return found


def snapshot(log, db, session):
    row = db.execute("SELECT * FROM events WHERE id=? AND type='session.started'", (session,)).fetchone()
    if not row:
        fail('session_not_found')
    seq = db.execute('SELECT COALESCE(max(seq),0) FROM events').fetchone()[0]
    project = db.execute("SELECT value FROM config WHERE key='project_id'").fetchone()
    events = [dict(r, payload=json.loads(r['payload'])) for r in db.execute(
        'SELECT * FROM events WHERE session_id=? AND seq<=? ORDER BY seq', (session, seq))]
    projections = {}
    for table in PROJECTIONS:
        projections[table] = [dict(r, payload=json.loads(r['payload'])) for r in db.execute(
            f'SELECT * FROM {table} WHERE session_id=? ORDER BY rowid', (session,))]
    lifecycle = db.execute('SELECT * FROM research_sessions WHERE session_id=?', (session,)).fetchone()
    # Shared project policy is an explicit dependency, not a dump of other sessions.
    policies = [dict(r, payload=json.loads(r['payload'])) for r in db.execute(
        "SELECT * FROM artifact_policies WHERE scope IN ('project',?)", (session,))]
    data = dict(project_id=project[0] if project else None, session_id=session,
                snapshot_seq=seq, schema_version=db.execute('PRAGMA user_version').fetchone()[0],
                created_at=utc(), events=events, projections=projections,
                lifecycle=dict(lifecycle) if lifecycle else None, dependencies=policies)
    refs = hashes(events) | hashes(projections)
    contents = {}
    for sha in sorted(refs):
        blob = db.execute('SELECT rowid,length(content) FROM blobs WHERE sha256=?', (sha,)).fetchone()
        if blob:
            contents[sha] = dict(storage='sqlite', rowid=blob[0], size=blob[1])
    for row in projections['research_artifacts']:
        artifact = row['payload']
        sha = artifact.get('sha256')
        if sha and artifact.get('status') == 'retained':
            contents[sha] = dict(storage='archive', size=artifact['size'])
    data['pending_jobs'] = [dict(id=r['id'], status=r['status']) for r in db.execute(
        "SELECT id,status FROM artifact_jobs WHERE session_id=? AND status IN ('pending','running')", (session,))]
    data['contents'] = contents
    return data


def content_chunks(root, sha, descriptor):
    """Bound memory for videos and SQLite blobs; immutable references only."""
    log = ResearchLog(root)
    if descriptor['storage'] == 'sqlite':
        with log.connection() as db:
            row = db.execute('SELECT rowid FROM blobs WHERE sha256=?', (sha,)).fetchone()
            if not row:
                fail('content_missing')
            with db.blobopen('blobs', 'content', row[0], readonly=True) as stream:
                while chunk := stream.read(65536):
                    yield chunk
    else:
        import os
        from manim_studio.research_files import open_project_file
        archive = ResearchArtifacts(root)
        path = archive._content_path(sha)
        with os.fdopen(open_project_file(log.root, path.relative_to(log.root).as_posix(), internal=True), 'rb') as stream:
            while chunk := stream.read(65536):
                yield chunk


def check(data, root=None, deep=False, progress=None):
    findings = []
    domains = {k: 'valid' for k in ('conversation', 'links', 'decisions', 'content', 'timing', 'storage')}
    # No checker can establish that an external client delivered every message.
    domains['conversation'] = 'unverified'
    def add(code, domain, entity=None, severity='warning', state='partial'):
        findings.append(dict(code=code, domain=domain, entity_id=entity, severity=severity))
        rank = {'valid': 0, 'unverified': 1, 'partial': 2, 'invalid': 3}
        if rank[state] > rank[domains[domain]]:
            domains[domain] = state
    add('source_delivery_unverified', 'conversation', severity='info', state='unverified')
    events = data['events']; by_id = {e['id']: e for e in events}
    if len(by_id) != len(events):
        add('duplicate_event', 'links', severity='error', state='invalid')
    if not any(e['type'] == 'prompt.recorded' for e in events):
        add('no_prompts', 'conversation')
    finished = set(); classified = {}; checkpoints = {}; candidates = {}
    for e in events:
        id, kind, p = e['id'], e['type'], e['payload']
        if e['session_id'] != data['session_id'] or e['seq'] > data['snapshot_seq']:
            add('event_scope_mismatch', 'links', id, 'error', 'invalid')
        for key in ('prompt_id', 'parent_id'):
            ref = e.get(key)
            if ref and (ref not in by_id or by_id[ref]['seq'] >= e['seq']):
                add('event_reference_invalid', 'links', id, 'error', 'invalid')
        if e.get('prompt_id') in by_id and by_id[e['prompt_id']]['type'] != 'prompt.recorded':
            add('prompt_reference_invalid', 'links', id, 'error', 'invalid')
        if kind == 'action.finished':
            parent = by_id.get(e.get('parent_id'))
            if not parent or parent['type'] != 'action.started' or parent.get('prompt_id') != e.get('prompt_id'):
                add('action_start_invalid', 'links', id, 'error', 'invalid')
            if e.get('parent_id') in finished:
                add('duplicate_action_finish', 'links', id, 'error', 'invalid')
            finished.add(e.get('parent_id'))
        if kind.startswith('capture.') and (kind.endswith('gap') or kind.endswith('failed') or p.get('capture_status') == 'partial'):
            add('capture_gap', 'conversation', id)
        if kind == 'action.observation_ended':
            add('action_outcome_unknown', 'links', e.get('parent_id'))
        if kind in ('decision.requested', 'decision.candidate_prepared'):
            candidates[p.get('decision_id')] = p.get('candidate')
        if kind in ('decision.completed', 'decision.failed'):
            if p.get('decision_id') not in candidates or p.get('candidate') != candidates[p.get('decision_id')]:
                add('decision_candidate_changed', 'decisions', id, 'error', 'invalid')
        if kind.startswith('classification.'):
            from manim_studio.research import PROMPT_TYPES, REASONS
            if p.get('taxonomy_version', 1) != 1 or p.get('prompt_type') not in (None, *PROMPT_TYPES) or any(r not in REASONS for r in (p.get('reasons') or [])):
                add('classification_taxonomy_invalid', 'links', id, 'error', 'invalid')
            if kind in ('classification.confirmed', 'classification.cleared', 'classification.skipped'):
                prompt = e.get('prompt_id')
                if e['actor'] != 'human':
                    add('classification_actor_invalid', 'links', id, 'error', 'invalid')
                if 'previous_human_head' not in p:
                    add('classification_history_legacy', 'links', id, 'info', 'unverified')
                elif p.get('previous_human_head') != classified.get(prompt):
                    add('classification_head_invalid', 'links', id, 'error', 'invalid')
                classified[prompt] = id
        if kind == 'time.interval.checkpointed':
            key = p.get('interval_id'); sequence = p.get('sequence', 0)
            if sequence <= checkpoints.get(key, 0):
                add('timer_checkpoint_invalid', 'timing', id, 'error', 'invalid')
            checkpoints[key] = sequence
        if p.get('run_context_id') and not any(r['id'] == p['run_context_id'] for r in data['projections']['run_contexts']):
            add('run_context_missing', 'links', id, 'error', 'invalid')
    for e in events:
        if e['type'] == 'action.started' and e['id'] not in finished:
            add('action_pending_or_interrupted', 'links', e['id'])
        state = e['payload'].get('state')
        if isinstance(state, dict) and state.get('omitted'):
            add('snapshot_omitted', 'content', e['id'])
    ids_by_table = {table: {r['id'] for r in rows} for table, rows in data['projections'].items()}
    for table, rows in data['projections'].items():
        for row in rows:
            p = row['payload']
            if row['session_id'] != data['session_id'] or p.get('session_id', data['session_id']) != data['session_id']:
                add('projection_scope_invalid', 'links', row['id'], 'error', 'invalid')
            for key, target in (('artifact_id', 'research_artifacts'), ('before_snapshot_id', 'artifact_snapshots'),
                                ('after_snapshot_id', 'artifact_snapshots'), ('run_context_id', 'run_contexts')):
                if p.get(key) and p[key] not in ids_by_table[target]:
                    add('projection_reference_invalid', 'links', row['id'], 'error', 'invalid')
            for ref in p.get('artifact_ids', []):
                if ref not in ids_by_table['research_artifacts']:
                    add('snapshot_artifact_missing', 'content', row['id'], 'error', 'invalid')
            for key, target in (('prompt_id', 'prompt.recorded'), ('action_id', 'action.started')):
                if p.get(key) and (p[key] not in by_id or by_id[p[key]]['type'] != target):
                    add('projection_event_invalid', 'links', row['id'], 'error', 'invalid')
    def manifests(value, entity):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'files':
                    if not isinstance(item, dict):
                        add('source_manifest_invalid', 'content', entity, 'error', 'invalid')
                        continue
                    for path, sha in item.items():
                        from manim_studio.research_export import safe_path
                        try:
                            safe_path(path)
                            if not isinstance(sha, str) or not SHA.fullmatch(sha):
                                raise ValueError('digest')
                        except ValueError:
                            add('source_manifest_invalid', 'content', entity, 'error', 'invalid')
                elif isinstance(item, (dict, list)):
                    manifests(item, entity)
        elif isinstance(value, list):
            for item in value:
                manifests(item, entity)
    for e in events:
        manifests(e['payload'], e['id'])
    for rows in data['projections'].values():
        for row in rows:
            manifests(row['payload'], row['id'])
    for row in data['projections']['research_artifacts']:
        a = row['payload']
        if a.get('status') != 'retained':
            add('artifact_' + a.get('status', 'unknown'), 'content', row['id'],
                'info' if a.get('status') == 'purged' else 'warning')
        elif a.get('sha256') not in data['contents']:
            add('retained_content_missing', 'content', row['id'], 'error', 'invalid')
    artifact_ids = {r['id']: r['payload'] for r in data['projections']['research_artifacts']}
    for row in data['projections']['research_decisions']:
        d = row['payload']
        if d.get('status') == 'outcome_unknown':
            add('decision_outcome_unknown', 'decisions', row['id'])
        if d.get('origin') not in ('human', 'automation'):
            add('decision_origin_unknown', 'decisions', row['id'])
        for candidate in (d.get('candidate') or {}).values():
            if not isinstance(candidate, dict):
                continue
            original = artifact_ids.get(candidate.get('artifact_id'))
            if not original or original.get('sha256') != candidate.get('sha256'):
                add('decision_candidate_invalid', 'decisions', row['id'], 'error', 'invalid')
    for row in data['projections']['artifact_snapshots']:
        if row['payload'].get('omitted'):
            add('snapshot_omitted', 'content', row['id'])
    intervals = [r['payload'] for r in data['projections']['timing_intervals']]
    reports = [r['payload'] for r in data['projections']['timing_reports']]
    for i in intervals:
        if i.get('tail_unknown') or i.get('status') == 'interrupted':
            add('timer_unconfirmed_tail', 'timing', i.get('interval_id'))
        if i.get('status') == 'active':
            add('timer_active_at_snapshot', 'timing', i.get('interval_id'), 'info')
        value = i.get('measured_seconds')
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            add('timer_duration_invalid', 'timing', i.get('interval_id'), 'error', 'invalid')
    try:
        from manim_studio.research_time import summarize
        summary = summarize(intervals, reports, events)
        for warning in summary.get('warnings', []):
            add(warning, 'timing')
    except (ValueError, TypeError, KeyError, OverflowError):
        summary = {'unavailable': True}
        add('time_summary_invalid', 'timing', severity='error', state='invalid')
    missing = hashes(events) | hashes(data['projections'])
    missing -= set(data['contents'])
    # Explicitly purged/unavailable artifact refs remain declared omissions, not corruption.
    declared = {a.get('sha256') for a in artifact_ids.values() if a.get('status') != 'retained'}
    for sha in sorted(missing - declared):
        add('content_reference_missing', 'content', sha, 'error', 'invalid')
    unavailable = set()
    for index, (sha, descriptor) in enumerate(data['contents'].items()):
        if progress:
            progress(index, len(data['contents']))
        try:
            if deep:
                count = 0; digest = hashlib.sha256()
                for chunk in content_chunks(root, sha, descriptor):
                    count += len(chunk); digest.update(chunk)
                    if count > descriptor['size']:
                        fail('content_corrupt')
                    if progress:
                        progress(index, len(data['contents']))
                if count != descriptor['size'] or digest.hexdigest() != sha:
                    fail('content_corrupt')
            elif descriptor['storage'] == 'archive':
                if ResearchArtifacts(root)._content_path(sha).stat().st_size != descriptor['size']:
                    fail('content_corrupt')
        except (OSError, ValueError):
            unavailable.add(sha)
            add('content_missing_or_corrupt', 'content', sha, 'error', 'invalid')
    if not deep:
        add('content_bytes_unverified', 'content', severity='info', state='unverified')
    for job in data.get('pending_jobs', []):
        add('artifact_job_pending_or_interrupted', 'storage', job['id'])
    if summary.get('human_time_missing'):
        add('human_time_missing', 'timing')
    if not any(r['payload'].get('model') and any(v is not None for v in r['payload']['model'].values())
               for r in data['projections']['run_contexts']):
        add('model_metadata_unknown', 'timing')
    if not data['projections']['run_contexts']:
        add('run_context_unknown', 'timing')
    return dict(checker_version=CHECKER_VERSION, snapshot_seq=data['snapshot_seq'],
                project_id=data['project_id'], session_id=data['session_id'], deep=deep,
                completed_at=utc(), domains=domains, findings=findings,
                time_summary=summary, unavailable=sorted(unavailable),
                coverage='partial' if any(v in ('partial', 'invalid') for v in domains.values()) else 'unverified')
