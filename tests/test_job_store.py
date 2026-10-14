"""
Unit tests for the JobStore abstraction and async runner (pipeline/job_store.py).

Tests:
1. Job creation and initial queued state.
2. Progressive stage updates and progress calculation.
3. Job cancellation.
4. TTL expiration and cleanup.
5. Async pipeline execution with sample matcher.
"""
import time
import unittest

from models.jobs import JobStage, JobStatus
from models.output import MeetingOutput
from pipeline.job_store import InMemoryJobStore, execute_pipeline_job


class TestInMemoryJobStore(unittest.TestCase):
    """Test InMemoryJobStore state management."""

    def test_create_and_get_job(self):
        store = InMemoryJobStore(ttl_seconds=10.0)
        job = store.create_job(
            job_id="job-101",
            meeting_title="Sprint Planning",
            transcript_length=500,
        )

        self.assertEqual(job.job_id, "job-101")
        self.assertEqual(job.status, JobStatus.PENDING)
        self.assertEqual(job.stage, JobStage.QUEUED)
        self.assertGreater(job.progress, 0.0)

        fetched = store.get_job("job-101")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.meeting_title, "Sprint Planning")

    def test_update_stages(self):
        store = InMemoryJobStore(ttl_seconds=10.0)
        store.create_job("job-102", "Design Review", 300)

        store.update_job("job-102", stage=JobStage.PREPROCESSING)
        j = store.get_job("job-102")
        self.assertEqual(j.stage, JobStage.PREPROCESSING)
        self.assertEqual(j.status, JobStatus.PROCESSING)

        store.update_job("job-102", stage=JobStage.EXTRACTING)
        j = store.get_job("job-102")
        self.assertEqual(j.stage, JobStage.EXTRACTING)

        store.update_job("job-102", stage=JobStage.DONE, status=JobStatus.DONE, progress=1.0)
        j = store.get_job("job-102")
        self.assertEqual(j.stage, JobStage.DONE)
        self.assertEqual(j.status, JobStatus.DONE)
        self.assertEqual(j.progress, 1.0)

    def test_cancel_job(self):
        store = InMemoryJobStore(ttl_seconds=10.0)
        store.create_job("job-103", "Quick Sync", 100)

        self.assertFalse(store.is_cancelled("job-103"))
        self.assertTrue(store.cancel_job("job-103"))
        self.assertTrue(store.is_cancelled("job-103"))

        j = store.get_job("job-103")
        self.assertEqual(j.status, JobStatus.CANCELLED)
        self.assertEqual(j.stage, JobStage.CANCELLED)

    def test_ttl_expiration(self):
        store = InMemoryJobStore(ttl_seconds=0.1)
        store.create_job("job-104", "Temp Meeting", 100)
        store.update_job("job-104", stage=JobStage.DONE, status=JobStatus.DONE)

        time.sleep(0.15)
        # Should be expired now
        self.assertIsNone(store.get_job("job-104"))

    def test_cleanup_expired(self):
        store = InMemoryJobStore(ttl_seconds=0.1)
        store.create_job("job-105", "Temp Meeting 2", 100)
        time.sleep(0.15)
        evicted = store.cleanup_expired()
        self.assertEqual(evicted, 1)

    def test_execute_pipeline_job_with_sample_matcher(self):
        store = InMemoryJobStore(ttl_seconds=60.0)
        store.create_job("job-fast", "Fast Sample", 200)

        dummy_sample = {"id": "sample_01", "title": "Sample 1"}
        dummy_output = MeetingOutput(meeting_summary="Summary")

        def sample_matcher(text, sample_id):
            return dummy_sample

        def sample_loader(sample, threshold):
            return dummy_output

        execute_pipeline_job(
            job_id="job-fast",
            transcript="Sample transcript text",
            meeting_title="Fast Sample",
            store=store,
            sample_matcher=sample_matcher,
            sample_loader=sample_loader,
        )

        job = store.get_job("job-fast")
        self.assertEqual(job.status, JobStatus.DONE)
        self.assertEqual(job.stage, JobStage.DONE)
        self.assertEqual(job.progress, 1.0)
        self.assertIsNotNone(job.result)


if __name__ == "__main__":
    unittest.main()
