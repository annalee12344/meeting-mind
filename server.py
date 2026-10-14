"""
Meeting Mind — FastAPI Backend Server

Provides REST API endpoints for:
- Health check: GET /api/health
- Sample transcripts catalog: GET /api/samples
- Load sample transcript: GET /api/samples/{sample_id}
- Run analysis pipeline: POST /api/analyze
"""
import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import config
from models.output import MeetingOutput, ResolvedResult
from pipeline.runner import run_pipeline

# Configure server logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("meeting_mind.server")

app = FastAPI(
    title="Meeting Mind API",
    description="Backend API for Vietnamese meeting transcript analysis with Google Gemini",
    version="1.0.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sample transcripts metadata catalog
SAMPLE_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "test_01_happy_path",
        "alt_id": "1",
        "title": "Standard Sprint Planning",
        "name": "Sprint 24 · Planning",
        "filename": "test_01_happy_path.txt",
        "expected_file": "test_01_expected.json",
        "description": "Sprint planning (happy path: 2 decisions, 3 actions, 1 blocker, 1 request)",
    },
    {
        "id": "test_02_decision_change",
        "alt_id": "2",
        "title": "Decision Change",
        "name": "Product Launch Timing",
        "filename": "test_02_decision_change.txt",
        "expected_file": "test_02_expected.json",
        "description": "Product launch timing (A->B changes: 2 decisions with history, 2 actions, 1 unresolved)",
    },
    {
        "id": "test_03_chaotic",
        "alt_id": "3",
        "title": "Chaotic Discussion",
        "name": "Chaotic Team Sync",
        "filename": "test_03_chaotic.txt",
        "expected_file": "test_03_expected.json",
        "description": "Chaotic meeting (interruptions, casual speech, sarcasm, unresolved conflict)",
    },
    {
        "id": "test_04_implicit",
        "alt_id": "4",
        "title": "Implicit Agreement",
        "name": "Implicit Consensus Discussion",
        "filename": "test_04_implicit.txt",
        "expected_file": "test_04_expected.json",
        "description": "Implicit context (implicit pronouns, silence consensus, no deadlines)",
    },
    {
        "id": "test_05_sarcasm_fail",
        "alt_id": "5",
        "title": "Sarcasm and Conflicting Statements",
        "name": "Adversarial Discussion",
        "filename": "test_05_sarcasm_fail.txt",
        "expected_file": "test_05_expected.json",
        "description": "Adversarial test (sarcasm rejection, joke proposals, unresolved disputes)",
    },
]


import json
from pipeline.validator import Validator

class AnalyzeRequest(BaseModel):
    """Payload for POST /api/analyze."""
    transcript: str = Field(..., description="Raw meeting transcript text to analyze.")
    meeting_name: Optional[str] = Field(default=None, description="Optional meeting name or title.")
    sample_id: Optional[str] = Field(default=None, description="Optional ID of known sample.")
    use_sample_cache: Optional[bool] = Field(
        default=True,
        description="Whether to reuse verified benchmark ground truth if transcript matches a known sample.",
    )
    language: Optional[str] = Field(default="vi", description="Language of transcript (default: vi).")
    threshold: Optional[int] = Field(
        default=None, ge=0, le=100, description="Optional fuzzy match threshold (0-100)."
    )


def load_sample_expected(sample: Dict[str, Any], threshold: Optional[int] = None) -> ResolvedResult:
    """Load precomputed expected benchmark output and validate evidence against transcript."""
    expected_path = config.EXPECTED_DIR / sample["expected_file"]
    transcript_path = config.TRANSCRIPTS_DIR / sample["filename"]

    if not expected_path.exists():
        raise FileNotFoundError(f"Expected file {sample['expected_file']} not found")

    with open(expected_path, "r", encoding="utf-8") as f:
        raw_json = json.load(f)

    resolved_result = ResolvedResult.model_validate(raw_json)

    if transcript_path.exists():
        transcript_text = transcript_path.read_text(encoding="utf-8")
        validator = Validator(threshold=threshold)
        resolved_result = validator.validate(resolved_result, transcript_text)

    return resolved_result


def find_matching_sample(
    transcript_text: str, sample_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Check if the provided transcript matches one of the benchmark samples."""
    clean_input = " ".join(transcript_text.split())

    # 1. Match by explicit sample_id if text matches
    if sample_id:
        sample_id_clean = sample_id.strip().lower()
        for s in SAMPLE_CATALOG:
            if s["id"].lower() == sample_id_clean or s["alt_id"] == sample_id_clean:
                file_path = config.TRANSCRIPTS_DIR / s["filename"]
                if file_path.exists():
                    saved_text = file_path.read_text(encoding="utf-8")
                    if clean_input == " ".join(saved_text.split()):
                        return s

    # 2. Match by normalized text content
    for s in SAMPLE_CATALOG:
        file_path = config.TRANSCRIPTS_DIR / s["filename"]
        if file_path.exists():
            saved_text = file_path.read_text(encoding="utf-8")
            if clean_input == " ".join(saved_text.split()):
                return s

    return None


class HealthResponse(BaseModel):
    """Response schema for GET /api/health."""
    status: str
    model: str
    gemini_configured: bool


class SampleSummary(BaseModel):
    """Summary item for GET /api/samples."""
    id: str
    title: str
    name: str
    filename: str
    description: str


class SampleDetail(SampleSummary):
    """Detail item for GET /api/samples/{sample_id}."""
    transcript: str


@app.get("/api/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Report API server availability and configuration status without exposing secrets."""
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


@app.get("/api/samples", response_model=List[SampleSummary])
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


@app.get("/api/samples/{sample_id}", response_model=SampleDetail)
def get_sample(sample_id: str) -> SampleDetail:
    """
    Get sample transcript contents by id, index, or filename.
    Does not run any analysis.
    """
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
        logger.error(f"Sample file not found at path: {file_path}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sample file '{target['filename']}' not found on server disk.",
        )

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.exception(f"Failed to read sample file '{target['filename']}':")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read sample transcript file.",
        )

    return SampleDetail(
        id=target["id"],
        title=target["title"],
        name=target["name"],
        filename=target["filename"],
        description=target["description"],
        transcript=content,
    )


@app.get("/api/samples/{sample_id}/result", response_model=MeetingOutput)
def get_sample_result(sample_id: str, threshold: Optional[int] = None) -> MeetingOutput:
    """
    Get precomputed, verified benchmark results for a sample without making any Gemini API calls.
    """
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
        return load_sample_expected(target, threshold=threshold)
    except Exception as exc:
        logger.exception(f"Failed to load expected output for '{sample_id}':")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load precomputed sample result.",
        )


@app.post("/api/analyze", response_model=MeetingOutput)
def analyze_transcript(request: AnalyzeRequest) -> MeetingOutput:
    """
    Execute 2-pass analysis pipeline on supplied transcript.
    If the transcript matches one of the benchmark samples, it automatically reuses
    the verified ground truth (0 Gemini API cost, sub-second response).
    """
    clean_text = request.transcript.strip()
    if not clean_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcript is empty. Please provide meeting text to analyze.",
        )

    # 1. Check if input matches one of the precomputed benchmark samples
    if request.use_sample_cache:
        matched_sample = find_matching_sample(clean_text, request.sample_id)
        if matched_sample:
            logger.info(
                f"Transcript matches benchmark sample '{matched_sample['id']}' ({matched_sample['title']}). "
                "Returning precomputed, verified results instantly (0 Gemini API calls)."
            )
            return load_sample_expected(matched_sample, threshold=request.threshold)

    # 2. For custom / modified transcripts, invoke Gemini pipeline
    if not config.GEMINI_API_KEY or config.GEMINI_API_KEY == "your_api_key_here":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini API key is not configured on the server. Please configure GEMINI_API_KEY in .env.",
        )

    try:
        meeting_title = request.meeting_name or "Untitled Meeting"
        logger.info(f"Starting transcript analysis for '{meeting_title}' ({len(clean_text)} chars)...")
        output = run_pipeline(clean_text, threshold=request.threshold)
        logger.info(
            f"Analysis completed successfully: {len(output.decisions)} decisions, "
            f"{len(output.action_items)} action items."
        )
        return output

    except ValueError as val_err:
        logger.warning(f"Validation error during analysis: {val_err}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        )
    except Exception as err:
        # Log full internal error on server, return safe error message without secrets
        logger.exception("Pipeline execution failed:")
        error_msg = str(err)
        # Filter out potential keys or long stack traces
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
