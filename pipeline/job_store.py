"""
Job Store abstraction and In-Memory implementation for async analysis jobs.

Architecture Notice:
The in-memory JobStore is designed for single-instance, local execution.
It stores active jobs in process memory and purges completed jobs after a configurable TTL.
LIMITATIONS:
1. In-memory storage loses all job states upon server restart.
2. In-memory storage cannot be shared across multiple Uvicorn worker processes (workers > 1).
To scale or persist jobs across restarts, swap this implementation with a Redis or SQL JobStore.
"""
from abc import abstractmethod
from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional, Protocol, Set

import config
from models.jobs import (
    AnalysisJob,
    JobStage,
    JobStatus,
    STAGE_LABELS_VI,
    STAGE_PROGRESS_MAP,
)
from models.output import MeetingOutput
from pipeline.deadlines import resolve_meeting_date
from pipeline.extractor import Extractor
from pipeline.mapper import map_to_public
from pipeline.preprocessor import preprocess
from pipeline.resolver import Resolver
from pipeline.validator import Validator

logger = logging.getLogger(__name__)


class JobStore(Protocol):
    """Protocol defining the storage interface for analysis jobs."""

    @abstractmethod
    def create_job(self, job_id: str, meeting_title: str, transcript_length: int) -> AnalysisJob:
        """Create and register a new job in queued state."""
        ...

    @abstractmethod
    def get_job(self, job_id: str) -> Optional[AnalysisJob]:
        """Fetch job state by ID, or None if expired/not found."""
        ...

    @abstractmethod
    def update_job(
        self,
        job_id: str,
        stage: JobStage,
        status: Optional[JobStatus] = None,
        progress: Optional[float] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
        friendly_error: Optional[str] = None,
        result: Optional[MeetingOutput] = None,
    ) -> Optional[AnalysisJob]:
        """Update job stage, progress, status, or result."""
        ...

    @abstractmethod
    def cancel_job(self, job_id: str) -> bool:
        """Mark a job as cancelled."""
        ...

    @abstractmethod
    def is_cancelled(self, job_id: str) -> bool:
        """Return True if job was marked cancelled."""
        ...

    @abstractmethod
    def delete_job(self, job_id: str) -> bool:
        """Remove a job from store."""
        ...

    @abstractmethod
    def cleanup_expired(self) -> int:
        """Evict jobs older than TTL. Returns number of evicted jobs."""
        ...


class InMemoryJobStore:
    """
    Thread-safe in-memory implementation of JobStore.
    """

    def __init__(self, ttl_seconds: float = 3600.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._jobs: Dict[str, AnalysisJob] = {}
        self._created_timestamps: Dict[str, float] = {}
        self._cancelled_ids: Set[str] = set()
        self._lock = threading.Lock()

    def create_job(self, job_id: str, meeting_title: str, transcript_length: int) -> AnalysisJob:
        with self._lock:
            job = AnalysisJob(
                job_id=job_id,
                meeting_title=meeting_title,
                transcript_length=transcript_length,
                status=JobStatus.PENDING,
                stage=JobStage.QUEUED,
                progress=STAGE_PROGRESS_MAP[JobStage.QUEUED],
                stage_message=STAGE_LABELS_VI[JobStage.QUEUED],
            )
            self._jobs[job_id] = job
            self._created_timestamps[job_id] = time.time()
            logger.info(f"[JobStore] Created job '{job_id}' for '{meeting_title}'")
            return job

    def get_job(self, job_id: str) -> Optional[AnalysisJob]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None

            # Check TTL
            created_at = self._created_timestamps.get(job_id, 0)
            if (time.time() - created_at) > self.ttl_seconds and job.status in (
                JobStatus.DONE,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            ):
                del self._jobs[job_id]
                self._created_timestamps.pop(job_id, None)
                self._cancelled_ids.discard(job_id)
                logger.debug(f"[JobStore] Job '{job_id}' expired and evicted.")
                return None

            return job

    def update_job(
        self,
        job_id: str,
        stage: JobStage,
        status: Optional[JobStatus] = None,
        progress: Optional[float] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
        friendly_error: Optional[str] = None,
        result: Optional[MeetingOutput] = None,
    ) -> Optional[AnalysisJob]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None

            job.stage = stage
            if status is not None:
                job.status = status
            elif stage == JobStage.DONE:
                job.status = JobStatus.DONE
            elif stage == JobStage.FAILED:
                job.status = JobStatus.FAILED
            elif stage == JobStage.CANCELLED:
                job.status = JobStatus.CANCELLED
            else:
                job.status = JobStatus.PROCESSING

            job.progress = progress if progress is not None else STAGE_PROGRESS_MAP.get(stage, job.progress)
            job.stage_message = message or STAGE_LABELS_VI.get(stage, job.stage_message)

            if error:
                job.error = error
            if friendly_error:
                job.friendly_error = friendly_error
            if result:
                job.result = result

            job.updated_at = datetime.now(timezone.utc).isoformat()
            logger.debug(f"[JobStore] Job '{job_id}' -> stage={stage.value}, progress={job.progress:.2f}")
            return job

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            if job_id not in self._jobs:
                return False
            self._cancelled_ids.add(job_id)
            job = self._jobs[job_id]
            job.status = JobStatus.CANCELLED
            job.stage = JobStage.CANCELLED
            job.progress = 1.0
            job.stage_message = STAGE_LABELS_VI[JobStage.CANCELLED]
            job.updated_at = datetime.now(timezone.utc).isoformat()
            logger.info(f"[JobStore] Cancelled job '{job_id}'")
            return True

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancelled_ids

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self._jobs:
                del self._jobs[job_id]
                self._created_timestamps.pop(job_id, None)
                self._cancelled_ids.discard(job_id)
                return True
            return False

    def cleanup_expired(self) -> int:
        now = time.time()
        evicted = 0
        with self._lock:
            to_remove = []
            for jid, created_at in self._created_timestamps.items():
                if (now - created_at) > self.ttl_seconds:
                    to_remove.append(jid)

            for jid in to_remove:
                self._jobs.pop(jid, None)
                self._created_timestamps.pop(jid, None)
                self._cancelled_ids.discard(jid)
                evicted += 1

        if evicted:
            logger.info(f"[JobStore] Cleaned up {evicted} expired jobs.")
        return evicted


# Global singleton instance
_GLOBAL_JOB_STORE: Optional[InMemoryJobStore] = None


def get_job_store() -> InMemoryJobStore:
    """Get the global InMemoryJobStore instance."""
    global _GLOBAL_JOB_STORE
    if _GLOBAL_JOB_STORE is None:
        _GLOBAL_JOB_STORE = InMemoryJobStore(ttl_seconds=3600.0)
    return _GLOBAL_JOB_STORE


def execute_pipeline_job(
    job_id: str,
    transcript: str,
    meeting_title: str,
    meeting_date: Optional[str] = None,
    threshold: Optional[int] = None,
    store: Optional[JobStore] = None,
    sample_matcher: Optional[Callable[[str, Optional[str]], Optional[Dict[str, Any]]]] = None,
    sample_loader: Optional[Callable[[Dict[str, Any], Optional[int]], Any]] = None,
) -> None:
    """
    Execute pipeline steps asynchronously in background thread, updating JobStore on each step.
    """
    job_store = store or get_job_store()

    def check_cancel() -> bool:
        if job_store.is_cancelled(job_id):
            logger.info(f"[PipelineJob] Job '{job_id}' aborting due to user cancellation.")
            return True
        return False

    try:
        clean_text = transcript.strip()
        if not clean_text:
            job_store.update_job(
                job_id,
                stage=JobStage.FAILED,
                status=JobStatus.FAILED,
                friendly_error="Nội dung biên bản cuộc họp trống.",
            )
            return

        if check_cancel():
            return

        # ── 1. Check Fast Sample Matcher ──
        if sample_matcher and sample_loader:
            matched_sample = sample_matcher(clean_text, None)
            if matched_sample:
                logger.info(f"[PipelineJob] Job '{job_id}' matches precomputed sample '{matched_sample['id']}'.")
                resolved = sample_loader(matched_sample, threshold)
                if isinstance(resolved, MeetingOutput):
                    public_out = resolved
                else:
                    public_out = map_to_public(
                        resolved,
                        transcript=clean_text,
                        meeting_date_input=meeting_date,
                    )
                job_store.update_job(
                    job_id,
                    stage=JobStage.DONE,
                    status=JobStatus.DONE,
                    progress=1.0,
                    message="Phân tích hoàn tất ngay lập tức (dữ liệu mẫu đã kiểm chứng).",
                    result=public_out,
                )
                return

        # ── Step 0: Preprocessing ──
        if check_cancel():
            return
        job_store.update_job(job_id, stage=JobStage.PREPROCESSING)
        preprocessed = preprocess(clean_text)

        # ── Step 1: Extraction ──
        if check_cancel():
            return
        job_store.update_job(job_id, stage=JobStage.EXTRACTING)
        extractor = Extractor()
        extracted = extractor.extract(preprocessed)

        # ── Step 2: Resolution ──
        if check_cancel():
            return
        job_store.update_job(job_id, stage=JobStage.RESOLVING)
        resolver = Resolver()
        resolved = resolver.resolve(extracted)

        # ── Step 3: Evidence Validation ──
        if check_cancel():
            return
        job_store.update_job(job_id, stage=JobStage.VALIDATING)
        validator = Validator(threshold=threshold)
        validated = validator.validate(resolved, clean_text)

        # ── Step 4: Deterministic Mapping ──
        if check_cancel():
            return
        job_store.update_job(job_id, stage=JobStage.MAPPING)
        public_output = map_to_public(
            validated,
            transcript=clean_text,
            meeting_date_input=meeting_date,
        )

        if check_cancel():
            return

        # ── Complete ──
        job_store.update_job(
            job_id,
            stage=JobStage.DONE,
            status=JobStatus.DONE,
            progress=1.0,
            result=public_output,
        )
        logger.info(f"[PipelineJob] Job '{job_id}' completed successfully.")

    except Exception as exc:
        logger.exception(f"[PipelineJob] Job '{job_id}' failed:")
        err_str = str(exc)
        if "API_KEY" in err_str or "GEMINI_API_KEY" in err_str:
            friendly = "Lỗi xác thực Google Gemini API. Vui lòng cấu hình GEMINI_API_KEY trong file .env."
        elif "ResourceExhausted" in err_str or "429" in err_str:
            friendly = "Gemini API đang bị giới hạn tần suất (Rate limit 429). Vui lòng thử lại sau vài giây."
        elif "timeout" in err_str.lower() or "deadline" in err_str.lower():
            friendly = "Quá thời gian chờ phản hồi từ Gemini API (Timeout). Vui lòng thử lại."
        else:
            friendly = f"Quá trình phân tích gặp sự cố: {type(exc).__name__} ({exc})"

        job_store.update_job(
            job_id,
            stage=JobStage.FAILED,
            status=JobStatus.FAILED,
            error=err_str,
            friendly_error=friendly,
        )
