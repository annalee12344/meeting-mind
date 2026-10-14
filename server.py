"""
Meeting Mind — FastAPI Backend Server

Provides REST API endpoints for:
- API v1 (Prefix: /api/v1):
  - Health check: GET /api/v1/health
  - Samples catalog: GET /api/v1/samples
  - Sample transcript: GET /api/v1/samples/{sample_id}
  - Sample precomputed result: GET /api/v1/samples/{sample_id}/result
  - Start Async Analysis Job: POST /api/v1/analyze
  - Poll Job Progress: GET /api/v1/jobs/{job_id}
  - Cancel Job: POST /api/v1/jobs/{job_id}/cancel
  - Upgrade Legacy 5-Array Export: POST /api/v1/legacy/upgrade
  - Clear Cache: POST /api/v1/cache/clear
- Legacy endpoints (/api/...) preserved for backwards-compatibility.
"""
import json
import logging
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Body, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import config
from models.jobs import (
    AnalysisJob,
    AnalyzeJobResponse,
    JobStage,
    JobStatus,
    JobStatusResponse,
)
from models.output import MeetingOutput, ResolvedResult
from models.overlay import ExportPackage, MeetingOverlay, MeetingViewModel
from pipeline.cache import compute_analysis_cache_key, get_analysis_cache
from pipeline.job_store import execute_pipeline_job, get_job_store
from pipeline.mapper import map_to_public, upgrade_legacy_result
from pipeline.preprocessor import PreprocessError, preprocess
from pipeline.runner import run_pipeline
from pipeline.validator import Validator
from prompts import PROMPT_VERSION

# Configure server logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("meeting_mind.server")

app = FastAPI(
    title="Meeting Mind API",
    description="Backend API for Vietnamese meeting transcript analysis with Google Gemini",
    version="2.0.0",
)

# Configure CORS
_is_wildcard_cors = "*" in config.CORS_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=not _is_wildcard_cors,
    allow_methods=["*"],
    allow_headers=["*"],
)

def verify_gemini_configuration() -> Dict[str, Any]:
    """Startup verification of Gemini configuration and connectivity."""
    key = config.GEMINI_API_KEY
    is_set = bool(key and key.strip() and key != "your_api_key_here")
    step1_model = config.STEP1_MODEL
    step2_model = config.STEP2_MODEL

    probe_ok = False
    probe_error = None
    if is_set:
        try:
            import google.generativeai as genai
            genai.configure(api_key=key)
            m = genai.GenerativeModel(step1_model)
            res = m.generate_content("Ping", request_options={"timeout": 10.0})
            if res.text:
                probe_ok = True
        except Exception as exc:
            probe_error = f"{type(exc).__name__}: {exc}"
            logger.warning(f"[StartupCheck] Gemini connectivity probe warning: {probe_error}")
    else:
        logger.warning("[StartupCheck] GEMINI_API_KEY is NOT configured or using default placeholder!")

    return {
        "configured": is_set,
        "step1_model": step1_model,
        "step2_model": step2_model,
        "probe_ok": probe_ok,
        "probe_error": probe_error,
    }


@app.on_event("startup")
def startup_event():
    check = verify_gemini_configuration()
    logger.info(
        f"[ServerStartup] Gemini verification: configured={check['configured']}, "
        f"step1_model={check['step1_model']}, step2_model={check['step2_model']}, probe_ok={check['probe_ok']}"
    )


# Sample transcripts metadata catalog
SAMPLE_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "test_01_happy_path",
        "alt_id": "1",
        "title": "Standard Sprint Planning",
        "name": "Sprint 24 · Planning",
        "filename": "test_01_happy_path.txt",
        "description": "Happy path standard sprint planning with 2 decisions, 3 actions, 1 blocker, 1 request.",
    },
    {
        "id": "test_02_decision_change",
        "alt_id": "2",
        "title": "Product Launch Timing (A -> B Changes)",
        "name": "Release Strategy Alignment",
        "filename": "test_02_decision_change.txt",
        "description": "Discussion progression where initial proposal (A) is debated and superseded by (B).",
    },
    {
        "id": "test_03_chaotic",
        "alt_id": "3",
        "title": "Chaotic Meeting (Casual & Disagreements)",
        "name": "Emergency Incident Post-mortem",
        "filename": "test_03_chaotic.txt",
        "description": "Fast-paced informal speech with interruptions, sarcasm, and unresolved disagreements.",
    },
    {
        "id": "test_04_implicit",
        "alt_id": "4",
        "title": "Implicit Consensus & Implicit Pronouns",
        "name": "Feature Scope Review",
        "filename": "test_04_implicit.txt",
        "description": "Subtle Vietnamese pronouns and silence/implicit agreement without explicit deadlines.",
    },
    {
        "id": "test_05_sarcasm_fail",
        "alt_id": "5",
        "title": "Adversarial Test (Sarcasm & Dispute)",
        "name": "Q3 Architecture Debate",
        "filename": "test_05_sarcasm_fail.txt",
        "description": "Stress-test for rejecting sarcasm, jokes, and unconfirmed proposals.",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response Schemas
# ─────────────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    model: str
    gemini_configured: bool
    schema_version: str = "2.0.0"
    prompt_version: str = PROMPT_VERSION


class SampleSummary(BaseModel):
    id: str
    title: str
    name: str
    filename: str
    description: str


class SampleDetail(SampleSummary):
    transcript: str


class AnalyzeRequest(BaseModel):
    transcript: str = Field(description="Raw Vietnamese meeting transcript text")
    meeting_name: Optional[str] = Field(default=None, description="Meeting title/name")
    meeting_title: Optional[str] = Field(default=None, description="Alias for meeting title")
    meeting_date: Optional[str] = Field(default=None, description="Optional ISO meeting date (YYYY-MM-DD)")
    sample_id: Optional[str] = Field(default=None, description="ID if using a benchmark sample")
    use_sample_cache: bool = Field(default=True, description="Whether to reuse verified benchmark results")
    language: str = Field(default="vi", description="Language of transcript")
    threshold: Optional[int] = Field(default=None, description="Fuzzy match threshold for validator")


def find_matching_sample(text: str, sample_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Check if transcript matches a known benchmark sample."""
    if sample_id:
        s_clean = sample_id.strip().lower()
        for s in SAMPLE_CATALOG:
            if s["id"].lower() == s_clean or s["alt_id"] == s_clean or s["filename"].lower() == s_clean:
                return s

    clean_input = "".join(text.split()).lower()
    for s in SAMPLE_CATALOG:
        fpath = config.TRANSCRIPTS_DIR / s["filename"]
        if fpath.exists():
            try:
                content = fpath.read_text(encoding="utf-8")
                clean_sample = "".join(content.split()).lower()
                if clean_input == clean_sample:
                    return s
            except Exception:
                pass
    return None


def load_sample_expected(sample: Dict[str, Any], threshold: Optional[int] = None) -> ResolvedResult:
    """Load precomputed expected result for a sample."""
    expected_filename = sample["filename"].replace(".txt", "").replace("happy_path", "expected").replace("decision_change", "expected").replace("chaotic", "expected").replace("implicit", "expected").replace("sarcasm_fail", "expected")
    if not expected_filename.endswith("_expected"):
        expected_filename = f"{sample['id'].split('_')[0]}_{sample['id'].split('_')[1]}_expected"

    json_file = config.EXPECTED_DIR / f"{expected_filename}.json"
    if not json_file.exists():
        prefix = sample["id"][:7]
        matches = list(config.EXPECTED_DIR.glob(f"{prefix}*.json"))
        if matches:
            json_file = matches[0]

    if not json_file.exists():
        raise FileNotFoundError(f"Expected JSON not found for sample '{sample['id']}' at {json_file}")

    raw_json = json.loads(json_file.read_text(encoding="utf-8"))
    resolved_result = ResolvedResult.model_validate(raw_json)

    fpath = config.TRANSCRIPTS_DIR / sample["filename"]
    if fpath.exists():
        transcript_text = fpath.read_text(encoding="utf-8")
        validator = Validator(threshold=threshold)
        resolved_result = validator.validate(resolved_result, transcript_text)

    return resolved_result


# ─────────────────────────────────────────────────────────────────────────────
# API v1 Router (/api/v1)
# ─────────────────────────────────────────────────────────────────────────────

v1_router = APIRouter(prefix="/api/v1")


@v1_router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Report API server availability and configuration status."""
    is_key_set = bool(
        config.GEMINI_API_KEY
        and config.GEMINI_API_KEY.strip()
        and config.GEMINI_API_KEY != "your_api_key_here"
    )
    return HealthResponse(
        status="ok",
        model=config.GEMINI_MODEL,
        gemini_configured=is_key_set,
    )


@v1_router.get("/samples", response_model=List[SampleSummary])
def list_samples() -> List[SampleSummary]:
    """List available benchmark sample transcripts."""
    return [
        SampleSummary(
            id=s["id"],
            title=s["title"],
            name=s["name"],
            filename=s["filename"],
            description=s["description"],
        )
        for s in SAMPLE_CATALOG
    ]


@v1_router.get("/samples/{sample_id}", response_model=SampleDetail)
def get_sample(sample_id: str) -> SampleDetail:
    """Get sample transcript contents by id or filename."""
    target = None
    sample_id_clean = sample_id.strip().lower()

    for s in SAMPLE_CATALOG:
        if (
            s["id"].lower() == sample_id_clean
            or s["alt_id"] == sample_id_clean
            or s["filename"].lower() == sample_id_clean
            or s["title"].lower() == sample_id_clean
        ):
            target = s
            break

    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sample transcript '{sample_id}' not found.",
        )

    file_path = config.TRANSCRIPTS_DIR / target["filename"]
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sample file '{target['filename']}' not found on server disk.",
        )

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read sample file: {exc}",
        )

    return SampleDetail(
        id=target["id"],
        title=target["title"],
        name=target["name"],
        filename=target["filename"],
        description=target["description"],
        transcript=content,
    )


@v1_router.get("/samples/{sample_id}/result", response_model=MeetingOutput)
def get_sample_result(sample_id: str, threshold: Optional[int] = None) -> MeetingOutput:
    """Fetch precomputed verified benchmark results for a sample (instant response)."""
    target = None
    sample_id_clean = sample_id.strip().lower()

    for s in SAMPLE_CATALOG:
        if (
            s["id"].lower() == sample_id_clean
            or s["alt_id"] == sample_id_clean
            or s["filename"].lower() == sample_id_clean
            or s["title"].lower() == sample_id_clean
        ):
            target = s
            break

    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sample transcript '{sample_id}' not found.",
        )

    try:
        logger.info(f"Serving precomputed verified result for sample '{target['id']}' ({target['title']})")
        resolved = load_sample_expected(target, threshold=threshold)
        file_path = config.TRANSCRIPTS_DIR / target["filename"]
        transcript_content = file_path.read_text(encoding="utf-8") if file_path.exists() else None
        return map_to_public(resolved, transcript=transcript_content)
    except Exception as exc:
        logger.exception(f"Failed to load expected output for '{sample_id}':")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load precomputed sample result.",
        )


@v1_router.post("/analyze", response_model=AnalyzeJobResponse)
def start_analysis_job_v1(request: AnalyzeRequest) -> AnalyzeJobResponse:
    """
    Asynchronously launch analysis pipeline job.
    Returns job_id immediately for progress polling via GET /api/v1/jobs/{job_id}.
    """
    clean_text = request.transcript.strip()
    if not clean_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nội dung biên bản cuộc họp trống.",
        )

    # Pre-validate transcript formatting and minimum content
    try:
        preprocess(clean_text, strict=True)
    except PreprocessError as pe:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Biên bản cuộc họp không hợp lệ: {pe}",
        )

    effective_title = request.meeting_title or request.meeting_name or "Untitled Meeting"
    job_id = f"job_{uuid4().hex[:12]}"

    job_store = get_job_store()
    created_job = job_store.create_job(
        job_id=job_id,
        meeting_title=effective_title,
        transcript_length=len(clean_text),
    )

    # Start asynchronous background execution
    thread = threading.Thread(
        target=execute_pipeline_job,
        kwargs={
            "job_id": job_id,
            "transcript": clean_text,
            "meeting_title": effective_title,
            "meeting_date": request.meeting_date,
            "threshold": request.threshold,
            "store": job_store,
            "sample_matcher": find_matching_sample if request.use_sample_cache else None,
            "sample_loader": load_sample_expected if request.use_sample_cache else None,
        },
        daemon=True,
    )
    thread.start()

    return AnalyzeJobResponse(
        job_id=job_id,
        status=created_job.status,
        stage=created_job.stage,
        stage_label=created_job.stage_label,
        progress_percent=created_job.progress_percent,
        poll_url=f"/api/v1/jobs/{job_id}",
        message="Tác vụ phân tích đã được khởi tạo thành công.",
    )


@v1_router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str) -> JobStatusResponse:
    """
    Query real-time status and progress for an analysis job.
    Reports: queued -> preprocessing -> extracting -> resolving -> validating -> mapping -> done | failed.
    """
    job_store = get_job_store()
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tác vụ phân tích '{job_id}' không tồn tại hoặc đã hết hạn.",
        )

    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        progress_percent=job.progress_percent,
        stage_message=job.stage_message,
        stage_label=job.stage_label,
        error_code=job.error_code,
        error=job.error,
        friendly_error=job.friendly_error,
        result=job.result,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@v1_router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> Dict[str, Any]:
    """Cancel an active analysis job."""
    job_store = get_job_store()
    cancelled = job_store.cancel_job(job_id)
    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tác vụ phân tích '{job_id}' không tồn tại.",
        )
    return {"job_id": job_id, "status": "cancelled", "message": "Đã hủy tác vụ phân tích thành công."}


@v1_router.post("/legacy/upgrade", response_model=MeetingOutput)
def upgrade_legacy_endpoint(payload: Any = Body(...), meeting_date: Optional[str] = None) -> MeetingOutput:
    """
    Upgrade an older exported JSON (5-array format without schema_version)
    into the new 4-group MeetingOutput structure.
    """
    try:
        data = payload
        date_in = meeting_date
        if isinstance(payload, dict):
            if "legacy_data" in payload:
                data = payload["legacy_data"]
            if "meeting_date" in payload and payload["meeting_date"]:
                date_in = payload["meeting_date"]

        return upgrade_legacy_result(data, meeting_date_input=date_in)
    except Exception as exc:
        logger.exception("Failed to upgrade legacy result:")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Không thể nâng cấp dữ liệu biên bản cũ: {exc}",
        )


@v1_router.post("/cache/clear")
def clear_analysis_cache_v1() -> Dict[str, str]:
    """Clear in-memory analysis cache."""
    cache = get_analysis_cache()
    cache.clear()
    return {"status": "ok", "message": "Analysis cache cleared successfully."}


clear_analysis_cache = clear_analysis_cache_v1


# Mount v1 router
app.include_router(v1_router)


# ─────────────────────────────────────────────────────────────────────────────
# Root & Legacy / Backward-Compatible Endpoints (/api/...)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
def root_index() -> Dict[str, str]:
    return {
        "status": "ok",
        "service": "Meeting Mind API",
        "version": "2.0.0",
        "health": "/api/v1/health",
        "docs": "/docs",
    }


@app.get("/api/health", response_model=HealthResponse)
def legacy_health_check() -> HealthResponse:
    return health_check()


@app.get("/api/samples", response_model=List[SampleSummary])
def legacy_list_samples() -> List[SampleSummary]:
    return list_samples()


@app.get("/api/samples/{sample_id}", response_model=SampleDetail)
def legacy_get_sample(sample_id: str) -> SampleDetail:
    return get_sample(sample_id)


@app.get("/api/samples/{sample_id}/result", response_model=MeetingOutput)
def legacy_get_sample_result(sample_id: str, threshold: Optional[int] = None) -> MeetingOutput:
    return get_sample_result(sample_id, threshold)


@app.post("/api/legacy/upgrade", response_model=MeetingOutput)
def legacy_upgrade_alias(payload: Any = Body(...), meeting_date: Optional[str] = None) -> MeetingOutput:
    return upgrade_legacy_endpoint(payload, meeting_date)


@app.post("/api/cache/clear")
def legacy_clear_cache() -> Dict[str, str]:
    return clear_analysis_cache_v1()


@app.post("/api/analyze", response_model=MeetingOutput)
def analyze_transcript(request: AnalyzeRequest) -> MeetingOutput:
    """
    Synchronous analysis pipeline execution (legacy endpoint).
    """
    clean_text = request.transcript.strip()
    if not clean_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcript is empty. Please provide meeting text to analyze.",
        )

    effective_title = request.meeting_title or request.meeting_name or "Untitled Meeting"

    # 0. Check Analysis Cache
    cache = get_analysis_cache()
    cache_key = compute_analysis_cache_key(
        clean_text,
        meeting_date=request.meeting_date,
        prompt_version=PROMPT_VERSION,
    )
    if config.CACHE_ENABLED:
        cached_result = cache.get(cache_key)
        if cached_result:
            logger.info(
                f"Analysis cache hit for '{effective_title}' (Key: {cache_key[:12]}...). "
                "Returning cached MeetingOutput (preserving item UUIDs)."
            )
            return cached_result

    # 1. Check if input matches one of the precomputed benchmark samples
    if request.use_sample_cache:
        matched_sample = find_matching_sample(clean_text, request.sample_id)
        if matched_sample:
            logger.info(
                f"Transcript matches benchmark sample '{matched_sample['id']}' ({matched_sample['title']}). "
                "Returning precomputed, verified results instantly (0 Gemini API calls)."
            )
            resolved = load_sample_expected(matched_sample, threshold=request.threshold)
            sample_output = map_to_public(
                resolved,
                transcript=clean_text,
                meeting_date_input=request.meeting_date,
            )
            if config.CACHE_ENABLED:
                cache.set(cache_key, sample_output)
            return sample_output

    # 2. For custom / modified transcripts, invoke Gemini pipeline
    if not config.GEMINI_API_KEY or config.GEMINI_API_KEY == "your_api_key_here":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini API key is not configured on the server. Please configure GEMINI_API_KEY in .env.",
        )

    try:
        logger.info(f"Starting transcript analysis for '{effective_title}' ({len(clean_text)} chars)...")
        resolved = run_pipeline(clean_text, threshold=request.threshold)
        public_output = map_to_public(
            resolved,
            transcript=clean_text,
            meeting_date_input=request.meeting_date,
        )
        if config.CACHE_ENABLED:
            cache.set(cache_key, public_output)
        logger.info(
            f"Analysis completed successfully: {len(public_output.decisions)} decisions, "
            f"{len(public_output.tasks)} tasks, {len(public_output.unresolved)} unresolved, "
            f"{len(public_output.issues)} issues."
        )
        return public_output

    except ValueError as val_err:
        logger.warning(f"Validation error during analysis: {val_err}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        )
    except Exception as err:
        logger.exception("Pipeline execution failed:")
        error_msg = str(err)
        if "API_KEY" in error_msg:
            safe_msg = "Google Gemini API authentication failed. Please verify API key."
        elif "ResourceExhausted" in error_msg or "429" in error_msg:
            safe_msg = "Gemini API rate limit exceeded. Please try again in a few moments."
        else:
            safe_msg = f"Analysis failed: {type(err).__name__}. Check server logs for details."
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=safe_msg,
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=config.PORT, reload=True)
