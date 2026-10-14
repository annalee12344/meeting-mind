"""
Job Models for Meeting Mind Async Analysis System.

Supports tracking step-by-step progress for asynchronous analysis requests:
queued -> preprocessing -> extracting -> resolving -> validating -> mapping -> done | failed.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from models.output import MeetingOutput


class JobStage(str, Enum):
    """Current processing stage of the analysis job."""
    QUEUED = "queued"
    PREPROCESSING = "preprocessing"
    EXTRACTING = "extracting"
    RESOLVING = "resolving"
    VALIDATING = "validating"
    MAPPING = "mapping"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStatus(str, Enum):
    """High-level status of the analysis job."""
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


STAGE_PROGRESS_MAP: dict[JobStage, float] = {
    JobStage.QUEUED: 0.05,
    JobStage.PREPROCESSING: 0.15,
    JobStage.EXTRACTING: 0.45,
    JobStage.RESOLVING: 0.75,
    JobStage.VALIDATING: 0.90,
    JobStage.MAPPING: 0.95,
    JobStage.DONE: 1.0,
    JobStage.FAILED: 1.0,
    JobStage.CANCELLED: 1.0,
}

STAGE_LABELS_VI: dict[JobStage, str] = {
    JobStage.QUEUED: "Đang xếp hàng chờ xử lý...",
    JobStage.PREPROCESSING: "Bước 0: Tiền xử lý và gán mã phát biểu [U001]...",
    JobStage.EXTRACTING: "Bước 1: Trích xuất các phát biểu và vai trò hội thoại (Gemini)...",
    JobStage.RESOLVING: "Bước 2: Phân nhóm chủ đề và theo dõi tiến trình thay đổi (Gemini)...",
    JobStage.VALIDATING: "Bước 3: Xác minh bằng chứng trích dẫn với câu thoại gốc (RapidFuzz)...",
    JobStage.MAPPING: "Bước 4: Ánh xạ cấu trúc dữ liệu theo 4 nhóm chuẩn...",
    JobStage.DONE: "Phân tích hoàn tất thành công!",
    JobStage.FAILED: "Phân tích thất bại.",
    JobStage.CANCELLED: "Đã hủy tác vụ phân tích.",
}


class AnalysisJob(BaseModel):
    """Complete internal representation of an analysis job."""
    job_id: str
    meeting_title: str = "Cuộc họp"
    transcript_length: int = 0
    status: JobStatus = JobStatus.PENDING
    stage: JobStage = JobStage.QUEUED
    progress: float = 0.05
    progress_percent: int = 5
    stage_message: str = "Đang xếp hàng chờ xử lý..."
    stage_label: str = "Đang xếp hàng chờ xử lý..."
    error_code: Optional[str] = None
    error: Optional[str] = None
    friendly_error: Optional[str] = None
    result: Optional[MeetingOutput] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AnalyzeJobResponse(BaseModel):
    """Immediate response returned by POST /api/v1/analyze."""
    job_id: str
    status: JobStatus = JobStatus.PENDING
    stage: JobStage = JobStage.QUEUED
    stage_label: str = "Đang xếp hàng chờ xử lý..."
    progress_percent: int = 5
    poll_url: Optional[str] = None
    message: str = "Tác vụ phân tích đã được khởi tạo."


class JobStatusResponse(BaseModel):
    """Response returned by GET /api/v1/jobs/{job_id} reporting progress and result."""
    job_id: str
    status: JobStatus
    stage: JobStage
    progress: float
    progress_percent: int = 5
    stage_message: str
    stage_label: str
    error_code: Optional[str] = None
    error: Optional[str] = None
    friendly_error: Optional[str] = None
    result: Optional[MeetingOutput] = None
    created_at: str
    updated_at: str
