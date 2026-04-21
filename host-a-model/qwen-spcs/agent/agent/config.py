"""Pydantic-typed YAML config loader for the Qwen SPCS LangGraph agent.

Defines the full configuration schema using nested Pydantic models. A
``backend`` discriminator on ``CortexAnalystConfig`` selects one of three
Cortex Analyst integration strategies: direct REST, MCP server, or Cortex
Agents. ``load_config`` resolves the config file path and deserialises the
YAML into an ``AppConfig`` instance.

See also: agent/graph.py (consumes AppConfig), server/app.py (calls load_config).
"""

from pathlib import Path
from pydantic import BaseModel, Field
import yaml
import os


# ============================================================
# SECTION: LLM + Snowflake
# Core connection settings for the language model and Snowflake account.
# ============================================================


class LLMConfig(BaseModel):
    """Settings for the self-hosted vLLM / ChatOpenAI client.

    Attrs:
        base_url: HTTP endpoint of the vLLM server (SPCS public endpoint).
        model: Model identifier string passed to the OpenAI-compatible API.
        max_tokens: Maximum tokens the model may generate per turn.
        temperature: Sampling temperature (0 = deterministic, 1 = creative).
        streaming: Whether to enable server-sent-event streaming responses.
    """

    base_url: str
    model: str
    max_tokens: int = 2048
    temperature: float = 0.7
    streaming: bool = True


class SnowflakeConfig(BaseModel):
    """Snowflake account coordinates used when making Cortex API calls.

    Attrs:
        account: Snowflake account identifier (e.g. ``myorg-myaccount``).
        warehouse: Virtual warehouse to bill query costs against.
    """

    account: str
    warehouse: str


# ============================================================
# SECTION: Tool backends (REST / MCP / Cortex Agents)
# Three alternative backends for Cortex Analyst; exactly one is active per run.
# ============================================================


class RESTConfig(BaseModel):
    """Parameters for the direct Cortex Analyst REST backend.

    Attrs:
        timeout_seconds: HTTP request timeout in seconds.
        stream: Whether to stream the Cortex Analyst response.
    """

    timeout_seconds: int = 30
    stream: bool = False


class MCPConfig(BaseModel):
    """Parameters for the MCP server backend.

    Attrs:
        database: Snowflake database containing the MCP server object.
        schema_name: Schema containing the MCP server object.
        server_name: Name of the MCP server Snowflake object.

    Notes:
        ``model_config`` is set so that the YAML key ``schema`` maps to
        ``schema_name`` without conflicting with Pydantic's reserved ``schema``
        attribute.
    """

    database: str
    schema_name: str = Field(alias="schema")  # 'schema' is pydantic-reserved, aliased from YAML key.
    server_name: str

    model_config = {"populate_by_name": True}  # Accept both 'schema' and 'schema_name' as input keys.


class CortexAgentsConfig(BaseModel):
    """Parameters for the Cortex Agents backend.

    Attrs:
        database: Snowflake database containing the agent.
        schema_name: Schema containing the agent.
        agent_name: Name of the Cortex Agent Snowflake object.
        timeout_seconds: HTTP request timeout in seconds.
    """

    database: str
    schema_name: str = Field(alias="schema")  # 'schema' is pydantic-reserved, aliased from YAML key.
    agent_name: str
    timeout_seconds: int = 60

    model_config = {"populate_by_name": True}  # Accept both 'schema' and 'schema_name' as input keys.


class CortexAnalystConfig(BaseModel):
    """Selects and configures one of three Cortex Analyst backends.

    The ``backend`` field acts as a discriminator. The matching sub-config
    (``rest``, ``mcp``, or ``cortex_agents``) provides backend-specific params.

    Attrs:
        backend: One of ``"rest"``, ``"mcp"``, or ``"cortex_agents"``.
        semantic_view: Fully-qualified Snowflake semantic view name used by all backends.
        description: Optional override for the tool description shown to the LLM.
            When set, replaces the generic default in ``CortexAgentBase``.  Use
            this to give the orchestrating LLM accurate capability context so it
            knows what to delegate and when.  Lives in config.yaml (gitignored).
        rest: REST backend config (always present; ignored unless backend=="rest").
        mcp: MCP backend config (required when backend=="mcp").
        cortex_agents: Cortex Agents backend config (required when backend=="cortex_agents").
    """

    backend: str = "rest"
    semantic_view: str
    description: str | None = None
    rest: RESTConfig = RESTConfig()
    mcp: MCPConfig | None = None
    cortex_agents: CortexAgentsConfig | None = None


class ToolsConfig(BaseModel):
    """Container for all tool backend configurations.

    Attrs:
        cortex_analyst: Config for the Cortex Analyst tool (the only tool currently registered).
    """

    cortex_analyst: CortexAnalystConfig


# ============================================================
# SECTION: Agent + Server
# Behavioural knobs for the LangGraph agent and FastAPI server.
# ============================================================


class LoggingConfig(BaseModel):
    """Logging output settings.

    Attrs:
        level: Root log level (DEBUG | INFO | WARNING | ERROR).
        log_dir: Directory for rotating log files (relative to CWD).
        max_bytes: Max size per log file before rotation (bytes).
        backup_count: Number of rotated log files to retain.
    """

    level: str = "INFO"
    log_dir: str = "logs"
    max_bytes: int = 10_485_760  # 10 MB
    backup_count: int = 5


class AgentConfig(BaseModel):
    """Runtime behaviour settings for the LangGraph agent.

    Attrs:
        checkpointer: Checkpointer backend; ``"memory"`` uses InMemorySaver.
        max_turns: Hard cap on tool-call iterations before forcing END.
        system_prompt: System message injected at position 0 of each conversation.
    """

    checkpointer: str = "memory"
    max_turns: int = 10
    system_prompt: str = ""


class ServerConfig(BaseModel):
    """FastAPI server binding and CORS settings.

    Attrs:
        host: Interface to bind (``"0.0.0.0"`` inside SPCS containers).
        port: TCP port to listen on.
        cors_origins: Allowed origins for cross-origin requests (e.g. the React UI).
    """

    host: str = "0.0.0.0"
    port: int = 8080
    cors_origins: list[str] = ["http://localhost:3000"]


class AppConfig(BaseModel):
    """Root configuration object for the entire agent application.

    Instantiated once at startup by ``load_config`` and passed to
    ``create_agent`` and the FastAPI app factory.

    Attrs:
        llm: LLM connection settings.
        snowflake: Snowflake account credentials.
        tools: Tool backend configuration.
        agent: LangGraph agent behavioural settings.
        server: FastAPI binding and CORS settings.
    """

    llm: LLMConfig
    snowflake: SnowflakeConfig
    tools: ToolsConfig
    agent: AgentConfig = AgentConfig()
    server: ServerConfig = ServerConfig()
    logging: LoggingConfig = LoggingConfig()


# ============================================================
# SECTION: Loader
# Resolves config file path and deserialises YAML into AppConfig.
# ============================================================


def load_config(path: str | None = None) -> AppConfig:
    """Load and validate the application config from a YAML file.

    Path resolution precedence (first match wins):
        1. ``path`` argument passed directly to this function.
        2. ``CONFIG_PATH`` environment variable.
        3. ``config.yaml`` in the current working directory.

    Args:
        path: Optional explicit path to the config YAML file.

    Returns:
        A fully validated ``AppConfig`` instance.

    Raises:
        FileNotFoundError: If the resolved path does not exist.
        pydantic.ValidationError: If the YAML does not match the schema.
    """
    config_path = Path(path or os.getenv("CONFIG_PATH", "config.yaml"))
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    return AppConfig(**raw)
