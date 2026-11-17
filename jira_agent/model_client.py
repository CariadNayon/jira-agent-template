"""SDK retries with a cumulative wait limit for one agent run; no Jira action replay."""
import asyncio
import math
import time

from openai import AsyncAzureOpenAI


class ModelRetryBudgetExceeded(RuntimeError):
    pass


class BoundedAzureClient(AsyncAzureOpenAI):
    def __init__(self, *, retry_wait_seconds: float = 30, **kwargs):
        if not math.isfinite(retry_wait_seconds) or retry_wait_seconds < 0:
            raise ValueError('Model retry wait budget must be finite and nonnegative.')
        super().__init__(**kwargs)
        self._retry_wait_remaining = retry_wait_seconds

    async def _sleep_for_retry(self, *, retries_taken, max_retries, options, response):
        # Keep the SDK's Retry-After parsing, backoff and retry classification.
        # This narrow SDK hook is covered with real-client MockTransport tests.
        delay = self._calculate_retry_timeout(max_retries - retries_taken, options,
                                              response.headers if response is not None else None)
        from jira_agent.performance import record_retry_wait
        if delay > self._retry_wait_remaining:
            record_retry_wait(0, exhausted=True)
            if response is not None:
                raise self._make_status_error_from_response(response)
            raise ModelRetryBudgetExceeded('The model service is unavailable and the retry wait budget is exhausted. Please try again later.')
        self._retry_wait_remaining -= delay
        started = time.perf_counter()
        try:
            await asyncio.sleep(delay)
        finally:
            record_retry_wait(time.perf_counter() - started)
