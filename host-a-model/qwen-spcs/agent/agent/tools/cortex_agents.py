"""Cortex Agents :run backend.

Implements the ``cortex_analyst`` tool using the Cortex Agents API:

    POST /api/v2/databases/<DB>/schemas/<SC>/agents/<name>:run

This backend differs from the REST and MCP alternatives in two important ways:

1. **Auth scheme** — uses ``Authorization: Bearer <pat>`` plus the explicit
   ``X-Snowflake-Authorization-Token-Type: PROGRAMMATIC_ACCESS_TOKEN`` header.
   The REST and MCP backends instead use ``Authorization: Snowflake Token="..."``.

2. **Response richness** — the ``content`` array can contain three block types
   (``text``, ``tool_result``, ``table``) each with different sub-structures,
   compared to the flat ``text``-only blocks returned by the REST backend.

Multi-turn threading:
    When a ``CortexThreadClient`` is attached (via ``_thread_client``) and a
    LangGraph ``thread_id`` is set (via ``_current_thread_id``), each ``:run``
    call includes a Snowflake ``thread_id`` in the request body so the Cortex
    Agent can resolve follow-up questions with full conversation context.
    Both attributes are set post-construction by the tool factory and
    ``call_tools`` node; they are not Pydantic fields.

Use this backend when the analyst capability is packaged as a named Cortex
Agent and you want richer structured output (inline SQL, result sets, tables).

See also:
    agent/tools/base.py              -- shared name, description, args_schema
    agent/tools/cortex_threads.py    -- thread lifecycle management
    agent/llm.py:resolve_pat         -- PAT resolution used for auth
    agent/tools/cortex_rest.py       -- REST alternative (simpler auth + response)
    agent/tools/cortex_mcp.py        -- MCP alternative (JSON-RPC 2.0)
"""

import json
import httpx
from agent.tools.base import CortexAnalystBase
from agent.llm import resolve_pat

_SKIP_STATUS = frozenset({"completed"})

_http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(120.0),
    limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
)


# ---------------------------------------------------------------------------
# Cortex Agents backend
# ---------------------------------------------------------------------------

class CortexAgentsRun(CortexAnalystBase):
    """Cortex Analyst tool backed by the Cortex Agents :run endpoint.

    Pydantic attributes:
        account: Snowflake account identifier (underscores converted to dashes
                 for the hostname).
        database: Database that owns the agent object.
        schema_name: Schema that owns the agent object.  Named ``schema_name``
                     to avoid shadowing Pydantic's reserved ``schema`` attribute.
        agent_name: Name of the Cortex Agent as defined in Snowflake.
        timeout: HTTP request timeout in seconds (default 120 — agents can be
                 slow when they invoke multiple internal tools).

    Non-Pydantic attributes (set post-construction):
        _thread_client: ``CortexThreadClient`` instance injected by the tool
                        factory.  When present, a Snowflake thread is created
                        (or reused from cache) per LangGraph session.
        _current_thread_id: LangGraph ``thread_id`` set by ``call_tools`` before
                            each invocation.  Used as the cache key when looking
                            up the corresponding Snowflake thread.
    """

    account: str
    database: str
    schema_name: str
    agent_name: str
    timeout: int = 120

    def model_post_init(self, __context) -> None:
        self._thread_client = None
        self._current_thread_id: str | None = None
        self._stream_writer = None

    def _inject_thread_context(self, body: dict) -> None:
        """Add thread_id and parent_message_id to *body* in-place if threading is active."""
        if self._thread_client is not None and self._current_thread_id is not None:
            sf_thread_id, parent_msg_id = self._thread_client.get_thread_context(self._current_thread_id)
            if sf_thread_id is not None:
                body["thread_id"] = sf_thread_id
                body["parent_message_id"] = parent_msg_id

    def _update_thread_message_id(self, metadata: dict) -> None:
        """Cache assistant_message_id from *metadata* for the next turn's parent pointer."""
        if self._thread_client is not None and self._current_thread_id is not None:
            asst_msg_id = metadata.get("assistant_message_id")
            if asst_msg_id is not None:
                self._thread_client.update_last_message_id(self._current_thread_id, asst_msg_id)

    def _build_url(self) -> str:
        """Construct the Cortex Agents :run endpoint URL.

        The ``:run`` suffix is a Snowflake REST API convention for invoking a
        named resource — analogous to a remote procedure call on the agent
        object rather than a CRUD operation.

        Returns:
            Full HTTPS URL including the ``:run`` action suffix.
        """
        # Snowflake hostnames use dashes; account identifiers use underscores.
        host = self.account.replace("_", "-")
        return (
            f"https://{host}.snowflakecomputing.com"
            f"/api/v2/databases/{self.database}"
            f"/schemas/{self.schema_name}"
            f"/agents/{self.agent_name}:run"
        )

    def _run(self, question: str) -> str:
        """Send *question* to the Cortex Agent and return a formatted response.

        Auth headers (different from REST and MCP backends):
            - ``Authorization: Bearer <pat>`` — note Bearer, not Snowflake Token.
            - ``X-Snowflake-Authorization-Token-Type: PROGRAMMATIC_ACCESS_TOKEN``
              — explicit token-type discriminator required by the Agents API.

        The REST and MCP backends use ``Authorization: Snowflake Token="..."``
        instead; this backend is the only one that uses the Bearer form.

        Request body shape::

            {
              "messages": [
                {"role": "user", "content": [{"type": "text", "text": "..."}]}
              ],
              "stream": false
            }

        Args:
            question: Natural language question forwarded to the Cortex Agent.

        Returns:
            Formatted multi-part string, or raw JSON on fallback.
        """
        pat = resolve_pat()  # See also: agent/llm.py:resolve_pat
        if not pat:
            return "Error: SNOWFLAKE_PAT not set and not found in connections.toml"

        url = self._build_url()
        # Cortex Agents :run uses Bearer + explicit token-type header.
        # This differs from the REST/MCP backends which use Snowflake Token="...".
        headers = {
            "Authorization": f"Bearer {pat}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Snowflake-Authorization-Token-Type": "PROGRAMMATIC_ACCESS_TOKEN",
        }
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": question}],
                }
            ],
            "stream": False,
        }

        self._inject_thread_context(body)

        try:
            resp = httpx.post(url, headers=headers, json=body, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            return f"Cortex Agent error ({e.response.status_code}): {e.response.text}"
        except httpx.RequestError as e:
            return f"Request failed: {e}"

        self._update_thread_message_id(data.get("metadata", {}))
        return self._format_response(data)

    async def _arun(self, question: str) -> str:
        """Async streaming version of _run — forwards Cortex tokens to the client in real-time.

        Uses ``httpx.AsyncClient`` with ``stream=True`` on the Cortex Agents ``:run``
        endpoint.  As chunks arrive they are classified into three categories:

        - **Status events** (``status`` key, no ``text``) — forwarded immediately as
          ``downstream_status`` custom events so the client can show progress
          ("Planning the next steps", "Executing SQL", etc.).
        - **Pre-tool text chunks** (``text`` key, ``tool_result_seen=False``) — Cortex's
          internal reasoning trace; accumulated but not streamed (private to Cortex).
        - **Final answer text chunks** (``text`` key, ``tool_result_seen=True``) — the
          synthesised answer; forwarded as ``downstream_token`` custom events AND
          accumulated for the returned ToolMessage string.

        Falls back to ``_run`` (non-streaming) if no ``_stream_writer`` is set, so the
        tool degrades gracefully when invoked outside a LangGraph streaming context.
        """
        if self._stream_writer is None:
            return self._run(question)

        pat = resolve_pat()
        if not pat:
            return "Error: SNOWFLAKE_PAT not set and not found in connections.toml"

        url = self._build_url()
        headers = {
            "Authorization": f"Bearer {pat}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Snowflake-Authorization-Token-Type": "PROGRAMMATIC_ACCESS_TOKEN",
        }
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": question}],
                }
            ],
            "stream": True,
        }
        self._inject_thread_context(body)

        tool_result_seen = False
        final_parts: list[str] = []
        all_parts: list[str] = []

        try:
            async with _http_client.stream(
                "POST", url, headers=headers, json=body
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue

                    try:
                        chunk = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    status = chunk.get("status", "")

                    # Status event — forward as downstream_status
                    if status and "text" not in chunk and "content" not in chunk and status not in _SKIP_STATUS:
                        self._stream_writer({
                            "type": "downstream_status",
                            "content": chunk.get("message") or status,
                            "metadata": {"status": status},
                        })

                    # Tool result received — everything after this is final answer
                    if chunk.get("type") == "cortex_analyst_text_to_sql" and status == "success":
                        tool_result_seen = True

                    # Text chunk
                    if "text" in chunk:
                        text: str = chunk["text"]
                        all_parts.append(text)
                        if tool_result_seen:
                            final_parts.append(text)
                            self._stream_writer({
                                "type": "downstream_token",
                                "content": text,
                            })

                    # Final completion chunk — update thread message_id
                    if status == "completed":
                        self._update_thread_message_id(chunk.get("metadata", {}))

        except httpx.HTTPStatusError as e:
            return f"Cortex Agent error ({e.response.status_code}): {e.response.text}"
        except httpx.RequestError as e:
            return f"Request failed: {e}"

        # If Cortex answered without a tool call, all text is the answer
        return "".join(final_parts) or "".join(all_parts) or "(No response from Cortex Agent)"

    def _format_response(self, data: dict) -> str:
        """Render the Cortex Agent response as a human-readable string.

        The top-level ``content`` array can contain three block types:

        - ``text`` — plain narrative answer; appended verbatim.
        - ``tool_result`` — nested structure from an internal tool call.
          Contains a ``content`` list of blocks; only ``type: "json"`` blocks
          are processed.  The JSON payload may include:
            - ``sql`` — the generated SQL statement (fenced code block).
            - ``result_set`` — query results forwarded to ``_format_result_set``.
            - ``text`` — supplemental narrative from the tool.
        - ``table`` — a named result set with an optional title.  The result
          set is forwarded to ``_format_result_set``; the title is bolded.

        Unknown block types are silently skipped.  The raw response JSON is
        returned as a fallback when no recognisable blocks are found.

        Args:
            data: Parsed JSON response body from the Cortex Agents API.

        Returns:
            Multi-part string with sections joined by double newlines.
        """
        parts = []
        content = data.get("content", [])

        for item in content:
            item_type = item.get("type", "")

            if item_type == "text":
                # Plain narrative answer from the agent.
                text = item.get("text", "")
                if text:
                    parts.append(text)

            elif item_type == "tool_result":
                # Result from an internal tool invocation by the agent.
                tr = item.get("tool_result", {})
                for block in tr.get("content", []):
                    if block.get("type") == "json":
                        j = block["json"]
                        if j.get("sql"):
                            # Generated SQL — rendered as a fenced code block.
                            parts.append(f"**SQL:**\n```sql\n{j['sql']}\n```")
                        if j.get("result_set"):
                            # Query results — rendered as an ASCII table.
                            parts.append(self._format_result_set(j["result_set"]))
                        if j.get("text"):
                            # Supplemental narrative from the tool.
                            parts.append(j["text"])

            elif item_type == "table":
                # Top-level table block with optional title.
                tbl = item.get("table", {})
                rs = tbl.get("result_set")
                if rs:
                    title = tbl.get("title", "")
                    if title:
                        parts.append(f"**{title}**")
                    parts.append(self._format_result_set(rs))

        return "\n\n".join(parts) if parts else json.dumps(data, indent=2)

    def _format_result_set(self, result_set: dict) -> str:
        """Render a Snowflake result set as a hand-rolled ASCII table.

        Column widths are computed as the maximum of the header width and the
        widest data value in that column.  Each cell is left-padded with spaces
        to the column width.  The header and data rows are separated by a line
        of the form ``---|----|---`` (dashes equal to the column width,
        connected by ``-|-`` separators).

        Args:
            result_set: Dict with structure::

                {
                  "resultSetMetaData": {"rowType": [{"name": "COL"}, ...]},
                  "data": [["val1", "val2", ...], ...]
                }

        Returns:
            Multi-line string containing the formatted ASCII table, or
            ``"(no results)"`` if the result set is empty.
        """
        meta = result_set.get("resultSetMetaData", {})
        columns = [col["name"] for col in meta.get("rowType", [])]
        rows = result_set.get("data", [])

        if not columns or not rows:
            return "(no results)"

        # Initialise column widths from header lengths, then expand for data.
        col_widths = [len(c) for c in columns]
        for row in rows:
            for i, val in enumerate(row):
                if i < len(col_widths):
                    col_widths[i] = max(col_widths[i], len(str(val)))

        # Header row: columns padded to their computed widths, separated by " | ".
        header = " | ".join(c.ljust(col_widths[i]) for i, c in enumerate(columns))
        # Separator: dashes of column width joined by "-|-" (not " | ").
        separator = "-|-".join("-" * w for w in col_widths)
        lines = [header, separator]
        for row in rows:
            line = " | ".join(
                str(row[i] if i < len(row) else "").ljust(col_widths[i])
                for i in range(len(columns))
            )
            lines.append(line)

        return "\n".join(lines)
