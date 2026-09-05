"""Structured JSON logging.

Alloy tails container stdout and ships it to Loki, so one JSON object per line
is what makes logs queryable there. When the OpenTelemetry operator injects the
Python SDK (via the `inject-python` annotation) and OTEL_PYTHON_LOG_CORRELATION
is on, it attaches `otelTraceID`/`otelSpanID` to every LogRecord — we surface
those so a Loki line links straight to its Tempo trace. Without the injection
the fields are simply absent, and the app logs the same either way.
"""

import json
import logging
import sys
from typing import Any

# LogRecord attributes that are part of the record itself rather than caller
# supplied `extra`, so we can pick out the extras generically.
_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        trace_id = getattr(record, "otelTraceID", None)
        if trace_id and trace_id != "0" * 32:
            payload["trace_id"] = trace_id
            payload["span_id"] = getattr(record, "otelSpanID", None)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Anything passed as logger.info(..., extra={...}).
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("otel"):
                payload[key] = value

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Route the root logger and uvicorn's loggers through the JSON formatter."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # uvicorn installs its own handlers; clear them so lines aren't duplicated
    # in one format and emitted again in another.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
