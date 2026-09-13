"""Logging setup for the integration.

Writes a rotating log to ``logs/apc40-sonar.log`` (ignored by git) and mirrors
warnings and errors to the console. The run loop uses this to record port
opens, the selected APC40 mode, the lightshow, and any per-message handler
errors, which makes the Cakewalk validation session diagnosable after the
fact.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

LOGGER_NAME = "apc40sonar"
DEFAULT_LOG_PATH = Path("logs") / "apc40-sonar.log"
_FILE_FORMAT = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    log_path: Path | str = DEFAULT_LOG_PATH,
    *,
    level: int = logging.INFO,
    console: bool = True,
) -> logging.Logger:
    """Configure and return the package logger.

    The file handler records everything at *level*; the console handler mirrors
    warnings and above so normal operation stays quiet. Repeated calls replace
    the handlers rather than stacking them.
    """

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(_FILE_FORMAT, _DATE_FORMAT)

    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


def get_logger() -> logging.Logger:
    """Return the package logger without (re)configuring it."""

    return logging.getLogger(LOGGER_NAME)
