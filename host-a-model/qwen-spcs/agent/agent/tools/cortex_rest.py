"""Cortex Analyst REST backend.

Implements the ``cortex_analyst`` tool using the Cortex Analyst REST API:

    POST /api/v2/cortex/analyst/message

Supports two execution paths:

- ``_run`` (sync, fallback): Non-streaming single-shot request. Returns the
  analyst's text interpretation and generated SQL without executing the SQL.
  Used when ``_stream_writer`` is not available (outside a LangGraph streaming
  context).

- ``_arun`` (async, primary): Streaming request with ``stream=true``. Emits
  ``downstream_status`` events as status updates arrive (interpreting question,
  generating SQL, etc.) and ``downstream_token`` events for the text
  interpretation so the UI renders live. Once the SQL statement is assembled it
  is executed via an injected Snowpark session and the results are formatted
  into the returned string.

Non-Pydantic runtime attributes (set post-construction):
    _stream_writer: LangGraph ``get_stream_writer()`` callable. Injected by
        ``call_tools`` before each invocation.
    _snowpark_session: ``snowflake.snowpark.Session`` instance. Injected by the
        FastAPI lifespan after agent startup.

See also:
    agent/tools/base.py           -- shared name, description, args_schema
    agent/llm.py:resolve_pat      -- PAT resolution used for auth
    agent/tools/cortex_mcp.py     -- MCP alternative (JSON-RPC 2.0)
    agent/tools/cortex_agents.py  -- Cortex Agents alternative (Bearer auth)
"""

import json
import httpx
from agent.tools.base import CortexAnalystBase
from agent.llm import resolve_pat
from agent.tools.cortex_agents import _http_client


# ---------------------------------------------------------------------------
# Status label mapping
# ---------------------------------------------------------------------------

_STATUS_LABELS: dict[str, str] = {
    "interpreting_question": "Interpreting your question...",
    "generating_sql": "Generating SQL...",
    "validating_sql": "Validating SQL...",
    "generating_suggestions": "Generating suggestions...",
}


# ---------------------------------------------------------------------------
# REST backend
# ---------------------------------------------------------------------------

class CortexAnalystREST(CortexAnalystBase):
    """Cortex Analyst tool backed by the direct REST API endpoint.

    Pydantic attributes:
        account: Snowflake account identifier (underscores converted to dashes
                 for the hostname).
        semantic_view: Fully-qualified semantic view name (``DB.SC.VIEW``).
        warehouse: Snowflake warehouse to execute generated SQL against.
        timeout: HTTP request timeout in seconds (default 60).

    Non-Pydantic attributes (set post-construction):
        _stream_writer: Injected by ``call_tools`` before each invocation.
        _snowpark_session: Injected by server lifespan after agent startup.
    """

    account: str
    semantic_view: str
    warehouse: str
    timeout: int = 60

    def model_post_init(self, __context) -> None:
        self._stream_writer = None
        self._snowpark_session = None

    def _build_url(self) -> str:
        host = self.account.replace("_", "-")
        return f"https://{host}.snowflakecomputing.com/api/v2/cortex/analyst/message"

    def _build_headers(self, pat: str) -> dict:
        return {
            "Authorization": f"Bearer {pat}",
            "X-Snowflake-Authorization-Token-Type": "PROGRAMMATIC_ACCESS_TOKEN",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _build_body(self, question: str, stream: bool) -> dict:
        return {
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": question}],
                }
            ],
            "semantic_view": self.semantic_view,
            "stream": stream,
        }

    # ------------------------------------------------------------------
    # Sync fallback (no streaming context)
    # ------------------------------------------------------------------

    def _run(self, question: str) -> str:
        pat = resolve_pat()
        if not pat:
            return "Error: SNOWFLAKE_PAT not set and not found in connections.toml"

        try:
            resp = httpx.post(
                self._build_url(),
                headers=self._build_headers(pat),
                json=self._build_body(question, stream=False),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            return f"Cortex Analyst error ({e.response.status_code}): {e.response.text}"
        except httpx.RequestError as e:
            return f"Request failed: {e}"

        return self._format_response(data)

    # ------------------------------------------------------------------
    # Async streaming path (primary)
    # ------------------------------------------------------------------

    async def _arun(self, question: str) -> str:
        """Stream from Cortex Analyst, execute generated SQL via Snowpark."""
        if self._stream_writer is None:
            return self._run(question)

        pat = resolve_pat()
        if not pat:
            return "Error: SNOWFLAKE_PAT not set and not found in connections.toml"

        content_blocks: dict[int, dict] = {}

        try:
            async with _http_client.stream(
                "POST",
                self._build_url(),
                headers=self._build_headers(pat),
                json=self._build_body(question, stream=True),
            ) as resp:
                if resp.status_code >= 400:
                    error_body = (await resp.aread()).decode(errors="replace")
                    return f"Cortex Analyst error ({resp.status_code}): {error_body}"
                current_event = ""
                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                        continue
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw:
                        continue

                    try:
                        chunk = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if current_event == "status":
                        status = chunk.get("status", "")
                        label = _STATUS_LABELS.get(status)
                        if label:
                            self._stream_writer({
                                "type": "downstream_status",
                                "content": label,
                                "metadata": {"status": status},
                            })

                    elif current_event == "message.content.delta":
                        idx = chunk.get("index", 0)
                        delta_type = chunk.get("type", "")

                        if delta_type == "text":
                            text_delta = chunk.get("text_delta", "")
                            block = content_blocks.setdefault(idx, {"type": "text", "text": ""})
                            block["text"] += text_delta
                            if text_delta:
                                self._stream_writer({
                                    "type": "downstream_token",
                                    "content": text_delta,
                                })

                        elif delta_type == "sql":
                            stmt_delta = chunk.get("statement_delta", "")
                            block = content_blocks.setdefault(idx, {"type": "sql", "statement": ""})
                            block["statement"] += stmt_delta

                        elif delta_type == "suggestions":
                            s_delta = chunk.get("suggestions_delta", {})
                            s_idx = s_delta.get("index", 0)
                            s_text = s_delta.get("suggestion_delta", "")
                            block = content_blocks.setdefault(idx, {"type": "suggestions", "suggestions": {}})
                            block["suggestions"].setdefault(s_idx, "")
                            block["suggestions"][s_idx] += s_text

        except httpx.HTTPStatusError:
            return "Cortex Analyst error: unexpected HTTP error"
        except httpx.RequestError as e:
            return f"Request failed: {e}"

        # Execute SQL if a statement was returned
        sql_statement = None
        for block in content_blocks.values():
            if block["type"] == "sql" and block.get("statement"):
                sql_statement = block["statement"].strip()
                break

        result_table = ""
        if sql_statement and self._snowpark_session is not None:
            self._stream_writer({
                "type": "downstream_status",
                "content": "Executing SQL...",
                "metadata": {"status": "executing_sql"},
            })
            try:
                rows = self._snowpark_session.sql(sql_statement).collect()
                result_table = self._format_snowpark_result(rows)
            except Exception as e:
                result_table = f"SQL execution error: {e}"

        return self._format_from_blocks(content_blocks, sql_statement, result_table)

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _format_from_blocks(
        self,
        content_blocks: dict[int, dict],
        sql_statement: str | None,
        result_table: str,
    ) -> str:
        parts = []
        for block in content_blocks.values():
            if block["type"] == "text" and block.get("text"):
                parts.append(block["text"])
            elif block["type"] == "suggestions" and block.get("suggestions"):
                ordered = [block["suggestions"][i] for i in sorted(block["suggestions"])]
                bullet = "\n".join(f"  - {s}" for s in ordered)
                parts.append(f"Suggested questions:\n{bullet}")

        if sql_statement:
            parts.append(f"**SQL:**\n```sql\n{sql_statement}\n```")

        if result_table:
            parts.append(result_table)

        return "\n\n".join(parts) if parts else "(No response from Cortex Analyst)"

    def _format_snowpark_result(self, rows) -> str:
        if not rows:
            return "(no results)"

        columns = list(rows[0].as_dict().keys())
        col_widths = [len(c) for c in columns]
        data = [list(row.as_dict().values()) for row in rows]

        for row in data:
            for i, val in enumerate(row):
                if i < len(col_widths):
                    col_widths[i] = max(col_widths[i], len(str(val) if val is not None else ""))

        header = " | ".join(c.ljust(col_widths[i]) for i, c in enumerate(columns))
        separator = "-|-".join("-" * w for w in col_widths)
        lines = [header, separator]
        for row in data:
            line = " | ".join(
                str(row[i] if i < len(row) and row[i] is not None else "").ljust(col_widths[i])
                for i in range(len(columns))
            )
            lines.append(line)

        return "\n".join(lines)

    def _format_response(self, data: dict) -> str:
        """Format a non-streaming response (sync fallback)."""
        parts = []
        content = data.get("message", {}).get("content", [])

        for block in content:
            if block["type"] == "text":
                parts.append(block["text"])
            elif block["type"] == "sql":
                parts.append(f"**SQL:**\n```sql\n{block['statement']}\n```")
            elif block["type"] == "suggestions":
                suggestions = "\n".join(f"  - {s}" for s in block["suggestions"])
                parts.append(f"Suggested questions:\n{suggestions}")

        return "\n\n".join(parts)
