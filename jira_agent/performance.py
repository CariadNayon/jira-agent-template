"""Per-run latency counters. Never record prompts, tool arguments, keys or user IDs."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import logging
import threading
import time
from uuid import uuid4

from agents.lifecycle import RunHooksBase

_log = logging.getLogger('jira_agent.performance')
_log.setLevel(logging.INFO)
_current: ContextVar[Performance | None] = ContextVar('agent_performance', default=None)


@dataclass(repr=False)
class Performance:
    request_id: str = field(default_factory=lambda: uuid4().hex)
    started: float = field(default_factory=time.perf_counter)
    counters: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, key: str, value: float = 1):
        with self._lock:
            self.counters[key] = self.counters.get(key, 0) + value

    def summary(self, outcome: str) -> dict:
        with self._lock:
            return {'event': 'agent_performance', 'request_id': self.request_id, 'outcome': outcome,
                    'total_ms': round((time.perf_counter()-self.started)*1000, 2),
                    **{key: round(value, 2) for key, value in self.counters.items()}}


@contextmanager
def measure_run():
    performance = Performance()
    token = _current.set(performance)
    outcome = 'completed'
    try:
        yield performance
    except BaseException as exc:
        outcome = 'cancelled' if isinstance(exc, (asyncio.CancelledError, GeneratorExit)) else 'error'
        raise
    finally:
        _current.reset(token)
        _log.info('%s', json.dumps(performance.summary(outcome), sort_keys=True))


@contextmanager
def measure_http(service: str):
    performance = _current.get()
    start = time.perf_counter()
    if performance:
        performance.add(service + '_calls')
    try:
        yield
    finally:
        if performance:
            performance.add(service + '_ms', (time.perf_counter()-start)*1000)


def measure_jira():
    return measure_http('jira')


def record_http_status(service: str, status: int):
    performance = _current.get()
    if performance:
        performance.add(f'{service}_status_{int(status)}')


def record_retry_wait(seconds: float, *, exhausted: bool = False):
    performance = _current.get()
    if performance:
        performance.add('azure_retry_budget_exhausted' if exhausted else 'azure_retry_waits')
        performance.add('azure_retry_wait_ms', seconds * 1000)


def record_model_queue_wait(seconds: float, *, exhausted: bool = False):
    performance = _current.get()
    if performance:
        performance.add('model_queue_timeouts' if exhausted else 'model_queue_entries')
        performance.add('model_queue_wait_ms', seconds * 1000)


class PerformanceHooks(RunHooksBase):
    def __init__(self, performance: Performance):
        self.performance = performance
        self.chat_result = None     # set by the handlers so the chat log can read the run's items at the end
        self._llm_started = None
        self._tools = {}
        self._first_event = True
        self._first_text = True

    def observe_stream(self, event):
        # The existing MLflow bridge yields both raw dictionaries and event models.
        elapsed = (time.perf_counter()-self.performance.started)*1000
        if self._first_event:
            self.performance.add('first_event_ms', elapsed)
            self._first_event = False
        kind = event.get('type') if isinstance(event, dict) else event.type
        if self._first_text and kind == 'response.output_text.delta':
            self.performance.add('first_text_ms', elapsed)
            self._first_text = False

    async def on_llm_start(self, context, agent, system_prompt, input_items):
        self.performance.add('llm_calls')
        self._llm_started = time.perf_counter()

    async def on_llm_end(self, context, agent, response):
        if self._llm_started is not None:
            self.performance.add('llm_ms', (time.perf_counter()-self._llm_started)*1000)
            self._llm_started = None
        usage = response.usage
        for field_name in ('input_tokens', 'output_tokens'):
            self.performance.add(field_name, getattr(usage, field_name, 0))
        self.performance.add('cached_input_tokens', getattr(usage.input_tokens_details, 'cached_tokens', 0) or 0)

    async def on_tool_start(self, context, agent, tool):
        self.performance.add('tool_calls')
        self.performance.add(f'tool_{tool.name}_calls')
        key = getattr(context, 'tool_call_id', None) or id(context)
        self._tools[key] = time.perf_counter()

    async def on_tool_end(self, context, agent, tool, result):
        key = getattr(context, 'tool_call_id', None) or id(context)
        start = self._tools.pop(key, None)
        if start is not None:
            elapsed = (time.perf_counter()-start)*1000
            self.performance.add('tool_ms', elapsed)
            self.performance.add(f'tool_{tool.name}_ms', elapsed)

    def finish(self):
        # Include time spent waiting when a model call fails or the user disconnects.
        if self._llm_started is not None:
            self.performance.add('llm_ms', (time.perf_counter()-self._llm_started)*1000)
            self.performance.add('unfinished_llm_calls')
            self._llm_started = None
