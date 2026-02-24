"""
Logging configuration for QA-Agent.

Usage in any module:
    from .logging_config import get_logger
    logger = get_logger(__name__)
"""

import logging
import sys
from pathlib import Path
from datetime import datetime

# Log directory
LOG_DIR = Path.home() / ".qa_agent" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Current log file
LOG_FILE = LOG_DIR / f"qa_agent_{datetime.now().strftime('%Y%m%d')}.log"

# Configure root logger only once
_configured = False


def setup_logging(level: int = logging.INFO, verbose: bool = False) -> None:
    """Configure logging for QA-Agent.

    Args:
        level: Logging level (default: INFO)
        verbose: If True, also log to stderr
    """
    global _configured
    if _configured:
        return

    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler (always enabled)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)  # File gets everything
    file_handler.setFormatter(formatter)

    # Configure qa_agent logger
    qa_logger = logging.getLogger("ui_verdict.qa_agent")
    qa_logger.setLevel(level)
    qa_logger.addHandler(file_handler)

    # Console handler (if verbose)
    if verbose:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        qa_logger.addHandler(console_handler)

    _configured = True
    qa_logger.info(f"QA-Agent logging initialized. Log file: {LOG_FILE}")


def get_logger(name: str) -> logging.Logger:
    """Get a logger for the given module name.

    Ensures logging is configured before returning.
    """
    setup_logging()
    return logging.getLogger(name)
