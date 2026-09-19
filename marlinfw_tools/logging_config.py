"""Structured logging for the one-shot CLI."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from marlinfw_tools.errors import ConfigurationError

_STANDARD_LOG_FIELDS = frozenset(logging.makeLogRecord({}).__dict__)
_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class JSONFormatter(logging.Formatter):
    """Emit stable structured records without serial payload bodies."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "time": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "file": record.filename,
            "line": record.lineno,
            "func": record.funcName,
            "msg": record.getMessage(),
        }
        data.update(
            {
                key: value
                for key, value in record.__dict__.items()
                if key not in _STANDARD_LOG_FIELDS and not key.startswith("_")
            }
        )
        if record.exc_info:
            data["error"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, sort_keys=True)


def configure_logging(level: str, log_file: str) -> None:
    """Configure stderr and a bounded local log for each CLI invocation."""
    normalized_level = level.upper()
    if normalized_level not in _LOG_LEVELS:
        raise ConfigurationError(
            "log level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL"
        )
    formatter = JSONFormatter()
    log_path = Path(log_file)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers: list[logging.Handler] = [
            logging.StreamHandler(),
            RotatingFileHandler(
                log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            ),
        ]
    except OSError as error:
        raise ConfigurationError("failed to open the configured log file") from error
    for handler in handlers:
        handler.setFormatter(formatter)
    logging.basicConfig(level=normalized_level, handlers=handlers, force=True)
