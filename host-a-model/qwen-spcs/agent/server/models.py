"""
Pydantic schemas for the chat API.

``ChatRequest`` is the JSON body accepted by POST /chat.
``ChatEvent`` mirrors the SSE payload shape emitted by the /chat endpoint's
event stream; it is not used at runtime for serialisation but serves as the
authoritative contract document for frontend consumers and AI agents reading
this code.

See also: server/app.py for the full SSE event emission logic.
"""

import uuid
from typing import Literal
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """POST /chat request body.

    Attributes:
        message: The user's raw text prompt for this conversational turn.
        thread_id: LangGraph checkpointer key that scopes memory to one
            conversation thread.  Callers may pass an explicit value to
            resume an existing thread; omitting it starts a fresh one.
        backend: Which Cortex tool backend to use for this request.
            ``"rest"`` uses Cortex Analyst REST + Snowpark SQL execution.
            ``"cortex_agents"`` uses the Cortex Agents ``:run`` endpoint.
    """

    message: str
    thread_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    backend: Literal["rest", "cortex_agents"] = "rest"


class ChatEvent(BaseModel):
    """Shape of every Server-Sent Event emitted by POST /chat.

    All SSE frames share this envelope regardless of event type.

    Attributes:
        type: Discriminator for the event.  One of:
            ``token``       -- incremental LLM text chunk from call_model node.
            ``tool_call``   -- LLM decided to invoke a tool (name + args).
            ``tool_result`` -- call_tools node finished executing the tool.
            ``usage``       -- final token-count summary for the full turn.
            ``done``        -- stream is complete; no further events follow.
        content: Primary payload string.  For ``token`` events this is the
            text fragment; for ``tool_call`` it is the tool name; for
            ``tool_result`` it is a human-readable status string; empty for
            ``usage`` and ``done``.
        metadata: Supplementary structured data keyed by event type:
            ``token``       -- {"node": str}
            ``tool_call``   -- {"args": dict}
            ``tool_result`` -- {"node": str}
            ``usage``       -- token count dict (input/output/total tokens)
            ``done``        -- {}
    """

    type: str
    content: str = ""
    metadata: dict = {}
