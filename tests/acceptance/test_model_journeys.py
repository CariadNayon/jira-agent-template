"""Scripted models exercise the live-evaluation harness deterministically, without paid API calls."""
import asyncio
import json
import re

import httpx
from agents import OpenAIChatCompletionsModel
from openai import AsyncAzureOpenAI

from agent_server.evaluation import run_case


def test_sdk_confirmation_replay_journey_creates_exactly_one_fake_ticket():
    calls=[]
    def handle(request):
        body=json.loads(request.content);calls.append(body)
        messages=body['messages'];last=max(i for i,m in enumerate(messages) if m['role']=='user')
        text=messages[last]['content'];after=messages[last+1:]
        outputs=[json.loads(m['content']) for m in after if m['role']=='tool']
        if outputs:
            out=outputs[-1]
            content='Bitte bestätige mit ja '+out['code'] if out.get('status')=='BESTAETIGUNG_NOETIG' else 'Ticket '+out.get('key','ABC-3')+' erstellt.'
            message={'role':'assistant','content':content};finish='stop'
        else:
            args={'project':'ABC','summary':'Akzeptanztest','issue_type':'Task','description':'Test','assignee':'@me'}
            code=re.fullmatch(r'ja ([A-F0-9]{6})',text)
            if code:args['confirmation_code']=code.group(1)
            message={'role':'assistant','content':None,'tool_calls':[{'id':'call_create','type':'function',
                        'function':{'name':'jira_create_issue','arguments':json.dumps(args)}}]};finish='tool_calls'
        return httpx.Response(200,json={'id':'test','object':'chat.completion','created':0,'model':'test',
            'choices':[{'index':0,'message':message,'finish_reason':finish}],
            'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}})
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            client=AsyncAzureOpenAI(api_key='test-only',azure_endpoint='https://example.openai.azure.com',
                                   api_version='2024-12-01-preview',http_client=http,max_retries=0)
            result=await run_case('approval_replay',OpenAIChatCompletionsModel(model='test',openai_client=client))
            assert result['passed'],result
    asyncio.run(check())
    assert len(calls)==6  # proposal, approval and identical retry, each a tool call plus final response


def test_evaluation_listing_is_offline_and_has_product_cases():
    import subprocess,sys
    result=subprocess.run([sys.executable,'-m','agent_server.evaluate_agent','--list'],capture_output=True,text=True,check=True)
    assert 'scan_pdf:' in result.stdout and 'csv_aggregation:' in result.stdout
    assert 'approval_replay:' in result.stdout
    assert 'Vietnamese' not in result.stdout
