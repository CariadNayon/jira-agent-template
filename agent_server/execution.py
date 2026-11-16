"""Common setup, connection lifetime and measurements for both agent endpoints."""
from contextlib import asynccontextmanager
import asyncio
import time

from jira_agent.connections import azure_connection_scope
from jira_agent.performance import PerformanceHooks, measure_run
from jira_agent.runtime import prepare


@asynccontextmanager
async def prepared_run(headers, messages, conversation_id):
    with measure_run() as performance, azure_connection_scope():
        agent = None
        hooks = PerformanceHooks(performance)
        try:
            started = time.perf_counter()
            try:
                agent, context = await asyncio.to_thread(prepare, headers, messages, conversation_id)
            finally:
                performance.add('prepare_ms', (time.perf_counter()-started)*1000)
            performance.add('input_items', len(messages))
            performance.add('instruction_chars', len(agent.instructions))
            performance.add('available_tools', len(agent.tools))
            yield agent, context, hooks
        finally:
            hooks.finish()
            # Close the request's credential-bearing SDK client. Its borrowed transport
            # leaves the credential-free connection pool available to the next request.
            client = getattr(getattr(agent, 'model', None), '_jira_agent_client', None)
            if client is not None:
                await client.close()
