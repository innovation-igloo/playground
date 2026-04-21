"""Tests for agent.config (Pydantic configuration models and YAML loader).

Covers:
- LLMConfig default field values
- MCPConfig 'schema' -> schema_name alias (Pydantic field_alias for reserved keyword)
- CortexAnalystConfig defaults (backend, mcp)
- AppConfig full parse with nested sub-configs and default agent/server values
- AppConfig ValidationError when a required field (llm.model) is absent
- load_config reading a YAML file from disk and returning a parsed AppConfig

Run: pytest tests/test_config.py
"""

import pytest
from pydantic import ValidationError
from agent.config import (
    AppConfig,
    LLMConfig,
    SnowflakeConfig,
    RESTConfig,
    MCPConfig,
    CortexAnalystConfig,
    ToolsConfig,
    AgentConfig,
    ServerConfig,
    load_config,
)


def test_llm_config_defaults():
    """LLMConfig applies defaults when only required fields are provided."""
    cfg = LLMConfig(base_url="http://localhost", model="qwen")
    assert cfg.max_tokens == 2048
    assert cfg.temperature == 0.7
    assert cfg.streaming is True


def test_mcp_config_alias():
    """MCPConfig accepts 'schema' key from YAML and exposes it as .schema_name."""
    cfg = MCPConfig(**{"database": "DB", "schema": "SC", "server_name": "SRV"})
    assert cfg.schema_name == "SC"


def test_cortex_analyst_config_defaults():
    """CortexAnalystConfig defaults to rest backend with no MCP block."""
    cfg = CortexAnalystConfig(semantic_view="DB.SC.VIEW")
    assert cfg.backend == "rest"
    assert cfg.mcp is None


def test_app_config_full():
    """AppConfig with minimal required fields defaults agent.max_turns and server.port."""
    raw = {
        "llm": {"base_url": "http://x", "model": "m"},
        "snowflake": {"account": "ACC", "warehouse": "WH"},
        "tools": {
            "cortex_analyst": {
                "backend": "rest",
                "semantic_view": "DB.SC.VIEW",
            }
        },
    }
    cfg = AppConfig(**raw)
    assert cfg.llm.model == "m"
    assert cfg.agent.max_turns == 10
    assert cfg.server.port == 8080


def test_app_config_missing_required():
    """AppConfig raises ValidationError when llm.model is missing."""
    with pytest.raises(ValidationError):
        AppConfig(
            llm={"base_url": "http://x"},
            snowflake={"account": "ACC", "warehouse": "WH"},
            tools={"cortex_analyst": {"semantic_view": "DB.SC.V"}},
        )


def test_load_config(tmp_path):
    """load_config reads a YAML file from disk and returns a parsed AppConfig."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        """
llm:
  base_url: "http://localhost"
  model: "test-model"
snowflake:
  account: "TESTACCT"
  warehouse: "WH"
tools:
  cortex_analyst:
    backend: rest
    semantic_view: "DB.SC.VIEW"
"""
    )
    cfg = load_config(str(cfg_file))
    assert cfg.llm.model == "test-model"
    assert cfg.snowflake.account == "TESTACCT"
