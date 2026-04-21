"""Abstract base class and Pydantic input schema shared by all three backends.

Defines two symbols imported by every Cortex Agent backend:

- ``CortexAgentInput`` — Pydantic model with a single ``question`` field.
  LangChain uses this schema to generate the JSON function-call schema that is
  sent to the LLM, so the LLM knows what arguments to pass when invoking the
  tool.

- ``CortexAgentBase`` — abstract ``BaseTool`` subclass that fixes the shared
  ``name``, ``description``, and ``args_schema`` for all three backends, and
  declares the abstract ``_run`` method that each backend must implement.

The three concrete backends (Cortex Analyst REST, Cortex Analyst MCP, Cortex
Agents :run) are all exposed to the self-hosted LLM under the single tool name
``cortex_agent`` — from the LLM's perspective, it is delegating the question
to "a Cortex Agent configured in Snowflake", regardless of which backend is
actually wired up by config.

See also:
    agent/tools/cortex_rest.py    -- Cortex Analyst REST backend
    agent/tools/cortex_mcp.py     -- Cortex Analyst MCP (JSON-RPC) backend
    agent/tools/cortex_agents.py  -- Cortex Agents :run backend
    agent/tools/__init__.py       -- factory that selects the active backend
"""

from abc import abstractmethod
from langchain.tools import BaseTool
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

class CortexAgentInput(BaseModel):
    """Pydantic schema for the single argument accepted by CortexAgentBase.

    LangChain serialises this class into a JSON Schema object and includes it
    in the ``tools`` array sent to the LLM, enabling structured tool-call
    generation.

    Attributes:
        question: The natural language question to forward to the Cortex
                  Agent configured in Snowflake.
    """

    question: str = Field(
        description="Natural language question to delegate to the Cortex Agent"
    )


# ---------------------------------------------------------------------------
# Abstract base tool
# ---------------------------------------------------------------------------

class CortexAgentBase(BaseTool):
    """Abstract LangChain tool shared by all three Cortex backends.

    Fixes ``name``, ``description``, and ``args_schema`` so the self-hosted
    LLM always routes to "the" Cortex Agent tool regardless of which concrete
    backend is wired up in ``config.yaml``.  Subclasses only need to implement
    ``_run``.

    Attributes:
        name: Tool identifier seen by the LLM.  All three backends share this
              name so swapping backends in config is transparent to the agent.
        description: Capability summary shown to the LLM in the tools list.
        args_schema: Pydantic class used to validate and document the tool's
                     input arguments.
    """

    # All three backends share this name so the LLM always routes to "the"
    # Cortex Agent tool regardless of which backend is actually wired up.
    name: str = "cortex_agent"
    description: str = (
        "Delegates a natural-language question to a Cortex Agent configured "
        "in your Snowflake account. Use this whenever the user asks a "
        "question that could be answered by querying data or running "
        "analytics in Snowflake. Returns the agent's answer along with any "
        "SQL, results, or citations it produced."
    )
    args_schema: type[BaseModel] = CortexAgentInput

    @abstractmethod
    def _run(self, question: str) -> str:
        """Execute the tool with the given natural language question.

        Args:
            question: Natural language question to forward to the Cortex
                      backend selected by config.

        Returns:
            Formatted string containing the answer, SQL, and/or result set.
        """
        ...


# ---------------------------------------------------------------------------
# Backwards-compatible aliases
# ---------------------------------------------------------------------------
# Older modules / configs may still import the pre-rebrand names.  Keep them
# as aliases so we don't break downstream code that hasn't been touched yet.
CortexAnalystInput = CortexAgentInput
CortexAnalystBase = CortexAgentBase
