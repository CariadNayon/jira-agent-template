"""Reproduce three successful metadata reads followed by model throttling, with no mutation."""
import asyncio
import json
from unittest.mock import patch

import httpx
import pytest
from agents import Runner
from openai import RateLimitError

from agent_server.evaluation import REFERENCE_SKILL
from agent_server.utils import process_agent_stream_events
from jira_agent import runtime
from jira_agent.model_client import BoundedAzureClient
from jira_agent.model_gate import QueuedAzureModel, clear_model_gates
from jira_agent.model_input import make_run_config
from jira_agent.state import logout, user_state
from jira_agent.testing import FakeJira


def test_throttle_after_reference_issue_types_and_fields_does_not_restart_or_create():
    owner = 'model-throttle@example.test'
    requests = []
    steps = [
        ('jira_get_issue', {'issue_key': 'WEST1-14597'}),
        ('jira_list_issue_types', {'project': 'WEST1'}),
        ('jira_get_create_fields', {'project': 'WEST1', 'issue_type_id': '10001'}),
    ]
    jira = FakeJira(issues={'WEST1-14597': {}})
    def handle(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) > len(steps):
            return httpx.Response(429, headers={'retry-after': '45'},
                json={'error': {'code': 'rate_limit_exceeded', 'message': 'internal-fixture-message'}})
        name, args = steps[len(requests)-1]
        base = {'id': f'fixture-{len(requests)}', 'object': 'chat.completion.chunk', 'created': 0, 'model': 'fixture'}
        chunks = [
            {**base, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'tool_calls': [{
                'index': 0, 'id': f'call-{len(requests)}', 'type': 'function',
                'function': {'name': name, 'arguments': json.dumps(args)}}]}, 'finish_reason': None}]},
            {**base, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}]},
        ]
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
            content=''.join('data: '+json.dumps(chunk)+'\n\n' for chunk in chunks)+'data: [DONE]\n\n')
    async def check():
        state = user_state(owner)
        state.creds = {'jira_token': 'fixture-only'}
        state.settings = dict(runtime.DEFAULT_SETTINGS)
        state.skills = {'testticket': {**REFERENCE_SKILL, 'name': 'testticket'}}
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
                async with BoundedAzureClient(api_key='fixture-only', azure_endpoint='https://example.openai.azure.com',
                        api_version='2024-12-01-preview', http_client=http, max_retries=2) as client:
                    model = QueuedAzureModel(model='fixture', openai_client=client,
                        endpoint='https://example.openai.azure.com', queue_wait_seconds=30)
                    with patch.object(runtime, 'JiraClient', return_value=jira), patch.object(runtime, 'build_model', return_value=model):
                        messages = [{'role': 'user', 'content': '/testticket bitte erstellen'}]
                        agent, context = runtime.prepare({'x-forwarded-email': owner}, messages, 'throttle-chat')
                        run = Runner.run_streamed(agent, messages, context=context,
                            run_config=make_run_config(tracing_disabled=True), max_turns=8)
                        outputs = []
                        try:
                            with pytest.raises(RateLimitError, match='Wait about 45 seconds'):
                                async for event in process_agent_stream_events(run.stream_events()):
                                    raw = event.model_dump() if hasattr(event, 'model_dump') else event
                                    if raw.get('type') == 'response.output_item.done' and raw.get('item', {}).get('type') == 'function_call_output':
                                        outputs.append(raw['item'])
                        finally:
                            run.cancel()
                        assert len(outputs) == 3
        finally:
            clear_model_gates()
            logout(owner)
    asyncio.run(check())
    assert len(requests) == 4
    assert all(method == 'GET' for method, _, _ in jira.calls)
    assert set(jira.issues) == {'WEST1-14597'}
