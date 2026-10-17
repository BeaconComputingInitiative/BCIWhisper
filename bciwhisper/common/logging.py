from __future__ import annotations
import logging
from logging.handlers import RotatingFileHandler

def build_rotating_logger(name, path, *, max_bytes=4_000_000, backups=3):
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backups)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(threadName)s | %(message)s"
    ))
    logger.addHandler(handler)
    return logger
