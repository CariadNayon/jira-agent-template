"""Chat debug log: masking, recording of requests and errors, owner-only download and size limits."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_server.execution as execution
import jira_agent.web as web
from jira_agent import chatlog
from jira_agent.connections import close_connections
from jira_agent.performance import Performance
from jira_agent.state import logout, user_state

ALICE, BOB = 'alice@example.test', 'bob@example.test'
SECRET = 'sk-test-0123456789abcdef'


class Item:
    def __init__(self, data):
        self.data = data

    def to_input_item(self):
        return self.data


def run_result(*items):
    return SimpleNamespace(new_items=[Item(i) for i in items])


@pytest.fixture(autouse=True)
def clean():
    for user in (ALICE, BOB, 'local'):
        logout(user)
    yield
    for user in (ALICE, BOB, 'local'):
        logout(user)


def agent(prompt='You are a test agent.'):
    return SimpleNamespace(instructions=prompt, model=SimpleNamespace(model='gpt-test', _client=None),
                           tools=[SimpleNamespace(name='jira_get_issue'), SimpleNamespace(name='export_file')])


def headers(email=ALICE, token='obo-token-12345678'):
    return {'x-forwarded-email': email, 'x-forwarded-access-token': token}


def record(chat='chat-1', email=ALICE, text='Show ABC-1', result=None, error=None, prompt='You are a test agent.'):
    recorder = chatlog.start(headers(email), chat, [{'role': 'user', 'content': text}])
    recorder.set_agent(agent(prompt))
    recorder.finish(Performance(), result, error)


def test_redaction_masks_secrets_tokens_and_image_data_and_cuts_long_values():
    text = ('Authorization: Bearer abcdefghijklmnop1234 api_key="XYZ12345678" jira_token=abc12345 '
            f'known {SECRET} img data:image/png;base64,{"A" * 200} end')
    cleaned = chatlog.redact(text, [SECRET])
    for leaked in ('abcdefghijklmnop1234', 'XYZ12345678', 'abc12345', SECRET, 'AAAAAAAAAA'):
        assert leaked not in cleaned
    assert 'binary data omitted' in cleaned and cleaned.count('[redacted]') >= 3
    assert chatlog.redact('ordinary ticket text ABC-1: password reset') == 'ordinary ticket text ABC-1: password reset'
    long = chatlog.redact('x' * (chatlog.MAX_FIELD_CHARS + 50))
    assert long.endswith('[... cut: 50 more characters]')


def test_items_are_formatted_readably():
    f = lambda item: chatlog.format_item(item, [])
    assert f({'type': 'function_call', 'name': 'jira_get_issue', 'arguments': '{"issue_key":"ABC-1"}'}) == \
        '[tool call] jira_get_issue  args: {"issue_key":"ABC-1"}'
    assert f({'type': 'function_call_output', 'output': '{"key":"ABC-1"}'}) == '[tool result] {"key":"ABC-1"}'
    assert f({'type': 'message', 'role': 'assistant',
              'content': [{'type': 'output_text', 'text': 'Hello'}, {'type': 'output_text', 'text': 'World'}]}) == \
        '[assistant] Hello\nWorld'
    assert f({'type': 'reasoning', 'summary': ['private thoughts']}) == '[reasoning] (not recorded)'
    assert f({'type': 'function_call_output', 'output': [{'type': 'input_text', 'text': 'PDF page 1'}]}) == \
        '[tool result] [{"type": "input_text", "text": "PDF page 1"}]'
    assert f('odd').startswith('[item]')


def test_a_request_is_logged_with_prompt_tools_results_answer_and_timings():
    result = run_result({'type': 'function_call', 'name': 'jira_get_issue', 'arguments': '{"issue_key":"ABC-1"}'},
                        {'type': 'function_call_output', 'output': '{"key":"ABC-1","summary":"Brake"}'},
                        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'ABC-1 is about brakes.'}]})
    record(text='Show ABC-1', result=result, prompt='Rules.\nThe user invoked the skill /triage')
    text, chat = chatlog.render(user_state(ALICE), ALICE, 'chat-1')
    assert chat == 'chat-1' and text.startswith('Jira Agent chat log')
    for expected in ('chat id: chat-1', 'user: alice@example.test', '=== Request 1 |', 'outcome: completed',
                     'model: gpt-test', 'tools offered: jira_get_issue, export_file', 'invoked the skill /triage',
                     '[user] Show ABC-1', '[tool call] jira_get_issue', '[tool result] {"key":"ABC-1"',
                     '[assistant] ABC-1 is about brakes.', '[performance] {', 'Check the file before you share it'):
        assert expected in text, expected
    record(text='And ABC-2?', result=run_result())
    assert '=== Request 2 |' in chatlog.render(user_state(ALICE), ALICE, 'chat-1')[0]


def test_errors_are_logged_with_their_text_but_secrets_are_masked():
    user_state(ALICE).creds['jira_token'] = SECRET
    error = RuntimeError(f"Error code: 429 - rate limit exceeded for key {SECRET} Authorization: Bearer abcdefghijklmnop1234")
    record(text=f'my token is {SECRET}', error=error)
    text = chatlog.render(user_state(ALICE), ALICE, 'chat-1')[0]
    assert 'outcome: error' in text and '[error] RuntimeError: Error code: 429 - rate limit exceeded' in text
    assert SECRET not in text and 'abcdefghijklmnop1234' not in text and 'obo-token-12345678' not in text
    cancelled = chatlog.start(headers(), 'chat-2', [{'role': 'user', 'content': 'hi'}])
    cancelled.finish(Performance(), None, asyncio.CancelledError())
    assert 'outcome: cancelled' in chatlog.render(user_state(ALICE), ALICE, 'chat-2')[0]


def test_chats_are_separate_per_user_and_the_latest_is_the_default():
    record('chat-1', ALICE, 'first')
    record('chat-2', ALICE, 'second')
    record('chat-1', BOB, 'bobs private text')
    assert '[user] first' in chatlog.render(user_state(ALICE), ALICE, 'chat-1')[0]
    latest, chat = chatlog.render(user_state(ALICE), ALICE)
    assert chat == 'chat-2' and '[user] second' in latest
    assert 'bobs private text' not in latest and 'bobs private text' not in chatlog.render(user_state(ALICE), ALICE, 'chat-1')[0]
    assert chatlog.render(user_state(ALICE), ALICE, 'unknown-chat') is None
    assert chatlog.render(user_state('nobody@example.test'), 'nobody@example.test') is None


def test_size_limits_drop_the_oldest_requests_and_the_least_recent_chats(monkeypatch):
    monkeypatch.setattr(chatlog, 'MAX_CHARS_PER_CHAT', 3000)
    for i in range(6):
        record('big', text=f'request-{i} ' + 'x' * 1200)
    text = chatlog.render(user_state(ALICE), ALICE, 'big')[0]
    assert 'request-5' in text and 'request-0' not in text
    assert 'Requests recorded: 6' in text and 'oldest were dropped' in text
    monkeypatch.setattr(chatlog, 'MAX_CHARS_PER_CHAT', 1_500_000)
    for i in range(chatlog.MAX_CHATS + 2):
        record(f'chat-{i}')
    kept = list(user_state(ALICE).chat_logs)
    assert len(kept) == chatlog.MAX_CHATS and 'chat-0' not in kept and f'chat-{chatlog.MAX_CHATS + 1}' in kept


def test_no_identity_means_no_recording_in_the_deployed_app(monkeypatch):
    monkeypatch.setenv('DATABRICKS_APP_NAME', 'agent-jira-v2')
    assert chatlog.start({}, 'chat-1', []) is None
    monkeypatch.delenv('DATABRICKS_APP_NAME')
    assert chatlog.start({}, 'chat-1', []) is not None      # local development uses the shared "local" user


def test_prepared_run_records_results_failures_and_never_breaks_the_request(monkeypatch):
    monkeypatch.setattr(execution, 'prepare', lambda *args: (agent(), object()))

    async def good():
        async with execution.prepared_run(headers(), [{'role': 'user', 'content': 'Show ABC-1'}], 'run-1') as (_, _, hooks):
            hooks.chat_result = run_result({'type': 'message', 'role': 'assistant',
                                            'content': [{'type': 'output_text', 'text': 'Done.'}]})
        with pytest.raises(ValueError):
            async with execution.prepared_run(headers(), [{'role': 'user', 'content': 'Fail now'}], 'run-2') as (_, _, hooks):
                raise ValueError('model exploded')
        await close_connections()
    asyncio.run(good())
    ok = chatlog.render(user_state(ALICE), ALICE, 'run-1')[0]
    assert '[user] Show ABC-1' in ok and '[assistant] Done.' in ok and 'outcome: completed' in ok
    failed = chatlog.render(user_state(ALICE), ALICE, 'run-2')[0]
    assert 'outcome: error' in failed and '[error] ValueError: model exploded' in failed

    def broken(*args):
        raise PermissionError('no access')
    monkeypatch.setattr(execution, 'prepare', broken)
    monkeypatch.setattr(chatlog.Recorder, 'finish', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('log failure')))

    async def prepare_fails():
        with pytest.raises(PermissionError):         # the original error, not the logging one
            async with execution.prepared_run(headers(), [], 'run-3'):
                pass
        await close_connections()
    try:
        asyncio.run(prepare_fails())
    except RuntimeError:
        pytest.fail('a logging failure must not replace the request error')


@pytest.fixture
def client():
    app = FastAPI()
    web.install(app)
    return lambda email: TestClient(app, headers={'x-forwarded-email': email, 'x-forwarded-access-token': 't'})


def _sdk_run(streaming: bool, fail_second_call: bool = False):
    """Run the real Agents SDK against a scripted model: one tool call, then the answer (or a 429)."""
    import json as _json
    import httpx
    from agents import Agent, OpenAIChatCompletionsModel, Runner
    from openai import AsyncAzureOpenAI, RateLimitError
    from jira_agent.adapter import RunContext, build_function_tools
    from jira_agent.model_input import make_run_config
    from jira_agent.testing import FakeJira
    from jira_agent.tools import ToolContext

    calls = []
    base = {'id': 'fixture', 'object': 'chat.completion.chunk', 'created': 0, 'model': 'fixture'}
    tool_call = {'id': 'call-1', 'type': 'function', 'function': {'name': 'jira_get_issue',
                                                                    'arguments': '{"issue_key":"ABC-1"}'}}

    def transport(request):
        calls.append(1)
        first = len(calls) == 1
        if not first and fail_second_call:
            return httpx.Response(429, json={'error': {'message': 'Your requests exceeded the token rate limit',
                                                        'code': 'rate_limit_exceeded'}})
        if streaming:
            if first:
                chunks = [{**base, 'choices': [{'index': 0, 'delta': {'role': 'assistant',
                           'tool_calls': [{**tool_call, 'index': 0}]}, 'finish_reason': None}]},
                          {**base, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}]}]
            else:
                chunks = [{**base, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': 'It is about brakes.'},
                           'finish_reason': None}]}, {**base, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}]
            body = ''.join('data: ' + _json.dumps(c) + '\n\n' for c in chunks) + 'data: [DONE]\n\n'
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=body.encode())
        message = ({'role': 'assistant', 'content': None, 'tool_calls': [tool_call]} if first
                   else {'role': 'assistant', 'content': 'It is about brakes.'})
        return httpx.Response(200, json={'id': 'x', 'object': 'chat.completion', 'created': 0, 'model': 'x',
            'choices': [{'index': 0, 'message': message, 'finish_reason': 'tool_calls' if first else 'stop'}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})

    async def check():
        error = None
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            client = AsyncAzureOpenAI(api_key='fixture-only', azure_endpoint='https://example.openai.azure.com',
                                      api_version='2024-12-01-preview', http_client=http, max_retries=0)
            context = RunContext(ToolContext(jira=FakeJira(issues={'ABC-1': {'summary': 'Brake noise'}})), b'secret', '')
            sdk_agent = Agent(name='Test', instructions='Be brief.', tools=build_function_tools(context.tool_ctx),
                              model=OpenAIChatCompletionsModel(model='fixture', openai_client=client))
            messages = [{'role': 'user', 'content': 'What is ABC-1 about?'}]
            try:
                if streaming:
                    result = Runner.run_streamed(sdk_agent, input=messages, context=context,
                                                 run_config=make_run_config(tracing_disabled=True))
                    async for _ in result.stream_events():
                        pass
                else:
                    result = await Runner.run(sdk_agent, messages, context=context,
                                              run_config=make_run_config(tracing_disabled=True))
            except Exception as exc:
                error = exc
                result = None if not streaming else result
        return result, error
    return asyncio.run(check())


@pytest.mark.parametrize('streaming', [False, True])
def test_real_sdk_run_shows_prompt_tool_call_result_and_answer(streaming):
    result, error = _sdk_run(streaming)
    assert error is None
    record(text='What is ABC-1 about?', result=result, prompt='Be brief.')
    text = chatlog.render(user_state(ALICE), ALICE, 'chat-1')[0]
    assert '[tool call] jira_get_issue  args: {"issue_key":"ABC-1"}' in text
    assert '[tool result]' in text and 'Brake noise' in text
    assert '[assistant] It is about brakes.' in text
    assert text.index('[tool call]') < text.index('[tool result]') < text.index('[assistant]')


@pytest.mark.parametrize('streaming', [False, True])
def test_real_sdk_model_failure_is_logged_with_the_provider_message_and_the_earlier_steps(streaming):
    result, error = _sdk_run(streaming, fail_second_call=True)
    assert error is not None and '429' in str(error)
    record(text='What is ABC-1 about?', result=result, error=error)
    text = chatlog.render(user_state(ALICE), ALICE, 'chat-1')[0]
    assert 'outcome: error' in text and 'RateLimitError' in text and 'rate_limit_exceeded' in text
    if streaming:       # the tool already ran before the model failed: that step must be visible for debugging
        assert '[tool call] jira_get_issue' in text and 'Brake noise' in text


def test_download_endpoint_is_owner_only_and_explains_missing_logs(client):
    alice, bob = client(ALICE), client(BOB)
    empty = alice.get('/jira/api/chatlog?chat_id=chat-1')
    assert empty.status_code == 404 and 'Send a message first' in empty.json()['detail']
    record('chat-1', ALICE, 'alice question')
    done = alice.get('/jira/api/chatlog?chat_id=chat-1')
    assert done.status_code == 200 and 'alice question' in done.text
    assert done.headers['content-type'].startswith('text/plain') and done.headers['cache-control'] == 'private, no-store'
    assert 'attachment; filename="jira-agent-chat-log-' in done.headers['content-disposition']
    assert done.headers['content-disposition'].endswith('.log"')
    assert 'alice question' in alice.get('/jira/api/chatlog').text            # most recent chat without an id
    assert bob.get('/jira/api/chatlog?chat_id=chat-1').status_code == 404       # other users never see it
    assert bob.get('/jira/api/chatlog').status_code == 404
    assert alice.get('/jira/api/chatlog?chat_id=../../x').status_code == 400
    assert alice.get('/jira/api/chatlog', headers={'x-forwarded-email': ''}).status_code == 401
