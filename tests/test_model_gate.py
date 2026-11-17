"""Real Agents SDK calls: shared deployment pressure, bounded waits, cancellation and streams."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from agents import Agent, Runner, RunConfig
from openai import RateLimitError

from jira_agent.model_client import BoundedAzureClient
from jira_agent.model_gate import ModelServiceBusy, QueuedAzureModel, clear_model_gates


def reply():
    return httpx.Response(200, json={'id': 'fixture', 'object': 'chat.completion', 'created': 0,
        'model': 'fixture', 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'OK'}, 'finish_reason': 'stop'}]})


def model(http, key='fixture-A', deployment='fixture', **kwargs):
    client = BoundedAzureClient(api_key=key, azure_endpoint='https://example.openai.azure.com',
        api_version='2024-12-01-preview', http_client=http, max_retries=0)
    return QueuedAzureModel(model=deployment, openai_client=client, endpoint='https://example.openai.azure.com', **kwargs)


async def ask(m, text='Fixture'):
    return await Runner.run(Agent(name='Fixture', instructions='Answer briefly.', model=m), text,
                            run_config=RunConfig(tracing_disabled=True))


def test_same_deployment_serializes_users_without_sharing_credentials():
    active, highest, requests = [0], [0], []
    async def handle(request):
        requests.append((request.headers['api-key'], json.loads(request.content)['messages'][-1]['content']))
        active[0] += 1; highest[0] = max(highest[0], active[0])
        await asyncio.sleep(0.01)
        active[0] -= 1
        return reply()
    async def check():
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
                first, second = model(http, 'fixture-A'), model(http, 'fixture-B')
                await asyncio.gather(ask(first, 'First user'), ask(second, 'Second user'))
        finally:
            clear_model_gates()
    asyncio.run(check())
    assert highest[0] == 1
    assert set(requests) == {('fixture-A', 'First user'), ('fixture-B', 'Second user')}


def test_different_deployments_can_run_in_parallel():
    active, both = [0], None
    async def check():
        nonlocal both
        both = asyncio.Event()
        async def handle(request):
            active[0] += 1
            if active[0] == 2: both.set()
            await asyncio.wait_for(both.wait(), 2)
            return reply()
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
                await asyncio.gather(ask(model(http, deployment='first')), ask(model(http, deployment='second')))
        finally:
            clear_model_gates()
    asyncio.run(check())
    assert active[0] == 2


def test_retry_after_is_shared_and_wait_budget_spans_model_rounds(monkeypatch):
    import jira_agent.model_gate as gate_module
    now, sleeps, calls = [100.0], [], []
    async def sleep(delay):
        sleeps.append(delay); now[0] += delay
    # Virtualize only this module's clock/wait, leaving SDK and asyncio timers unchanged.
    monkeypatch.setattr(gate_module, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(gate_module, 'asyncio', SimpleNamespace(get_running_loop=asyncio.get_running_loop,
        Semaphore=asyncio.Semaphore, timeout=asyncio.timeout, sleep=sleep))
    def handle(request):
        calls.append(request.headers['api-key'])
        if request.headers['api-key'] == 'throttled':
            return httpx.Response(429, headers={'retry-after': '10'}, json={'error': {'code': 'rate_limit_exceeded'}})
        return reply()
    async def check():
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
                first, second = model(http, 'throttled'), model(http, 'other-user', queue_wait_seconds=15)
                with pytest.raises(RateLimitError): await ask(first)
                assert (await ask(second)).final_output == 'OK'
                with pytest.raises(RateLimitError): await ask(first)
                with pytest.raises(ModelServiceBusy, match='wait budget'): await ask(second)
        finally:
            clear_model_gates()
    asyncio.run(check())
    assert sleeps == [10] and calls == ['throttled', 'other-user', 'throttled']


def test_full_queue_rejects_without_another_provider_call():
    calls = []
    async def check():
        entered, release = asyncio.Event(), asyncio.Event()
        async def handle(request):
            calls.append(1); entered.set(); await release.wait(); return reply()
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
                first = asyncio.create_task(ask(model(http, max_pending=0)))
                await asyncio.wait_for(entered.wait(), 2)
                try:
                    with pytest.raises(ModelServiceBusy, match='queue is full'):
                        await ask(model(http, max_pending=0))
                finally:
                    release.set()
                    await first
        finally:
            clear_model_gates()
    asyncio.run(check())
    assert len(calls) == 1


def test_cancelled_waiter_does_not_leak_capacity():
    import jira_agent.model_gate as gate_module
    calls = []
    async def check():
        entered, release = asyncio.Event(), asyncio.Event()
        async def handle(request):
            calls.append(1); entered.set(); await release.wait(); return reply()
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
                first = asyncio.create_task(ask(model(http)))
                await asyncio.wait_for(entered.wait(), 2)
                second = asyncio.create_task(ask(model(http)))
                gate = gate_module._gate(('https://example.openai.azure.com', 'fixture'), 1)
                for _ in range(100):
                    if gate.users == 2: break
                    await asyncio.sleep(0)
                assert gate.users == 2
                second.cancel()
                with pytest.raises(asyncio.CancelledError): await second
                assert gate.users == 1
                release.set(); await first
                assert (await ask(model(http))).final_output == 'OK'
                assert gate.users == 0
        finally:
            clear_model_gates()
    asyncio.run(check())
    assert len(calls) == 2


def test_stream_holds_slot_until_the_model_finishes():
    calls = []
    async def check():
        release, first_text = asyncio.Event(), asyncio.Event()
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                base = {'id': 'fixture', 'object': 'chat.completion.chunk', 'created': 0, 'model': 'fixture'}
                yield ('data: '+json.dumps({**base, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': 'OK'}, 'finish_reason': None}]})+'\n\n').encode()
                await release.wait()
                yield ('data: '+json.dumps({**base, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})+'\n\ndata: [DONE]\n\n').encode()
        def handle(request):
            calls.append(1)
            if json.loads(request.content).get('stream'):
                return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Stream())
            return reply()
        async def read(m):
            run = Runner.run_streamed(Agent(name='Fixture', model=m), 'Fixture', run_config=RunConfig(tracing_disabled=True))
            async for event in run.stream_events():
                if event.type == 'raw_response_event' and event.data.type == 'response.output_text.delta':
                    first_text.set()
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
                first = asyncio.create_task(read(model(http)))
                await asyncio.wait_for(first_text.wait(), 2)
                second = asyncio.create_task(ask(model(http)))
                await asyncio.sleep(0.01)
                assert len(calls) == 1
                release.set()
                await asyncio.wait_for(asyncio.gather(first, second), 2)
        finally:
            clear_model_gates()
    asyncio.run(check())
    assert len(calls) == 2


def test_cancelling_active_model_call_releases_the_slot():
    calls = []
    async def check():
        entered = asyncio.Event()
        async def handle(request):
            calls.append(1)
            if len(calls) == 1:
                entered.set()
                await asyncio.Future()
            return reply()
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
                first = asyncio.create_task(ask(model(http)))
                await asyncio.wait_for(entered.wait(), 2)
                first.cancel()
                with pytest.raises(asyncio.CancelledError): await first
                assert (await asyncio.wait_for(ask(model(http)), 2)).final_output == 'OK'
        finally:
            clear_model_gates()
    asyncio.run(check())
    assert len(calls) == 2


def virtual_cooldown(monkeypatch):
    import jira_agent.model_gate as gate_module
    now, sleeps = [100.0], []
    async def sleep(delay):
        sleeps.append(delay)
        now[0] += delay
    monkeypatch.setattr(gate_module, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(gate_module, 'asyncio', SimpleNamespace(get_running_loop=asyncio.get_running_loop,
        Semaphore=asyncio.Semaphore, timeout=asyncio.timeout, sleep=sleep))
    return sleeps


def transport_reply(message, finish, stream):
    body = {'id': 'fixture', 'object': 'chat.completion', 'created': 0, 'model': 'fixture'}
    if not stream:
        return httpx.Response(200, json={**body, 'choices': [
            {'index': 0, 'message': message, 'finish_reason': finish}]})
    delta = dict(message)
    if delta.get('tool_calls'):
        delta['tool_calls'] = [{**call, 'index': i} for i, call in enumerate(delta['tool_calls'])]
    chunks = [
        {**body, 'object': 'chat.completion.chunk', 'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]},
        {**body, 'object': 'chat.completion.chunk', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}]},
    ]
    return httpx.Response(200, headers={'content-type': 'text/event-stream'},
        content=''.join('data: '+json.dumps(chunk)+'\n\n' for chunk in chunks)+'data: [DONE]\n\n')


@pytest.mark.parametrize('stream', [False, True])
def test_native_retry_after_32_seconds_keeps_approved_jira_write_and_retries_only_model(monkeypatch, stream):
    from jira_agent.adapter import RunContext, build_function_tools, execute
    from jira_agent.testing import FakeJira
    from jira_agent.tools import ToolContext, load_tools
    sleeps = virtual_cooldown(monkeypatch)
    jira, requests, retry_counts = FakeJira(), [], []
    context = RunContext(ToolContext(jira=jira), b'fixture', '')
    args = {'project': 'ABC', 'summary': 'Fixture', 'issue_type': 'Task'}
    code = execute(load_tools()['jira_create_issue'], context, args)['code']
    context.last_user_text = 'yes ' + code
    args['confirmation_code'] = code
    def handle(request):
        payload = json.loads(request.content)
        requests.append(payload)
        retry_counts.append(request.headers.get('x-stainless-retry-count'))
        if len(requests) == 1:
            return transport_reply({'role': 'assistant', 'content': None, 'tool_calls': [{
                'id': 'approved-create', 'type': 'function',
                'function': {'name': 'jira_create_issue', 'arguments': json.dumps(args)}}]}, 'tool_calls', stream)
        # The Jira write has already completed before the final model answer is throttled.
        assert set(jira.issues) == {'ABC-1'}
        if len(requests) == 2:
            return httpx.Response(429, headers={'retry-after': '32'}, json={'error': {'code': 'rate_limit_exceeded'}})
        return transport_reply({'role': 'assistant', 'content': 'Created ABC-1'}, 'stop', stream)
    async def check():
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
                m = model(http)
                m._client.max_retries = 2  # Runner must disable HTTP retries; no retry multiplication.
                agent = Agent(name='Fixture', model=m, model_settings=m._jira_agent_model_settings,
                    tools=build_function_tools(context.tool_ctx))
                config = RunConfig(tracing_disabled=True)
                if stream:
                    run = Runner.run_streamed(agent, context.last_user_text, context=context, run_config=config)
                    async for _ in run.stream_events(): pass
                    assert run.final_output == 'Created ABC-1'
                else:
                    run = await Runner.run(agent, context.last_user_text, context=context, run_config=config)
                    assert run.final_output == 'Created ABC-1'
        finally:
            clear_model_gates()
    asyncio.run(check())
    assert sleeps == [32]
    assert len(requests) == 3 and requests[1] == requests[2]
    assert retry_counts == ['0', '0', '0']
    assert len([c for c in jira.calls if c[0] == 'POST' and c[1] == '/issue']) == 1


@pytest.mark.parametrize('code,headers,expected_calls,expected_sleeps', [
    ('rate_limit_exceeded', {'retry-after': '32'}, 2, [32]),
    ('rate_limit_exceeded', {'retry-after': '90'}, 1, []),
    ('insufficient_quota', {'retry-after': '1'}, 1, []),
    ('rate_limit_exceeded', {'retry-after': '1', 'x-should-retry': 'false'}, 1, []),
])
def test_native_retry_is_bounded_and_respects_provider_veto(monkeypatch, code, headers, expected_calls, expected_sleeps):
    sleeps = virtual_cooldown(monkeypatch)
    calls = []
    def handle(request):
        calls.append(1)
        return httpx.Response(429, headers=headers, json={'error': {'code': code}})
    async def check():
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
                m = model(http)
                with pytest.raises(RateLimitError):
                    await Runner.run(Agent(name='Fixture', model=m, model_settings=m._jira_agent_model_settings),
                        'Fixture', run_config=RunConfig(tracing_disabled=True))
        finally:
            clear_model_gates()
    asyncio.run(check())
    assert len(calls) == expected_calls and sleeps == expected_sleeps


@pytest.mark.parametrize('status', [429, 503])
def test_native_retry_preserves_bounded_sdk_backoff_without_retry_after(monkeypatch, status):
    import jira_agent.model_client as client_module
    sleeps, calls = [], []
    async def sleep(delay): sleeps.append(delay)
    monkeypatch.setattr(client_module, 'asyncio', SimpleNamespace(sleep=sleep))
    def handle(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(status, json={'error': {'code': 'transient'}})
        return reply()
    async def check():
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
                m = model(http)
                result = await Runner.run(Agent(name='Fixture', model=m, model_settings=m._jira_agent_model_settings),
                    'Fixture', run_config=RunConfig(tracing_disabled=True))
                assert result.final_output == 'OK'
        finally:
            clear_model_gates()
    asyncio.run(check())
    assert len(calls) == 2 and len(sleeps) == 1 and 0 < sleeps[0] <= 0.5


def test_native_retry_never_replays_a_stream_after_visible_text():
    calls = []
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            chunk = {'id': 'fixture', 'object': 'chat.completion.chunk', 'created': 0, 'model': 'fixture',
                'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': 'Partial'}, 'finish_reason': None}]}
            yield ('data: '+json.dumps(chunk)+'\n\n').encode()
            response = httpx.Response(429, headers={'retry-after': '1'}, request=httpx.Request('POST', 'https://example.openai.azure.com'))
            raise RateLimitError('Fixture interrupted stream', response=response, body={'code': 'rate_limit_exceeded'})
    def handle(request):
        calls.append(1)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=BrokenStream())
    async def check():
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
                m = model(http)
                run = Runner.run_streamed(Agent(name='Fixture', model=m, model_settings=m._jira_agent_model_settings),
                    'Fixture', run_config=RunConfig(tracing_disabled=True))
                text = []
                with pytest.raises(RateLimitError):
                    async for event in run.stream_events():
                        if event.type == 'raw_response_event' and event.data.type == 'response.output_text.delta':
                            text.append(event.data.delta)
                assert text == ['Partial']
        finally:
            clear_model_gates()
    asyncio.run(check())
    assert calls == [1]
