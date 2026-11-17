"""SDK transport replay of the supplied skill, explicitly not a real-model quality test."""
import asyncio
import json
import re

import httpx
from agents import OpenAIChatCompletionsModel
from openai import AsyncAzureOpenAI

from agent_server.evaluation import REFERENCE_SKILL, run_case
from jira_agent.adapter import RunContext, execute
from jira_agent.testing import FakeJira
from jira_agent.tools import ToolContext, load_tools


def test_reference_issue_exposes_actual_project_instead_of_guessing_prefix():
    jira = FakeJira(issues={'WEST1-14597': {'project': {'key': 'ACTUAL', 'name': 'Actual project'}}})
    result = execute(load_tools()['jira_get_issue'], RunContext(ToolContext(jira=jira), b'fixture', ''),
                     {'issue_key': 'WEST1-14597'})
    assert result['project']['key'] == 'ACTUAL'


def test_reference_skill_sdk_flow_preserves_values_through_approval_and_replay():
    calls = []
    args = {'project': 'WEST1', 'summary': 'Demo mit Mathias test ticket', 'issue_type': 'Task',
            'assignee': '@me', 'description': 'Cariad bringt Ideen auf den Weg,\nGemeinsam wird aus Zukunft ein Beleg.'}
    def handle(request):
        body = json.loads(request.content); calls.append(body)
        # Every model round, including approval, receives the complete active skill.
        assert REFERENCE_SKILL['anleitung'] in body['messages'][0]['content']
        messages = body['messages']
        last = max(i for i, m in enumerate(messages) if m['role'] == 'user')
        after = [json.loads(m['content']) for m in messages[last+1:] if m['role'] == 'tool']
        text = messages[last]['content']
        if after and (after[-1].get('status') == 'BESTAETIGUNG_NOETIG' or after[-1].get('key', '').startswith('WEST1-14598')):
            out = after[-1]
            content = 'Confirm with yes ' + out['code'] if 'code' in out else 'Created ' + out['key']
            message, finish = {'role': 'assistant', 'content': content}, 'stop'
        else:
            approval = re.fullmatch(r'yes ([A-F0-9]{6})', text)
            if approval:
                name, params = 'jira_create_issue', {**args, 'confirmation_code': approval.group(1)}
            elif not after:
                name, params = 'jira_get_issue', {'issue_key': 'WEST1-14597'}
            elif len(after) == 1:
                name, params = 'jira_list_issue_types', {'project': after[0]['project']['key']}
            elif len(after) == 2:
                name, params = 'jira_get_create_fields', {'project': 'WEST1', 'issue_type_id': '10001'}
            else:
                name, params = 'jira_create_issue', args
            message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'fixture_call_' + str(len(calls)),
                        'type': 'function', 'function': {'name': name, 'arguments': json.dumps(params)}}]}
            finish = 'tool_calls'
        return httpx.Response(200, json={'id': 'fixture', 'object': 'chat.completion', 'created': 0,
             'model': 'fixture', 'choices': [{'index': 0, 'message': message, 'finish_reason': finish}],
             'usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            c = AsyncAzureOpenAI(api_key='fixture', azure_endpoint='https://example.openai.azure.com',
                                 api_version='2024-12-01-preview', http_client=http, max_retries=0)
            result = await run_case('reference_test_skill', OpenAIChatCompletionsModel(model='fixture', openai_client=c))
            assert result['passed'], result
            assert result['metrics']['llm_calls'] == len(calls)
            assert result['metrics']['input_tokens'] == len(calls) * 10
    asyncio.run(run())
