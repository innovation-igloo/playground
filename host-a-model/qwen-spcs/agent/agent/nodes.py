"""LangGraph node implementations for the Qwen SPCS agent.

Defines three nodes that make up the agent graph:

- ``call_model``: Trims conversation history, invokes the LLM with bound
  tools, and returns the response plus updated turn count and token usage.

- ``call_tools``: Dispatches each tool call from the last AIMessage to the
  matching tool in the registry, then returns ToolMessages and structured logs.

- ``should_continue``: Conditional router that decides whether to loop back to
  ``call_model`` via ``call_tools`` or terminate at END.

See also: agent/graph.py (wires these nodes), agent/state.py (state schema).
"""

import asyncio
import logging
from typing import Literal
from langchain_core.messages import ToolMessage, trim_messages
from langgraph.config import get_stream_writer
from langgraph.graph import END
from agent.state import AgentState

logger = logging.getLogger(__name__)


# ============================================================
# SECTION: Constants
# ============================================================

MAX_CONTEXT_TOKENS = 20000


# ============================================================
# SECTION: Nodes
# ============================================================


async def call_model(state: AgentState, config) -> dict:
    """Invoke the LLM with a trimmed view of the conversation history.

    Args:
        state: Current graph state containing messages and turn metadata.
        config: LangGraph runtime config; must have ``configurable.llm_with_tools``.

    Returns:
        dict with keys: ``messages``, ``turn_count``, ``token_usage``.
    """
    llm_with_tools = config["configurable"]["llm_with_tools"]
    turn = state.get("turn_count", 0) + 1

    trimmed = trim_messages(
        state["messages"],
        max_tokens=MAX_CONTEXT_TOKENS,
        token_counter="approximate",
        strategy="last",
        include_system=True,
        start_on="human",
    )

    logger.debug(
        "llm call start",
        extra={
            "turn": turn,
            "messages_in": len(trimmed),
            "messages_total": len(state["messages"]),
        },
    )

    response = await llm_with_tools.ainvoke(trimmed)

    usage = {}
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        usage = dict(response.usage_metadata)

    tool_calls = getattr(response, "tool_calls", [])
    logger.info(
        "llm call complete",
        extra={
            "turn": turn,
            "tool_calls": [tc["name"] for tc in tool_calls],
            "has_content": bool(getattr(response, "content", None)),
            "token_usage": usage,
        },
    )

    return {
        "messages": [response],
        "turn_count": turn,
        "token_usage": usage,
    }


async def call_tools(state: AgentState, config) -> dict:
    """Execute all tool calls requested in the last AIMessage.

    Args:
        state: Current graph state; ``state["messages"][-1]`` must be an
            AIMessage with a non-empty ``tool_calls`` list.
        config: LangGraph runtime config; must have ``configurable.tools_by_name``.

    Returns:
        dict with keys: ``messages`` (ToolMessage list), ``tool_results``.
    """
    tools_by_name = config["configurable"]["tools_by_name"]
    stream_writer = get_stream_writer()
    results = []
    tool_data = []

    thread_id = config["configurable"].get("thread_id")

    for tc in state["messages"][-1].tool_calls:
        tool = tools_by_name[tc["name"]]

        if thread_id is not None and hasattr(tool, "_current_thread_id"):
            tool._current_thread_id = thread_id

        if hasattr(tool, "_stream_writer"):
            tool._stream_writer = stream_writer

        logger.info(
            "tool call start",
            extra={"tool": tc["name"], "arg_keys": list(tc["args"].keys())},
        )

        result = await tool.ainvoke(tc["args"])

        result_str = str(result)
        logger.info(
            "tool call complete",
            extra={
                "tool": tc["name"],
                "result_chars": len(result_str),
                "result_preview": result_str[:120],
            },
        )

        results.append(ToolMessage(content=result_str, tool_call_id=tc["id"]))
        tool_data.append({"tool": tc["name"], "args": tc["args"], "result": result})

    return {"messages": results, "tool_results": tool_data}


# ============================================================
# SECTION: Router
# ============================================================


def should_continue(state: AgentState, config) -> Literal["call_tools", "__end__"]:
    """Decide whether to run another tool-call round or end the graph.

    Args:
        state: Current graph state.
        config: LangGraph runtime config; ``configurable.max_turns`` overrides default.

    Returns:
        ``"call_tools"`` to loop, or ``END`` to terminate.
    """
    last = state["messages"][-1]
    max_turns = config["configurable"].get("max_turns", 10)
    turn = state.get("turn_count", 0)

    if hasattr(last, "tool_calls") and last.tool_calls:
        if turn >= max_turns:
            logger.warning(
                "max turns reached — forcing end",
                extra={"turn": turn, "max_turns": max_turns},
            )
            return END
        logger.debug("routing to call_tools", extra={"turn": turn, "tools": [tc["name"] for tc in last.tool_calls]})
        return "call_tools"

    logger.debug("routing to end", extra={"turn": turn})
    return END
