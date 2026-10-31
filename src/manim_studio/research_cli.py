"""Host bridge: one JSON request on stdin, one JSON response on stdout."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from manim_studio.research import ResearchLog, PROMPT_TYPES, REASONS, STAGES


def dispatch(root: Path, action: str, payload: dict):
    log = ResearchLog(root)
    if action.startswith('timing.'):
        from manim_studio.research_time import ResearchTiming
        return ResearchTiming(root).dispatch(action.removeprefix('timing.'),payload)
    if action.startswith('artifacts.'):
        from manim_studio.research_artifacts import ResearchArtifacts, kick_worker
        service = ResearchArtifacts(root)
        result = service.dispatch(action.removeprefix('artifacts.'), payload)
        if action == 'artifacts.purge':
            service.collect_garbage()
        if action in ('artifacts.list', 'artifacts.job_status', 'artifacts.retry_jobs'):
            kick_worker(root)
        return result
    if action.startswith('classification.'):
        from manim_studio.prompt_classifications import PromptClassifications
        return PromptClassifications(root).dispatch(action.removeprefix('classification.'), payload)
    if action.startswith('research.'):
        from manim_studio.research_sessions import ResearchSessions
        return ResearchSessions(root).dispatch(action.removeprefix('research.'), payload)
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


def rpc_loop(root):
    """Dedicated annotation transport, separate from the synchronous authoring queue."""
    from manim_studio.rpc_stdio import configure_utf8
    configure_utf8()
    for line in sys.stdin:
        request_id = None
        try:
            request = json.loads(line)
            request_id = request.get('id')
            method = request.get('method', '')
            if not isinstance(request_id, int) or not isinstance(method, str) or not (method.startswith(('classification.', 'artifacts.', 'timing.')) or method in ('research.list', 'research.get')):
                raise ValueError('invalid annotation RPC request')
            result = dispatch(root, method, request.get('params', {}))
            response = {'id': request_id, 'ok': True, 'data': result}
        except Exception as exc:
            response = {'id': request_id, 'ok': False, 'error': {
                'code': getattr(exc, 'code', 'invalid_request'), 'message': str(exc)}}
        print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


def main():
    from manim_studio.research_sessions import ACTIONS
    from manim_studio.prompt_classifications import ACTIONS as ANNOTATIONS
    from manim_studio.research_artifacts import ACTIONS as ARTIFACTS
    from manim_studio.research_time import ACTIONS as TIMING
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('action', choices=['configure', 'start_session', 'record_prompt',
                                         'record_response', 'classify', 'export', 'schema', 'status',
                                         'codex-connect', 'codex-config', 'codex-hook', 'capture-status'] +
                                        ['research.' + action for action in ACTIONS] +
                                        ['classification.' + action for action in ANNOTATIONS] + ['artifacts.' + action for action in ARTIFACTS] + ['timing.' + action for action in TIMING] + ['rpc'])
    args = parser.parse_args()
    if args.action == 'rpc':
        return rpc_loop(args.root)
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
