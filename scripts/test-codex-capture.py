"""Exercise real Codex hooks against a local fake Responses server, without auth.

Usage: python scripts/test-codex-capture.py --codex /path/to/codex
Only a fresh temporary project is enrolled. No real model, user config, credentials,
or repository writes are needed. Normal tool sandboxing stays enabled. The temporary
hook definition is generated and checked here before the test-only trust override.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(SOURCE))
from manim_studio.research_capture import CodexCapture, HOOKS, MARKER, connect


class Model(BaseHTTPRequestHandler):
    calls = 0

    def log_message(self, *args):
        pass

    def do_GET(self):
        content = b'{"models":[]}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        # Consume, but do not retain or print request context.
        self.rfile.read(int(self.headers['Content-Length']))
        type(self).calls += 1
        first = type(self).calls == 1
        message = {'id': 'msg1' if first else 'msg2', 'type': 'message', 'role': 'assistant',
                   'phase': 'commentary' if first else 'final_answer', 'status': 'completed',
                   'content': [{'type': 'output_text', 'text': 'Checking the example.' if first
                                else 'The example failed as expected. הנה הסבר.', 'annotations': []}]}
        items = [message]
        if first:
            items.append({'id': 'fc1', 'type': 'function_call', 'call_id': 'test-call1',
                          'name': 'exec_command',
                          'arguments': json.dumps({'cmd': "printf 'render failed\\n'; exit 1"})})
        response = {'id': f'resp{type(self).calls}', 'object': 'response', 'created_at': 1793361600,
                    'status': 'completed', 'model': 'mock-capture', 'output': items,
                    'usage': {'input_tokens': 10, 'output_tokens': 10, 'total_tokens': 20}}
        events = [{'type': 'response.created', 'response': dict(response, output=[], status='in_progress')}]
        for index, item in enumerate(items):
            events.append({'type': 'response.output_item.added', 'output_index': index, 'item': item})
            events.append({'type': 'response.output_item.done', 'output_index': index, 'item': item})
        events.append({'type': 'response.completed', 'response': response})
        content = ''.join('data: ' + json.dumps(event, ensure_ascii=False) + '\n\n' for event in events).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', required=True)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Model)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Codex refuses to create its helper aliases under the OS /tmp directory.
        cache = SOURCE.parent.parent / '.manim-studio-capture-smoke'
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='native-', dir=cache) as directory:
            root = Path(directory).resolve()
            connect(root)
            hooks = json.loads((root / '.codex' / 'hooks.json').read_text())['hooks']
            assert set(hooks) == set(HOOKS)
            for groups in hooks.values():
                for group in groups:
                    for handler in group['hooks']:
                        assert handler['statusMessage'] == MARKER
                        assert 'manim_studio.research_cli' in handler['command']
            # Local project trust is confined to this fresh, disposable project.
            config = root / '.codex' / 'config.toml'
            config.write_text(f'[projects.{json.dumps(str(root))}]\ntrust_level = "trusted"\n')
            port = server.server_address[1]
            command = [args.codex, '--no-daemon', 'exec', '--ignore-user-config', '--skip-git-repo-check',
                       '--dangerously-bypass-hook-trust', '--sandbox', 'read-only', '--json',
                       '-C', str(root), '-c', 'model_provider="capture_mock"',
                       '-c', f'projects.{json.dumps(str(root))}.trust_level="trusted"',
                       '--disable', 'plugins', '--disable', 'apps', '--disable', 'remote_plugin',
                       '--disable', 'code_mode_host', '--disable', 'shell_snapshot',
                       '-c', 'cli_auth_credentials_store="file"',
                       '-c', 'model="mock-capture"', '-c', 'web_search="disabled"',
                       '-c', 'model_providers.capture_mock={name="Local capture test",'
                       f'base_url="http://127.0.0.1:{port}/v1",wire_api="responses",'
                       'requires_openai_auth=false,supports_websockets=false,'
                       'request_max_retries=0,stream_max_retries=0,stream_idle_timeout_ms=5000}',
                       'Test the example, then explain its failure. No other work.']
            try:
                # Give the test client its own application state/auth store; the
                # user's active Codex database and credentials must not be opened.
                test_environment = dict(os.environ, PYTHONPATH=str(SOURCE),
                                        NO_PROXY='127.0.0.1,localhost', no_proxy='127.0.0.1,localhost')
                test_state = root / 'codex-test-state'
                test_state.mkdir()
                test_environment['CODEX_HOME'] = str(test_state)
                # Do not attach this test to the caller's remote executor/thread.
                preserved = {'CODEX_HOME', 'CODEX_NETWORK_PROXY_ACTIVE', 'CODEX_NETWORK_ALLOW_LOCAL_BINDING',
                             'CODEX_SANDBOX_NETWORK_DISABLED', 'CODEX_PROXY_CERT'}
                for key in list(test_environment):
                    if key.startswith('CODEX_') and key not in preserved:
                        test_environment.pop(key)
                test_environment['RUST_LOG'] = 'warn'
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, encoding='utf-8', env=test_environment,
                    start_new_session=os.name != 'nt')
                try:
                    stdout, stderr = process.communicate('', timeout=30)
                except subprocess.TimeoutExpired:
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                    stdout, stderr = process.communicate(timeout=5)
                    raise subprocess.TimeoutExpired(command, 30, output=stdout.encode(), stderr=stderr.encode())
                result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired as exc:
                print('Mock requests:', Model.calls, file=sys.stderr)
                print('Capture status:', CodexCapture(root).status(), file=sys.stderr)
                print((exc.stdout or b'')[-6000:], file=sys.stderr)
                print((exc.stderr or b'')[-12000:], file=sys.stderr)
                raise SystemExit('Native Codex initialization timed out before capture could be verified.') from None
            status = CodexCapture(root).status()
            with sqlite3.connect(root / '.manim-studio' / 'research' / 'events.sqlite3') as db:
                events = [dict(type=r[0], prompt_id=r[1], payload=json.loads(r[2]))
                          for r in db.execute('SELECT type,prompt_id,payload FROM events ORDER BY seq')]
            counts = {name: sum(e['type'] == name for e in events)
                      for name in ('prompt.recorded', 'model.responded', 'action.started',
                                   'action.finished', 'capture.gap')}
            print(json.dumps({'codex_exit': result.returncode, 'mock_model_requests': Model.calls,
                              'counts': counts, 'status': status}, ensure_ascii=False, indent=2))
            if result.returncode or not all(counts[n] for n in (
                    'prompt.recorded', 'model.responded', 'action.started', 'action.finished')):
                # CLI diagnostics contain only this synthetic test conversation.
                print(result.stderr[-8000:], file=sys.stderr)
                print(result.stdout[-8000:], file=sys.stderr)
                raise SystemExit('Native Codex capture smoke failed')
            responses = [e['payload']['text'] for e in events if e['type'] == 'model.responded']
            assert 'Checking the example.' in responses, responses
            assert 'The example failed as expected. הנה הסבר.' in responses, responses
            assert len(responses) == 2, responses
            assert not counts['capture.gap'], [e for e in events if e['type'] == 'capture.gap']
            print('Native Codex hook capture smoke passed (local fake model, no credentials).')
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
