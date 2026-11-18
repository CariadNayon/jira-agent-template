"""Agent-Handler für den MLflow AgentServer (Databricks-Vorlage, angepasst für den Jira-Agenten).

Der eigentliche Agent (Modell, Tools, Anweisungen) wird pro Anfrage in jira_agent/runtime.py gebaut –
mit Identität, Keys, Einstellungen und Rechten des angemeldeten Nutzers.
"""
import logging
from typing import AsyncGenerator

import mlflow
from agents import Runner, set_default_openai_api
from agents.tracing import set_trace_processors
from mlflow.genai.agent_server import get_request_headers, invoke, stream
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
)

from agent_server.history import normalize_history_items, public_output_item
from agent_server.utils import get_session_id, process_agent_stream_events
from jira_agent import CFG
from jira_agent.model_input import make_run_config
from agent_server.execution import prepared_run

set_default_openai_api("chat_completions")
set_trace_processors([])  # only use mlflow for trace processing
mlflow.openai.autolog()
logging.getLogger("mlflow.utils.autologging_utils").setLevel(logging.ERROR)


@invoke()
async def invoke_handler(request: ResponsesAgentRequest) -> ResponsesAgentResponse:
    if session_id := get_session_id(request):
        mlflow.update_current_trace(metadata={"mlflow.trace.session": session_id})
    messages = normalize_history_items([i.model_dump() for i in request.input])
    async with prepared_run(get_request_headers(), messages, get_session_id(request) or "") as (agent, run_ctx, hooks):
        mlflow.update_current_trace(metadata={"performance.request_id": hooks.performance.request_id})
        result = await Runner.run(agent, messages, context=run_ctx, hooks=hooks,
                                  run_config=make_run_config(), max_turns=CFG["agent"]["max_turns"])
        hooks.chat_result = result
        return ResponsesAgentResponse(output=[public_output_item(item.to_input_item()) for item in result.new_items])


@stream()
async def stream_handler(
    request: ResponsesAgentRequest,
) -> AsyncGenerator[ResponsesAgentStreamEvent, None]:
    if session_id := get_session_id(request):
        mlflow.update_current_trace(metadata={"mlflow.trace.session": session_id})
    messages = normalize_history_items([i.model_dump() for i in request.input])
    async with prepared_run(get_request_headers(), messages, get_session_id(request) or "") as (agent, run_ctx, hooks):
        mlflow.update_current_trace(metadata={"performance.request_id": hooks.performance.request_id})
        result = Runner.run_streamed(agent, input=messages, context=run_ctx, hooks=hooks,
                                     run_config=make_run_config(), max_turns=CFG["agent"]["max_turns"])
        hooks.chat_result = result
        try:
            async for event in process_agent_stream_events(result.stream_events()):
                hooks.observe_stream(event)
                yield event
        finally:
            result.cancel()
