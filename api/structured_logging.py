"""Structured logging utilities for API and worker processes."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
_session_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("session_id", default=None)

_configured = False


def set_request_id(request_id: str | None) -> contextvars.Token[str | None]:
    return _request_id_var.set(request_id)


def reset_request_id(token: contextvars.Token[str | None]) -> None:
    _request_id_var.reset(token)


def get_request_id() -> str | None:
    return _request_id_var.get()


def set_session_id(session_id: str | None) -> contextvars.Token[str | None]:
    return _session_id_var.set(session_id)


def reset_session_id(token: contextvars.Token[str | None]) -> None:
    _session_id_var.reset(token)


def get_session_id() -> str | None:
    return _session_id_var.get()


def bind_session_id(session_id: str | None) -> None:
    _session_id_var.set(session_id)


class _JsonFormatter(logging.Formatter):
    """Render log records as one-line JSON."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", record.getMessage()),
            "module": record.name,
            "request_id": get_request_id(),
            "session_id": getattr(record, "session_id", get_session_id()),
            "path": getattr(record, "path", None),
            "method": getattr(record, "method", None),
            "status_code": getattr(record, "status_code", None),
            "duration_ms": getattr(record, "duration_ms", None),
            "error_type": getattr(record, "error_type", None),
            "error_message": getattr(record, "error_message", None),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_structured_logging() -> None:
    """Configure the `lumina` logger family for JSON output."""
    global _configured
    if _configured:
        return
    _configured = True

    logger = logging.getLogger("lumina")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    logger.handlers.clear()
    logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Get a namespaced logger under the `lumina` family."""
    configure_structured_logging()
    if name.startswith("lumina."):
        return logging.getLogger(name)
    return logging.getLogger(f"lumina.{name}")
