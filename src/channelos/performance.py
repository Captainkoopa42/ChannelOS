"""Small operation timings for user actions, without per-frame log traffic."""
from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@contextmanager
def operation(name: str, **counts):
    start = time.perf_counter()
    try:
        yield counts
    finally:
        logger.info('operation=%s elapsed_ms=%.3f work=%s', name,
                    (time.perf_counter() - start) * 1000,
                    json.dumps(counts, sort_keys=True))
