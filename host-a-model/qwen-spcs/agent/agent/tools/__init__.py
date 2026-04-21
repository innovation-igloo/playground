"""Backend factory for Cortex Analyst tool instances.

Reads ``config.tools.cortex_analyst.backend`` and returns a list containing
exactly one tool instance wired to the chosen backend. Keeping all three
backends behind a single factory means the rest of the agent is decoupled from
transport details — only ``config.yaml`` needs to change to swap backends.

Valid ``backend`` values: ``"rest"``, ``"mcp"``, ``"cortex_agents"``.

See also:
    agent/tools/cortex_rest.py    -- REST backend
    agent/tools/cortex_mcp.py     -- MCP (JSON-RPC 2.0) backend
    agent/tools/cortex_agents.py  -- Cortex Agents :run backend
"""

from agent.config import AppConfig
from agent.tools.cortex_rest import CortexAnalystREST
from agent.tools.cortex_mcp import CortexAnalystMCP
from agent.tools.cortex_agents import CortexAgentsRun
from agent.tools.cortex_threads import CortexThreadClient


def build_tools(config: AppConfig) -> list:
    """Instantiate and return the active Cortex Analyst backend as a tool list.

    Dispatches on ``config.tools.cortex_analyst.backend``:

    - ``"cortex_agents"`` — full Cortex Agent with Bearer + token-type header;
      returns richer structured responses (text, tool_result, table blocks).
    - ``"rest"`` — thin Cortex Analyst REST wrapper; simplest option.
    - ``"mcp"`` — JSON-RPC 2.0 MCP server endpoint.

    If ``config.tools.cortex_analyst.description`` is set, it overrides the
    generic default description on the tool so the orchestrating LLM sees
    accurate capability context in its tool schema.

    Args:
        config: Fully parsed ``AppConfig`` object (from ``config.yaml``).

    Returns:
        A one-element list containing the active ``CortexAnalystBase`` subclass.

    Raises:
        ValueError: If ``backend`` is not one of the three recognised values.
    """
    ca = config.tools.cortex_analyst

    if ca.backend == "cortex_agents":
        tool = CortexAgentsRun(
            account=config.snowflake.account,
            database=ca.cortex_agents.database,
            schema_name=ca.cortex_agents.schema_name,
            agent_name=ca.cortex_agents.agent_name,
            timeout=ca.cortex_agents.timeout_seconds,
        )
        tool._thread_client = CortexThreadClient(account=config.snowflake.account)
    elif ca.backend == "rest":
        tool = CortexAnalystREST(
            name="cortex_analyst",
            account=config.snowflake.account,
            semantic_view=ca.semantic_view,
            warehouse=config.snowflake.warehouse,
            timeout=ca.rest.timeout_seconds,
        )
    elif ca.backend == "mcp":
        tool = CortexAnalystMCP(
            account=config.snowflake.account,
            semantic_view=ca.semantic_view,
            database=ca.mcp.database,
            schema_name=ca.mcp.schema_name,
            server_name=ca.mcp.server_name,
        )
    else:
        raise ValueError(f"Unknown backend: {ca.backend}")

    if ca.description:
        tool.description = ca.description.strip()

    return [tool]
