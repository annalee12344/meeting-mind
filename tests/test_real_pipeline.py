"""
Integration and End-to-End Tests for Meeting Mind Real Analysis Path.

Tests:
1. Success lifecycle through all pipeline steps (Preprocess -> Extract -> Resolve -> Validate -> Map -> Done).
2. Failure paths: LLMAuthError, LLMRateLimitError, LLMTimeoutError, LLMInvalidOutputError.
3. Job cancellation.
4. API v1 controller endpoints (validation, 400 bad request, 404 not found, status polling).
"""
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from models.jobs import JobStage, JobStatus
from pipeline.job_store import InMemoryJobStore, execute_pipeline_job
from pipeline.llm_client import (
    LLMAuthError,
    LLMInvalidOutputError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from server import (
    AnalyzeRequest,
    cancel_job,
    get_job_status,
    start_analysis_job_v1,
)
from tests.fake_llm import (
    FakeLLMClient,
    create_minimal_extraction_result,
    create_minimal_resolved_result,
)


class TestRealPipeline(unittest.TestCase):
    """Integration tests for the real analysis pipeline path."""

    def setUp(self):
        self.store = InMemoryJobStore(ttl_seconds=3600.0)
        self.sample_text = (
            "[09:00] An: Chốt ngày phát hành là 25/12/2026.\n"
            "[09:02] Bình: Kiểm thử tải hệ thống hoàn thành trước thứ Sáu.\n"
            "[09:04] Cường: Chưa được cấp quyền truy cập máy chủ production.\n"
            "[09:06] An: Chưa thống nhất ngân sách cho chiến dịch."
        )

    @patch("pipeline.extractor.GeminiLLMClient")
    @patch("pipeline.resolver.GeminiLLMClient")
    def test_pipeline_success_lifecycle(self, mock_resolver_client, mock_extractor_client):
        fake_llm = FakeLLMClient()
        mock_extractor_client.return_value = fake_llm
        mock_resolver_client.return_value = fake_llm

        job_id = "test_job_success"
        self.store.create_job(job_id=job_id, meeting_title="Test Success", transcript_length=len(self.sample_text))

        execute_pipeline_job(
            job_id=job_id,
            transcript=self.sample_text,
            meeting_title="Test Success",
            store=self.store,
        )

        job = self.store.get_job(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job.status, JobStatus.DONE)
        self.assertEqual(job.stage, JobStage.DONE)
        self.assertEqual(job.progress, 1.0)
        self.assertEqual(job.progress_percent, 100)
        self.assertIsNone(job.error)
        self.assertIsNotNone(job.result)

        # Verify output structure
        res = job.result
        self.assertGreaterEqual(len(res.decisions), 1)
        self.assertGreaterEqual(len(res.tasks), 1)
        self.assertGreaterEqual(len(res.issues), 1)
        self.assertGreaterEqual(len(res.unresolved), 1)

    @patch("pipeline.extractor.GeminiLLMClient")
    def test_pipeline_llm_auth_error(self, mock_extractor_client):
        fake_llm = FakeLLMClient()
        fake_llm.set_exception(LLMAuthError("Invalid Gemini API key provided."))
        mock_extractor_client.return_value = fake_llm

        job_id = "test_job_auth_err"
        self.store.create_job(job_id=job_id, meeting_title="Test Auth Error", transcript_length=len(self.sample_text))

        execute_pipeline_job(
            job_id=job_id,
            transcript=self.sample_text,
            meeting_title="Test Auth Error",
            store=self.store,
        )

        job = self.store.get_job(job_id)
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertEqual(job.stage, JobStage.FAILED)
        self.assertEqual(job.error_code, "llm_auth")
        self.assertIn("GEMINI_API_KEY", job.friendly_error)

    @patch("pipeline.extractor.GeminiLLMClient")
    def test_pipeline_llm_rate_limit_error(self, mock_extractor_client):
        fake_llm = FakeLLMClient()
        fake_llm.set_exception(LLMRateLimitError("ResourceExhausted 429 quota exceeded"))
        mock_extractor_client.return_value = fake_llm

        job_id = "test_job_rate_limit"
        self.store.create_job(job_id=job_id, meeting_title="Test Rate Limit", transcript_length=len(self.sample_text))

        execute_pipeline_job(
            job_id=job_id,
            transcript=self.sample_text,
            meeting_title="Test Rate Limit",
            store=self.store,
        )

        job = self.store.get_job(job_id)
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertEqual(job.error_code, "llm_rate_limit")
        self.assertIn("429", job.friendly_error)

    @patch("pipeline.extractor.GeminiLLMClient")
    def test_pipeline_llm_timeout_error(self, mock_extractor_client):
        fake_llm = FakeLLMClient()
        fake_llm.set_exception(LLMTimeoutError("Request timed out after 60s"))
        mock_extractor_client.return_value = fake_llm

        job_id = "test_job_timeout"
        self.store.create_job(job_id=job_id, meeting_title="Test Timeout", transcript_length=len(self.sample_text))

        execute_pipeline_job(
            job_id=job_id,
            transcript=self.sample_text,
            meeting_title="Test Timeout",
            store=self.store,
        )

        job = self.store.get_job(job_id)
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertEqual(job.error_code, "llm_timeout")

    @patch("pipeline.extractor.GeminiLLMClient")
    def test_pipeline_llm_invalid_output_error(self, mock_extractor_client):
        fake_llm = FakeLLMClient()
        fake_llm.set_exception(LLMInvalidOutputError("JSONDecodeError: Unterminated string"))
        mock_extractor_client.return_value = fake_llm

        job_id = "test_job_invalid_out"
        self.store.create_job(job_id=job_id, meeting_title="Test Invalid Output", transcript_length=len(self.sample_text))

        execute_pipeline_job(
            job_id=job_id,
            transcript=self.sample_text,
            meeting_title="Test Invalid Output",
            store=self.store,
        )

        job = self.store.get_job(job_id)
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertEqual(job.error_code, "llm_invalid_output")

    def test_pipeline_cancellation(self):
        job_id = "test_job_cancel"
        self.store.create_job(job_id=job_id, meeting_title="Test Cancel", transcript_length=len(self.sample_text))
        self.store.cancel_job(job_id)

        execute_pipeline_job(
            job_id=job_id,
            transcript=self.sample_text,
            meeting_title="Test Cancel",
            store=self.store,
        )

        job = self.store.get_job(job_id)
        self.assertEqual(job.status, JobStatus.CANCELLED)

    def test_api_v1_empty_transcript_rejected(self):
        # Empty string
        with self.assertRaises(HTTPException) as ctx:
            start_analysis_job_v1(AnalyzeRequest(transcript="   "))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Nội dung biên bản cuộc họp trống", ctx.exception.detail)

    def test_api_v1_invalid_transcript_rejected(self):
        # Text with only blank lines and whitespace
        with self.assertRaises(HTTPException) as ctx:
            start_analysis_job_v1(AnalyzeRequest(transcript="\n\n   \n\t  \n"))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_api_v1_job_not_found(self):
        with self.assertRaises(HTTPException) as ctx:
            get_job_status("non_existent_job_xyz")
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("không tồn tại", ctx.exception.detail)

    def test_api_v1_cancel_not_found(self):
        with self.assertRaises(HTTPException) as ctx:
            cancel_job("non_existent_job_xyz")
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
