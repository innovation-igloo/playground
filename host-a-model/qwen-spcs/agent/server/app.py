"""
FastAPI application entry point for the Snowflake Multi-Agent Studio server.

This module wires together the FastAPI app, CORS and error-handling
middleware, the LangGraph agent (defined in agent/graph.py), and the two
HTTP endpoints: POST /chat (SSE streaming) and GET /health.

The agent itself is a self-hosted LLM (deployed to Snowpark Container
Services) that is given a single tool: ``cortex_agent``, which delegates
natural-language questions to a Cortex Agent configured in Snowflake.
This demonstrates the "BYO-LLM orchestrating Cortex Agents" pattern.

Startup order matters: ``_config`` is loaded at module import time so that
the CORS middleware can consume ``config.server.cors_origins`` before the
lifespan context manager executes.  The LangGraph graph is built exactly
once inside the lifespan manager and stored in the module-level
``app_state`` dict to avoid re-instantiation per request.

Middleware stack (outermost to innermost): CORSMiddleware -> error_handler
-> RequestLoggingMiddleware -> route handlers.  CORS must be outermost so
its headers survive 500 responses produced by error_handler.
"""

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage, SystemMessage, AIMessageChunk
import snowflake.connector
from snowflake.snowpark import Session

from agent.config import load_config
from agent.graph import create_agent
from agent.tools import build_tools
from server.logging_config import setup_logging
from server.middleware import RequestLoggingMiddleware, error_handler
from server.models import ChatRequest

# ============================================================
# SECTION: CONFIG + LOGGING
# Logging must be initialised before any other module emits records.
# ============================================================

_config = load_config()
setup_logging(_config)

logger = logging.getLogger(__name__)
logger.info("config loaded", extra={"log_level": _config.logging.level, "log_dir": _config.logging.log_dir})

# Populated during lifespan startup; holds graph + runtime objects for the
# lifetime of the process so they are created exactly once.
app_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the LangGraph agent once at server startup.

    Stores the compiled graph and associated runtime objects in ``app_state``
    so that request handlers can access them without rebuilding per request.

    Args:
        app: The FastAPI application instance (injected by the framework).

    Yields:
        Control is yielded back to FastAPI after startup; shutdown logic
        (if any) would go after the yield.
    """
    logger.info(
        "agent startup",
        extra={
            "model": _config.llm.model,
            "base_url": _config.llm.base_url,
            "tool_backend": _config.tools.cortex_analyst.backend,
            "system_prompt_chars": len(_config.agent.system_prompt),
        },
    )
    graph, llm_with_tools_rest, tools_rest, llm = create_agent(_config)

    config_agents = _config.model_copy(deep=True)
    config_agents.tools.cortex_analyst.backend = "cortex_agents"
    tools_agents_list = build_tools(config_agents)
    llm_with_tools_agents = llm.bind_tools(tools_agents_list)
    tools_agents = {t.name: t for t in tools_agents_list}

    app_state["graph"] = graph
    app_state["backends"] = {
        "rest": {"llm_with_tools": llm_with_tools_rest, "tools_by_name": tools_rest},
        "cortex_agents": {"llm_with_tools": llm_with_tools_agents, "tools_by_name": tools_agents},
    }
    app_state["system_prompt"] = _config.agent.system_prompt
    app_state["config"] = _config

    conn_name = os.getenv("SNOW_CONNECTION", "innovation-igloo")
    sf_conn = snowflake.connector.connect(connection_name=conn_name)
    snowpark_session = Session.builder.configs({"connection": sf_conn}).create()
    app_state["snowpark_session"] = snowpark_session
    for backend_cfg in app_state["backends"].values():
        for tool in backend_cfg["tools_by_name"].values():
            if hasattr(tool, "_snowpark_session"):
                tool._snowpark_session = snowpark_session

    logger.info(
        "agent ready",
        extra={
            "tools_rest": list(tools_rest.keys()),
            "tools_agents": list(tools_agents.keys()),
            "host": _config.server.host,
            "port": _config.server.port,
        },
    )
    yield
    snowpark_session.close()
    logger.info("agent shutdown")


app = FastAPI(title="Snowflake Multi-Agent Studio", lifespan=lifespan)

# ============================================================
# SECTION: MIDDLEWARE
# Registration order: CORS (outermost) → error_handler → RequestLogging.
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=_config.server.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(error_handler)
app.add_middleware(RequestLoggingMiddleware)


# ============================================================
# SECTION: /chat -- SSE streaming chat endpoint
#
# Drives the LangGraph agent and emits five SSE event types:
#   token       -- incremental LLM text chunk (AIMessageChunk with content)
#   tool_call   -- LLM decided to invoke a tool (name + args)
#   tool_result -- call_tools node finished; signals tool round-trip done
#   usage       -- final token counts for the full turn
#   done        -- stream closed; no more events
# ============================================================

@app.post("/chat")
async def chat(request: ChatRequest):
    """Stream an agent response as Server-Sent Events.

    Builds the initial message list (optional system prompt + user message),
    then drives ``graph.astream`` with ``stream_mode=["messages", "updates"]``
    -- a hybrid mode that yields both per-chunk LLM tokens ("messages") and
    per-node state snapshots ("updates") in the same stream.

    Args:
        request: Parsed ``ChatRequest`` containing the user message and an
            optional ``thread_id`` for conversation continuity.

    Returns:
        A ``StreamingResponse`` with ``media_type="text/event-stream"``.
    """
    graph = app_state["graph"]
    system_prompt = app_state["system_prompt"]

    backend_key = request.backend if request.backend in app_state["backends"] else "rest"
    backend_cfg = app_state["backends"][backend_key]
    run_config = {
        "configurable": {
            "thread_id": request.thread_id,
            "llm_with_tools": backend_cfg["llm_with_tools"],
            "tools_by_name": backend_cfg["tools_by_name"],
        }
    }

    messages = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    messages.append(HumanMessage(content=request.message))

    chat_logger = logging.getLogger("server.chat")
    chat_logger.info(
        "chat request",
        extra={"thread_id": request.thread_id, "backend": backend_key, "message_chars": len(request.message)},
    )

    async def event_stream():
        token_usage = {}
        tool_calls_made: list[str] = []
        start = time.perf_counter()
        ttfb_ms: float | None = None
        first_token = True

        # -- Producer/consumer via asyncio.Queue so the consumer loop can emit
        #    heartbeat SSE events every 3 s while a tool call is in progress.
        #    Without this, graph.astream blocks the generator silently for the
        #    entire Cortex Agent round-trip (20–60 s), making the SSE stream
        #    appear dead from the client's perspective.
        queue: asyncio.Queue = asyncio.Queue()

        async def _producer():
            try:
                async for chunk in graph.astream(
                    {"messages": messages, "turn_count": 0, "tool_results": []},
                    run_config,
                    stream_mode=["messages", "updates", "custom"],
                    version="v2",
                ):
                    await queue.put(chunk)
            finally:
                await queue.put(None)  # sentinel — always emitted even on error

        producer = asyncio.create_task(_producer())

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(queue.get(), timeout=3.0)
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat', 'content': 'Processing…', 'metadata': {}})}\n\n"
                    continue

                if chunk is None:
                    break

                if chunk["type"] == "custom":
                    event_data = chunk["data"]
                    evt_type = event_data.get("type")
                    if evt_type in ("downstream_token", "downstream_status"):
                        yield f"data: {json.dumps({'type': evt_type, 'content': event_data.get('content', ''), 'metadata': event_data.get('metadata', {})})}\n\n"

                elif chunk["type"] == "messages":
                    msg, metadata = chunk["data"]

                    if not isinstance(msg, AIMessageChunk):
                        continue

                    node = metadata.get("langgraph_node", "")

                    if hasattr(msg, "content") and msg.content and node != "call_tools":
                        if first_token:
                            ttfb_ms = round((time.perf_counter() - start) * 1000, 1)
                            first_token = False
                        event = {
                            "type": "token",
                            "content": msg.content,
                            "metadata": {"node": node},
                        }
                        yield f"data: {json.dumps(event)}\n\n"

                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tc in msg.tool_calls:
                            tool_calls_made.append(tc["name"])
                            event = {
                                "type": "tool_call",
                                "content": tc["name"],
                                "metadata": {"args": tc["args"]},
                            }
                            yield f"data: {json.dumps(event)}\n\n"

                    if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                        token_usage = dict(msg.usage_metadata)

                    if hasattr(msg, "response_metadata") and msg.response_metadata:
                        rm = msg.response_metadata
                        if "token_usage" in rm:
                            token_usage = rm["token_usage"]
                        elif "usage" in rm:
                            token_usage = rm["usage"]

                elif chunk["type"] == "updates":
                    for node_name, node_data in chunk["data"].items():
                        if node_name == "call_tools":
                            event = {
                                "type": "tool_result",
                                "content": "Tool execution complete",
                                "metadata": {"node": node_name},
                            }
                            yield f"data: {json.dumps(event)}\n\n"

                        if node_name == "call_model" and isinstance(node_data, dict):
                            usage = node_data.get("token_usage")
                            if usage:
                                token_usage = usage
        finally:
            producer.cancel()
            try:
                await producer
            except asyncio.CancelledError:
                pass

        if token_usage:
            yield f"data: {json.dumps({'type': 'usage', 'content': '', 'metadata': token_usage})}\n\n"

        yield f"data: {json.dumps({'type': 'done', 'content': '', 'metadata': {}})}\n\n"

        chat_logger.info(
            "chat complete",
            extra={
                "thread_id": request.thread_id,
                "tools_called": tool_calls_made,
                "token_usage": token_usage,
                "ttfb_ms": ttfb_ms,
            },
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )


# ============================================================
# SECTION: /health
# ============================================================

@app.get("/health")
async def health():
    """Liveness probe endpoint.

    Returns:
        A dict ``{"status": "ok"}`` with HTTP 200.
    """
    return {"status": "ok"}


# ============================================================
# SECTION: STATIC UI
# ============================================================

_ui_dist = Path(__file__).parent.parent / "ui-dist"
if _ui_dist.exists():
    app.mount("/", StaticFiles(directory=str(_ui_dist), html=True), name="ui")
