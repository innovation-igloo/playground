"""Snowflake Threads API client for multi-turn Cortex Agent conversations.

Maintains a server-side conversation thread per LangGraph session so the
downstream Cortex Agent can resolve follow-up questions with full context
(e.g. "Can you check sweeps for this?" where "this" = TSLA from a prior turn).

API: POST /api/v2/cortex/threads
Docs: https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-threads-rest-api

Auth: Bearer <PAT> + X-Snowflake-Authorization-Token-Type header (same as :run).

Threading protocol (discovered via live testing):
    1. ``POST /api/v2/cortex/threads`` → create thread, get ``thread_id``
    2. First ``:run`` call: ``thread_id=<sf_thread_id>``, ``parent_message_id=0``
       Response metadata includes ``user_message_id`` and ``assistant_message_id``.
    3. Subsequent calls: ``parent_message_id=<last assistant_message_id>``
    The cache stores ``{langgraph_thread_id: (sf_thread_id, last_assistant_msg_id)}``
    where ``last_assistant_msg_id`` starts at ``0`` (sentinel for "new thread").

Design:
    - One ``CortexThreadClient`` instance is shared across all requests.
    - ``get_thread_context`` returns ``(sf_thread_id, parent_message_id)`` — the
      caller passes both fields in the ``:run`` body.
    - ``update_last_message_id`` is called after each successful ``:run`` with the
      ``metadata.assistant_message_id`` from the response.
    - All methods return ``None``/skip gracefully on failure so the caller can
      fall back to stateless requests rather than hard-failing.

See also:
    agent/tools/cortex_agents.py  -- consumes CortexThreadClient
    agent/llm.py:resolve_pat      -- PAT resolution
"""

import logging
import httpx
from agent.llm import resolve_pat

logger = logging.getLogger(__name__)


class CortexThreadClient:
    """Thin client for the Snowflake Threads API.

    Attributes:
        _account:  Snowflake account identifier (underscores converted to dashes
                   for the hostname internally).
        _sf_ids:   LangGraph thread_id → Snowflake thread_id (integer).
        _last_msg: LangGraph thread_id → last assistant_message_id (integer).
                   ``0`` is the sentinel for a brand-new thread with no messages.
    """

    def __init__(self, account: str) -> None:
        self._account = account
        self._sf_ids: dict[str, int] = {}
        self._last_msg: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _base_url(self) -> str:
        host = self._account.replace("_", "-")
        return f"https://{host}.snowflakecomputing.com/api/v2/cortex/threads"

    def _headers(self, pat: str) -> dict:
        return {
            "Authorization": f"Bearer {pat}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Snowflake-Authorization-Token-Type": "PROGRAMMATIC_ACCESS_TOKEN",
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_thread_context(self, langgraph_thread_id: str) -> tuple[int, int] | tuple[None, None]:
        """Return ``(sf_thread_id, parent_message_id)`` for the given session.

        Creates a new Snowflake thread on first call for a session.
        ``parent_message_id`` is ``0`` for a brand-new thread (first message),
        or the ``assistant_message_id`` from the previous response for all
        subsequent turns.

        Args:
            langgraph_thread_id: LangGraph session identifier from
                ``config["configurable"]["thread_id"]``.

        Returns:
            ``(sf_thread_id, parent_message_id)`` on success.
            ``(None, None)`` on any failure — caller should degrade gracefully.
        """
        if langgraph_thread_id in self._sf_ids:
            sf_thread_id = self._sf_ids[langgraph_thread_id]
            parent_msg_id = self._last_msg.get(langgraph_thread_id, 0)
            return sf_thread_id, parent_msg_id

        pat = resolve_pat()
        if not pat:
            logger.warning("thread creation skipped — SNOWFLAKE_PAT not available")
            return None, None

        try:
            resp = httpx.post(
                self._base_url(),
                headers=self._headers(pat),
                json={"origin_application": "qwen_agent"},
                timeout=10,
            )
            resp.raise_for_status()
            sf_thread_id: int = resp.json()["thread_id"]
            self._sf_ids[langgraph_thread_id] = sf_thread_id
            self._last_msg[langgraph_thread_id] = 0
            logger.info(
                "cortex thread created",
                extra={
                    "langgraph_thread_id": langgraph_thread_id,
                    "sf_thread_id": sf_thread_id,
                },
            )
            return sf_thread_id, 0
        except httpx.HTTPStatusError as e:
            logger.warning(
                "thread creation failed — http error",
                extra={"status": e.response.status_code, "body": e.response.text[:200]},
            )
        except Exception as e:
            logger.warning("thread creation failed", extra={"error": str(e)})

        return None, None

    def update_last_message_id(self, langgraph_thread_id: str, assistant_message_id: int) -> None:
        """Cache the latest ``assistant_message_id`` for the next turn's ``parent_message_id``.

        Must be called after every successful ``:run`` response so the next
        invocation in the same session passes the correct parent pointer.

        Args:
            langgraph_thread_id: LangGraph session identifier.
            assistant_message_id: ``metadata.assistant_message_id`` from the
                ``:run`` response body.
        """
        self._last_msg[langgraph_thread_id] = assistant_message_id
        logger.debug(
            "thread message_id updated",
            extra={
                "langgraph_thread_id": langgraph_thread_id,
                "assistant_message_id": assistant_message_id,
            },
        )
