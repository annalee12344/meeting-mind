"""
Unit tests for the Analysis Cache module (pipeline/cache.py).

Tests:
1. Basic get/set/miss behavior.
2. TTL expiration.
3. LRU capacity-based eviction order.
4. Deterministic cache key generation with NFC normalization.
5. Preserving item UUIDs across cache retrievals.
6. Thread safety with concurrent accesses.
7. Server /api/cache/clear endpoint.
"""
from concurrent.futures import ThreadPoolExecutor
import time
import unicodedata
import unittest

import config
from models.output import (
    MeetingOutput,
    PublicDecision,
    PublicIssue,
    PublicMeta,
    PublicTask,
    PublicUnresolvedItem,
)
from pipeline.cache import (
    InMemoryLRUTTLCache,
    compute_analysis_cache_key,
    get_analysis_cache,
)
from server import clear_analysis_cache


class TestAnalysisCacheBasics(unittest.TestCase):
    """Test basic LRU and TTL cache operations."""

    def test_cache_put_get_miss(self):
        cache = InMemoryLRUTTLCache(capacity=5, default_ttl=60.0)
        self.assertIsNone(cache.get("key1"))

        cache.set("key1", "val1")
        self.assertEqual(cache.get("key1"), "val1")
        self.assertEqual(cache.size(), 1)

        self.assertTrue(cache.delete("key1"))
        self.assertFalse(cache.delete("key1"))
        self.assertIsNone(cache.get("key1"))

    def test_ttl_expiration(self):
        cache = InMemoryLRUTTLCache(capacity=5, default_ttl=0.1)
        cache.set("key_expire", "temp_value")
        self.assertEqual(cache.get("key_expire"), "temp_value")

        time.sleep(0.15)
        self.assertIsNone(cache.get("key_expire"))
        self.assertEqual(cache.size(), 0)

    def test_lru_eviction(self):
        cache = InMemoryLRUTTLCache(capacity=3, default_ttl=60.0)
        cache.set("A", 1)
        cache.set("B", 2)
        cache.set("C", 3)

        # Access A to make it recently used: order becomes B, C, A
        self.assertEqual(cache.get("A"), 1)

        # Insert D: should evict B (least recently used)
        cache.set("D", 4)

        self.assertIsNone(cache.get("B"))
        self.assertEqual(cache.get("A"), 1)
        self.assertEqual(cache.get("C"), 3)
        self.assertEqual(cache.get("D"), 4)

    def test_clear_cache(self):
        cache = InMemoryLRUTTLCache(capacity=5)
        cache.set("A", 1)
        cache.set("B", 2)
        cache.clear()
        self.assertEqual(cache.size(), 0)
        self.assertIsNone(cache.get("A"))


class TestDeterministicCacheKey(unittest.TestCase):
    """Test cache key hashing and normalization."""

    def test_identical_inputs_produce_identical_key(self):
        t = "Minh: Chào mọi người."
        k1 = compute_analysis_cache_key(t, meeting_date="2026-10-14")
        k2 = compute_analysis_cache_key(t, meeting_date="2026-10-14")
        self.assertEqual(k1, k2)

    def test_different_dates_produce_different_keys(self):
        t = "Minh: Chào mọi người."
        k1 = compute_analysis_cache_key(t, meeting_date="2026-10-14")
        k2 = compute_analysis_cache_key(t, meeting_date="2026-10-15")
        self.assertNotEqual(k1, k2)

    def test_different_models_produce_different_keys(self):
        t = "Minh: Chào mọi người."
        k1 = compute_analysis_cache_key(t, models={"step1": "modelA", "step2": "modelB"})
        k2 = compute_analysis_cache_key(t, models={"step1": "modelX", "step2": "modelB"})
        self.assertNotEqual(k1, k2)

    def test_unicode_normalization_in_cache_key(self):
        # NFC vs NFD representations of Vietnamese text
        nfc_text = "Chào cả nhà, hôm nay họp nhé."
        nfd_text = unicodedata.normalize("NFD", nfc_text)

        k_nfc = compute_analysis_cache_key(nfc_text)
        k_nfd = compute_analysis_cache_key(nfd_text)
        self.assertEqual(k_nfc, k_nfd)


class TestItemIDPreservationOnCacheHit(unittest.TestCase):
    """Test that cached results keep stable, unchanging item UUIDs."""

    def test_cached_meeting_output_preserves_item_ids(self):
        cache = InMemoryLRUTTLCache(capacity=10, default_ttl=60.0)

        # Build sample MeetingOutput with generated UUIDs
        d = PublicDecision(
            topic="Database",
            content="Use MongoDB Atlas",
            proposed_by="Tuấn",
            confirmed_by="Minh",
        )
        t = PublicTask(
            title="Setup MongoDB",
            assignee="Lan",
            deadline_raw="thứ Sáu",
            deadline_iso="2026-10-18",
        )
        u = PublicUnresolvedItem(
            kind="open_decision",
            content="CI/CD pipeline choice",
            reason_unresolved="Chưa thống nhất",
        )
        i = PublicIssue(
            content="Sandbox API key delayed",
            owner="Lan",
        )
        original_output = MeetingOutput(
            meeting_summary="Cuộc họp thảo luận kiến trúc",
            participants=["Minh", "Lan", "Tuấn"],
            decisions=[d],
            tasks=[t],
            unresolved=[u],
            issues=[i],
            meta=PublicMeta(
                per_step_model={"step1": "m1", "step2": "m2"},
                meeting_date="2026-10-14",
                meeting_date_source="user",
            ),
        )

        orig_d_id = original_output.decisions[0].id
        orig_t_id = original_output.tasks[0].id
        orig_u_id = original_output.unresolved[0].id
        orig_i_id = original_output.issues[0].id

        cache.set("key_output", original_output)

        # Retrieve 1st time
        retrieved_1 = cache.get("key_output")
        self.assertIsNotNone(retrieved_1)
        self.assertEqual(retrieved_1.decisions[0].id, orig_d_id)
        self.assertEqual(retrieved_1.tasks[0].id, orig_t_id)
        self.assertEqual(retrieved_1.unresolved[0].id, orig_u_id)
        self.assertEqual(retrieved_1.issues[0].id, orig_i_id)

        # Retrieve 2nd time
        retrieved_2 = cache.get("key_output")
        self.assertEqual(retrieved_2.decisions[0].id, orig_d_id)
        self.assertEqual(retrieved_2.tasks[0].id, orig_t_id)


class TestConcurrentCacheAccess(unittest.TestCase):
    """Test thread safety under concurrent writes and reads."""

    def test_concurrent_access_does_not_crash(self):
        cache = InMemoryLRUTTLCache(capacity=20, default_ttl=10.0)

        def worker(thread_id: int):
            for i in range(50):
                key = f"key_{i % 15}"
                cache.set(key, f"val_{thread_id}_{i}")
                _ = cache.get(key)
                if i % 10 == 0:
                    _ = cache.size()

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker, tid) for tid in range(8)]
            for f in futures:
                f.result()

        self.assertLessEqual(cache.size(), 20)


class TestServerCacheEndpoints(unittest.TestCase):
    """Test server cache endpoints."""

    def test_clear_cache_endpoint(self):
        cache = get_analysis_cache()
        cache.set("test_server_key", "value")
        self.assertGreaterEqual(cache.size(), 1)

        result = clear_analysis_cache()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(cache.size(), 0)


if __name__ == "__main__":
    unittest.main()
