"""Exercise the installed OpenAI SDK with synthetic HTTP replies and virtual waits."""
import asyncio

import httpx
import pytest
from openai import APIStatusError, RateLimitError

from jira_agent.model_client import BoundedAzureClient
from jira_agent.performance import measure_run


def response(status=200, delay=None):
    return httpx.Response(status, headers={} if delay is None else {'retry-after': str(delay)}, json={
        'id': 'fixture', 'object': 'chat.completion', 'created': 0, 'model': 'fixture',
        'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'OK'}, 'finish_reason': 'stop'}],
        **({'error': {'message': 'Synthetic service failure'}} if status != 200 else {}),
    })


def client(http, budget=30):
    return BoundedAzureClient(api_key='fixture-only', azure_endpoint='https://example.openai.azure.com',
                              api_version='2024-12-01-preview', max_retries=2,
                              retry_wait_seconds=budget, http_client=http)


async def ask(c):
    return await c.chat.completions.create(model='fixture', messages=[{'role': 'user', 'content': 'Test'}])


def test_long_retry_after_fails_promptly_instead_of_sleeping_or_retrying(monkeypatch):
    requests, sleeps = [], []
    async def sleep(delay): sleeps.append(delay)
    monkeypatch.setattr('jira_agent.model_client.asyncio.sleep', sleep)
    def handle(request):
        requests.append(request)
        return response(429, 60)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http, client(http) as c:
            with measure_run() as metrics:
                with pytest.raises(RateLimitError): await ask(c)
            assert metrics.counters['azure_retry_budget_exhausted'] == 1
    asyncio.run(run())
    assert len(requests) == 1 and not sleeps


def test_wait_budget_is_shared_across_model_rounds_in_one_run(monkeypatch):
    replies = iter([response(429, 15), response(), response(429, 15), response(), response(429, 15)])
    sleeps, requests = [], []
    async def sleep(delay): sleeps.append(delay)
    monkeypatch.setattr('jira_agent.model_client.asyncio.sleep', sleep)
    def handle(request):
        requests.append(request)
        return next(replies)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http, client(http) as c:
            await ask(c); await ask(c)
            with pytest.raises(RateLimitError): await ask(c)
    asyncio.run(run())
    assert sleeps == [15, 15] and len(requests) == 5


@pytest.mark.parametrize('status', [400, 401, 403])
def test_permanent_model_errors_are_not_retried(status):
    requests = []
    def handle(request):
        requests.append(request)
        return response(status)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http, client(http) as c:
            with pytest.raises(APIStatusError): await ask(c)
    asyncio.run(run())
    assert len(requests) == 1


def test_retry_count_is_bounded_when_a_service_keeps_throttling(monkeypatch):
    requests, sleeps = [], []
    async def sleep(delay): sleeps.append(delay)
    monkeypatch.setattr('jira_agent.model_client.asyncio.sleep', sleep)
    def handle(request):
        requests.append(request)
        return response(429, 1)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http, client(http) as c:
            with pytest.raises(RateLimitError): await ask(c)
    asyncio.run(run())
    assert len(requests) == 3 and sleeps == [1, 1]


def test_cancelling_backoff_stops_the_sdk_without_another_attempt(monkeypatch):
    requests = []
    async def run():
        entered = asyncio.Event()
        async def sleep(delay):
            entered.set()
            await asyncio.Future()
        monkeypatch.setattr('jira_agent.model_client.asyncio.sleep', sleep)
        def handle(request):
            requests.append(request)
            return response(429, 1)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http, client(http) as c:
            task = asyncio.create_task(ask(c))
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    asyncio.run(run())
    assert len(requests) == 1
