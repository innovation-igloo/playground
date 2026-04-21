"""Builds the LangGraph StateGraph for the Qwen SPCS agent.

Returns ``(graph, llm_with_tools, tools_by_name)`` so the FastAPI server can
cache all three objects and reuse them across requests without rebuilding the
graph on every call.

The graph wires three nodes — ``call_model``, ``call_tools``, and the
conditional router ``should_continue`` — into a loop that runs until the LLM
stops requesting tool calls or the ``max_turns`` safety cap is hit.

See also: agent/nodes.py (node implementations), server/app.py (caches and
          invokes the returned tuple).
"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from agent.state import AgentState
from agent.nodes import call_model, call_tools, should_continue
from agent.config import AppConfig
from agent.llm import create_llm
from agent.tools import build_tools


def create_agent(config: AppConfig):
    """Construct and compile the LangGraph agent graph.

    Builds the LLM client, binds tools to it, wires the StateGraph nodes, and
    compiles with an in-memory checkpointer.

    Graph topology::

        START
          |
          v
       call_model  <-------+
          |                |
          v                |
       should_continue     |
          |   \\            |
          |    \\           |
         END    call_tools-+

    ``should_continue`` routes to ``call_tools`` when the last AIMessage
    contains tool_calls AND turn_count < max_turns; otherwise it routes to END.

    Args:
        config: Fully validated ``AppConfig`` instance (from ``load_config``).

    Returns:
        tuple:
            - graph: Compiled ``CompiledStateGraph`` ready to invoke.
            - llm_with_tools: The ChatOpenAI client with tools bound (used by
              ``call_model`` via ``config["configurable"]``).
            - tools_by_name: ``dict[str, BaseTool]`` mapping tool name to
              callable tool instance (used by ``call_tools`` via
              ``config["configurable"]``).

    Notes:
        The returned tuple is cached by the server to avoid rebuilding the
        graph on every /chat request.
    """
    llm = create_llm(config.llm)
    tools = build_tools(config)
    llm_with_tools = llm.bind_tools(tools)

    builder = StateGraph(AgentState)
    builder.add_node("call_model", call_model)
    builder.add_node("call_tools", call_tools)
    builder.add_edge(START, "call_model")
    builder.add_conditional_edges("call_model", should_continue, ["call_tools", END])
    builder.add_edge("call_tools", "call_model")

    checkpointer = InMemorySaver()  # Ephemeral — conversation state is lost on process restart. Swap to persistent checkpointer for production.
    graph = builder.compile(checkpointer=checkpointer)

    tools_by_name = {t.name: t for t in tools}
    return graph, llm_with_tools, tools_by_name, llm
