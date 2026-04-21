"""Structured JSON logging configuration for the FastAPI agent server.

Sets up three handlers: console (stdout), rotating app log (INFO+), and
rotating error log (ERROR+). All emit newline-delimited JSON so log collectors
(CloudWatch, Fluentd, Datadog, etc.) can parse them without a custom pattern.

Call ``setup_logging(config)`` once at application startup before any other
module emits log records.
"""

import json
import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent.config import AppConfig


# ============================================================
# SECTION: JSON Formatter
# ============================================================


class JsonFormatter(logging.Formatter):
    """Format a LogRecord as a single-line JSON object.

    Core fields always present:
        timestamp   ISO 8601 UTC (e.g. "2026-04-21T14:32:01.123Z")
        level       "INFO", "ERROR", etc.
        logger      dotted logger name (e.g. "server.middleware")
        message     formatted log message

    Any keyword arguments passed via ``extra={}`` to the logger call are
    merged into the JSON object at the top level, enabling structured context
    (request_id, thread_id, latency_ms, etc.) without string interpolation.
    """

    # Keys that are standard LogRecord attributes — we skip them in extras
    # to avoid polluting the JSON with internal Python logging internals.
    _SKIP = frozenset({
        "args", "created", "exc_info", "exc_text", "filename", "funcName",
        "levelname", "levelno", "lineno", "message", "module", "msecs",
        "msg", "name", "pathname", "process", "processName", "relativeCreated",
        "stack_info", "thread", "threadName", "taskName",
    })

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc)
        payload: dict = {
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
        }

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key not in self._SKIP:
                payload[key] = value

        return json.dumps(payload, default=str)


# ============================================================
# SECTION: Setup
# ============================================================


def setup_logging(config: AppConfig) -> None:
    """Configure the root logger with console + rotating file handlers.

    Creates the log directory if it does not exist. Idempotent — calling
    this function more than once only adds duplicate handlers if Python's
    logging module has been reset externally (it won't be in normal use).

    Handlers registered:
        console     → stdout, level from config.logging.level
        app.log     → logs/app.log, INFO+, 10 MB × 5 rotated files
        error.log   → logs/error.log, ERROR+, 10 MB × 5 rotated files

    Args:
        config: Fully loaded AppConfig instance (reads config.logging section).
    """
    log_cfg = config.logging
    level = getattr(logging, log_cfg.level.upper(), logging.INFO)
    log_dir = Path(log_cfg.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = JsonFormatter()

    # ── console ─────────────────────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    # ── app.log (INFO+) ──────────────────────────────────────
    app_handler = logging.handlers.RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=log_cfg.max_bytes,
        backupCount=log_cfg.backup_count,
        encoding="utf-8",
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(formatter)

    # ── error.log (ERROR+) ───────────────────────────────────
    error_handler = logging.handlers.RotatingFileHandler(
        log_dir / "error.log",
        maxBytes=log_cfg.max_bytes,
        backupCount=log_cfg.backup_count,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(console_handler)
    root.addHandler(app_handler)
    root.addHandler(error_handler)

    # Suppress noisy third-party loggers that don't add developer value.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
