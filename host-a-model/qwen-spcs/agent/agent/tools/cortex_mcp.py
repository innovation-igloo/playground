"""Cortex Analyst MCP (Model Context Protocol) backend.

Implements the ``cortex_analyst`` tool using Snowflake's MCP server endpoint:

    POST /api/v2/databases/<DB>/schemas/<SC>/mcp-servers/<name>

The request body is a JSON-RPC 2.0 envelope with method ``tools/call``.
This backend is the right choice when the Cortex Analyst capability is exposed
as an MCP server rather than as a standalone REST endpoint or a named agent.

See also:
    agent/tools/base.py           -- shared name, description, args_schema
    agent/llm.py:resolve_pat      -- PAT resolution used for auth
    agent/tools/cortex_rest.py    -- simpler REST alternative
    agent/tools/cortex_agents.py  -- Cortex Agents alternative (Bearer auth)
"""

import os
import json
import httpx
from agent.tools.base import CortexAnalystBase
from agent.llm import resolve_pat


# ---------------------------------------------------------------------------
# MCP backend
# ---------------------------------------------------------------------------

class CortexAnalystMCP(CortexAnalystBase):
    """Cortex Analyst tool backed by a Snowflake MCP server endpoint.

    Attributes:
        account: Snowflake account identifier (underscores converted to dashes
                 for the hostname).
        semantic_view: Fully-qualified semantic view name (``DB.SC.VIEW``).
                       Stored for reference; the MCP server resolves it
                       internally via the server configuration.
        database: Database that owns the MCP server object.
        schema_name: Schema that owns the MCP server object.
                     Named ``schema_name`` (not ``schema``) to avoid shadowing
                     Python's built-in ``schema`` attribute on Pydantic models.
        server_name: Name of the MCP server as defined in Snowflake.
    """

    account: str
    semantic_view: str
    database: str
    schema_name: str
    server_name: str

    def _build_url(self) -> str:
        """Construct the MCP server endpoint URL.

        Account underscores are replaced with dashes for the hostname — the
        same convention used by cortex_rest.py and cortex_agents.py.

        Returns:
            Full HTTPS URL for the MCP server endpoint.
        """
        # Snowflake hostnames use dashes; account identifiers use underscores.
        host = self.account.replace("_", "-")
        return (
            f"https://{host}.snowflakecomputing.com"
            f"/api/v2/databases/{self.database}"
            f"/schemas/{self.schema_name}"
            f"/mcp-servers/{self.server_name}"
        )

    def _run(self, question: str) -> str:
        """Send *question* to the MCP server and return a formatted response.

        Auth header: ``Authorization: Snowflake Token="<pat>"``
        Same form as the REST backend; the MCP endpoint also accepts this
        Snowflake-specific token format.

        Request body is a JSON-RPC 2.0 envelope::

            {
              "jsonrpc": "2.0",
              "id": 1,
              "method": "tools/call",
              "params": {
                "name": "<slug>",
                "arguments": {"message": "<question>"}
              }
            }

        The ``params.name`` slug is the server name lowercased with underscores
        converted to dashes.  This matches MCP's kebab-case tool-name convention
        and differs from the URL path segment (which preserves the original
        ``server_name`` casing).

        Args:
            question: Natural language question forwarded to the MCP server.

        Returns:
            Concatenated text blocks from the response, or raw JSON on fallback.
        """
        pat = resolve_pat()  # See also: agent/llm.py:resolve_pat
        if not pat:
            return "Error: SNOWFLAKE_PAT not set and not found in connections.toml"

        url = self._build_url()
        # Cortex MCP endpoint uses the same Snowflake Token auth as the REST API.
        headers = {
            "Authorization": f'Snowflake Token="{pat}"',
            "Content-Type": "application/json",
        }
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                # MCP tool slugs are kebab-case: lowercase + underscores -> dashes.
                "name": self.server_name.lower().replace("_", "-"),
                "arguments": {
                    "message": question,
                },
            },
        }

        try:
            resp = httpx.post(url, headers=headers, json=body, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            return f"MCP error ({e.response.status_code}): {e.response.text}"
        except httpx.RequestError as e:
            return f"Request failed: {e}"

        return self._format_response(data)

    def _format_response(self, data: dict) -> str:
        """Extract text content from a JSON-RPC 2.0 MCP response.

        The MCP response has this shape::

            {
              "jsonrpc": "2.0",
              "id": 1,
              "result": {
                "content": [
                  {"type": "text", "text": "..."},
                  ...
                ]
              }
            }

        Only ``type: "text"`` blocks are extracted.  Other block types (if any)
        are silently skipped; the raw ``result`` JSON is returned as a fallback
        when no text blocks are found.

        Args:
            data: Parsed JSON-RPC 2.0 response body.

        Returns:
            Text content joined by double newlines, or raw JSON on fallback.
        """
        result = data.get("result", {})
        content = result.get("content", [])
        # Collect only text-type blocks; ignore non-text blocks.
        parts = [block["text"] for block in content if block.get("type") == "text"]
        return "\n\n".join(parts) if parts else json.dumps(result, indent=2)
