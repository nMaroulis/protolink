"""Tests for Protolink logger implementations."""

import logging

from protolink.logging import BaseLogger, QuietLogger


def test_quiet_logger_implements_base_logger() -> None:
    """QuietLogger should be a drop-in BaseLogger implementation."""
    logger = QuietLogger(name="silent-agent")

    assert isinstance(logger, BaseLogger)
    assert logger.name == "silent-agent"


def test_quiet_logger_drops_all_messages(capsys) -> None:
    """QuietLogger should not write output or configure Python logging."""
    root_logger = logging.getLogger()
    handlers_before = tuple(root_logger.handlers)
    logger = QuietLogger()

    assert logger.debug("debug", extra={"event": "ignored"}) is None
    assert logger.info("info", extra={"event": "ignored"}) is None
    assert logger.warning("warning", extra={"event": "ignored"}) is None
    assert logger.error("error", exc_info=True, extra={"event": "ignored"}) is None
    assert logger.exception("exception", exc_info=True, extra={"event": "ignored"}) is None

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert tuple(root_logger.handlers) == handlers_before
