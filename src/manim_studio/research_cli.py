"""Host bridge: one JSON request on stdin, one JSON response on stdout."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from manim_studio.research import ResearchLog, PROMPT_TYPES, REASONS, STAGES


def dispatch(root: Path, action: str, payload: dict):
    log = ResearchLog(root)
    operations = {
        'configure': log.configure,
        'start_session': log.start_session,
        'record_prompt': log.record_prompt,
        'record_response': log.record_response,
        'classify': log.classify,
        'export': log.export,
    }
    if action == 'schema':
        return {'prompt_types': PROMPT_TYPES, 'reasons': REASONS, 'stages': STAGES}
    if action == 'status':
        return {'enabled': log.enabled}
    if action not in operations:
        raise ValueError('unknown research action')
    return operations[action](**payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('action', choices=['configure', 'start_session', 'record_prompt',
                                         'record_response', 'classify', 'export', 'schema', 'status'])
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin) if args.action not in ('schema', 'status') else {}
        print(json.dumps({'ok': True, 'data': dispatch(args.root, args.action, payload)}, ensure_ascii=False))
    except (ValueError, TypeError, OSError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
