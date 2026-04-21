"""LLM factory and PAT (Programmatic Access Token) resolver.

Provides two public symbols used throughout the agent:

- ``resolve_pat`` — returns a Snowflake PAT by walking a three-step cascade
  (env var -> connections.toml -> None). Called by every HTTP backend before
  it builds an Authorization header.

- ``create_llm`` — constructs a LangChain ``ChatOpenAI`` instance aimed at the
  vLLM server running on SPCS. When the base URL is a Snowflake-hosted endpoint
  the function injects a ``Snowflake Token`` auth header and disables Qwen3's
  reasoning-trace mode.

See also: agent/tools/cortex_rest.py, agent/tools/cortex_mcp.py,
          agent/tools/cortex_agents.py (each call resolve_pat independently).
"""

import os
import tomllib
from pathlib import Path
from langchain_openai import ChatOpenAI
from agent.config import LLMConfig


# ---------------------------------------------------------------------------
# PAT resolution
# ---------------------------------------------------------------------------

def _pat_from_connection(connection_name: str) -> str | None:
    """Read the ``password`` field for *connection_name* from connections.toml.

    Snowflake CLI stores connection profiles in ``~/.snowflake/connections.toml``.
    For this project the ``password`` field holds a Programmatic Access Token
    (PAT), not a plain-text password.

    Args:
        connection_name: The section key to look up, e.g. ``"innovation-igloo"``.

    Returns:
        The PAT string if the file and section exist, otherwise ``None``.
    """
    toml_path = Path.home() / ".snowflake" / "connections.toml"
    if not toml_path.exists():
        return None
    with open(toml_path, "rb") as f:
        cfg = tomllib.load(f)
    return cfg.get(connection_name, {}).get("password")


def resolve_pat() -> str | None:
    """Return a Snowflake PAT using a three-step cascade.

    Resolution order:
        1. ``SNOWFLAKE_PAT`` environment variable — highest priority, useful for
           Docker / CI environments where secrets are injected at runtime.
        2. ``password`` field under ``[<SNOW_CONNECTION>]`` in
           ``~/.snowflake/connections.toml`` — the default developer path.
           ``SNOW_CONNECTION`` defaults to ``"innovation-igloo"`` when unset.
        3. ``None`` — callers must handle the missing-PAT case explicitly.

    Returns:
        PAT string or ``None`` if no PAT is found.

    See also: agent/tools/base.py (all three backends call this before sending
              HTTP requests).
    """
    # Step 1: explicit env override
    if pat := os.getenv("SNOWFLAKE_PAT"):
        return pat

    # Step 2: fall back to the password field in connections.toml
    connection = os.getenv("SNOW_CONNECTION", "innovation-igloo")
    return _pat_from_connection(connection)


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------

def create_llm(config: LLMConfig) -> ChatOpenAI:
    """Build a LangChain ChatOpenAI client pointed at the vLLM / SPCS endpoint.

    When ``config.base_url`` contains ``"snowflakecomputing"`` the function
    assumes the target is a Snowflake-hosted vLLM service and applies two
    Snowflake-specific overrides:

    1. **Auth header**: ChatOpenAI's default ``Authorization: Bearer <key>``
       header is replaced with ``Authorization: Snowflake Token="<pat>"``.
       Snowflake SPCS ingress rejects the standard Bearer form with a 302
       redirect; the ``Snowflake Token`` form is required.

    2. **Thinking mode**: ``extra_body.chat_template_kwargs.enable_thinking``
       is set to ``False``. This is a Qwen3-specific flag recognised by vLLM.
       Without it Qwen3 emits a ``<think>...</think>`` reasoning trace before
       every response, consuming tokens and producing unusable streaming chunks
       that confuse LangChain's message parser.

    Args:
        config: ``LLMConfig`` dataclass with ``base_url``, ``model``,
                ``max_tokens``, ``temperature``, and ``streaming`` fields.

    Returns:
        A configured ``ChatOpenAI`` instance ready for use as the agent's LLM.

    Notes:
        The ``api_key`` argument is always set to a non-empty string because
        ChatOpenAI validates that the field is not empty at construction time.
        When the ``Snowflake Token`` header is in use the api_key value is
        never sent to the server.
    """
    pat = resolve_pat()

    # ChatOpenAI requires a non-empty api_key but ignores it when Authorization
    # header is set explicitly via default_headers.
    api_key = os.getenv("LLM_API_KEY") or pat or "not-set"

    kwargs: dict = {}
    if pat and "snowflakecomputing" in config.base_url:
        # Override default OpenAI bearer auth — SPCS ingress requires this form.
        kwargs["default_headers"] = {
            "Authorization": f'Snowflake Token="{pat}"'
        }
        # Qwen3-specific: disable reasoning-trace wrapper tokens.
        # Without enable_thinking=False the model outputs <think>...</think>
        # blocks before the actual answer, which break streaming and waste
        # context budget during tool-call loops.
        kwargs["model_kwargs"] = {
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}}
        }

    return ChatOpenAI(
        base_url=config.base_url,
        api_key=api_key,
        model=config.model,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        streaming=config.streaming,
        stream_usage=True,  # Emits usage metadata in the final streaming chunk.
        **kwargs,
    )
