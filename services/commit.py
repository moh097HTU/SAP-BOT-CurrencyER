# services/commit.py
from __future__ import annotations
import os
import threading
from contextlib import contextmanager

# How many concurrent "Create/Activate" commits may run at once?
# Default = 1 (fully serialized). You can set COMMIT_CONCURRENCY=2..N if SAP allows it.
_COMMIT_CONCURRENCY = max(1, int(os.getenv("COMMIT_CONCURRENCY", "1")))
_SEM = threading.Semaphore(_COMMIT_CONCURRENCY)

@contextmanager
def commit_gate():
    _SEM.acquire()
    try:
        yield
    finally:
        _SEM.release()
