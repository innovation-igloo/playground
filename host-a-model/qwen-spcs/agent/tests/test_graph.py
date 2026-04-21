"""Tests for agent.nodes (LangGraph state-machine nodes).

Covers:
- call_model increments turn_count and appends the LLM response to messages
- call_tools dispatches to the named tool, wraps result in a ToolMessage, and records tool_results
- should_continue routes to 'call_tools' when the last AIMessage has tool_calls
- should_continue routes to '__end__' when the last AIMessage has no tool_calls
- should_continue routes to '__end__' when max_turns is reached regardless of pending tool_calls

Run: pytest tests/test_graph.py
"""

import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from agent.nodes import call_model, call_tools, should_continue
from agent.state import AgentState


def _make_state(messages, turn_count=0, tool_results=None) -> AgentState:
    """Build a minimal AgentState for use in node tests.

    Stands in for the full LangGraph state dict that nodes receive at runtime.
    """
    return AgentState(
        messages=messages,
        turn_count=turn_count,
        tool_results=tool_results or [],
    )


def _make_config(max_turns=10):
    """Build a minimal LangGraph config dict with a MagicMock LLM.

    The 'llm_with_tools' value stands in for a real ChatOpenAI instance bound
    to tools via .bind_tools(); 'tools_by_name' maps tool names to callables.
    """
    llm = MagicMock()
    return {
        "configurable": {
            "llm_with_tools": llm,
            "tools_by_name": {},
            "max_turns": max_turns,
        }
    }


def test_call_model_increments_turn_count():
    """call_model increments turn_count by 1 and appends the LLM AIMessage to state."""
    state = _make_state([HumanMessage(content="hello")], turn_count=2)
    config = _make_config()
    mock_response = AIMessage(content="Hi there")
    config["configurable"]["llm_with_tools"].invoke.return_value = mock_response

    result = call_model(state, config)

    assert result["turn_count"] == 3
    assert result["messages"] == [mock_response]


def test_call_tools_invokes_tool():
    """call_tools dispatches the tool call, wraps the result as ToolMessage, and logs tool_results."""
    tool_mock = MagicMock()
    tool_mock.invoke.return_value = "SQL result"

    ai_msg = AIMessage(content="")
    ai_msg.tool_calls = [{"name": "cortex_agent", "args": {"question": "q?"}, "id": "call_1"}]

    state = _make_state([HumanMessage(content="q"), ai_msg])
    config = {
        "configurable": {
            "llm_with_tools": MagicMock(),
            "tools_by_name": {"cortex_agent": tool_mock},
        }
    }

    result = call_tools(state, config)

    tool_mock.invoke.assert_called_once_with({"question": "q?"})
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], ToolMessage)
    assert result["tool_results"][0]["tool"] == "cortex_agent"


def test_should_continue_with_tool_calls():
    """should_continue returns 'call_tools' when the latest AIMessage has pending tool calls."""
    ai_msg = AIMessage(content="")
    ai_msg.tool_calls = [{"name": "cortex_agent", "args": {}, "id": "c1"}]
    state = _make_state([HumanMessage(content="q"), ai_msg], turn_count=1)
    config = {"configurable": {"max_turns": 10}}

    result = should_continue(state, config)
    assert result == "call_tools"


def test_should_continue_no_tool_calls():
    """should_continue returns '__end__' when the latest AIMessage has no tool calls."""
    ai_msg = AIMessage(content="Here is your answer")
    ai_msg.tool_calls = []
    state = _make_state([HumanMessage(content="q"), ai_msg])
    config = {"configurable": {"max_turns": 10}}

    result = should_continue(state, config)
    assert result == "__end__"


def test_should_continue_max_turns_reached():
    """should_continue returns '__end__' when turn_count has reached max_turns."""
    ai_msg = AIMessage(content="")
    ai_msg.tool_calls = [{"name": "cortex_agent", "args": {}, "id": "c1"}]
    state = _make_state([HumanMessage(content="q"), ai_msg], turn_count=10)
    config = {"configurable": {"max_turns": 10}}

    result = should_continue(state, config)
    assert result == "__end__"
