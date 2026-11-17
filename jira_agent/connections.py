"""Reusable HTTP connections, without shared credentials, cookies or conversation data."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from http.cookiejar import CookieJar, DefaultCookiePolicy
import threading
from weakref import WeakKeyDictionary

import httpx
from openai import DefaultAsyncHttpxClient
import requests


class _NoCookies(DefaultCookiePolicy):
    def set_ok(self, cookie, request):
        return False

    def return_ok(self, cookie, request):
        return False


_local = threading.local()
_sessions: set[requests.Session] = set()
_session_lock = threading.Lock()
_session_generation = 0
_async_clients = WeakKeyDictionary()
_current_async: ContextVar[httpx.AsyncClient | None] = ContextVar('azure_http_pool', default=None)


def jira_session() -> requests.Session:
    """One session per worker thread. Auth is supplied on each individual request."""
    session = getattr(_local, 'session', None)
    if session is None or getattr(_local, 'generation', -1) != _session_generation:
        session = requests.Session()
        session.cookies.set_policy(_NoCookies())
        _local.session = session
        _local.generation = _session_generation
        with _session_lock:
            _sessions.add(session)
    return session


class _NoDirectTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request):
        raise RuntimeError('Requests must use the shared HTTP client.')


class _BorrowedAsyncClient(DefaultAsyncHttpxClient):
    def __init__(self, shared: httpx.AsyncClient):
        # Avoid constructing another unused TLS transport for every SDK client.
        super().__init__(transport=_NoDirectTransport())
        self._shared = shared

    async def send(self, request, **kwargs):
        # The SDK has already built this request with its own credential and headers.
        # The shared client retains normal HTTPX proxy/CA handling and no cookies.
        from jira_agent.performance import measure_http, record_http_status
        with measure_http('azure_http'):
            response = await self._shared.send(request, **kwargs)
            record_http_status('azure_http', response.status_code)
            return response


def azure_http_client() -> httpx.AsyncClient | None:
    shared = _current_async.get()
    return _BorrowedAsyncClient(shared) if shared is not None else None


@contextmanager
def azure_connection_scope():
    """Share transport on this event loop; each run keeps its own SDK client/key."""
    loop = asyncio.get_running_loop()
    shared = _async_clients.get(loop)
    if shared is None or shared.is_closed:
        shared = DefaultAsyncHttpxClient(cookies=CookieJar(policy=_NoCookies()))
        _async_clients[loop] = shared
    token = _current_async.set(shared)
    try:
        yield
    finally:
        _current_async.reset(token)


async def close_connections() -> None:
    """Run at application shutdown, after active requests have finished."""
    global _session_generation
    from jira_agent.model_gate import clear_model_gates
    clear_model_gates()
    shared = _async_clients.pop(asyncio.get_running_loop(), None)
    if shared is not None:
        await shared.aclose()
    with _session_lock:
        sessions = list(_sessions)
        _sessions.clear()
        _session_generation += 1
    for session in sessions:
        session.close()
    # Other thread-local references are retired along with the application's workers.
    if hasattr(_local, 'session'):
        del _local.session


def install_connection_lifecycle(app) -> None:
    """Compose with the server's existing lifespan, including custom MLflow startup."""
    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        try:
            async with previous(application) as state:
                yield state
        finally:
            await close_connections()

    app.router.lifespan_context = lifespan
