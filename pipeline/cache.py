"""
Analysis Cache Module for Meeting Mind.

Provides:
1. AnalysisCache Protocol interface.
2. In-memory LRU + TTL Cache implementation (InMemoryLRUTTLCache) with thread safety.
3. Deterministic SHA-256 cache key generation based on:
   hash(transcript + meeting_date + prompt_version + models).
4. Stable UUID preservation across cache hits.
"""
from abc import abstractmethod
from collections import OrderedDict
import hashlib
import json
import logging
import threading
import time
from typing import Any, Dict, Optional, Protocol, Tuple
import unicodedata

import config
from prompts import PROMPT_VERSION

logger = logging.getLogger(__name__)


def compute_analysis_cache_key(
    transcript: str,
    meeting_date: Optional[str] = None,
    prompt_version: Optional[str] = None,
    models: Optional[Dict[str, str]] = None,
) -> str:
    """
    Generate deterministic SHA-256 cache key from:
    transcript (NFC normalized) + meeting_date + prompt_version + models.
    """
    norm_transcript = unicodedata.normalize("NFC", transcript.strip())
    clean_date = meeting_date.strip() if meeting_date else ""
    clean_prompt = prompt_version or PROMPT_VERSION

    default_models = {
        "step1": config.STEP1_MODEL,
        "step2": config.STEP2_MODEL,
    }
    models_dict = models or default_models
    models_str = json.dumps(models_dict, sort_keys=True)

    payload = f"{norm_transcript}::{clean_date}::{clean_prompt}::{models_str}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AnalysisCache(Protocol):
    """Protocol defining cache interface for meeting analyses."""

    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """Retrieve item by key if present and not expired."""
        ...

    @abstractmethod
    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Store item in cache with optional TTL in seconds."""
        ...

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete an item from cache."""
        ...

    @abstractmethod
    def clear(self) -> None:
        """Clear all entries from cache."""
        ...

    @abstractmethod
    def size(self) -> int:
        """Return number of active non-expired items."""
        ...


class InMemoryLRUTTLCache:
    """
    Thread-safe in-memory cache combining Least Recently Used (LRU) eviction
    with Time-To-Live (TTL) expiration.
    """

    def __init__(
        self,
        capacity: Optional[int] = None,
        default_ttl: Optional[float] = None,
    ) -> None:
        self.capacity: int = capacity if capacity is not None else config.CACHE_CAPACITY
        self.default_ttl: float = default_ttl if default_ttl is not None else config.CACHE_TTL_SECONDS
        self._cache: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        """
        Retrieve value for key. Evicts expired items.
        Refreshes LRU order on hit.
        """
        with self._lock:
            if key not in self._cache:
                return None

            value, expire_at = self._cache[key]
            if time.time() > expire_at:
                # Expired -> delete and return None
                del self._cache[key]
                logger.debug(f"[Cache] Evicted expired key '{key[:12]}...'")
                return None

            # Hit -> move to end (most recently used)
            self._cache.move_to_end(key)
            logger.debug(f"[Cache] Hit for key '{key[:12]}...'")
            return value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """
        Store value under key with specified or default TTL.
        Evicts least recently used item if capacity is reached.
        """
        effective_ttl = ttl if ttl is not None else self.default_ttl
        expire_at = time.time() + effective_ttl

        with self._lock:
            if key in self._cache:
                del self._cache[key]

            # Evict LRU if capacity exceeded
            while len(self._cache) >= self.capacity:
                evicted_key, _ = self._cache.popitem(last=False)
                logger.debug(f"[Cache] Capacity reached. Evicted LRU key '{evicted_key[:12]}...'")

            self._cache[key] = (value, expire_at)
            logger.debug(f"[Cache] Cached key '{key[:12]}...' (TTL={effective_ttl}s)")

    def delete(self, key: str) -> bool:
        """Delete key from cache. Returns True if key was present."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all entries."""
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        """Return count of active (non-expired) entries."""
        now = time.time()
        with self._lock:
            # Purge expired entries on count check
            expired_keys = [k for k, (_, exp) in self._cache.items() if now > exp]
            for k in expired_keys:
                del self._cache[k]
            return len(self._cache)


# Global singleton instance
_GLOBAL_CACHE: Optional[InMemoryLRUTTLCache] = None


def get_analysis_cache() -> InMemoryLRUTTLCache:
    """Get the global analysis cache instance."""
    global _GLOBAL_CACHE
    if _GLOBAL_CACHE is None:
        _GLOBAL_CACHE = InMemoryLRUTTLCache(
            capacity=config.CACHE_CAPACITY,
            default_ttl=config.CACHE_TTL_SECONDS,
        )
    return _GLOBAL_CACHE
