"""Real local HTTP sockets: reuse connections without carrying auth or cookies across users."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Barrier, Thread

import pytest

from jira_agent.connections import azure_connection_scope, close_connections, jira_session
from jira_agent.jira_client import JiraClient
from jira_agent.llm import _azure_model
from jira_agent.performance import measure_run


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv('NO_PROXY', '127.0.0.1,localhost')
    records = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def reply(self, value, status=200):
            records.append({'port': self.client_address[1], 'authorization': self.headers.get('Authorization'),
                            'api_key': self.headers.get('api-key'), 'cookie': self.headers.get('Cookie'), 'status': status})
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Set-Cookie', 'private-session=do-not-share; Path=/')
            if status == 429:
                self.send_header('retry-after-ms', '1')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.reply({'name': 'test.user'})

        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            if self.headers.get('api-key') == 'fixture-retry' and not records:
                self.reply({'error': {'message': 'fixture throttle', 'type': 'rate_limit', 'code': '429'}}, 429)
                return
            self.reply({'id': 'test', 'object': 'chat.completion', 'created': 0, 'model': 'test',
                        'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'OK'},
                                     'finish_reason': 'stop'}]})

    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{httpd.server_port}', records
    asyncio.run(close_connections())
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


def test_jira_reuses_tcp_connection_but_supplies_each_users_token(server):
    url, records = server
    with measure_run() as metrics:
        JiraClient(url, 'fixture-user-A').myself()
        JiraClient(url, 'fixture-user-B').myself()
    assert records[0]['port'] == records[1]['port']
    assert [r['authorization'] for r in records] == ['Bearer fixture-user-A', 'Bearer fixture-user-B']
    assert all(r['cookie'] is None for r in records)
    assert metrics.counters['jira_calls'] == 2 and metrics.counters['jira_ms'] > 0
    assert 'Authorization' not in jira_session().headers and not jira_session().cookies


def test_sdk_throttling_retries_are_visible_as_http_attempts(server):
    url, records = server
    async def check():
        try:
            with measure_run() as metrics, azure_connection_scope():
                model = _azure_model('fixture-retry', url, '2024-12-01-preview', 'test')
                model._client.max_retries = 1
                try:
                    await model._client.chat.completions.create(model='test', messages=[{'role':'user','content':'Test'}])
                finally:
                    await model._client.close()
                assert metrics.counters['azure_http_calls'] == 2
                assert metrics.counters['azure_http_status_429'] == 1
                assert metrics.counters['azure_http_status_200'] == 1
        finally:
            await close_connections()
    asyncio.run(check())
    assert [r['status'] for r in records] == [429, 200]


def test_sync_sessions_are_not_shared_between_threads():
    barrier = Barrier(2)
    def session_id():
        session = jira_session()
        barrier.wait(timeout=5)
        return id(session)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(session_id)
        second = executor.submit(session_id)
        assert first.result() != second.result()
    asyncio.run(close_connections())


def test_azure_reuses_tcp_across_closed_sdk_clients_without_sharing_keys_or_cookies(server):
    url, records = server
    async def check():
        try:
            with measure_run() as metrics:
                for key in ('fixture-A', 'fixture-B'):
                    with azure_connection_scope():
                        # Match prepare(), which builds the model in a worker thread.
                        model = await asyncio.to_thread(_azure_model, key, url, '2024-12-01-preview', 'test')
                        try:
                            result = await model._client.chat.completions.create(
                                model='test', messages=[{'role': 'user', 'content': 'Test'}])
                            assert result.choices[0].message.content == 'OK'
                        finally:
                            await model._client.close()
                assert metrics.counters['azure_http_calls'] == 2
        finally:
            await close_connections()
    asyncio.run(check())
    assert records[0]['port'] == records[1]['port']
    assert [r['api_key'] for r in records] == ['fixture-A', 'fixture-B']
    assert all(r['cookie'] is None for r in records)


def test_azure_pools_are_scoped_to_the_event_loop(server):
    url, records = server
    async def request():
        try:
            with azure_connection_scope():
                model = _azure_model('fixture', url, '2024-12-01-preview', 'test')
                try:
                    await model._client.chat.completions.create(model='test', messages=[{'role':'user','content':'Test'}])
                finally:
                    await model._client.close()
        finally:
            await close_connections()
    asyncio.run(request())
    asyncio.run(request())
    assert len(records) == 2 and records[0]['port'] != records[1]['port']
