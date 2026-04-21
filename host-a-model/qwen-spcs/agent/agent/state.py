"""LangGraph state schema for the Qwen SPCS agent.

Extends ``MessagesState`` (which already provides the ``messages`` field with
an append reducer) with three additional fields that track agent progress and
tool activity across turns. This module is the single source of truth for the
shape of data flowing through the graph.

See also: agent/graph.py (creates the StateGraph with this schema),
          agent/nodes.py (reads and writes these fields).
"""

from typing import Annotated
from langgraph.graph import MessagesState


class AgentState(MessagesState):
    """Full state record passed between every node in the LangGraph graph.

    Inherits from ``MessagesState``, which contributes:
        messages (list[BaseMessage]): The conversation history. LangGraph's
            built-in append reducer merges new messages rather than overwriting.

    Additional fields:
        turn_count (int): How many ``call_model`` iterations have completed in
            the current invocation. Overwritten (not accumulated) on each turn.
            Read by ``should_continue`` to enforce the ``max_turns`` safety cap.

        tool_results (list[dict]): Structured log of every tool call made this
            invocation, each entry containing ``tool``, ``args``, and ``result``.
            The lambda reducer accumulates results across turns rather than overwriting.

        token_usage (dict): Raw ``usage_metadata`` dict from the last LLM
            response (keys: ``input_tokens``, ``output_tokens``, ``total_tokens``).
            Overwritten on each turn; callers read the final value after graph completion.
    """

    turn_count: int
    tool_results: Annotated[list[dict], lambda a, b: a + b]  # Additive reducer = accumulate results across turns rather than overwriting.
    token_usage: dict
