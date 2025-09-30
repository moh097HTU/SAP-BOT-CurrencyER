from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Any, Iterable

# How many concurrent "Create/Activate" commits may run at once? Process-wide gate.
_COMMIT_CONCURRENCY = max(1, int(os.getenv("COMMIT_CONCURRENCY", "1")))
_GLOBAL_SEM = threading.Semaphore(_COMMIT_CONCURRENCY)

# Per-key locks let us serialize only conflicting commits instead of the entire pool.
_KEY_LOCKS: dict[str, tuple[threading.Lock, int]] = {}
_KEY_LOCKS_GUARD = threading.Lock()


def _normalize_key(key: Any) -> str | None:
    """Turn various key shapes into a stable, case-insensitive token."""
    if key is None:
        return None
    if hasattr(key, "dict"):
        data = key.dict()
        parts: Iterable[Any] = (
            data.get("ExchangeRateType"),
            data.get("FromCurrency"),
            data.get("ToCurrency"),
            data.get("ValidFrom"),
        )
    elif isinstance(key, dict):
        parts = key.values()
    elif isinstance(key, (list, tuple, set)):
        parts = key
    else:
        parts = (key,)

    normalized = [str(p).strip().upper() for p in parts if p is not None]
    return "|".join(normalized) if normalized else None


def _reserve_key_lock(key: str) -> threading.Lock:
    with _KEY_LOCKS_GUARD:
        if key in _KEY_LOCKS:
            lock, refcount = _KEY_LOCKS[key]
            _KEY_LOCKS[key] = (lock, refcount + 1)
            return lock
        lock = threading.Lock()
        _KEY_LOCKS[key] = (lock, 1)
        return lock


def _release_key_lock(key: str, lock: threading.Lock) -> None:
    with _KEY_LOCKS_GUARD:
        stored = _KEY_LOCKS.get(key)
        if not stored:
            return
        stored_lock, refcount = stored
        if stored_lock is lock and refcount <= 1:
            _KEY_LOCKS.pop(key, None)
        else:
            _KEY_LOCKS[key] = (stored_lock, max(1, refcount - 1))


@contextmanager
def commit_gate(key: Any = None):
    """
    Serialize the critical "commit" step in SAP.

    When ``key`` is provided, only workers targeting the same key block one
    another, while still respecting the global COMMIT_CONCURRENCY semaphore.
    This keeps conflicting commits serialized without throttling unrelated ones.
    """
    normalized_key = _normalize_key(key)
    key_lock: threading.Lock | None = None

    try:
        if normalized_key:
            key_lock = _reserve_key_lock(normalized_key)
            key_lock.acquire()

        _GLOBAL_SEM.acquire()
        try:
            yield
        finally:
            _GLOBAL_SEM.release()
    finally:
        if normalized_key and key_lock:
            key_lock.release()
            _release_key_lock(normalized_key, key_lock)