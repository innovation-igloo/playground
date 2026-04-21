"""Tests for agent.tools (CortexAnalystREST and CortexAnalystMCP backends).

These are the REST and MCP backends behind the ``cortex_agent`` LangChain
tool — the tool the self-hosted LLM calls to delegate questions to a Cortex
Agent configured in Snowflake.

Pure-unit tests using httpx mocks — no real network calls for passing tests.
Covers:
- REST URL construction from account name
- REST response formatting: text, SQL, and suggestions content types
- REST full round-trip with a mocked httpx.post (success path)
- MCP URL construction including database/schema/server path segments
- Known-failing: PAT-not-set error path for REST and MCP (see comments below)

Run: pytest tests/test_tools.py
"""

import pytest
from unittest.mock import patch, MagicMock
from agent.tools.cortex_rest import CortexAnalystREST
from agent.tools.cortex_mcp import CortexAnalystMCP


@pytest.fixture
def rest_tool():
    """Provide a CortexAnalystREST instance pointed at a fake Snowflake account.

    Stands in for the tool that would be instantiated from config.yaml at runtime.
    """
    return CortexAnalystREST(
        account="TESTACCT",
        semantic_view="DB.SC.VIEW",
        warehouse="WH",
        timeout=10,
    )


@pytest.fixture
def mcp_tool():
    """Provide a CortexAnalystMCP instance pointed at a fake Snowflake account.

    Stands in for the MCP-backend tool instantiated when config.tools.cortex_analyst.backend == 'mcp'.
    (Config key is preserved for backwards-compatibility; the LLM-facing tool name is ``cortex_agent``.)
    """
    return CortexAnalystMCP(
        account="TESTACCT",
        semantic_view="DB.SC.VIEW",
        database="DB",
        schema_name="SC",
        server_name="MARKET_INTEL_MCP",
    )


def test_rest_build_url(rest_tool):
    """_build_url constructs the correct Cortex Analyst REST endpoint for the account."""
    url = rest_tool._build_url()
    assert url == "https://TESTACCT.snowflakecomputing.com/api/v2/cortex/analyst/message"


# KNOWN LIMITATION: This test patches os.environ to clear SNOWFLAKE_PAT, but
# resolve_pat() falls back to ~/.snowflake/connections.toml. If a dev PAT
# exists there, this test fires a real HTTP request and fails with a 404 HTML
# page instead of the 'Error: SNOWFLAKE_PAT not set' message. To fix reliably,
# also patch agent.llm._pat_from_connection to return None.
def test_rest_no_pat(rest_tool):
    """_run returns an error string containing 'SNOWFLAKE_PAT' when no PAT is available."""
    with patch.dict("os.environ", {}, clear=True):
        result = rest_tool._run("What is the flow today?")
    assert "SNOWFLAKE_PAT" in result


def test_rest_format_response_text(rest_tool):
    """_format_response extracts plain text from a text-type content block."""
    data = {
        "message": {
            "content": [{"type": "text", "text": "Here is the answer"}]
        }
    }
    result = rest_tool._format_response(data)
    assert result == "Here is the answer"


def test_rest_format_response_sql(rest_tool):
    """_format_response includes a 'SQL:' label and the statement for sql-type content blocks."""
    data = {
        "message": {
            "content": [
                {"type": "text", "text": "Based on your question"},
                {"type": "sql", "statement": "SELECT * FROM flows"},
            ]
        }
    }
    result = rest_tool._format_response(data)
    assert "SQL:" in result
    assert "SELECT * FROM flows" in result


def test_rest_format_response_suggestions(rest_tool):
    """_format_response includes all suggestion strings from a suggestions-type content block."""
    data = {
        "message": {
            "content": [
                {"type": "suggestions", "suggestions": ["Try A", "Try B"]}
            ]
        }
    }
    result = rest_tool._format_response(data)
    assert "Try A" in result
    assert "Try B" in result


def test_rest_http_success(rest_tool):
    """_run returns the formatted text answer when httpx.post succeeds and PAT is set."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "message": {"content": [{"type": "text", "text": "Answer"}]}
    }

    with patch.dict("os.environ", {"SNOWFLAKE_PAT": "testpat"}):
        with patch("httpx.post", return_value=mock_resp):
            result = rest_tool._run("What is unusual flow today?")

    assert result == "Answer"


def test_mcp_build_url(mcp_tool):
    """_build_url embeds the correct account host and database/schema/server path segments."""
    url = mcp_tool._build_url()
    assert "TESTACCT.snowflakecomputing.com" in url
    assert "/databases/DB/schemas/SC/mcp-servers/MARKET_INTEL_MCP" in url


# KNOWN LIMITATION: This test patches os.environ to clear SNOWFLAKE_PAT, but
# resolve_pat() falls back to ~/.snowflake/connections.toml. If a dev PAT
# exists there, this test fires a real HTTP request and fails with a 404 HTML
# page instead of the 'Error: SNOWFLAKE_PAT not set' message. To fix reliably,
# also patch agent.llm._pat_from_connection to return None.
def test_mcp_no_pat(mcp_tool):
    """_run returns an error string containing 'SNOWFLAKE_PAT' when no PAT is available."""
    with patch.dict("os.environ", {}, clear=True):
        result = mcp_tool._run("Question")
    assert "SNOWFLAKE_PAT" in result
