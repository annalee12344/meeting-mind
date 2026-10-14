"""
Unit tests for Meeting Mind API v1 endpoints (server.py).

Tests:
1. Health check v1.
2. Sample listings and retrieval v1.
3. Sample result retrieval v1.
4. Async job creation and status polling.
5. Job cancellation.
6. Legacy 5-array JSON upgrade endpoint.
"""
import json
import unittest
from pathlib import Path

from fastapi import HTTPException

import config
from models.jobs import JobStatus
from server import (
    AnalyzeRequest,
    cancel_job,
    get_job_status,
    get_sample,
    get_sample_result,
    health_check,
    list_samples,
    start_analysis_job_v1,
    upgrade_legacy_endpoint,
)


class TestApiV1(unittest.TestCase):
    """Test API v1 controller functions."""

    def test_health_check_v1(self):
        res = health_check()
        self.assertEqual(res.status, "ok")
        self.assertIsInstance(res.model, str)
        self.assertEqual(res.schema_version, "2.0.0")

    def test_samples_v1(self):
        samples = list_samples()
        self.assertGreaterEqual(len(samples), 5)
        detail = get_sample(samples[0].id)
        self.assertIn("Minh:", detail.transcript)

    def test_sample_result_v1(self):
        result = get_sample_result("test_01_happy_path")
        self.assertGreater(len(result.decisions), 0)
        self.assertGreater(len(result.unresolved), 0)
        self.assertEqual(result.meta.schema_version, "2.0.0")

    def test_async_job_creation_and_polling(self):
        # Empty input rejected
        with self.assertRaises(HTTPException) as ctx:
            start_analysis_job_v1(AnalyzeRequest(transcript="   "))
        self.assertEqual(ctx.exception.status_code, 400)

        # Valid input initiates job
        sample_path = config.TRANSCRIPTS_DIR / "test_01_happy_path.txt"
        transcript_text = sample_path.read_text(encoding="utf-8")

        start_res = start_analysis_job_v1(
            AnalyzeRequest(
                transcript=transcript_text,
                meeting_title="Sprint 24 Test",
                use_sample_cache=True,
            )
        )
        self.assertTrue(start_res.job_id.startswith("job_"))
        self.assertEqual(start_res.status, JobStatus.PENDING)

        # Poll status
        status_res = get_job_status(start_res.job_id)
        self.assertEqual(status_res.job_id, start_res.job_id)
        self.assertIn(status_res.status, [JobStatus.PENDING, JobStatus.PROCESSING, JobStatus.DONE])

    def test_job_cancellation_v1(self):
        start_res = start_analysis_job_v1(
            AnalyzeRequest(
                transcript="Nam: Chúng ta họp nhé.",
                meeting_title="Cancel Test",
                use_sample_cache=False,
            )
        )
        cancel_res = cancel_job(start_res.job_id)
        self.assertEqual(cancel_res["status"], "cancelled")

        status_res = get_job_status(start_res.job_id)
        self.assertEqual(status_res.status, JobStatus.CANCELLED)

    def test_upgrade_legacy_json_endpoint(self):
        legacy_path = config.EXPECTED_DIR / "test_01_expected.json"
        legacy_json = json.loads(legacy_path.read_text(encoding="utf-8"))

        upgraded = upgrade_legacy_endpoint(legacy_json)
        self.assertEqual(upgraded.meta.schema_version, "2.0.0")
        self.assertGreaterEqual(len(upgraded.decisions), 1)
        self.assertGreaterEqual(len(upgraded.issues), 1)
        # All items have UUIDs
        for d in upgraded.decisions:
            self.assertTrue(len(d.id) > 20)


if __name__ == "__main__":
    unittest.main()
