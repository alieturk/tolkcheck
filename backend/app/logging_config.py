"""Centralised logging configuration for the tolkcheck backend.

Call configure_logging() once at application startup (main.py + worker.py).
Every module should then get its logger via:

    import logging
    log = logging.getLogger(__name__)
"""
from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    """Set up a human-readable log format on stdout.

    Format:  YYYY-MM-DD HH:MM:SS | LEVEL    | module.name | message
    """
    fmt = "%(asctime)s | %(levelname)-8s | %(name)-40s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        datefmt=datefmt,
        stream=sys.stdout,
        force=True,
    )

    # Silence noisy third-party loggers that flood the console during model loading
    for noisy in (
        "httpx",
        "httpcore",
        "sentence_transformers",
        "faster_whisper",
        "pyannote",
        "torch",
        "transformers",
        "urllib3",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)
