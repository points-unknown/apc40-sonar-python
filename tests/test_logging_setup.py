"""Unit tests for apc40sonar.logging_setup."""

from __future__ import annotations

import logging

from apc40sonar import logging_setup


def test_setup_logging_writes_to_file(tmp_path):
    log_path = tmp_path / "logs" / "test.log"

    logger = logging_setup.setup_logging(log_path, console=False)
    assert logger.name == logging_setup.LOGGER_NAME

    logger.info("hello world")
    for handler in logger.handlers:
        handler.flush()

    assert log_path.is_file()
    assert "hello world" in log_path.read_text(encoding="utf-8")


def test_setup_logging_replaces_handlers_instead_of_stacking(tmp_path):
    log_path = tmp_path / "logs" / "test.log"

    logger = logging_setup.setup_logging(log_path, console=False)
    initial = len(logger.handlers)

    logging_setup.setup_logging(log_path, console=False)

    assert len(logger.handlers) == initial


def test_get_logger_returns_package_logger():
    assert logging_setup.get_logger().name == "apc40sonar"
    assert isinstance(logging_setup.get_logger(), logging.Logger)
