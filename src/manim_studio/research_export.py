"""Versioned scoped ZIP packages, bounded independent verification and restore."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from manim_studio.research import _json
from manim_studio.research_integrity import SHA, content_chunks, fail

EXPORT_VERSION = 1
MAX_MEMBER = 100 * 1024**3
MAX_TOTAL = 120 * 1024**3
MAX_RECORDS = 100_000
JSON_LIMIT = 64 * 1024**2

# Nested metadata is opt-in, including fields introduced after the original JSONL.
# Text, arguments, results, feedback, labels, settings paths and raw transcripts are absent.
SCALARS = frozenset('''schema_version studio_version python_version extension_version
prompt_type human_seconds time_source duration_seconds source_id thread_id client_id client_type
research_epoch capture_status code status reason boundary_verified coverage_start offset taxonomy_version
previous_human_head suggestion_id request_id artifact_id sha256 size role build_id proposal_id revision
decision_id kind origin reported_by action_id before_snapshot_id after_snapshot_id snapshot_id
run_context_id observed_at interval_id participant_id category process_token start_utc end_utc
confirmed_end_utc measured_seconds sequence clock_anomaly tail_unknown close_reason delta_seconds
report_id seconds retrospective measurement_ref replaces_interval_id voided previous_revision
fingerprint collection_epoch source_epoch scope project_revision connected protocol_version
provider model version name deployment client_version client_surface renderer profile effort code_revision temperature top_p seed reasoning_effort max_tokens max_output_tokens
studio python platform system release machine git_commit git_dirty available value provenance
source architecture architecture_source commit dirty captured_at confirmed_seconds tracked_seconds waiting_seconds aggregation_version
count incomplete raw_seconds union_seconds observed_actions evidence wall_span_seconds
start_seq end_seq last_sequence status revision previous_status expected_revision created_at
finished_at policy_revision storage mode seconds_per_category tracked canonical legacy_classification_seconds
'''.split())
OBJECTS = frozenset('''source model settings run_settings runtime provenance state candidate
candidate_source baseline_source values policy interval report context summary totals tool render
os git packages classifier model_turn authoring classification waiting tracked canonical reported families run_context
'''.split())
LISTS = frozenset('reasons related_prompt_ids event_ids warnings'.split())


def safe_path(name):
    if (not isinstance(name, str) or not name or '\\' in name or '\x00' in name
            or ':' in name or PurePosixPath(name).is_absolute() or PureWindowsPath(name).drive
            or any(p in ('', '.', '..') for p in name.split('/'))):
        fail('unsafe_path')
    return name


def metadata(value):
    """No recursive pass-through: unknown keys and containers are dropped."""
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, item in value.items():
        if key in SCALARS and (item is None or isinstance(item, (str, bool, int, float))):
            result[key] = item
        elif key in OBJECTS and isinstance(item, dict):
            result[key] = metadata(item)
        elif key in LISTS and isinstance(item, list):
            result[key] = [i for i in item if isinstance(i, (str, int, float, bool)) or i is None]
        elif key in ('manim', 'manim-slides', 'mcp') and isinstance(item, (str, type(None))):
            result[key] = item
        elif key == 'files' and isinstance(item, dict):
            result[key] = {safe_path(p): h for p, h in item.items() if isinstance(h, str) and SHA.fullmatch(h)}
        elif key in ('omitted', 'missing') and isinstance(item, list):
            result[key] = [metadata(i) for i in item if isinstance(i, dict)]
    return result


def package_snapshot(data, full):
    result = {k: v for k, v in data.items() if k not in ('contents', 'events')}
    if not full:
        result['lifecycle'] = {k: v for k, v in (data.get('lifecycle') or {}).items()
                               if k not in ('title', 'topic')}
        result['dependencies'] = [dict(scope=r['scope'], revision=r['revision'],
                                        payload=metadata(r['payload'])) for r in data['dependencies']]
        result['projections'] = {table: [{**{k: v for k, v in r.items() if k != 'payload'},
                                        'payload': metadata(r['payload'])} for r in rows]
                                 for table, rows in data['projections'].items()}
    return result


def write_package(root, data, report, job_id, mode, staging, progress):
    full = mode == 'full'
    members = {}
    unavailable = set(report['unavailable'])
    manifest = dict(export_version=EXPORT_VERSION, export_id=job_id, mode=mode,
                    project_id=data['project_id'], session_id=data['session_id'],
                    snapshot_seq=data['snapshot_seq'], schema_version=data['schema_version'],
                    checker_version=report['checker_version'], aggregation_version=1,
                    unavailable=sorted(unavailable), members=members)
    with zipfile.ZipFile(staging, 'x', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        def write(name, chunks):
            hashed = hashlib.sha256(); size = 0
            with archive.open(name, 'w', force_zip64=True) as target:
                for chunk in chunks:
                    target.write(chunk); size += len(chunk); hashed.update(chunk)
                    progress(None, None)
            members[name] = dict(size=size, sha256=hashed.hexdigest())
        events = (dict(e, payload=e['payload'] if full else metadata(e['payload'])) for e in data['events'])
        write('events.jsonl', ((_json(e) + '\n').encode('utf-8') for e in events))
        write('snapshot.json', [_json(package_snapshot(data, full)).encode('utf-8')])
        write('integrity.json', [_json(report).encode('utf-8')])
        write('summaries/time.json', [_json(report['time_summary']).encode('utf-8')])
        if full:
            for index, (sha, descriptor) in enumerate(data['contents'].items()):
                progress(index, len(data['contents']))
                if sha in unavailable:
                    continue
                # Fail on a mid-export change instead of publishing mismatched bytes.
                name = 'content/sha256/' + sha
                write(name, content_chunks(root, sha, descriptor))
                if members[name] != dict(size=descriptor['size'], sha256=sha):
                    fail('content_changed_during_export')
        archive.writestr('manifest.json', _json(manifest).encode('utf-8'))
    with open(staging, 'r+b') as output:
        os.fsync(output.fileno())
    verify_export(staging, progress=progress)
    return file_digest(staging, progress)


def file_digest(path, progress=None):
    hashed = hashlib.sha256()
    with open(path, 'rb') as stream:
        while chunk := stream.read(65536):
            hashed.update(chunk)
            if progress:
                progress(None, None)
    return hashed.hexdigest()


def verify_export(path, progress=None):
    """No original DB, no extraction, no code execution and no unbounded reads."""
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_RECORDS or len({i.filename for i in infos}) != len(infos):
                fail('duplicate_or_excess_members')
            total = 0
            for info in infos:
                safe_path(info.filename)
                if stat.S_ISLNK(info.external_attr >> 16) or info.is_dir() or info.flag_bits & 1:
                    fail('unsafe_member')
                if info.file_size > MAX_MEMBER:
                    fail('archive_size_limit')
                total += info.file_size
            if total > MAX_TOTAL:
                fail('archive_size_limit')
            def read_json(name):
                if archive.getinfo(name).file_size > JSON_LIMIT:
                    fail('json_size_limit')
                def unique(pairs):
                    d = {}
                    for k, v in pairs:
                        if k in d:
                            fail('duplicate_json_key')
                        d[k] = v
                    return d
                return json.loads(archive.read(name), object_pairs_hook=unique,
                                  parse_constant=lambda _: fail('invalid_number'))
            manifest = read_json('manifest.json')
            if (manifest.get('export_version') != EXPORT_VERSION or manifest.get('mode') not in ('metadata', 'full')
                    or not isinstance(manifest.get('export_id'), str)):
                fail('unsupported_export')
            from manim_studio.research_schema import VERSION
            if (type(manifest.get('schema_version')) is not int or not 1 <= manifest['schema_version'] <= VERSION
                    or manifest.get('checker_version') != 1 or manifest.get('aggregation_version') != 1):
                fail('unsupported_export_schema')
            members = manifest['members']
            required = {'events.jsonl', 'snapshot.json', 'integrity.json', 'summaries/time.json'}
            if not required <= set(members) or set(members) | {'manifest.json'} != {i.filename for i in infos}:
                fail('inventory_mismatch')
            for index, (name, expected) in enumerate(members.items()):
                if name not in required and not re.fullmatch(r'content/sha256/[0-9a-f]{64}', name):
                    fail('unexpected_member')
                if type(expected.get('size')) is not int or expected['size'] != archive.getinfo(name).file_size:
                    fail('member_size_mismatch')
                hashed = hashlib.sha256(); count = 0
                with archive.open(name) as stream:
                    while chunk := stream.read(65536):
                        count += len(chunk)
                        if count > expected['size']:
                            fail('member_size_mismatch')
                        hashed.update(chunk)
                        if progress:
                            progress(index, len(members))
                if count != expected['size'] or hashed.hexdigest() != expected['sha256']:
                    fail('member_hash_mismatch')
                if name.startswith('content/') and name.rsplit('/', 1)[1] != expected['sha256']:
                    fail('content_hash_mismatch')
            data = read_json('snapshot.json'); report = read_json('integrity.json')
            summary = read_json('summaries/time.json')
            for record in (data, report):
                if any(record.get(key) != manifest.get(key) for key in ('session_id', 'project_id', 'snapshot_seq')):
                    fail('snapshot_scope_mismatch')
            if summary != report['time_summary']:
                fail('summary_mismatch')
            if archive.getinfo('events.jsonl').file_size > JSON_LIMIT:
                fail('event_size_limit')
            events = []; ids = {}; last = 0
            with archive.open('events.jsonl') as stream:
                while line := stream.readline(JSON_LIMIT + 1):
                    if len(line) > JSON_LIMIT or len(events) >= MAX_RECORDS:
                        fail('event_size_limit')
                    event = json.loads(line)
                    if (event['session_id'] != manifest['session_id'] or type(event['seq']) is not int
                            or not last < event['seq'] <= manifest['snapshot_seq'] or event['id'] in ids):
                        fail('event_scope_invalid')
                    ids[event['id']] = event; events.append(event); last = event['seq']
            if not any(e['id'] == manifest['session_id'] and e['type'] == 'session.started' for e in events):
                fail('session_start_missing')
            # Broken links are permitted only as explicit integrity findings in a partial export.
            broken = []
            for event in events:
                for key in ('parent_id', 'prompt_id'):
                    ref = event.get(key)
                    if ref and (ref not in ids or ids[ref]['seq'] >= event['seq']):
                        broken.append(event['id'])
            declared = {f['entity_id'] for f in report['findings'] if f['code'] == 'event_reference_invalid'}
            if set(broken) - declared:
                fail('undeclared_broken_link')
            for rows in data['projections'].values():
                if any(r['session_id'] != manifest['session_id'] for r in rows):
                    fail('projection_scope_invalid')
            if manifest['mode'] == 'metadata':
                if any(name.startswith('content/') for name in members):
                    fail('metadata_contains_content')
                if any(r['payload'] != metadata(r['payload']) for rows in data['projections'].values() for r in rows):
                    fail('metadata_projection_contains_free_text')
                if any(k in (data.get('lifecycle') or {}) for k in ('title', 'topic')):
                    fail('metadata_contains_labels')
                if any(e['payload'] != metadata(e['payload']) for e in events):
                    fail('metadata_contains_free_text')
            else:
                from manim_studio.research_integrity import hashes
                refs = hashes(events) | hashes(data['projections'])
                explicit = {r['payload'].get('sha256') for r in data['projections']['research_artifacts']
                            if r['payload'].get('status') != 'retained'}
                missing = refs - {name.rsplit('/', 1)[1] for name in members if name.startswith('content/')}
                explicit.update(manifest['unavailable'])
                explicit.update(f['entity_id'] for f in report['findings'] if f['code'] == 'content_reference_missing')
                if missing - explicit:
                    fail('undeclared_missing_content')
                from manim_studio.research_time import summarize
                try:
                    calculated = summarize([r['payload'] for r in data['projections']['timing_intervals']],
                                           [r['payload'] for r in data['projections']['timing_reports']], events)
                except (ValueError, KeyError, TypeError, OverflowError):
                    calculated = {'unavailable': True}
                if calculated != summary:
                    fail('time_replay_mismatch')
                from manim_studio.research_integrity import check, PROJECTIONS
                if set(data['projections']) != set(PROJECTIONS):
                    fail('projection_inventory_mismatch')
                replay = dict(data, events=events, contents={name.rsplit('/', 1)[1]: dict(storage='verified_export', size=info['size'])
                              for name, info in members.items() if name.startswith('content/')})
                replayed = check(replay, deep=False)
                for domain in ('links', 'decisions', 'timing'):
                    if replayed['domains'][domain] == 'invalid' and report['domains'][domain] != 'invalid':
                        fail('integrity_replay_mismatch')
            return dict(valid=True, export_id=manifest['export_id'], mode=manifest['mode'],
                        session_id=manifest['session_id'], snapshot_seq=manifest['snapshot_seq'],
                        members=len(members), coverage=report['coverage'], domains=report['domains'])
    except (zipfile.BadZipFile, KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError, RuntimeError) as exc:
        raise ValueError('invalid_export') from exc


def restore_export(path, destination):
    """Restore evidence to a new directory; never modify an active project or run code."""
    verified = verify_export(path)
    destination = Path(destination).resolve()
    destination.mkdir(parents=False, exist_ok=False)
    try:
        with zipfile.ZipFile(path) as archive:
            # Keep content-addressed evidence and replayable state; never materialize caller paths.
            for info in archive.infolist():
                target = destination.joinpath(*PurePosixPath(info.filename).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open('xb') as output:
                    while chunk := source.read(65536):
                        output.write(chunk)
        return dict(verified, destination=str(destination))
    except BaseException:
        # A partial restore is kept as evidence, never reported successful.
        raise
