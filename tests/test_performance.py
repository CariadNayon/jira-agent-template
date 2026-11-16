import asyncio
from contextlib import asynccontextmanager
import json
import logging
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from agents import Agent, OpenAIChatCompletionsModel, Runner
from openai import AsyncAzureOpenAI

from jira_agent.adapter import RunContext, build_function_tools
from jira_agent.connections import close_connections, install_connection_lifecycle
from jira_agent.model_input import make_run_config
from jira_agent.performance import PerformanceHooks, measure_run
from jira_agent.testing import FakeJira
from jira_agent.tools import ToolContext


def test_real_sdk_counts_model_rounds_tools_and_tokens_without_logging_content(caplog):
    calls = []
    secret_text = 'PRIVATE-TICKET-DESCRIPTION'

    def transport(request):
        calls.append(json.loads(request.content))
        message = ({'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': 'call-1', 'type': 'function', 'function': {
                'name': 'jira_get_issue', 'arguments': '{"issue_key":"ABC-1"}'}}]}
                   if len(calls) == 1 else {'role': 'assistant', 'content': secret_text})
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 0,
            'model': 'test', 'choices': [{'index': 0, 'message': message,
                'finish_reason': 'tool_calls' if len(calls) == 1 else 'stop'}],
            'usage': {'prompt_tokens': 8, 'completion_tokens': 2, 'total_tokens': 10,
                      'prompt_tokens_details': {'cached_tokens': 4}}})

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            client = AsyncAzureOpenAI(api_key='fixture-only', azure_endpoint='https://example.openai.azure.com',
                                     api_version='2024-12-01-preview', http_client=http, max_retries=0)
            context = RunContext(ToolContext(jira=FakeJira(issues={'ABC-1': {'description': secret_text}})), b'secret', '')
            agent = Agent(name='Test', model=OpenAIChatCompletionsModel(model='test', openai_client=client),
                          tools=build_function_tools(context.tool_ctx))
            with measure_run() as metrics:
                hooks = PerformanceHooks(metrics)
                result = await Runner.run(agent, [{'role':'user','content':secret_text}], context=context,
                                          hooks=hooks, run_config=make_run_config(tracing_disabled=True))
                hooks.finish()
                assert result.final_output == secret_text
        return metrics

    with caplog.at_level(logging.INFO, logger='jira_agent.performance'):
        metrics = asyncio.run(check())
    assert metrics.counters['llm_calls'] == 2 and metrics.counters['tool_calls'] == 1
    assert metrics.counters['tool_jira_get_issue_calls'] == 1
    assert metrics.counters['tool_jira_get_issue_ms'] >= 0
    assert metrics.counters['input_tokens'] == 16 and metrics.counters['output_tokens'] == 4
    assert metrics.counters['cached_input_tokens'] == 8
    records = [r.message for r in caplog.records if r.name == 'jira_agent.performance']
    assert len(records) == 1
    assert all(value not in records[0] for value in (secret_text, 'fixture-only', 'ABC-1'))
    assert json.loads(records[0])['outcome'] == 'completed'


def test_cancelled_run_includes_incomplete_model_wait_without_exception_text(caplog):
    async def check():
        with pytest.raises(asyncio.CancelledError):
            with measure_run() as metrics:
                hooks = PerformanceHooks(metrics)
                await hooks.on_llm_start(None, None, 'PRIVATE', [])
                try:
                    raise asyncio.CancelledError('PRIVATE')
                finally:
                    hooks.finish()
    with caplog.at_level(logging.INFO, logger='jira_agent.performance'):
        asyncio.run(check())
    data = json.loads(next(r.message for r in caplog.records if r.name == 'jira_agent.performance'))
    assert data['outcome'] == 'cancelled' and data['unfinished_llm_calls'] == 1
    assert 'PRIVATE' not in json.dumps(data)


def test_connection_cleanup_preserves_the_existing_server_lifespan(monkeypatch):
    events = []
    @asynccontextmanager
    async def previous(app):
        events.append('startup')
        yield {'existing': True}
        events.append('shutdown')

    async def close():
        events.append('connections_closed')
    monkeypatch.setattr('jira_agent.connections.close_connections', close)
    app = FastAPI(lifespan=previous)
    install_connection_lifecycle(app)
    with TestClient(app):
        events.append('request')
    assert events == ['startup', 'request', 'shutdown', 'connections_closed']


@pytest.mark.parametrize('owned', [True, False])
def test_prepared_run_respects_client_ownership_and_measures_setup_on_failure(monkeypatch, caplog, owned):
    import agent_server.execution as execution
    closed = []
    class Client:
        async def close(self):
            closed.append(True)
    client = Client()
    model = SimpleNamespace(_client=client)
    if owned:
        model._jira_agent_client = client
    agent = SimpleNamespace(model=model, instructions='Rules', tools=[])
    monkeypatch.setattr(execution, 'prepare', lambda *args: (agent, object()))
    async def check():
        try:
            with pytest.raises(ValueError):
                async with execution.prepared_run({}, [], 'test'):
                    raise ValueError('PRIVATE-FAILURE')
        finally:
            await close_connections()
    with caplog.at_level(logging.INFO, logger='jira_agent.performance'):
        asyncio.run(check())
    assert closed == ([True] if owned else [])
    record = next(r.message for r in caplog.records if r.name == 'jira_agent.performance')
    data = json.loads(record)
    assert data['outcome'] == 'error' and data['prepare_ms'] >= 0
    assert 'PRIVATE-FAILURE' not in record


def test_team_skill_cache_reuses_parse_but_refreshes_changes_and_copies_results(tmp_path, monkeypatch):
    from jira_agent import skills
    path = tmp_path / 'cached-skill.md'
    path.write_text('---\nname: cached-skill\ndescription: First\n---\nFirst instructions')
    parses = []
    original = skills.parse_skill
    def parse(*args):
        parses.append(True)
        return original(*args)
    monkeypatch.setattr(skills, 'parse_skill', parse)
    first = skills.team_skills(tmp_path)
    first['cached-skill']['anleitung'] = 'MUTATED'
    assert skills.team_skills(tmp_path)['cached-skill']['anleitung'] == 'First instructions'
    assert len(parses) == 1
    path.write_text('---\nname: cached-skill\ndescription: Second description\n---\nNew instructions')
    assert skills.team_skills(tmp_path)['cached-skill']['anleitung'] == 'New instructions'
    assert len(parses) == 2
