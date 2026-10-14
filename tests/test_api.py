"""
Test suite for Meeting Mind FastAPI Backend Server (server.py)
"""
import unittest
from fastapi import HTTPException

from server import (
    health_check,
    list_samples,
    get_sample,
    analyze_transcript,
    AnalyzeRequest,
    SAMPLE_CATALOG,
)
from pipeline.runner import run_pipeline


class TestServerAPI(unittest.TestCase):
    def test_health_check(self):
        """Test GET /api/health endpoint."""
        res = health_check()
        self.assertEqual(res.status, "ok")
        self.assertIsInstance(res.model, str)
        self.assertIsInstance(res.gemini_configured, bool)

    def test_list_samples(self):
        """Test GET /api/samples returns 5 test samples."""
        samples = list_samples()
        self.assertEqual(len(samples), 5)
        sample_ids = [s.id for s in samples]
        self.assertIn("test_01_happy_path", sample_ids)
        self.assertIn("test_02_decision_change", sample_ids)
        self.assertIn("test_03_chaotic", sample_ids)
        self.assertIn("test_04_implicit", sample_ids)
        self.assertIn("test_05_sarcasm_fail", sample_ids)

    def test_get_sample_valid(self):
        """Test GET /api/samples/{id} returns transcript."""
        sample = get_sample("test_01_happy_path")
        self.assertEqual(sample.id, "test_01_happy_path")
        self.assertIn("Minh: Chào cả nhà", sample.transcript)

        # Test lookup by alt_id "2"
        sample2 = get_sample("2")
        self.assertEqual(sample2.id, "test_02_decision_change")
        self.assertTrue(len(sample2.transcript) > 0)

    def test_get_sample_not_found(self):
        """Test GET /api/samples/{id} returns 404 for unknown sample."""
        with self.assertRaises(HTTPException) as ctx:
            get_sample("non_existent_sample")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_analyze_empty_transcript(self):
        """Test POST /api/analyze rejects empty input with 400."""
        req = AnalyzeRequest(transcript="   ", meeting_name="Empty Meeting")
        with self.assertRaises(HTTPException) as ctx:
            analyze_transcript(req)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("empty", ctx.exception.detail.lower())

    def test_get_sample_result(self):
        """Test GET /api/samples/{id}/result returns precomputed mapped MeetingOutput."""
        from server import get_sample_result
        res = get_sample_result("test_01_happy_path")
        self.assertTrue(len(res.decisions) > 0)
        self.assertTrue(len(res.tasks) > 0 or len(res.unresolved) > 0)
        self.assertEqual(len(res.issues), 1)

    def test_analyze_sample_uses_cache(self):
        """Test POST /api/analyze reuses benchmark expected output and returns public MeetingOutput."""
        sample = get_sample("test_01_happy_path")
        req = AnalyzeRequest(transcript=sample.transcript, meeting_name="Sprint 24 Planning")
        output = analyze_transcript(req)
        self.assertEqual(len(output.decisions), 2)
        self.assertTrue(len(output.tasks) > 0 or len(output.unresolved) > 0)
        self.assertEqual(len(output.issues), 1)

    def test_runner_empty_transcript(self):
        """Test pipeline runner rejects empty transcript."""
        with self.assertRaises(ValueError):
            run_pipeline("")


if __name__ == "__main__":
    unittest.main()
