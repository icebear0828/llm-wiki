from __future__ import annotations

import logging
from pathlib import Path

from llmwiki.cli import _configure_daemon_logging


def test_configure_daemon_logging_writes_rotating_log_without_duplicates(tmp_path: Path) -> None:
    logger = logging.getLogger("llmwiki")
    original_handlers = list(logger.handlers)
    try:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)

        first = _configure_daemon_logging(tmp_path)
        second = _configure_daemon_logging(tmp_path)

        assert first == tmp_path / ".llmwiki" / "logs" / "daemon.log"
        assert second == first
        matching = [
            handler
            for handler in logger.handlers
            if getattr(handler, "_llmwiki_daemon_log_path", None) == str(first)
        ]
        assert len(matching) == 1

        logger.info("daemon logging test message")
        for handler in matching:
            handler.flush()

        assert "daemon logging test message" in first.read_text(encoding="utf-8")
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        for handler in original_handlers:
            logger.addHandler(handler)
