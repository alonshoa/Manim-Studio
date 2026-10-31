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
    if action in ('codex-connect', 'codex-config', 'capture-status', 'codex-hook'):
        from manim_studio.research_capture import CodexCapture, connect, hook_config
        if action == 'codex-connect':
            return connect(root)
        if action == 'codex-config':
            return hook_config(root)
        capture = CodexCapture(root)
        return capture.status() if action == 'capture-status' else capture.handle(payload)
    if action not in operations:
        raise ValueError('unknown research action')
    return operations[action](**payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('action', choices=['configure', 'start_session', 'record_prompt',
                                         'record_response', 'classify', 'export', 'schema', 'status',
                                         'codex-connect', 'codex-config', 'codex-hook', 'capture-status'])
    args = parser.parse_args()
    payload = None
    try:
        payload = json.load(sys.stdin) if args.action not in (
            'schema', 'status', 'codex-connect', 'codex-config', 'capture-status') else {}
        result = dispatch(args.root, args.action, payload)
        # Hook output must never become model context, deny tools, or continue a turn.
        print(json.dumps({} if args.action == 'codex-hook' else {'ok': True, 'data': result},
                         ensure_ascii=False))
    except Exception as exc:
        if args.action == 'codex-hook':
            # Keep Codex working even on malformed input/disk failure. No payload text.
            print('{}')
            try:
                from manim_studio.research_capture import CodexCapture
                CodexCapture(args.root).record_failure(payload, type(exc).__name__)
            except Exception as diagnostic_error:
                print('Capture failure diagnostics could not be persisted '
                      f'({type(diagnostic_error).__name__}).', file=sys.stderr)
            print(f'Manim Studio research capture failed ({type(exc).__name__}); '
                  'this invocation was not collected. Check capture-status.', file=sys.stderr)
            return
        print(json.dumps({'ok': False, 'error': str(exc)}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
