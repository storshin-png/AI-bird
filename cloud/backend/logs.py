"""Структурированные JSON-логи (structlog), AI_AGENTS_SPEC.md §7.4.

Каждая запись приёма несёт device_id, event_id (если есть) и trace_id.
"""

import logging
import sys

import structlog


def configure(level: int = logging.INFO) -> None:
    logging.basicConfig(stream=sys.stdout, level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        # Без file=: поток берётся в момент записи, а не при настройке.
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str = "backend"):
    return structlog.get_logger(name)
