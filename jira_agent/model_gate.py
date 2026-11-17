"""Bound model concurrency and respect shared Azure deployment cooldowns in this worker.

Only deployment identifiers and timing/capacity state are shared, never prompts,
credentials, tool results, user identities or agent runs.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
import math
import threading
import time
from weakref import WeakKeyDictionary

from agents import ModelSettings, OpenAIChatCompletionsModel
from agents.retry import ModelRetrySettings, RetryDecision
from openai import RateLimitError
from openai._models import FinalRequestOptions

from jira_agent.performance import record_model_queue_wait


class ModelServiceBusy(RuntimeError):
    pass


@dataclass(repr=False)
class _Gate:
    capacity: int
    semaphore: asyncio.Semaphore
    users: int = 0
    blocked_until: float = 0


_gates = WeakKeyDictionary()
_registry_lock = threading.Lock()
_MAX_GATES = 128


def clear_model_gates():
    with _registry_lock:
        _gates.pop(asyncio.get_running_loop(), None)


def _gate(key: tuple[str, str], capacity: int) -> _Gate:
    loop = asyncio.get_running_loop()
    with _registry_lock:
        for old_loop in list(_gates):
            if old_loop.is_closed():
                _gates.pop(old_loop, None)
        gates = _gates.setdefault(loop, OrderedDict())
        if key not in gates:
            if len(gates) >= _MAX_GATES:
                evict = next((k for k, g in gates.items() if not g.users and g.blocked_until <= time.monotonic()), None)
                if evict is None:
                    raise ModelServiceBusy('The AI model service is busy. No capacity slot is available; please try again later.')
                gates.pop(evict)
            gates[key] = _Gate(capacity, asyncio.Semaphore(capacity))
        gate = gates[key]
        if gate.capacity != capacity:
            raise ValueError('Model concurrency changed while the app is running. Restart to apply the new limit.')
        gates.move_to_end(key)
        return gate


class QueuedAzureModel(OpenAIChatCompletionsModel):
    def __init__(self, *, endpoint: str, queue_wait_seconds: float = 60, max_inflight: int = 1,
                 max_pending: int = 8, model_retries: int = 2, **kwargs):
        if not math.isfinite(queue_wait_seconds) or queue_wait_seconds < 0:
            raise ValueError('Model queue wait budget must be finite and nonnegative.')
        if not isinstance(max_inflight, int) or max_inflight < 1 or not isinstance(max_pending, int) or max_pending < 0:
            raise ValueError('Model concurrency must be positive and pending capacity nonnegative.')
        super().__init__(**kwargs)
        self._gate_key = (endpoint.rstrip('/').lower(), self.model)
        self._queue_remaining = queue_wait_seconds
        self._max_inflight = max_inflight
        self._max_pending = max_pending
        # Agent identity serialization deep-copies dataclass fields. A function
        # closure stays runtime-only without attempting to copy the HTTP client.
        async def retry_request(context):
            return await self._retry_model_request(context)
        self._jira_agent_model_settings = ModelSettings(retry=ModelRetrySettings(
            max_retries=model_retries, policy=retry_request))

    async def _retry_model_request(self, context):
        # The Agents SDK retries only the rejected model call, retaining prior tool
        # results. Its native replay guards remain authoritative for streaming.
        if context.response_started or context.replay_safety == 'unsafe':
            return False
        if context.provider_advice is None or context.provider_advice.suggested is not True:
            return False
        code = context.normalized.error_code
        if code in ('insufficient_quota', 'billing_hard_limit_reached'):
            return False
        delay = context.normalized.retry_after
        if isinstance(context.error, RateLimitError) and delay is not None and math.isfinite(delay) and delay > 0:
            if delay > self._queue_remaining:
                return False
            # The shared gate owns the cooldown, so the runner must not wait twice.
            return RetryDecision(retry=True, delay=0)
        # Preserve the existing SDK backoff and cumulative budget for transient
        # network/server errors and throttling without Retry-After. The runner
        # disables nested HTTP retries; this is the only backoff for that attempt.
        await self._client._sleep_for_retry(retries_taken=context.attempt - 1,
            max_retries=context.max_retries,
            options=FinalRequestOptions.construct(method='POST', url='/chat/completions'),
            response=getattr(context.error, 'response', None))
        return RetryDecision(retry=True, delay=0)

    @asynccontextmanager
    async def _slot(self):
        gate = _gate(self._gate_key, self._max_inflight)
        if gate.users >= self._max_inflight + self._max_pending:
            record_model_queue_wait(0, exhausted=True)
            raise ModelServiceBusy('The AI model service is busy. The request queue is full; please try again later.')
        gate.users += 1
        acquired = False
        started = time.monotonic()
        try:
            try:
                async with asyncio.timeout(self._queue_remaining):
                    await gate.semaphore.acquire()
                    acquired = True
                    remaining = gate.blocked_until - time.monotonic()
                    while remaining > 0:
                        if remaining > self._queue_remaining - (time.monotonic() - started):
                            raise TimeoutError
                        await asyncio.sleep(remaining)
                        remaining = gate.blocked_until - time.monotonic()
            except TimeoutError:
                self._queue_remaining = 0
                record_model_queue_wait(time.monotonic() - started, exhausted=True)
                raise ModelServiceBusy('The AI model service is busy. The queue wait budget was reached; please try again later.') from None
            waited = time.monotonic() - started
            self._queue_remaining = max(0, self._queue_remaining - waited)
            record_model_queue_wait(waited)
            try:
                yield
            except RateLimitError as exc:
                delay = self._get_client()._parse_retry_after_header(exc.response.headers)
                if delay is not None and math.isfinite(delay) and delay > 0:
                    gate.blocked_until = max(gate.blocked_until, time.monotonic() + delay)
                raise
        finally:
            if acquired:
                gate.semaphore.release()
            gate.users -= 1

    async def get_response(self, *args, **kwargs):
        async with self._slot():
            return await super().get_response(*args, **kwargs)

    async def stream_response(self, *args, **kwargs):
        async with self._slot():
            async for event in super().stream_response(*args, **kwargs):
                yield event
