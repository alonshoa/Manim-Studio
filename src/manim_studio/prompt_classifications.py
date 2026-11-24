"""Versioned human annotation over the append-only research ledger. No model calls."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path

from manim_studio.research import ResearchLog, PROMPT_TYPES, REASONS, _json
from manim_studio.research_sessions import ResearchSessionError

ACTIONS = ('schema', 'list', 'get', 'history', 'save', 'skip', 'clear', 'suggest')
TYPE_LABELS = dict(zip(PROMPT_TYPES, ('פתיחת משימה', 'המשך רגיל', 'תיקון או שינוי מכוון', 'לא רלוונטי לניסוי')))
REASON_LABELS = dict(zip(REASONS, ('דיוק עובדתי או מתמטי', 'רצף ההסבר וסדר ההצגה', 'הסבר לא ברור',
    'הוספת תוכן', 'הסרת תוכן', 'שינוי חזותי או אנימציה', 'אי־התאמה לכוונה', 'בעיה טכנית או רינדור', 'אחר')))
HUMAN_EVENTS = ('classification.confirmed', 'classification.skipped', 'classification.cleared')


def fail(code):
    raise ResearchSessionError(code)


def validate(prompt_type, reasons, other, taxonomy_version=1):
    if type(taxonomy_version) is not int or taxonomy_version != 1:
        fail('unsupported_taxonomy')
    if prompt_type not in PROMPT_TYPES:
        fail('invalid_classification')
    if reasons is not None and (not isinstance(reasons, list) or any(not isinstance(r, str) or r not in REASONS for r in reasons)):
        fail('invalid_classification')
    if other is not None and (not isinstance(other, str) or len(other) > 4000):
        fail('invalid_classification')
    if reasons and 'other' in reasons:
        if not isinstance(other, str) or not other.strip():
            fail('invalid_classification')
    elif other:
        fail('invalid_classification')
    return dict(prompt_type=prompt_type, reasons=list(dict.fromkeys(reasons)) if reasons is not None else None,
                other=other.strip() if other else None, taxonomy_version=1)


def decode(row):
    return dict(row, payload=json.loads(row['payload']))


def annotation_state(events):
    """Rebuildable projection; suggestions never change the human head."""
    head, current, suggestion, review = None, None, None, 'unclassified'
    for event in events:
        if event['type'] == 'classification.suggested':
            suggestion = event
        elif event['type'] in HUMAN_EVENTS and event['actor'] == 'human':
            head = event['id']
            if event['type'] == 'classification.skipped':
                if current is None:
                    review = 'deferred'
            elif event['type'] == 'classification.cleared':
                current, review = None, 'unclassified'
            else:
                payload = event['payload']
                # Historical null confirmations clear human validity, not skip.
                current = event if payload.get('prompt_type') in PROMPT_TYPES and payload.get('taxonomy_version', 1) == 1 else None
                review = 'confirmed' if current else 'unclassified'
    return dict(human_head_event_id=head, current=current, suggestion=suggestion, review_status=review)


class PromptClassifications:
    def __init__(self, root):
        self.log = ResearchLog(Path(root))

    def schema(self):
        return {'api_version': 1, 'taxonomy_version': 1, 'required_human_versioned_writes': True,
                'prompt_types': [{'code': code, 'label': label} for code, label in TYPE_LABELS.items()],
                'reasons': [{'code': code, 'label': label} for code, label in REASON_LABELS.items()]}

    def _project(self, db):
        row = db.execute("SELECT value FROM config WHERE key='project_id'").fetchone()
        return row[0] if row else None

    def _session(self, db, session_id):
        if not isinstance(session_id, str):
            fail('session_not_found')
        row = db.execute("SELECT * FROM events WHERE id=? AND type='session.started'", (session_id,)).fetchone()
        if not row:
            fail('session_not_found')
        title = json.loads(row['payload']).get('label', session_id)
        managed = db.execute('SELECT title,topic,state FROM research_sessions WHERE session_id=?', (session_id,)).fetchone()
        return dict(managed) if managed else dict(title=title, topic='', state='legacy')

    def _prompt(self, db, session_id, prompt_id):
        self._session(db, session_id)
        if not isinstance(prompt_id, str):
            fail('prompt_not_found')
        row = db.execute("SELECT * FROM events WHERE id=? AND session_id=? AND type='prompt.recorded'", (prompt_id, session_id)).fetchone()
        if not row:
            fail('prompt_not_found')
        return decode(row)

    def _events(self, db, session_id, prompt_id, snapshot):
        return [decode(r) for r in db.execute("SELECT * FROM events WHERE session_id=? AND prompt_id=? "
                    "AND type LIKE 'classification.%' AND seq<=? ORDER BY seq", (session_id, prompt_id, snapshot))]

    def dispatch(self, action, payload):
        if action not in ACTIONS or not isinstance(payload, dict):
            fail('invalid_request')
        if action == 'schema':
            return self.schema()
        if not self.log.database.exists():
            fail('session_not_found')
        try:
            with self.log.connection(timeout=1.0) as db:
                writing = action in ('save', 'skip', 'clear', 'suggest')
                db.execute('BEGIN IMMEDIATE' if writing else 'BEGIN')
                if writing:
                    return self._write(db, action, payload)
                if action == 'list':
                    return self._list(db, **payload)
                return self._get(db, history=action == 'history', **payload)
        except (sqlite3.Error, OSError) as exc:
            raise ResearchSessionError('storage_error', 'Annotation storage is unavailable; draft was not confirmed.') from exc

    def _get(self, db, session_id, prompt_id, history=False):
        prompt = self._prompt(db, session_id, prompt_id)
        snapshot = db.execute('SELECT COALESCE(max(seq),0) FROM events').fetchone()[0]
        events = self._events(db, session_id, prompt_id, snapshot)
        state = annotation_state(events)
        preceding = db.execute("SELECT id,type,payload FROM events WHERE session_id=? AND seq<? "
                               "AND type='model.responded' ORDER BY seq DESC LIMIT 1", (session_id, prompt['seq'])).fetchone()
        context = []
        if preceding:
            context.append({'id': preceding['id'], 'relation': 'preceding', 'text': json.loads(preceding['payload']).get('text', '')[:12000]})
        for row in db.execute("SELECT * FROM events WHERE session_id=? AND seq>? AND type IN "
                              "('model.responded','action.started','action.finished') ORDER BY seq", (session_id, prompt['seq'])):
            value = json.loads(row['payload'])
            related = value.get('related_prompt_ids', [])
            if row['prompt_id'] == prompt_id or prompt_id in related:
                context.append({'id': row['id'], 'relation': 'linked' if row['prompt_id'] == prompt_id else 'shared',
                                'text': (value.get('text') or value.get('name') or row['type'])[:12000]})
            if len(context) >= 12:
                break
        return dict(project_id=self._project(db), session_id=session_id, prompt_id=prompt_id,
                    session=self._session(db, session_id), prompt=prompt, snapshot_seq=snapshot,
                    context=context, history=events if history else [], **state)

    def _list(self, db, session_id, filter='unclassified', offset=0, limit=30, snapshot_seq=None):
        session = self._session(db, session_id)
        if filter not in ('all', 'unclassified', 'deferred', 'confirmed') or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            fail('invalid_request')
        newest = db.execute('SELECT COALESCE(max(seq),0) FROM events').fetchone()[0]
        if snapshot_seq is not None and (type(snapshot_seq) is not int or not 0 <= snapshot_seq <= newest):
            fail('invalid_request')
        snapshot = newest if snapshot_seq is None else snapshot_seq
        by_prompt = {}
        for row in db.execute("SELECT * FROM events WHERE session_id=? AND seq<=? AND type LIKE 'classification.%' ORDER BY seq", (session_id, snapshot)):
            by_prompt.setdefault(row['prompt_id'], []).append(decode(row))
        rows, counts = [], dict(total=0, confirmed=0, missing=0, deferred=0, reasons_reviewed=0)
        for row in db.execute("SELECT * FROM events WHERE session_id=? AND type='prompt.recorded' AND seq<=? ORDER BY seq", (session_id, snapshot)):
            state = annotation_state(by_prompt.get(row['id'], []))
            counts['total'] += 1
            confirmed = state['current'] is not None
            counts['confirmed' if confirmed else 'missing'] += 1
            counts['deferred'] += int(state['review_status'] == 'deferred')
            counts['reasons_reviewed'] += int(confirmed and state['current']['payload'].get('reasons') is not None)
            if filter == 'all' or state['review_status'] == filter:
                rows.append(dict(prompt_id=row['id'], number=counts['total'], timestamp=row['timestamp'],
                    preview=json.loads(row['payload']).get('text', '')[:180], **state))
        gaps = db.execute("SELECT count(*) FROM events WHERE session_id=? AND type='capture.gap' AND seq<=?", (session_id, snapshot)).fetchone()[0]
        return dict(project_id=self._project(db), session_id=session_id, session=session, snapshot_seq=snapshot,
                    prompts=rows[offset:offset+limit], next_offset=offset+limit if offset+limit < len(rows) else None,
                    offset=offset, limit=limit, filtered_count=len(rows), counts=counts,
                    coverage={'known_gaps': gaps, 'status': 'partial' if gaps else 'unverified'})

    def _write(self, db, action, payload):
        data = dict(payload)
        request_id = data.get('request_id')
        if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 512:
            fail('classification_revision_required')
        if action != 'suggest' and 'expected_human_head' not in data:
            fail('classification_revision_required')
        if data.get('project_id') != self._project(db):
            fail('project_mismatch')
        fingerprint = hashlib.sha256(json.dumps({'action': 'classification.'+action, 'payload': data}, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        receipt = db.execute('SELECT * FROM research_requests WHERE request_id=?', (request_id,)).fetchone()
        if receipt:
            if receipt['fingerprint'] != fingerprint:
                fail('request_id_conflict')
            return json.loads(receipt['result'])
        session_id, prompt_id = data.get('session_id'), data.get('prompt_id')
        self._prompt(db, session_id, prompt_id)
        current = self._get(db, session_id, prompt_id)
        if action != 'suggest' and data['expected_human_head'] != current['human_head_event_id']:
            fail('classification_conflict')
        payload = dict(request_id=request_id, taxonomy_version=1,
                       previous_human_head=current['human_head_event_id'])
        if action in ('clear', 'skip') and any(data.get(key) is not None for key in ('reasons', 'other', 'human_seconds')):
            fail('invalid_classification')
        if action in ('save', 'suggest'):
            payload.update(validate(data.get('prompt_type'), data.get('reasons'), data.get('other'), data.get('taxonomy_version', 1)))
            if data.get('human_seconds') is not None:
                seconds = data['human_seconds']
                if action == 'suggest' or isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
                    fail('invalid_classification')
                payload.update(human_seconds=seconds, time_source='self_report')
            if action == 'suggest':
                classifier = data.get('classifier')
                if classifier is not None and (not isinstance(classifier, dict) or any(k not in ('name', 'version', 'model') or not isinstance(v, str) or len(v) > 512 for k,v in classifier.items())):
                    fail('invalid_classification')
                payload['classifier'] = classifier
            if data.get('suggestion_id'):
                suggestion = db.execute("SELECT * FROM events WHERE id=? AND session_id=? AND prompt_id=? AND type='classification.suggested'",
                                        (data['suggestion_id'], session_id, prompt_id)).fetchone()
                if action != 'save' or not suggestion:
                    fail('invalid_classification')
                payload['suggestion_id'] = data['suggestion_id']
        elif action == 'skip' and current['current']:
            fail('already_classified')
        else:
            payload.update(prompt_type=None, reasons=None)
        kind = {'save':'classification.confirmed', 'suggest':'classification.suggested',
                'skip':'classification.skipped', 'clear':'classification.cleared'}[action]
        event_id = self.log._event(db, kind, session_id, payload,
                                  prompt_id=prompt_id, actor='model' if action == 'suggest' else 'human')
        result = dict(self._get(db, session_id, prompt_id), event_id=event_id)
        db.execute('INSERT INTO research_requests VALUES (?,?,?)', (request_id, fingerprint, _json(result)))
        return result
