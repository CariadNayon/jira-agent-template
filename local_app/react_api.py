"""Compatibility API for the existing Databricks React client.

The React client expects AI SDK v6 UI-message SSE streams and a few session/
config routes. We adapt those to the existing OpenAI Agents SDK runner rather
than running a Node/Databricks authentication server during local development.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import OrderedDict
from uuid import uuid4

from agents import Runner
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from agent_server.execution import prepared_run
from agent_server.history import public_output_item
from jira_agent import CFG
from jira_agent.model_input import make_run_config

router = APIRouter(prefix="/api")
_log = logging.getLogger("jira_agent.local_ui")
_lock = asyncio.Lock()
_chats: OrderedDict[str, list[list[dict]]] = OrderedDict()
_MAX_CHATS = 12
_MAX_TURNS = 8
_CHAT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


@router.get("/session")
async def session():
    return {"user": {"email": "local", "name": "Local Developer",
                     "preferredUsername": "local"}}


@router.get("/config")
async def config():
    return {"features": {"chatHistory": False, "feedback": False},
            "greeting": "What would you like to know?",
            "obo": {"missingScopes": []}}


@router.get("/history", status_code=204)
async def no_history():
    return Response(status_code=204)


@router.get("/chat/{conversation_id}/stream")
async def no_resume(conversation_id: str):
    # No automatic replays of potentially non-idempotent Jira operations.
    return Response(status_code=204)


@router.get("/chat/{conversation_id}")
async def chat_info(conversation_id: str):
    raise HTTPException(404, "No persistent local chat history.")


@router.get("/messages/{message_id}", status_code=204)
async def no_stored_messages(message_id: str):
    return Response(status_code=204)


@router.post("/feedback", status_code=204)
async def no_feedback():
    return Response(status_code=204)


def _user_text(message: object) -> str:
    if not isinstance(message, dict) or message.get("role") != "user":
        return ""
    parts = message.get("parts")
    if not isinstance(parts, list):
        return ""
    return "\n".join(p.get("text", "") for p in parts if
                     isinstance(p, dict) and p.get("type") == "text"
                     and isinstance(p.get("text"), str)).strip()


def _frame(data: dict) -> str:
    return "data: " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n\n"


def _safe_text(error: Exception) -> str:
    # Never echo API secrets, Jira token values, user text or model outputs
    # from unknown exception messages into the browser.
    return "Request failed (" + type(error).__name__ + "). Check local server logs."


@router.post("/chat")
async def react_chat(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Expected a JSON request body")
    chat_id = body.get("id")
    if not isinstance(chat_id, str) or not _CHAT_ID.fullmatch(chat_id):
        raise HTTPException(400, "Invalid conversation ID")
    text = _user_text(body.get("message"))
    if not text or len(text) > 12000:
        raise HTTPException(400, "Expected a user message of at most 12000 characters")

    async def events():
        async with _lock:
            # UI transport sends the entire previousMessages when chat history
            # is disabled, but our backend retains complete typed tool call/output
            # pairs in memory so approvals and subsequent model turns stay valid.
            previous = _chats.get(chat_id, [])
            messages = [item for turn in previous for item in turn]
            messages.append({"role": "user", "content": text})
            answer_id = str(uuid4())
            text_id = str(uuid4())
            yield _frame({"type": "start", "messageId": answer_id})
            yield _frame({"type": "text-start", "id": text_id})
            run = None
            try:
                async with prepared_run({}, messages, chat_id) as (agent, context, hooks):
                    run = Runner.run_streamed(agent, input=messages,
                                              context=context, hooks=hooks,
                                              run_config=make_run_config(),
                                              max_turns=CFG["agent"]["max_turns"])
                    hooks.chat_result = run
                    async for event in run.stream_events():
                        if event.type == "raw_response_event":
                            payload = event.data
                            if getattr(payload, "type", "") == "response.output_text.delta":
                                delta = getattr(payload, "delta", "")
                                if isinstance(delta, str) and delta:
                                    yield _frame({"type": "text-delta", "id": text_id, "delta": delta})
                    outputs = [public_output_item(item.to_input_item())
                               for item in run.new_items]
                    # Keep complete tool history, not just text, for approvals.
                    _chats[chat_id] = [*previous, [
                        {"role": "user", "content": text}, *outputs
                    ]][-_MAX_TURNS:]
                    _chats.move_to_end(chat_id)
                    while len(_chats) > _MAX_CHATS:
                        _chats.popitem(last=False)
            except asyncio.CancelledError:
                if run is not None:
                    run.cancel()
                raise
            except Exception as exc:
                _log.exception("React client run failed")
                if run is not None:
                    run.cancel()
                yield _frame({"type": "error", "errorText": _safe_text(exc)})
            yield _frame({"type": "text-end", "id": text_id})
            yield _frame({"type": "finish"})
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform",
                 "X-Accel-Buffering": "no",
                 "x-vercel-ai-ui-message-stream": "v1"},
    )
