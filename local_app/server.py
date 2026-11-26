"""Lightweight developer-only FastAPI runtime. No MLflow, Databricks UI, or Node server.

Never expose this unauthenticated process on a LAN or the Internet. The launcher
binds it exclusively to the loopback interface.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import OrderedDict
from pathlib import Path
from uuid import uuid4

from agents import Runner, set_default_openai_api
from agents.tracing import set_trace_processors
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field

from agent_server.execution import prepared_run
from agent_server.history import public_output_item
from jira_agent import CFG
from jira_agent.model_input import make_run_config
from jira_agent.runtime import load_settings
from jira_agent.state import user_state
from jira_agent.web import router as jira_router
from jira_agent.connections import close_connections

log = logging.getLogger("jira_agent.local")
set_default_openai_api("chat_completions")
set_trace_processors([])

# A single-user, memory-only browser session. No database, no cross-user sharing.
# Each conversation stores a bounded number of complete turns to preserve the
# function-call/result pairs needed for SDK history and write confirmations.
_MAX_CHATS = 12
_MAX_TURNS = 8
_chats: OrderedDict[str, list[list[dict]]] = OrderedDict()
_run_lock = asyncio.Lock()

app = FastAPI(title="T1 Jira Agent - Local Development", docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])
app.include_router(jira_router)


@app.middleware("http")
async def local_security(request: Request, call_next):
    # Cross-origin form requests must not be able to modify Jira credentials,
    # issue tickets, settings, or files on an otherwise unauthenticated server.
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and origin not in ("http://127.0.0.1:8000", "http://localhost:8000"):
            return JSONResponse({"detail": "Cross-origin requests are blocked."}, status_code=403)
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            # Existing /jira/api/upload accepts raw file bytes. The local dev UI
            # deliberately does not support browser uploads yet.
            return JSONResponse({"detail": "JSON requests only in local dev mode."}, status_code=415)
    return await call_next(request)


@app.on_event("shutdown")
async def shutdown():
    await close_connections()


@app.get("/")
async def homepage():
    return FileResponse(Path(__file__).with_name("index.html"), media_type="text/html",
                        headers={"Cache-Control": "no-store",
                                 "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"})


@app.get("/health")
async def health():
    return {"status": "ok", "mode": "local-fastapi"}


class AzureKeyBody(BaseModel):
    key: str = Field(min_length=1, max_length=4096)


@app.post("/api/local/azure-key")
async def set_local_model_key(body: AzureKeyBody):
    # The existing Jira credentials endpoint only stores the key. Here we
    # additionally select the matching provider for immediate local use.
    state = user_state("local")
    state.creds["azure_key"] = body.key
    load_settings(state, "local", None)["llm_provider"] = "azure_own"
    return {"status": "ready", "provider": "azure_own"}


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    conversation_id: str | None = Field(default=None, pattern=r"^[a-f0-9-]{36}$")


def _output_text(result) -> str:
    answer = result.final_output
    if isinstance(answer, str):
        return answer
    if answer is not None:
        return str(answer)
    return "The agent returned no text."


@app.post("/api/local/chat")
async def chat(body: ChatBody):
    conversation_id = body.conversation_id or str(uuid4())
    # One local developer at a time, including model/tool calls.
    async with _run_lock:
        previous = _chats.get(conversation_id, [])
        messages = [item for turn in previous for item in turn]
        messages.append({"role": "user", "content": body.message.strip()})
        try:
            async with prepared_run({}, messages, conversation_id) as (agent, context, hooks):
                result = await Runner.run(
                    agent, messages, context=context, hooks=hooks,
                    run_config=make_run_config(), max_turns=CFG["agent"]["max_turns"],
                )
                hooks.chat_result = result
                answer = _output_text(result)
                outputs = [public_output_item(item.to_input_item()) for item in result.new_items]
        except Exception as exc:
            # Keep the prior history unchanged if a model or network call fails;
            # never automatically repeat potentially executed Jira write tools.
            log.exception("Local agent request failed")
            raise HTTPException(502, f"{type(exc).__name__}: {str(exc)[:350]}") from None

        _chats[conversation_id] = [*previous, [
            {"role": "user", "content": body.message.strip()}, *outputs,
        ]][- _MAX_TURNS:]
        _chats.move_to_end(conversation_id)
        while len(_chats) > _MAX_CHATS:
            _chats.popitem(last=False)
        return {"conversation_id": conversation_id, "answer": answer}


@app.post("/api/local/reset")
async def reset():
    async with _run_lock:
        _chats.clear()
    return {"status": "cleared"}
