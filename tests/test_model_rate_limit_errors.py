"""Final 429 errors preserve service identity and useful wait hints without raw response text."""
import asyncio
import json

import httpx
import pytest
from openai import RateLimitError

from jira_agent.model_client import BoundedAzureClient


@pytest.mark.parametrize('headers,code,expected', [
    ({'retry-after': '45'}, 'rate_limit_exceeded', 'Wait about 45 seconds'),
    ({'retry-after-ms': '1500'}, 'rate_limit_exceeded', 'Wait about 2 seconds'),
    ({}, 'rate_limit_exceeded', 'Wait a moment'),
    ({'retry-after': 'NaN'}, 'rate_limit_exceeded', 'Wait a moment'),
    ({'retry-after': '-1'}, 'rate_limit_exceeded', 'Wait a moment'),
    ({}, 'insufficient_quota', 'no available quota'),
    ({}, 'billing_hard_limit_reached', 'no available quota'),
])
def test_service_error_is_actionable_and_sanitized(headers, code, expected):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(429, headers=headers, json={'error': {'code': code,
            'message': 'private-fixture-service-message', 'internal': 'private-fixture-value'}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            async with BoundedAzureClient(api_key='fixture-only', azure_endpoint='https://example.openai.azure.com',
                    api_version='2024-12-01-preview', http_client=http, max_retries=0) as client:
                with pytest.raises(RateLimitError) as failure:
                    await client.chat.completions.create(model='fixture', messages=[{'role': 'user', 'content': 'Test'}])
                error = failure.value
                assert error.status_code == 429 and expected in str(error)
                assert str(error).startswith('The AI model service ')
                assert 'private-fixture' not in str(error) + json.dumps(error.body)
                assert 'Jira' not in str(error)  # This error makes no assertion about action outcomes.
    asyncio.run(run())
    assert len(requests) == 1
