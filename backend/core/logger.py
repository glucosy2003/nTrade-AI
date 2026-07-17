"""
Logging configuration for the nTrade AI system.

Provides structured logging with support for:
- Multiple log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- File and console output
- Rotating log files
- JSON formatting for easy parsing
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path

from backend.core.settings import settings


def _configure_console_encoding() -> None:
    """Ensure console streams can safely handle UTF-8 output on Windows."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue

        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
                continue
        except (OSError, ValueError, AttributeError):
            pass

        buffer = getattr(stream, "buffer", None)
        if buffer is not None:
            try:
                setattr(
                    sys,
                    stream_name,
                    open(
                        buffer.fileno(),
                        mode="w",
                        encoding="utf-8",
                        errors="replace",
                        closefd=False,
                    ),
                )
            except Exception:
                pass


def setup_logger(name: str = "nTradeAI") -> logging.Logger:
    """
    Configure and return a logger instance for the application.
    
    Args:
        name: Logger name (typically __name__ or module name)
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    
    # Avoid duplicate handlers if setup_logger is called multiple times
    if logger.handlers:
        return logger
    
    # Create logs directory if it doesn't exist
    logs_dir = Path(settings.log_dir)
    logs_dir.mkdir(exist_ok=True, parents=True)

    _configure_console_encoding()
    
    # Set logger level
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logger.setLevel(log_level)
    
    # Console Handler (stderr)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(log_level)
    console_format = logging.Formatter(
        fmt="%(asctime)s | %(name)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # File Handler (rotating log file)
    log_file = logs_dir / "app.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,  # Keep 5 backup files
        encoding="utf-8"
    )
    file_handler.setLevel(log_level)
    file_format = logging.Formatter(
        fmt="%(asctime)s | %(name)s | %(levelname)-8s | %(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_format)
    logger.addHandler(file_handler)
    
    return logger


# Create module-level logger
logger = setup_logger(__name__)
