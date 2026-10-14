"""
Meeting Mind — Configuration
Loads settings from .env file.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

# ── API ──────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
STEP1_MODEL: str = os.getenv("STEP1_MODEL", os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest"))
STEP2_MODEL: str = os.getenv("STEP2_MODEL", os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest"))
TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.1"))
LLM_REQUEST_TIMEOUT: float = float(os.getenv("LLM_REQUEST_TIMEOUT", "60.0"))
MAX_CONTEXT_CHARS: int = int(os.getenv("MAX_CONTEXT_CHARS", "400000"))

# ── Validation ───────────────────────────────────────
FUZZY_MATCH_THRESHOLD: int = int(os.getenv("FUZZY_MATCH_THRESHOLD", "80"))

# ── Cache ────────────────────────────────────────────
CACHE_ENABLED: bool = os.getenv("CACHE_ENABLED", "true").lower() in ("true", "1", "yes")
CACHE_CAPACITY: int = int(os.getenv("CACHE_CAPACITY", "100"))
CACHE_TTL_SECONDS: float = float(os.getenv("CACHE_TTL_SECONDS", "3600.0"))

# ── Server / CORS ────────────────────────────────────
PORT: int = int(os.getenv("PORT", "8000"))
CORS_ORIGINS: list[str] = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080,http://127.0.0.1:8080,http://localhost:8081,http://127.0.0.1:8081",
    ).split(",")
    if origin.strip()
]

# ── Paths ────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
TESTS_DIR = PROJECT_ROOT / "tests"
TRANSCRIPTS_DIR = TESTS_DIR / "transcripts"
EXPECTED_DIR = TESTS_DIR / "expected"
OUTPUT_DIR = PROJECT_ROOT / "output"
